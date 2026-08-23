"""Stage 4T 复杂表的 LLM 结构解释契约与路由。"""

from __future__ import annotations

import json
import re
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from prompt_loader import PromptLoader, RenderedPrompt
from schema.polymer_schema import Stage0Element, Stage0TableCell
from stages.stage4t_table_survey import _is_value_like_numeric, survey_table
from stages.table_grid import table_cells_for


INTERPRETATION_SCHEMA_VERSION = "stage4t_table_interpretation_schema.v1"
PROMPT_ID = "polymer.stage4t.table_interpretation"
_STATE_VALUE_RE = re.compile(
    r"^\s*(ox|red)\s*=\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+)\s*$",
    re.IGNORECASE,
)
_LEADING_VALUE_RE = re.compile(
    r"^\s*\$?\s*(?:[<>≤≥~≈]\s*)?[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
)
_RANGE_VALUE_RE = re.compile(r"(?:\\sim|[–—:]|(?<=\d)\s*-\s*(?=\d))")
_CANONICAL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class HeaderAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_cell_ids: list[str] = Field(min_length=1)
    role: Literal[
        "sample_axis",
        "composition_axis",
        "condition_axis",
        "official_property",
        "material_characteristic",
        "process_metadata",
        "identifier",
        "measurement_role",
        "unknown",
    ]
    normalized_name: str | None = None
    semantic_label: str | None = None
    measurement_role: Literal[
        "experimental", "calculated", "reported_unknown"
    ] | None = None
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=240)

    @model_validator(mode="after")
    def validate_role_fields(self) -> "HeaderAssignment":
        if self.role == "official_property" and not self.normalized_name:
            raise ValueError("official_property 必须给出 normalized_name")
        if self.role == "material_characteristic" and not self.semantic_label:
            raise ValueError("material_characteristic 必须给出 semantic_label")
        if self.role == "measurement_role" and not self.measurement_role:
            raise ValueError("measurement_role 节点必须给出 measurement_role")
        if self.role in {
            "sample_axis",
            "composition_axis",
            "condition_axis",
            "process_metadata",
            "identifier",
        } and not self.normalized_name:
            raise ValueError(f"{self.role} 必须给出 canonical normalized_name")
        if self.role == "official_property" and self.semantic_label:
            raise ValueError("official_property 不得填写 semantic_label")
        if self.role == "material_characteristic" and self.normalized_name:
            raise ValueError("material_characteristic 不得填写 normalized_name")
        if self.role in {
            "sample_axis",
            "composition_axis",
            "condition_axis",
            "process_metadata",
            "identifier",
            "measurement_role",
        } and self.semantic_label:
            raise ValueError(f"{self.role} 不得填写 semantic_label")
        if self.role == "unknown" and (
            self.normalized_name or self.semantic_label
        ):
            raise ValueError("unknown 不得填写规范语义字段")
        for field_name in ("normalized_name", "semantic_label"):
            value = getattr(self, field_name)
            if value and not _CANONICAL_NAME_RE.fullmatch(value):
                raise ValueError(
                    f"{field_name} 必须是 canonical snake_case，不能复制原始表头"
                )
        return self


class Stage4TTableInterpretation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[
        "stage4t_table_interpretation_schema.v1"
    ] = INTERPRETATION_SCHEMA_VERSION
    table_id: str = Field(min_length=1)
    direction: Literal[
        "row_samples",
        "column_samples",
        "mixed",
        "condition_series",
        "unknown",
    ]
    axis_role: Literal[
        "named_sample",
        "composition",
        "grouped_sample",
        "condition",
        "implicit_subject",
        "unknown",
    ]
    sample_binding_strategy: Literal[
        "direct_row",
        "direct_column",
        "grouped_columns",
        "inherit_row_group",
        "implicit_subject",
        "unknown",
    ]
    header_assignments: list[HeaderAssignment] = Field(default_factory=list)
    requires_human_review: bool
    warnings: list[str] = Field(default_factory=list)


def render_interpretation_prompt(
    loader: PromptLoader | None = None,
) -> RenderedPrompt:
    return (loader or PromptLoader()).render_stage_prompt(
        PROMPT_ID,
        Stage4TTableInterpretation,
        expected_stage="stage4t_table_interpretation",
        expected_output_schema=INTERPRETATION_SCHEMA_VERSION,
    )


def _redacted_cell_text(cell: Stage0TableCell, *, is_header: bool) -> str:
    text = cell.text.strip()
    if is_header:
        return text
    if match := _STATE_VALUE_RE.fullmatch(text):
        return f"{match.group(1)} = <NUMERIC>"
    first_number = re.search(r"\d", text)
    has_semantic_prefix = bool(
        first_number and re.search(r"[A-Za-z]", text[:first_number.start()])
    )
    if _LEADING_VALUE_RE.match(text) or (
        _is_value_like_numeric(text) and not has_semantic_prefix
    ):
        if "/" in text or _RANGE_VALUE_RE.search(text):
            return "<NUMERIC_COMPOSITE>"
        if "±" in text or "\\pm" in text:
            return "<NUMERIC_WITH_UNCERTAINTY>"
        return "<NUMERIC>"
    return text


def build_interpretation_input(
    table: Stage0Element,
    *,
    survey: Mapping[str, Any] | None = None,
    max_data_rows: int = 16,
) -> dict[str, Any]:
    """构造结构解释输入；数据格数值被占位符替代。"""
    structure = dict(survey or survey_table(table))
    header_rows = set(structure.get("header_rows") or [])
    cells = table_cells_for(table)
    header_end = max(header_rows, default=-1)
    for cell in cells:
        if cell.row_index in header_rows:
            header_end = max(header_end, cell.row_index + cell.row_span - 1)
    header_rows.update(range(header_end + 1))
    data_start = header_end + 1
    included: list[dict[str, Any]] = []
    for cell in cells:
        is_header = cell.row_index in header_rows
        if not is_header and cell.row_index >= data_start + max_data_rows:
            continue
        included.append({
            "cell_id": cell.cell_id,
            "row_index": cell.row_index,
            "column_index": cell.column_index,
            "row_span": cell.row_span,
            "column_span": cell.column_span,
            "cell_role": "header" if is_header else "data_preview",
            "text": _redacted_cell_text(cell, is_header=is_header),
        })
    return {
        "input_schema_version": "stage4t_table_interpretation_input.v1",
        "table_id": table.block_id,
        "caption": table.caption,
        "page": table.page,
        "rule_survey": {
            "direction": structure.get("direction"),
            "axis_role": structure.get("axis_role"),
            "header_rows": structure.get("header_rows") or [],
            "warnings": structure.get("warnings") or [],
        },
        "cells": included,
    }


def interpretation_route_reasons(
    survey: Mapping[str, Any],
    shadow: Mapping[str, Any] | None,
    *,
    eligible: bool,
) -> list[str]:
    if not eligible:
        return []
    reasons: list[str] = []
    if survey.get("direction") == "unknown":
        reasons.append("direction_unknown")
    if survey.get("axis_role") == "grouped_sample":
        reasons.append("grouped_sample_axis")
    if (
        int(survey.get("header_level_count") or 0) > 1
        and "variable_row_width_or_spans" in set(survey.get("warnings") or [])
    ):
        reasons.append("multilevel_spanning_header")
    observations = list((shadow or {}).get("observations") or [])
    semantic = [
        item for item in observations
        if item.get("semantic_status") in {"normalized", "mapped_characteristic"}
        or item.get("property_name_normalized")
        or item.get("semantic_label")
    ]
    unmapped = [
        item for item in observations
        if item.get("semantic_status") == "unmapped"
        or not (item.get("property_name_normalized") or item.get("semantic_label"))
    ]
    if observations and not semantic:
        reasons.append("only_unmapped_candidates")
    elif observations and len(unmapped) / len(observations) >= 0.5:
        reasons.append("high_unmapped_ratio")
    if any(
        item.get("value_kind") in {
            "numeric_multiple", "numeric_range", "state_qualified_numeric"
        }
        for item in observations
    ):
        reasons.append("structured_or_composite_values")
    return list(dict.fromkeys(reasons))


def validate_interpretation(
    data: Mapping[str, Any],
    request_input: Mapping[str, Any],
) -> Stage4TTableInterpretation:
    interpretation = Stage4TTableInterpretation.model_validate(data)
    if interpretation.table_id != request_input.get("table_id"):
        raise ValueError("LLM 解释的 table_id 与请求不一致")
    known_cell_ids = {
        str(cell.get("cell_id")) for cell in request_input.get("cells", [])
    }
    referenced = {
        cell_id
        for assignment in interpretation.header_assignments
        for cell_id in assignment.source_cell_ids
    }
    unknown = sorted(referenced - known_cell_ids)
    if unknown:
        raise ValueError(f"LLM 解释引用未知 cell_id：{unknown}")
    return interpretation


def normalize_interpretation_response(
    data: Mapping[str, Any],
) -> dict[str, Any]:
    """移除模型在两个规范字段中写入的完全相同镜像值。"""
    normalized = json.loads(json.dumps(data, ensure_ascii=False))
    for assignment in normalized.get("header_assignments") or []:
        if not isinstance(assignment, dict):
            continue
        normalized_name = assignment.get("normalized_name")
        semantic_label = assignment.get("semantic_label")
        if not normalized_name or normalized_name != semantic_label:
            continue
        if assignment.get("role") == "material_characteristic":
            assignment["normalized_name"] = None
        else:
            assignment["semantic_label"] = None
    return normalized


def build_interpretation_user_message(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
