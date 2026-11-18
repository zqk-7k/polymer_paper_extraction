"""Read-only publication regression against a frozen audit baseline. No API calls."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from stages.measurement_record import publication_audit_for_final
from stages.publication_evidence import repair_specialized_evidence
from stages.publication_input_scope import stage4_input_diagnostics
from stages.measurement_groups import group_measurement_claims


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _index(records: list[dict]) -> dict:
    # Same publication file hash is required by the caller. Ordinals compare
    # repeated objects in that frozen sequence; they are NOT measurement IDs.
    result, occurrences = {}, Counter()
    for record in records:
        key = (record["collection"], record["object_id"])
        ordinal = occurrences[key]
        occurrences[key] += 1
        result[(*key, ordinal)] = record
    return result


def run_regression(batch_dir: Path, baseline_path: Path, output_dir: Path, *, repair_evidence: bool = False) -> dict:
    batch_dir, baseline_path, output_dir = (p.resolve() for p in (batch_dir, baseline_path, output_dir))
    if batch_dir == output_dir or batch_dir in output_dir.parents or output_dir in batch_dir.parents:
        raise ValueError("Regression output must be separate from batch inputs")
    if output_dir.exists():
        raise ValueError("Output exists; choose a new directory")
    baseline_hash = _hash(baseline_path)
    baseline = _read(baseline_path)
    summaries, audits, diffs, input_hashes = [], [], [], {}
    repair_log, repaired_payloads = [], []
    measurement_groups = []
    seen = set()
    for old in baseline:
        ref = old["document_id"]
        if not re.fullmatch(r"reference_no_\d+", ref) or ref in seen:
            raise ValueError("Invalid or duplicate document identity")
        seen.add(ref)
        if old["source_file"] not in {"final.json", "candidate.json"}:
            raise ValueError("Unsupported publication input")
        source = batch_dir / ref
        files = {}
        names = [old["source_file"], "stage0_blocks.json", "stage3_process.json", "stage4_properties.json", "stage4_llm_response.json", "stage5_characterizations.json", "stage5_shards.json"]
        for name in names:
            path = source / name
            if path.is_file():
                input_hashes[str(path)] = _hash(path)
                files[name] = _read(path)
        publication_path = source / old["source_file"]
        if input_hashes.get(str(publication_path)) != old["sha256"]:
            raise ValueError(f"Publication input changed since baseline: {ref}")
        payload = files[old["source_file"]]
        if any(data.get("document_id") != ref for data in files.values()):
            raise ValueError(f"Mixed document inputs: {ref}")
        repairs = []
        if repair_evidence and files.get("stage0_blocks.json"):
            payload, repairs = repair_specialized_evidence(payload, files["stage0_blocks.json"])
            repair_log.extend({"document_id": ref, **row} for row in repairs)
        audit = publication_audit_for_final(
            payload, stage0=files.get("stage0_blocks.json"), stage3=files.get("stage3_process.json"),
            stage4=files.get("stage4_properties.json"), stage5=files.get("stage5_characterizations.json"),
            stage5_shards=files.get("stage5_shards.json"),
        )
        before, after = _index(old["audit"]["records"]), _index(audit["records"])
        grouped = group_measurement_claims(payload, audit)
        measurement_groups.append(grouped)
        if set(before) != set(after):
            raise ValueError(f"Audit lost or added objects: {ref}")
        transitions = Counter()
        for key in sorted(after):
            previous, current = before[key], after[key]
            transition = f"{previous['publication_status']} -> {current['publication_status']}"
            transitions[transition] += 1
            diffs.append({
                "document_id": ref, "collection": key[0], "object_id": key[1],
                "frozen_occurrence": key[2],
                "value_raw": current["value_raw"], "before": previous["publication_status"],
                "after": current["publication_status"], "before_reasons": previous["publication_reasons"],
                "after_reasons": current["publication_reasons"],
                "resolved_reasons": sorted(set(previous["publication_reasons"]) - set(current["publication_reasons"])),
                "source_cell_ids": current["source_cell_ids"],
            })
        reasons = Counter(r for row in audit["records"] for r in row["publication_reasons"])
        summaries.append({
            "document_id": ref, "source_file": old["source_file"], "records": len(after),
            "before_counts": old["audit"]["counts"]["publication_status"],
            "after_counts": audit["counts"]["publication_status"],
            "stage_input_status": audit["stage_input_status"], "transitions": dict(transitions),
            "stage4_diagnostics": stage4_input_diagnostics(files.get("stage4_properties.json"), files.get("stage4_llm_response.json")),
            "binding_counts": audit["counts"]["binding_status"],
            "measurement_group_counts": {k: grouped[k] for k in ("record_count", "group_count", "repeated_expression_count", "differing_source_count")},
            "input_scope_counts": audit["input_scope_counts"],
            "registered_records": sum(r["status"] == "registered" for r in repairs),
            "evidence_repair_rejected": sum(r["status"] == "not_repaired" for r in repairs),
            "evidence_reference_restored": sum(
                "evidence_reference_unknown" in before[key]["publication_reasons"]
                and "evidence_reference_unknown" not in after[key]["publication_reasons"] for key in after
            ),
            "reason_counts": dict(reasons.most_common()),
            "source_cell_verified": sum(r["evidence_status"] == "source_cell_verified" for r in audit["records"]),
        })
        audits.append({"document_id": ref, **audit})
        if repair_evidence:
            repaired_payloads.append((ref, {**payload, "measurement_publication_audit": audit}))
    if baseline_hash != _hash(baseline_path) or any(_hash(Path(p)) != value for p, value in input_hashes.items()):
        raise ValueError("Inputs changed during audit; refusing to write results")
    summary = {
        "schema_version": "publication_regression.v1", "documents": summaries,
        "record_count": len(diffs), "original_inputs_unchanged": True, "api_requests": 0,
        "scope": "Existing publication collections only; raw candidates and series point expansion are not included.",
        "baseline_sha256": baseline_hash, "input_hashes": input_hashes,
        "rule_hashes": {str(path.relative_to(Path(__file__).resolve().parents[1])): _hash(path)
                        for path in [Path(__file__).resolve().parents[1] / 'stages' / name for name in
                                     ('measurement_record.py', 'measurement_groups.py', 'binding_identity.py', 'sample_catalog.py', 'publication_checks.py', 'standard_mapping.py', 'sample_binding.py', 'publication_evidence.py', 'publication_input_scope.py', 'stage6_preview_salvage.py', 'stage6_validate_merge.py')]},
    }
    summary["rule_hashes"]["schema/polymer_schema.py"] = _hash(Path(__file__).resolve().parents[1] / "schema/polymer_schema.py")
    summary["rule_hashes"]["tools/audit_publication_regression.py"] = _hash(Path(__file__).resolve())
    output_dir.mkdir(parents=True, exist_ok=False)
    for name, content in (("summary.json", summary), ("audits.json", audits), ("measurement_groups.json", measurement_groups)):
        (output_dir / name).write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    if repair_evidence:
        (output_dir / "evidence_repairs.json").write_text(json.dumps(repair_log, ensure_ascii=False, indent=2), encoding="utf-8")
        copies = output_dir / "audit_copies"
        copies.mkdir()
        for ref, payload in repaired_payloads:
            (copies / f"{ref}.evidence_repaired.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "differences.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in diffs), encoding="utf-8")
    lines = ["# 发布门禁离线回归", "", "范围：已有发布集合的旁路审计；状态变化不等于抽取准确率变化。原始候选及系列点展开尚未纳入。", "", "|文章|记录数|旧审计 final|新审计 final|待核|阻断|Stage4 / Stage5|", "|---|---:|---:|---:|---:|---:|---|"]
    for d in summaries:
        counts, status = d["after_counts"], d["stage_input_status"]
        lines.append(f"|{d['document_id']}|{d['records']}|{d['before_counts']['final']}|{counts['final']}|{counts['candidate']}|{counts['not_publishable']}|{status['stage4']} / {status['stage5']}|")
    lines += ["", "输入哈希复核通过；未覆盖旧结果；API 请求数为 0。", "", "证据及输入范围修复："]
    for d in summaries:
        lines.append(f"- {d['document_id']}: 重登记 {d['registered_records']} 条；解除悬空引用阻断 {d['evidence_reference_restored']} 条；证据未通过校验 {d['evidence_repair_rejected']} 条；输入范围 {d['input_scope_counts']}")
    lines += ["", "audit_copies 仅为审计副本，不是正式发布结果。证据引用恢复不等于已满足全部发布门禁。", "", "主要阻断或待核原因："]
    for d in summaries:
        lines.append(f"- {d['document_id']}: " + "; ".join(f"{reason}={count}" for reason, count in list(d['reason_counts'].items())[:8]))
    lines += ["", "Stage4 输入诊断（只解释原因，不提升完整性状态）："]
    for d in summaries:
        diagnostic = d["stage4_diagnostics"]
        lines.append(f"- {d['document_id']}: {', '.join(diagnostic['diagnostic_categories']) or 'stage_complete'}；保存响应={diagnostic['saved_response_available']}；严格 JSON 对象={diagnostic['strict_json_object']}；下一步={diagnostic['next_action']}")
    lines += ["", "来源单元格分组（所有原始表达均保留；分组数不等于独立测量数）："]
    for d in summaries:
        counts = d["measurement_group_counts"]
        lines.append(f"- {d['document_id']}: 原始 {counts['record_count']} 条；分组 {counts['group_count']}；重复表达 {counts['repeated_expression_count']} 条；同来源不同表达 {counts['differing_source_count']} 处。")
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-dir", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repair-specialized-evidence", action="store_true")
    args = parser.parse_args()
    result = run_regression(args.batch_dir, args.baseline, args.output_dir, repair_evidence=args.repair_specialized_evidence)
    print(f"Audited {len(result['documents'])} documents / {result['record_count']} records; inputs unchanged")


if __name__ == "__main__":
    main()
