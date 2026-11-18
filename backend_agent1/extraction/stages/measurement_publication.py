"""Materialize source-checked measurements without discarding original claims."""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json

from stages.measurement_record import MeasurementRecord, publication_audit_for_final
from stages.series_point_audit import audit_series_points


def _key(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _meaning(value):
    """Evidence location and confidence are provenance, not test conditions."""
    if isinstance(value, dict):
        return {k: _meaning(v) for k, v in sorted(value.items())
                if v is not None and k not in {"confidence", "evidence"} and not k.endswith("evidence_ids")}
    if isinstance(value, list):
        return [_meaning(v) for v in value]
    return value


def build_measurement_publication(payload, *, stage0, stage2, stage3, stage4,
                                  stage5=None, stage5_shards=None, trace=None, origin_trace=None,
                                  stage4t=None, stage4r=None, stage4r_audit=None,
                                  stage4n=None, lineage_file_hashes=None):
    """Publish only independently verified exact claims; preserve all other inputs.

    Stage4T/R preview claims enter the source-indexed ledger without becoming
    certified members of the primary publication groups.
    """
    doc = payload.get("document_id")
    if not doc or any(x.get("document_id") != doc for x in (stage0, stage2, stage3, stage4)):
        raise ValueError("Measurement publication document mismatch")
    if stage5 and stage5.get("document_id") not in (None, doc):
        raise ValueError("Measurement publication Stage5 mismatch")
    series_audit = audit_series_points(stage0, stage2, stage3, stage4, trace=trace, origin_trace=origin_trace,
        stage4n=stage4n, stage4t=stage4t, stage4r_audit=stage4r_audit, lineage_file_hashes=lineage_file_hashes)
    audit = publication_audit_for_final(payload, stage0=stage0, stage3=stage3,
        stage4=stage4, stage5=stage5, stage5_shards=stage5_shards,
        stage4_input_proof=series_audit["input_proof"] if trace is not None else None)
    entries, aggregates, containers = [], [], []
    ordinals = Counter()
    for row in audit["records"]:
        collection = row["collection"]
        key = (collection, row["object_id"])
        matches = [item for item in payload[collection] if str(item.get("property_id") or item.get("unresolved_id")
                   or item.get("series_id") or item.get("specialized_id")) == row["object_id"]]
        item = matches[ordinals[key]]
        ordinals[key] += 1
        member = {"collection": collection, "object_id": row["object_id"],
                  "source_stage": row["source_stage"], "original_record": deepcopy(item), "audit": deepcopy(row)}
        if collection == "property_series":
            containers.append(member)
        elif item.get("observation_role") == "aggregate":
            aggregates.append(member)
        else:
            entries.append((item, row, member))
    for row in series_audit["records"]:
        item = row["effective_candidate"]
        member = {"collection": "property_series.points", "object_id": f"{row['series_id']}:{row['point_id']}",
                  "source_stage": "stage4", "series_id": row["series_id"], "point_id": row["point_id"],
                  "original_record": deepcopy(row["original_point"]),
                  "audit": {k: deepcopy(v) for k, v in row.items() if k not in {"effective_candidate", "original_point"}}}
        entries.append((item, row, member))
    known_samples = {s["sample_id"] for s in payload.get("samples", [])}
    known_entities = {e["entity_id"] for e in payload.get("polymer_entities", [])}
    groups, anchors = {}, defaultdict(set)
    for ordinal, (item, row, member) in enumerate(entries):
        cells = sorted(set(row.get("source_cell_ids") or []))
        conditions = _meaning(item.get("measurement_context") or item.get("conditions") or {})
        # Retain additional condition/scale claims, even if they are not yet resolved.
        qualifiers = {k: _meaning(item[k]) for k in ("condition_id", "condition_ids", "measurement_condition_id",
            "measurement_condition_ids", "characterization_id", "method_raw", "determination_method_raw",
            "display_scale_raw", "scale_factor_raw", "scale_factor_exponent", "coordinates") if item.get(k) is not None}
        identity = {"document_id": doc, "source_cell_ids": cells,
                    "property": row.get("standard_property_code") or row.get("property_name_raw"),
                    "value_raw": row.get("value_raw"), "unit_raw": item.get("unit_raw"),
                    "sample_id": row.get("sample_id"), "entity_id": row.get("entity_id"),
                    "article_sample_key": row.get("article_sample_key"),
                    "conditions": conditions, "qualifiers": qualifiers}
        stable = row.get("evidence_status") == "source_cell_verified" and len(cells) == 1
        if not stable:
            identity["unverified_occurrence"] = [member["collection"], member["object_id"], ordinal]
        mid = "measurement_" + hashlib.sha256(_key(identity).encode()).hexdigest()[:24]
        group = groups.setdefault(mid, {"measurement_id": mid, "identity": identity, "members": [],
                                       "review_reasons": [], "record": None})
        group["members"].append(member)
        # Any two located claims on one source cell require reconciliation,
        # including a wrong sample or property claim that failed validation.
        if len(cells) == 1:
            anchors[cells[0]].add(mid)
        if group["record"] is None and row.get("value_raw") is not None and str(row["value_raw"]).strip() and cells:
            binding = row["binding_status"]
            sample = row.get("sample_id") if binding == "resolved" else None
            entity = row.get("entity_id") if binding in {"resolved", "entity_only"} else None
            alias = row.get("article_sample_key") if binding == "article_alias_confirmed" else None
            group["record"] = MeasurementRecord(
                measurement_id=mid, source_stage=member["source_stage"], source_cell_ids=cells,
                property_name_raw=row.get("property_name_raw") or "unknown property",
                property_code=item.get("property_code"), standard_property_code=row.get("standard_property_code"),
                standard_status=row["standard_status"], standard_mapping_reasons=row.get("mapping_reasons", []),
                value_raw=str(row["value_raw"]), unit_raw=item.get("unit_raw"),
                unit_normalized=row.get("unit_normalized") if row.get("unit_basis") == "source_qualified_dimensionless_definition" else None,
                # Do not copy model-provided converted values without conversion proof.
                condition_context={"measurement_context": conditions, **qualifiers},
                source_condition_context=deepcopy(row.get("source_condition_context") or {}),
                sample_id=sample, entity_id=entity, article_sample_key=alias,
                article_sample_label_raw=row.get("article_sample_label_raw"), binding_status=binding,
                binding_basis=row.get("binding_basis"), binding_evidence_ids=row.get("path_evidence_ids", []),
            ).model_dump(mode="json")
        if row.get("sample_id") and row["sample_id"] not in known_samples:
            group["review_reasons"].append("publication_sample_reference_unknown")
        if row.get("entity_id") and row["entity_id"] not in known_entities:
            group["review_reasons"].append("publication_entity_reference_unknown")
    for ids in anchors.values():
        if len(ids) > 1:
            for mid in ids:
                groups[mid]["review_reasons"].append("same_source_claims_differ")
    result = {"schema_version": "measurement_publication.v1", "document_id": doc,
              "scope": "stage6_scalars_and_stage4_series_points", "final": [], "candidate": [], "not_publishable": [],
              "aggregate_records": aggregates, "series_containers": containers,
              "stage6_rejected_objects": deepcopy(payload.get("rejected_objects") or []),
              "quarantined_records": [deepcopy(o) for w in stage4.get("warnings", [])
                                      if w.get("code") == "preview_objects_quarantined" for o in w.get("objects", [])],
              "series_input_proof": series_audit["input_proof"]}
    for group in sorted(groups.values(), key=lambda g: g["measurement_id"]):
        reasons = sorted(set(group["review_reasons"]))
        decisions = [m["audit"]["publication_status"] for m in group["members"]]
        # Duplicate expressions cannot erase another member's failed gate.
        status = "not_publishable" if "not_publishable" in decisions else "candidate" if "candidate" in decisions or reasons else "final"
        if group["record"] is None:
            status = "not_publishable"
            reasons.append("measurement_record_unavailable")
        if any(r.endswith("reference_unknown") for r in reasons):
            status = "not_publishable"
        reasons = sorted(set(reasons + [r for m in group["members"] for r in m["audit"]["publication_reasons"]]))
        group.update(publication_status=status, publication_reasons=reasons)
        if group["record"] is not None:
            group["record"].update(publication_status=status, publication_reasons=reasons)
            MeasurementRecord.model_validate(group["record"])
        result[status].append(group)
    result["counts"] = {s: len(result[s]) for s in ("final", "candidate", "not_publishable")}
    result["counts"].update(source_expression_count=len(entries), measurement_group_count=len(groups),
        repeated_expression_count=len(entries) - len(groups), aggregate_count=len(aggregates),
        quarantined_count=len(result["quarantined_records"]))
    from stages.raw_measurement_candidates import build_raw_candidate_ledger, source_cell_groups
    ledger = build_raw_candidate_ledger(stage0, stage2, stage3, stage4t=stage4t, stage4r=stage4r, stage4r_audit=stage4r_audit)
    result["raw_candidate_ledger"] = ledger
    result["source_cell_groups"] = source_cell_groups(doc, result, ledger)
    result["scope"] = "stage6_scalars_stage4_points_with_stage4t_stage4r_candidate_ledger"
    from stages.source_table_extraction import build_source_extraction
    from stages.source_derivation_enrichment import build_source_interpretations
    result["source_interpretation_bundle"] = build_source_interpretations(stage0, stage4, stage5)
    result['source_evidence_catalog'] = deepcopy(payload.get('evidence') or [])
    result["source_extraction"] = build_source_extraction(stage0, result)
    result["default_view"] = "source_extraction"
    return result
