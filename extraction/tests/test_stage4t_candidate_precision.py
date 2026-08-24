from __future__ import annotations

import json
from pathlib import Path

from stages.stage4t_candidate_precision import (
    audit_candidate_fixture,
    build_fixture_from_sidecars,
    build_expected_cell_fixture_from_sidecars,
    build_extended_fixture_from_sidecars,
)


TEST_ROOT = Path(__file__).parent
BATCH_ROOT = TEST_ROOT / "fixtures" / "stage4t_snapshots"
REFS = [
    "reference_no_0021296",
    "reference_no_0038527",
    "reference_no_0039705",
    "reference_no_0043541",
    "reference_no_0043590",
]


def test_candidate_fixture_seed_is_explicitly_provisional() -> None:
    fixture = build_fixture_from_sidecars(BATCH_ROOT, REFS)

    assert fixture["schema_version"] == "stage4t_candidate_precision_fixture.v0.1"
    assert fixture["review_status"] == "provisional_seed"
    assert "禁止" in fixture["accuracy_claim"]
    assert len(fixture["cases"]) == 5
    assert sum(case["expected_observation_count"] for case in fixture["cases"]) == 98
    assert all(case["review_status"] == "pending_human_review" for case in fixture["cases"])


def test_candidate_fixture_audit_is_structural_and_candidate_only() -> None:
    fixture = build_fixture_from_sidecars(BATCH_ROOT, REFS)
    report = audit_candidate_fixture(fixture, BATCH_ROOT)

    assert report["failure_count"] == 0
    assert report["fixture_review_status"] == "provisional_seed"
    assert report["summary"] == {
        "expected": 98,
        "actual": 98,
        "matched": 98,
        "missing": 0,
        "extra": 0,
        "duplicate": 0,
        "value_mismatch": 0,
        "semantic_mismatch": 0,
        "sample_mismatch": 0,
        "condition_mismatch": 0,
        "unit_mismatch": 0,
        "role_mismatch": 0,
        "cell_recall": 1.0,
    }
    assert all(
        case["publication_statuses"] == {"candidate_only": case["actual_count"]}
        for case in report["cases"]
    )


def test_candidate_fixture_audit_detects_value_and_semantic_changes(tmp_path: Path) -> None:
    fixture = build_fixture_from_sidecars(BATCH_ROOT, REFS)
    first = fixture["cases"][0]["observations"][0]
    first["value_raw"] = "CHANGED"
    first["semantic_label"] = "wrong_semantic"

    report = audit_candidate_fixture(fixture, BATCH_ROOT)

    assert report["summary"]["value_mismatch"] == 1
    assert report["summary"]["semantic_mismatch"] == 1
    assert report["cases"][0]["mismatches"][0]["cell_id"] == first["cell_id"]


def test_expected_cell_fixture_includes_known_gaps() -> None:
    fixture = build_expected_cell_fixture_from_sidecars(BATCH_ROOT, REFS)

    assert fixture["schema_version"] == "stage4t_candidate_precision_fixture.v0.2"
    t449 = next(case for case in fixture["cases"] if case["table_id"] == "T_4_49")
    assert t449["expected_cell_count"] == 24
    assert {
        item["cell_id"] for item in t449["expected_cells"]
        if item["cell_id"].startswith("T_4_49:r000")
        and item["cell_id"].endswith(":c0002")
        and item["cell_id"] in {
            "T_4_49:r0002:c0002",
            "T_4_49:r0003:c0002",
            "T_4_49:r0004:c0002",
        }
    } == {
        "T_4_49:r0002:c0002",
        "T_4_49:r0003:c0002",
        "T_4_49:r0004:c0002",
    }

    report = audit_candidate_fixture(fixture, BATCH_ROOT)
    assert report["summary"]["expected"] == 98
    assert report["summary"]["actual"] == 98
    assert report["summary"]["matched"] == 98
    assert report["summary"]["missing"] == 0
    assert report["summary"]["extra"] == 0
    assert report["summary"]["cell_recall"] == 1.0


def test_extended_fixture_includes_categorical_solubility_tables() -> None:
    fixture = build_extended_fixture_from_sidecars(BATCH_ROOT, REFS)

    assert fixture["schema_version"] == "stage4t_candidate_precision_fixture.v0.3"
    assert len(fixture["cases"]) == 7
    assert sum(case["expected_cell_count"] for case in fixture["cases"]) == 212
    solubility_cases = {
        case["table_id"]: case for case in fixture["cases"]
        if case["table_id"] in {"T_5_74", "T_7_98"}
    }
    assert solubility_cases["T_5_74"]["expected_cell_count"] == 66
    assert solubility_cases["T_7_98"]["expected_cell_count"] == 48

    report = audit_candidate_fixture(fixture, BATCH_ROOT)
    assert report["summary"]["expected"] == 212
    assert report["summary"]["actual"] == 212
    assert report["summary"]["matched"] == 212
    assert report["summary"]["missing"] == 0
    assert report["summary"]["duplicate"] == 0
