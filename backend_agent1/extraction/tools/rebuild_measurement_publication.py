"""Rebuild Stage6 and gated measurements in a new directory, without model calls."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from stages.stage6_validate_merge import run_stage6
from stages.raw_measurement_candidates import build_raw_candidate_ledger
from stages.source_table_extraction import build_source_extraction
from tools.source_extraction_export import render_source_report


STAGE_FILES = ("stage0_blocks.json", "stage1_mentions.json", "stage2_entities.json",
               "stage3_process.json", "stage4_properties.json", "stage5_characterizations.json")


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rebuild(input_root, output_root, *, stage4_root=None, origin_trace_root=None):
    input_root, output_root = Path(input_root).resolve(), Path(output_root).resolve()
    roots = [input_root] + [Path(p).resolve() for p in (stage4_root, origin_trace_root) if p is not None]
    if output_root.exists():
        raise ValueError("Output already exists")
    if any(output_root == p or p in output_root.parents or output_root in p.parents for p in roots):
        raise ValueError("Output must be separate from input directories")
    documents = sorted(p for p in input_root.glob("reference_no_*") if p.is_dir())
    if not documents:
        raise ValueError("No input documents")
    # Freeze all discovered inputs before processing any document.
    jobs, hashes = [], {}
    for base in documents:
        paths = [base / name for name in STAGE_FILES]
        override = Path(stage4_root) / base.name / STAGE_FILES[4] if stage4_root else None
        if override is not None and override.is_file():
            paths[4] = override
        trace = paths[4].with_name("stage4_request_trace.json")
        origin = Path(origin_trace_root) / base.name / "stage4_request_trace.json" if origin_trace_root else None
        extra = [base / name for name in ("stage5_shards.json", "stage4t_shadow.json", "stage4_properties.unified_preview.json", "stage4r_unified_audit.json")] + [trace] + ([origin] if origin else [])
        for path in paths + extra:
            if path.is_file():
                hashes[str(path.resolve())] = _hash(path)
        jobs.append((base.name, paths, trace, origin))
    output_root.mkdir(parents=True)
    rows, queue, raw_queue = [], [], []
    def collect_raw(doc, ledger):
        raw_queue.extend({"document_id": doc, "measurement_id": r["measurement_id"], "source_stage": r["source_stage"],
                          "source_cell_ids": r["source_cell_ids"], "source_occurrences": r["source_occurrences"],
                          "review_route": r["review_route"], "source_roles": r["source_roles"],
                          "source_context": r["source_context"],
                          "publication_status": r["publication_status"], "reasons": r["publication_reasons"]} for r in ledger["records"])

    for doc, paths, trace, origin in jobs:
        row = {"document_id": doc, "stage4_input": str(paths[4].resolve()),
               "missing_inputs": [p.name for p in paths if not p.is_file()]}
        if row["missing_inputs"]:
            row["status"] = "missing_input"
            if paths[0].is_file():
                def read_optional(path):
                    return json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else None
                try:
                    ledger = build_raw_candidate_ledger(read_optional(paths[0]), read_optional(paths[2]), read_optional(paths[3]),
                        stage4t=read_optional(paths[0].with_name("stage4t_shadow.json")),
                        stage4r=read_optional(paths[0].with_name("stage4_properties.unified_preview.json")),
                        stage4r_audit=read_optional(paths[0].with_name("stage4r_unified_audit.json")))
                    out = output_root / doc
                    out.mkdir()
                    (out / "raw_candidate_ledger.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
                    row["raw_candidate_counts"] = ledger["counts"]
                    collect_raw(doc, ledger)
                except (ValueError, TypeError, KeyError) as exc:
                    row["raw_candidate_error_type"] = type(exc).__name__
        else:
            out = output_root / doc
            try:
                validation, published = run_stage6(doc, *paths, out / "stage6_validation.json", out / "final.json",
                    preview=True, stage4_trace_path=trace, stage4_origin_trace_path=origin)
                row.update(status="published" if published else "validation_failed", validation_status=validation.status,
                           validation_error_count=validation.error_count)
                if published:
                    data = json.loads((out / "measurement_publication.json").read_text(encoding="utf-8"))
                    row.update(counts=data["counts"], series_input_proof=data["series_input_proof"],
                               raw_candidate_counts=data["raw_candidate_ledger"]["counts"], source_cell_group_count=len(data["source_cell_groups"]),
                               reason_counts=dict(Counter(r for status in ("candidate", "not_publishable")
                                   for g in data[status] for r in g["publication_reasons"])))
                    collect_raw(doc, data["raw_candidate_ledger"])
                    for status in ("candidate", "not_publishable"):
                        for group in data[status]:
                            queue.append({"document_id": doc, "measurement_id": group["measurement_id"],
                                "publication_status": status, "reasons": group["publication_reasons"],
                                "identity": group["identity"], "members": [{k: m[k] for k in ("collection", "object_id", "source_stage")} for m in group["members"]]})
            except Exception as exc:
                # Error type is enough to locate a failed job without dumping input text.
                row.update(status="execution_failed", error_type=type(exc).__name__)
        source_path = output_root / doc / "source_extraction.json"
        try:
            if not source_path.is_file() and paths[0].is_file():
                source = json.loads(paths[0].read_text(encoding="utf-8-sig"))
                if source.get("document_id") != doc:
                    raise ValueError("Source document mismatch")
                ledger_path = source_path.with_name("raw_candidate_ledger.json")
                publication = {"document_id": doc, "raw_candidate_ledger": json.loads(ledger_path.read_text(encoding="utf-8"))} if ledger_path.is_file() else None
                extracted = build_source_extraction(source, publication)
                source_path.parent.mkdir(parents=True, exist_ok=True)
                source_path.write_text(json.dumps(extracted, ensure_ascii=False, indent=2), encoding="utf-8")
                render_source_report(extracted, source_path.with_name("report.html"))
            if source_path.is_file():
                row["source_counts"] = json.loads(source_path.read_text(encoding="utf-8"))["counts"]
                row["source_status"] = "source_rechecked"
            else:
                row["source_status"] = "source_missing"
        except (OSError, ValueError, TypeError, KeyError) as exc:
            row.update(source_status="source_failed", source_error_type=type(exc).__name__)
        rows.append(row)
        print(json.dumps({k: row[k] for k in ("document_id", "status", "counts", "error_type") if k in row}), flush=True)
    unchanged = all(Path(p).is_file() and _hash(Path(p)) == h for p, h in hashes.items())
    total, source_total = Counter(), Counter()
    for row in rows:
        total.update(row.get("counts", {}))
        source_total.update(row.get("source_counts", {}))
    raw_totals = Counter()
    route_totals = Counter()
    context_totals = Counter()
    comparison_totals = Counter()
    for row in rows:
        raw_totals.update({k: v for k, v in row.get("raw_candidate_counts", {}).items() if isinstance(v, int)})
        route_totals.update(row.get("raw_candidate_counts", {}).get("review_route_counts", {}))
        context_totals.update(row.get("raw_candidate_counts", {}).get("source_context_status_counts", {}))
        comparison_totals.update(row.get("raw_candidate_counts", {}).get("condition_comparison_status_counts", {}))
    code_root = Path(__file__).resolve().parents[1]
    rules = list((code_root / "stages").glob("*.py")) + [code_root / "schema/polymer_schema.py", code_root / "config/standard_property_codes.v1.json", code_root / "config/source_table_reviews.v1.json", code_root / "config/source_text_reviews.v1.json", code_root / "config/source_sample_alias_reviews.v1.json", code_root / "tools/source_extraction_export.py", Path(__file__).resolve()]
    summary = {"schema_version": "measurement_publication_rebuild.v1", "documents": rows,
               "default_view": "source_extraction", "source_counts": dict(source_total),
               "source_status_counts": dict(Counter(r["source_status"] for r in rows)),
               "document_status_counts": dict(Counter(r["status"] for r in rows)), "counts": dict(total),
               "raw_candidate_counts": dict(raw_totals),
               "raw_candidate_review_route_counts": dict(route_totals),
               "raw_candidate_source_context_status_counts": dict(context_totals),
               "raw_candidate_condition_comparison_status_counts": dict(comparison_totals),
               "input_hashes": hashes, "original_inputs_unchanged": unchanged, "api_requests": 0,
               "rule_hashes": {str(p.relative_to(code_root)): _hash(p) for p in rules},
               "scope": "Stage6 scalars and Stage4 points; historical Stage4T/R claims are retained in a linked, uncertified candidate ledger."}
    (output_root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_root / "review_queue.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in queue), encoding="utf-8")
    (output_root / "raw_candidate_review_queue.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in raw_queue), encoding="utf-8")
    lines = ["# 原文抽取与兼容发布回归", "", f"默认入口：各文章 report.html / source_extraction.json。原文抽取汇总：{dict(source_total)}。数量按来源格计，复合格不等于独立测量数。",
             "", "以下表格为旧严格口径的兼容统计，其阻断不再影响原文抽取结果。严格正式测量请读取 measurement_publication.json 的 final 集合；旧格式 final.json 保留原有表达。",
             "", "范围：Stage6 标量集合和 Stage4 系列点；Stage4T/R 历史候选在关联台账保留并核对来源，未认证为正式记录。源单元格只索引一次，各层表达不相加当独立测量数。",
             "", "|文章|运行状态|正式|待核|阻断|聚合摘要|", "|---|---|---:|---:|---:|---:|"]
    for row in rows:
        counts = row.get("counts", {})
        lines.append(f"|{row['document_id']}|{row['status']}|{counts.get('final', '—')}|{counts.get('candidate', '—')}|{counts.get('not_publishable', '—')}|{counts.get('aggregate_count', '—')}|")
    lines += ["", f"主发布集合：{dict(total)}", "", f"历史候选台账：{dict(raw_totals)}；其表达数不能与主集合相加当独立测量数。", "", f"原输入未变化：{unchanged}；API 请求数：0。", "",
              f"历史候选复核分流：{dict(route_totals)}。context_review 核对条件/组成上下文；identity_review 核对样品轴；property_review 核对性质；source_review 先核对来源；header_review/role_review 核对表头或未明角色。分流不删除候选、不改变发布资格。", "",
              f"源表条件/组成关联：{dict(context_totals)}。source_aligned 仅表示表格位置关联；candidate 包含推断表头等待核情况，ambiguous 保留跨行歧义。原始条件值、表头及来源格均保留，与模型声明分开保存；具体核对结果见下项。", "",
              f"显式剂量条件核对：{dict(comparison_totals)}。仅比较具名剂量字段及明确的 Gy/kGy 数值；推断表头不直接确认匹配或冲突。declaration_missing 指缺少具名剂量字段，不代表原始响应所有文本都没提到剂量。结果不改写模型条件或发布资格。", "",
              "系列点缺少真实请求证明时继续阻断；不能用事后重建请求证明历史调用。聚合摘要、隔离候选和 Stage6 拒绝对象分别保留，不重复计入测量数。",
              "", "主集合待核和阻断清单：review_queue.jsonl；历史候选队列：raw_candidate_review_queue.jsonl。逐篇缺失输入、完整性证明和原因统计：summary.json。"]
    (output_root / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if not unchanged:
        raise ValueError("Inputs changed during rebuild; output must not be accepted")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--stage4-root", type=Path)
    parser.add_argument("--origin-trace-root", type=Path)
    args = parser.parse_args()
    result = rebuild(**vars(args))
    print(json.dumps({"counts": result["counts"], "documents": result["document_status_counts"]}))
    return int(any(r["status"] != "published" for r in result["documents"]))


if __name__ == "__main__":
    raise SystemExit(main())
