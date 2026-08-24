from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from schema.polymer_schema import Stage0Document
from stages.stage4t_table_interpretation import (
    build_interpretation_input,
    interpretation_route_reasons,
    validate_interpretation,
)
from stages.stage4t_table_property import shadow_extract_table
from stages.stage4t_table_survey import survey_table


TEST_ROOT = Path(__file__).parent
PROJECT_ROOT = TEST_ROOT.parents[1]
FIXTURE_PATH = (
    TEST_ROOT / "fixtures" / "stage4t_table_interpretation_v0.1.json"
)
BATCH_ROOT = PROJECT_ROOT / "batch_results" / "demo20_preview_final_20260812"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _contains_value_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            key == "value" or key.startswith("value_")
            or _contains_value_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_value_key(item) for item in value)
    return False


def test_v01_interpretations_validate_against_real_stage0_cells() -> None:
    fixture = _load(FIXTURE_PATH)
    documents: dict[str, Stage0Document] = {}

    assert fixture["schema_version"] == (
        "stage4t_table_interpretation_fixture.v0.1"
    )
    assert len(fixture["cases"]) == 5

    for case in fixture["cases"]:
        doc_id = case["doc_id"]
        if doc_id not in documents:
            documents[doc_id] = Stage0Document.model_validate(
                _load(BATCH_ROOT / doc_id / "stage0_blocks.json")
            )
        table = next(
            element
            for element in documents[doc_id].elements
            if element.block_id == case["table_id"]
        )
        request_input = build_interpretation_input(table)
        interpretation = validate_interpretation(
            case["interpretation"], request_input
        )

        assert interpretation.table_id == case["table_id"]
        assert interpretation.header_assignments
        assert not _contains_value_key(case["interpretation"])


def test_v01_cases_are_routed_because_rule_shadow_has_no_semantics() -> None:
    fixture = _load(FIXTURE_PATH)
    documents: dict[str, Stage0Document] = {}

    for case in fixture["cases"]:
        doc_id = case["doc_id"]
        if doc_id not in documents:
            documents[doc_id] = Stage0Document.model_validate(
                _load(BATCH_ROOT / doc_id / "stage0_blocks.json")
            )
        table = next(
            element
            for element in documents[doc_id].elements
            if element.block_id == case["table_id"]
        )
        survey = survey_table(table)
        shadow = shadow_extract_table(table)
        reasons = interpretation_route_reasons(survey, shadow, eligible=True)

        assert "only_unmapped_candidates" in reasons, (
            doc_id,
            case["table_id"],
            reasons,
        )


def test_v01_freezes_expected_direction_overrides() -> None:
    fixture = _load(FIXTURE_PATH)
    directions = {
        (case["doc_id"], case["table_id"]): case["interpretation"]["direction"]
        for case in fixture["cases"]
    }

    assert directions == {
        ("reference_no_0021296", "T_8_91"): "column_samples",
        ("reference_no_0038527", "T_5_69"): "row_samples",
        ("reference_no_0039705", "T_6_84"): "row_samples",
        ("reference_no_0043541", "T_4_49"): "column_samples",
        ("reference_no_0043590", "T_1_19"): "column_samples",
    }
