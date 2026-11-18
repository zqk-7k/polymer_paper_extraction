"""Stage 4T 复杂表的 LLM 结构解释契约与路由。"""

from __future__ import annotations

import json
import hashlib
import re
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from prompt_loader import PromptLoader, RenderedPrompt
from schema.polymer_schema import Stage0Element, Stage0TableCell
from stages.stage4t_table_survey import _is_value_like_numeric, survey_table
from stages.table_grid import table_cells_for
from stages.stage4t_subject_context import evidence_sources


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

    source_cell_ids: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    source_quote: str | None = None
    target_cell_ids: list[str] = Field(default_factory=list)
    role: Literal[
        "sample_axis",
        "composition_axis",
        "condition_axis",
        "official_property",
        "material_characteristic",
        "unmapped_property",
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
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_role_fields(self) -> "HeaderAssignment":
        if not self.source_cell_ids and not self.source_refs:
            raise ValueError("assignment requires a source")
        if self.source_refs and (not self.source_quote or not self.target_cell_ids):
            raise ValueError("non-cell source requires quote and explicit targets")
        if self.role == "official_property" and not self.normalized_name:
            raise ValueError("official_property 必须给出 normalized_name")
        if self.role == "material_characteristic" and not self.semantic_label:
            raise ValueError("material_characteristic 必须给出 semantic_label")
        if self.role == "measurement_role" and not self.measurement_role:
            raise ValueError("measurement_role 节点必须给出 measurement_role")
        if self.role in {
            "sample_axis",
            "condition_axis",
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
        if self.role in {"unknown", "unmapped_property"} and (
            self.normalized_name or self.semantic_label
        ):
            raise ValueError("未映射角色不得填写规范语义字段")
        for field_name in ("normalized_name", "semantic_label"):
            value = getattr(self, field_name)
            if value and not _CANONICAL_NAME_RE.fullmatch(value):
                raise ValueError(
                    f"{field_name} 必须是 canonical snake_case，不能复制原始表头"
                )
        return self


class ScopedRelation(BaseModel):
    """An evidence-backed relation; never a measured property value."""
    model_config = ConfigDict(extra="forbid")
    kind: Literal['subject', 'unit', 'condition', 'measurement_role', 'scale']
    source_refs: list[str] = Field(min_length=1)
    source_quote: str = Field(min_length=1)
    target_cell_ids: list[str] = Field(min_length=1)
    name: str | None = None
    measurement_role: Literal['experimental', 'calculated', 'reported_unknown'] | None = None
    candidate_sample_ids: list[str] = Field(default_factory=list)
    candidate_entity_ids: list[str] = Field(default_factory=list)
    condition_kind: Literal['measurement', 'processing', 'state', 'unknown'] = 'unknown'
    footnote_marker: str | None = None
    reason: str = Field(min_length=1)

    @model_validator(mode='after')
    def validate_fields(self):
        if self.kind == 'condition' and (not self.name or not _CANONICAL_NAME_RE.fullmatch(self.name)):
            raise ValueError('condition requires canonical name')
        if self.kind == 'measurement_role' and not self.measurement_role:
            raise ValueError('measurement role missing')
        if self.kind != 'subject' and (self.candidate_sample_ids or self.candidate_entity_ids):
            raise ValueError('only subject may nominate identity')
        if self.footnote_marker and not re.fullmatch(r'[A-Za-z]|\*?\d+|[*†‡]', self.footnote_marker):
            raise ValueError('invalid footnote marker')
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
    scoped_relations: list[ScopedRelation] = Field(default_factory=list)
    rejected_items: list[dict[str, Any]] = Field(default_factory=list)
    requires_human_review: bool
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def mark_unmapped_composition(self) -> "Stage4TTableInterpretation":
        if any(a.role == 'process_metadata' and not a.normalized_name for a in self.header_assignments):
            self.requires_human_review = True
            if 'metadata_name_unresolved' not in self.warnings:
                self.warnings.append('metadata_name_unresolved')
        if any(item.role == "unmapped_property" for item in self.header_assignments):
            self.requires_human_review = True
            if "property_name_outside_catalog" not in self.warnings:
                self.warnings.append("property_name_outside_catalog")
        missing = [cell for item in self.header_assignments
                   if item.role == "composition_axis" and not item.normalized_name
                   for cell in item.source_cell_ids]
        if missing:
            self.requires_human_review = True
            warning = "composition_axis_name_unresolved:" + ",".join(missing)
            if warning not in self.warnings:
                self.warnings.append(warning)
        return self


def render_interpretation_prompt(
    loader: PromptLoader | None = None,
) -> RenderedPrompt:
    return (loader or PromptLoader()).render_stage_prompt(
        PROMPT_ID,
        Stage4TTableInterpretation,
        expected_stage="stage4t_table_interpretation",
        expected_output_schema=INTERPRETATION_SCHEMA_VERSION,
    )


def interpretation_catalog() -> dict[str, Any]:
    """Use the same property registries as the application layer, without values."""
    from stages.property_semantics import default_official_vocabulary
    from stages.specialized_vocabulary import get_specialized_vocabulary
    vocabulary = get_specialized_vocabulary()
    return {
        "official_properties": sorted(default_official_vocabulary()),
        "material_characteristics": [
            {"name": entry.key, "source_field": entry.source_field,
             "variants": list(entry.variants)}
            for entry in sorted(vocabulary.entries.values(), key=lambda e: e.key)
            if "stage4t" in entry.stages
        ],
        "outside_catalog_policy": "Preserve known property roles as unmapped_property; read names from source_cell_ids. Never invent codes.",
    }


def interpretation_contract_hash() -> str:
    payload = {"prompt": render_interpretation_prompt().sha256,
               "schema": Stage4TTableInterpretation.model_json_schema(),
               "catalog": interpretation_catalog()}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


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
    context: Mapping[str, Any] | None = None,
    max_data_rows: int | None = None,
) -> dict[str, Any]:
    """保留 OCR 上下文；输出契约禁止生成性质数值。"""
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
        if max_data_rows is not None and not is_header and cell.row_index >= data_start + max_data_rows:
            continue
        included.append({
            "cell_id": cell.cell_id,
            "row_index": cell.row_index,
            "column_index": cell.column_index,
            "row_span": cell.row_span,
            "column_span": cell.column_span,
            "cell_role": "header" if is_header else "data_preview",
            "text": cell.text,
        })
    context_payload = dict(context or {})
    return {
        "input_schema_version": "stage4t_table_interpretation_input.v3",
        "numeric_policy": "OCR text is evidence only; output relations, never measured values. Images must not replace OCR values.",
        "coverage": {"total_cells": len(cells), "included_cells": len(included),
                     "complete": len(cells) == len(included)},
        "subject_catalog": context_payload.get("subject_catalog", {"entities": [], "samples": []}),
        "table_id": table.block_id,
        "caption": table.caption,
        "page": table.page,
        "context": {
            "preceding_text": list(context_payload.get("preceding_text") or []),
            "following_text": list(context_payload.get("following_text") or []),
            "footnotes": list(context_payload.get("footnotes") or []),
            "referencing_text": list(context_payload.get("referencing_text") or []),
        },
        "rule_survey": {
            "direction": structure.get("direction"),
            "axis_role": structure.get("axis_role"),
            "header_rows": structure.get("header_rows") or [],
            "warnings": structure.get("warnings") or [],
        },
        "cells": included,
        "sources": [s for s in evidence_sources(table, context)
                    if s['kind'] != 'cell'],
    }


def interpretation_route_reasons(
    survey: Mapping[str, Any],
    shadow: Mapping[str, Any] | None,
    *,
    eligible: bool,
) -> list[str]:
    if not eligible:
        return []
    observations = list((shadow or {}).get("observations") or [])
    property_candidates = list((shadow or {}).get("property_candidates") or [])
    # 只有真正没有 Stage0 cell 的空网格没有可供 LLM 解释的内容；
    # 只要表中存在 cell，即使 Shadow 暂无候选，也要允许复杂路由恢复信息。
    if (
        not observations
        and not property_candidates
        and int(survey.get("cell_count") or 0) == 0
    ):
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
    *, partial: bool = False,
) -> Stage4TTableInterpretation:
    if partial:
        prepared = json.loads(json.dumps(data, ensure_ascii=False))
        rejected = []
        for field in ('header_assignments', 'scoped_relations'):
            accepted = []
            for index, item in enumerate(prepared.get(field) or []):
                isolated = {**prepared, 'header_assignments': [], 'scoped_relations': [], field: [item]}
                try:
                    validate_interpretation(isolated, request_input)
                    accepted.append(item)
                except (ValueError, TypeError) as exc:
                    rejected.append({'field': field, 'index': index, 'raw': item, 'reason': str(exc)})
            prepared[field] = accepted
        if rejected:
            prepared['rejected_items'] = rejected
            prepared['requires_human_review'] = True
            prepared['warnings'] = [*(prepared.get('warnings') or []), 'partial_interpretation_rejected']
        return validate_interpretation(prepared, request_input)
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
    sources = {s['source_id']: s['text'] for s in request_input.get('sources', [])}
    sources.update({c['cell_id']: c['text'] for c in request_input.get('cells', [])})
    catalog = request_input.get('subject_catalog') or {}
    samples = {s['sample_id'] for s in catalog.get('samples', [])}
    entities = {s['entity_id'] for s in catalog.get('entities', [])}
    for item in [*interpretation.header_assignments, *interpretation.scoped_relations]:
        if set(item.target_cell_ids) - known_cell_ids:
            raise ValueError('unknown target cell')
        if item.source_refs:
            if set(item.source_refs) - sources.keys():
                raise ValueError('unknown source reference')
            if not any(item.source_quote in sources[s] for s in item.source_refs):
                raise ValueError('quote absent from cited source')
        if isinstance(item, ScopedRelation):
            if set(item.candidate_sample_ids) - samples or set(item.candidate_entity_ids) - entities:
                raise ValueError('unknown identity candidate')
            if item.kind == 'scale' and not any(item.source_quote.strip() == sources[s].strip() for s in item.source_refs):
                raise ValueError('scale requires complete source expression')
            if item.footnote_marker:
                from stages.source_context_semantics import explicit_note_markers
                footnotes = {s['source_id']: s['text'] for s in request_input.get('sources', []) if s.get('kind') == 'footnote'}
                if not any(ref in footnotes and item.footnote_marker.lower() in explicit_note_markers(footnotes[ref])
                           for ref in item.source_refs):
                    raise ValueError('footnote marker lacks cited definition')
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
    from stages.stage4t_compact_transport import compact_input
    wire, _ = compact_input(payload)
    return json.dumps(wire, ensure_ascii=False, separators=(",", ":"))
