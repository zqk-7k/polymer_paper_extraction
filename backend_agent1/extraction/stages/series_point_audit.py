"""Source checks for each series point, independent of a multi-subject parent."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy

from stages.publication_checks import audit_context, check_publication_source
from stages.measurement_record import publication_decision
from stages.binding_publication import binding_publication_options
from stages.series_input_scope import verify_series_input_trace, point_input_scope


def audit_series_points(stage0: dict, stage2: dict, stage3: dict, stage4: dict, *, trace=None, origin_trace=None,
                        stage4n=None, stage4t=None, stage4r_audit=None, lineage_file_hashes=None) -> dict:
    document_id = stage0.get("document_id")
    if not document_id or any(d.get("document_id") != document_id for d in (stage2, stage3, stage4)):
        raise ValueError("Series audit document mismatch")
    payload = {"document_id": document_id, "polymer_entities": stage2.get("polymer_entities", []), "evidence": []}
    context = audit_context(payload, stage0, stage3)
    input_proof = verify_series_input_trace(stage0, stage2, stage3, stage4, trace, origin_trace,
        stage4n=stage4n, stage4t=stage4t, stage4r_audit=stage4r_audit, lineage_file_hashes=lineage_file_hashes)
    series_ids = Counter(s.get("series_id") for s in stage4.get("property_series", []))
    records = []
    for series in stage4.get("property_series", []):
        point_ids = Counter(p.get("point_id") for p in series.get("points", []))
        for point in series.get("points", []):
            # Never use a parent's unresolved subject to override point-level
            # identity, or fill an explicit null point subject from the parent.
            candidate = deepcopy(point)
            candidate["property_id"] = f"{series.get('series_id')}:{point.get('point_id')}"
            candidate["property_name_raw"] = series.get("property_name_raw")
            inherited = ["property_name_raw"]
            if candidate.get("unit_raw") is None and series.get("unit_raw") is not None:
                candidate["unit_raw"] = series["unit_raw"]
                inherited.append("unit_raw")
            parent_context = series.get("measurement_context") or {}
            own_context = point.get("measurement_context") or {}
            if parent_context:
                merged_context = deepcopy(parent_context)
                for key, value in own_context.items():
                    if value is None:
                        continue
                    if isinstance(value, dict) and isinstance(merged_context.get(key), dict):
                        merged_context[key].update(deepcopy(value))
                    else:
                        merged_context[key] = deepcopy(value)
                candidate["measurement_context"] = merged_context
                inherited.append("measurement_context")
            check = check_publication_source(candidate, context)
            context_conflicts = [key for key in set(parent_context) & set(own_context)
                                 if parent_context[key] is not None and own_context[key] is not None
                                 and parent_context[key] != own_context[key] and key != "confidence"]
            if context_conflicts:
                check["check_reasons"].append("series_point_context_conflict")
            if series_ids[series.get("series_id")] != 1 or point_ids[point.get("point_id")] != 1:
                check["check_reasons"].append("duplicate_object_id")
            if not series.get("series_id") or not point.get("point_id"):
                check["check_reasons"].append("point_identity_missing")
            if point.get("coverage_status") != "covered":
                check["check_reasons"].append("series_point_not_covered")
            scope = point_input_scope(series, point, input_proof)
            decision = publication_decision(path_status=check["path_status"], standard_status=check["standard_status"],
                unit_status=check["unit_status"], binding_status=check["binding_status"],
                evidence_ids=check["path_evidence_ids"], input_complete=scope["input_complete"],
                conflicts=check["check_reasons"] + scope["input_scope_reasons"], **binding_publication_options(check))
            source_decision = publication_decision(path_status=check["path_status"], standard_status=check["standard_status"],
                unit_status=check["unit_status"], binding_status=check["binding_status"],
                evidence_ids=check["path_evidence_ids"], input_complete=True, conflicts=check["check_reasons"], **binding_publication_options(check))
            records.append({"series_id": series.get("series_id"), "point_id": point.get("point_id"),
                "property_name_raw": candidate["property_name_raw"], "value_raw": point.get("value_raw"),
                "unit_raw": candidate.get("unit_raw"), "unit_normalized": candidate.get("unit_normalized"),
                "sample_id": point.get("sample_id"), "entity_id": point.get("entity_id"),
                "declared_binding_status": point.get("sample_resolution_status"),
                "parent_binding_status": series.get("sample_resolution_status"), "inherited_fields": inherited,
                "context_conflict_fields": sorted(context_conflicts), **check, **scope, **decision,
                "measurement_context": deepcopy(candidate.get("measurement_context") or {}),
                "effective_candidate": candidate,
                "original_point": deepcopy(point),
                "source_audit_status": "passed" if source_decision["publication_status"] == "final" else "requires_review",
                "source_audit_reasons": source_decision["publication_reasons"]})
    return {"schema_version": "series_point_source_audit.v1", "document_id": document_id,
        "definition": "逐点发布资格审计，不写正式 final；只有验证真实请求及逐点依赖后才允许通过输入门禁。",
        "input_proof": input_proof,
        "publication_counts": dict(Counter(r["publication_status"] for r in records)),
        "record_count": len(records), "binding_counts": dict(Counter(r["binding_status"] for r in records)),
        "source_audit_counts": dict(Counter(r["source_audit_status"] for r in records)),
        "source_reason_counts": dict(Counter(reason for row in records for reason in row["source_audit_reasons"])),
        "records": records}
