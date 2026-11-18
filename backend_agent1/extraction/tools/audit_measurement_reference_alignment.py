"""Compare frozen reference rows to gated measurements, never infer GT sample IDs."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from stages.final_unit_conversion import enrich_observation, match_reference
from tools.reference_sample_crosswalk import identity_match, load_crosswalk


def compare_reference(expected, publication, crosswalk=None):
    code = expected.get("standard_property_code")
    result = {k: expected.get(k) for k in ("standard_record_id", "reference_no", "article_sample_id", "standard_property_code")}
    result.update(published_value_matches=[], unpublished_value_matches=[], raw_unit_unverified_matches=[],
                  reference_sample_status="crosswalk_missing", fully_verified_match=False)
    entry = (crosswalk or {}).get((expected.get("reference_no"), expected.get("article_sample_id")))
    result["reference_sample_status"] = entry["status"] if entry else "crosswalk_missing"
    result["identity_verified_value_matches"] = []
    if publication is None:
        result["status"] = "publication_input_missing"
        return result
    if publication.get("schema_version") != "measurement_publication.v1" or publication.get("document_id") != expected.get("reference_no"):
        raise ValueError("Publication schema or document mismatch")
    if not code:
        result["status"] = "reference_mapping_unresolved"
        return result
    for status in ("final", "candidate", "not_publishable"):
        for group in publication.get(status, []):
            record = group.get("record") or {}
            if record.get("standard_property_code") != code:
                continue
            # Only source values are converted. Reference numbers never enrich a record.
            observation = enrich_observation(record, expected.get("reviewed_unit"), code)
            match = match_reference(expected, observation)
            if match is None:
                continue
            known_units = bool(expected.get("reviewed_unit")) and observation.get("unit_conversion_status") in {"unit_equivalent", "unit_converted_exact"}
            target = ("published_value_matches" if status == "final" else "unpublished_value_matches") if known_units else "raw_unit_unverified_matches"
            result[target].append({"measurement_id": group["measurement_id"], "publication_status": status,
                                   "sample_id": record.get("sample_id"), "source_cell_ids": record.get("source_cell_ids", []),
                                   "value_comparison": match, "conversion_status": observation.get("unit_conversion_status"),
                                   "conversion_factor": observation.get("conversion_factor"), "conversion_offset": observation.get("conversion_offset")})
            if known_units and identity_match(record, entry):
                result["identity_verified_value_matches"].append({"measurement_id": group["measurement_id"], "publication_status": status})
    result["status"] = ("published_value_match_sample_unverified" if result["published_value_matches"] else
                        "unpublished_value_match" if result["unpublished_value_matches"] else
                        "unit_review_required" if result["raw_unit_unverified_matches"] else "no_qualified_measurement_match")
    if any(m["publication_status"] == "final" for m in result["identity_verified_value_matches"]):
        result["status"] = "published_identity_value_match_conditions_unverified"
    elif result["identity_verified_value_matches"]:
        result["status"] = "unpublished_identity_value_match"
    return result


def audit(reference_rows, publication_root, output_root, sample_crosswalk=None):
    reference_rows, publication_root, output_root = [Path(p).resolve() for p in (reference_rows, publication_root, output_root)]
    if output_root.exists():
        raise ValueError("Output already exists")
    if publication_root in output_root.parents or output_root in publication_root.parents or output_root in reference_rows.parents:
        raise ValueError("Output must be separate from inputs")
    snapshots = {reference_rows: reference_rows.read_bytes()}
    crosswalk = {}
    if sample_crosswalk is not None:
        crosswalk, identity_sources = load_crosswalk(sample_crosswalk)
        snapshots.update(identity_sources)
    rows = [json.loads(line) for line in snapshots[reference_rows].decode("utf-8-sig").splitlines() if line.strip()]
    if len({r["standard_record_id"] for r in rows}) != len(rows):
        raise ValueError("Duplicate reference IDs")
    publications = {}
    # Enumerate existing outputs instead of constructing paths from reference text.
    for path in sorted(publication_root.glob("reference_no_*/measurement_publication.json")):
        snapshots[path] = path.read_bytes()
        data = json.loads(snapshots[path])
        if data.get("document_id") != path.parent.name:
            raise ValueError("Mixed publication documents")
        publications[path.parent.name] = data
    results = [compare_reference(row, publications.get(row["reference_no"]), crosswalk) for row in rows]
    if any(p.read_bytes() != content for p, content in snapshots.items()):
        raise ValueError("Input changed during reference comparison")
    summary = {"schema_version": "measurement_reference_alignment.v1", "reference_records": len(rows),
               "reference_documents": len({r["reference_no"] for r in rows}), "publication_documents": len(publications),
               "status_counts": dict(Counter(r["status"] for r in results)), "fully_verified_matches": 0,
               "reference_sample_status_counts": dict(Counter(r["reference_sample_status"] for r in results)),
               "identity_verified_value_match_rows": sum(bool(r["identity_verified_value_matches"]) for r in results),
               "published_identity_verified_value_match_rows": sum(any(m["publication_status"] == "final" for m in r["identity_verified_value_matches"]) for r in results),
               "input_hashes": {str(p): hashlib.sha256(c).hexdigest() for p, c in snapshots.items()},
               "original_inputs_unchanged": True, "api_requests": 0,
               "definition": "同文献、标准性质、已确认单位换算后的值比较；可选独立样品对应仅接受经复核、来源哈希锁定的名称和制备条件证明。身份和值匹配不代表全部测量条件吻合，不报告完整匹配率或全量样品准确率。"}
    output_root.mkdir(parents=True)
    (output_root / "alignment.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in results), encoding="utf-8")
    (output_root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 冻结标准记录与正式测量集合对照", "", summary["definition"], "",
             f"标准记录：{len(rows)}；标准文献：{summary['reference_documents']}；有发布文件文献：{len(publications)}。",
             "", "|对照状态|记录数|", "|---|---:|"]
    lines += [f"|{k}|{v}|" for k, v in sorted(summary["status_counts"].items())]
    lines += ["", f"独立样品对应覆盖：{summary['reference_sample_status_counts']}。",
              f"身份及值匹配的标准行：{summary['identity_verified_value_match_rows']}；其中正式发布：{summary['published_identity_verified_value_match_rows']}。"]
    lines += ["", "published_value_match_sample_unverified 仅表示正式集合中存在兼容性质和值，不表示标准样品身份已匹配。",
              "计数按标准记录行计算，多行可能命中同一测量，不代表独立测量数。",
              "no_qualified_measurement_match 仅针对本次统一测量集合，不等于原文或所有过程候选没有捕获。",
              "unit_review_required 不计作单位确认的匹配。完整逐条结果见 alignment.jsonl。",
              "", "原输入哈希复核通过；API 请求数 0；未使用标准答案回填生产记录。"]
    (output_root / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-rows", type=Path, required=True)
    parser.add_argument("--publication-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--sample-crosswalk", type=Path)
    print(json.dumps(audit(**vars(parser.parse_args()))["status_counts"]))


if __name__ == "__main__":
    main()
