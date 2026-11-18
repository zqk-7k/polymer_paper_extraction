"""Lossless grouping of equivalent source-cell claims for offline review."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import hashlib
import json

from stages.standard_mapping import normalize_mapping_text


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def group_measurement_claims(payload: dict, audit: dict) -> dict:
    """Group exact claims only; never choose a winner or change publication."""
    originals = defaultdict(list)
    for row in audit["records"]:
        key = (row["collection"], row["object_id"])
        if key in originals:
            continue
        for item in payload.get(row["collection"], []):
            oid = item.get("property_id") or item.get("unresolved_id") or item.get("series_id") or item.get("specialized_id")
            if str(oid) == row["object_id"]:
                originals[key].append(item)
    occurrences = defaultdict(int)
    groups, source_claims = {}, defaultdict(set)
    for row in audit["records"]:
        key = (row["collection"], row["object_id"])
        occurrence = occurrences[key]
        occurrences[key] += 1
        item = originals[key][occurrence]
        source_cells = sorted(set(row.get("source_cell_ids") or []))
        verified = row.get("evidence_status") == "source_cell_verified" and len(source_cells) == 1
        property_key = (row.get("standard_property_code") if row.get("standard_status") in {"standard_exact", "standard_alias"}
                        else normalize_mapping_text(row.get("property_name_raw")))
        anchor = {"document_id": payload["document_id"], "source_cell_ids": source_cells, "property": property_key}
        # Preserve raw units/values: conversions and rounding require their own proof.
        claim = {
            "value_raw": row.get("value_raw"), "unit_raw": item.get("unit_raw"),
            "sample_id": row.get("sample_id"), "entity_id": row.get("entity_id"),
            "article_sample_key": row.get("article_sample_key"),
            "binding_status": row.get("binding_status"),
            "conditions": {field: item.get(field) for field in (
                "conditions", "measurement_context", "condition_id", "condition_ids",
                "measurement_condition_id", "measurement_condition_ids", "characterization_id",
                "method_raw", "determination_method_raw", "display_scale_raw",
                "scale_factor_raw", "scale_factor_exponent", "points")},
        }
        identity = {**anchor, "claim": claim}
        if not verified:
            # Text blocks and unresolved/multi-cell paths are not measurement identities.
            identity["unverified_occurrence"] = [*key, occurrence]
        gid = "measurement_group_" + hashlib.sha256(_canonical(identity).encode()).hexdigest()[:24]
        group = groups.setdefault(gid, {
            "measurement_group_id": gid, **anchor, "claim": claim,
            "source_verified": verified, "members": [], "review_reasons": [],
        })
        group["members"].append({
            "collection": row["collection"], "object_id": row["object_id"], "occurrence": occurrence,
            "source_stage": row.get("source_stage"), "publication_status": row["publication_status"],
            "publication_reasons": row["publication_reasons"], "original_record": deepcopy(item),
        })
        if verified:
            source_claims[_canonical(anchor)].add(gid)
        else:
            group["review_reasons"].append("source_identity_unverified")
    for ids in source_claims.values():
        if len(ids) > 1:
            for gid in ids:
                groups[gid]["review_reasons"].append("same_source_claims_differ")
    rows = sorted(groups.values(), key=lambda row: row["measurement_group_id"])
    return {
        "schema_version": "measurement_claim_groups.v1", "document_id": payload["document_id"],
        "definition": "无损来源分组，不是独立测量数量，不替代逐条发布门禁；不同表达需复核。",
        "record_count": len(audit["records"]), "group_count": len(rows),
        "repeated_expression_count": sum(len(g["members"]) - 1 for g in rows),
        "differing_source_count": sum(len(ids) > 1 for ids in source_claims.values()),
        "groups": rows,
    }
