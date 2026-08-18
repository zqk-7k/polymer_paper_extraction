"""隔离运行的 PoLyInfo 锚点召回自进化试验。"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any


MODULE_DIR = Path(__file__).resolve().parent
REPO_ROOT = MODULE_DIR.parents[1]
EXTRACTION_ROOT = REPO_ROOT / "extraction"
MANIFEST_PATH = MODULE_DIR / "experiment_manifest.json"
MEMORY_PATH = MODULE_DIR / "recall_memory.md"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from extraction.llm_client import LLMClient, load_pipeline_config  # noqa: E402
from extraction.prompt_loader import PromptLoader, RenderedPrompt  # noqa: E402
from extraction.stages.stage4_property import (  # noqa: E402
    OUTPUT_SCHEMA_VERSION,
    STAGE_ID,
    PropertyStageResponse,
    load_property_vocabulary,
    run_stage4,
)
from web_api.app import (  # noqa: E402
    _align_property_records,
    _alignment_metrics,
    _polyinfo_detail,
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_manifest() -> dict[str, Any]:
    return read_json(MANIFEST_PATH)


def baseline_root(manifest: dict[str, Any]) -> Path:
    return REPO_ROOT / "batch_results" / str(manifest["baseline_collection"])


def build_evolved_prompt() -> RenderedPrompt:
    base = PromptLoader().render_stage_prompt(
        "polymer.stage4.property",
        PropertyStageResponse,
        expected_stage=STAGE_ID,
        expected_output_schema=OUTPUT_SCHEMA_VERSION,
    )
    memory = MEMORY_PATH.read_text(encoding="utf-8").strip()
    text = base.text + "\n\n# Approved Recall Memory\n\n" + memory
    return RenderedPrompt(
        prompt_id="polymer.stage4.property.recall_evolution_v1",
        version=base.version + "+recall-evolution.1",
        stage=base.stage,
        output_schema_version=base.output_schema_version,
        text=text,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def stage4_properties(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path)
    return list(payload.get("properties") or [])


def anchor_ready_properties(properties: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """确定性补齐评价所需规范名，不修改抽取产物。"""
    normalized = copy.deepcopy(properties)
    for item in normalized:
        molecular_weight_type = str(item.get("molecular_weight_type") or "").lower()
        if molecular_weight_type in {"mn", "mw", "mv", "mz"}:
            item["property_name_normalized"] = molecular_weight_type
    return normalized


def property_quality(ref_dir: Path, properties: list[dict[str, Any]]) -> dict[str, Any]:
    stage3 = read_json(ref_dir / "stage3_process.json")
    sample_ids = {
        str(item.get("sample_id"))
        for item in stage3.get("samples") or []
        if item.get("sample_id")
    }
    total = len(properties)
    sample_bound = sum(
        1 for item in properties if str(item.get("sample_id")) in sample_ids
    )
    evidence_located = 0
    for item in properties:
        evidence = item.get("evidence") or []
        if evidence and all(
            entry.get("block_id")
            and entry.get("page") is not None
            and isinstance(entry.get("bbox"), list)
            and len(entry["bbox"]) == 4
            for entry in evidence
        ):
            evidence_located += 1
    unit_complete = sum(1 for item in properties if item.get("unit_raw"))
    return {
        "properties": total,
        "sample_bound": sample_bound,
        "evidence_located": evidence_located,
        "unit_complete": unit_complete,
        "sample_binding_rate": round(sample_bound / total, 4) if total else 0.0,
        "evidence_location_rate": round(evidence_located / total, 4) if total else 0.0,
        "unit_completeness": round(unit_complete / total, 4) if total else 0.0,
    }


def alignment_for(ref_no: str, properties: list[dict[str, Any]]) -> dict[str, Any]:
    polyinfo = _polyinfo_detail(ref_no)
    alignment = _align_property_records(
        polyinfo["properties"],
        anchor_ready_properties(properties),
    )
    counts = {
        status: sum(item["status"] == status for item in alignment)
        for status in ("matched", "value_diff", "polyinfo_only", "extraction_only")
    }
    return {
        **_alignment_metrics(counts),
        "missing_property_types": dict(Counter(
            item["canonical_name"]
            for item in alignment
            if item["status"] == "polyinfo_only"
        ).most_common()),
    }


def extraction_only_review_rows(
    ref_no: str,
    properties: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    polyinfo = _polyinfo_detail(ref_no)
    alignment = _align_property_records(
        polyinfo["properties"],
        anchor_ready_properties(properties),
    )
    rows = []
    for item in alignment:
        if item["status"] != "extraction_only":
            continue
        prop = item["extraction"] or {}
        evidence = (prop.get("evidence") or [{}])[0]
        locator = evidence.get("table_locator") or {}
        rows.append({
            "ref_no": ref_no,
            "property_id": prop.get("property_id"),
            "sample_id": prop.get("sample_id"),
            "property_name_raw": prop.get("property_name_raw"),
            "property_name_normalized": prop.get("property_name_normalized"),
            "molecular_weight_type": prop.get("molecular_weight_type"),
            "value_raw": prop.get("value_raw"),
            "unit_raw": prop.get("unit_raw"),
            "page": evidence.get("page"),
            "block_id": evidence.get("block_id"),
            "bbox": json.dumps(evidence.get("bbox"), ensure_ascii=False),
            "table_row": locator.get("row_label"),
            "table_column": locator.get("column_label"),
            "evidence_text": evidence.get("source_sentence"),
            "expert_decision": "pending",
            "expert_note": "",
        })
    return rows


def aggregate(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    counts = {
        status: sum(int(row[key][status]) for row in rows)
        for status in ("matched", "value_diff", "polyinfo_only", "extraction_only")
    }
    return _alignment_metrics(counts)


def prepare_development_report(run_dir: Path) -> Path:
    manifest = load_manifest()
    source_root = baseline_root(manifest)
    rows = []
    missing_types: Counter[str] = Counter()
    for ref_no in manifest["development_refs"]:
        properties = stage4_properties(source_root / ref_no / "stage4_properties.json")
        alignment = alignment_for(ref_no, properties)
        missing_types.update(alignment.pop("missing_property_types"))
        rows.append({"ref_no": ref_no, "baseline": alignment})
    report = {
        "experiment_id": manifest["experiment_id"],
        "development_refs": manifest["development_refs"],
        "frozen_test_refs": manifest["frozen_test_refs"],
        "development_missing_property_types": dict(missing_types.most_common()),
        "recall_memory_sha256": hashlib.sha256(MEMORY_PATH.read_bytes()).hexdigest(),
        "rows": rows,
    }
    path = run_dir / "development_error_patterns.json"
    write_json(path, report)
    return path


def copy_stage_inputs(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for name in ("stage0_blocks.json", "stage2_entities.json", "stage3_process.json"):
        shutil.copy2(source / name, target / name)


def run_evolved(run_dir: Path, refs: list[str]) -> None:
    manifest = load_manifest()
    source_root = baseline_root(manifest)
    config_path = EXTRACTION_ROOT / "config" / "pipeline.yaml"
    config = load_pipeline_config(config_path)
    stage_config = config["stages"][STAGE_ID]
    vocabulary_path = EXTRACTION_ROOT / str(stage_config["vocabulary_path"])
    vocabulary, vocabulary_sha256 = load_property_vocabulary(vocabulary_path)
    prompt = build_evolved_prompt()
    client = LLMClient.from_pipeline_config(stage=STAGE_ID, config_path=config_path)
    evolved_root = run_dir / "evolved"

    for ref_no in refs:
        source = source_root / ref_no
        target = evolved_root / ref_no
        copy_stage_inputs(source, target)
        run_stage4(
            target / "stage0_blocks.json",
            target / "stage2_entities.json",
            target / "stage3_process.json",
            target / "stage4_properties.json",
            client,
            prompt,
            vocabulary,
            vocabulary_sha256,
            force=True,
            input_sections=tuple(stage_config.get("input_sections") or ("Methods", "Results")),
            max_input_chars=int(stage_config.get("max_input_chars") or 110000),
            max_validation_retries=0,
            max_tokens=int(stage_config.get("max_tokens") or 128000),
            preview_relaxed=True,
        )
        subprocess.run(
            [
                sys.executable,
                str(EXTRACTION_ROOT / "stages" / "stage4r_table_recovery.py"),
                "--input-root", str(evolved_root),
                "--output-root", str(evolved_root),
                "--ref-no", ref_no,
                "--apply",
                "--force",
            ],
            check=True,
            cwd=REPO_ROOT,
        )

    write_json(run_dir / "run_metadata.json", {
        "experiment_id": manifest["experiment_id"],
        "refs": refs,
        "prompt_id": prompt.prompt_id,
        "prompt_version": prompt.version,
        "prompt_sha256": prompt.sha256,
        "recall_memory_sha256": hashlib.sha256(MEMORY_PATH.read_bytes()).hexdigest(),
        "model_calls": len(client.call_history),
    })


def evaluate(run_dir: Path) -> Path:
    manifest = load_manifest()
    source_root = baseline_root(manifest)
    evolved_root = run_dir / "evolved"
    rows = []
    total_cost = 0.0
    total_input_tokens = 0
    total_output_tokens = 0
    review_rows: list[dict[str, Any]] = []
    for ref_no in manifest["frozen_test_refs"]:
        baseline_dir = source_root / ref_no
        evolved_dir = evolved_root / ref_no
        baseline_properties = stage4_properties(baseline_dir / "stage4_properties.json")
        evolved_properties = stage4_properties(evolved_dir / "stage4_properties.json")
        evolved_payload = read_json(evolved_dir / "stage4_properties.json")
        provenance = evolved_payload.get("provenance") or {}
        usage = provenance.get("usage") or {}
        cost = provenance.get("cost") or {}
        total_input_tokens += int(usage.get("input_tokens") or 0)
        total_output_tokens += int(usage.get("output_tokens") or 0)
        total_cost += float(cost.get("total_cost") or 0)
        baseline_alignment = alignment_for(ref_no, baseline_properties)
        evolved_alignment = alignment_for(ref_no, evolved_properties)
        review_rows.extend(extraction_only_review_rows(ref_no, evolved_properties))
        baseline_alignment.pop("missing_property_types", None)
        evolved_alignment.pop("missing_property_types", None)
        rows.append({
            "ref_no": ref_no,
            "baseline": baseline_alignment,
            "evolved": evolved_alignment,
            "baseline_quality": property_quality(baseline_dir, baseline_properties),
            "evolved_quality": property_quality(evolved_dir, evolved_properties),
        })

    baseline = aggregate(rows, "baseline")
    evolved = aggregate(rows, "evolved")
    guardrails = manifest["guardrails"]
    min_evidence = min(row["evolved_quality"]["evidence_location_rate"] for row in rows)
    min_binding = min(row["evolved_quality"]["sample_binding_rate"] for row in rows)
    checks = {
        "recall_improved": evolved["recall"] > baseline["recall"],
        "precision_guardrail": evolved["precision"] >= baseline["precision"] - float(guardrails["maximum_precision_drop"]),
        "evidence_guardrail": min_evidence >= float(guardrails["minimum_evidence_location_rate"]),
        "sample_binding_guardrail": min_binding >= float(guardrails["minimum_sample_binding_rate"]),
    }
    report = {
        "experiment_id": manifest["experiment_id"],
        "primary_metric": manifest["primary_metric"],
        "baseline": baseline,
        "evolved": evolved,
        "delta": {
            "matched": evolved["matched"] - baseline["matched"],
            "precision": round(evolved["precision"] - baseline["precision"], 4),
            "recall": round(evolved["recall"] - baseline["recall"], 4),
            "f1": round(evolved["f1"] - baseline["f1"], 4),
        },
        "guardrail_checks": checks,
        "eligible_for_expert_review": (
            checks["recall_improved"]
            and checks["evidence_guardrail"]
            and checks["sample_binding_guardrail"]
        ),
        "eligible_for_automatic_promotion": all(checks.values()),
        "review_candidate_count": len(review_rows),
        "runtime": {
            "model_calls": len(rows),
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "reported_cost_cny": round(total_cost, 4),
        },
        "rows": rows,
    }
    path = run_dir / "evaluation.json"
    write_json(path, report)
    review_path = run_dir / "expert_review_candidates.csv"
    if review_rows:
        with review_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(review_rows[0]))
            writer.writeheader()
            writer.writerows(review_rows)
    markdown = [
        "# PoLyInfo 锚点召回自进化试验结果",
        "",
        f"- 基线 Recall：{baseline['recall']:.1%}",
        f"- 进化版 Recall：{evolved['recall']:.1%}",
        f"- Recall 变化：{report['delta']['recall']:+.1%}",
        f"- 基线 Precision：{baseline['precision']:.1%}",
        f"- 进化版 Precision：{evolved['precision']:.1%}",
        f"- F1：{baseline['f1']:.1%} → {evolved['f1']:.1%}",
        f"- 精确匹配记录：{baseline['matched']} → {evolved['matched']}",
        f"- 本轮模型费用：{report['runtime']['reported_cost_cny']:.4f} CNY",
        f"- 待人工审核新增记录：{len(review_rows)} 条",
        "",
        "## 分论文结果",
        "",
        "| reference_no | 基线 Recall | 进化 Recall | 基线 F1 | 进化 F1 | 证据定位 | 样品绑定 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        markdown.append(
            "| {ref_no} | {br:.1%} | {er:.1%} | {bf:.1%} | {ef:.1%} | {evidence:.1%} | {binding:.1%} |".format(
                ref_no=row["ref_no"],
                br=row["baseline"]["recall"],
                er=row["evolved"]["recall"],
                bf=row["baseline"]["f1"],
                ef=row["evolved"]["f1"],
                evidence=row["evolved_quality"]["evidence_location_rate"],
                binding=row["evolved_quality"]["sample_binding_rate"],
            )
        )
    markdown.extend([
        "",
        "## 自动门禁",
        "",
        *[f"- {'通过' if passed else '未通过'}：{name}" for name, passed in checks.items()],
        "",
        "PoLyInfo 未收录不等于抽取错误，因此锚点 Precision 下降只触发人工审核，",
        "不能单独证明新增记录错误。所有新增记录仍需抽样核查原文语义。",
    ])
    (run_dir / "evaluation.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "evaluate", "all"))
    parser.add_argument("--run-dir", type=Path, default=MODULE_DIR / "runs" / "trial_v1")
    parser.add_argument("--ref-no", action="append", dest="refs")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    run_dir = args.run_dir.expanduser().resolve()
    manifest = load_manifest()
    refs = args.refs or list(manifest["frozen_test_refs"])
    run_dir.mkdir(parents=True, exist_ok=True)
    if args.command in {"prepare", "all"}:
        print(prepare_development_report(run_dir))
    if args.command in {"run", "all"}:
        run_evolved(run_dir, refs)
    if args.command in {"evaluate", "all"}:
        print(evaluate(run_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
