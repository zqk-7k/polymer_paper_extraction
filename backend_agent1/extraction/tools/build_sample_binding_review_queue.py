"""Build an offline, grouped manual queue for unresolved sample bindings."""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


def _read_jsonl(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def _priority(packet: dict) -> tuple[int, str]:
    status = packet["deterministic_binding"].get("sample_binding_status")
    reasons = set(packet.get("failure_reasons") or [])
    if "candidate_sample_conflict" in reasons or status == "ambiguous":
        rank = 0
    elif status == "unresolved" and packet.get("evidence_paths"):
        rank = 1
    elif status == "unresolved":
        rank = 2
    else:
        rank = 3
    return rank, packet["review_id"]


def _record(packet: dict) -> dict:
    binding = packet["deterministic_binding"]
    paths = packet.get("evidence_paths") or []
    candidate = packet.get("candidate") or {}
    tables = sorted({p.get("table_id") for p in paths if p.get("table_id")})
    targets = sorted({p.get("target_cell_id") for p in paths if p.get("target_cell_id")})
    axes = sorted({cell for p in paths for cell in p.get("axis_cell_ids", [])})
    group_rows = sorted({cell for p in paths for cell in p.get("group_row_cell_ids", [])})
    observed = sorted(set(binding.get("observed_labels") or []))
    reasons = sorted(set(packet.get("failure_reasons") or []))
    return {
        "priority": _priority(packet)[0],
        "document_id": packet.get("document_id"),
        "review_id": packet.get("review_id"),
        "property_id": packet.get("property_id"),
        "source_collection": packet.get("source_collection"),
        "property_name": packet.get("property_name"),
        "value_raw": packet.get("value_raw"),
        "unit_raw": packet.get("unit_raw"),
        "sample_binding_status": binding.get("sample_binding_status"),
        "binding_status": binding.get("binding_status"),
        "candidate_sample_id": packet.get("sample_id_candidate"),
        "candidate_entity_id": candidate.get("entity_id"),
        "sample_candidate_ids": ";".join(binding.get("sample_candidate_ids") or []),
        "observed_labels": " | ".join(observed),
        "failure_reasons": ";".join(reasons),
        "table_ids": ";".join(tables),
        "target_cell_ids": ";".join(targets),
        "axis_cell_ids": ";".join(axes),
        "group_row_cell_ids": ";".join(group_rows),
        "has_source_evidence": bool(packet.get("source_evidence")),
    }


def build_queue(input_dir: Path, output_dir: Path) -> dict:
    rows: list[dict] = []
    errors = []
    for packet_path in sorted(input_dir.glob("reference_no_*/sample_binding_evidence_packets.jsonl")):
        try:
            for packet in _read_jsonl(packet_path):
                status = packet.get("deterministic_binding", {}).get("sample_binding_status")
                if status in {"ambiguous", "unresolved"}:
                    rows.append(_record(packet))
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            errors.append({"path": str(packet_path), "error_type": type(exc).__name__})
    rows.sort(key=lambda row: (row["priority"], row["document_id"], row["table_ids"], row["review_id"]))
    output_dir.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else ["priority", "document_id", "review_id"]
    with (output_dir / "sample_binding_manual_review_queue.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    (output_dir / "sample_binding_manual_review_queue.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
    )
    by_doc = defaultdict(list)
    by_table = Counter()
    for row in rows:
        by_doc[row["document_id"]].append(row)
        for table in filter(None, row["table_ids"].split(";")):
            by_table[(row["document_id"], table)] += 1
    summary = {
        "schema_version": "sample_binding_manual_review_queue.v1",
        "source_dir": str(input_dir.resolve()),
        "output_dir": str(output_dir.resolve()),
        "candidate_count": len(rows),
        "status_counts": dict(Counter(row["sample_binding_status"] for row in rows)),
        "priority_counts": dict(Counter(str(row["priority"]) for row in rows)),
        "documents": len(by_doc),
        "tables_with_queue_items": len(by_table),
        "source_evidence_count": sum(bool(row["has_source_evidence"]) for row in rows),
        "errors": errors,
        "per_document": {
            doc: {"count": len(items), "status_counts": dict(Counter(x["sample_binding_status"] for x in items)),
                  "priority_counts": dict(Counter(str(x["priority"]) for x in items))}
            for doc, items in sorted(by_doc.items())
        },
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 样品绑定人工审阅队列", "", "该队列完全由现有证据包生成，不调用 API，也不改变抽取结果。", "",
             f"候选数：{len(rows)}；文章数：{len(by_doc)}；含来源证据：{summary['source_evidence_count']}", "",
             "优先级：0=歧义/冲突，1=有表格证据但未解析，2=无可用表格证据，3=其他待核。", "",
             "| 文献 | 待审候选 | 歧义 | 未解析 |", "|---|---:|---:|---:|"]
    for doc, items in sorted(by_doc.items()):
        counts = Counter(x["sample_binding_status"] for x in items)
        lines.append(f"| {doc} | {len(items)} | {counts.get('ambiguous', 0)} | {counts.get('unresolved', 0)} |")
    (output_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_queue(args.input_dir, args.output_dir), ensure_ascii=False))


if __name__ == "__main__":
    main()
