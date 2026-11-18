"""Input-derived cell preservation and coverage, independent of model outputs.

The data-region denominator is provisional: recipe amounts and coordinates can
also be numeric. It measures candidate capture, never property recall/accuracy.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence
import re

from schema.polymer_schema import Stage0TableCell
from stages.final_unit_conversion import parse_numeric
from stages.property_path_resolver import resolve_property_paths
from stages.table_cell_roles import classify_table_cells

INVENTORY_VERSION = "table_value_inventory.v5"


def composite_candidates(text: str, headers: Sequence[str] = ()) -> dict[str, Any]:
    """Diagnostic candidates only; no guessed precision, roles or sample identity."""
    if re.search(r"[A-Za-z].*\d", text):
        return {"status": "label_or_formula_not_split", "candidates": []}
    number = r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)"
    match = re.fullmatch(r"\s*(?P<outside>" + number + r")\s*\(\s*(?P<inside>" + number + r")\s*\)\s*", text)
    if match:
        header = " | ".join(headers)
        # A parenthetical calculation label scopes to the inner part only.
        inner_calculated = bool(re.search(r"\(\s*(?:calcd\.?|calculated|theoretical)\s*\)", header, re.I))
        outer_measured = inner_calculated and bool(re.search(r"\b(?:found|measured|experimental)\s*\(", header, re.I))
        return {"status": "explicit_parenthetical_pair", "candidates": [
            {"value_raw": match[name], "source_start": match.start(name), "source_end": match.end(name),
             "position": name, "role": "calculated" if name == "inside" and inner_calculated
                 else "measured" if name == "outside" and outer_measured else "unknown",
             "role_basis": header if inner_calculated else None, "status": "review_required"}
            for name in ("outside", "inside")]}
    if re.search(r"\d+\.\d+\.\d+", text):
        return {"status": "ambiguous_concatenated_numbers", "candidates": []}
    return {"status": "not_composite", "candidates": []}


def build_inventory(table_id: str, cells: Sequence[Stage0TableCell],
                    header_rows: set[int]) -> list[dict[str, Any]]:
    from stages.source_table_layout import refine_layout
    layout = refine_layout([c.model_dump() for c in cells], {'orientation': 'unknown'})
    pairs = layout['orientation'] == 'property_value_pairs'
    records = []
    role_rows = classify_table_cells(cells)
    role_map = {row["cell_id"]: row for row in role_rows}
    path_map = {row["target_cell_id"]: row for row in resolve_property_paths(cells, role_rows)}
    for cell in cells:
        parsed = parse_numeric(cell.text)
        role = ("property_value" if pairs and cell.column_index == 1
                else "header" if cell.is_header or cell.row_index in header_rows
                else "axis_or_label" if cell.column_index == 0 or cell.row_index == 0
                else "unclassified_numeric" if parsed else "text_or_unparsed")
        annotation = role_map[cell.cell_id]
        headers = [c.text for c in cells if (c.is_header or c.row_index in header_rows)
                   and c.row_index < cell.row_index and c.column_index <= cell.column_index < c.column_index+c.column_span]
        composite = composite_candidates(cell.text, headers) if role not in {"header", "axis_or_label"} else {
            "status": "header_or_axis_not_split", "candidates": []}
        records.append({
            "table_id": table_id, **cell.model_dump(mode="json"),
            "value_raw": cell.text, "input_role": role,
            "role_basis": "source_grid_and_header_rows",
            "role_requires_review": role in {"axis_or_label", "unclassified_numeric"},
            "cell_role": annotation["cell_role"],
            "axis_role": annotation["axis_role"],
            "role_confidence": annotation["role_confidence"],
            "role_evidence": annotation["role_evidence"],
            "role_conflicts": annotation["role_conflicts"],
            "property_path": path_map.get(cell.cell_id),
            "numeric_kind": parsed["kind"] if parsed else None,
            "numeric_values": [str(v) for v in parsed["values"]] if parsed else [],
            "eligible_for_capture": role in {"unclassified_numeric", "property_value"},
            "composite_diagnostic": composite,
        })
    return records


def capture_coverage(inventory: Sequence[Mapping[str, Any]],
                     observations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    expected = {r["cell_id"]: r for r in inventory if r["eligible_for_capture"]}
    # An ID alone is not proof: the original cell value must have survived.
    captured = {o.get("cell_id") for o in observations
                if o.get("cell_id") in expected
                and str(o.get("value_raw", "")).strip()
                == str(expected[o["cell_id"]]["value_raw"]).strip()}
    interpreted = {o.get("cell_id") for o in observations
                   if o.get("cell_id") in captured
                   and (o.get("property_name_normalized") or o.get("semantic_label"))}
    missing = sorted(set(expected) - captured)
    return {
        "inventory_version": INVENTORY_VERSION,
        "denominator_basis": "input_numeric_data_region_provisional",
        "metric_scope": "candidate_capture_not_property_recall",
        "source_cell_count": len(inventory),
        "expected": len(expected), "captured": len(captured),
        "missing": len(missing), "missing_cell_ids": missing,
        "ratio": len(captured) / len(expected) if expected else None,
        "interpreted": len(interpreted),
        "pending_interpretation": len(expected) - len(interpreted),
        "status": "empty_or_unclassified" if not expected else "missing_candidates" if missing
                  else "captured_pending_interpretation" if len(interpreted) < len(expected)
                  else "captured",
        "requires_role_review": True,
        "composite_cells": [r["cell_id"] for r in inventory
                            if r.get("composite_diagnostic", {}).get("status") in {
                                "explicit_parenthetical_pair", "ambiguous_concatenated_numbers"}],
        "composite_metric_scope": "diagnostic_only_not_numeric_capture",
    }
