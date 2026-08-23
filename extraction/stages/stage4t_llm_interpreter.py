"""Stage 4T 复杂表的可控 LLM 结构解释。"""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from llm_client import (
    DEFAULT_CONFIG_PATH,
    LLMClient,
    LLMJSONResponse,
    LLMRequestError,
    load_pipeline_config,
    summarize_client_calls,
)
from prompt_loader import PromptLoader
from stages.stage4t_table_interpretation import (
    build_interpretation_input,
    build_interpretation_user_message,
    normalize_interpretation_response,
    render_interpretation_prompt,
    validate_interpretation,
)


LLM_STAGE = "stage4t_table_interpretation"
INTERPRETER_VERSION = "0.4.0"
DEFAULT_MAX_TOKENS = 4096
INCOMPLETE_MARKERS = (
    "仅保留示例",
    "完整输出需补全",
    "请补全",
    "后续省略",
    "输出被截断",
    "truncated",
    "incomplete",
)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def interpretation_stage_settings(
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> dict[str, Any]:
    config = load_pipeline_config(config_path)
    stages = config.get("stages") or {}
    settings = stages.get(LLM_STAGE) if isinstance(stages, dict) else None
    return dict(settings) if isinstance(settings, dict) else {}


def approved_interpretation_tables(
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> set[tuple[str, str]]:
    approved = interpretation_stage_settings(config_path).get(
        "approved_tables"
    ) or []
    return {
        (str(item.get("doc_id")), str(item.get("table_id")))
        for item in approved
        if isinstance(item, dict) and item.get("doc_id") and item.get("table_id")
    }


def _cost_payload(response: LLMJSONResponse | None) -> dict[str, Any] | None:
    if response is None:
        return None
    usage = response.usage
    cost = response.cost
    payload: dict[str, Any] = {
        "provider": response.provider,
        "model": response.model,
        "usage": asdict(usage),
    }
    if cost is not None:
        payload["cost"] = {
            "currency": cost.currency,
            "input_per_million": str(cost.input_per_million),
            "output_per_million": str(cost.output_per_million),
            "input_cost": str(cost.input_cost),
            "output_cost": str(cost.output_cost),
            "total_cost": str(cost.total_cost),
        }
    else:
        payload["cost"] = None
    return payload


def _incomplete_reasons(
    response: LLMJSONResponse,
    client: LLMClient,
) -> list[str]:
    reasons: list[str] = []
    parsed = response.parsed_json
    raw = getattr(client, "last_raw_response", None)
    if parsed is not None:
        outside_json = "\n".join((parsed.prefix_text, parsed.trailing_text))
        if outside_json.strip():
            for marker in INCOMPLETE_MARKERS:
                if marker.casefold() in outside_json.casefold():
                    reasons.append(f"incomplete_marker:{marker}")
    if raw is not None and raw.finish_reason in {"max_tokens", "length"}:
        reasons.append(f"finish_reason:{raw.finish_reason}")
    return list(dict.fromkeys(reasons))


def _structural_completeness_reasons(interpretation: Any) -> list[str]:
    assignments = list(interpretation.header_assignments)
    if not assignments:
        return ["missing_header_assignments"]
    roles = {item.role for item in assignments}
    reasons: list[str] = []
    if interpretation.direction in {"row_samples", "column_samples", "mixed"}:
        if not roles.intersection({"sample_axis", "composition_axis"}):
            reasons.append("missing_subject_axis_assignment")
    semantic_roles = {
        "official_property",
        "material_characteristic",
        "process_metadata",
        "unknown",
    }
    if not roles.intersection(semantic_roles):
        reasons.append("missing_semantic_assignment")
    return reasons


def _response_raw_metadata(client: LLMClient) -> dict[str, Any] | None:
    raw = getattr(client, "last_raw_response", None)
    if raw is None:
        return None
    return {
        "finish_reason": raw.finish_reason,
        "provider": raw.provider,
        "model": raw.model,
    }


def _fallback(
    *,
    reason: str,
    client: LLMClient | None,
    error: Exception | None = None,
    response: LLMJSONResponse | None = None,
    call_attempted: bool = False,
) -> dict[str, Any]:
    summary = None
    if client is not None:
        history = getattr(client, "call_history", [])
        summary = summarize_client_calls(
            client,
            0,
            call_count=len(history),
        )
    artifact: dict[str, Any] = {
        "status": "fallback_candidate_only",
        "authoritative": False,
        "reason": reason,
        "publication_status": "candidate_only",
        "llm_call_attempted": call_attempted,
        "cost": _cost_payload(response),
        "raw_response": _response_raw_metadata(client),
    }
    if summary is not None:
        usage, cost = summary
        artifact["usage_summary"] = {
            "usage": _json_safe(usage),
            "cost": _json_safe(cost),
        }
    if error is not None:
        artifact["error_type"] = type(error).__name__
        artifact["error"] = str(error)
    return artifact


def interpret_table_with_llm(
    table: Any,
    *,
    survey: Mapping[str, Any],
    shadow: Mapping[str, Any],
    config_path: Path = DEFAULT_CONFIG_PATH,
    client: LLMClient | None = None,
) -> dict[str, Any]:
    """调用一次结构解释 LLM；失败或不完整时安全回落为候选态。"""
    local_client = client
    response: LLMJSONResponse | None = None
    call_attempted = False
    try:
        if local_client is None:
            local_client = LLMClient.from_pipeline_config(
                stage=LLM_STAGE,
                config_path=config_path,
            )
        request_input = build_interpretation_input(table, survey=survey)
        rendered = render_interpretation_prompt(PromptLoader())
        stage_settings = interpretation_stage_settings(config_path)
        max_tokens = max(
            256,
            int(stage_settings.get("max_tokens") or DEFAULT_MAX_TOKENS),
        )
        call_attempted = True
        response = local_client.call_json(
            rendered.text,
            build_interpretation_user_message(request_input),
            max_tokens=max_tokens,
        )
        incomplete = _incomplete_reasons(response, local_client)
        if incomplete:
            return _fallback(
                reason=";".join(incomplete),
                client=local_client,
                response=response,
                call_attempted=call_attempted,
            )
        interpretation = validate_interpretation(
            normalize_interpretation_response(response.data),
            request_input,
        )
        structural_incomplete = _structural_completeness_reasons(
            interpretation
        )
        if structural_incomplete:
            return _fallback(
                reason=";".join(structural_incomplete),
                client=local_client,
                response=response,
                call_attempted=call_attempted,
            )
        return {
            "status": "succeeded",
            "authoritative": False,
            "publication_status": "candidate_only",
            "llm_call_attempted": True,
            "interpretation": interpretation.model_dump(mode="json"),
            "cost": _cost_payload(response),
            "raw_response": _response_raw_metadata(local_client),
        }
    except (LLMRequestError, ValueError) as exc:
        return _fallback(
            reason="llm_or_schema_failure",
            client=local_client,
            error=exc,
            response=response,
            call_attempted=call_attempted,
        )
    except Exception as exc:  # 配置/API key 错误也不得阻断非权威 sidecar
        return _fallback(
            reason="llm_configuration_or_runtime_failure",
            client=local_client,
            error=exc,
            response=response,
            call_attempted=call_attempted,
        )


def disabled_interpretation(reason: str = "feature_disabled") -> dict[str, Any]:
    return {
        "status": "disabled",
        "authoritative": False,
        "publication_status": "candidate_only",
        "llm_call_attempted": False,
        "reason": reason,
    }
