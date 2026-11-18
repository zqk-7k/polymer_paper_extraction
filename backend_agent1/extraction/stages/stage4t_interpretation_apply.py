"""将 Stage 4T 结构解释确定性地投影到宽松候选。"""

from __future__ import annotations

import copy
import re
from collections import Counter, defaultdict
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
from stages.table_value_inventory import capture_coverage
from stages.stage4t_scoped_relations import merge_units, apply_scoped_metadata
from stages.value_normalization import normalize_observation
from stages.property_semantics import (
    default_official_vocabulary,
    resolve_property_surface,
)
from stages.specialized_vocabulary import get_specialized_vocabulary


APPLICATION_VERSION = "0.3.0"
_PROPERTY_ROLES = {"official_property", "material_characteristic", "unmapped_property"}


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
    if assignment.target_cell_ids:
        return any(c.cell_id in assignment.target_cell_ids and c.row_index == row and c.column_index == column
                   for c in cell_by_id.values())
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
        # 横向样品表既可能按“性质行”组织，也可能是多级表头下按
        # “性质列”组织；两种布局都需要保留可安全投影的语义候选。
        return "either"
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
    if assignment.role == "unmapped_property":
        return assignment.role, "|".join(sorted([*assignment.source_cell_ids, *assignment.source_refs]))
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
        if item.role == "sample_axis"
    ]
    if not subject_assignments:
        subject_assignments = [item for item in assignments
                               if item.role == "composition_axis" and item.normalized_name]
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
    from stages.source_table_layout import refine_layout
    layout = refine_layout([c.model_dump() for c in cell_by_id.values()], {'orientation': 'unknown'})
    for assignment in assignments:
        if assignment.role != "condition_axis" or not assignment.normalized_name:
            continue
        if assignment.target_cell_ids and not any(c.cell_id in assignment.target_cell_ids and c.row_index == row and c.column_index == column for c in cell_by_id.values()):
            continue
        for source in _source_cells(assignment, cell_by_id):
            if layout['orientation'] == 'two_condition_axes' and source.row_index < layout['header_rows']:
                axis_cell = _cell_at(list(cell_by_id.values()), row, 0) if source.column_index == 0 else (
                    _cell_at(list(cell_by_id.values()), layout['header_rows'] - 1, column)
                    if _covers_column(source, column) else None)
                if axis_cell and axis_cell.text.strip():
                    headers = [c.text for c in cell_by_id.values() if c.row_index < layout['header_rows']
                               and _covers_column(c, axis_cell.column_index)]
                    unit = _unit_info(headers, None).get('unit_raw')
                    if not unit:
                        # Condition axes include time units outside the property-unit catalogue.
                        unit_match = re.search(r'\((s|sec|min|h|ms|μs|µs|Hz|kHz|MHz|nm|μm|°C|K|%)\)', ' '.join(headers))
                        unit = unit_match.group(1) if unit_match else None
                    text = axis_cell.text.strip()
                    if unit and unit not in text:
                        text += ' ' + unit
                    values[assignment.normalized_name].append(text)
                    evidence_ids.extend([source.cell_id, axis_cell.cell_id])
                continue
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
        if assignment.role not in {"measurement_role", "process_metadata", *_PROPERTY_ROLES} or not assignment.measurement_role:
            continue
        if assignment.target_cell_ids and not any(c.cell_id in assignment.target_cell_ids and c.row_index == row and c.column_index == column for c in cell_by_id.values()):
            continue
        if assignment.source_refs and assignment.target_cell_ids:
            roles.append(assignment.measurement_role)
            evidence_ids.extend(assignment.source_refs)
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
    for assignment in semantic_assignments:
        if assignment.source_quote:
            property_headers.append(assignment.source_quote)
            unit_headers.append(assignment.source_quote)
        for source in _source_cells(assignment, cell_by_id):
            declared_headers = {cid for a in all_assignments for cid in a.source_cell_ids}
            for parent in cells:
                if (parent.is_header or parent.cell_id in declared_headers) and parent.row_index < source.row_index and _covers_column(parent, source.column_index) and _covers_column(parent, column):
                    unit_headers.append(parent.text)
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
    # d_spacing 为统一后的 vocabulary key；interlayer_spacing 是历史产物里的
    # legacy 写法，仍需识别（登记表把两者都映射到 d_spacing）。
    if semantic_label in {"d_spacing", "interlayer_spacing"} and re.search(
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
    *,
    context: Mapping[str, Any] | None = None,
    _structure_sources: Sequence[Mapping[str, Any]] = (),
) -> tuple[dict[str, Any], dict[str, Any]]:
    """应用结构解释，但始终保留在非权威 candidate_only 层。

    ``context`` 是 Stage4T 已构建的局部表格上下文；缺省时仍兼容旧调用方。
    语义复核只修正明显未受控的 LLM 表头，不覆盖已有的合法语义。
    """
    from stages.stage4t_table_interpretation import build_interpretation_input, validate_interpretation
    data = interpretation.model_dump(mode='json') if isinstance(interpretation, Stage4TTableInterpretation) else interpretation
    request_input = build_interpretation_input(table, context=context)
    request_input['sources'].extend(copy.deepcopy(list(_structure_sources)))
    interpretation = validate_interpretation(data, request_input, partial=True)
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
    semantic_resolution_counts: Counter[str] = Counter()
    official_vocabulary = default_official_vocabulary()
    specialized_vocabulary = get_specialized_vocabulary()
    context_parts = [str(table.caption or "")]
    for section in ("preceding_text", "following_text", "referencing_text", "footnotes"):
        for item in (context or {}).get(section, []):
            if isinstance(item, Mapping) and item.get("text"):
                context_parts.append(str(item["text"]))
    table_context_text = " | ".join(item for item in context_parts if item)
    originals = list(shadow.get("observations") or [])
    seen = {o['cell_id'] for o in originals}
    # Explicit property targets can recover an unparsed text/mixed OCR cell.
    from stages.stage4t_table_property import _observation
    for assignment in assignments:
        if assignment.role not in _PROPERTY_ROLES:
            continue
        for target in assignment.target_cell_ids:
            cell = cell_by_id[target]
            if target in seen or target in header_cell_ids or not cell.text.strip():
                continue
            originals.append(_observation(table_id=table.block_id, cell=cell, sample_label=None,
                property_raw='', property_name=None, semantic_label=None, property_variant=None,
                conditions={}, unit={}, direction=interpretation.direction))
            seen.add(target)
    for original in originals:
        cell_id = str(original.get("cell_id") or "")
        if cell_id in header_cell_ids:
            excluded.append(str(original.get("observation_id") or cell_id))
            continue
        row = int(original.get("row_index"))
        column = int(original.get("column_index"))
        # Metadata is independently useful even when the property is unmapped.
        original = copy.deepcopy(dict(original))
        apply_scoped_metadata(original, interpretation.scoped_relations)
        metadata, metadata_evidence, metadata_conflicts = _condition_binding(
            assignments, cell_by_id=cell_by_id, row=row, column=column)
        measured_role, measured_evidence, measured_conflicts = _measurement_role_binding(
            assignments, cell_by_id=cell_by_id, row=row, column=column)
        if metadata_evidence or measured_evidence:
            prior_conditions = dict(original.get("conditions") or {})
            for key, value in metadata.items():
                if key in prior_conditions and prior_conditions[key] != value:
                    metadata_conflicts.append("existing_condition_conflict:" + key)
                else:
                    prior_conditions[key] = value
            original["conditions"] = prior_conditions
            prior_role = original.get("measurement_role", "reported_unknown")
            if measured_evidence:
                if prior_role not in {"reported_unknown", measured_role}:
                    measured_conflicts.append("existing_measurement_role_conflict")
                    measured_role = "reported_unknown"
                original["measurement_role"] = measured_role
            original["metadata_interpretation"] = {
                "condition_assignment_cell_ids": metadata_evidence,
                "measurement_role_assignment_cell_ids": measured_evidence,
                "conditions": metadata, "measurement_role": measured_role,
                "warnings": metadata_conflicts + measured_conflicts,
            }
            original["interpretation_status"] = "metadata_applied"
            original.setdefault("warnings", []).extend(metadata_conflicts + measured_conflicts)
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
        conditions = dict(original.get("conditions") or {})
        condition_evidence, condition_conflicts = metadata_evidence, metadata_conflicts
        measurement_role = original.get("measurement_role", "reported_unknown")
        role_evidence, role_conflicts = measured_evidence, measured_conflicts
        property_headers, unit_headers, property_evidence = _property_headers(
            semantic_assignments,
            all_assignments=assignments,
            cells=cells,
            cell_by_id=cell_by_id,
            row=row,
            column=column,
            direction=interpretation.direction,
        )
        property_header_text = _unique_text(property_headers) or str(
            original.get("property_name_raw") or ""
        )
        semantic_resolution = resolve_property_surface(
            property_header_text,
            context=" | ".join([table_context_text, *unit_headers]),
            value_text=str(original.get("value_raw") or ""),
            official_vocabulary=official_vocabulary,
            specialized_vocabulary=specialized_vocabulary,
            stage="stage4t",
        )
        semantic_resolution_counts[semantic_resolution.status] += 1
        semantic_warnings: list[str] = []
        if role == "unmapped_property":
            semantic_warnings.append("property_name_outside_catalog")
        if semantic_resolution.status == "specialized":
            # LLM 若把明确的 specialized 表头放入 official_property，转回
            # 专用语义；已有合法 material_characteristic 语义不被覆盖。
            if role == "unmapped_property" or (role == "official_property" and property_name not in official_vocabulary):
                property_name = None
                semantic_label = semantic_resolution.specialized_property_key
                semantic_warnings.append("semantic_rerouted_to_specialized")
        elif semantic_resolution.status == "official":
            # 只修复未受控的 official 名称；合法但与原始表头冲突时保留
            # LLM 结果并留下审计 warning，避免在多级表头中擅自改列。
            resolved_official = semantic_resolution.official_property
            if role == "unmapped_property" or (role == "official_property" and property_name not in official_vocabulary):
                property_name = resolved_official
                semantic_warnings.append("semantic_repaired_from_header")
            elif role == "material_characteristic" and not semantic_label:
                property_name = resolved_official
                semantic_label = None
                semantic_warnings.append("semantic_repaired_from_header")
            elif (
                role == "official_property"
                and resolved_official
                and property_name != resolved_official
            ):
                semantic_warnings.append("semantic_header_assignment_conflict")
        elif semantic_resolution.status == "ambiguous":
            semantic_warnings.append("semantic_context_insufficient")
        semantic_status, candidate_class, authority_target = semantic_classification(
            property_name,
            semantic_label,
        )
        assignment_confidences = [
            float(item.confidence)
            for item in semantic_assignments
            if item.confidence is not None
        ]
        interpretation_confidence = (
            min(assignment_confidences)
            if assignment_confidences
            else None
        )
        candidate = copy.deepcopy(dict(original))
        candidate.update({
            "direction": interpretation.direction,
            "sample_label_raw": sample_label or original.get("sample_label_raw"),
            "property_name_raw": property_header_text,
            "property_role": role,
            "property_name_normalized": property_name,
            "semantic_label": semantic_label,
            "semantic_status": semantic_status,
            "candidate_class": candidate_class,
            "authority_target": authority_target,
            "source_layer": "llm_enriched",
            "extraction_source": "llm_structure_interpretation",
            "interpretation_status": "applied",
            "confidence": interpretation_confidence,
            "confidence_source": "llm_header_assignment",
            "interpretation_confidence": interpretation_confidence,
            "interpretation_confidence_values": assignment_confidences,
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
                "warnings": [
                    *condition_conflicts,
                    *role_conflicts,
                    *semantic_warnings,
                ],
                "semantic_resolution": semantic_resolution.as_dict(),
            },
        })
        merge_units(candidate, _measurement_unit(
            headers=unit_headers, value_raw=str(original.get("value_raw") or ""),
            caption=table.caption, property_name=property_name, semantic_label=semantic_label))
        candidate["property_source_relations"] = [a.model_dump(mode='json') for a in semantic_assignments]
        candidate["semantic_resolution"] = semantic_resolution.as_dict()
        candidate["publication_gate"] = assess_publication_candidate(candidate)
        candidate["publication_gate"]["status"] = "candidate_only"
        applied.append(normalize_observation(candidate))

    result = copy.deepcopy(dict(shadow))
    result["direction"] = interpretation.direction
    result["axis_role"] = interpretation.axis_role
    if interpretation.sample_binding_strategy == "implicit_subject":
        result["sample_axis"] = "implicit"
    result["interpretation_rejected_items"] = interpretation.rejected_items
    result["scoped_relations"] = [r.model_dump(mode='json') for r in interpretation.scoped_relations]
    result["observations"] = applied
    if "input_cell_inventory" in result:
        result["input_capture_coverage"] = capture_coverage(result["input_cell_inventory"], applied)
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
        "shadow_observation_count": len(
            shadow.get("shadow_observations")
            or shadow.get("observations")
            or []
        ),
        "applied_observation_count": sum(
            (item.get("interpretation_application") or {}).get("status") == "applied"
            for item in applied
        ),
        "excluded_header_observation_ids": excluded,
        "semantic_conflict_observation_ids": conflicts,
        "semantic_resolution_counts": dict(sorted(semantic_resolution_counts.items())),
        "authoritative": False,
        "publication_status": "candidate_only",
    }
    return result, audit
