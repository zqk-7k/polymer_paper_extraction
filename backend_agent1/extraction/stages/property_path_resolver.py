"""Build auditable property paths from deterministic table-cell roles."""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

from stages.table_cell_roles import classify_table_cells


_UNIT_RE = re.compile(
    r"(?:°\s*[CF]|℃|℉|MPa|GPa|kPa|Pa|Hz|kHz|MHz|mol%|wt%|vol%|kGy|V|mV|kV|%)",
    re.I,
)


def _value(cell: Any, key: str, default: Any = None) -> Any:
    return cell.get(key, default) if isinstance(cell, Mapping) else getattr(cell, key, default)


def _text(cell: Any) -> str:
    return str(_value(cell, "text", "") or "").strip()


def _covers_column(cell: Any, column: int) -> bool:
    start = _value(cell, "column_index", 0)
    return start <= column < start + _value(cell, "column_span", 1)


def _covers_row(cell: Any, row: int) -> bool:
    start = _value(cell, "row_index", 0)
    return start <= row < start + _value(cell, "row_span", 1)


def _above_headers(cell: Any, cells: list[Any], roles: dict[str, dict[str, Any]]) -> list[Any]:
    row, column = _value(cell, "row_index", 0), _value(cell, "column_index", 0)
    result = [
        other for other in cells
        if (_value(other, "is_header", False) or roles.get(_value(other, "cell_id"), {}).get("is_effective_header", False))
        and _value(other, "row_index", 0) < row
        and _covers_column(other, column)
    ]
    return sorted(result, key=lambda item: (_value(item, "row_index", 0), _value(item, "column_index", 0)))


def _row_cells(cell: Any, cells: list[Any]) -> list[Any]:
    row = _value(cell, "row_index", 0)
    end = row + _value(cell, "row_span", 1)
    return [other for other in cells if _value(other, "row_index", 0) < end
            and _value(other, "row_index", 0) + _value(other, "row_span", 1) > row]


def _role(cell: Any, roles: dict[str, dict[str, Any]]) -> str:
    return str(roles.get(_value(cell, "cell_id"), {}).get("cell_role") or "unknown")


def _is_header(cell: Any, roles: dict[str, dict[str, Any]]) -> bool:
    return bool(_value(cell, "is_header", False) or roles.get(_value(cell, "cell_id"), {}).get("is_effective_header"))


def _axis_header_value(
    axis_cell: Any,
    cells: list[Any],
    roles: dict[str, dict[str, Any]],
    axis_role: str,
    target: Any,
) -> dict[str, Any]:
    headers = _above_headers(axis_cell, cells, roles)
    named_headers = [item for item in headers if _role(item, roles) == axis_role]
    header = named_headers[-1] if named_headers else None
    annotation = roles.get(_value(axis_cell, "cell_id"), {})
    reasons = []
    status = "source_aligned"
    if not named_headers:
        reasons.append("context_header_missing")
    if annotation.get("role_confidence") != "confirmed":
        reasons.append("context_role_requires_review")
    if len({_text(h) for h in named_headers}) > 1:
        reasons.append("context_header_path_requires_review")
    if _value(axis_cell, "column_span", 1) != 1:
        reasons.append("context_column_span_requires_review")
    if reasons:
        status = "candidate"
    target_start = _value(target, "row_index", 0)
    target_end = target_start + _value(target, "row_span", 1) - 1
    if not (_covers_row(axis_cell, target_start) and _covers_row(axis_cell, target_end)):
        status = "ambiguous"
        reasons.append("context_covers_only_part_of_target_rows")
    return {
        "name": _text(header) if header is not None else None,
        "value_raw": _text(axis_cell),
        "cell_id": _value(axis_cell, "cell_id"),
        "header_cell_ids": [_value(item, "cell_id") for item in headers],
        "header_path": [_text(item) for item in headers],
        "role_confidence": annotation.get("role_confidence", "needs_review"),
        "association_status": status, "association_reasons": reasons,
        "association_basis": "overlapping_rows" if status == "ambiguous" else
                             "shared_rowspan" if _value(axis_cell, "row_span", 1) > 1 else "same_row",
        **{key: _value(axis_cell, key, 1 if key.endswith("span") else 0)
           for key in ("row_index", "row_span", "column_index", "column_span")},
    }


def resolve_property_paths(cells: Iterable[Any], roles: Iterable[Mapping[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Return one path for each property-value cell, preserving ambiguity."""
    values = list(cells)
    role_rows = list(roles) if roles is not None else classify_table_cells(values)
    role_map = {str(row.get("cell_id")): dict(row) for row in role_rows}
    paths: list[dict[str, Any]] = []
    for target in values:
        target_id = _value(target, "cell_id")
        if role_map.get(target_id, {}).get("cell_role") != "property_value":
            continue
        headers = _above_headers(target, values, role_map)
        property_headers = [item for item in headers if _role(item, role_map) == "property_header"]
        scales = [item for item in headers if _role(item, role_map) == "scale_header"]
        units = [item for item in headers if _role(item, role_map) == "unit_header"]
        row = [item for item in _row_cells(target, values) if not _is_header(item, role_map)]
        sample_cells = [item for item in row if _role(item, role_map) == "sample_label" and _value(item, "column_index", 0) < _value(target, "column_index", 0)]
        condition_cells = [item for item in row if _role(item, role_map) == "condition" and item is not target]
        composition_cells = [item for item in row if _role(item, role_map) == "composition" and item is not target]
        property_name = _text(property_headers[-1]) if property_headers else None
        unit_match = _UNIT_RE.search(" ".join([_text(item) for item in [*property_headers, *units]]))
        evidence_ids = [target_id]
        evidence_ids.extend(_value(item, "cell_id") for item in [*property_headers, *scales, *units, *sample_cells, *condition_cells, *composition_cells])
        evidence_ids = list(dict.fromkeys(x for x in evidence_ids if x))
        sample_axis = {
            "label_raw": _text(sample_cells[-1]) if sample_cells else None,
            "cell_id": _value(sample_cells[-1], "cell_id") if sample_cells else None,
        }
        condition_axes = [_axis_header_value(item, values, role_map, "condition", target) for item in condition_cells]
        composition_axes = [_axis_header_value(item, values, role_map, "composition", target) for item in composition_cells]
        context_axes = condition_axes + composition_axes
        evidence_ids = list(dict.fromkeys(evidence_ids + [cid for axis in context_axes for cid in axis["header_cell_ids"]]))
        complete = bool(property_headers and sample_cells)
        ambiguous = (len(property_headers) > 1 and len({_text(item) for item in property_headers}) > 1
                     or len(sample_cells) > 1 or any(axis["association_status"] == "ambiguous" for axis in context_axes))
        inferred_header = any(e.get("rule") == "simple_first_row_header_inferred"
                              for item in headers for e in role_map.get(_value(item, "cell_id"), {}).get("role_evidence", []))
        paths.append({
            "target_cell_id": target_id,
            "value_raw": _text(target),
            "property_name_raw": property_name,
            "property_header_path": [_text(item) for item in property_headers],
            "condition_axes": condition_axes,
            "composition_axes": composition_axes,
            "sample_axis": sample_axis,
            "unit_raw": unit_match.group(0) if unit_match else None,
            "display_scale_raw": _text(scales[-1]) if scales else None,
            "evidence_cell_ids": evidence_ids,
            "path_status": "ambiguous" if ambiguous else "complete" if complete and not inferred_header
                           and all(axis["association_status"] == "source_aligned" for axis in context_axes) else "candidate",
        })
    return paths
