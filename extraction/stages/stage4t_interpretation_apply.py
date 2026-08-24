"""将 Stage 4T 结构解释确定性地投影到宽松候选。"""

from __future__ import annotations

import copy
import re
from collections import defaultdict
from typing import Any, Mapping, Sequence

from schema.polymer_schema import Stage0Element, Stage0TableCell
from stages.stage4t_candidate_gate import (
    assess_publication_candidate,
    semantic_classification,
)
from stages.stage4t_table_interpretation import (
    HeaderAssignment,
    Stage4TTableInterpretation,
)
from stages.stage4t_table_property import _unit_info
from stages.table_grid import table_cells_for


APPLICATION_VERSION = "0.1.2"
_PROPERTY_ROLES = {"official_property", "material_characteristic"}


def _covers_row(cell: Stage0TableCell, row: int) -> bool:
    return cell.row_index <= row < cell.row_index + cell.row_span


def _covers_column(cell: Stage0TableCell, column: int) -> bool:
    return cell.column_index <= column < cell.column_index + cell.column_span


def _cell_at(
    cells: Sequence[Stage0TableCell],
    row: int,
    column: int,
) -> Stage0TableCell | None:
    return next(
        (
            cell
            for cell in cells
            if _covers_row(cell, row) and _covers_column(cell, column)
        ),
        None,
    )


def _source_cells(
    assignment: HeaderAssignment,
    cell_by_id: Mapping[str, Stage0TableCell],
) -> list[Stage0TableCell]:
    return [
        cell_by_id[cell_id]
        for cell_id in assignment.source_cell_ids
        if cell_id in cell_by_id
    ]


def _projected(
    assignment: HeaderAssignment,
    *,
    cell_by_id: Mapping[str, Stage0TableCell],
    row: int,
    column: int,
    projection: str,
) -> bool:
    sources = _source_cells(assignment, cell_by_id)
    if projection == "row":
        return any(_covers_row(cell, row) for cell in sources)
    if projection == "column":
        return any(_covers_column(cell, column) for cell in sources)
    return any(
        _covers_row(cell, row) or _covers_column(cell, column)
        for cell in sources
    )


def _property_projection(direction: str) -> str:
    if direction == "column_samples":
        return "row"
    if direction in {"row_samples", "condition_series"}:
        return "column"
    return "either"


def _matching_assignments(
    assignments: Sequence[HeaderAssignment],
    *,
    roles: set[str],
    cell_by_id: Mapping[str, Stage0TableCell],
    row: int,
    column: int,
    projection: str,
) -> list[HeaderAssignment]:
    return [
        assignment
        for assignment in assignments
        if assignment.role in roles
        and _projected(
            assignment,
            cell_by_id=cell_by_id,
            row=row,
            column=column,
            projection=projection,
        )
    ]


def _semantic_key(assignment: HeaderAssignment) -> tuple[str, str]:
    if assignment.role == "official_property":
        return assignment.role, str(assignment.normalized_name)
    return assignment.role, str(assignment.semantic_label)


def _unique_text(values: Sequence[str]) -> str | None:
    unique = list(dict.fromkeys(value.strip() for value in values if value.strip()))
    return " | ".join(unique) if unique else None


def _sample_binding(
    interpretation: Stage4TTableInterpretation,
    assignments: Sequence[HeaderAssignment],
    *,
    cells: Sequence[Stage0TableCell],
    cell_by_id: Mapping[str, Stage0TableCell],
    row: int,
    column: int,
) -> tuple[str | None, list[str]]:
    subject_assignments = [
        item
        for item in assignments
        if item.role in {"sample_axis", "composition_axis"}
    ]
    evidence_ids: list[str] = []
    labels: list[str] = []
    if interpretation.direction == "row_samples":
        for assignment in subject_assignments:
            for source in _source_cells(assignment, cell_by_id):
                candidate = _cell_at(cells, row, source.column_index)
                if candidate is None or candidate.cell_id == source.cell_id:
                    continue
                if candidate.text.strip():
                    labels.append(candidate.text)
                    evidence_ids.extend((source.cell_id, candidate.cell_id))
    else:
        for assignment in subject_assignments:
            for source in _source_cells(assignment, cell_by_id):
                if _covers_column(source, column) and source.text.strip():
                    labels.append(source.text)
                    evidence_ids.append(source.cell_id)
    return _unique_text(labels), list(dict.fromkeys(evidence_ids))


def _condition_binding(
    assignments: Sequence[HeaderAssignment],
    *,
    cell_by_id: Mapping[str, Stage0TableCell],
    row: int,
    column: int,
) -> tuple[dict[str, str], list[str], list[str]]:
    values: dict[str, list[str]] = defaultdict(list)
    evidence_ids: list[str] = []
    conflicts: list[str] = []
    for assignment in assignments:
        if assignment.role != "condition_axis" or not assignment.normalized_name:
            continue
        for source in _source_cells(assignment, cell_by_id):
            column_aligned = (
                source.row_index <= row and _covers_column(source, column)
            )
            row_aligned = (
                source.column_index <= column and _covers_row(source, row)
            )
            if not (column_aligned or row_aligned) or not source.text.strip():
                continue
            values[assignment.normalized_name].append(source.text.strip())
            evidence_ids.append(source.cell_id)
    conditions: dict[str, str] = {}
    for name, raw_values in values.items():
        unique = list(dict.fromkeys(raw_values))
        conditions[name] = " | ".join(unique)
        if len(unique) > 1:
            conflicts.append(f"multiple_condition_values:{name}")
    return conditions, list(dict.fromkeys(evidence_ids)), conflicts


def _measurement_role_binding(
    assignments: Sequence[HeaderAssignment],
    *,
    cell_by_id: Mapping[str, Stage0TableCell],
    row: int,
    column: int,
) -> tuple[str, list[str], list[str]]:
    roles: list[str] = []
    evidence_ids: list[str] = []
    for assignment in assignments:
        if assignment.role != "measurement_role" or not assignment.measurement_role:
            continue
        for source in _source_cells(assignment, cell_by_id):
            column_aligned = (
                source.row_index <= row and _covers_column(source, column)
            )
            row_aligned = (
                source.column_index <= column and _covers_row(source, row)
            )
            if column_aligned or row_aligned:
                roles.append(assignment.measurement_role)
                evidence_ids.append(source.cell_id)
    unique_roles = list(dict.fromkeys(roles))
    if len(unique_roles) == 1:
        return unique_roles[0], list(dict.fromkeys(evidence_ids)), []
    if len(unique_roles) > 1:
        return (
            "reported_unknown",
            list(dict.fromkeys(evidence_ids)),
            ["multiple_measurement_roles"],
        )
    return "reported_unknown", [], []


def _property_headers(
    semantic_assignments: Sequence[HeaderAssignment],
    *,
    all_assignments: Sequence[HeaderAssignment],
    cells: Sequence[Stage0TableCell],
    cell_by_id: Mapping[str, Stage0TableCell],
    row: int,
    column: int,
    direction: str,
) -> tuple[list[str], list[str], list[str]]:
    property_headers: list[str] = []
    unit_headers: list[str] = []
    evidence_ids: list[str] = []
    for assignment in semantic_assignments:
        for source in _source_cells(assignment, cell_by_id):
            if source.text.strip():
                property_headers.append(source.text.strip())
                unit_headers.append(source.text.strip())
                evidence_ids.append(source.cell_id)
    if direction == "column_samples":
        subject_columns = [
            source.column_index
            for assignment in all_assignments
            if assignment.role in {"sample_axis", "composition_axis"}
            for source in _source_cells(assignment, cell_by_id)
        ]
        data_start = min(subject_columns, default=column)
        for cell in cells:
            if _covers_row(cell, row) and cell.column_index < data_start:
                if cell.text.strip():
                    unit_headers.append(cell.text.strip())
    return (
        list(dict.fromkeys(property_headers)),
        list(dict.fromkeys(unit_headers)),
        list(dict.fromkeys(evidence_ids)),
    )


def _measurement_unit(
    *,
    headers: Sequence[str],
    value_raw: str,
    caption: str | None,
    property_name: str | None,
    semantic_label: str | None,
) -> dict[str, Any]:
    info = _unit_info([*headers, value_raw], caption)
    joined = " | ".join([*headers, value_raw])
    if property_name == "thermal_decomposition_temperature":
        if info.get("unit_normalized") == "%" or info.get("unit_raw") == "%":
            return {
                "unit_raw": None,
                "unit_normalized": None,
                "unit_location": "not_reported",
            }
    if semantic_label == "xray_diffraction_peak" and re.search(
        r"\bdeg\b|degree|2\s*\\?theta", joined, re.IGNORECASE
    ):
        return {"unit_raw": "deg", "unit_normalized": "deg", "unit_location": "header"}
    if semantic_label == "interlayer_spacing" and re.search(
        r"Å|\\AA", joined, re.IGNORECASE
    ):
        return {"unit_raw": "Å", "unit_normalized": "Å", "unit_location": "header"}
    if semantic_label == "residual_mass_fraction" and "%" in joined:
        return {"unit_raw": "%", "unit_normalized": "%", "unit_location": "header"}
    if property_name == "contact_angle" and re.search(
        r"°|\\circ", joined, re.IGNORECASE
    ):
        return {"unit_raw": "°", "unit_normalized": "deg", "unit_location": "value"}
    fallback_units = (
        (r"\bkg\s*/\s*m\s*(?:\^?3|³)\b", "kg/m3", "kg/m³"),
        (r"\bm(?:l|L)\s*/\s*100\s*g\b", "mL/100 g", "mL/100 g"),
        (r"\bm\s*(?:\^?2|²)\s*/\s*g\b", "m2/g", "m²/g"),
    )
    if not info.get("unit_normalized"):
        for pattern, raw, normalized in fallback_units:
            if re.search(pattern, joined, re.IGNORECASE):
                return {
                    "unit_raw": raw,
                    "unit_normalized": normalized,
                    "unit_location": "header",
                }
    return info


def _conflict_candidate(
    observation: Mapping[str, Any],
    semantic_keys: Sequence[tuple[str, str]],
) -> dict[str, Any]:
    candidate = copy.deepcopy(dict(observation))
    candidate["interpretation_application"] = {
        "status": "semantic_conflict",
        "semantic_candidates": [f"{role}:{name}" for role, name in semantic_keys],
    }
    blockers = list((candidate.get("publication_gate") or {}).get("blockers") or [])
    blockers.append("interpretation_semantic_conflict")
    gate = assess_publication_candidate(candidate)
    gate["blockers"] = list(dict.fromkeys([*gate["blockers"], *blockers]))
    gate["status"] = "candidate_only"
    candidate["publication_gate"] = gate
    return candidate


def apply_table_interpretation(
    table: Stage0Element,
    shadow: Mapping[str, Any],
    interpretation: Stage4TTableInterpretation | Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """应用结构解释，但始终保留在非权威 candidate_only 层。"""
    if not isinstance(interpretation, Stage4TTableInterpretation):
        interpretation = Stage4TTableInterpretation.model_validate(interpretation)
    if interpretation.table_id != table.block_id:
        raise ValueError("interpretation.table_id 与 Stage 0 表不一致")

    cells = table_cells_for(table)
    cell_by_id = {cell.cell_id: cell for cell in cells}
    assignments = list(interpretation.header_assignments)
    header_cell_ids = {
        cell_id
        for assignment in assignments
        for cell_id in assignment.source_cell_ids
    }
    applied: list[dict[str, Any]] = []
    excluded: list[str] = []
    conflicts: list[str] = []
    for original in shadow.get("observations") or []:
        cell_id = str(original.get("cell_id") or "")
        if cell_id in header_cell_ids:
            excluded.append(str(original.get("observation_id") or cell_id))
            continue
        row = int(original.get("row_index"))
        column = int(original.get("column_index"))
        semantic_assignments = _matching_assignments(
            assignments,
            roles=_PROPERTY_ROLES,
            cell_by_id=cell_by_id,
            row=row,
            column=column,
            projection=_property_projection(interpretation.direction),
        )
        semantic_keys = list(dict.fromkeys(
            _semantic_key(item) for item in semantic_assignments
        ))
        if len(semantic_keys) != 1:
            if len(semantic_keys) > 1:
                conflicts.append(str(original.get("observation_id") or cell_id))
                applied.append(_conflict_candidate(original, semantic_keys))
            else:
                applied.append(copy.deepcopy(dict(original)))
            continue

        role, semantic_name = semantic_keys[0]
        property_name = semantic_name if role == "official_property" else None
        semantic_label = (
            semantic_name if role == "material_characteristic" else None
        )
        sample_label, sample_evidence = _sample_binding(
            interpretation,
            assignments,
            cells=cells,
            cell_by_id=cell_by_id,
            row=row,
            column=column,
        )
        conditions, condition_evidence, condition_conflicts = _condition_binding(
            assignments,
            cell_by_id=cell_by_id,
            row=row,
            column=column,
        )
        measurement_role, role_evidence, role_conflicts = _measurement_role_binding(
            assignments,
            cell_by_id=cell_by_id,
            row=row,
            column=column,
        )
        property_headers, unit_headers, property_evidence = _property_headers(
            semantic_assignments,
            all_assignments=assignments,
            cells=cells,
            cell_by_id=cell_by_id,
            row=row,
            column=column,
            direction=interpretation.direction,
        )
        semantic_status, candidate_class, authority_target = semantic_classification(
            property_name,
            semantic_label,
        )
        candidate = copy.deepcopy(dict(original))
        candidate.update({
            "direction": interpretation.direction,
            "sample_label_raw": sample_label,
            "property_name_raw": _unique_text(property_headers),
            "property_name_normalized": property_name,
            "semantic_label": semantic_label,
            "semantic_status": semantic_status,
            "candidate_class": candidate_class,
            "authority_target": authority_target,
            "conditions": conditions,
            "measurement_role": measurement_role,
            "binding_status": (
                "bound" if sample_label and (property_name or semantic_label)
                else "unresolved"
            ),
            "extraction_source": "llm_structure_interpretation",
            "interpretation_application": {
                "status": "applied",
                "application_version": APPLICATION_VERSION,
                "property_assignment_cell_ids": property_evidence,
                "sample_assignment_cell_ids": sample_evidence,
                "condition_assignment_cell_ids": condition_evidence,
                "measurement_role_assignment_cell_ids": role_evidence,
                "warnings": [*condition_conflicts, *role_conflicts],
            },
            **_measurement_unit(
                headers=unit_headers,
                value_raw=str(original.get("value_raw") or ""),
                caption=table.caption,
                property_name=property_name,
                semantic_label=semantic_label,
            ),
        })
        candidate["publication_gate"] = assess_publication_candidate(candidate)
        candidate["publication_gate"]["status"] = "candidate_only"
        applied.append(candidate)

    result = copy.deepcopy(dict(shadow))
    result["direction"] = interpretation.direction
    result["axis_role"] = interpretation.axis_role
    result["observations"] = applied
    result["unresolved"] = [
        {
            "observation_id": item.get("observation_id"),
            "reason": (
                "property_mapping_not_found"
                if not (item.get("property_name_normalized") or item.get("semantic_label"))
                else "sample_label_not_found"
            ),
            "cell_id": item.get("cell_id"),
            "row_index": item.get("row_index"),
            "column_index": item.get("column_index"),
        }
        for item in applied
        if item.get("binding_status") != "bound"
    ]
    warnings = list(result.get("warnings") or [])
    if conflicts:
        warnings.append("interpretation_semantic_conflict")
    result["warnings"] = sorted(set(warnings))
    audit = {
        "status": "applied_with_conflicts" if conflicts else "applied",
        "application_version": APPLICATION_VERSION,
        "input_observation_count": len(shadow.get("observations") or []),
        "output_observation_count": len(applied),
        "applied_observation_count": sum(
            (item.get("interpretation_application") or {}).get("status") == "applied"
            for item in applied
        ),
        "excluded_header_observation_ids": excluded,
        "semantic_conflict_observation_ids": conflicts,
        "authoritative": False,
        "publication_status": "candidate_only",
    }
    return result, audit
