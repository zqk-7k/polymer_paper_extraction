from __future__ import annotations

from pathlib import Path

from stages.stage4t_interpretation_audit import (
    audit_interpretations,
    render_audit_markdown,
)


TEST_ROOT = Path(__file__).parent
BATCH_ROOT = TEST_ROOT / "fixtures" / "stage4t_snapshots"
FIXTURE_PATH = (
    TEST_ROOT / "fixtures" / "stage4t_table_interpretation_v0.1.json"
)


def test_current_v01_remote_interpretations_match_required_fixture() -> None:
    report = audit_interpretations(
        batch_root=BATCH_ROOT,
        fixture_path=FIXTURE_PATH,
    )

    assert report["summary"]["case_count"] == 5
    assert report["summary"]["passed_count"] == 5
    assert report["summary"]["failed_count"] == 0
    assert report["summary"]["missing_expected_assignment_count"] == 0
    assert report["summary"]["matched_assignment_count"] == (
        report["summary"]["expected_assignment_count"]
    )
    assert "通过：5/5" in render_audit_markdown(report)
