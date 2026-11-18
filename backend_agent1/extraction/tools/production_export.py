"""Export gated measurements, or explicitly selected historical value diagnostics."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path
from stages.final_unit_conversion import enrich_observation
from stages.measurement_record import MeasurementRecord
from tools.source_index_diagnostics import FAILURE_CLASSES


def _read_jsonl(path):
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"{path}: expected JSON objects")
    return rows


def _write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False)+"\n" for row in rows), encoding="utf-8")


def prepare_value_row(row: dict) -> dict:
    """Materialize source values; never use reference numbers as predictions."""
    observations, seen = [], set()
    for original in row.get("matched_observations") or []:
        observation = enrich_observation(original, row.get("reviewed_unit"), row.get("standard_property_code") or "")
        if not observation["numeric_present"]:
            continue
        fingerprint = json.dumps(observation, sort_keys=True, ensure_ascii=False)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        observation["value_observation_id"] = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:20]
        observations.append(observation)
    out = dict(row)
    out.pop("matched_observations", None)
    out["reference_value_min"] = out.pop("value_min", None)
    out["reference_value_max"] = out.pop("value_max", None)
    out["legacy_alignment_status"] = out.pop("status", None)
    out.update(value_status="captured" if observations and row.get("standard_property_code") else "not_captured",
               sample_binding_ignored=True, observations=observations, observation_count=len(observations),
               sample_binding_status=row.get("sample_binding_status", "unresolved"),
               standard_value=None, standard_value_min=None, standard_value_max=None, standard_unit=None,
               original_value=None, original_unit=None, standard_uncertainty=None,
               conversion_operation=None, conversion_factor=None, conversion_offset=None,
               unit_conversion_status="unit_review_required", value_parse_warnings=[],
               value_aggregation_status="single_representation", standard_value_candidates=[])
    if not observations:
        out["failure_reason"] = row.get("index_failure_reason") or row.get("index_failure_class") or "no_numeric_source_observation"
        return out
    if not row.get("standard_property_code"):
        out["failure_reason"] = "property_code_unresolved"
        return out
    # Choose a numeric representation, not a sample. All source alternatives
    # remain in observations; disagreeing standard values are not collapsed.
    rank = {"unit_equivalent": 0, "unit_converted_exact": 0, "unit_source_only": 1,
            "unit_review_required": 2, "unit_conflict": 3}
    best = min(rank[o["unit_conversion_status"]] for o in observations)
    preferred = [o for o in observations if rank[o["unit_conversion_status"]] == best]
    forms = {json.dumps([o["standard_value"], o["standard_unit"], o["standard_uncertainty"]]) for o in preferred}
    preferred.sort(key=lambda o: o["value_observation_id"])
    chosen = preferred[0]
    if len(forms) == 1:
        for key in ("standard_value", "standard_value_min", "standard_value_max", "standard_unit",
                    "standard_uncertainty", "conversion_operation", "conversion_factor", "conversion_offset",
                    "unit_conversion_status", "original_value", "original_unit"):
            out[key] = chosen.get(key)
        out["representative_observation_id"] = chosen["value_observation_id"]
    else:
        out["value_parse_warnings"].append("multiple_value_representations")
        out["value_aggregation_status"] = "multiple_representations"
        out["standard_value_candidates"] = [dict(zip(("standard_value", "standard_unit", "standard_uncertainty"), json.loads(form))) for form in sorted(forms)]
        # Multiple values with a known converted unit require value review,
        # not unit review. Keep these two diagnostics independent as well.
        statuses = {o["unit_conversion_status"] for o in preferred}
        out["unit_conversion_status"] = "unit_converted_exact" if "unit_converted_exact" in statuses else chosen["unit_conversion_status"]
        known_units = {o["standard_unit"] for o in preferred}
        if len(known_units) == 1:
            out["standard_unit"] = chosen["standard_unit"]
    out["value_parse_warnings"] += sorted({w for o in observations for w in o.get("conversion_warnings", [])})
    out["unit_review_required"] = out["unit_conversion_status"] in {"unit_review_required", "unit_conflict"}
    out["publish_status"] = "value_only"
    out["value_only_candidate"] = True
    return out


def build_export(alignment_dir: Path, output_dir: Path, diagnostics_path: Path | None = None) -> dict:
    alignment_dir, output_dir = alignment_dir.resolve(), output_dir.resolve()
    source = alignment_dir / "properties_alignment.jsonl"
    rows = _read_jsonl(source)
    if not rows:
        raise ValueError("properties_alignment.jsonl is empty")
    if any(r.get("value_captured") and "matched_observations" not in r for r in rows):
        raise ValueError("Alignment lacks source observations. Rerun production_alignment_audit v2 before publishing.")
    ids = [r["standard_record_id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate standard_record_id in alignment")
    diagnostics = _read_jsonl(diagnostics_path) if diagnostics_path else []
    if len({r['standard_record_id'] for r in diagnostics}) != len(diagnostics):
        raise ValueError('Duplicate diagnostic record IDs')
    by_id = {r['standard_record_id']: r for r in rows}
    for note in diagnostics:
        record = by_id.get(note['standard_record_id'])
        if (record is None or note.get('index_failure_class') not in FAILURE_CLASSES
                or note.get('current_value_captured') != bool(record.get('matched_observations'))):
            raise ValueError('Diagnostics do not match the current alignment')
        # A diagnostic sidecar can annotate a result, never change a source
        # observation, numeric value or capture decision.
        for key in ('index_failure_class', 'index_failure_reason', 'index_diagnostic_note',
                    'index_resolution_status', 'index_recovery_rules', 'review_evidence'):
            if key in note:
                record[key] = note[key]
    candidate, final, failed = [], [], []
    for row in rows:
        prepared = prepare_value_row(row)
        if prepared["value_status"] == "captured":
            candidate.append({**prepared, "export_kind": "candidate_value_only"})
            final.append({**prepared, "export_kind": "final_value_only"})
        else:
            failed.append({**prepared, "export_kind": "not_captured"})
    review = [r for r in final if r.get("unit_review_required")]
    counts = {"alignment_records": len(rows), "property_value_capture": len(final),
              "candidate_value_only": len(candidate), "final_value_only": len(final),
              "not_captured": len(failed), "unit_conversion_review": len(review)}
    units = dict(sorted(Counter(r["unit_conversion_status"] for r in final).items()))
    samples = dict(sorted(Counter(r["sample_binding_status"] for r in final).items()))
    split_counts = {
        "compound_column_split_deterministic": sum("compound_column_split_deterministic" in (r.get("review_flags") or []) for r in rows),
        "surface_component_split_deterministic": sum("surface_component_split_deterministic" in (r.get("review_flags") or []) for r in rows),
    }
    per_doc = []
    for doc in sorted({r["reference_no"] for r in rows}):
        included = [r for r in final if r["reference_no"] == doc]
        total = sum(r["reference_no"] == doc for r in rows)
        per_doc.append({"reference_no": doc, "standard_records": total,
                        "candidate_value_only": len(included), "final_value_only": len(included),
                        "not_captured": total-len(included),
                        "unit_status_counts": dict(Counter(r["unit_conversion_status"] for r in included))})
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, records in (("candidate_value_only", candidate), ("final_value_only", final),
                          ("unit_conversion_review", review), ("not_captured", failed)):
        _write_jsonl(output_dir / f"{name}.jsonl", records)
    manifest = {
        "schema_version": "production_value_export.v2", "generated_at": date.today().isoformat(),
        "alignment_dir": str(alignment_dir), "output_dir": str(output_dir),
        "alignment_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "diagnostics_sha256": hashlib.sha256(diagnostics_path.read_bytes()).hexdigest() if diagnostics_path else None,
        "counts": counts, "property_value_capture_rate": len(final)/len(rows), "deterministic_split_counts": split_counts,
        "unit_status_counts": units, "sample_status_informational": samples, "per_document": per_doc,
        "value_aggregation_counts": dict(Counter(r["value_aggregation_status"] for r in final)),
        "failure_reason_counts": dict(Counter(r["failure_reason"] for r in failed)),
        "definition": "按标准集记录统计真实性质和值候选；单位转换在两个出口之前执行。样品、证据及单位复核状态不阻塞值出口。",
        "notes": ["标准值由原始候选转换，不从标准集复制；reference_value 是评估目标。",
                  "unit_converted_exact 表示换算公式确定，不等于标准值零误差，也不代表样品匹配。",
                  "同一标准记录保留全部观测；多样品不作为失败。原批次文件未覆盖。",
                  "不再生成 strict_dataset 或 dataset；旧样品审计状态仅作为附加字段。"],
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    lines = ["# 性质和值出口报告", "", manifest["definition"], "", "| 指标 | 数量 |", "|---|---:|"]
    lines += [f"| {key} | {value} |" for key, value in counts.items()]
    lines += ["", "| 确定性拆分 | 标准记录数 |", "|---|---:|"]
    lines += [f"| {key} | {value} |" for key, value in split_counts.items()]
    lines += ["", f"性质和值覆盖：{len(final)} / {len(rows)} = {len(final)/len(rows):.2%}", "",
              "| 单位状态 | 标准记录数 |", "|---|---:|"]
    lines += [f"| {key} | {value} |" for key, value in units.items()]
    lines += ["", *manifest["notes"], "", "样品状态仅供参考，不参与上述覆盖率或出口门禁。", ""]
    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return manifest


def build_measurement_export(publication_root: Path, output_dir: Path) -> dict:
    """Use only the new publication contract; never fall back to legacy final.json."""
    publication_root, output_dir = publication_root.resolve(), output_dir.resolve()
    if output_dir.exists():
        raise ValueError("Output already exists")
    if output_dir == publication_root or publication_root in output_dir.parents or output_dir in publication_root.parents:
        raise ValueError("Output must be separate from publication inputs")
    files = sorted(publication_root.glob("reference_no_*/measurement_publication.json"))
    if not files:
        raise ValueError("No gated measurement publication files; legacy final.json is not a fallback")
    snapshots, exported, seen = {}, {s: [] for s in ("final", "candidate", "not_publishable", "raw_candidate")}, set()
    per_document = []
    for path in files:
        snapshots[path] = path.read_bytes()
        data = json.loads(snapshots[path])
        doc = path.parent.name
        if data.get("schema_version") != "measurement_publication.v1" or data.get("document_id") != doc:
            raise ValueError("Publication schema or document mismatch")
        counts = {}
        for status in ("final", "candidate", "not_publishable"):
            groups = data.get(status, [])
            if data.get("counts", {}).get(status) != len(groups):
                raise ValueError("Publication count mismatch")
            counts[status] = len(groups)
            for group in groups:
                identity = (doc, group["measurement_id"])
                if identity in seen:
                    raise ValueError("Duplicate measurement identity")
                seen.add(identity)
                if group.get("publication_status") != status:
                    raise ValueError("Measurement collection/status mismatch")
                if status == "final":
                    record = MeasurementRecord.model_validate(group["record"])
                    members = group.get("members") or []
                    if (record.publication_status != "final" or record.measurement_id != group["measurement_id"]
                            or group.get("publication_reasons") or group.get("review_reasons") or not members
                            or record.standard_status not in {"standard_exact", "standard_alias"}
                            or not record.standard_property_code or not record.source_cell_ids
                            or record.binding_status not in {"resolved", "article_alias_confirmed", "entity_only"}):
                        raise ValueError("Final measurement gate is inconsistent")
                    for member in members:
                        audit = member.get("audit") or {}
                        from stages.binding_publication import binding_publication_options
                        options = binding_publication_options(audit)
                        if ((record.binding_status == "article_alias_confirmed" and not options["allow_article_alias"])
                                or (record.binding_status == "entity_only" and not options["allow_entity_only"])
                                or audit.get("binding_status") != record.binding_status
                                or audit.get("article_sample_key") != record.article_sample_key):
                            raise ValueError("Final measurement identity proof is inconsistent")
                        if (audit.get("publication_status") != "final" or audit.get("publication_reasons")
                                or audit.get("input_complete") is not True
                                or audit.get("unit_status") not in {"confirmed", "unit_equivalent", "unit_converted_exact"}
                                or audit.get("evidence_status") != "source_cell_verified"
                                or sorted(audit.get("source_cell_ids") or []) != sorted(record.source_cell_ids)
                                or audit.get("standard_property_code") != record.standard_property_code
                                or audit.get("sample_id") != record.sample_id
                                or audit.get("entity_id") != record.entity_id
                                or (audit.get("source_condition_context") or {}) != record.source_condition_context
                                or audit.get("unit_raw", (member.get("original_record") or {}).get("unit_raw")) != record.unit_raw
                                or (record.unit_normalized is not None and audit.get("unit_normalized") != record.unit_normalized)
                                or str(audit.get("value_raw")) != record.value_raw):
                            raise ValueError("Final measurement member proof is inconsistent")
                    exported[status].append({"document_id": doc, **record.model_dump(mode="json"),
                                             "source_claims": group["members"]})
                else:
                    exported[status].append({"document_id": doc, **group})
        ledger = data.get("raw_candidate_ledger") or {}
        for row in ledger.get("records", []):
            if row.get("publication_status") == "final":
                raise ValueError("Raw preview candidate cannot enter final export")
            exported["raw_candidate"].append({"document_id": doc, **row})
        per_document.append({"document_id": doc, **counts, "raw_candidate": len(ledger.get("records", []))})
    for path in sorted(publication_root.glob("reference_no_*/raw_candidate_ledger.json")):
        snapshots[path] = path.read_bytes()
        ledger = json.loads(snapshots[path])
        doc = path.parent.name
        if (ledger.get("schema_version") != "raw_measurement_ledger.v1" or ledger.get("document_id") != doc
                or doc in {r["document_id"] for r in per_document}):
            raise ValueError("Standalone raw ledger document mismatch or duplicate")
        for row in ledger.get("records", []):
            if row.get("publication_status") == "final":
                raise ValueError("Raw preview candidate cannot enter final export")
            exported["raw_candidate"].append({"document_id": doc, **row})
    summary_path = publication_root / "summary.json"
    missing = []
    if summary_path.is_file():
        snapshots[summary_path] = summary_path.read_bytes()
        summary = json.loads(snapshots[summary_path])
        if summary.get("original_inputs_unchanged") is not True:
            raise ValueError("Batch input integrity was not confirmed")
        present = {r["document_id"] for r in per_document}
        for row in summary.get("documents", []):
            if row.get("status") == "published" and row["document_id"] not in present:
                raise ValueError("Published document file is missing")
            if row.get("status") != "published":
                if row["document_id"] in present:
                    raise ValueError("Failed document contains stale publication output")
                missing.append({k: row[k] for k in ("document_id", "status", "missing_inputs", "error_type") if k in row})
        if present - {r["document_id"] for r in summary.get("documents", [])}:
            raise ValueError("Publication document is absent from batch manifest")
    if any(p.read_bytes() != content for p, content in snapshots.items()):
        raise ValueError("Publication input changed during export")
    output_dir.mkdir(parents=True)
    for status, rows in exported.items():
        _write_jsonl(output_dir / f"{status}_measurements.jsonl", rows)
    manifest = {"schema_version": "production_measurement_export.v1", "counts": {k: len(v) for k, v in exported.items()},
                "per_document": per_document, "unavailable_documents": missing, "original_inputs_unchanged": True,
                "input_hashes": {str(p): hashlib.sha256(c).hexdigest() for p, c in snapshots.items()},
                "api_requests": 0, "definition": "正式出口仅 final_measurements.jsonl；候选、阻断及历史原始候选分别保留。不读取标准答案，不回退旧 final.json。"}
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 正式测量导出", "", manifest["definition"], "", "|集合|数量|", "|---|---:|"]
    lines += [f"|{k}|{v}|" for k, v in manifest["counts"].items()]
    lines += ["", f"有发布文件文献：{len(per_document)}；批次缺失或失败文献：{len(missing)}。",
              "原输入哈希复核通过；API 请求数 0。原始候选表达数不等于独立测量数，来源去重关系保留在各文献 measurement_publication.json。"]
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--publication-root", type=Path)
    inputs.add_argument("--alignment-dir", type=Path)
    parser.add_argument("--legacy-value-only", action="store_true", help="显式选择历史值捕获诊断，不是正式测量出口")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--view", choices=("source", "standardized"), default="source", help="默认导出原文抽取；standardized 保留旧严格出口")
    parser.add_argument("--diagnostics-jsonl", type=Path)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.publication_root:
        if args.legacy_value_only or args.diagnostics_jsonl:
            parser.error("正式测量出口不接受历史值诊断参数")
        if args.view == "standardized":
            result = build_measurement_export(args.publication_root, args.output_dir)
        else:
            from tools.source_extraction_export import build_source_export
            result = build_source_export(args.publication_root, args.output_dir)
    else:
        if not args.legacy_value_only:
            parser.error("旧值捕获模式需显式 --legacy-value-only；正式出口请使用 --publication-root")
        result = build_export(args.alignment_dir, args.output_dir, args.diagnostics_jsonl)
    print(json.dumps(result["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
