"""在 Preview 中生成非权威、可独立丢弃的 Stage 4T Shadow sidecar。"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping

EXTRACTION_ROOT = Path(__file__).resolve().parents[1]
if str(EXTRACTION_ROOT) not in sys.path:
    sys.path.insert(0, str(EXTRACTION_ROOT))

from llm_client import DEFAULT_CONFIG_PATH
from schema.polymer_schema import Stage0Document
from stages.stage4t_table_property import (
    SHADOW_VERSION,
    build_table_interpretation_context,
    shadow_extract_document,
)
from stages.stage4t_llm_interpreter import (
    INTERPRETER_VERSION,
    disabled_interpretation,
    interpret_table_with_llm,
)
from stages.stage4t_table_interpretation import interpretation_route_reasons, render_interpretation_prompt, interpretation_contract_hash
from stages.stage4t_interpretation_apply import (
    APPLICATION_VERSION,
    apply_table_interpretation,
)
from stages.stage4t_table_survey import survey_table


SIDECAR_SCHEMA_VERSION = "stage4t_preview_sidecar.v0.6"
OUTPUT_NAME = "stage4t_shadow.json"
LLM_INTERPRETATION_SCOPE = "routed_complex_tables"


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _summary(document: Mapping[str, Any]) -> dict[str, Any]:
    tables = document.get("tables", [])
    observations = [
        item for table in tables for item in table.get("observations", [])
    ]
    unresolved = [
        item for table in tables for item in table.get("unresolved", [])
    ]
    coverage = [table.get("input_capture_coverage", {}) for table in tables]
    expected = sum(item.get("expected", 0) for item in coverage)
    captured = sum(item.get("captured", 0) for item in coverage)
    return {
        "input_capture_coverage": {
            "metric_scope": "candidate_capture_not_property_recall",
            "denominator_basis": "input_numeric_data_region_provisional",
            "expected": expected, "captured": captured,
            "missing": expected - captured,
            "ratio": captured / expected if expected else None,
            "pending_interpretation": sum(item.get("pending_interpretation", 0) for item in coverage),
            "tables_requiring_review": [table["table_id"] for table in tables
                if table.get("input_capture_coverage", {}).get("status") != "captured"],
            "requires_role_review": True,
        },
        "observation_count": len(observations),
        "binding_status_counts": dict(sorted(Counter(
            item.get("binding_status") for item in observations
        ).items())),
        "candidate_class_counts": dict(sorted(Counter(
            item.get("candidate_class") for item in observations
        ).items())),
        "semantic_status_counts": dict(sorted(Counter(
            item.get("semantic_status") for item in observations
        ).items())),
        "publication_status_counts": dict(sorted(Counter(
            (item.get("publication_gate") or {}).get("status")
            for item in observations
        ).items())),
        "unresolved_count": len(unresolved),
        "tables_with_observations": sum(
            bool(table.get("observations")) for table in tables
        ),
        "warning_counts": dict(sorted(Counter(
            warning
            for table in tables
            for warning in table.get("warnings", [])
        ).items())),
    }


def _interpretation_summary(
    interpretations: list[Mapping[str, Any]],
) -> dict[str, Any]:
    applications = [
        item.get("application")
        for item in interpretations
        if isinstance(item.get("application"), Mapping)
    ]
    input_observation_count = sum(
        int(item.get("input_observation_count") or 0)
        for item in applications
    )
    output_observation_count = sum(
        int(item.get("output_observation_count") or 0)
        for item in applications
    )
    excluded_header_count = sum(
        len(item.get("excluded_header_observation_ids") or [])
        for item in applications
    )
    enriched_observation_count = sum(
        int(item.get("applied_observation_count") or 0)
        for item in applications
    )
    shadow_retained_count = max(
        0,
        output_observation_count - enriched_observation_count,
    )
    unaccounted_count = (
        input_observation_count
        - output_observation_count
        - excluded_header_count
    )
    return {
        "routed_table_count": len(interpretations),
        "route_reason_counts": dict(sorted(Counter(
            reason
            for item in interpretations
            for reason in item.get("route_reasons") or []
        ).items())),
        "status_counts": dict(sorted(Counter(
            str(item.get("status") or "unknown")
            for item in interpretations
        ).items())),
        "llm_attempt_count": sum(
            bool(item.get("llm_call_attempted"))
            for item in interpretations
        ),
        "fallback_count": sum(
            str(item.get("status") or "").startswith("fallback")
            for item in interpretations
        ),
        "application_status_counts": dict(sorted(Counter(
            str((item.get("application") or {}).get("status") or "not_applied")
            for item in interpretations
        ).items())),
        "interpretation_duration_seconds": round(sum(
            float(item.get("duration_seconds") or 0)
            for item in interpretations
        ), 6),
        "candidate_conservation": {
            "input_observation_count": input_observation_count,
            "output_observation_count": output_observation_count,
            "enriched_observation_count": enriched_observation_count,
            "shadow_retained_count": shadow_retained_count,
            "excluded_header_count": excluded_header_count,
            "unaccounted_count": unaccounted_count,
            "balanced": unaccounted_count == 0,
        },
    }


def _table_interpretation_context(
    document: Stage0Document,
    table: Any,
) -> dict[str, Any]:
    """兼容旧调用方；实际逻辑由 Stage4T 共用上下文构建器提供。"""

    return build_table_interpretation_context(document, table)


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _llm_billing(
    interpretations: list[dict[str, Any]],
    *,
    enabled: bool,
) -> dict[str, Any]:
    usage_fields = (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    )
    usage = {field: 0 for field in usage_fields}
    attempts = [
        item for item in interpretations if item.get("llm_call_attempted")
    ]
    if not enabled or not attempts:
        usage.update({"billable_input_tokens": 0, "total_tokens": 0})
        return {
            "call_count": 0,
            "usage": usage,
            "cost": {
                "status": "not_applicable",
                "currency": None,
                "input_per_million": None,
                "output_per_million": None,
                "input_cost": "0",
                "output_cost": "0",
                "total_cost": "0",
            },
            "raw_response": None,
        }

    calculated_costs: list[dict[str, Any]] = []
    billing_complete = True
    for item in attempts:
        direct = item.get("cost") or {}
        summary = item.get("usage_summary") or {}
        item_usage = direct.get("usage") or summary.get("usage") or {}
        for field in usage_fields:
            usage[field] += int(item_usage.get(field) or 0)
        direct_cost = direct.get("cost")
        summary_cost = summary.get("cost") or {}
        if isinstance(direct_cost, dict):
            calculated_costs.append(direct_cost)
        elif summary_cost.get("status") == "calculated":
            calculated_costs.append(summary_cost)
        else:
            billing_complete = False

    billable_input = (
        usage["input_tokens"]
        + usage["cache_creation_input_tokens"]
        + usage["cache_read_input_tokens"]
    )
    usage.update({
        "billable_input_tokens": billable_input,
        "total_tokens": billable_input + usage["output_tokens"],
    })
    if not billing_complete or len(calculated_costs) != len(attempts):
        cost = {
            "status": "unavailable",
            "currency": None,
            "input_per_million": None,
            "output_per_million": None,
            "input_cost": None,
            "output_cost": None,
            "total_cost": None,
        }
    else:
        first = calculated_costs[0]
        totals: dict[str, Decimal] = {}
        for field in ("input_cost", "output_cost", "total_cost"):
            values = [_decimal(item.get(field)) for item in calculated_costs]
            if any(value is None for value in values):
                billing_complete = False
                break
            totals[field] = sum(
                (value for value in values if value is not None),
                start=Decimal(0),
            )
        if not billing_complete:
            cost = {
                "status": "unavailable",
                "currency": first.get("currency"),
                "input_per_million": first.get("input_per_million"),
                "output_per_million": first.get("output_per_million"),
                "input_cost": None,
                "output_cost": None,
                "total_cost": None,
            }
        else:
            cost = {
                "status": "calculated",
                "currency": first.get("currency"),
                "input_per_million": first.get("input_per_million"),
                "output_per_million": first.get("output_per_million"),
                **{key: str(value) for key, value in totals.items()},
            }
    return {
        "call_count": len(attempts),
        "usage": usage,
        "cost": cost,
        "raw_response": None,
    }


def _reusable_interpretation(
    cached: Mapping[str, Any],
    *,
    table_id: str,
    shadow_version: str,
    source_sha256: str,
    config_sha256: str | None,
) -> dict[str, Any] | None:
    provenance = cached.get("provenance") or {}
    cached_shadow_version = str(cached.get("shadow_version") or "")
    # 0.6.5 adds an input inventory without changing source cell IDs. Reuse
    # only the interpretation; always regenerate candidates with current rules.
    shadow_version_compatible = (
        cached_shadow_version == shadow_version
        or (
            shadow_version == "0.6.5"
            and cached_shadow_version in {
                "0.6.0", "0.6.1", "0.6.2", "0.6.3", "0.6.4"
            }
        )
    )
    if (
        not cached.get("llm_interpretation_enabled")
        or not shadow_version_compatible
        or cached.get("llm_interpreter_version") != INTERPRETER_VERSION
        or cached.get("interpretation_contract_sha256") != interpretation_contract_hash()
        or provenance.get("stage0_sha256") != source_sha256
        or provenance.get("config_sha256") != config_sha256
    ):
        return None
    previous = next(
        (
            item
            for item in cached.get("interpretations") or []
            if item.get("table_id") == table_id
            and item.get("status") == "succeeded"
            and isinstance(item.get("interpretation"), Mapping)
        ),
        None,
    )
    if previous is None:
        return None
    reused = copy.deepcopy(dict(previous))
    reused["llm_call_attempted"] = False
    reused["cost"] = None
    reused["usage_summary"] = None
    reused["reused_from_sidecar"] = True
    reused["reused_from_sidecar_schema_version"] = cached.get(
        "sidecar_schema_version"
    )
    return reused


def _run_table_interpretation(
    *,
    table: Any,
    table_report: Mapping[str, Any],
    table_context: Mapping[str, Any],
    survey: Mapping[str, Any],
    route_reasons: list[str],
    enable_llm_interpretation: bool,
    cached_report: Mapping[str, Any],
    source_sha256: str,
    config_sha256: str | None,
    resolved_config_path: Path,
    checkpoint_dir: Path | None = None,
    retry_failed_tables: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """执行单张路由表的解释；供串行和有限并发路径共用。"""

    started_at = _utc_timestamp()
    started_clock = perf_counter()
    table_id = str(table_report.get("table_id") or "")
    if not enable_llm_interpretation or table is None:
        result = disabled_interpretation(
            "feature_disabled"
            if not enable_llm_interpretation
            else "stage0_table_not_found"
        )
    else:
        fingerprint = hashlib.sha256(json.dumps({
            "stage0_sha256":source_sha256, "config_sha256":config_sha256,
            "table_id":table_id, "shadow_version":SHADOW_VERSION,
            "context": table_context,
            "interpreter_version":INTERPRETER_VERSION,
            "interpretation_contract_sha256":interpretation_contract_hash(),
        }, sort_keys=True).encode("utf-8")).hexdigest()
        checkpoint_path = checkpoint_dir / (hashlib.sha256(table_id.encode()).hexdigest() + ".json") if checkpoint_dir else None
        previous = None
        if checkpoint_path and checkpoint_path.is_file() and not force:
            try:
                checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                if checkpoint.get("input_fingerprint") == fingerprint:
                    previous = checkpoint.get("result")
            except (OSError, ValueError):
                pass
        if previous and (previous.get("status") == "succeeded" or not retry_failed_tables):
            reused = copy.deepcopy(previous)
            reused.update(llm_call_attempted=False, cost=None, usage_summary=None, reused_from_checkpoint=True)
        else:
            reused = None
        reused = reused or (None if force else _reusable_interpretation(
            cached_report,
            table_id=table_id,
            shadow_version=SHADOW_VERSION,
            source_sha256=source_sha256,
            config_sha256=config_sha256,
        ))
        if reused:
            result = reused
        else:
            if checkpoint_path:
                _write_json_atomic(checkpoint_path, {"input_fingerprint":fingerprint,
                    "result":{"status":"fallback_candidate_only", "reason":"request_interrupted_or_unknown",
                              "llm_call_attempted":True, "publication_status":"candidate_only", "authoritative":False}})
            result = interpret_table_with_llm(table, survey=survey, shadow=table_report,
                                             context=table_context, config_path=resolved_config_path)
        if checkpoint_path and not reused:
            _write_json_atomic(checkpoint_path, {"input_fingerprint":fingerprint, "result":result})
    result = _align_interpretation_with_shadow(result, survey)
    return {
        "table_id": table_id,
        "route_reasons": route_reasons,
        "context_source_block_ids": list(
            table_context.get("source_block_ids") or []
        ),
        **result,
        "started_at": started_at,
        "duration_seconds": round(perf_counter() - started_clock, 6),
    }


def _align_interpretation_with_shadow(
    result: dict[str, Any],
    survey: Mapping[str, Any],
) -> dict[str, Any]:
    """将高置信的表结构信号应用到可复用的 LLM 解释。"""
    interpretation = result.get("interpretation")
    if not isinstance(interpretation, Mapping):
        return result
    if (
        survey.get("direction") != "column_samples"
        or survey.get("axis_role") != "grouped_sample"
        or interpretation.get("direction")
        not in {"row_samples", "column_samples", "mixed"}
    ):
        return result
    adjusted = dict(interpretation)
    changes: list[str] = []
    if adjusted.get("direction") != "column_samples":
        adjusted["direction"] = "column_samples"
        changes.append("direction=column_samples")
    if adjusted.get("axis_role") != "grouped_sample":
        adjusted["axis_role"] = "grouped_sample"
        changes.append("axis_role=grouped_sample")
    if adjusted.get("sample_binding_strategy") != "grouped_columns":
        adjusted["sample_binding_strategy"] = "grouped_columns"
        changes.append("sample_binding_strategy=grouped_columns")
    if not changes:
        return result
    aligned = dict(result)
    aligned["interpretation"] = adjusted
    aligned["rule_adjustments"] = [
        *list(result.get("rule_adjustments") or []),
        {
            "code": "shadow_grouped_sample_alignment",
            "changes": changes,
            "reason": "高置信 Shadow 识别为列分组样品，修正可复用解释的轴角色",
        },
    ]
    return aligned


def run_sidecar(
    *,
    input_root: Path,
    output_root: Path,
    ref_no: str,
    force: bool = False,
    enable_llm_interpretation: bool = False,
    table_workers: int = 1,
    config_path: Path | None = None,
    retry_failed_tables: bool = False,
) -> tuple[Path, bool]:
    if table_workers < 1:
        raise ValueError("table_workers 必须大于 0")
    started_at = _utc_timestamp()
    started_clock = perf_counter()
    source_path = input_root / ref_no / "stage0_blocks.json"
    output_path = output_root / ref_no / OUTPUT_NAME
    source_sha256 = _sha256_file(source_path)
    from stages.stage4t_subject_context import load_subject_summary
    subject_root = output_root / ref_no
    source_document_id = json.loads(source_path.read_text(encoding="utf-8")).get("document_id")
    subject_catalog, subject_hashes = load_subject_summary(subject_root, source_document_id, input_root / ref_no)
    resolved_config_path = config_path or DEFAULT_CONFIG_PATH
    config_sha256 = (
        _sha256_file(resolved_config_path)
        if enable_llm_interpretation and resolved_config_path.is_file()
        else None
    )
    interpretation_scope = (
        LLM_INTERPRETATION_SCOPE
        if enable_llm_interpretation
        else "disabled"
    )

    cached_report: dict[str, Any] = {}
    if output_path.is_file():
        try:
            cached_report = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached_report = {}
        provenance = cached_report.get("provenance") or {}
        if (
            not force
            and not retry_failed_tables
            and
            cached_report.get("sidecar_schema_version") == SIDECAR_SCHEMA_VERSION
            and cached_report.get("shadow_version") == SHADOW_VERSION
            and cached_report.get("llm_interpretation_enabled")
            == enable_llm_interpretation
            and cached_report.get("llm_interpretation_scope")
            == interpretation_scope
            and cached_report.get("table_workers", 1) == table_workers
            and cached_report.get("llm_interpreter_version")
            == INTERPRETER_VERSION
            and cached_report.get("interpretation_contract_sha256") == interpretation_contract_hash()
            and cached_report.get("interpretation_application_version")
            == APPLICATION_VERSION
            and provenance.get("stage0_sha256") == source_sha256
            and provenance.get("subject_input_hashes") == subject_hashes
            and provenance.get("config_sha256") == config_sha256
        ):
            return output_path, True

    payload = json.loads(source_path.read_text(encoding="utf-8"))
    stage0_document = Stage0Document.model_validate(payload)
    stage0_tables = {
        element.block_id: element
        for element in stage0_document.elements
        if element.type == "table"
    }
    table_contexts = {
        table_id: _table_interpretation_context(stage0_document, table)
        for table_id, table in stage0_tables.items()
    }
    for context in table_contexts.values():
        context["subject_catalog"] = subject_catalog
    if (cached_report.get("provenance") or {}).get("subject_input_hashes") != subject_hashes:
        cached_report = {}
    shadow_started_clock = perf_counter()
    document = shadow_extract_document(
        stage0_document,
        table_contexts=table_contexts,
    )
    shadow_duration_seconds = round(perf_counter() - shadow_started_clock, 6)
    routed_entries: list[dict[str, Any]] = []
    for table_report in document["tables"]:
        table = stage0_tables.get(table_report.get("table_id"))
        table_context = table_contexts.get(
            str(table_report.get("table_id")),
            {},
        )
        survey = survey_table(table) if table is not None else {}
        reasons = interpretation_route_reasons(
            survey,
            table_report,
            eligible=True,
        )
        if not reasons:
            continue
        routed_entries.append({
            "table": table,
            "table_report": table_report,
            "table_context": table_context,
            "survey": survey,
            "route_reasons": reasons,
        })

    def run_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
        return _run_table_interpretation(
            table=entry.get("table"),
            table_report=entry["table_report"],
            table_context=entry["table_context"],
            survey=entry["survey"],
            route_reasons=entry["route_reasons"],
            enable_llm_interpretation=enable_llm_interpretation,
            cached_report=cached_report,
            source_sha256=source_sha256,
            config_sha256=config_sha256,
            resolved_config_path=resolved_config_path,
            checkpoint_dir=output_path.parent / "stage4t_checkpoints",
            retry_failed_tables=retry_failed_tables,
            force=force,
        )

    if table_workers == 1 or len(routed_entries) <= 1:
        interpretation_records = [run_entry(entry) for entry in routed_entries]
    else:
        with ThreadPoolExecutor(max_workers=table_workers) as executor:
            futures = [executor.submit(run_entry, entry) for entry in routed_entries]
            # 按 routed_entries 原顺序收集，保证 sidecar 和审计稳定。
            interpretation_records = [future.result() for future in futures]

    interpretations: list[dict[str, Any]] = []
    for entry, interpretation_record in zip(
        routed_entries,
        interpretation_records,
    ):
        table = entry.get("table")
        table_report = entry["table_report"]
        if (
            table is not None
            and interpretation_record.get("status") == "succeeded"
            and isinstance(interpretation_record.get("interpretation"), Mapping)
        ):
            rule_observations = copy.deepcopy(
                list(table_report.get("observations") or [])
            )
            try:
                applied_table, application = apply_table_interpretation(
                    table,
                    table_report,
                    interpretation_record["interpretation"],
                    context=entry["table_context"],
                )
            except (TypeError, ValueError) as exc:
                application = {
                    "status": "failed_candidate_only",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "authoritative": False,
                    "publication_status": "candidate_only",
                }
                table_report.setdefault("warnings", []).append(
                    "interpretation_application_failed"
                )
            else:
                table_report.clear()
                table_report.update(applied_table)
                table_report["rule_observations"] = rule_observations
                table_report["llm_enriched_observations"] = copy.deepcopy(
                    list(applied_table.get("observations") or [])
                )
                table_report["interpretation_application"] = application
            interpretation_record["application"] = application
        interpretations.append(interpretation_record)
    billing = _llm_billing(
        interpretations,
        enabled=enable_llm_interpretation,
    )
    ended_at = _utc_timestamp()
    report = {
        "sidecar_schema_version": SIDECAR_SCHEMA_VERSION,
        "shadow_version": SHADOW_VERSION,
        "authoritative": False,
        "candidate_layer": "broad",
        "llm_interpretation_enabled": enable_llm_interpretation,
        "llm_interpretation_scope": interpretation_scope,
        "table_workers": table_workers,
        "llm_interpreter_version": INTERPRETER_VERSION,
        "interpretation_contract_sha256": interpretation_contract_hash(),
        "interpretation_application_version": APPLICATION_VERSION,
        "document_id": document["document_id"],
        "table_count": document["table_count"],
        "summary": _summary(document),
        "tables": document["tables"],
        "subject_catalog": subject_catalog,
        "interpretations": interpretations,
        "interpretation_summary": _interpretation_summary(interpretations),
        "provenance": {
            "source": "stage0_blocks.json",
            "subject_input_hashes": subject_hashes,
            "stage0_sha256": source_sha256,
            "config_sha256": config_sha256,
            "timing": {
                "started_at": started_at,
                "ended_at": ended_at,
                "duration_seconds": round(
                    perf_counter() - started_clock,
                    6,
                ),
                "shadow_duration_seconds": shadow_duration_seconds,
                "interpretation_duration_seconds": round(sum(
                    float(item.get("duration_seconds") or 0)
                    for item in interpretations
                ), 6),
            },
            **billing,
        },
    }
    _write_json_atomic(output_path, report)
    return output_path, False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="生成非权威 Stage 4T Preview Shadow sidecar"
    )
    parser.add_argument("--ref-no", required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--retry-failed-tables", action="store_true",
                        help="显式补跑失败/状态不明的T表；复用已有成功解释")
    parser.add_argument(
        "--stage4t-llm-interpretation",
        action="store_true",
        help="显式启用 Stage 4T 复杂表 LLM 结构解释；失败仍回落 candidate_only",
    )
    parser.add_argument(
        "--stage4t-table-workers",
        type=int,
        default=1,
        help="Stage4T 路由表并发数；默认 1，建议结合全局 LLM 限流显式设置",
    )
    args = parser.parse_args()

    output_path, cached = run_sidecar(
        input_root=args.input_root,
        output_root=args.output_root,
        ref_no=args.ref_no,
        force=args.force,
        enable_llm_interpretation=args.stage4t_llm_interpretation,
        table_workers=args.stage4t_table_workers,
        config_path=args.config,
        retry_failed_tables=args.retry_failed_tables,
    )
    print(f"[{'cached' if cached else 'written'}] {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
