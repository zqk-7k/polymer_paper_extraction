from __future__ import annotations

import json
from pathlib import Path

from stages.stage4t_shadow_binding_audit import (
    audit_shadow_report,
    expand_expected_observations,
    load_fixture,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "stage4t_shadow_binding_v0.2.json"
SHADOW_REPORT_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "stage4t_snapshots"
    / "reports"
    / "stage4t_table_property_shadow_20260821.json"
)


def _fixture() -> dict:
    return load_fixture(FIXTURE_PATH)


def _report() -> dict:
    return json.loads(SHADOW_REPORT_PATH.read_text(encoding="utf-8"))


def test_v02_inherits_v01_and_expands_characteristic_coverage() -> None:
    fixture = _fixture()

    assert fixture["schema_version"] == "stage4t_shadow_binding_fixture.v0.2"
    assert fixture["base_fixture_schema_version"] == "stage4t_shadow_binding_fixture.v0.1"
    assert len(fixture["cases"]) == 13
    assert sum(case["eligible"] for case in fixture["cases"]) == 12
    assert sum(
        len(expand_expected_observations(case))
        for case in fixture["cases"] if case["eligible"]
    ) == 260
    assert {
        case["table_role"] for case in fixture["cases"]
    } >= {
        "inherent_viscosity",
        "grouped_header_run_axis",
        "molecular_weight_and_blank_sample_event",
        "crystallinity_complex_sample_labels",
        "transposed_mass_loss_fraction",
        "cell_density_not_material_density",
        "ocr_shifted_viscosity_column",
    }


def test_v02_current_report_passes_after_reviewed_column_shift_recovery() -> None:
    report = audit_shadow_report(_fixture(), _report())
    summary = report["summary"]

    assert report["failure_count"] == 0
    assert summary["expected_cell_count"] == 260
    assert summary["matched_cell_count"] == 260
    assert summary["missing_cell_count"] == 0
    assert summary["unexpected_cell_count"] == 0
    assert summary["eligible_complete_table_count"] == 12
    assert summary.get("eligible_partial_table_count", 0) == 0
    assert summary["property_mapping_accuracy"] == 1.0
    assert summary["sample_binding_accuracy"] == 1.0
