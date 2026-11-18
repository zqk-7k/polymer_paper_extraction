"""Trace candidates and response locators, not correctness or property recall."""
from __future__ import annotations
from typing import Any


def _locators(item: dict) -> set[tuple[str, str]]:
    result = set()
    for evidence in item.get("evidence", []):
        locator = evidence.get("table_locator") or {}
        table_id = evidence.get("block_id") or locator.get("table_id")
        cell_id = locator.get("cell_id")
        if not cell_id and locator.get("row_index") is not None and locator.get("column_index") is not None:
            cell_id = f'{table_id}:r{locator["row_index"]:04d}:c{locator["column_index"]:04d}'
        if table_id and cell_id:
            result.add((table_id, cell_id))
    # Final evidence registry may omit table locators; a source-bound derived cell
    # context still supplies a trace. Presence remains distinct from value capture.
    contexts = ((item.get("value_derivation") or {}).get("source_semantics") or {}).get("source_contexts", [])
    for context in contexts:
        if context.get("scope") == "table_cell" and context.get("block_id") and context.get("source_cell_id"):
            result.add((context["block_id"], context["source_cell_id"]))
    return result


def diagnose_response_trace(inventory: list[dict], shadow_observations: list[dict],
                            response_items: list[dict], final_items: list[dict]) -> dict[str, Any]:
    """Do not label an unlocated response a model omission or metadata a captured value."""
    raw_cells = set().union(*(_locators(i) for i in response_items)) if response_items else set()
    final_cells = set().union(*(_locators(i) for i in final_items)) if final_items else set()
    shadow = {(i.get("table_id"), i.get("cell_id")) for i in shadow_observations}
    cells = []
    for row in inventory:
        key = (row["table_id"], row["cell_id"])
        composite = row.get("composite_diagnostic", {})
        if not row["eligible_for_capture"] and composite.get("status") not in {
                "explicit_parenthetical_pair", "ambiguous_concatenated_numbers"} and key not in shadow:
            continue
        cells.append({"table_id": key[0], "cell_id": key[1], "value_raw": row["value_raw"],
                      "composite_status": composite.get("status"),
                      "diagnostic_numeric_parts": composite.get("candidates", []),
                      "local_candidate_generated": key in shadow,
                      "response_locator_present": key in raw_cells,
                      "final_locator_present": key in final_cells,
                      "status": "response_located" if key in raw_cells else "response_not_traced",
                      "interpretation_metadata_is_capture_proof": False})
    final_ids = {i.get("property_id") or i.get("unresolved_id") for i in final_items}
    uncatalogued = [{"object_id": i.get("property_id") or i.get("unresolved_id"),
                    "property_name_raw": i.get("property_name_raw"), "value_raw": i.get("value_raw"),
                    "final_source_cell_trace_present": bool(_locators(i) & final_cells),
                    "id_presence_is_retention_proof": False,
                    "final_id_present": (i.get("property_id") or i.get("unresolved_id")) in final_ids}
                   for i in response_items if i.get("property_name_raw") and not i.get("property_code")]
    return {"version": "extraction_trace.v1", "scope": "provenance_diagnostic_not_accuracy",
            "final_trace_basis": "evidence_locator_or_source_bound_derived_cell_context_not_numeric_capture",
            "cells": cells, "uncatalogued_response_items": uncatalogued,
            "response_items_without_cell_locator": sum(not _locators(i) for i in response_items)}
