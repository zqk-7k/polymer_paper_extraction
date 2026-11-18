"""Trace response values into Stage4 scalars/series without certifying correctness."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from schema.polymer_schema import Stage0Element
from stages.table_grid import resolve_table_locator
from stages.standard_mapping import normalize_source_notation
from stages.request_trace import content_hash


def _records(payload):
    for collection in ("properties", "unresolved_properties", "specialized_property_observations", "property_series"):
        for index, item in enumerate(payload.get(collection, [])):
            if collection != "property_series":
                yield {"collection": collection, "index": index}, item
            else:
                for point_index, point in enumerate(item.get("points", [])):
                    yield {"collection": collection, "index": index, "point_index": point_index}, {
                        "property_name_raw": item.get("property_name_raw"),
                        "unit_raw": item.get("unit_raw"), "sample_id": item.get("sample_id"),
                        "entity_id": item.get("entity_id"), "measurement_context": item.get("measurement_context"),
                        **point,
                    }


def _anchors(item, blocks):
    evidence = item.get("evidence") or []
    if isinstance(evidence, dict):
        evidence = [evidence]
    anchors = set()
    for entry in evidence:
        bid = entry.get("block_id")
        if bid not in blocks:
            continue
        block = blocks[bid]
        locator = entry.get("table_locator")
        if block.type == "table" and locator:
            resolved = resolve_table_locator(block, locator)
            if resolved:
                # Condition or sample-label cells do not identify the value.
                value = "" if item.get("value_raw") is None else str(item["value_raw"]).strip()
                cell_value = "" if locator.get("cell_value") is None else str(locator["cell_value"]).strip()
                if value and value == cell_value:
                    anchors.add((bid, resolved["cell_id"]))
        elif block.type != "table":
            quote = entry.get("source_sentence")
            if quote and quote in (block.text or block.caption or ""):
                anchors.add((bid, quote))
    return sorted(anchors)


def trace_records(response: dict, output: dict, stage0: dict) -> dict:
    blocks = {b["block_id"]: Stage0Element.model_validate(b) for b in stage0.get("elements", [])}
    source_rows = list(_records(response))
    object_id = lambda item: item.get("property_id") or item.get("unresolved_id") or item.get("specialized_id") or item.get("point_id")
    identity_counts = Counter((ref["collection"], object_id(item)) for ref, item in source_rows)
    quarantined = defaultdict(list)
    for warning in output.get("warnings", []):
        if warning.get("code") == "preview_objects_quarantined":
            for rejected in warning.get("objects", []):
                quarantined[(rejected.get("collection"), rejected.get("object_id"))].append(rejected["reason"])
    destinations = defaultdict(list)
    for ref, item in _records(output):
        for anchor in _anchors(item, blocks):
            destinations[(anchor, str(item.get("value_raw")))].append((ref, item))
    rows = []
    for ref, item in source_rows:
        anchors = _anchors(item, blocks)
        candidates = {}
        for anchor in anchors:
            for target_ref, target in destinations.get((anchor, str(item.get("value_raw"))), []):
                candidates[json.dumps(target_ref, sort_keys=True)] = (target_ref, target)
        row = {"source_record": ref, "property_name_raw": item.get("property_name_raw"),
               "value_raw": item.get("value_raw"), "source_anchors": anchors,
               "destination_records": [], "changed_fields": []}
        key = (ref["collection"], object_id(item))
        if identity_counts[key] == 1 and key in quarantined:
            row["status"] = "quarantined_requires_review"
            row["quarantine_reasons"] = quarantined[key]
        elif not anchors:
            row["status"] = "source_anchor_unverified"
        elif not candidates:
            row["status"] = "destination_not_found_requires_review"
        elif len(candidates) > 1:
            row["status"] = "multiple_destinations_requires_review"
            row["destination_records"] = [value[0] for value in candidates.values()]
        else:
            target_ref, target = next(iter(candidates.values()))
            row["destination_records"] = [target_ref]
            for field in ("property_name_raw", "unit_raw", "sample_id", "entity_id", "measurement_context", "coordinates", "determination_method_raw", "measurement_condition_id"):
                old, new = item.get(field), target.get(field)
                if old != new:
                    row["changed_fields"].append({"field": field, "before": old, "after": new})
            same_name = normalize_source_notation(item.get("property_name_raw")) == normalize_source_notation(target.get("property_name_raw"))
            semantic_changes = [c for c in row["changed_fields"] if c["field"] != "property_name_raw" or not same_name]
            row["status"] = ("same_source_value_fields_changed" if semantic_changes else
                             "represented_as_series_point" if target_ref["collection"] == "property_series" and ref["collection"] != "property_series" else
                             "retained_notation_normalized" if row["changed_fields"] else "retained_checked_fields")
        rows.append(row)
    return {"schema_version": "stage4_record_lineage.v1", "document_id": stage0.get("document_id"),
            "definition": "来源与值的去向核对，包含系列点；字段一致不代表语义正确或可发布。未匹配不等于确认丢失。",
            "input_hashes": {"response": content_hash(response), "output": content_hash(output), "stage0": content_hash(stage0)},
            "response_record_count": len(rows), "output_record_count": sum(1 for _ in _records(output)),
            "status_counts": dict(Counter(row["status"] for row in rows)), "records": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--stage4", type=Path, required=True)
    parser.add_argument("--stage0", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Report already exists")
    read = lambda p: json.loads(p.read_text(encoding="utf-8"))
    trace, output, stage0 = read(args.trace), read(args.stage4), read(args.stage0)
    if trace.get("schema_version") != "stage4_request_trace.v1" or trace.get("output_sha256") != content_hash(output):
        raise ValueError("Trace/output mismatch")
    if trace.get("document_id") != stage0.get("document_id"):
        raise ValueError("Document mismatch")
    from stages.stage4_property import load_stage0_document
    if trace.get("input_model_hashes", {}).get("stage0") != content_hash(load_stage0_document(args.stage0).model_dump(mode="json")):
        raise ValueError("Stage0 input changed since request")
    last = (trace.get("attempts") or [{}])[-1]
    response = last.get("parsed_response")
    if response is None or last.get("parsed_response_sha256") != content_hash(response):
        raise ValueError("No verified parsed response available")
    result = trace_records(response, output, stage0)
    result["trace_id"] = trace["trace_id"]
    result["mode"] = trace["mode"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["status_counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
