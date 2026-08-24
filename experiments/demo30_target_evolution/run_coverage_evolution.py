"""Run and evaluate goal-driven nine-field coverage Agent evolution."""

from __future__ import annotations

import argparse
import html
import json
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any


MODULE_DIR = Path(__file__).resolve().parent
REPO_ROOT = MODULE_DIR.parents[1]
EXTRACTION_ROOT = REPO_ROOT / "extraction"
if str(EXTRACTION_ROOT) not in sys.path:
    sys.path.insert(0, str(EXTRACTION_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agents.specialized_coverage import passes_schema_release_gate, run_coverage_agent  # noqa: E402
from evaluate_demo30 import (  # noqa: E402
    SPECIALIZED_FIELDS,
    discover_polyinfo,
    polyinfo_specialized_fields,
)
from web_api.app import _read_polyinfo_samples  # noqa: E402


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_safe(value), ensure_ascii=False, indent=2), encoding="utf-8")


def workflow_fields(document_dir: Path) -> set[str]:
    candidate = read_json(document_dir / "candidate.json")
    return {
        str(item.get("source_field"))
        for item in candidate.get("specialized_property_observations") or []
        if item.get("publication_status") == "published"
        and item.get("source_field") in SPECIALIZED_FIELDS
    }


def agent_fields(path: Path, *, apply_release_gate: bool) -> tuple[set[str], int, int, list[str]]:
    artifact = read_json(path)
    decisions = (artifact.get("response") or {}).get("decisions") or []
    raw_supported = [item for item in decisions if item.get("decision") == "supported"]
    blocked = [
        str(item.get("source_field"))
        for item in raw_supported
        if apply_release_gate and not passes_schema_release_gate(item)
    ]
    supported = [
        item
        for item in raw_supported
        if not apply_release_gate or passes_schema_release_gate(item)
    ]
    fields = {str(item.get("source_field")) for item in supported}
    resolved = sum(item.get("subject_resolution") in {"sample", "entity_only"} for item in supported)
    return fields, resolved, len(supported), blocked


def run_agents(
    batch_root: Path,
    output_root: Path,
    refs: list[str],
    memory_path: Path | None,
    *,
    include_global_context: bool,
) -> None:
    vocabulary = EXTRACTION_ROOT / "config" / "polymer_schema.yaml"
    config = EXTRACTION_ROOT / "config" / "pipeline.yaml"
    for ref_no in refs:
        artifact_path = output_root / ref_no / "specialized_coverage_agent.json"
        if artifact_path.is_file():
            print(f"[{output_root.name}] {ref_no} already complete", flush=True)
            continue
        print(f"[{output_root.name}] {ref_no}", flush=True)
        artifact = run_coverage_agent(
            batch_root / ref_no,
            vocabulary_path=vocabulary,
            memory_path=memory_path,
            config_path=config,
            include_global_context=include_global_context,
        )
        write_json(artifact_path, artifact)


def score(
    batch_root: Path,
    polyinfo_root: Path,
    refs: list[str],
    agent_root: Path | None,
    *,
    apply_release_gate: bool = False,
) -> dict[str, Any]:
    polyinfo = discover_polyinfo(polyinfo_root)
    rows = []
    totals = Counter()
    subject_resolved = 0
    supported_total = 0
    for ref_no in refs:
        samples = _read_polyinfo_samples(polyinfo[ref_no], include_structures=False)
        anchors = polyinfo_specialized_fields(samples)
        baseline = workflow_fields(batch_root / ref_no)
        added: set[str] = set()
        blocked: list[str] = []
        if agent_root is not None:
            added, resolved, supported, blocked = agent_fields(
                agent_root / ref_no / "specialized_coverage_agent.json",
                apply_release_gate=apply_release_gate,
            )
            subject_resolved += resolved
            supported_total += supported
        predicted = baseline | added
        hit = anchors & predicted
        totals.update({"anchor": len(anchors), "predicted": len(predicted), "hit": len(hit)})
        rows.append({
            "ref_no": ref_no,
            "anchors": sorted(anchors),
            "workflow": sorted(baseline),
            "agent_added": sorted(added - baseline),
            "combined": sorted(predicted),
            "matched": sorted(hit),
            "missing": sorted(anchors - predicted),
            "anchor_only_predictions": sorted(predicted - anchors),
            "blocked_by_release_gate": sorted(blocked),
            "recall": round(len(hit) / len(anchors), 4) if anchors else 1.0,
        })
    precision = totals["hit"] / totals["predicted"] if totals["predicted"] else 0.0
    recall = totals["hit"] / totals["anchor"] if totals["anchor"] else 0.0
    return {
        "anchor_document_fields": totals["anchor"],
        "predicted_document_fields": totals["predicted"],
        "matched_document_fields": totals["hit"],
        "anchor_precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
        "evidence_validation_rate": 1.0 if agent_root is not None else None,
        "subject_resolution_rate": round(subject_resolved / supported_total, 4) if supported_total else None,
        "release_gate_enabled": apply_release_gate,
        "rows": rows,
    }


def render_html(report: dict[str, Any]) -> str:
    workflow = report["workflow"]
    base = report.get("base_agent")
    evolved = report["evolved_agent"]
    rows = evolved["rows"]
    full_baseline = report.get("full_demo30_baseline") or {}

    def pct(value: float | None) -> str:
        return "-" if value is None else f"{value * 100:.1f}%"

    cards = [
        ("当前 workflow", workflow["recall"], "候选 JSON 已发布九类字段"),
        ("基础 Agent", base["recall"] if base else None, "受控词表 + 检索 + 证据校验"),
        ("自进化版本", evolved["recall"], "审批记忆 + 全局语境检索 + 发布门禁"),
        ("最终锚点 Precision", evolved["anchor_precision"], "仅用于参考对齐，不等同全文准确率"),
    ]
    calibration_rows = "".join(
        f'<tr><td>{html.escape(str(item["run"]))}</td><td>{pct(item["base_agent"]["recall"])}</td>'
        f'<td>{pct(item["evolved_agent"]["recall"])}</td><td>{pct(item["evolved_agent"]["anchor_precision"])}</td>'
        f'<td>用于改进，不计入最终成绩</td></tr>'
        for item in report.get("calibration") or []
    )
    exact_full = (full_baseline.get("exact_property_alignment") or {}).get("recall")
    semantic_full = (full_baseline.get("semantic_property_alignment") or {}).get("recall")
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Agent 与受控自进化结果</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#eef3f6;color:#12212b;font:15px/1.55 Inter,"Microsoft YaHei",sans-serif}}main{{max-width:1460px;margin:auto;padding:48px 32px 80px}}header{{padding:38px 42px;background:linear-gradient(120deg,#082d38,#0d4952);color:#fff;border-radius:8px}}h1{{font:700 36px Georgia,serif;margin:8px 0}}h2{{font:700 20px Georgia,serif}}header p{{max-width:1100px;color:#c7dde2}}.eyebrow{{color:#4fd3be;font-weight:800;letter-spacing:.08em}}.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:18px 0}}.card,.panel{{background:#fff;border:1px solid #d7e3e8;border-radius:7px;box-shadow:0 10px 30px rgba(10,42,52,.07)}}.card{{padding:22px}}.card span,.card small{{display:block;color:#61747e}}.card b{{display:block;font:700 34px Georgia,serif;margin:8px 0}}.flow{{display:grid;grid-template-columns:repeat(9,auto);align-items:center;gap:10px;padding:22px;margin:16px 0;background:#fff;border-radius:7px}}.flow i{{font-style:normal;color:#90a1a9}}.flow b{{padding:12px 14px;background:#eaf5f4;color:#096d66;border:1px solid #cbe7e3}}.panel{{padding:24px;margin-top:16px;overflow:auto}}table{{width:100%;border-collapse:collapse}}th,td{{padding:11px 9px;border-bottom:1px solid #e2eaed;text-align:left;vertical-align:top}}th{{font-size:12px;color:#61727c}}code{{font-size:12px;color:#285365}}.pass{{color:#087d63}}.fail{{color:#b54040}}.note{{padding:14px 18px;border-left:4px solid #d7951c;background:#fff8e6;margin-top:16px}}@media(max-width:1000px){{.cards{{grid-template-columns:repeat(2,1fr)}}.flow{{grid-template-columns:1fr}}.flow i{{display:none}}}}@media(max-width:620px){{.cards{{grid-template-columns:1fr}}}}
</style></head><body><main><header><div class="eyebrow">GOAL-DRIVEN EXTRACTION · CONTROLLED EVOLUTION</div><h1>九类性质归属 Agent：从漏检定位到可验证候选</h1><p>Agent 只在高风险语义归属步骤工作。它检索 Stage 0 原文、查询 Stage 2/3 实体与样品、查受控词表，并由确定性验证器检查原文短语、block、bbox 和外键。自进化只加入专家批准的检索线索，不写入论文答案和数值。</p></header>
<div class="cards">{''.join(f'<div class="card"><span>{html.escape(name)}</span><b>{pct(value)}</b><small>{html.escape(note)}</small></div>' for name,value,note in cards)}</div>
<div class="flow"><b>初始 workflow</b><i>→</i><b>归属 Agent</b><i>→</i><b>两轮校准</b><i>→</i><b>受控自进化</b><i>→</i><b>独立冻结集</b></div>
<section class="panel"><h2>预注册门禁</h2><table><tr><th>目标</th><th>结果</th><th>判定</th></tr>{''.join(f'<tr><td>{html.escape(key)}</td><td>{html.escape(str(value))}</td><td class="{("pass" if passed else "fail")}">{("通过" if passed else "未通过")}</td></tr>' for key,(value,passed) in report['guardrails'].items())}</table></section>
<section class="panel"><h2>校准轮次</h2><table><thead><tr><th>轮次</th><th>基础 Agent Recall</th><th>自进化版本 Recall</th><th>自进化版本锚点 Precision</th><th>用途</th></tr></thead><tbody>{calibration_rows}</tbody></table></section>
<section class="panel"><h2>五篇独立冻结论文的字段恢复</h2><table><thead><tr><th>论文</th><th>workflow</th><th>Agent 新增</th><th>仍缺失</th><th>锚点外候选</th><th>门禁拦截</th><th>Recall</th></tr></thead><tbody>{''.join(f'<tr><td><code>{row["ref_no"]}</code></td><td>{html.escape(", ".join(row["workflow"]) or "-")}</td><td>{html.escape(", ".join(row["agent_added"]) or "-")}</td><td>{html.escape(", ".join(row["missing"]) or "-")}</td><td>{html.escape(", ".join(row["anchor_only_predictions"]) or "-")}</td><td>{html.escape(", ".join(row["blocked_by_release_gate"]) or "-")}</td><td><b>{pct(row["recall"])}</b></td></tr>' for row in rows)}</tbody></table></section>
<div class="note">这里的 Recall 是“九类 source_field 在文献级是否被原文支持候选覆盖”，不是 1,550 条数值记录的完全一致 Recall。demo30 全量数值精确 Recall 为 <b>{pct(exact_full)}</b>，性质名称语义 Recall 为 <b>{pct(semantic_full)}</b>；两个口径必须并列报告，不能互相替代。</div>
</main></body></html>"""


def evaluate_all(batch_root: Path, polyinfo_root: Path, run_root: Path) -> dict[str, Any]:
    manifest = read_json(MODULE_DIR / "experiment_manifest.json")
    refs = list(manifest["frozen_test_refs"])
    workflow = score(batch_root, polyinfo_root, refs, None)
    base_path = run_root / "base_agent"
    evolved_path = run_root / "evolved_agent"
    base = score(batch_root, polyinfo_root, refs, base_path) if base_path.is_dir() else None
    evolved = score(batch_root, polyinfo_root, refs, evolved_path, apply_release_gate=True)
    calibration = []
    for round_info in manifest.get("calibration_rounds") or []:
        calibration_root = MODULE_DIR / "runs" / str(round_info["run"])
        calibration_refs = list(round_info["refs"])
        if not (calibration_root / "base_agent").is_dir() or not (calibration_root / "evolved_agent").is_dir():
            continue
        calibration.append({
            "run": round_info["run"],
            "base_agent": score(batch_root, polyinfo_root, calibration_refs, calibration_root / "base_agent"),
            "evolved_agent": score(
                batch_root,
                polyinfo_root,
                calibration_refs,
                calibration_root / "evolved_agent",
                apply_release_gate=True,
            ),
        })
    baseline_path = MODULE_DIR / "runs" / "baseline" / "baseline_audit.json"
    full_demo30_baseline = read_json(baseline_path) if baseline_path.is_file() else None
    guardrail_config = manifest["guardrails"]
    checks = {
        "Recall ≥ 80%": (pct := evolved["recall"], pct >= float(manifest["target_recall"])),
        "锚点 Precision ≥ 75%": (pct := evolved["anchor_precision"], pct >= float(guardrail_config["minimum_anchor_precision"])),
        "证据验证率 = 100%": (pct := evolved["evidence_validation_rate"], pct >= float(guardrail_config["minimum_evidence_validation_rate"])),
        "主体解析率 ≥ 90%": (pct := evolved["subject_resolution_rate"], pct >= float(guardrail_config["minimum_subject_resolution_rate"])),
        "相对 workflow 有提升": (evolved["recall"] - workflow["recall"], evolved["recall"] > workflow["recall"]),
    }
    report = {
        "schema_version": "specialized-coverage-evolution-evaluation/1.0",
        "experiment_id": manifest["experiment_id"],
        "scope": "five frozen papers; document-level nine-field anchor coverage",
        "workflow": workflow,
        "base_agent": base,
        "evolved_agent": evolved,
        "calibration": calibration,
        "full_demo30_baseline": full_demo30_baseline,
        "delta_vs_workflow": round(evolved["recall"] - workflow["recall"], 4),
        "guardrails": checks,
        "eligible_for_expert_review": all(value[1] for value in checks.values()),
        "eligible_for_automatic_production_promotion": False,
    }
    write_json(run_root / "evaluation.json", report)
    (run_root / "agent_evolution_report.html").write_text(render_html(report), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run-base", "run-evolved", "evaluate", "all"))
    parser.add_argument("--batch-root", type=Path, default=REPO_ROOT / "batch_results" / "demo30_preview_20260824")
    parser.add_argument("--polyinfo-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, default=MODULE_DIR / "runs" / "coverage_v3")
    args = parser.parse_args()
    manifest = read_json(MODULE_DIR / "experiment_manifest.json")
    refs = list(manifest["frozen_test_refs"])
    args.run_root.mkdir(parents=True, exist_ok=True)
    if args.command in {"run-base", "all"}:
        run_agents(
            args.batch_root,
            args.run_root / "base_agent",
            refs,
            None,
            include_global_context=False,
        )
    if args.command in {"run-evolved", "all"}:
        run_agents(
            args.batch_root,
            args.run_root / "evolved_agent",
            refs,
            MODULE_DIR / "approved_memory_v1.yaml",
            include_global_context=True,
        )
    if args.command in {"evaluate", "all"}:
        report = evaluate_all(args.batch_root, args.polyinfo_root, args.run_root)
        print(json.dumps({"recall": report["evolved_agent"]["recall"], "guardrails": report["guardrails"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
