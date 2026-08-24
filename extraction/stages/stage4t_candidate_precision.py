"""Stage 4T 宽松候选逐格 fixture 的生成与只读审计。"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping


FIXTURE_SCHEMA_VERSION = "stage4t_candidate_precision_fixture.v0.1"
REVIEW_FIXTURE_SCHEMA_VERSION = "stage4t_candidate_precision_fixture.v0.2"
EXTENDED_FIXTURE_SCHEMA_VERSION = "stage4t_candidate_precision_fixture.v0.3"
AUDIT_SCHEMA_VERSION = "stage4t_candidate_precision_audit.v0.1"

SOLUBILITY_TABLE_REFS = (
    ("reference_no_0020284", "T_5_74"),
    ("reference_no_0038813", "T_7_98"),
)

KNOWN_GAP_CELLS = (
    {
        "cell_id": "T_4_49:r0002:c0002",
        "row_index": 2,
        "column_index": 2,
        "value_raw": "$13^{°b)}$",
        "property_name_normalized": "contact_angle",
        "semantic_label": None,
        "property_variant": None,
        "sample_label_raw": "poly(MPC)",
        "conditions": {"probe_phase": "$Water^{a)}$", "contact_angle_mode": "(advancing)"},
        "unit_normalized": "deg",
        "measurement_role": "reported_unknown",
        "candidate_class": "official_property",
    },
    {
        "cell_id": "T_4_49:r0003:c0002",
        "row_index": 3,
        "column_index": 2,
        "value_raw": "$<5^{°b)}$",
        "property_name_normalized": "contact_angle",
        "semantic_label": None,
        "property_variant": None,
        "sample_label_raw": "poly(MPC)",
        "conditions": {"probe_phase": "$Water^{a)}$", "contact_angle_mode": "(receding)"},
        "unit_normalized": "deg",
        "measurement_role": "reported_unknown",
        "candidate_class": "official_property",
    },
    {
        "cell_id": "T_4_49:r0004:c0002",
        "row_index": 4,
        "column_index": 2,
        "value_raw": "$15^{°b)}$",
        "property_name_normalized": "contact_angle",
        "semantic_label": None,
        "property_variant": None,
        "sample_label_raw": "poly(MPC)",
        "conditions": {"probe_phase": "$Water^{a)}$", "contact_angle_mode": "(sliding)"},
        "unit_normalized": "deg",
        "measurement_role": "reported_unknown",
        "candidate_class": "official_property",
    },
)

_CHECK_FIELDS = (
    "value_raw",
    "property_name_normalized",
    "semantic_label",
    "property_variant",
    "sample_label_raw",
    "conditions",
    "unit_normalized",
    "measurement_role",
    "candidate_class",
    "candidate_role",
    "candidate_state",
    "evidence_locator",
    "warnings",
)


def _candidate_record(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "cell_id": item.get("cell_id"),
        "row_index": item.get("row_index"),
        "column_index": item.get("column_index"),
        **{field: item.get(field) for field in _CHECK_FIELDS},
    }


def build_fixture_from_sidecars(
    sidecar_root: Path,
    refs: list[str],
) -> dict[str, Any]:
    """从已应用 sidecar 生成待人工确认的逐格 fixture 种子。"""
    cases: list[dict[str, Any]] = []
    for ref_no in refs:
        sidecar_path = sidecar_root / ref_no / "stage4t_shadow.json"
        report = json.loads(sidecar_path.read_text(encoding="utf-8"))
        tables = [
            table
            for table in report.get("tables", [])
            if table.get("interpretation_application", {})
            .get("status", "")
            .startswith("applied")
        ]
        if len(tables) != 1:
            raise ValueError(
                f"{ref_no}: expected exactly one applied table, got {len(tables)}"
            )
        table = tables[0]
        observations = list(table.get("observations") or [])
        cases.append({
            "doc_id": ref_no,
            "table_id": table.get("table_id"),
            "table_role": table.get("axis_role"),
            "review_status": "pending_human_review",
            "source_sidecar_schema_version": report.get("sidecar_schema_version"),
            "source_application_version": report.get(
                "interpretation_application_version"
            ),
            "expected_observation_count": len(observations),
            "observations": [_candidate_record(item) for item in observations],
        })
    return {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "created_at": "2026-08-22",
        "purpose": "5 张复杂表新增 Stage 4T 候选的逐格人工复核底稿",
        "review_status": "provisional_seed",
        "accuracy_claim": "禁止将自动种子或本审计结果直接解释为准确率",
        "required_review_fields": list(_CHECK_FIELDS),
        "cases": cases,
    }


def build_expected_cell_fixture_from_sidecars(
    sidecar_root: Path,
    refs: list[str],
) -> dict[str, Any]:
    """在 v0.1 候选种子上加入已知漏格，形成逐格召回底稿。"""
    fixture = build_fixture_from_sidecars(sidecar_root, refs)
    fixture["schema_version"] = REVIEW_FIXTURE_SCHEMA_VERSION
    fixture["purpose"] = "5 张复杂表 Stage 4T 候选的逐格召回与人工精度复核底稿"
    for case in fixture["cases"]:
        expected_cells = list(case["observations"])
        if case["table_id"] == "T_4_49":
            existing_ids = {str(item.get("cell_id") or "") for item in expected_cells}
            expected_cells.extend(
                dict(item)
                for item in KNOWN_GAP_CELLS
                if item["cell_id"] not in existing_ids
            )
        case["expected_cells"] = expected_cells
        case["expected_cell_count"] = len(expected_cells)
    return fixture


def build_extended_fixture_from_sidecars(
    sidecar_root: Path,
    refs: list[str],
) -> dict[str, Any]:
    """在 v0.2 数值候选底稿上加入已实现的定性溶解性表。"""
    fixture = build_expected_cell_fixture_from_sidecars(sidecar_root, refs)
    for ref_no, table_id in SOLUBILITY_TABLE_REFS:
        sidecar_path = sidecar_root / ref_no / "stage4t_shadow.json"
        report = json.loads(sidecar_path.read_text(encoding="utf-8"))
        table = next(
            (item for item in report.get("tables", []) if item.get("table_id") == table_id),
            None,
        )
        if table is None:
            raise ValueError(f"{ref_no}/{table_id}: table not found")
        observations = list(table.get("observations") or [])
        fixture["cases"].append({
            "doc_id": ref_no,
            "table_id": table_id,
            "table_role": table.get("axis_role"),
            "review_status": "pending_human_review",
            "source_sidecar_schema_version": report.get("sidecar_schema_version"),
            "source_application_version": report.get(
                "interpretation_application_version"
            ),
            "expected_observation_count": len(observations),
            "observations": [_candidate_record(item) for item in observations],
            "expected_cells": [_candidate_record(item) for item in observations],
            "expected_cell_count": len(observations),
        })
    fixture["schema_version"] = EXTENDED_FIXTURE_SCHEMA_VERSION
    fixture["purpose"] = "5 张复杂数值表与 2 张定性溶解性表的 Stage 4T 逐格人工复核底稿"
    return fixture


def _index_observations(
    observations: list[Mapping[str, Any]],
) -> tuple[dict[str, Mapping[str, Any]], list[str]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    duplicates: list[str] = []
    for item in observations:
        cell_id = str(item.get("cell_id") or "")
        if not cell_id:
            continue
        if cell_id in indexed:
            duplicates.append(cell_id)
        else:
            indexed[cell_id] = item
    return indexed, duplicates


def audit_candidate_fixture(
    fixture: Mapping[str, Any],
    sidecar_root: Path,
) -> dict[str, Any]:
    """比较 fixture 与 sidecar，不改变候选或发布状态。"""
    failures: list[dict[str, Any]] = []
    cases: list[dict[str, Any]] = []
    totals = Counter(
        expected=0,
        actual=0,
        matched=0,
        missing=0,
        extra=0,
        duplicate=0,
        value_mismatch=0,
        semantic_mismatch=0,
        sample_mismatch=0,
        condition_mismatch=0,
        unit_mismatch=0,
        role_mismatch=0,
    )
    for case in fixture.get("cases") or []:
        doc_id = str(case.get("doc_id"))
        table_id = str(case.get("table_id"))
        sidecar_path = sidecar_root / doc_id / "stage4t_shadow.json"
        result: dict[str, Any] = {
            "doc_id": doc_id,
            "table_id": table_id,
            "review_status": case.get("review_status"),
        }
        if not sidecar_path.is_file():
            result["status"] = "missing_sidecar"
            failures.append({"doc_id": doc_id, "table_id": table_id, "error": "missing_sidecar"})
            cases.append(result)
            continue
        try:
            report = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            result["status"] = "invalid_sidecar"
            failures.append({
                "doc_id": doc_id,
                "table_id": table_id,
                "error": f"{type(exc).__name__}: {exc}",
            })
            cases.append(result)
            continue
        table = next(
            (item for item in report.get("tables", []) if item.get("table_id") == table_id),
            None,
        )
        if table is None:
            result["status"] = "missing_table"
            failures.append({"doc_id": doc_id, "table_id": table_id, "error": "missing_table"})
            cases.append(result)
            continue
        expected = list(case.get("expected_cells") or case.get("observations") or [])
        actual = list(table.get("observations") or [])
        expected_by_cell, expected_duplicates = _index_observations(expected)
        actual_by_cell, actual_duplicates = _index_observations(actual)
        missing = sorted(set(expected_by_cell) - set(actual_by_cell))
        extra = sorted(set(actual_by_cell) - set(expected_by_cell))
        mismatches: list[dict[str, Any]] = []
        for cell_id in sorted(set(expected_by_cell) & set(actual_by_cell)):
            expected_item = expected_by_cell[cell_id]
            actual_item = actual_by_cell[cell_id]
            mismatch_fields = [
                field
                for field in _CHECK_FIELDS
                if expected_item.get(field) != actual_item.get(field)
            ]
            if mismatch_fields:
                mismatches.append({"cell_id": cell_id, "fields": mismatch_fields})
                for field in mismatch_fields:
                    totals_key = {
                        "value_raw": "value_mismatch",
                        "property_name_normalized": "semantic_mismatch",
                        "semantic_label": "semantic_mismatch",
                        "property_variant": "semantic_mismatch",
                        "sample_label_raw": "sample_mismatch",
                        "conditions": "condition_mismatch",
                        "unit_normalized": "unit_mismatch",
                        "measurement_role": "role_mismatch",
                        "candidate_class": "semantic_mismatch",
                    }[field]
                    totals[totals_key] += 1
        totals.update({
            "expected": len(expected_by_cell),
            "actual": len(actual_by_cell),
            "matched": len(set(expected_by_cell) & set(actual_by_cell)) - len(mismatches),
            "missing": len(missing),
            "extra": len(extra),
            "duplicate": len(expected_duplicates) + len(actual_duplicates),
        })
        result.update({
            "status": "audited",
            "expected_count": len(expected),
            "actual_count": len(actual),
            "missing_cell_ids": missing,
            "extra_cell_ids": extra,
            "duplicate_cell_ids": sorted(set(expected_duplicates + actual_duplicates)),
            "mismatches": mismatches,
            "publication_statuses": dict(Counter(
                (item.get("publication_gate") or {}).get("status")
                for item in actual
            )),
        })
        cases.append(result)
    totals["cell_recall"] = (
        totals["matched"] / totals["expected"] if totals["expected"] else 0.0
    )
    return {
        "audit_schema_version": AUDIT_SCHEMA_VERSION,
        "fixture_schema_version": fixture.get("schema_version"),
        "fixture_review_status": fixture.get("review_status"),
        "accuracy_claim": fixture.get("accuracy_claim"),
        "failure_count": len(failures),
        "failures": failures,
        "summary": dict(totals),
        "cases": cases,
    }


def render_audit_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Stage 4T 候选逐格精度 Fixture 审计",
        "",
        f"- Fixture：{report.get('fixture_schema_version')}",
        f"- Fixture 状态：{report.get('fixture_review_status')}",
        f"- 准确率声明：{report.get('accuracy_claim')}",
        f"- 失败：{report.get('failure_count', 0)}",
        "",
        "## 汇总",
        "",
        f"- 预期候选：{summary.get('expected', 0)}",
        f"- 实际候选：{summary.get('actual', 0)}",
        f"- cell 命中：{summary.get('matched', 0)}",
        f"- 数值格召回率（结构底线）：{summary.get('matched', 0)}/{summary.get('expected', 0)} = {summary.get('cell_recall', 0.0):.2%}",
        f"- 缺格/多格/重复：{summary.get('missing', 0)} / {summary.get('extra', 0)} / {summary.get('duplicate', 0)}",
        f"- 值不一致：{summary.get('value_mismatch', 0)}",
        f"- 语义不一致：{summary.get('semantic_mismatch', 0)}",
        f"- 样品/条件/单位/角色不一致：{summary.get('sample_mismatch', 0)} / {summary.get('condition_mismatch', 0)} / {summary.get('unit_mismatch', 0)} / {summary.get('role_mismatch', 0)}",
        "",
        "| 文献 | 表格 | 状态 | 预期 | 实际 | 缺格 | 多格 | 不一致 |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for case in report.get("cases") or []:
        lines.append(
            "| {doc} | {table} | {status} | {expected} | {actual} | {missing} | {extra} | {mismatch} |".format(
                doc=case.get("doc_id"),
                table=case.get("table_id"),
                status=case.get("status"),
                expected=case.get("expected_count", 0),
                actual=case.get("actual_count", 0),
                missing=len(case.get("missing_cell_ids") or []),
                extra=len(case.get("extra_cell_ids") or []),
                mismatch=len(case.get("mismatches") or []),
            )
        )
    return "\n".join(lines) + "\n"
