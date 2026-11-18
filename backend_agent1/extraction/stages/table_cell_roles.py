"""Deterministic role classification for table cells.

This module only annotates cells. It does not publish values or choose a sample
when the table evidence is ambiguous.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Literal, Mapping


CellRole = Literal[
    "property_value",
    "condition",
    "composition",
    "sample_label",
    "property_header",
    "unit_header",
    "scale_header",
    "note",
    "unknown",
]
AxisRole = Literal[
    "sample_axis",
    "property_axis",
    "condition_axis",
    "composition_axis",
    "none",
]
RoleConfidence = Literal["confirmed", "candidate", "needs_review"]


_NUMBER_RE = re.compile(
    r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:\s*[×x*]\s*10\s*[+-]?\d+)?"
    r"(?:\s*(?:±|\+/-)\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+))?"
    r"(?:\s*[-–—]\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+))?$",
    re.I,
)
_UNIT_RE = re.compile(
    r"(?:°\s*[CF]|℃|℉|MPa|GPa|kPa|Pa|Hz|kHz|MHz|s|sec|min|h|hour|hours|"
    r"day|days|nm|µm|μm|mm|cm|mL|mol%|wt%|vol%|kGy|V|mV|kV|%)\b",
    re.I,
)
_UNIT_ONLY_RE = re.compile(
    r"^(?:unit|units|单位|°\s*[CF]|℃|℉|MPa|GPa|kPa|Pa|Hz|kHz|MHz|s|sec|min|h|hour|hours|"
    r"day|days|nm|µm|μm|mm|cm|mL|mol%|wt%|vol%|kGy|V|mV|kV|%)$",
    re.I,
)
_SCALE_RE = re.compile(r"(?:×|x|\*)\s*10\s*(?:\^|\s*)[+-]?\d+|10\s*\^\s*[+-]?\d+", re.I)
# Match the complete axis name, not a word inside a measured property such as
# glass transition temperature, relaxation time, or conductivity after UV exposure.
_AXIS_UNIT = r"(?:°\s*[CF]|℃|K|Hz|kHz|MHz|GHz|%|Pa|kPa|MPa|nm|µm|μm|s|sec|min|h|hours?|days?|kGy|Gy|wt\.?\s*%|mol\.?\s*%|vol\.?\s*%)"
_AXIS_SUFFIX = rf"(?:\s*(?:/\s*{_AXIS_UNIT}|,\s*{_AXIS_UNIT}|\({_AXIS_UNIT}\)|\[{_AXIS_UNIT}\]|\s+{_AXIS_UNIT}))?"
_CONDITION_RE = re.compile(
    r"(?:temperature|temp\.?|test temperature|measurement temperature|"
    r"frequency|freq\.?|humidity|relative humidity|pressure|wavelength|"
    r"time|duration|(?:aging|ageing|annealing|curing|drying|irradiation|UV exposure) (?:time|temperature)|"
    r"(?:irradiation |radiation |absorbed )?dose|温度|频率|湿度|压力|波长|时间|时长|剂量|辐照剂量)"
    + _AXIS_SUFFIX, re.I,
)
_COMPOSITION_RE = re.compile(
    r"(?:wt\.?\s*%|mol\.?\s*%|vol\.?\s*%|weight\s*(?:fraction|ratio)|"
    r"molar\s*(?:fraction|ratio)|composition|blend ratio|ratio|组成|质量分数|摩尔分数|配比)"
    + _AXIS_SUFFIX, re.I,
)
_NOTE_RE = re.compile(r"^(?:note|notes|remark|remarks|注|备注|说明)\b", re.I)
_SAMPLE_HEADER_RE = re.compile(
    r"^(?:sample|samples|specimen|specimens|material|materials|polymer|"
    r"code|codes|样品|材料|试样|编号)(?:\s*(?:code|id|name|label))?",
    re.I,
)


def _value(cell: Any, key: str, default: Any = None) -> Any:
    return cell.get(key, default) if isinstance(cell, Mapping) else getattr(cell, key, default)


def _covers(cell: Any, row: int, column: int) -> bool:
    return (
        _value(cell, "row_index", 0) <= row < _value(cell, "row_index", 0) + _value(cell, "row_span", 1)
        and _value(cell, "column_index", 0) <= column < _value(cell, "column_index", 0) + _value(cell, "column_span", 1)
    )


def _header_context(cell: Any, cells: list[Any]) -> list[Any]:
    row, column = _value(cell, "row_index", 0), _value(cell, "column_index", 0)
    result = []
    for other in cells:
        if not _value(other, "is_header", False):
            continue
        other_row = _value(other, "row_index", 0)
        other_column = _value(other, "column_index", 0)
        if other_row < row and other_column <= column < other_column + _value(other, "column_span", 1):
            result.append(other)
        elif other_column < column and other_row <= row < other_row + _value(other, "row_span", 1):
            result.append(other)
    return sorted(result, key=lambda item: (_value(item, "row_index", 0), _value(item, "column_index", 0)))


def _text(cell: Any) -> str:
    return str(_value(cell, "text", "") or "").strip()


def _sample_header(text: str) -> bool:
    return bool(_SAMPLE_HEADER_RE.fullmatch(text))


def _prepare_headers(cells: list[Any]) -> tuple[list[Any], set[str]]:
    """Recognize a simple td-only header row; never mutate the source grid."""
    if not cells or any(_value(c, "is_header", False) for c in cells):
        return cells, set()
    first = [c for c in cells if _value(c, "row_index", 0) == 0]
    if (len(first) < 2 or not any(_value(c, "row_index", 0) > 0 for c in cells)
            or any(not _text(c) or _NUMBER_RE.fullmatch(_text(c))
                   or _value(c, "row_span", 1) != 1 or _value(c, "column_span", 1) != 1 for c in first)
            or not any(_sample_header(_text(c)) or _CONDITION_RE.fullmatch(_text(c))
                       or _COMPOSITION_RE.fullmatch(_text(c)) for c in first)):
        return cells, set()
    ids = {_value(c, "cell_id") for c in first}
    copies = [dict(c) if isinstance(c, Mapping) else c.model_dump() for c in cells]
    for cell in copies:
        if cell["cell_id"] in ids:
            cell["is_header"] = True
    return copies, ids


def _classify_cell(cell: Any, table_cells: Iterable[Any]) -> dict[str, Any]:
    """Classify one cell and retain the rules that produced the result."""
    cells = list(table_cells)
    text = _text(cell)
    headers = _header_context(cell, cells)
    header_text = [(_value(item, "cell_id", ""), _text(item)) for item in headers]
    evidence: list[dict[str, Any]] = []
    conflicts: list[str] = []
    if not text:
        return {
            "cell_id": _value(cell, "cell_id"), "cell_role": "unknown", "axis_role": "none",
            "role_confidence": "needs_review", "role_evidence": [], "role_conflicts": [],
        }

    is_header = bool(_value(cell, "is_header", False))
    row, column = _value(cell, "row_index", 0), _value(cell, "column_index", 0)
    vertical_headers = [
        item for item in headers
        if _value(item, "row_index", 0) < row
        and _value(item, "column_index", 0) <= column < _value(item, "column_index", 0) + _value(item, "column_span", 1)
    ]
    has_sample_header = any(
        _sample_header(_text(item))
        and _value(item, "row_index", 0) < row
        and _value(item, "column_index", 0) <= column < _value(item, "column_index", 0) + _value(item, "column_span", 1)
        for item in headers
    ) or (
        column == 0
        and any(_sample_header(_text(item)) for item in headers)
    )
    # The nearest semantic header wins over a broad spanning group heading.
    semantic_headers = [h for h in vertical_headers
                        if not _UNIT_ONLY_RE.fullmatch(_text(h)) and not _SCALE_RE.search(_text(h))]
    axis_text = text if is_header else _text(semantic_headers[-1]) if semantic_headers else ""
    if _NOTE_RE.search(text):
        role, axis, confidence = "note", "none", "confirmed"
        evidence.append({"rule": "note_keyword"})
    elif is_header and _sample_header(text):
        role, axis, confidence = "sample_label", "sample_axis", "confirmed"
        evidence.append({"rule": "sample_header"})
    elif is_header and _SCALE_RE.search(text):
        role, axis, confidence = "scale_header", "property_axis", "confirmed"
        evidence.append({"rule": "scale_pattern"})
    elif is_header and _UNIT_ONLY_RE.fullmatch(text):
        role, axis, confidence = "unit_header", "property_axis", "confirmed"
        evidence.append({"rule": "unit_pattern"})
    elif _COMPOSITION_RE.fullmatch(axis_text):
        role, axis, confidence = "composition", "composition_axis", "confirmed"
        evidence.append({"rule": "composition_keyword_or_header"})
    elif _CONDITION_RE.fullmatch(axis_text):
        role, axis, confidence = "condition", "condition_axis", "confirmed"
        evidence.append({"rule": "condition_keyword_or_header"})
    elif not is_header and has_sample_header:
        role, axis, confidence = "sample_label", "sample_axis", "confirmed"
        evidence.append({"rule": "sample_axis_context"})
    elif _NUMBER_RE.fullmatch(text) and not is_header:
        role, axis, confidence = "property_value", "property_axis", "confirmed"
        evidence.append({"rule": "numeric_value"})
    elif has_sample_header or (_value(cell, "column_index", 0) == 0 and not is_header):
        role, axis, confidence = "sample_label", "sample_axis", "candidate"
        evidence.append({"rule": "sample_axis_context" if has_sample_header else "left_axis_candidate"})
    elif is_header:
        role, axis, confidence = "property_header", "property_axis", "candidate"
        evidence.append({"rule": "header_cell"})
    else:
        role, axis, confidence = "unknown", "none", "needs_review"
        evidence.append({"rule": "no_matching_rule"})

    evidence.extend({"rule": "source_header_context", "cell_id": cid, "text": value} for cid, value in header_text)
    return {
        "cell_id": _value(cell, "cell_id"), "cell_role": role, "axis_role": axis,
        "role_confidence": confidence, "role_evidence": evidence,
        "role_conflicts": conflicts,
        "is_effective_header": is_header,
    }


def classify_table_cells(cells: Iterable[Any]) -> list[dict[str, Any]]:
    """Classify a table while preserving input order."""
    values, inferred = _prepare_headers(list(cells))
    rows = [_classify_cell(cell, values) for cell in values]
    for row in rows:
        relevant = inferred.intersection({row["cell_id"], *(e.get("cell_id") for e in row["role_evidence"])})
        if relevant:
            row["role_evidence"].append({"rule": "simple_first_row_header_inferred", "cell_ids": sorted(relevant)})
            row["role_confidence"] = "candidate"
    return rows


def classify_cell(cell: Any, table_cells: Iterable[Any]) -> dict[str, Any]:
    return next(row for row in classify_table_cells(table_cells) if row["cell_id"] == _value(cell, "cell_id"))
