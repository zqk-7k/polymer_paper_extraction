"""Audit Stage 4T Shadow output against a manually reviewed table fixture."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping


AUDIT_VERSION = "0.1.0"


def _cell_id(table_id: str, row: int, column: int) -> str:
    return f"{table_id}:r{row:04d}:c{column:04d}"


def expand_expected_observations(case: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Expand the compact row/column fixture into stable cell-level answers."""
    table_id = str(case["table_id"])
    case_samples_by_row = case.get("sample_labels_by_row") or {}
    samples_by_column = case.get("sample_labels_by_column") or {}
    excluded = set(case.get("sample_evaluation_excluded_cells") or [])
    expected: dict[str, dict[str, Any]] = {}

    for column in case.get("expected_columns", []):
        column_index = int(column["column_index"])
        samples_by_row = column.get("sample_labels_by_row") or case_samples_by_row
        for row in column.get("rows", []):
            cell_id = _cell_id(table_id, int(row), column_index)
            expected[cell_id] = {
                "cell_id": cell_id,
                "expected_property_name": column.get("expected_property_name"),
                "expected_semantic_label": column.get("expected_semantic_label"),
                "expected_property_variant": column.get("expected_property_variant"),
                "expected_conditions": column.get("expected_conditions") or {},
                "expected_sample_label": samples_by_row.get(str(row)),
                "sample_evaluable": cell_id not in excluded,
            }

    for row in case.get("expected_rows", []):
        row_index = int(row["row_index"])
        for column in row.get("columns", []):
            cell_id = _cell_id(table_id, row_index, int(column))
            expected[cell_id] = {
                "cell_id": cell_id,
                "expected_property_name": row.get("expected_property_name"),
                "expected_semantic_label": row.get("expected_semantic_label"),
                "expected_property_variant": row.get("expected_property_variant"),
                "expected_conditions": row.get("expected_conditions") or {},
                "expected_sample_label": samples_by_column.get(str(column)),
                "sample_evaluable": cell_id not in excluded,
            }
    return expected


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def audit_shadow_report(
    fixture: Mapping[str, Any],
    shadow_report: Mapping[str, Any],
) -> dict[str, Any]:
    """Calculate direction, cell, property and sample metrics for Shadow output."""
    table_index = {
        (str(document.get("document_id")), str(table.get("table_id"))): table
        for document in shadow_report.get("documents", [])
        for table in document.get("tables", [])
    }
    failures: list[dict[str, str]] = []
    cases: list[dict[str, Any]] = []
    totals: Counter[str] = Counter()

    for case in fixture.get("cases", []):
        doc_id = str(case.get("doc_id"))
        table_id = str(case.get("table_id"))
        table = table_index.get((doc_id, table_id))
        if table is None:
            failures.append({"doc_id": doc_id, "table_id": table_id, "error": "table_not_found"})
            continue

        expected = expand_expected_observations(case)
        expected_columns = {
            int(cell_id.rsplit(":c", 1)[1]) for cell_id in expected
        }
        audit_columns = {
            int(column) for column in case.get("audit_columns", expected_columns)
        }
        by_cell: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for item in table.get("observations", []):
            cell_id = str(item.get("cell_id"))
            column_index = item.get("column_index")
            if column_index is None and ":c" in cell_id:
                column_index = int(cell_id.rsplit(":c", 1)[1])
            if int(column_index if column_index is not None else -1) in audit_columns:
                by_cell[cell_id].append(item)

        expected_cells = set(expected)
        actual_cells = set(by_cell)
        matched_cells = expected_cells & actual_cells
        missing_cells = expected_cells - actual_cells
        unexpected_cells = actual_cells - expected_cells
        actual_count = sum(len(items) for items in by_cell.values())
        duplicate_extra = sum(max(0, len(items) - 1) for items in by_cell.values())

        property_evaluated = 0
        property_correct = 0
        sample_evaluated = 0
        sample_correct = 0
        for cell_id in matched_cells:
            answer = expected[cell_id]
            for actual in by_cell[cell_id]:
                property_evaluated += 1
                property_correct += (
                    actual.get("property_name_normalized") == answer["expected_property_name"]
                    and actual.get("semantic_label") == answer["expected_semantic_label"]
                    and actual.get("property_variant") == answer["expected_property_variant"]
                    and (actual.get("conditions") or {}) == answer["expected_conditions"]
                )
                if answer["sample_evaluable"]:
                    sample_evaluated += 1
                    sample_correct += actual.get("sample_label_raw") == answer["expected_sample_label"]

        eligible = bool(case.get("eligible"))
        direction_correct = table.get("direction") == case.get("expected_direction")
        status = (
            "not_eligible" if not eligible
            else "zero_output" if not actual_count
            else "complete" if not missing_cells
            else "partial"
        )
        item = {
            "doc_id": doc_id,
            "table_id": table_id,
            "table_role": case.get("table_role"),
            "eligible": eligible,
            "status": status,
            "expected_direction": case.get("expected_direction"),
            "actual_direction": table.get("direction"),
            "direction_correct": direction_correct,
            "expected_cell_count": len(expected_cells),
            "actual_output_count": actual_count,
            "matched_cell_count": len(matched_cells),
            "missing_cell_count": len(missing_cells),
            "unexpected_cell_count": len(unexpected_cells),
            "duplicate_extra_count": duplicate_extra,
            "property_mapping_evaluated_count": property_evaluated,
            "property_mapping_correct_count": property_correct,
            "sample_binding_evaluated_count": sample_evaluated,
            "sample_binding_correct_count": sample_correct,
            "missing_cells": sorted(missing_cells),
            "unexpected_cells": sorted(unexpected_cells),
        }
        cases.append(item)

        totals["table_count"] += 1
        totals["direction_evaluated_count"] += 1
        totals["direction_correct_count"] += direction_correct
        if eligible:
            totals["duplicate_extra_count"] += duplicate_extra
            totals["actual_output_count"] += actual_count
            totals["eligible_table_count"] += 1
            totals["expected_cell_count"] += len(expected_cells)
            totals["matched_cell_count"] += len(matched_cells)
            totals["missing_cell_count"] += len(missing_cells)
            totals["unexpected_cell_count"] += len(unexpected_cells)
            totals["property_mapping_evaluated_count"] += property_evaluated
            totals["property_mapping_correct_count"] += property_correct
            totals["sample_binding_evaluated_count"] += sample_evaluated
            totals["sample_binding_correct_count"] += sample_correct
            totals[f"eligible_{status}_table_count"] += 1

    summary = dict(totals)
    summary.update({
        "direction_accuracy": _ratio(totals["direction_correct_count"], totals["direction_evaluated_count"]),
        "numeric_cell_recall": _ratio(totals["matched_cell_count"], totals["expected_cell_count"]),
        "output_precision": _ratio(totals["matched_cell_count"], totals["actual_output_count"]),
        "property_mapping_accuracy": _ratio(totals["property_mapping_correct_count"], totals["property_mapping_evaluated_count"]),
        "sample_binding_accuracy": _ratio(totals["sample_binding_correct_count"], totals["sample_binding_evaluated_count"]),
        "duplicate_output_rate": _ratio(totals["duplicate_extra_count"], totals["actual_output_count"]),
    })
    return {
        "audit_schema_version": "stage4t_shadow_binding_audit.v0.1",
        "audit_version": AUDIT_VERSION,
        "fixture_schema_version": fixture.get("schema_version"),
        "shadow_version": shadow_report.get("shadow_version"),
        "failure_count": len(failures),
        "failures": failures,
        "summary": summary,
        "cases": cases,
    }


def audit_shadow_files(fixture_path: Path, shadow_report_path: Path) -> dict[str, Any]:
    fixture = load_fixture(fixture_path)
    shadow_report = json.loads(shadow_report_path.read_text(encoding="utf-8"))
    return audit_shadow_report(fixture, shadow_report)


def load_fixture(fixture_path: Path) -> dict[str, Any]:
    """Load a fixture and merge an optional relative base fixture by table key."""
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    base_name = fixture.get("base_fixture")
    if not base_name:
        return fixture
    base = load_fixture(fixture_path.parent / str(base_name))
    merged = {
        (str(case.get("doc_id")), str(case.get("table_id"))): case
        for case in base.get("cases", [])
    }
    for case in fixture.get("cases", []):
        merged[(str(case.get("doc_id")), str(case.get("table_id")))] = case
    return {
        **fixture,
        "base_fixture_schema_version": base.get("schema_version"),
        "cases": list(merged.values()),
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Stage 4T Shadow 人工 fixture 审计",
        "",
        f"- Fixture：`{report.get('fixture_schema_version')}`",
        f"- Shadow：`{report.get('shadow_version')}`",
        f"- 数值格召回率：{summary.get('matched_cell_count', 0)}/{summary.get('expected_cell_count', 0)} = {summary.get('numeric_cell_recall')}",
        f"- 输出精确率：{summary.get('output_precision')}",
        f"- 性质映射准确率：{summary.get('property_mapping_accuracy')}",
        f"- 样品绑定准确率：{summary.get('sample_binding_accuracy')}",
        f"- 重复输出率：{summary.get('duplicate_output_rate')}",
        "",
        "| 文献 | 表格 | 角色 | 状态 | 方向 | 预期格 | 命中格 | 缺失格 | 非预期格 |",
        "|---|---|---|---|---|---:|---:|---:|---:|",
    ]
    for case in report.get("cases", []):
        lines.append(
            "| {doc} | {table} | {role} | {status} | {actual}/{expected} | {cells} | {matched} | {missing} | {unexpected} |".format(
                doc=case.get("doc_id"), table=case.get("table_id"), role=case.get("table_role"),
                status=case.get("status"), actual=case.get("actual_direction"), expected=case.get("expected_direction"),
                cells=case.get("expected_cell_count"), matched=case.get("matched_cell_count"),
                missing=case.get("missing_cell_count"), unexpected=case.get("unexpected_cell_count"),
            )
        )
    return "\n".join(lines) + "\n"
