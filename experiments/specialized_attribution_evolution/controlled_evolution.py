"""专家审核驱动的九类性质归属受控自进化。

该工具只生成和编译版本化记忆，不直接修改生产词表、Schema 或抽取结果。
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml


SCHEMA_VERSION = "specialized_attribution_memory.v1"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_gold(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        row = json.loads(line)
        if not row.get("case_id") or not row.get("ref_no") or not row.get("table_id"):
            raise ValueError(f"Gold 第 {line_number} 行缺少 case/ref/table")
        rows.append(row)
    return rows


def artifact_path(root: Path, case: Mapping[str, Any]) -> Path:
    return (
        root
        / str(case["ref_no"])
        / f"{case['table_id']}_attribution_agent.json"
    )


def _norm(value: Any) -> str:
    return re.sub(r"[^0-9a-z]+", "", str(value or "").casefold())


def _semantic_match(expected: Mapping[str, Any], predicted: Mapping[str, Any]) -> bool:
    if expected.get("anchor_cell_id") not in set(predicted.get("source_cell_ids") or []):
        return False
    for key in ("decision", "source_field", "semantic_label"):
        if expected.get(key) != predicted.get(key):
            return False
    expected_variant = expected.get("variant")
    return expected_variant is None or expected_variant == predicted.get("variant")


def score_case(case: Mapping[str, Any], artifact: Mapping[str, Any]) -> dict[str, Any]:
    response = artifact.get("response") or {}
    predicted_semantics = list(response.get("semantic_assignments") or [])
    expected_semantics = list(case.get("expected_semantics") or [])
    used_predictions: set[int] = set()
    missing = []
    for expected in expected_semantics:
        match_index = next(
            (
                index for index, predicted in enumerate(predicted_semantics)
                if index not in used_predictions
                and _semantic_match(expected, predicted)
            ),
            None,
        )
        if match_index is None:
            missing.append(expected)
        else:
            used_predictions.add(match_index)
    specialized_predictions = {
        index for index, item in enumerate(predicted_semantics)
        if item.get("decision") == "specialized"
    }
    semantic_tp = len(expected_semantics) - len(missing)
    semantic_fp = len(specialized_predictions - used_predictions)
    semantic_fn = len(missing)

    predicted_samples: dict[str, list[Mapping[str, Any]]] = {}
    for item in response.get("sample_assignments") or []:
        predicted_samples.setdefault(_norm(item.get("sample_label_raw")), []).append(item)
    sample_errors = []
    sample_correct = 0
    expected_samples = list(case.get("expected_samples") or [])
    for expected in expected_samples:
        candidates = predicted_samples.get(_norm(expected.get("sample_label_raw"))) or []
        matched = any(
            item.get("status") == expected.get("status")
            and (
                expected.get("sample_id") is None
                or item.get("sample_id") == expected.get("sample_id")
            )
            for item in candidates
        )
        if matched:
            sample_correct += 1
        else:
            sample_errors.append(expected)

    out_of_scope_count = sum(
        item.get("decision") == "not_in_specialized_scope"
        for item in predicted_semantics
    )
    expected_out_of_scope_min = int(case.get("expected_out_of_scope_min") or 0)
    return {
        "case_id": case["case_id"],
        "split": case.get("split"),
        "ref_no": case["ref_no"],
        "table_id": case["table_id"],
        "agent_status": artifact.get("status"),
        "semantic_tp": semantic_tp,
        "semantic_fp": semantic_fp,
        "semantic_fn": semantic_fn,
        "missing_semantics": missing,
        "sample_correct": sample_correct,
        "sample_total": len(expected_samples),
        "sample_errors": sample_errors,
        "out_of_scope_count": out_of_scope_count,
        "out_of_scope_expected": expected_out_of_scope_min > 0,
        "out_of_scope_pass": out_of_scope_count >= expected_out_of_scope_min,
        "requires_human_review": bool(response.get("requires_human_review")),
    }


def aggregate(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    tp = sum(int(row.get("semantic_tp") or 0) for row in rows)
    fp = sum(int(row.get("semantic_fp") or 0) for row in rows)
    fn = sum(int(row.get("semantic_fn") or 0) for row in rows)
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    sample_correct = sum(int(row.get("sample_correct") or 0) for row in rows)
    sample_total = sum(int(row.get("sample_total") or 0) for row in rows)
    return {
        "cases": len(rows),
        "failed_agent_runs": sum(row.get("agent_status") != "succeeded" for row in rows),
        "semantic_tp": tp,
        "semantic_fp": fp,
        "semantic_fn": fn,
        "semantic_precision": round(precision, 4),
        "semantic_recall": round(recall, 4),
        "semantic_f1": round(f1, 4),
        "sample_binding_accuracy": round(
            sample_correct / sample_total, 4
        ) if sample_total else 1.0,
        "out_of_scope_cases_passed": sum(
            bool(row.get("out_of_scope_expected"))
            and bool(row.get("out_of_scope_pass"))
            for row in rows
        ),
        "out_of_scope_cases": sum(
            bool(row.get("out_of_scope_expected")) for row in rows
        ),
    }


def score_root(
    gold: list[dict[str, Any]],
    output_root: Path,
    *,
    split: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected = [row for row in gold if split is None or row.get("split") == split]
    rows = [
        score_case(case, read_json(artifact_path(output_root, case)))
        for case in selected
    ]
    return rows, aggregate(rows)


def propose_updates(
    *,
    gold_path: Path,
    baseline_root: Path,
    output_path: Path,
) -> Path:
    gold = load_gold(gold_path)
    development = [row for row in gold if row.get("split") == "development"]
    scored, metrics = score_root(gold, baseline_root, split="development")
    scores = {row["case_id"]: row for row in scored}
    proposals = []
    seen: set[str] = set()
    for case in development:
        score = scores[case["case_id"]]
        issue = (
            "baseline_error"
            if score["semantic_fn"] or score["semantic_fp"] or score["sample_errors"]
            else "verified_generalizable_pattern"
        )
        for pattern in case.get("memory_patterns") or []:
            pattern_id = str(pattern.get("pattern_id") or "")
            if not pattern_id or pattern_id in seen:
                continue
            seen.add(pattern_id)
            proposals.append({
                "proposal_id": f"proposal_{len(proposals) + 1:03d}",
                "pattern_id": pattern_id,
                "source_case_ids": [case["case_id"]],
                "selection_reason": issue,
                "target": "agent_retrieval_memory",
                "pattern": pattern,
                "automatic_application_allowed": False,
            })
    payload = {
        "schema_version": "specialized_evolution_proposals.v1",
        "gold_source": str(gold_path),
        "development_metrics": metrics,
        "development_case_ids": [row["case_id"] for row in development],
        "proposals": proposals,
    }
    write_json(output_path, payload)
    return output_path


def compile_approved_memory(
    *,
    proposals_path: Path,
    reviews_path: Path,
    output_path: Path,
) -> Path:
    proposals = read_json(proposals_path)
    reviews = read_json(reviews_path)
    decisions = {
        str(item.get("pattern_id")): item
        for item in reviews.get("decisions") or []
        if isinstance(item, Mapping)
    }
    approved = []
    rejected = []
    for proposal in proposals.get("proposals") or []:
        decision = decisions.get(str(proposal.get("pattern_id"))) or {}
        if decision.get("decision") == "approved":
            approved.append({
                **dict(proposal["pattern"]),
                "source_case_ids": proposal.get("source_case_ids") or [],
                "review_note": decision.get("note"),
            })
        else:
            rejected.append({
                "pattern_id": proposal.get("pattern_id"),
                "decision": decision.get("decision") or "not_reviewed",
            })
    payload = {
        "schema_version": SCHEMA_VERSION,
        "version": "pilot-v1",
        "production_authoritative": False,
        "review_scope": reviews.get("review_scope"),
        "approved_patterns": approved,
        "rejected_or_pending": rejected,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return output_path


def evaluate_versions(
    *,
    gold_path: Path,
    baseline_root: Path,
    evolved_root: Path,
    manifest_path: Path,
    output_dir: Path,
) -> Path:
    gold = load_gold(gold_path)
    manifest = read_json(manifest_path)
    baseline_rows, baseline = score_root(gold, baseline_root, split="frozen_test")
    evolved_rows, evolved = score_root(gold, evolved_root, split="frozen_test")
    by_case_baseline = {row["case_id"]: row for row in baseline_rows}
    by_case_evolved = {row["case_id"]: row for row in evolved_rows}
    negative_case_ids = {
        row["case_id"]
        for row in gold
        if row.get("split") == "frozen_test" and not row.get("expected_semantics")
    }
    evolved_negative_fp = sum(
        by_case_evolved[case_id]["semantic_fp"] for case_id in negative_case_ids
    )
    guardrail_config = manifest.get("guardrails") or {}
    checks = {
        "semantic_f1_not_worse": evolved["semantic_f1"] >= baseline["semantic_f1"],
        "sample_binding_not_worse": (
            evolved["sample_binding_accuracy"] >= baseline["sample_binding_accuracy"]
        ),
        "no_failed_agent_runs": (
            evolved["failed_agent_runs"]
            <= int(guardrail_config.get("maximum_failed_agent_runs") or 0)
        ),
        "negative_control_false_positive_guardrail": (
            evolved_negative_fp
            <= int(
                guardrail_config.get(
                    "maximum_specialized_false_positives_on_negative_control"
                ) or 0
            )
        ),
    }
    report = {
        "schema_version": "specialized_evolution_evaluation.v1",
        "experiment_id": manifest.get("experiment_id"),
        "scope": "five-table engineering pilot; not publication-grade evidence",
        "baseline": baseline,
        "evolved": evolved,
        "delta": {
            "semantic_precision": round(
                evolved["semantic_precision"] - baseline["semantic_precision"], 4
            ),
            "semantic_recall": round(
                evolved["semantic_recall"] - baseline["semantic_recall"], 4
            ),
            "semantic_f1": round(
                evolved["semantic_f1"] - baseline["semantic_f1"], 4
            ),
            "sample_binding_accuracy": round(
                evolved["sample_binding_accuracy"]
                - baseline["sample_binding_accuracy"], 4
            ),
        },
        "guardrail_checks": checks,
        "eligible_for_production_promotion": False,
        "eligible_for_domain_expert_review": all(checks.values()),
        "rows": [
            {
                "case_id": case_id,
                "baseline": by_case_baseline[case_id],
                "evolved": by_case_evolved[case_id],
            }
            for case_id in sorted(by_case_baseline)
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "evaluation.json"
    write_json(json_path, report)
    lines = [
        "# 九类性质归属 Agent 与受控自进化小试验",
        "",
        "> 该结果只覆盖 5 张表，其中 3 张为冻结小测试，不能外推为总体性能。",
        "",
        "| 指标 | 基线 | 进化后 | 变化 |",
        "|---|---:|---:|---:|",
        f"| 语义 Precision | {baseline['semantic_precision']:.1%} | {evolved['semantic_precision']:.1%} | {report['delta']['semantic_precision']:+.1%} |",
        f"| 语义 Recall | {baseline['semantic_recall']:.1%} | {evolved['semantic_recall']:.1%} | {report['delta']['semantic_recall']:+.1%} |",
        f"| 语义 F1 | {baseline['semantic_f1']:.1%} | {evolved['semantic_f1']:.1%} | {report['delta']['semantic_f1']:+.1%} |",
        f"| 样品绑定准确率 | {baseline['sample_binding_accuracy']:.1%} | {evolved['sample_binding_accuracy']:.1%} | {report['delta']['sample_binding_accuracy']:+.1%} |",
        "",
        "## 门禁",
        "",
        *[
            f"- {'通过' if passed else '未通过'}：{name}"
            for name, passed in checks.items()
        ],
        "",
        "无论门禁是否通过，本轮均不会自动修改生产词表或发布数据。",
    ]
    (output_dir / "evaluation.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return json_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    propose = subparsers.add_parser("propose")
    propose.add_argument("--gold", type=Path, required=True)
    propose.add_argument("--baseline-root", type=Path, required=True)
    propose.add_argument("--output", type=Path, required=True)

    compile_parser = subparsers.add_parser("compile")
    compile_parser.add_argument("--proposals", type=Path, required=True)
    compile_parser.add_argument("--reviews", type=Path, required=True)
    compile_parser.add_argument("--output", type=Path, required=True)

    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--gold", type=Path, required=True)
    evaluate.add_argument("--baseline-root", type=Path, required=True)
    evaluate.add_argument("--evolved-root", type=Path, required=True)
    evaluate.add_argument("--manifest", type=Path, required=True)
    evaluate.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "propose":
        print(propose_updates(
            gold_path=args.gold.resolve(),
            baseline_root=args.baseline_root.resolve(),
            output_path=args.output.resolve(),
        ))
    elif args.command == "compile":
        print(compile_approved_memory(
            proposals_path=args.proposals.resolve(),
            reviews_path=args.reviews.resolve(),
            output_path=args.output.resolve(),
        ))
    else:
        print(evaluate_versions(
            gold_path=args.gold.resolve(),
            baseline_root=args.baseline_root.resolve(),
            evolved_root=args.evolved_root.resolve(),
            manifest_path=args.manifest.resolve(),
            output_dir=args.output_dir.resolve(),
        ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
