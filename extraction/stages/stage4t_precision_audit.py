"""Stage 4T 表格性质映射精度审计。

本模块只比较标准化映射记录与 fixture 中冻结的互斥关系，不参与在线抽取。
Char yield 等具体性质只应通过 fixture 声明，算法本身不包含专项判断。
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from stages.stage4t_shadow_binding_audit import (
    expand_expected_observations,
    load_fixture,
)


AUDIT_VERSION = "0.2.0"


def _kind_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    return {str(item) for item in value}


def snapshot_to_mappings(
    snapshot: Mapping[str, Any], *, table_id: str | None = None
) -> list[dict[str, Any]]:
    """将 Stage 4 properties 快照转换为冲突审计所需的标准记录。"""
    mappings: list[dict[str, Any]] = []
    for property_item in snapshot.get("properties", []):
        locators = property_item.get("evidence") or []
        for evidence in locators:
            locator = evidence.get("table_locator") or {}
            if not locator or (table_id is not None and locator.get("table_id") != table_id):
                continue
            mappings.append(
                {
                    "mapping_id": property_item.get("property_id")
                    or f"{locator.get('cell_id')}:{len(mappings)}",
                    "table_id": locator.get("table_id"),
                    "cell_id": locator.get("cell_id"),
                    "row_index": locator.get("row_index"),
                    "column_index": locator.get("column_index"),
                    "sample_id": property_item.get("sample_id"),
                    "kind": property_item.get("property_name_raw")
                    or property_item.get("property_name_normalized"),
                }
            )
    return mappings


def shadow_report_to_mappings(
    shadow_report: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """将批次 Stage 4T Shadow 报告转换为冲突审计标准记录。"""
    mappings: list[dict[str, Any]] = []
    for document in shadow_report.get("documents", []):
        document_id = str(document.get("document_id"))
        for table in document.get("tables", []):
            table_id = table.get("table_id")
            for observation in table.get("observations", []):
                kind = observation.get("semantic_label") or observation.get(
                    "property_name_normalized"
                )
                if not kind:
                    continue
                mappings.append({
                    "mapping_id": (
                        f"{document_id}:{observation.get('cell_id')}:{len(mappings)}"
                    ),
                    "document_id": document_id,
                    "table_id": table_id,
                    "cell_id": observation.get("cell_id"),
                    "row_index": observation.get("row_index"),
                    "column_index": observation.get("column_index"),
                    "sample_id": observation.get("sample_id"),
                    "kind": kind,
                    "direction": table.get("direction"),
                })
    return mappings


def _cell_key(item: Mapping[str, Any]) -> tuple[Any, Any]:
    return item.get("document_id"), item.get("cell_id")


def _column_key(item: Mapping[str, Any]) -> tuple[Any, Any, Any]:
    return (
        item.get("document_id"),
        item.get("table_id"),
        item.get("column_index"),
    )


def audit_mutually_exclusive_mapping_conflicts(
    mappings: Iterable[Mapping[str, Any]],
    forbidden_pairs: Sequence[Mapping[str, Any]],
    *,
    expected_columns: Sequence[Mapping[str, Any]] = (),
    expected_cells: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """按 cell/column/observation 三层统计互斥性质映射冲突。

    ``expected_columns`` 用 fixture 的列答案标注每个数值格的期望 kind；
    若未提供，则仍可检出同一 cell/column 内同时出现互斥 kind 的冲突。
    """
    records = []
    for index, item in enumerate(mappings):
        if not item.get("kind"):
            continue
        record = dict(item)
        record.setdefault("mapping_id", f"mapping-{index}")
        records.append(record)
    expected_by_column = {
        (
            item.get("document_id"),
            item.get("table_id"),
            item.get("index"),
        ): item.get("expected_kind")
        for item in expected_columns
        if item.get("expected_kind")
    }
    expected_by_cell = {
        (item.get("document_id"), item.get("cell_id")): item.get("expected_kind")
        for item in expected_cells
        if item.get("cell_id") and item.get("expected_kind")
    }
    by_cell: dict[tuple[Any, Any], list[dict[str, Any]]] = defaultdict(list)
    by_column: dict[tuple[Any, Any, Any], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        cell_id = record.get("cell_id")
        if cell_id:
            by_cell[_cell_key(record)].append(record)
        if record.get("direction") != "column_samples":
            by_column[_column_key(record)].append(record)

    def expected_kind(record: Mapping[str, Any]) -> Any:
        return expected_by_cell.get(
            _cell_key(record),
            expected_by_column.get(_column_key(record)),
        )

    classes: dict[str, dict[str, Any]] = {}
    detail_rows: list[dict[str, Any]] = []
    total_cells: set[tuple[Any, Any]] = set()
    total_columns: set[tuple[Any, Any, Any]] = set()
    total_observations: set[str] = set()

    for pair in forbidden_pairs:
        conflict_class = str(pair.get("conflict_class", "unspecified"))
        left = _kind_set(pair.get("left_kinds"))
        right = _kind_set(pair.get("right_kinds"))
        if not left or not right:
            continue
        class_cells: set[tuple[Any, Any]] = set()
        class_columns: set[tuple[Any, Any, Any]] = set()
        class_observations: set[str] = set()

        def mark(
            level: str,
            record: Mapping[str, Any],
            *,
            counterpart: str | None = None,
        ) -> None:
            if level == "cell":
                key = _cell_key(record)
                if key[1]:
                    class_cells.add(key)
                    total_cells.add(key)
            elif level == "column":
                key = _column_key(record)
                if key[1] is not None and key[2] is not None:
                    class_columns.add(key)
                    total_columns.add(key)
            else:
                key = str(record.get("mapping_id"))
                class_observations.add(key)
                total_observations.add(key)
            detail_rows.append(
                {
                    "conflict_class": conflict_class,
                    "level": level,
                    "mapping_id": record.get("mapping_id"),
                    "document_id": record.get("document_id"),
                    "cell_id": record.get("cell_id"),
                    "table_id": record.get("table_id"),
                    "column_index": record.get("column_index"),
                    "actual_kind": record.get("kind"),
                    "expected_kind": expected_kind(record),
                    "counterpart_kind": counterpart,
                }
            )

        for record in records:
            actual = str(record["kind"])
            expected = expected_kind(record)
            expected_is_left = expected in left
            expected_is_right = expected in right
            wrong_side = (
                (expected_is_left and actual in right)
                or (expected_is_right and actual in left)
            )
            if wrong_side:
                counterpart = expected
                mark("cell", record, counterpart=counterpart)
                if record.get("direction") != "column_samples":
                    mark("column", record, counterpart=counterpart)
                mark("observation", record, counterpart=counterpart)

        for cell_id, cell_records in by_cell.items():
            kinds = {str(item["kind"]) for item in cell_records}
            if kinds & left and kinds & right:
                representative = cell_records[0]
                mark("cell", representative, counterpart="same_cell_both_sides")
                for item in cell_records:
                    if str(item["kind"]) in left | right:
                        mark("observation", item, counterpart="same_cell_both_sides")

        for column_key, column_records in by_column.items():
            kinds = {str(item["kind"]) for item in column_records}
            if kinds & left and kinds & right:
                representative = column_records[0]
                mark("column", representative, counterpart="same_column_both_sides")

        classes[conflict_class] = {
            "cell_level": len(class_cells),
            "column_level": len(class_columns),
            "observation_level": len(class_observations),
            "expected_conflicts": pair.get("expected_conflicts"),
        }

    return {
        "cell_level": len(total_cells),
        "column_level": len(total_columns),
        "observation_level": len(total_observations),
        "mutually_exclusive_property_mapping_conflicts": len(total_observations),
        "by_class": classes,
        "details": detail_rows,
    }


def _fixture_forbidden_pairs(fixture: Mapping[str, Any]) -> list[dict[str, Any]]:
    pairs: dict[str, dict[str, Any]] = {}
    for case in fixture.get("cases", []):
        for pair in case.get("forbidden_pairs", []):
            pairs[str(pair.get("conflict_class", "unspecified"))] = dict(pair)
    return list(pairs.values())


def _binding_expected_cells(
    binding_fixture: Mapping[str, Any],
) -> list[dict[str, Any]]:
    expected: list[dict[str, Any]] = []
    for case in binding_fixture.get("cases", []):
        if not case.get("eligible"):
            continue
        for item in expand_expected_observations(case).values():
            kind = item.get("expected_semantic_label") or item.get(
                "expected_property_name"
            )
            if kind:
                expected.append({
                    "document_id": case.get("doc_id"),
                    "cell_id": item.get("cell_id"),
                    "expected_kind": kind,
                })
    return expected


def audit_shadow_report(
    shadow_report: Mapping[str, Any],
    precision_fixture: Mapping[str, Any],
    binding_fixture: Mapping[str, Any],
) -> dict[str, Any]:
    """用通用互斥规则和逐格 binding 答案审计当前 Shadow 报告。"""
    observation_count = sum(
        len(table.get("observations", []))
        for document in shadow_report.get("documents", [])
        for table in document.get("tables", [])
    )
    mappings = shadow_report_to_mappings(shadow_report)
    expected_cells = _binding_expected_cells(binding_fixture)
    conflict_audit = audit_mutually_exclusive_mapping_conflicts(
        mappings,
        _fixture_forbidden_pairs(precision_fixture),
        expected_cells=expected_cells,
    )
    return {
        "audit_schema_version": "stage4t_shadow_conflict_audit.v0.1",
        "audit_version": AUDIT_VERSION,
        "shadow_version": shadow_report.get("shadow_version"),
        "precision_fixture_schema_version": precision_fixture.get("schema_version"),
        "binding_fixture_schema_version": binding_fixture.get("schema_version"),
        "observation_count": observation_count,
        "mapping_count": len(mappings),
        "unmapped_count": observation_count - len(mappings),
        "expected_cell_count": len(expected_cells),
        "summary": conflict_audit,
    }


def audit_shadow_files(
    precision_fixture_path: Path,
    binding_fixture_path: Path,
    shadow_report_path: Path,
) -> dict[str, Any]:
    precision_fixture = json.loads(
        precision_fixture_path.read_text(encoding="utf-8")
    )
    binding_fixture = load_fixture(binding_fixture_path)
    shadow_report = json.loads(shadow_report_path.read_text(encoding="utf-8"))
    return audit_shadow_report(
        shadow_report,
        precision_fixture,
        binding_fixture,
    )


def audit_snapshot_against_case(
    snapshot: Mapping[str, Any], case: Mapping[str, Any]
) -> dict[str, Any]:
    """用 Stage 4T fixture case 审计一个 Stage 4 properties 快照。"""
    mappings = snapshot_to_mappings(snapshot, table_id=case.get("table_id"))
    columns = [
        {**column, "table_id": case.get("table_id")}
        for column in case.get("columns", [])
    ]
    return audit_mutually_exclusive_mapping_conflicts(
        mappings,
        case.get("forbidden_pairs", []),
        expected_columns=columns,
    )


def audit_fixture_batch(
    fixture: Mapping[str, Any],
    preview_root: Path,
) -> dict[str, Any]:
    """对 fixture 中的 case 生成只读 Shadow 报告。"""
    documents: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    totals = {
        "cell_level": 0,
        "column_level": 0,
        "observation_level": 0,
        "mutually_exclusive_property_mapping_conflicts": 0,
    }

    for case in fixture.get("cases", []):
        doc_id = str(case.get("doc_id"))
        item: dict[str, Any] = {
            "doc_id": doc_id,
            "table_id": case.get("table_id"),
            "eligible": bool(case.get("eligible")),
            "expected_status": case.get("expected_status"),
        }
        table_id = case.get("table_id")
        snapshot_path = preview_root / doc_id / "stage4_properties.json"
        if not table_id:
            item["audit_status"] = "not_applicable_no_table_id"
            documents.append(item)
            continue
        if not snapshot_path.is_file():
            item["audit_status"] = "missing_stage4_properties"
            failures.append({"doc_id": doc_id, "error": "missing_stage4_properties"})
            documents.append(item)
            continue
        try:
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            report = audit_snapshot_against_case(snapshot, case)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            item["audit_status"] = "audit_failed"
            failures.append({
                "doc_id": doc_id,
                "error": f"{type(exc).__name__}: {exc}",
            })
            documents.append(item)
            continue
        item["audit_status"] = "audited"
        item["conflict_audit"] = report
        for key in totals:
            totals[key] += int(report[key])
        documents.append(item)

    return {
        "audit_schema_version": "stage4t_precision_shadow.v0.1",
        "audit_version": AUDIT_VERSION,
        "fixture_schema_version": fixture.get("schema_version"),
        "preview_root": str(preview_root.resolve()),
        "document_count": len(documents),
        "audited_document_count": sum(
            item.get("audit_status") == "audited" for item in documents
        ),
        "failure_count": len(failures),
        "failures": failures,
        "summary": totals,
        "documents": documents,
    }


def audit_fixture_file(fixture_path: Path, preview_root: Path) -> dict[str, Any]:
    """读取 fixture 文件并生成 Shadow 报告，不写入任何输入文件。"""
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    return audit_fixture_batch(fixture, preview_root)
