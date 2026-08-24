"""Stage 4T LLM 结构解释与人工 fixture 的离线审计。"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from stages.stage4t_llm_interpreter import INTERPRETER_VERSION


TOP_LEVEL_FIELDS = (
    "direction",
    "axis_role",
    "sample_binding_strategy",
)


def _canonical_name(assignment: Mapping[str, Any]) -> str | None:
    if assignment.get("role") == "material_characteristic":
        return assignment.get("semantic_label")
    return assignment.get("normalized_name")


def _assignment_triples(
    interpretation: Mapping[str, Any],
) -> set[tuple[str, str, str | None]]:
    return {
        (str(cell_id), str(assignment.get("role")), _canonical_name(assignment))
        for assignment in interpretation.get("header_assignments") or []
        for cell_id in assignment.get("source_cell_ids") or []
    }


def _triple_payload(
    triple: tuple[str, str, str | None],
) -> dict[str, Any]:
    return {
        "cell_id": triple[0],
        "role": triple[1],
        "canonical_name": triple[2],
    }


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(0)


def audit_interpretations(
    *,
    batch_root: Path,
    fixture_path: Path,
) -> dict[str, Any]:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = []
    total_tokens = 0
    total_cost = Decimal(0)
    expected_count = 0
    matched_count = 0
    extra_count = 0

    for fixture_case in fixture.get("cases") or []:
        doc_id = str(fixture_case["doc_id"])
        table_id = str(fixture_case["table_id"])
        sidecar_path = batch_root / doc_id / "stage4t_shadow.json"
        report = json.loads(sidecar_path.read_text(encoding="utf-8"))
        interpretation_record = next(
            (
                item for item in report.get("interpretations") or []
                if item.get("table_id") == table_id
            ),
            None,
        )
        expected = fixture_case["interpretation"]
        actual = (
            interpretation_record.get("interpretation")
            if isinstance(interpretation_record, dict)
            else None
        ) or {}
        top_mismatches = {
            field: {
                "expected": expected.get(field),
                "actual": actual.get(field),
            }
            for field in TOP_LEVEL_FIELDS
            if expected.get(field) != actual.get(field)
        }
        expected_triples = _assignment_triples(expected)
        actual_triples = _assignment_triples(actual)
        missing = sorted(expected_triples - actual_triples)
        extra = sorted(actual_triples - expected_triples)
        matched = expected_triples & actual_triples
        status = (
            interpretation_record.get("status")
            if isinstance(interpretation_record, dict)
            else "missing"
        )
        version = report.get("llm_interpreter_version")
        passed = (
            status == "succeeded"
            and version == INTERPRETER_VERSION
            and not top_mismatches
            and not missing
        )
        provenance = report.get("provenance") or {}
        usage = provenance.get("usage") or {}
        cost = provenance.get("cost") or {}
        case_tokens = int(usage.get("total_tokens") or 0)
        case_cost = _decimal(cost.get("total_cost"))
        total_tokens += case_tokens
        total_cost += case_cost
        expected_count += len(expected_triples)
        matched_count += len(matched)
        extra_count += len(extra)
        cases.append({
            "doc_id": doc_id,
            "table_id": table_id,
            "passed": passed,
            "status": status,
            "interpreter_version": version,
            "top_level_mismatches": top_mismatches,
            "expected_assignment_count": len(expected_triples),
            "matched_assignment_count": len(matched),
            "missing_expected_assignments": [
                _triple_payload(item) for item in missing
            ],
            "extra_assignments": [_triple_payload(item) for item in extra],
            "total_tokens": case_tokens,
            "total_cost": str(case_cost),
            "currency": cost.get("currency"),
        })

    passed_count = sum(case["passed"] for case in cases)
    return {
        "audit_schema_version": "stage4t_interpretation_audit.v0.1",
        "fixture_schema_version": fixture.get("schema_version"),
        "interpreter_version": INTERPRETER_VERSION,
        "batch_root": str(batch_root),
        "summary": {
            "case_count": len(cases),
            "passed_count": passed_count,
            "failed_count": len(cases) - passed_count,
            "expected_assignment_count": expected_count,
            "matched_assignment_count": matched_count,
            "missing_expected_assignment_count": (
                expected_count - matched_count
            ),
            "extra_assignment_count": extra_count,
            "total_tokens": total_tokens,
            "total_cost": str(total_cost),
            "currency": next(
                (case["currency"] for case in cases if case["currency"]),
                None,
            ),
        },
        "cases": cases,
    }


def render_audit_markdown(report: Mapping[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Stage 4T LLM 表结构解释审计",
        "",
        f"- 解释器版本：`{report['interpreter_version']}`",
        f"- 通过：{summary['passed_count']}/{summary['case_count']}",
        f"- 人工必需 assignment：{summary['matched_assignment_count']}/"
        f"{summary['expected_assignment_count']}",
        f"- 缺失：{summary['missing_expected_assignment_count']}",
        f"- 额外解释：{summary['extra_assignment_count']}",
        f"- 最新同版本运行：{summary['total_tokens']} token，"
        f"{summary['total_cost']} {summary['currency'] or ''}".rstrip(),
        "",
        "| 文献 | 表格 | 状态 | 必需 assignment | 缺失 | 额外 | token | 费用 |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for case in report["cases"]:
        lines.append(
            f"| {case['doc_id']} | {case['table_id']} | "
            f"{'通过' if case['passed'] else '失败'} | "
            f"{case['matched_assignment_count']}/"
            f"{case['expected_assignment_count']} | "
            f"{len(case['missing_expected_assignments'])} | "
            f"{len(case['extra_assignments'])} | "
            f"{case['total_tokens']} | {case['total_cost']} |"
        )
    lines.extend([
        "",
        "> 额外解释允许保留，但不计入人工必需 assignment 的命中；"
        "权威发布资格仍由独立 publication gate 决定。",
        "",
    ])
    return "\n".join(lines)
