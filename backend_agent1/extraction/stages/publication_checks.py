"""Rebuild publication evidence from source tables, never trust claimed statuses."""
from __future__ import annotations

import re
from typing import Any

from stages.binding_identity import build_article_sample_key
from stages.final_unit_conversion import canonical_unit
from stages.sample_catalog import build_catalog, catalog_for_source_cells, digest, normalize_label, source_index
from stages.standard_mapping import resolve_standard_property, units_in_text, load_standard_mapping
from stages.source_measurement_context import build_source_context_index, source_context_for, source_context_blockers


SCALE_PATTERN = re.compile(r"10\s*(?:\^|[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻])|(?:×|\\times)\s*10|\bscale\b|倍率", re.I)


def audit_context(payload: dict, stage0: dict | None, stage3: dict | None) -> dict:
    evidence = payload.get("evidence") or []
    ids = [e.get("evidence_id") for e in evidence if e.get("evidence_id")]
    indexes = source_index(stage0) if stage0 is not None else ({}, {})
    return {
        "payload": payload,
        "stage0": stage0,
        "catalog": build_catalog(stage0, stage3) if stage0 is not None and stage3 is not None else None,
        "indexes": indexes,
        "source_context_index": build_source_context_index(stage0, indexes) if stage0 is not None else None,
        "source_hash": digest(stage0) if stage0 is not None else None,
        "evidence": {e["evidence_id"]: e for e in evidence if e.get("evidence_id")},
        "duplicate_evidence": len(ids) != len(set(ids)),
    }


def check_publication_source(item: dict, context: dict) -> dict[str, Any]:
    """Check one scalar. Text and series require separate proof and stay pending."""
    # sample_binding imports MeasurementRecord, hence load only when called.
    from stages.sample_binding import (
        build_packet, condition_conflicts, deterministic_review, property_on_path,
        validate_review,
    )

    raw_name = item.get("property_name_raw") or item.get("semantic_label") or ""
    mapping = resolve_standard_property(raw_name, item.get("unit_raw"))
    result = {
        **mapping, "path_status": "candidate", "binding_status": "unresolved",
        "source_cell_ids": [], "path_evidence_ids": [], "scale_status": "unverified",
        "evidence_status": "unverified", "check_reasons": [],
    }
    reasons = result["check_reasons"]
    reasons.extend(r for r in mapping["mapping_reasons"] if r != "unit_annotation_in_property_name")
    if item.get("standard_property_code") and item["standard_property_code"] != mapping["standard_property_code"]:
        reasons.append("standard_code_conflict")
    # Lower-confidence source states may never be overwritten by the mere presence of an ID.
    claimed = item.get("binding_status") or item.get("sample_resolution_status")
    if claimed in {"ambiguous", "unresolved", "conflict"}:
        result["binding_status"] = claimed
    elif item.get("sample_id"):
        result["binding_status"] = "unresolved"  # promoted only after source checks
    elif item.get("article_sample_key"):
        reasons.append("article_alias_unverified")
    elif item.get("entity_id"):
        known = {e.get("entity_id") for e in context["payload"].get("polymer_entities", [])}
        if item["entity_id"] in known:
            result["binding_status"] = "entity_only"
        else:
            reasons.append("entity_reference_unknown")

    references = item.get("evidence_ids") or []
    registry = context["evidence"]
    if set(references) - set(registry):
        reasons.append("evidence_reference_unknown")
    if context["duplicate_evidence"]:
        reasons.append("evidence_reference_ambiguous")
    evidence = [registry[eid] for eid in references if eid in registry]
    inline = item.get("evidence") or []
    evidence.extend([inline] if isinstance(inline, dict) else inline)
    if not evidence:
        reasons.append("evidence_missing")
    if context["stage0"] is None:
        reasons.append("source_input_missing")
        return result
    blocks, cells = context["indexes"]
    for e in evidence:
        bid = e.get("block_id") or e.get("table_id")
        if bid not in blocks:
            reasons.append("source_block_unknown")
        elif e.get("page") is not None and e["page"] != blocks[bid].get("page"):
            reasons.append("source_page_conflict")
    if context["catalog"] is None:
        reasons.append("sample_catalog_missing")
        return result
    if item.get("points"):
        reasons.append("series_requires_point_audit")
        return result
    if item.get("value_raw") is None:
        reasons.append("value_missing")
        return result
    candidate = {**item, "evidence": evidence}
    catalog = catalog_for_source_cells(context["catalog"],
        [(e.get("table_locator") or {}).get("cell_id") for e in evidence], cells)
    packet = build_packet(
        {"candidate": candidate, "review_id": "publication_audit", "property_id": str(item.get("property_id") or item.get("unresolved_id") or item.get("specialized_id") or "audit")},
        context["stage0"], catalog, indexes=context["indexes"], source_hash=context["source_hash"],
    )
    reasons.extend(packet["locator_errors"])
    paths = packet["evidence_paths"]
    if len(paths) != 1:
        reasons.append("evidence_path_not_unique" if paths else "source_path_unverified")
        return result
    path = paths[0]
    dimensionless_definition = None
    for entry in load_standard_mapping()["registry"]["entries"]:
        rule = entry.get("source_symbol_rule")
        if not rule or str(raw_name).strip() != rule["symbol"]:
            continue
        target = cells[path["target_cell_id"]]
        headers = [cells[cid] for cid in path["axis_cell_ids"]
                   if cells[cid]["text"].strip() == rule["symbol"]
                   and cells[cid]["row_index"] < target["row_index"]
                   and cells[cid]["column_index"] <= target["column_index"] < cells[cid]["column_index"] + cells[cid]["column_span"]]
        caption = " ".join(str(path.get("caption") or "").split())
        if len(headers) != 1 or not re.fullmatch(rule["caption_pattern"], caption, re.I):
            continue
        # Source-qualified semantics establish a dimension, not an observed unit.
        # Never apply this rule to a bare symbol or an unrelated table caption.
        old_mapping_reasons = set(mapping["mapping_reasons"]) | {"standard_code_conflict"}
        reasons[:] = [r for r in reasons if r not in old_mapping_reasons]
        mapping = resolve_standard_property(entry["key"], item.get("unit_raw") or rule["unit_by_definition"])
        mapping["standard_status"] = "standard_alias" if mapping["standard_status"] == "standard_exact" else mapping["standard_status"]
        result.update(mapping)
        reasons.extend(mapping["mapping_reasons"])
        if item.get("standard_property_code") and item["standard_property_code"] != mapping["standard_property_code"]:
            reasons.append("standard_code_conflict")
        dimensionless_definition = rule["unit_by_definition"]
        result.update(unit_basis="source_qualified_dimensionless_definition", unit_normalized=dimensionless_definition,
                      standard_mapping_basis={"header_cell_id": headers[0]["cell_id"],
                          "table_id": path["table_id"], "caption": caption, "registry_key": entry["key"]})
        break
    result["source_cell_ids"] = [path["target_cell_id"]]
    result["path_evidence_ids"] = sorted({path["target_cell_id"], *path["axis_cell_ids"]})
    if property_on_path(packet, path) and not packet["locator_errors"]:
        result["path_status"] = "complete"
        result["evidence_status"] = "source_cell_verified"
    else:
        reasons.append("property_evidence_path_missing")
    reasons.extend(condition_conflicts(packet, path))
    review = validate_review(deterministic_review(packet), packet, allow_inherited=False)
    reasons.extend(review["validation_errors"])
    selected = packet["deterministic_binding"].get("sample_id")
    selected_entry = next((s for s in catalog["samples"] if s["sample_id"] == selected), {})
    if item.get("sample_id"):
        matches = catalog["legacy_mapping"].get(item["sample_id"], [])
        if not matches:
            reasons.append("sample_reference_unknown")
        elif len(matches) != 1:
            reasons.append("sample_mapping_not_unique")
        elif selected and matches[0] != selected:
            result["binding_status"] = "conflict"
            reasons.append("sample_axis_conflict")
        elif review["validation_passed"] and selected == matches[0] and claimed not in {"ambiguous", "unresolved", "conflict"}:
            result["binding_status"] = "resolved"
            if selected_entry.get("source_alias_reviews"):
                result["source_alias_reviews"] = selected_entry["source_alias_reviews"]
        selected_entry = next((s for s in catalog["samples"] if s["sample_id"] == selected), {})
        if item.get("entity_id") and selected_entry.get("refers_to_entity") and item["entity_id"] != selected_entry["refers_to_entity"]:
            result["binding_status"] = "conflict"
            reasons.append("sample_entity_conflict")
        elif item.get("entity_id") and not selected_entry.get("refers_to_entity"):
            reasons.append("sample_entity_relation_unverified")

    # A Stage2 ID alone proves existence, not that this value belongs to it.
    entity_proof = None
    if (item.get("entity_id") and not item.get("sample_id") and not item.get("article_sample_key")
            and claimed not in {"ambiguous", "unresolved", "conflict"} and result["path_status"] == "complete"):
        target_cell = cells[path["target_cell_id"]]
        matches = []
        for entity in context["payload"].get("polymer_entities", []):
            names = {normalize_label(n) for n in [entity.get("polymer_name"), *(entity.get("source_names") or [])] if n}
            evidence = entity.get("evidence") or []
            evidence = [evidence] if isinstance(evidence, dict) else evidence
            for cid in path["axis_cell_ids"]:
                cell = cells[cid]
                is_row_label = (cell["row_index"] <= target_cell["row_index"] < cell["row_index"] + cell["row_span"]
                                and cell["column_index"] < target_cell["column_index"])
                if not is_row_label or normalize_label(cell["text"]) not in names:
                    continue
                same_names = [e for e in context["payload"].get("polymer_entities", [])
                              if normalize_label(cell["text"]) in {normalize_label(n) for n in
                                  [e.get("polymer_name"), *(e.get("source_names") or [])] if n}]
                if len(same_names) != 1:
                    continue
                if any(e.get("block_id") == path["table_id"] and normalize_label(e.get("source_sentence")) == normalize_label(cell["text"])
                       for e in evidence):
                    matches.append((entity["entity_id"], cid))
        if len(set(matches)) == 1 and matches[0][0] == item["entity_id"]:
            entity_proof = {"entity_id": item["entity_id"], "label_cell_id": matches[0][1], "table_id": path["table_id"],
                            "basis": "unique_exact_entity_name_and_same_table_evidence"}
            result.update(binding_status="entity_only", binding_basis="entity_source_axis", entity_source_proof=entity_proof)
        else:
            reasons.append("entity_value_relation_unverified")

    # A source-only catalog entry is an article label, never a Stage3 sample ID.
    if (not item.get("sample_id") and selected_entry and not selected_entry.get("legacy_sample_ids")
            and entity_proof is None
            and review["validation_passed"] and result["path_status"] == "complete"
            and claimed not in {"ambiguous", "unresolved", "conflict"}):
        label = selected_entry["sample_label_primary"]
        label_cells = [cells[cid] for cid in path["axis_cell_ids"]
                       if normalize_label(cells[cid]["text"]) == normalize_label(label)]
        if len(label_cells) == 1:
            cell = label_cells[0]
            target = cells[path["target_cell_id"]]
            # Repeated labels and rowspan dose rows remain distinct. Properties
            # on the same sample row (or column) retain the same identity.
            row_axis = cell["row_index"] <= target["row_index"] < cell["row_index"] + cell["row_span"]
            variant = {"label_cell_id": cell["cell_id"],
                       "sample_row" if row_axis else "sample_column": target["row_index"] if row_axis else target["column_index"],
                       "measurement_context": packet["measurement_context"]}
            key = build_article_sample_key(context["payload"]["document_id"], path["table_id"], label, variant_context=variant)
            if item.get("article_sample_key") and item["article_sample_key"] != key:
                reasons.append("article_sample_key_conflict")
                result["binding_status"] = "conflict"
            else:
                result.update(binding_status="article_alias_confirmed", article_sample_key=key,
                              article_sample_label_raw=label, binding_basis="row_label" if row_axis else "column_label",
                              binding_evidence_ids=result["path_evidence_ids"])
                if "article_alias_unverified" in reasons:
                    reasons.remove("article_alias_unverified")
                if item.get("entity_id"):
                    reasons.append("article_entity_relation_unverified")

    # Restrict unit/scale evidence to this path; other columns cannot validate it.
    axis_text = " | ".join(packet["source_evidence"][x]["text"] for x in path["axis_cell_ids"])
    property_cells = []
    unit_cells = []
    target = cells[path["target_cell_id"]]
    for cid in path["axis_cell_ids"]:
        cell = cells[cid]
        mapped = resolve_standard_property(cell["text"], item.get("unit_raw"))
        if (mapping["standard_property_code"] and mapped["standard_property_code"] == mapping["standard_property_code"]) or (dimensionless_definition and cell["text"].strip() == str(raw_name).strip()):
            property_cells.append(cell)
        # A separate unit header must cover the target column.
        elif (cell.get("is_header") and cell["column_index"] <= target["column_index"] < cell["column_index"] + cell["column_span"]
              and units_in_text(cell["text"]) == [cell["text"].strip()]):
            unit_cells.append(cell)
    source_units = units_in_text(" | ".join(c["text"] for c in property_cells + unit_cells))
    expected_unit = canonical_unit(item.get("unit_raw") or dimensionless_definition)
    unit_matches = [u for u in source_units if canonical_unit(u) == expected_unit]
    if source_units and any(canonical_unit(u) != expected_unit for u in source_units):
        result["unit_status"] = "unit_conflict"
        reasons.append("unit_source_conflict")
    definition_proves_unit = dimensionless_definition and expected_unit in {"1", "dimensionless"} and not source_units
    if not expected_unit or (not unit_matches and not definition_proves_unit):
        result["unit_status"] = "unit_unresolved"
        reasons.append("unit_source_unverified")
    if item.get("unit_normalized") and canonical_unit(item["unit_normalized"]) != expected_unit and not (
        dimensionless_definition and {canonical_unit(item["unit_normalized"]), expected_unit} <= {"1", "dimensionless"}
    ):
        # A normalized unit requires a separate numeric conversion proof.
        result["unit_status"] = "unit_unresolved"
        reasons.append("unit_conversion_unverified")
    scale_text = axis_text + " | " + " | ".join(
        packet["source_evidence"][eid]["text"] for eid in path.get("context_evidence_ids", [])
    )
    explicit_scale = any(item.get(key) is not None for key in ("display_scale_raw", "scale_factor_exponent", "scale_factor_raw"))
    if explicit_scale or SCALE_PATTERN.search(scale_text):
        reasons.append("display_scale_unverified")
    else:
        result["scale_status"] = "not_present_on_source_path"
    source_context = source_context_for(item, result, context["source_context_index"])
    if source_context:
        result["source_condition_context"] = source_context
        reasons.extend(source_context_blockers(source_context))
    return result
