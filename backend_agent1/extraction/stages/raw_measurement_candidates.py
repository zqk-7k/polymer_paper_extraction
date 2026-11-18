"""Preserve historical table/recovery claims in a source-indexed measurement ledger.

Preview claims are not votes against independently certified measurements and
cannot promote themselves to final. Their source checks and provenance stay explicit.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json

from stages.measurement_record import MeasurementRecord, measurement_record_from_candidate, publication_decision
from stages.publication_checks import audit_context, check_publication_source
from stages.series_point_audit import audit_series_points
from stages.binding_publication import binding_publication_options


TABLE_COLLECTIONS = ("shadow_observations", "rule_observations", "llm_enriched_observations", "observations", "unresolved")


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def build_raw_candidate_ledger(stage0, stage2, stage3, *, stage4t=None, stage4r=None, stage4r_audit=None):
    doc = stage0["document_id"]
    for data in (stage4t, stage4r, stage4r_audit):
        if data is not None and (not isinstance(data, dict) or data.get("document_id") != doc):
            raise ValueError("Raw candidate document mismatch")
    context = audit_context({"document_id": doc, "polymer_entities": (stage2 or {}).get("polymer_entities", []), "evidence": []}, stage0, stage3)
    roles = context["source_context_index"]["roles"]
    expressions, auxiliary = {}, []

    def retain(original, candidate, stage, pointer, check=None):
        # The exact same saved expression can occur in several Stage4T views.
        key = _hash({"document_id": doc, "source_stage": stage, "original": original})
        if key in expressions:
            expressions[key]["source_occurrences"].append(pointer)
            return
        if not isinstance(candidate, dict) or candidate.get("value_raw") is None:
            auxiliary.append({"source_stage": stage, "source_pointer": pointer, "original_record": deepcopy(original), "reason": "not_a_scalar_candidate"})
            return
        candidate = deepcopy(candidate)
        candidate["value_raw"] = str(candidate["value_raw"])
        check = deepcopy(check) if check is not None else check_publication_source(candidate, context)
        source_roles = [deepcopy(roles[cid]) for cid in check["source_cell_ids"] if cid in roles]
        # A source role only routes human review. It never supplies a unit, an
        # identity, input completeness, or permission to publish the claim.
        review_route = "source_review"
        source_context = None
        if (len(source_roles) == 1 and check.get("evidence_status") == "source_cell_verified"
                and "value_not_in_target_cell" not in check["check_reasons"]):
            role = source_roles[0]["cell_role"]
            review_route = {"condition": "context_review", "composition": "context_review",
                            "sample_label": "identity_review", "property_value": "property_review",
                            "property_header": "header_review", "unit_header": "header_review",
                            "scale_header": "header_review", "note": "context_review"}.get(role, "role_review")
        source_context = deepcopy(check.get("source_condition_context"))
        decision = publication_decision(path_status=check["path_status"], standard_status=check["standard_status"],
            unit_status=check["unit_status"], binding_status=check["binding_status"], evidence_ids=check["path_evidence_ids"],
            input_complete=False, conflicts=check["check_reasons"] + ["historical_preview_input_not_certified"],
            **binding_publication_options(check))
        mid = "raw_measurement_" + key[:24]
        record = measurement_record_from_candidate(candidate, document_id=doc, source_stage=stage)
        if record is not None:
            data = record.model_dump(mode="json")
            binding = check["binding_status"]
            data.update(measurement_id=mid, binding_status=binding,
                sample_id=candidate.get("sample_id") if binding == "resolved" else None,
                entity_id=candidate.get("entity_id") if binding in {"resolved", "entity_only"} else None,
                article_sample_key=check.get("article_sample_key") if binding == "article_alias_confirmed" else None,
                article_sample_label_raw=check.get("article_sample_label_raw"),
                standard_property_code=check.get("standard_property_code"), standard_status=check["standard_status"],
                standard_mapping_reasons=check.get("mapping_reasons", []), value_normalized=None, unit_normalized=None,
                source_cell_ids=check["source_cell_ids"], binding_evidence_ids=check["path_evidence_ids"],
                source_condition_context=deepcopy(check.get("source_condition_context") or {}), **decision)
            record = MeasurementRecord.model_validate(data).model_dump(mode="json")
        expressions[key] = {"measurement_id": mid, "source_stage": stage, "authority": "historical_preview",
            "source_roles": source_roles, "review_route": review_route,
            "source_context": source_context,
            "source_occurrences": [pointer], "source_cell_ids": check["source_cell_ids"], "record": record,
            "original_record": deepcopy(original), "effective_candidate": candidate, "source_audit": check, **decision}

    for ti, table in enumerate((stage4t or {}).get("tables", [])):
        for collection in TABLE_COLLECTIONS:
            for oi, raw in enumerate(table.get(collection) or []):
                pointer = f"stage4t_shadow.json#/tables/{ti}/{collection}/{oi}"
                if not isinstance(raw, dict):
                    retain(raw, None, "stage4t", pointer)
                    continue
                candidate = deepcopy(raw)
                # Preserve locator disagreements; never synthesize a target from a value.
                locator = deepcopy(raw.get("evidence_locator") or raw.get("evidence") or {})
                if isinstance(locator, dict):
                    for key in ("table_id", "cell_id", "row_index", "column_index"):
                        if raw.get(key) is not None:
                            locator.setdefault(key, raw[key])
                candidate.update(property_id=raw.get("observation_id"),
                    evidence=[{"block_id": raw.get("table_id") or table.get("table_id"),
                               "table_locator": locator, "source_sentence": str(raw.get("value_raw") or "")}])
                # Stage4T's 'bound' describes a table axis, not a Stage3 identity.
                candidate.pop("binding_status", None)
                if candidate.get("measurement_context") is None:
                    candidate["measurement_context"] = deepcopy(raw.get("conditions") or {})
                retain(raw, candidate, "stage4t", pointer)
    if stage4r is not None:
        for collection in ("properties", "unresolved_properties", "specialized_property_observations"):
            for index, raw in enumerate(stage4r.get(collection) or []):
                retain(raw, raw, "stage4r", f"stage4_properties.unified_preview.json#/{collection}/{index}")
        if stage2 is None or stage3 is None:
            point_audit = {"records": []}
            auxiliary.extend({"source_stage": "stage4r", "source_pointer": f"stage4_properties.unified_preview.json#/property_series/{i}",
                              "original_record": deepcopy(series), "reason": "series_upstream_input_missing"}
                             for i, series in enumerate(stage4r.get("property_series", [])))
        else:
            point_audit = audit_series_points(stage0, stage2, stage3, stage4r)
        for index, row in enumerate(point_audit["records"]):
            original = {"series_id": row["series_id"], "point": row["original_point"], "inherited_candidate": row["effective_candidate"]}
            retain(original, row["effective_candidate"], "stage4r", f"stage4_properties.unified_preview.json#/series_point_audit/{index}", row)
    rows = sorted(expressions.values(), key=lambda r: r["measurement_id"])
    return {"schema_version": "raw_measurement_ledger.v1", "document_id": doc, "records": rows,
        "auxiliary_records": auxiliary,
        "stage4r_relations": deepcopy((stage4r_audit or {}).get("candidate_outcomes", [])),
        "table_contexts": [{k: deepcopy(v) for k, v in table.items() if k not in TABLE_COLLECTIONS}
                           for table in (stage4t or {}).get("tables", [])],
        "table_interpretations": deepcopy((stage4t or {}).get("interpretations", [])),
        "series_contexts": [{k: deepcopy(v) for k, v in series.items() if k != "points"}
                            for series in (stage4r or {}).get("property_series", [])],
        "measurement_conditions": deepcopy((stage4r or {}).get("measurement_conditions", [])),
        "input_provenance": {"stage4t": deepcopy((stage4t or {}).get("provenance")),
                             "stage4r": deepcopy((stage4r or {}).get("provenance")),
                             "stage4r_input_hashes": deepcopy((stage4r_audit or {}).get("input_hashes")),
                             "stage4r_output_sha256": (stage4r_audit or {}).get("output_sha256")},
        "counts": {"expression_count": len(rows), "occurrence_count": sum(len(r["source_occurrences"]) for r in rows),
                   "duplicate_view_count": sum(len(r["source_occurrences"]) - 1 for r in rows),
                   "source_stage_counts": dict(Counter(r["source_stage"] for r in rows)), "auxiliary_count": len(auxiliary),
                   "review_route_counts": dict(Counter(r["review_route"] for r in rows)),
                   "source_context_expression_count": sum(r["source_context"] is not None for r in rows),
                   "source_context_status_counts": dict(Counter(r["source_context"]["status"] for r in rows if r["source_context"] is not None)),
                   "condition_comparison_status_counts": dict(Counter(r["source_context"]["declared_context_comparison"] for r in rows if r["source_context"] is not None))}}


def source_cell_groups(document_id, publication, ledger):
    """Index all co-located claims once without treating conflicting claims as measurements."""
    cells = defaultdict(lambda: {"publication_measurement_ids": [], "raw_measurement_ids": []})
    for status in ("final", "candidate", "not_publishable"):
        for group in publication[status]:
            ids = group["identity"].get("source_cell_ids") or []
            if len(ids) == 1:
                cells[ids[0]]["publication_measurement_ids"].append(group["measurement_id"])
    for row in ledger["records"]:
        if len(row["source_cell_ids"]) == 1:
            cells[row["source_cell_ids"][0]]["raw_measurement_ids"].append(row["measurement_id"])
    return [{"source_group_id": "source_" + _hash([document_id, cell])[:24], "source_cell_id": cell,
             **{k: sorted(set(v)) for k, v in links.items()},
             "definition": "同一源单元格的声明集合，不表示这些声明等价或均为独立测量。"}
            for cell, links in sorted(cells.items())]
