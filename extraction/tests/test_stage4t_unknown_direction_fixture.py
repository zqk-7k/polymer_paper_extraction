from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from schema.polymer_schema import Stage0Document
from stages.stage4t_table_property import shadow_extract_table
from stages.stage4t_table_survey import survey_table


TEST_ROOT = Path(__file__).parent
PROJECT_ROOT = TEST_ROOT.parents[1]
FIXTURE_PATH = TEST_ROOT / "fixtures" / "stage4t_unknown_direction_v0.1.json"
BATCH_ROOT = PROJECT_ROOT / "batch_results" / "demo20_preview_final_20260812"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_v01_freezes_unknown_table_direction_and_axis_roles() -> None:
    fixture = _load(FIXTURE_PATH)
    actual_counts: Counter[str] = Counter()

    assert fixture["schema_version"] == "stage4t_unknown_direction_fixture.v0.1"
    assert len(fixture["cases"]) == 14

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
        result = survey_table(table)

        assert result["direction"] == case["direction"], (doc_id, case["table_id"])
        assert result["sample_axis"] == case["sample_axis"], (doc_id, case["table_id"])
        assert result["axis_role"] == case["axis_role"], (doc_id, case["table_id"])
        assert result["header_rows"] == case["header_rows"], (doc_id, case["table_id"])
        actual_counts[result["direction"]] += 1

    assert actual_counts == {
        "column_samples": 3,
        "condition_series": 2,
        "row_samples": 9,
    }


def test_v01_recovered_tables_have_complete_axis_binding() -> None:
    fixture = _load(FIXTURE_PATH)
    documents: dict[str, Stage0Document] = {}
    total_observations = 0

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
        result = shadow_extract_table(table)
        observations = result["observations"]

        assert len(observations) == case["observation_count"], (doc_id, case["table_id"])
        assert not any(
            item["reason"] == "sample_label_not_found"
            for item in result["unresolved"]
        ), (doc_id, case["table_id"])
        if case["direction"] == "condition_series":
            assert all(item["sample_label_raw"] is None for item in observations)
            assert all(
                item["property_name_normalized"]
                != "thermal_decomposition_temperature"
                for item in observations
            )
        total_observations += len(observations)

    assert total_observations == 442
