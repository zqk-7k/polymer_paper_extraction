import json
from pathlib import Path

from stages.stage4t_precision_audit import (
    audit_fixture_batch,
    audit_mutually_exclusive_mapping_conflicts,
    audit_shadow_report,
    audit_snapshot_against_case,
)
from stages.stage4t_shadow_binding_audit import load_fixture


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "stage4t_precision_v0.1.json"
PREVIEW_ROOT = (
    Path(__file__).parent
    / "fixtures"
    / "stage4t_snapshots"
)
SHADOW_REPORT_PATH = (
    PREVIEW_ROOT
    / "reports"
    / "stage4t_table_property_shadow_20260821.json"
)
BINDING_FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "stage4t_shadow_binding_v0.3.json"
)


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _case(doc_id: str) -> dict:
    return next(item for item in _fixture()["cases"] if item["doc_id"] == doc_id)


def test_fixture_has_stable_multi_sample_table_counts_and_bindings() -> None:
    case = _case("reference_no_0038813")
    assert case["eligible"] is True
    assert case["table_role"] == "multi_sample_multi_property"
    assert len(case["sample_rows"]) == 8
    assert len(case["columns"]) == 5
    assert case["expected_counts"] == {
        "table_numeric_cells": 40,
        "glass_transition_temperature": 8,
        "thermal_decomposition_temperature": 24,
        "thermal_mass_fraction_by_weight_loss": 16,
        "char_yield": 8,
        "observations_if_weight_loss_is_split": 56,
        "mutually_exclusive_property_mapping_conflicts": 0,
    }
    assert {row["sample_id"] for row in case["sample_rows"]} == set(
        case["sample_id_by_row"].values()
    )


def test_fixture_defines_general_mutually_exclusive_mapping_conflicts() -> None:
    case = _case("reference_no_0038813")
    assert case["expected_counts"]["mutually_exclusive_property_mapping_conflicts"] == 0
    assert {item["conflict_class"] for item in case["forbidden_pairs"]} == {
        "thermal_mass_vs_decomposition",
        "glass_transition_vs_melting",
        "viscosity_vs_molecular_weight",
    }
    assert all(item["left_kinds"] for item in case["forbidden_pairs"])
    assert all(item["right_kinds"] for item in case["forbidden_pairs"])


def test_char_yield_case_is_a_thermal_mass_sentinel_not_the_metric_name() -> None:
    case = _case("reference_no_0038813")
    char_column = next(c for c in case["columns"] if c["expected_kind"] == "char_yield")
    assert char_column["temperature"] == 700
    assert "thermal_decomposition_temperature" in char_column["forbid_kind"]
    sentinel = next(
        item for item in case["forbidden_pairs"]
        if item["conflict_class"] == "thermal_mass_vs_decomposition"
    )
    assert sentinel["sentinel"] == "char_yield_to_thermal_decomposition_temperature"


def test_current_0038813_snapshot_exposes_the_known_stage4_binding_gap() -> None:
    case = _case("reference_no_0038813")
    snapshot = json.loads(
        (PREVIEW_ROOT / "reference_no_0038813" / "stage4_properties.json").read_text(
            encoding="utf-8"
        )
    )
    properties = snapshot["properties"]
    table_properties = [
        item
        for item in properties
        if (item.get("evidence") or [{}])[0].get("table_locator", {}).get("table_id")
        == case["table_id"]
    ]
    assert len(table_properties) == 16
    assert sum(
        item.get("property_name_raw") == "thermal_decomposition_temperature"
        and (item.get("evidence") or [{}])[0].get("table_locator", {}).get("column_index") == 5
        for item in table_properties
    ) == 8
    assert not any(
        item.get("property_name_raw") == "thermal_decomposition_temperature"
        and (item.get("evidence") or [{}])[0].get("table_locator", {}).get("column_index") in {2, 3, 4}
        for item in table_properties
    )


def test_general_conflict_audit_detects_fixture_sentinel_in_current_snapshot() -> None:
    case = _case("reference_no_0038813")
    snapshot = json.loads(
        (PREVIEW_ROOT / "reference_no_0038813" / "stage4_properties.json").read_text(
            encoding="utf-8"
        )
    )

    report = audit_snapshot_against_case(snapshot, case)

    assert report["cell_level"] == 8
    assert report["column_level"] == 1
    assert report["observation_level"] == 8
    assert report["mutually_exclusive_property_mapping_conflicts"] == 8
    assert report["by_class"]["thermal_mass_vs_decomposition"] == {
        "cell_level": 8,
        "column_level": 1,
        "observation_level": 8,
        "expected_conflicts": 0,
    }
    assert report["by_class"]["glass_transition_vs_melting"]["observation_level"] == 0
    assert report["by_class"]["viscosity_vs_molecular_weight"]["observation_level"] == 0


def test_general_conflict_audit_is_not_specific_to_char_yield() -> None:
    rules = [
        {
            "conflict_class": "glass_transition_vs_melting",
            "left_kinds": ["glass_transition_temperature"],
            "right_kinds": ["melting_temperature"],
            "expected_conflicts": 0,
        }
    ]
    mappings = [
        {
            "mapping_id": "prop-tg-wrong",
            "table_id": "T_test",
            "cell_id": "T_test:r0001:c0001",
            "row_index": 1,
            "column_index": 1,
            "kind": "melting_temperature",
        },
        {
            "mapping_id": "prop-tg-correct",
            "table_id": "T_test",
            "cell_id": "T_test:r0002:c0001",
            "row_index": 2,
            "column_index": 1,
            "kind": "glass_transition_temperature",
        },
    ]
    expected_columns = [
        {
            "table_id": "T_test",
            "index": 1,
            "expected_kind": "glass_transition_temperature",
        }
    ]

    report = audit_mutually_exclusive_mapping_conflicts(
        mappings,
        rules,
        expected_columns=expected_columns,
    )

    assert report["cell_level"] == 1
    assert report["column_level"] == 1
    assert report["observation_level"] == 1
    assert report["by_class"]["glass_transition_vs_melting"]["observation_level"] == 1


def test_general_conflict_audit_accepts_correct_mapping() -> None:
    case = _case("reference_no_0038813")
    mappings = [
        {
            "mapping_id": "prop-char",
            "table_id": case["table_id"],
            "cell_id": f"{case['table_id']}:r0001:c0005",
            "row_index": 1,
            "column_index": 5,
            "kind": "char_yield",
        }
    ]
    columns = [{**item, "table_id": case["table_id"]} for item in case["columns"]]

    report = audit_mutually_exclusive_mapping_conflicts(
        mappings,
        case["forbidden_pairs"],
        expected_columns=columns,
    )

    assert report["mutually_exclusive_property_mapping_conflicts"] == 0
    assert report["cell_level"] == 0
    assert report["column_level"] == 0


def test_current_stage4t_shadow_has_no_mutually_exclusive_mapping_conflicts() -> None:
    shadow_report = json.loads(SHADOW_REPORT_PATH.read_text(encoding="utf-8"))
    report = audit_shadow_report(
        shadow_report,
        _fixture(),
        load_fixture(BINDING_FIXTURE_PATH),
    )

    assert report["audit_schema_version"] == "stage4t_shadow_conflict_audit.v0.1"
    assert report["observation_count"] == 538
    assert report["mapping_count"] == 524
    assert report["unmapped_count"] == 14
    assert report["expected_cell_count"] == 524
    assert report["summary"]["mutually_exclusive_property_mapping_conflicts"] == 0
    assert report["summary"]["cell_level"] == 0
    assert report["summary"]["column_level"] == 0


def test_fixture_batch_shadow_report_keeps_non_table_cases_and_aggregates_counts() -> None:
    report = audit_fixture_batch(_fixture(), PREVIEW_ROOT)

    assert report["audit_schema_version"] == "stage4t_precision_shadow.v0.1"
    assert report["document_count"] == 3
    assert report["audited_document_count"] == 2
    assert report["failure_count"] == 0
    assert report["summary"] == {
        "cell_level": 8,
        "column_level": 1,
        "observation_level": 8,
        "mutually_exclusive_property_mapping_conflicts": 8,
    }
    statuses = {item["doc_id"]: item["audit_status"] for item in report["documents"]}
    assert statuses == {
        "reference_no_0038813": "audited",
        "reference_no_0033617": "audited",
        "reference_no_0043955": "not_applicable_no_table_id",
    }


def test_fixture_batch_shadow_report_keeps_missing_input_as_failure(tmp_path: Path) -> None:
    fixture = {
        "schema_version": "stage4t_precision_fixture.v0.1",
        "cases": [{
            "doc_id": "reference_no_missing",
            "table_id": "T_missing",
            "eligible": True,
            "forbidden_pairs": [],
            "columns": [],
        }],
    }

    report = audit_fixture_batch(fixture, tmp_path)

    assert report["document_count"] == 1
    assert report["audited_document_count"] == 0
    assert report["failure_count"] == 1
    assert report["failures"] == [{
        "doc_id": "reference_no_missing",
        "error": "missing_stage4_properties",
    }]


def test_0033617_fixture_requires_non_success_when_series_subject_is_missing() -> None:
    case = _case("reference_no_0033617")
    assert case["expected_status"] == "semantic_validation_failure"
    snapshot = json.loads(
        (PREVIEW_ROOT / "reference_no_0033617" / "stage4_properties.json").read_text(
            encoding="utf-8"
        )
    )
    series = snapshot["property_series"]
    assert len(series) == 3
    assert all(item.get("sample_id") is None for item in series)
    assert all(item.get("entity_id") is None for item in series)


def test_0043955_fixture_requires_partial_status_and_tail_diagnostic() -> None:
    case = _case("reference_no_0043955")
    snapshot_dir = PREVIEW_ROOT / "reference_no_0043955"
    stage4 = json.loads((snapshot_dir / "stage4_properties.json").read_text(encoding="utf-8"))
    response = json.loads((snapshot_dir / "stage4_llm_response.json").read_text(encoding="utf-8"))
    content = response["raw_response"]["content"]
    assert stage4["provenance"]["status"] == "success"
    assert any(item.get("code") == "preview_degraded_empty_shell" for item in stage4["warnings"])
    assert case["expected_status"] == "candidate_partial"
    assert case["forbid_status"] == ["success"]
    assert all(keyword in content for keyword in case["required_diagnostic_keywords"])
    assert content.rstrip().endswith("```")
