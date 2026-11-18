"""审计 Stage 4T 无性质列/unknown 表的人工 eligibility fixture。"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping


CLASSIFICATIONS = {
    "eligible_property",
    "material_characteristic",
    "condition_or_process",
    "not_eligible",
    "ambiguous",
}


def _survey_candidates(survey: Mapping[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    candidates: dict[tuple[str, str], dict[str, Any]] = {}
    for document in survey.get("documents", []):
        doc_id = str(document.get("document_id"))
        for table in document.get("tables", []):
            warnings = set(table.get("warnings") or [])
            if (
                "numeric_table_without_property_columns" in warnings
                or table.get("direction") == "unknown"
            ):
                candidates[(doc_id, str(table.get("table_id")))] = dict(table)
    return candidates


def _survey_tables(survey: Mapping[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (str(document.get("document_id")), str(table.get("table_id"))): dict(table)
        for document in survey.get("documents", [])
        for table in document.get("tables", [])
    }


def audit_eligibility(
    fixture: Mapping[str, Any],
    survey: Mapping[str, Any],
    shadow_report: Mapping[str, Any],
    binding_fixture: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    candidates = _survey_candidates(survey)
    survey_tables = _survey_tables(survey)
    fixture_cases = {
        (str(case.get("doc_id")), str(case.get("table_id"))): dict(case)
        for case in fixture.get("cases", [])
    }
    shadow_tables = {
        (str(document.get("document_id")), str(table.get("table_id"))): table
        for document in shadow_report.get("documents", [])
        for table in document.get("tables", [])
    }

    failures: list[dict[str, Any]] = []
    for key in sorted(candidates.keys() - fixture_cases.keys()):
        failures.append({"doc_id": key[0], "table_id": key[1], "error": "missing_fixture_case"})
    for key in sorted(fixture_cases.keys() - survey_tables.keys()):
        failures.append({"doc_id": key[0], "table_id": key[1], "error": "fixture_table_not_found"})

    counts: Counter[str] = Counter()
    cases: list[dict[str, Any]] = []
    for key in sorted(fixture_cases.keys() & survey_tables.keys()):
        case = fixture_cases[key]
        classification = str(case.get("classification"))
        if classification not in CLASSIFICATIONS:
            failures.append({"doc_id": key[0], "table_id": key[1], "error": "invalid_classification"})
        modes = set(case.get("eligible_modes") or [])
        invalid_modes = modes - {"numeric", "categorical"}
        if invalid_modes:
            failures.append({"doc_id": key[0], "table_id": key[1], "error": "invalid_eligible_mode"})
        survey_table = survey_tables[key]
        shadow_table = shadow_tables.get(key) or {}
        observations = shadow_table.get("observations") or []
        observation_count = len(observations)
        semantic_observation_count = sum(
            item.get("semantic_status") in {"normalized", "mapped_characteristic"}
            or bool(item.get("property_name_normalized") or item.get("semantic_label"))
            for item in observations
        )
        publication_eligible_count = sum(
            (item.get("publication_gate") or {}).get("status") == "eligible"
            for item in observations
        )
        numeric_eligible = "numeric" in modes
        categorical_eligible = "categorical" in modes
        shadow_status = "has_output" if observation_count else "zero_output"

        counts[f"classification:{classification}"] += 1
        counts["numeric_eligible_table_count"] += numeric_eligible
        counts["categorical_eligible_table_count"] += categorical_eligible
        if numeric_eligible and not observation_count:
            counts["numeric_eligible_zero_output_table_count"] += 1
        if categorical_eligible and not observation_count:
            counts["categorical_eligible_zero_output_table_count"] += 1
        if observation_count:
            counts["tables_with_shadow_output"] += 1
        if semantic_observation_count:
            counts["tables_with_semantic_output"] += 1
        if publication_eligible_count:
            counts["tables_with_publication_eligible_output"] += 1

        cases.append({
            "doc_id": key[0],
            "table_id": key[1],
            "caption": survey_table.get("caption"),
            "survey_direction": survey_table.get("direction"),
            "survey_numeric_cell_count": survey_table.get("numeric_cell_count"),
            "survey_warnings": survey_table.get("warnings") or [],
            "classification": classification,
            "eligible_modes": sorted(modes),
            "mixed_content": bool(case.get("mixed_content")),
            "target_families": case.get("target_families") or [],
            "reason": case.get("reason"),
            "shadow_observation_count": observation_count,
            "shadow_status": shadow_status,
            "semantic_observation_count": semantic_observation_count,
            "semantic_shadow_status": (
                "has_output" if semantic_observation_count else "zero_output"
            ),
            "publication_eligible_count": publication_eligible_count,
            "publication_status": (
                "eligible" if publication_eligible_count else "candidate_only"
            ),
        })

    summary = {
        "reviewed_table_count": len(cases),
        "classification_counts": {
            name: counts[f"classification:{name}"]
            for name in sorted(CLASSIFICATIONS)
        },
        "numeric_eligible_table_count": counts["numeric_eligible_table_count"],
        "numeric_eligible_zero_output_table_count": counts[
            "numeric_eligible_zero_output_table_count"
        ],
        "categorical_eligible_table_count": counts["categorical_eligible_table_count"],
        "categorical_eligible_zero_output_table_count": counts[
            "categorical_eligible_zero_output_table_count"
        ],
        "tables_with_shadow_output": counts["tables_with_shadow_output"],
        "tables_with_semantic_output": counts["tables_with_semantic_output"],
        "tables_with_publication_eligible_output": counts[
            "tables_with_publication_eligible_output"
        ],
    }
    if binding_fixture is not None:
        reviewed_numeric = {
            (case["doc_id"], case["table_id"])
            for case in cases
            if "numeric" in case["eligible_modes"]
        }
        reviewed_output = {
            (case["doc_id"], case["table_id"])
            for case in binding_fixture.get("cases", [])
            if case.get("eligible")
        }
        all_output = {
            key
            for key, table in shadow_tables.items()
            if table.get("observations")
        }
        all_semantic_output = {
            key
            for key, table in shadow_tables.items()
            if any(
                item.get("semantic_status") in {"normalized", "mapped_characteristic"}
                or bool(item.get("property_name_normalized") or item.get("semantic_label"))
                for item in table.get("observations", [])
            )
        }
        all_publication_eligible = {
            key
            for key, table in shadow_tables.items()
            if any(
                (item.get("publication_gate") or {}).get("status") == "eligible"
                for item in table.get("observations", [])
            )
        }
        combined_eligible = reviewed_numeric | reviewed_output
        combined_output = combined_eligible & all_output
        combined_semantic_output = combined_eligible & all_semantic_output
        combined_publication_eligible = combined_eligible & all_publication_eligible
        summary.update({
            "combined_numeric_eligible_table_count": len(combined_eligible),
            "combined_numeric_output_table_count": len(combined_output),
            "combined_numeric_zero_output_table_count": len(
                combined_eligible - combined_output
            ),
            "combined_numeric_table_output_coverage": round(
                len(combined_output) / len(combined_eligible), 6
            ) if combined_eligible else None,
            "combined_numeric_semantic_output_table_count": len(
                combined_semantic_output
            ),
            "combined_numeric_semantic_zero_output_table_count": len(
                combined_eligible - combined_semantic_output
            ),
            "combined_numeric_semantic_output_coverage": round(
                len(combined_semantic_output) / len(combined_eligible), 6
            ) if combined_eligible else None,
            "combined_numeric_publication_eligible_table_count": len(
                combined_publication_eligible
            ),
            "combined_numeric_publication_eligible_coverage": round(
                len(combined_publication_eligible) / len(combined_eligible), 6
            ) if combined_eligible else None,
        })
    return {
        "audit_schema_version": "stage4t_table_eligibility_audit.v0.1",
        "fixture_schema_version": fixture.get("schema_version"),
        "survey_schema_version": survey.get("survey_schema_version"),
        "shadow_version": shadow_report.get("shadow_version"),
        "failure_count": len(failures),
        "failures": failures,
        "summary": summary,
        "cases": cases,
    }


def audit_files(
    fixture_path: Path,
    survey_path: Path,
    shadow_report_path: Path,
    binding_fixture_path: Path | None = None,
) -> dict[str, Any]:
    binding_fixture = None
    if binding_fixture_path is not None:
        from stages.stage4t_shadow_binding_audit import load_fixture

        binding_fixture = load_fixture(binding_fixture_path)
    return audit_eligibility(
        json.loads(fixture_path.read_text(encoding="utf-8")),
        json.loads(survey_path.read_text(encoding="utf-8")),
        json.loads(shadow_report_path.read_text(encoding="utf-8")),
        binding_fixture,
    )


def render_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Stage 4T 表格 Eligibility 人工复核",
        "",
        f"- Fixture：`{report.get('fixture_schema_version')}`",
        f"- 复核表数：{summary.get('reviewed_table_count', 0)}",
        f"- 分类：`{summary.get('classification_counts', {})}`",
        f"- Numeric eligible：{summary.get('numeric_eligible_table_count', 0)}",
        f"- Numeric eligible 零输出：{summary.get('numeric_eligible_zero_output_table_count', 0)}",
        f"- Categorical eligible：{summary.get('categorical_eligible_table_count', 0)}",
        f"- 全批 numeric eligible 表：{summary.get('combined_numeric_eligible_table_count', '未合并')}",
        f"- 全批当前有输出：{summary.get('combined_numeric_output_table_count', '未合并')}",
        f"- 全批表级输出覆盖：{summary.get('combined_numeric_table_output_coverage', '未合并')}",
        f"- 全批已映射语义覆盖：{summary.get('combined_numeric_semantic_output_coverage', '未合并')}",
        f"- 全批权威发布资格覆盖：{summary.get('combined_numeric_publication_eligible_coverage', '未合并')}",
        f"- 失败：{report.get('failure_count', 0)}",
        "",
        "| 文献 | 表格 | 分类 | Eligible 模式 | Survey 方向 | 数值格 | 宽松候选 | 已映射语义 | 可发布 | 目标语义 | 理由 |",
        "|---|---|---|---|---|---:|---:|---:|---:|---|---|",
    ]
    for case in report.get("cases", []):
        lines.append(
            "| {doc} | {table} | {classification} | {modes} | {direction} | {numeric} | {output} | {semantic} | {publishable} | {families} | {reason} |".format(
                doc=case.get("doc_id"),
                table=case.get("table_id"),
                classification=case.get("classification"),
                modes=", ".join(case.get("eligible_modes") or []) or "—",
                direction=case.get("survey_direction"),
                numeric=case.get("survey_numeric_cell_count"),
                output=case.get("shadow_observation_count"),
                semantic=case.get("semantic_observation_count"),
                publishable=case.get("publication_eligible_count"),
                families=", ".join(case.get("target_families") or []) or "—",
                reason=str(case.get("reason") or "").replace("|", "\\|"),
            )
        )
    return "\n".join(lines) + "\n"
