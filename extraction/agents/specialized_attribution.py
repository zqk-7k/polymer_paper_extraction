"""九类 specialized 性质的非权威证据归属核验 Agent。

该 Agent 是 Stage 4R/Stage 5 可按需调用的共享服务。它只解释表头语义和
样品归属，不读取或改写数据格数值，也不决定最终发布状态。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from llm_client import (
    DEFAULT_CONFIG_PATH,
    LLMClient,
    LLMRequestError,
    load_pipeline_config,
    summarize_client_calls,
)
from prompt_loader import PromptLoader, RenderedPrompt
from schema.polymer_schema import Stage0Document, Stage0Element
from stages.stage4t_table_interpretation import build_interpretation_input
from stages.stage4t_table_survey import survey_table


AGENT_STAGE = "specialized_attribution_agent"
AGENT_VERSION = "0.1.0"
SCHEMA_VERSION = "specialized_attribution_agent_schema.v1"
PROMPT_ID = "polymer.specialized.attribution"


class SemanticAttribution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_cell_ids: list[str] = Field(min_length=1)
    decision: Literal[
        "specialized",
        "not_in_specialized_scope",
        "unknown",
    ]
    source_field: str | None = None
    semantic_label: str | None = None
    variant: str | None = None
    external_semantic_label: str | None = None
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=320)

    @model_validator(mode="after")
    def validate_decision_fields(self) -> "SemanticAttribution":
        if self.decision == "specialized":
            if not self.source_field or not self.semantic_label:
                raise ValueError(
                    "specialized 必须同时给出 source_field 和 semantic_label"
                )
        elif self.source_field or self.semantic_label or self.variant:
            raise ValueError(
                "非 specialized 决策不得填写九类 source_field/semantic_label/variant"
            )
        return self


class SampleAttribution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_label_raw: str = Field(min_length=1)
    source_cell_ids: list[str] = Field(min_length=1)
    status: Literal["matched", "ambiguous", "unmatched", "implicit_subject"]
    sample_id: str | None = None
    entity_id: str | None = None
    candidate_sample_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=320)

    @model_validator(mode="after")
    def validate_binding_fields(self) -> "SampleAttribution":
        if self.status == "matched" and not self.sample_id:
            raise ValueError("matched 必须给出 sample_id")
        if self.status != "matched" and self.sample_id:
            raise ValueError("仅 matched 可填写 sample_id")
        if self.status == "ambiguous" and len(self.candidate_sample_ids) < 2:
            raise ValueError("ambiguous 至少需要两个候选 sample_id")
        if self.status != "ambiguous" and self.candidate_sample_ids:
            raise ValueError("仅 ambiguous 可填写 candidate_sample_ids")
        return self


class SpecializedAttributionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[
        "specialized_attribution_agent_schema.v1"
    ] = SCHEMA_VERSION
    document_id: str = Field(min_length=1)
    table_id: str = Field(min_length=1)
    semantic_assignments: list[SemanticAttribution] = Field(default_factory=list)
    sample_assignments: list[SampleAttribution] = Field(default_factory=list)
    requires_human_review: bool
    warnings: list[str] = Field(default_factory=list)


def render_agent_prompt(loader: PromptLoader | None = None) -> RenderedPrompt:
    return (loader or PromptLoader()).render_stage_prompt(
        PROMPT_ID,
        SpecializedAttributionResponse,
        expected_stage=AGENT_STAGE,
        expected_output_schema=SCHEMA_VERSION,
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_specialized_vocabulary(
    path: Path,
) -> tuple[dict[str, dict[str, Any]], str]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    vocabulary = data.get("specialized_property_vocabulary")
    if not isinstance(vocabulary, dict) or not vocabulary:
        raise ValueError("配置缺少 specialized_property_vocabulary")
    result: dict[str, dict[str, Any]] = {}
    for source_field, raw in vocabulary.items():
        if not isinstance(raw, Mapping):
            raise ValueError(f"specialized 词表项无效：{source_field}")
        semantic_labels = [
            str(value) for value in raw.get("semantic_labels") or [] if value
        ]
        if not semantic_labels:
            raise ValueError(f"specialized 词表项没有 semantic_labels：{source_field}")
        result[str(source_field)] = {
            "semantic_labels": semantic_labels,
            "aliases": [str(value) for value in raw.get("aliases") or []],
            "variants": [str(value) for value in raw.get("variants") or []],
            "value_kinds": [
                str(value) for value in raw.get("value_kinds") or []
            ],
            "stages": [str(value) for value in raw.get("stages") or []],
        }
    return result, _sha256(path)


def load_approved_memory(path: Path | None) -> tuple[list[dict[str, Any]], str | None]:
    if path is None:
        return [], None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    patterns = data.get("approved_patterns") or []
    if not isinstance(patterns, list):
        raise ValueError("approved_patterns 必须是数组")
    approved = [dict(item) for item in patterns if isinstance(item, Mapping)]
    return approved, _sha256(path)


def _table(stage0: Stage0Document, table_id: str) -> tuple[Stage0Element, int]:
    for index, element in enumerate(stage0.elements):
        if element.block_id == table_id and element.type == "table":
            return element, index
    raise ValueError(f"Stage 0 中不存在表格：{table_id}")


def _nearby_evidence(
    stage0: Stage0Document,
    table_index: int,
    *,
    char_limit: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    used = 0
    candidates = []
    for distance in range(1, 7):
        for index in (table_index - distance, table_index + distance):
            if 0 <= index < len(stage0.elements):
                candidates.append(stage0.elements[index])
    seen: set[str] = set()
    for element in candidates:
        if element.block_id in seen or element.type not in {
            "text", "title", "footnote"
        }:
            continue
        seen.add(element.block_id)
        text = str(element.text or "").strip()
        if not text:
            continue
        remaining = char_limit - used
        if remaining <= 0:
            break
        text = text[:remaining]
        selected.append({
            "block_id": element.block_id,
            "page": element.page,
            "section": element.section,
            "text": text,
        })
        used += len(text)
    return selected


def _sample_catalog(stage3: Mapping[str, Any]) -> list[dict[str, Any]]:
    fields = (
        "sample_id",
        "sample_label_raw",
        "polymer_name",
        "refers_to_entity",
        "state_description",
        "material_type",
        "polymer_type",
    )
    return [
        {key: item.get(key) for key in fields}
        for item in stage3.get("samples") or []
        if isinstance(item, Mapping) and item.get("sample_id")
    ]


def _shadow_summary(
    shadow: Mapping[str, Any] | None,
    table_id: str,
) -> dict[str, Any] | None:
    if not shadow:
        return None
    for table in shadow.get("tables") or []:
        if not isinstance(table, Mapping) or table.get("table_id") != table_id:
            continue
        observations = [
            item for item in table.get("observations") or []
            if isinstance(item, Mapping)
        ]
        blockers: dict[str, int] = {}
        for item in observations:
            for blocker in (item.get("publication_gate") or {}).get("blockers") or []:
                blockers[str(blocker)] = blockers.get(str(blocker), 0) + 1
        return {
            "direction": table.get("direction"),
            "axis_role": table.get("axis_role"),
            "warnings": list(table.get("warnings") or []),
            "candidate_headers": [
                {
                    "header_context": item.get("header_context") or [],
                    "semantic_label": item.get("semantic_label"),
                    "property_name_normalized": item.get(
                        "property_name_normalized"
                    ),
                    "property_variant": item.get("property_variant"),
                }
                for item in table.get("property_candidates") or []
                if isinstance(item, Mapping)
            ],
            "observation_count": len(observations),
            "blocker_counts": blockers,
        }
    return None


def _memory_search_text(
    table_input: Mapping[str, Any],
) -> str:
    fragments = [str(table_input.get("caption") or "")]
    fragments.extend(
        str(cell.get("text") or "")
        for cell in table_input.get("cells") or []
        if isinstance(cell, Mapping) and cell.get("cell_role") == "header"
    )
    # 记忆路由只看 caption 与表头。邻近正文可能同时讨论多种性质，
    # 用它触发记忆会把无关规则带入当前表格。
    text = " ".join(fragments).casefold()
    text = text.replace("\\theta", " theta ").replace("θ", " theta ")
    text = text.replace("\\text", " ").replace("\\aa", " angstrom ")
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", text)


def select_applicable_memory(
    patterns: list[dict[str, Any]],
    *,
    table_input: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """只检索上下文命中的已批准模式，避免全局记忆污染无关任务。"""
    corpus = _memory_search_text(table_input)
    selected: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    for pattern in patterns:
        cues = [str(value) for value in pattern.get("positive_cues") or [] if value]
        matched = []
        for cue in cues:
            normalized = _memory_search_text({"caption": cue, "cells": []}).strip()
            if normalized and normalized in corpus:
                matched.append(cue)
        is_selected = bool(matched)
        if is_selected:
            selected.append(pattern)
        audit.append({
            "pattern_id": pattern.get("pattern_id"),
            "selected": is_selected,
            "matched_cues": matched,
        })
    return selected, audit


def build_agent_input(
    stage0: Stage0Document,
    stage3: Mapping[str, Any],
    *,
    table_id: str,
    vocabulary: Mapping[str, Mapping[str, Any]],
    shadow: Mapping[str, Any] | None = None,
    approved_memory: list[dict[str, Any]] | None = None,
    nearby_evidence_chars: int = 5000,
) -> dict[str, Any]:
    table, table_index = _table(stage0, table_id)
    table_input = build_interpretation_input(
        table,
        survey=survey_table(table),
        max_data_rows=24,
    )
    nearby_evidence = _nearby_evidence(
        stage0,
        table_index,
        char_limit=max(0, nearby_evidence_chars),
    )
    selected_memory, memory_audit = select_applicable_memory(
        list(approved_memory or []),
        table_input=table_input,
    )
    return {
        "input_schema_version": "specialized_attribution_agent_input.v1",
        "document_id": stage0.document_id,
        "table": table_input,
        "nearby_evidence": nearby_evidence,
        "stage3_samples": _sample_catalog(stage3),
        "current_candidate_diagnostics": _shadow_summary(shadow, table_id),
        "specialized_vocabulary": {
            key: dict(value) for key, value in vocabulary.items()
        },
        "approved_memory": selected_memory,
        "memory_retrieval": memory_audit,
        "tool_trace": [
            "load_stage0_table_grid",
            "retrieve_neighbor_evidence",
            "query_stage3_sample_catalog",
            "lookup_specialized_vocabulary",
            "summarize_shadow_candidates",
        ],
    }


def validate_agent_response(
    data: Mapping[str, Any],
    request_input: Mapping[str, Any],
    vocabulary: Mapping[str, Mapping[str, Any]],
) -> SpecializedAttributionResponse:
    response = SpecializedAttributionResponse.model_validate(data)
    if response.document_id != request_input.get("document_id"):
        raise ValueError("Agent document_id 与请求不一致")
    table = request_input.get("table") or {}
    if response.table_id != table.get("table_id"):
        raise ValueError("Agent table_id 与请求不一致")
    known_cells = {
        str(item.get("cell_id"))
        for item in table.get("cells") or []
        if isinstance(item, Mapping) and item.get("cell_id")
    }
    known_samples = {
        str(item.get("sample_id")): str(item.get("refers_to_entity") or "")
        for item in request_input.get("stage3_samples") or []
        if isinstance(item, Mapping) and item.get("sample_id")
    }
    referenced_cells = {
        cell_id
        for item in response.semantic_assignments
        for cell_id in item.source_cell_ids
    } | {
        cell_id
        for item in response.sample_assignments
        for cell_id in item.source_cell_ids
    }
    unknown_cells = sorted(referenced_cells - known_cells)
    if unknown_cells:
        raise ValueError(f"Agent 引用了未知 cell_id：{unknown_cells}")
    for item in response.semantic_assignments:
        if item.decision != "specialized":
            continue
        entry = vocabulary.get(str(item.source_field))
        if not entry:
            raise ValueError(f"Agent 使用未知 source_field：{item.source_field}")
        if item.semantic_label not in set(entry.get("semantic_labels") or []):
            raise ValueError(
                "semantic_label 与 source_field 不兼容："
                f"{item.source_field}/{item.semantic_label}"
            )
        allowed_variants = set(entry.get("variants") or [])
        if item.variant and item.variant not in allowed_variants:
            raise ValueError(
                f"variant 不在受控词表：{item.source_field}/{item.variant}"
            )
    for item in response.sample_assignments:
        referenced_samples = (
            [item.sample_id] if item.sample_id else item.candidate_sample_ids
        )
        unknown_samples = sorted(
            sample_id for sample_id in referenced_samples
            if sample_id not in known_samples
        )
        if unknown_samples:
            raise ValueError(f"Agent 引用了未知 sample_id：{unknown_samples}")
        if item.sample_id and item.entity_id:
            expected_entity = known_samples[item.sample_id]
            if expected_entity and item.entity_id != expected_entity:
                raise ValueError(
                    f"sample/entity 引用不一致：{item.sample_id}/{item.entity_id}"
                )
    return response


def _settings(config_path: Path) -> dict[str, Any]:
    config = load_pipeline_config(config_path)
    stages = config.get("stages") or {}
    value = stages.get(AGENT_STAGE) if isinstance(stages, Mapping) else None
    return dict(value) if isinstance(value, Mapping) else {}


def _call_summary(client: LLMClient, history_start: int) -> dict[str, Any]:
    call_count = len(client.call_history) - history_start
    usage, cost = summarize_client_calls(
        client,
        history_start,
        call_count=max(0, call_count),
    )
    return {
        "call_count": max(0, call_count),
        "usage": _json_safe(usage),
        "cost": _json_safe(cost),
    }


def run_attribution_agent(
    *,
    stage0: Stage0Document,
    stage3: Mapping[str, Any],
    table_id: str,
    vocabulary: Mapping[str, Mapping[str, Any]],
    vocabulary_sha256: str,
    shadow: Mapping[str, Any] | None = None,
    approved_memory: list[dict[str, Any]] | None = None,
    memory_sha256: str | None = None,
    config_path: Path = DEFAULT_CONFIG_PATH,
    client: LLMClient | None = None,
) -> dict[str, Any]:
    """运行 risk-routed propose/validate/repair；结果恒为 shadow candidate。"""
    settings = _settings(config_path)
    request_input = build_agent_input(
        stage0,
        stage3,
        table_id=table_id,
        vocabulary=vocabulary,
        shadow=shadow,
        approved_memory=approved_memory,
        nearby_evidence_chars=int(settings.get("nearby_evidence_chars") or 5000),
    )
    rendered = render_agent_prompt(PromptLoader())
    local_client = client or LLMClient.from_pipeline_config(
        stage=AGENT_STAGE,
        config_path=config_path,
    )
    history_start = len(local_client.call_history)
    max_tokens = max(512, int(settings.get("max_tokens") or 4096))
    repair_attempts = max(0, int(settings.get("max_repair_attempts") or 0))
    errors: list[str] = []
    prior: Mapping[str, Any] | None = None

    for attempt in range(repair_attempts + 1):
        if attempt == 0:
            user_payload: dict[str, Any] = request_input
        else:
            user_payload = {
                "task": "repair_previous_attribution",
                "request": request_input,
                "previous_response": prior,
                "validation_errors": errors,
            }
        try:
            llm_response = local_client.call_json(
                rendered.text,
                json.dumps(user_payload, ensure_ascii=False, separators=(",", ":")),
                max_tokens=max_tokens,
            )
            prior = llm_response.data
            validated = validate_agent_response(
                llm_response.data,
                request_input,
                vocabulary,
            )
            return {
                "schema_version": "specialized_attribution_agent_artifact.v1",
                "agent_version": AGENT_VERSION,
                "status": "succeeded",
                "authoritative": False,
                "shadow_mode": True,
                "publication_status": "candidate_only",
                "document_id": stage0.document_id,
                "table_id": table_id,
                "response": validated.model_dump(mode="json"),
                "tool_trace": request_input["tool_trace"] + [
                    "validate_agent_response"
                ],
                "repair_attempts_used": attempt,
                "prompt": {
                    "prompt_id": rendered.prompt_id,
                    "version": rendered.version,
                    "sha256": rendered.sha256,
                },
                "vocabulary_sha256": vocabulary_sha256,
                "memory_sha256": memory_sha256,
                "selected_memory_pattern_ids": [
                    item.get("pattern_id")
                    for item in request_input.get("approved_memory") or []
                ],
                "runtime": _call_summary(local_client, history_start),
            }
        except (ValueError, LLMRequestError) as exc:
            errors = [f"{type(exc).__name__}: {exc}"]
            if attempt >= repair_attempts:
                break
        except Exception as exc:
            errors = [f"{type(exc).__name__}: {exc}"]
            break

    return {
        "schema_version": "specialized_attribution_agent_artifact.v1",
        "agent_version": AGENT_VERSION,
        "status": "fallback_candidate_only",
        "authoritative": False,
        "shadow_mode": True,
        "publication_status": "candidate_only",
        "document_id": stage0.document_id,
        "table_id": table_id,
        "reason": "agent_or_validation_failure",
        "errors": errors,
        "tool_trace": request_input["tool_trace"] + ["validate_agent_response"],
        "prompt": {
            "prompt_id": rendered.prompt_id,
            "version": rendered.version,
            "sha256": rendered.sha256,
        },
        "vocabulary_sha256": vocabulary_sha256,
        "memory_sha256": memory_sha256,
        "selected_memory_pattern_ids": [
            item.get("pattern_id")
            for item in request_input.get("approved_memory") or []
        ],
        "runtime": _call_summary(local_client, history_start),
    }


def load_document_inputs(
    document_dir: Path,
) -> tuple[Stage0Document, dict[str, Any], dict[str, Any] | None]:
    stage0 = Stage0Document.model_validate(json.loads(
        (document_dir / "stage0_blocks.json").read_text(encoding="utf-8")
    ))
    stage3 = json.loads(
        (document_dir / "stage3_process.json").read_text(encoding="utf-8")
    )
    shadow_path = document_dir / "stage4t_shadow.json"
    shadow = (
        json.loads(shadow_path.read_text(encoding="utf-8"))
        if shadow_path.is_file()
        else None
    )
    return stage0, stage3, shadow


def artifact_cost(artifact: Mapping[str, Any]) -> Decimal | None:
    value = ((artifact.get("runtime") or {}).get("cost") or {}).get(
        "total_cost"
    )
    try:
        return Decimal(str(value)) if value is not None else None
    except Exception:
        return None
