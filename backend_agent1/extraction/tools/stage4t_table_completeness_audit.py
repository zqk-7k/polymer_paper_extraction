# -*- coding: utf-8 -*-
"""Audit Stage4T table columns against the unified Preview candidates."""
import argparse
import json
import os
from collections import Counter

from tools.polyinfo_coverage_matcher import (
    classify_pred,
    classify_surface_component,
    extract_evidence_labels,
)


def _column_bucket(candidate):
    unit = candidate.get("unit_normalized") or candidate.get("unit_raw") or ""
    header = candidate.get("property_name_raw")
    if header:
        bucket = classify_pred(header, unit)
        if bucket is not None:
            return bucket, classify_surface_component(header)
    parts = [
        candidate.get("property_name_normalized"),
        candidate.get("semantic_label"),
    ]
    name = " ".join(str(value or "") for value in parts).strip()
    return classify_pred(name, unit), classify_surface_component(name)


def _iter_final_objects(final_payload):
    for key in (
        "properties",
        "property_observations",
        "unresolved_properties",
        "unresolved_property_observations",
        "specialized_property_observations",
    ):
        for obj in final_payload.get(key) or []:
            yield key, obj
    for series in final_payload.get("property_series") or []:
        yield "property_series", series
        for point in series.get("points") or []:
            yield "property_series", point


def _object_bucket(obj):
    # For table-backed candidates, the evidence column label is the strongest
    # property identity. Metadata such as ``variant=mass_loss_threshold`` must
    # not override a header that explicitly says ``T_d``.
    labels = extract_evidence_labels(obj.get("evidence"))
    unit = obj.get("unit_normalized") or obj.get("unit_raw") or ""
    for label in labels:
        bucket = classify_pred(label, unit)
        if bucket is not None:
            return bucket, classify_surface_component(label)
    parts = [
        obj.get("property_name_normalized"),
        obj.get("semantic_label"),
        obj.get("property_name_raw"),
    ]
    name = " ".join(str(value or "") for value in parts + labels).strip()
    return classify_pred(name, unit), classify_surface_component(name)


def _final_cells(final_payload):
    """Map (table_id, column_index) to candidate objects with status metadata."""
    cells = {}
    evidence_index = {
        item.get("evidence_id"): item
        for item in final_payload.get("evidence") or []
        if isinstance(item, dict) and item.get("evidence_id")
    }
    for container, obj in _iter_final_objects(final_payload):
        evidence = list(obj.get("evidence") or [])
        if not evidence:
            evidence = [
                evidence_index[evidence_id]
                for evidence_id in obj.get("evidence_ids") or []
                if evidence_id in evidence_index
            ]
        # Resolve top-level evidence_ids for classification as well as cell
        # location, without changing the final payload.
        classified_obj = dict(obj)
        classified_obj["evidence"] = evidence
        bucket, component = _object_bucket(classified_obj)
        for evidence in evidence:
            locator = evidence.get("table_locator") or {}
            table_id = locator.get("table_id")
            column_index = locator.get("column_index")
            if table_id is None or column_index is None:
                continue
            key = (str(table_id), int(column_index))
            cells.setdefault(key, []).append({
                "container": container,
                "bucket": bucket,
                "surface_component": component,
                "publication_status": obj.get("publication_status"),
                "reason": obj.get("reason"),
                "property_name_raw": obj.get("property_name_raw"),
                "semantic_label": obj.get("semantic_label"),
            })
    return cells


def audit_document(document_dir):
    """Return table-column completeness rows for one Preview document."""
    shadow_path = os.path.join(document_dir, "stage4t_shadow.json")
    final_path = os.path.join(document_dir, "final.json")
    if not (os.path.exists(shadow_path) and os.path.exists(final_path)):
        return []
    with open(shadow_path, encoding="utf-8") as fh:
        shadow = json.load(fh)
    with open(final_path, encoding="utf-8") as fh:
        final = json.load(fh)
    final_cells = _final_cells(final)
    rows = []
    for table in shadow.get("tables") or []:
        table_id = str(table.get("table_id"))
        observations = table.get("shadow_observations") or table.get("observations") or []
        obs_by_col = Counter(
            int(obs["column_index"])
            for obs in observations
            if obs.get("column_index") is not None and obs.get("value_raw") not in (None, "")
        )
        for candidate in table.get("property_candidates") or []:
            column_index = candidate.get("column_index")
            if column_index is None:
                continue
            bucket, component = _column_bucket(candidate)
            values = obs_by_col.get(int(column_index), 0)
            if bucket is None:
                status = "out_of_scope"
                cells = []
            else:
                cells = [
                    cell for cell in final_cells.get((table_id, int(column_index)), [])
                    if cell.get("bucket") == bucket
                    and (component is None or cell.get("surface_component") == component)
                ]
                if values == 0:
                    status = "header_without_values"
                elif not cells:
                    status = "table_column_dropped"
                elif any(cell.get("publication_status") in ("published", "candidate_only", None)
                         for cell in cells):
                    status = "candidate_present"
                elif any(cell.get("publication_status") == "unresolved" for cell in cells):
                    status = "candidate_unresolved"
                else:
                    status = "candidate_quarantined"
            rows.append({
                "document_id": shadow.get("document_id") or os.path.basename(document_dir),
                "table_id": table_id,
                "column_index": int(column_index),
                "header": candidate.get("property_name_raw"),
                "bucket": bucket,
                "surface_component": component,
                "shadow_value_count": values,
                "final_candidate_count": len(cells),
                "status": status,
                "final_containers": sorted({cell["container"] for cell in cells}),
                "final_reasons": sorted({cell["reason"] for cell in cells if cell.get("reason")}),
            })
    return rows


def audit_batch(batch_dir):
    rows = []
    for name in sorted(os.listdir(batch_dir)):
        path = os.path.join(batch_dir, name)
        if name.startswith("reference_no_") and os.path.isdir(path):
            rows.extend(audit_document(path))
    return rows


def build_summary(rows):
    by_doc = {}
    for row in rows:
        by_doc.setdefault(row["document_id"], []).append(row)
    status_counts = Counter(row["status"] for row in rows)
    mapped = [row for row in rows if row["bucket"] is not None]
    return {
        "schema_version": "stage4t_table_completeness.v1",
        "documents": len(by_doc),
        "columns": len(rows),
        "mapped_columns": len(mapped),
        "status_counts": dict(sorted(status_counts.items())),
        "table_column_dropped": sum(row["status"] == "table_column_dropped" for row in rows),
        "per_document": {
            doc: dict(Counter(row["status"] for row in doc_rows))
            for doc, doc_rows in sorted(by_doc.items())
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    rows = audit_batch(args.batch)
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "table_completeness.json"), "w", encoding="utf-8") as fh:
        json.dump(build_summary(rows), fh, ensure_ascii=False, indent=2)
    with open(os.path.join(args.out, "table_completeness.jsonl"), "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps(build_summary(rows), ensure_ascii=False))


if __name__ == "__main__":
    main()
