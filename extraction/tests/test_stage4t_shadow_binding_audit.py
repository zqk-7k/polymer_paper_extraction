from __future__ import annotations

import json
from pathlib import Path

from stages.stage4t_shadow_binding_audit import (
    audit_shadow_report,
    expand_expected_observations,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "stage4t_shadow_binding_v0.1.json"
SHADOW_REPORT_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "stage4t_snapshots"
    / "reports"
    / "stage4t_table_property_shadow_20260821.json"
)


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _report() -> dict:
    return json.loads(SHADOW_REPORT_PATH.read_text(encoding="utf-8"))


def test_fixture_covers_all_required_table_shapes_and_risks() -> None:
    fixture = _fixture()

    assert fixture["schema_version"] == "stage4t_shadow_binding_fixture.v0.1"
    assert {case["table_role"] for case in fixture["cases"]} == {
        "row_samples_multilevel_header",
        "column_samples",
        "mixed_repeated_groups",
        "thermal_mass_sentinel",
        "blank_sample_cross_row_event",
        "condition_axis_not_sample",
        "categorical_unknown_safe_hold",
    }
    assert sum(
        len(expand_expected_observations(case))
        for case in fixture["cases"] if case["eligible"]
    ) == 108


def test_fixture_expansion_preserves_null_semantics_and_stable_cells() -> None:
    cases = {case["table_role"]: case for case in _fixture()["cases"]}
    thermal = expand_expected_observations(cases["thermal_mass_sentinel"])
    condition = expand_expected_observations(cases["condition_axis_not_sample"])

    assert thermal["T_6_86:r0001:c0005"] == {
        "cell_id": "T_6_86:r0001:c0005",
        "expected_property_name": None,
        "expected_semantic_label": "char_yield",
        "expected_property_variant": None,
        "expected_conditions": {"temperature_celsius": 700.0},
        "expected_sample_label": "1AQA-PPDI",
        "sample_evaluable": True,
    }
    assert condition["T_5_83:r0002:c0001"]["expected_sample_label"] is None


def test_current_shadow_metrics_are_reproducible() -> None:
    report = audit_shadow_report(_fixture(), _report())
    summary = report["summary"]

    assert report["failure_count"] == 0
    assert summary["table_count"] == 7
    assert summary["eligible_table_count"] == 6
    assert summary["expected_cell_count"] == 108
    assert summary["matched_cell_count"] == 108
    assert summary["missing_cell_count"] == 0
    assert summary["numeric_cell_recall"] == 1.0
    assert summary["output_precision"] == 1.0
    assert summary["property_mapping_accuracy"] == 1.0
    assert summary["sample_binding_accuracy"] == 1.0
    assert summary["duplicate_output_rate"] == 0.0
    assert summary["eligible_complete_table_count"] == 6
    assert summary.get("eligible_partial_table_count", 0) == 0
    assert summary.get("eligible_zero_output_table_count", 0) == 0


def test_audit_detects_missing_wrong_duplicate_and_unexpected_outputs() -> None:
    fixture = {
        "schema_version": "test",
        "cases": [{
            "doc_id": "doc",
            "table_id": "T",
            "eligible": True,
            "expected_direction": "row_samples",
            "audit_columns": [1, 3],
            "sample_labels_by_row": {"1": "S1", "2": "S2"},
            "expected_columns": [{
                "column_index": 1,
                "rows": [1, 2],
                "expected_property_name": "glass_transition_temperature",
            }],
        }],
    }
    shadow = {
        "shadow_version": "test",
        "documents": [{"document_id": "doc", "tables": [{
            "table_id": "T",
            "direction": "row_samples",
            "observations": [
                {"cell_id": "T:r0001:c0001", "property_name_normalized": "melting_temperature", "sample_label_raw": "wrong"},
                {"cell_id": "T:r0001:c0001", "property_name_normalized": "glass_transition_temperature", "sample_label_raw": "S1"},
                {"cell_id": "T:r0003:c0001", "property_name_normalized": "glass_transition_temperature", "sample_label_raw": "S3"},
            ],
        }]}],
    }

    summary = audit_shadow_report(fixture, shadow)["summary"]

    assert summary["matched_cell_count"] == 1
    assert summary["missing_cell_count"] == 1
    assert summary["unexpected_cell_count"] == 1
    assert summary["duplicate_extra_count"] == 1
    assert summary["property_mapping_accuracy"] == 0.5
    assert summary["sample_binding_accuracy"] == 0.5
