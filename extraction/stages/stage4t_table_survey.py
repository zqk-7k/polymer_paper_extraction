"""Stage 4T P1-a 表结构调查。

本模块只读取 Stage 0 表格，输出方向、表头、样品轴、单位位置和异常信号。
调查结果用于设计 Stage 4T Shadow，不直接生成 PropertyObservation。
"""

from __future__ import annotations

import html
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from schema.polymer_schema import Stage0Document, Stage0Element, Stage0TableCell
from stages.table_grid import table_cells_for
from stages.table_recall_audit import (
    _infer_header_rows,
    _is_value_like_numeric,
    _load_property_patterns,
    _looks_like_identifier,
    _normalized_text,
    _property_match,
)


SURVEY_VERSION = "0.3.0"
_UNIT_RE = re.compile(
    r"(?<![A-Za-z])(?:°|º)?\s*(?:c|k)\b|%|\b(?:dL|mL|g|kg|mg|mol|mmol|MPa|GPa|Pa|Hz|kHz|J|kJ|W|cm|mm|nm|Å|deg|degree)(?:\s*/\s*(?:g|mol|L|mL|cm))?\b",
    re.IGNORECASE,
)
_SAMPLE_WORD_RE = re.compile(
    r"\b(?:samples?|polymers?|polyesters?|resins?|specimens?|compounds?|blends?|runs?|code|sample\s*id)\b|样品|聚合物|编号|试样",
    re.IGNORECASE,
)
_PROPERTY_WORD_RE = re.compile(
    r"\b(?:yield|state|solvent|catalyst|run|found|calcd|ratio|feed|appearance)\b|溶剂|催化剂|状态",
    re.IGNORECASE,
)
_COMPOSITION_AXIS_RE = re.compile(
    r"\b(?:feed|unit)\s*ratio\b|\bcomposition\b|\bcontent\s*\(\s*phr\s*\)|\bmole\s*[- ]?%|组成|配比|含量",
    re.IGNORECASE,
)
_CONDITION_AXIS_RE = re.compile(
    r"(?:^|[^a-z])f[^a-z]*(?:\(\s*)?(?:k?hz)(?:\s*\))?"
    r"|(?:^|[^a-z])t[^a-z]*\(\s*k\s*\)"
    r"|\bfrequency\b|\btemperature\b|频率|温度",
    re.IGNORECASE,
)
_COMPOUND_VALUE_RE = re.compile(
    r"\b(?:ox|red)\s*=\s*[+-]?\d+(?:\.\d+)?\b",
    re.IGNORECASE,
)
_GROUP_ROW_EXCLUSION_RE = re.compile(r"^(?:calcd|calculated|found)$", re.IGNORECASE)


def _grid_shape(cells: Sequence[Stage0TableCell]) -> tuple[int, int]:
    if not cells:
        return 0, 0
    return (
        max(cell.row_index + cell.row_span for cell in cells),
        max(cell.column_index + cell.column_span for cell in cells),
    )


def _covers(cell: Stage0TableCell, row: int, column: int) -> bool:
    return (
        cell.row_index <= row < cell.row_index + cell.row_span
        and cell.column_index <= column < cell.column_index + cell.column_span
    )


def _cell_at(cells: Sequence[Stage0TableCell], row: int, column: int) -> Stage0TableCell | None:
    return next((cell for cell in cells if _covers(cell, row, column)), None)


def _row_cells(cells: Sequence[Stage0TableCell], row: int) -> list[Stage0TableCell]:
    return sorted(
        [cell for cell in cells if cell.row_index <= row < cell.row_index + cell.row_span],
        key=lambda item: item.column_index,
    )


def _column_cells(cells: Sequence[Stage0TableCell], column: int) -> list[Stage0TableCell]:
    return sorted(
        [cell for cell in cells if cell.column_index <= column < cell.column_index + cell.column_span],
        key=lambda item: item.row_index,
    )


def _sample_like(text: str) -> bool:
    normalized = _normalized_text(text)
    if not normalized:
        return False
    if _is_value_like_numeric(text) and not any(char.isalpha() for char in normalized):
        return False
    if len(normalized.replace(" ", "")) < 2:
        return False
    if _looks_like_identifier(text):
        return True
    if _SAMPLE_WORD_RE.search(normalized):
        return True
    # 常见的带字母样品名；排除长句和明显的方法/性质表头。
    return (
        len(normalized) <= 40
        and any(char.isalpha() for char in normalized)
        and not _PROPERTY_WORD_RE.search(normalized)
    )


def _axis_header_role(
    cells: Sequence[Stage0TableCell],
    header_rows: set[int],
) -> str:
    first_column_headers = " | ".join(
        cell.text.strip()
        for cell in cells
        if cell.row_index in header_rows
        and cell.column_index == 0
        and cell.text.strip()
    )
    if _CONDITION_AXIS_RE.search(first_column_headers):
        return "condition"
    if _COMPOSITION_AXIS_RE.search(first_column_headers):
        return "composition"
    if _SAMPLE_WORD_RE.search(_normalized_text(first_column_headers)):
        return "named_sample"
    return "unknown"


def _composition_value_like(text: str) -> bool:
    normalized = html.unescape(text or "").strip()
    return bool(
        _is_value_like_numeric(normalized)
        or re.fullmatch(r"[+-]?\d+(?:\.\d+)?\s*[:/]\s*[+-]?\d+(?:\.\d+)?", normalized)
    )


def _row_has_numeric_payload(cells: Sequence[Stage0TableCell], row: int) -> bool:
    return any(
        _is_value_like_numeric(cell.text) or _COMPOUND_VALUE_RE.search(cell.text)
        for cell in cells
        if cell.row_index == row and cell.text.strip()
    )


def _has_numeric_data_after_headers(
    cells: Sequence[Stage0TableCell],
    header_rows: set[int],
) -> bool:
    data_start = max(header_rows, default=-1) + 1
    return any(
        cell.row_index >= data_start and _is_value_like_numeric(cell.text)
        for cell in cells
    )


def _stage4t_header_rows(
    cells: Sequence[Stage0TableCell],
    patterns: Sequence[tuple[re.Pattern[str], str]],
) -> set[int]:
    """收窄被稀疏数值行或样品分组行误扩大的表头。"""
    inferred = _infer_header_rows(cells)
    if not inferred:
        first_row = [cell for cell in cells if cell.row_index == 0]
        has_explicit_sample_axis = any(
            cell.column_index == 0
            and _SAMPLE_WORD_RE.search(_normalized_text(cell.text))
            for cell in first_row
        )
        if has_explicit_sample_axis and any(
            _row_has_numeric_payload(cells, row)
            for row in range(1, _grid_shape(cells)[0])
        ):
            return {0}
    if len(inferred) <= 1:
        return inferred

    axis_role = _axis_header_role(cells, inferred)
    row_count, column_count = _grid_shape(cells)
    for row in sorted(inferred):
        if row == min(inferred):
            continue
        first = _cell_at(cells, row, 0)
        first_text = first.text.strip() if first is not None and first.row_index == row else ""
        has_payload = _row_has_numeric_payload(cells, row)
        later_has_payload = any(
            _row_has_numeric_payload(cells, later)
            for later in range(row + 1, row_count)
        )
        composition_row = (
            axis_role == "composition"
            and _composition_value_like(first_text)
            and has_payload
        )
        named_group_row = bool(
            first_text
            and not _GROUP_ROW_EXCLUSION_RE.fullmatch(_normalized_text(first_text))
            and not _property_term_like(first_text, patterns)
            and _sample_like(first_text)
            and (
                has_payload
                or (
                    first is not None
                    and first.column_span >= max(2, column_count - 1)
                    and later_has_payload
                )
            )
        )
        if composition_row or named_group_row:
            return {header_row for header_row in inferred if header_row < row}
    return inferred


def _header_direction_signal(
    cells: Sequence[Stage0TableCell],
    header_rows: set[int],
    patterns: Sequence[tuple[re.Pattern[str], str]],
    column_count: int,
) -> tuple[str, int, str]:
    """从表头识别转置/重复分组信号，不把材料或条件列当样品轴。"""
    if not header_rows:
        return "unknown", 0, "unknown"
    header_row = min(header_rows)
    labels = []
    for column in range(column_count):
        cell = _cell_at(cells, header_row, column)
        labels.append(cell.text.strip() if cell is not None else "")

    def property_like(text: str) -> bool:
        return _property_header_like(text, patterns)

    def sample_axis_header(text: str) -> bool:
        return bool(_SAMPLE_WORD_RE.search(_normalized_text(text)))

    top_cells = sorted(
        [cell for cell in cells if cell.row_index == header_row],
        key=lambda cell: cell.column_index,
    )
    has_axis_title = bool(
        top_cells
        and top_cells[0].column_index == 0
        and top_cells[0].column_span == 1
        and (
            not top_cells[0].text.strip()
            or sample_axis_header(top_cells[0].text)
        )
    )
    sample_cells = top_cells[1:] if has_axis_title else top_cells
    direct_samples = [
        cell for cell in sample_cells
        if cell.column_span == 1
        and _sample_like(cell.text)
        and not property_like(cell.text)
    ]
    if len(direct_samples) >= 2 and len(direct_samples) == len(sample_cells):
        return "column", len(direct_samples), "named_sample"

    grouped_samples = [
        cell for cell in sample_cells
        if cell.column_span > 1
        and _sample_like(cell.text)
        and not property_like(cell.text)
    ]
    grouped_widths = {cell.column_span for cell in grouped_samples}
    if (
        len(grouped_samples) >= 2
        and len(grouped_samples) == len(sample_cells)
        and len(grouped_widths) == 1
    ):
        return "column", len(grouped_samples), "grouped_sample"

    if len(labels) >= 4 and len(labels) % 2 == 0:
        sample_positions = labels[::2]
        property_positions = labels[1::2]
        if (
            sum(sample_axis_header(label) for label in sample_positions) >= 2
            and all(property_like(label) for label in property_positions)
        ):
            return "mixed", len(sample_positions), "named_sample"
    return "unknown", 0, "unknown"


def _unit_hits(text: str) -> list[str]:
    return [match.group(0).strip() for match in _UNIT_RE.finditer(html.unescape(text or ""))]


def _property_header_like(
    text: str,
    patterns: Sequence[tuple[re.Pattern[str], str]],
) -> bool:
    normalized = _normalized_text(text)
    return bool(
        _unit_hits(text)
        or _property_match(normalized, patterns)
        or re.search(r"(?:λ|max|min|t\s*[gmd]|td|tg|tm)", normalized)
    )


def _property_term_like(
    text: str,
    patterns: Sequence[tuple[re.Pattern[str], str]],
) -> bool:
    """仅识别性质名称；样品轴判断时不因名称内含单位字符而误排除。"""
    normalized = _normalized_text(text)
    return bool(
        _property_match(normalized, patterns)
        or re.search(
            r"λ|\bmax\b|\bmin\b|\bresidu(?:e|al)\b"
            r"|\b(?:t\s*[gmd]|td|tg|tm)\b|\bt\s*\d+(?:\\?%)",
            normalized,
        )
    )


def _property_columns(
    cells: Sequence[Stage0TableCell],
    header_rows: set[int],
    patterns: Sequence[tuple[re.Pattern[str], str]],
    column_count: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for column in range(column_count):
        labels = []
        for row in sorted(header_rows):
            cell = _cell_at(cells, row, column)
            if cell is not None and cell.text.strip():
                labels.append(cell.text.strip())
        context = " | ".join(labels)
        property_name = _property_match(_normalized_text(context), patterns)
        if property_name is not None:
            candidates.append({
                "column_index": column,
                "header_context": labels,
                "property_name": property_name,
            })
    return candidates


def survey_table(
    table: Stage0Element,
    *,
    property_patterns: Sequence[tuple[re.Pattern[str], str]] | None = None,
) -> dict[str, Any]:
    """调查单张 Stage 0 表格。"""
    cells = table_cells_for(table)
    row_count, column_count = _grid_shape(cells)
    patterns = list(property_patterns or _load_property_patterns())
    header_rows = _stage4t_header_rows(cells, patterns) if cells else set()
    header_axis_role = _axis_header_role(cells, header_rows)

    data_start_row = max(header_rows, default=-1) + 1
    row_scores: list[int] = []
    for row in range(data_start_row, row_count):
        row_items = _row_cells(cells, row)
        numeric_count = sum(
            bool(_is_value_like_numeric(cell.text) or _COMPOUND_VALUE_RE.search(cell.text))
            for cell in row_items
        )
        first_text = _cell_at(cells, row, 0)
        first_value = first_text.text.strip() if first_text is not None else ""
        composition_sample = (
            header_axis_role == "composition"
            and _composition_value_like(first_value)
        )
        named_sample = any(
            _sample_like(cell.text)
            and not _property_term_like(cell.text, patterns)
            and not _GROUP_ROW_EXCLUSION_RE.fullmatch(_normalized_text(cell.text))
            for cell in row_items
            if cell.column_index <= 1
        )
        grouped_sample = bool(
            named_sample
            and first_text is not None
            and first_text.row_index == row
            and first_text.column_span > 1
        )
        row_scores.append(
            1 if composition_sample and numeric_count >= 2
            else 1 if named_sample and (numeric_count or grouped_sample)
            else 0
        )

    row_score = sum(row_scores)
    header_signal, column_score, column_axis_role = _header_direction_signal(
        cells, header_rows, patterns, column_count
    )
    corner = _cell_at(cells, min(header_rows, default=0), 0)
    empty_corner = corner is None or not corner.text.strip()
    if header_axis_role == "condition" and _has_numeric_data_after_headers(cells, header_rows):
        direction = "condition_series"
    elif header_signal == "mixed" and row_score:
        direction = "mixed"
    elif header_signal == "column" and (empty_corner or not row_score):
        direction = "column_samples"
    elif row_score > 0:
        direction = "row_samples"
    else:
        direction = "unknown"

    axis_candidates = []
    if row_score:
        axis_candidates.append({"axis": "row", "score": row_score})
    if column_score:
        axis_candidates.append({"axis": "column", "score": column_score})
    sample_axis = (
        "both" if row_score and column_score and direction == "mixed"
        else "row" if direction == "row_samples"
        else "column" if direction == "column_samples"
        else "implicit" if direction == "condition_series"
        else "unknown"
    )
    axis_role = (
        "condition" if direction == "condition_series"
        else column_axis_role if direction in {"column_samples", "mixed"}
        else header_axis_role if direction == "row_samples" and header_axis_role != "unknown"
        else "named_sample" if direction == "row_samples"
        else "unknown"
    )

    header_texts = [
        cell.text.strip()
        for cell in cells
        if cell.row_index in header_rows and cell.text.strip()
    ]
    caption_text = str(table.caption or "")
    header_units = _unit_hits(" | ".join(header_texts))
    caption_units = _unit_hits(caption_text)
    data_units = _unit_hits(" | ".join(
        cell.text for cell in cells if cell.row_index not in header_rows
    ))
    unit_locations = []
    if header_units:
        unit_locations.append("header")
    if data_units:
        unit_locations.append("cell")
    if caption_units:
        unit_locations.append("caption")
    unit_location = unit_locations[0] if len(unit_locations) == 1 else (
        "multiple" if unit_locations else "not_found"
    )

    numeric_cell_count = sum(
        _is_value_like_numeric(cell.text)
        for cell in cells
        if cell.row_index not in header_rows
    )
    property_columns = _property_columns(
        cells, header_rows, patterns, column_count
    )
    warnings: list[str] = []
    if not cells:
        warnings.append("empty_table_grid")
    if not header_rows and cells:
        warnings.append("header_rows_not_detected")
    if numeric_cell_count and not property_columns:
        warnings.append("numeric_table_without_property_columns")
    if sample_axis == "unknown" and numeric_cell_count:
        warnings.append("numeric_table_without_sample_axis")
    row_widths = {
        row: len([cell for cell in cells if cell.row_index == row])
        for row in range(row_count)
    }
    if len(set(row_widths.values())) > 1:
        warnings.append("variable_row_width_or_spans")

    return {
        "table_id": table.block_id,
        "page": table.page,
        "section": table.section,
        "caption": table.caption,
        "row_count": row_count,
        "column_count": column_count,
        "cell_count": len(cells),
        "numeric_cell_count": numeric_cell_count,
        "header_rows": sorted(header_rows),
        "header_level_count": len(header_rows),
        "direction": direction,
        "sample_axis": sample_axis,
        "axis_role": axis_role,
        "sample_axis_candidates": axis_candidates,
        "property_column_candidates": property_columns,
        "unit_location": unit_location,
        "unit_hits": {
            "header": header_units,
            "cell": data_units,
            "caption": caption_units,
        },
        "warnings": sorted(set(warnings)),
    }


def survey_document(
    document: Stage0Document | Mapping[str, Any],
    *,
    property_patterns: Sequence[tuple[re.Pattern[str], str]] | None = None,
) -> dict[str, Any]:
    """调查一篇 Stage 0 文档中的所有表格。"""
    if not isinstance(document, Stage0Document):
        document = Stage0Document.model_validate(document)
    tables = [
        survey_table(table, property_patterns=property_patterns)
        for table in document.elements
        if table.type == "table"
    ]
    return {
        "document_id": document.document_id,
        "table_count": len(tables),
        "tables": tables,
    }


def survey_batch(
    batch_root: Path,
    *,
    include_empty_documents: bool = True,
) -> dict[str, Any]:
    """调查 batch_root 下所有 reference_no_* 的 Stage 0 表格。"""
    documents: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for document_dir in sorted(path for path in batch_root.iterdir() if path.is_dir()):
        stage0_path = document_dir / "stage0_blocks.json"
        if not stage0_path.is_file():
            continue
        try:
            payload = json.loads(stage0_path.read_text(encoding="utf-8"))
            report = survey_document(payload)
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            failures.append({
                "document_id": document_dir.name,
                "error": f"{type(exc).__name__}: {exc}",
            })
            continue
        if include_empty_documents or report["table_count"]:
            documents.append(report)

    tables = [table for document in documents for table in document["tables"]]
    direction_counts = Counter(table["direction"] for table in tables)
    axis_counts = Counter(table["sample_axis"] for table in tables)
    axis_role_counts = Counter(table["axis_role"] for table in tables)
    unit_counts = Counter(table["unit_location"] for table in tables)
    warning_counts = Counter(
        warning for table in tables for warning in table["warnings"]
    )
    return {
        "survey_schema_version": "stage4t_table_structure_survey.v0.3",
        "survey_version": SURVEY_VERSION,
        "batch_root": str(batch_root.resolve()),
        "document_count": len(documents),
        "table_count": len(tables),
        "failure_count": len(failures),
        "failures": failures,
        "summary": {
            "direction_counts": dict(sorted(direction_counts.items())),
            "sample_axis_counts": dict(sorted(axis_counts.items())),
            "axis_role_counts": dict(sorted(axis_role_counts.items())),
            "unit_location_counts": dict(sorted(unit_counts.items())),
            "warning_counts": dict(sorted(warning_counts.items())),
            "tables_with_property_columns": sum(
                bool(table["property_column_candidates"]) for table in tables
            ),
            "tables_with_numeric_cells": sum(
                table["numeric_cell_count"] > 0 for table in tables
            ),
        },
        "documents": documents,
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    """把调查 JSON 渲染为便于人工复核的 Markdown。"""
    summary = report.get("summary") or {}
    lines = [
        "# Stage 4T 表结构调查报告",
        "",
        f"- 调查版本：`{report.get('survey_version')}`",
        f"- 文档数：{report.get('document_count', 0)}",
        f"- 表格数：{report.get('table_count', 0)}",
        f"- 失败数：{report.get('failure_count', 0)}",
        "",
        "## 汇总",
        "",
        f"- 方向：`{summary.get('direction_counts', {})}`",
        f"- 样品轴：`{summary.get('sample_axis_counts', {})}`",
        f"- 轴角色：`{summary.get('axis_role_counts', {})}`",
        f"- 单位位置：`{summary.get('unit_location_counts', {})}`",
        f"- 性质列可识别表：{summary.get('tables_with_property_columns', 0)}",
        f"- 含数值表：{summary.get('tables_with_numeric_cells', 0)}",
        "",
        "## 逐表清单",
        "",
        "| 文献 | 表格 | 方向 | 样品轴 | 表头层级 | 单位位置 | 性质列数 | 数值格 | 异常 |",
        "|---|---|---|---:|---:|---|---:|---:|---|",
    ]
    for document in report.get("documents", []):
        for table in document.get("tables", []):
            lines.append(
                "| {doc} | {table_id} | {direction} | {axis} | {headers} | {unit} | {props} | {numeric} | {warnings} |".format(
                    doc=document.get("document_id"),
                    table_id=table.get("table_id"),
                    direction=table.get("direction"),
                    axis=table.get("sample_axis"),
                    headers=table.get("header_level_count"),
                    unit=table.get("unit_location"),
                    props=len(table.get("property_column_candidates") or []),
                    numeric=table.get("numeric_cell_count"),
                    warnings="、".join(table.get("warnings") or []) or "—",
                )
            )
    return "\n".join(lines) + "\n"
