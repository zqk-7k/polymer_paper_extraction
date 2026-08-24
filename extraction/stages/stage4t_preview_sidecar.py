"""在 Preview 中生成非权威、可独立丢弃的 Stage 4T Shadow sidecar。"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

EXTRACTION_ROOT = Path(__file__).resolve().parents[1]
if str(EXTRACTION_ROOT) not in sys.path:
    sys.path.insert(0, str(EXTRACTION_ROOT))

from llm_client import DEFAULT_CONFIG_PATH
from schema.polymer_schema import Stage0Document
from stages.stage4t_table_property import SHADOW_VERSION, shadow_extract_document
from stages.stage4t_llm_interpreter import (
    INTERPRETER_VERSION,
    approved_interpretation_tables,
    disabled_interpretation,
    interpret_table_with_llm,
)
from stages.stage4t_table_interpretation import interpretation_route_reasons
from stages.stage4t_interpretation_apply import (
    APPLICATION_VERSION,
    apply_table_interpretation,
)
from stages.stage4t_table_survey import survey_table


SIDECAR_SCHEMA_VERSION = "stage4t_preview_sidecar.v0.4"
OUTPUT_NAME = "stage4t_shadow.json"


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
    return {
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
    source_sha256: str,
    config_sha256: str | None,
) -> dict[str, Any] | None:
    provenance = cached.get("provenance") or {}
    if (
        not cached.get("llm_interpretation_enabled")
        or cached.get("llm_interpreter_version") != INTERPRETER_VERSION
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


def run_sidecar(
    *,
    input_root: Path,
    output_root: Path,
    ref_no: str,
    force: bool = False,
    enable_llm_interpretation: bool = False,
    config_path: Path | None = None,
) -> tuple[Path, bool]:
    source_path = input_root / ref_no / "stage0_blocks.json"
    output_path = output_root / ref_no / OUTPUT_NAME
    source_sha256 = _sha256_file(source_path)
    resolved_config_path = config_path or DEFAULT_CONFIG_PATH
    config_sha256 = (
        _sha256_file(resolved_config_path)
        if enable_llm_interpretation and resolved_config_path.is_file()
        else None
    )

    cached_report: dict[str, Any] = {}
    if output_path.is_file() and not force:
        try:
            cached_report = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached_report = {}
        provenance = cached_report.get("provenance") or {}
        if (
            cached_report.get("sidecar_schema_version") == SIDECAR_SCHEMA_VERSION
            and cached_report.get("shadow_version") == SHADOW_VERSION
            and cached_report.get("llm_interpretation_enabled")
            == enable_llm_interpretation
            and cached_report.get("llm_interpreter_version")
            == INTERPRETER_VERSION
            and cached_report.get("interpretation_application_version")
            == APPLICATION_VERSION
            and provenance.get("stage0_sha256") == source_sha256
            and provenance.get("config_sha256") == config_sha256
        ):
            return output_path, True

    payload = json.loads(source_path.read_text(encoding="utf-8"))
    stage0_document = Stage0Document.model_validate(payload)
    document = shadow_extract_document(stage0_document)
    interpretations: list[dict[str, Any]] = []
    approved_tables = (
        approved_interpretation_tables(resolved_config_path)
        if enable_llm_interpretation
        else set()
    )
    stage0_tables = {
        element.block_id: element
        for element in stage0_document.elements
        if element.type == "table"
    }
    for table_report in document["tables"]:
        table = stage0_tables.get(table_report.get("table_id"))
        survey = survey_table(table) if table is not None else {}
        reasons = interpretation_route_reasons(
            survey,
            table_report,
            eligible=True,
        )
        if not reasons:
            continue
        approved = (ref_no, str(table_report.get("table_id"))) in approved_tables
        if not enable_llm_interpretation or table is None or not approved:
            result = disabled_interpretation(
                "feature_disabled" if not enable_llm_interpretation
                else (
                    "stage0_table_not_found" if table is None
                    else "not_in_approved_fixture"
                )
            )
        else:
            reused = _reusable_interpretation(
                cached_report,
                table_id=str(table_report.get("table_id")),
                source_sha256=source_sha256,
                config_sha256=config_sha256,
            )
            result = reused or interpret_table_with_llm(
                table,
                survey=survey,
                shadow=table_report,
                config_path=resolved_config_path,
            )
        interpretation_record = {
            "table_id": table_report.get("table_id"),
            "route_reasons": reasons,
            **result,
        }
        if (
            table is not None
            and result.get("status") == "succeeded"
            and isinstance(result.get("interpretation"), Mapping)
        ):
            rule_observations = copy.deepcopy(
                list(table_report.get("observations") or [])
            )
            try:
                applied_table, application = apply_table_interpretation(
                    table,
                    table_report,
                    result["interpretation"],
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
                table_report["interpretation_application"] = application
            interpretation_record["application"] = application
        interpretations.append(interpretation_record)
    billing = _llm_billing(
        interpretations,
        enabled=enable_llm_interpretation,
    )
    report = {
        "sidecar_schema_version": SIDECAR_SCHEMA_VERSION,
        "shadow_version": SHADOW_VERSION,
        "authoritative": False,
        "candidate_layer": "broad",
        "llm_interpretation_enabled": enable_llm_interpretation,
        "llm_interpreter_version": INTERPRETER_VERSION,
        "interpretation_application_version": APPLICATION_VERSION,
        "document_id": document["document_id"],
        "table_count": document["table_count"],
        "summary": _summary(document),
        "tables": document["tables"],
        "interpretations": interpretations,
        "provenance": {
            "source": "stage0_blocks.json",
            "stage0_sha256": source_sha256,
            "config_sha256": config_sha256,
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
    parser.add_argument(
        "--stage4t-llm-interpretation",
        action="store_true",
        help="显式启用 Stage 4T 复杂表 LLM 结构解释；失败仍回落 candidate_only",
    )
    args = parser.parse_args()

    output_path, cached = run_sidecar(
        input_root=args.input_root,
        output_root=args.output_root,
        ref_no=args.ref_no,
        force=args.force,
        enable_llm_interpretation=args.stage4t_llm_interpretation,
        config_path=args.config,
    )
    print(f"[{'cached' if cached else 'written'}] {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
