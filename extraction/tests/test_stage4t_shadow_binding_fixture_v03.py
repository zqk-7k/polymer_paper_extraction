from __future__ import annotations

import json
from pathlib import Path

from stages.stage4t_shadow_binding_audit import (
    audit_shadow_report,
    expand_expected_observations,
    load_fixture,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "stage4t_shadow_binding_v0.3.json"
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


def test_v03_covers_every_current_shadow_output_table() -> None:
    fixture = _fixture()
    report = _report()

    fixture_tables = {
        (case["doc_id"], case["table_id"])
        for case in fixture["cases"] if case["eligible"]
    }
    output_tables = {
        (document["document_id"], table["table_id"])
        for document in report["documents"]
        for table in document["tables"]
        if table.get("observations")
    }

    assert fixture["schema_version"] == "stage4t_shadow_binding_fixture.v0.3"
    assert fixture["base_fixture_schema_version"] == "stage4t_shadow_binding_fixture.v0.2"
    assert len(fixture["cases"]) == 27
    assert len(fixture_tables) == 26
    assert fixture_tables == output_tables
    assert sum(
        len(expand_expected_observations(case))
        for case in fixture["cases"] if case["eligible"]
    ) == 538


def test_v03_current_report_passes_full_output_table_audit() -> None:
    report = audit_shadow_report(_fixture(), _report())
    summary = report["summary"]

    assert report["failure_count"] == 0
    assert summary["expected_cell_count"] == 538
    assert summary["matched_cell_count"] == 538
    assert summary["missing_cell_count"] == 0
    assert summary["unexpected_cell_count"] == 0
    assert summary["eligible_complete_table_count"] == 26
    assert summary.get("eligible_partial_table_count", 0) == 0
    assert summary["direction_accuracy"] == 1.0
    assert summary["numeric_cell_recall"] == 1.0
    assert summary["output_precision"] == 1.0
    assert summary["property_mapping_accuracy"] == 1.0
    assert summary["sample_binding_accuracy"] == 1.0
    assert summary["duplicate_output_rate"] == 0.0
