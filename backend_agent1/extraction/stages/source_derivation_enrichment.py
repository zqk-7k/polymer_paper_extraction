"""Display saved interpretations beside source cells; never rewrite or certify raw observations."""
from copy import deepcopy
from types import SimpleNamespace

from schema.polymer_schema import Stage0Element, Evidence, NumericValueSemantics
from stages.numeric_value_semantics import derive_numeric_value
from stages.source_context_semantics import literal_value_supported, plain
from stages.table_grid import table_cells_for


def _records(stage):
    conditions = {c.get("condition_id"): c for c in stage.get("measurement_conditions", [])}
    for collection in ("properties", "unresolved_properties", "specialized_property_observations"):
        for item in stage.get(collection, []):
            yield collection, item, {}, conditions.get(item.get("measurement_condition_id"))
    for series in stage.get("property_series", []):
        parent = {k: v for k, v in series.items() if k != "points"}
        for point in series.get("points", []):
            yield "property_series.points", point, parent, None


def build_source_interpretations(stage0, stage4=None, stage5=None):
    """Recheck numeric derivations against exact saved evidence, without an API."""
    blocks = {b["block_id"]: Stage0Element.model_validate(b) for b in stage0.get("elements", [])}
    cells = {c.cell_id: c for b in blocks.values() if b.type == "table" for c in table_cells_for(b)}
    rows, methods = [], []
    for stage_name, stage in (("stage4", stage4), ("stage5", stage5)):
        if not stage:
            continue
        if not any(stage.get(k) for k in ("properties", "unresolved_properties", "specialized_property_observations", "property_series", "characterizations")):
            continue
        if stage.get("document_id") != stage0["document_id"]:
            raise ValueError("Source interpretation document mismatch")
        for collection, item, parent, condition in _records(stage):
            raw = item.get("value_raw")
            if raw is None:
                continue
            merged = {**parent, **item}
            for key in ("unit_raw", "unit_normalized"):
                if merged.get(key) is None:
                    merged[key] = parent.get(key)
            merged["measurement_context"] = {**(parent.get("measurement_context") or {}), **(item.get("measurement_context") or {})}
            evidence = item.get("evidence") or parent.get("evidence") or []
            oid = item.get("property_id") or item.get("specialized_id") or item.get("unresolved_id") or item.get("point_id")
            row = {"document_id": stage0["document_id"], "source_stage": stage_name, "collection": collection, "object_id": oid,
                   "series_id": parent.get("series_id"), "value_raw": raw,
                   "property_name_raw": merged.get("property_name_raw"),
                   "property_name_normalized": merged.get("property_name_normalized") or merged.get("semantic_label"),
                   "unit_raw": merged.get("unit_raw"),
                   "measurement_context": deepcopy(merged.get("measurement_context") or {}),
                   "measurement_condition": deepcopy(condition),
                   "evidence": deepcopy(evidence), "source_cell_ids": [],
                   "source_literal_verified": False, "semantic_status": "interpretation_requires_review",
                   "value_derivation": None,
                   "stage4t_relations": deepcopy((item.get("candidate_trace") or {}).get("stage4t_relations") or {})}
            for e in evidence:
                loc = e.get("table_locator") or {}
                cid = loc.get("cell_id")
                cell = cells.get(cid)
                if cell is not None and cid.startswith(e.get("block_id", "") + ":") and all(
                    loc.get(k) is None or loc[k] == getattr(cell, k) for k in ("row_index", "column_index")):
                    row["source_cell_ids"].append(cid)
            try:
                obj = SimpleNamespace(value_raw=raw, value_min=item.get("value_min"), value_max=item.get("value_max"),
                    unit_raw=merged.get("unit_raw"), unit_normalized=merged.get("unit_normalized"),
                    value_semantics=NumericValueSemantics.model_validate(item["value_semantics"]) if item.get("value_semantics") else None,
                    candidate_trace=item.get("candidate_trace"), evidence=[Evidence.model_validate(e) for e in evidence])
                row["source_literal_verified"] = literal_value_supported(obj, blocks)
                if row["source_literal_verified"]:
                    row["value_derivation"] = derive_numeric_value(obj, blocks)
            except (ValueError, TypeError, AttributeError) as exc:
                row["review_reason"] = "derivation_unavailable:" + type(exc).__name__
            rows.append(row)
        # Retain methods at their declared scope; do not broadcast to all samples.
        for method in stage.get("characterizations", []):
            methods.append({"document_id": stage0["document_id"], **{k: deepcopy(method.get(k)) for k in ("characterization_id", "method_raw", "method_normalized",
                "series_id", "derived_property_ids", "parameters", "parameter_sources", "measurement_context", "evidence")}})
    return {"version": "source_interpretations.v1", "document_id": stage0["document_id"],
            "records": rows, "methods": methods}


def inherit_cell_interpretations(observation, records):
    """Attach candidates independently of sample/publication gates and retain disagreements."""
    attached = []
    for row in records:
        if observation["source_cell_id"] not in row["source_cell_ids"]:
            continue
        value = deepcopy(row)
        # Evidence elsewhere cannot certify a mismatching value at this cell.
        if plain(str(value["value_raw"])) != plain(str(observation["value_raw"])):
            value["source_literal_verified"] = False
            value["value_derivation"] = None
            value["semantic_status"] = "component_or_value_requires_review"
        if value not in attached:
            attached.append(value)
    if not attached:
        return
    observation["derived_interpretations"] = attached
    confirmed_roles = set()
    normalized_values = set()
    normalized_units = set()
    for row in attached:
        d = row.get("value_derivation") or {}
        sem = d.get("source_semantics") or {}
        if row["source_literal_verified"] and sem.get("role_status") == "confirmed":
            confirmed_roles.add(sem.get("source_role"))
        if row["source_literal_verified"] and d.get("status") == "normalized":
            normalized_values.add(tuple(d.get("actual_values", [])))
            if d.get("actual_unit"):
                normalized_units.add(d["actual_unit"])
    if len(confirmed_roles) == 1:
        role = next(iter(confirmed_roles))
        observation["result_origin"] = "experimental" if role == "measured" else role
    if len(confirmed_roles) > 1 or len(normalized_values) > 1 or len(normalized_units) > 1:
        observation["review_fields"].append("derived_interpretations_conflict")
        observation["extraction_status"] = "needs_review"
