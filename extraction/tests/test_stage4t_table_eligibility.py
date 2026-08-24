from __future__ import annotations

import json
from pathlib import Path

from stages.stage4t_table_eligibility import audit_eligibility
from stages.stage4t_shadow_binding_audit import load_fixture


TEST_ROOT = Path(__file__).parent
FIXTURE_PATH = TEST_ROOT / "fixtures" / "stage4t_table_eligibility_v0.4.json"
SNAPSHOT_ROOT = TEST_ROOT / "fixtures" / "stage4t_snapshots"
SURVEY_PATH = SNAPSHOT_ROOT / "reports" / "stage4t_table_structure_survey_20260821.json"
SHADOW_PATH = SNAPSHOT_ROOT / "reports" / "stage4t_table_property_shadow_20260821.json"
BINDING_FIXTURE_PATH = TEST_ROOT / "fixtures" / "stage4t_shadow_binding_v0.3.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _report() -> dict:
    return audit_eligibility(
        _load(FIXTURE_PATH),
        _load(SURVEY_PATH),
        _load(SHADOW_PATH),
        load_fixture(BINDING_FIXTURE_PATH),
    )


def test_v04_exactly_covers_numeric_without_property_or_unknown_tables() -> None:
    report = _report()

    assert report["failure_count"] == 0
    assert report["summary"]["reviewed_table_count"] == 41
    assert report["summary"]["classification_counts"] == {
        "ambiguous": 2,
        "condition_or_process": 2,
        "eligible_property": 16,
        "material_characteristic": 19,
        "not_eligible": 2,
    }


def test_v04_freezes_real_zero_output_denominators() -> None:
    summary = _report()["summary"]

    assert summary["numeric_eligible_table_count"] == 33
    assert summary["numeric_eligible_zero_output_table_count"] == 25
    assert summary["categorical_eligible_table_count"] == 2
    assert summary["categorical_eligible_zero_output_table_count"] == 2
    assert summary["tables_with_shadow_output"] == 8
    assert summary["combined_numeric_eligible_table_count"] == 51
    assert summary["combined_numeric_output_table_count"] == 26
    assert summary["combined_numeric_zero_output_table_count"] == 25
    assert summary["combined_numeric_table_output_coverage"] == 0.509804


def test_v04_keeps_conditions_and_calculated_properties_out_of_numeric_gate() -> None:
    report = _report()
    by_table = {
        (case["doc_id"], case["table_id"]): case
        for case in report["cases"]
    }

    assert by_table[("reference_no_0025452", "T_6_40")]["classification"] == "condition_or_process"
    assert by_table[("reference_no_0042367", "T_2_31")]["eligible_modes"] == []
    assert by_table[("reference_no_0037886", "T_8_101")]["classification"] == "ambiguous"
    assert by_table[("reference_no_0037886", "T_9_108")]["classification"] == "ambiguous"


def test_v04_identifies_hidden_numeric_and_categorical_tables() -> None:
    report = _report()
    by_table = {
        (case["doc_id"], case["table_id"]): case
        for case in report["cases"]
    }

    electrochromic = by_table[("reference_no_0033617", "T_5_64")]
    assert electrochromic["survey_numeric_cell_count"] == 0
    assert electrochromic["eligible_modes"] == ["numeric"]
    assert electrochromic["shadow_status"] == "zero_output"

    solubility = by_table[("reference_no_0038813", "T_7_98")]
    assert solubility["eligible_modes"] == ["categorical"]
    assert solubility["survey_numeric_cell_count"] == 0


def test_fixture_case_remains_in_denominator_after_survey_warning_is_fixed() -> None:
    fixture = {
        "schema_version": "test",
        "cases": [{
            "doc_id": "reference_no_1",
            "table_id": "T_1",
            "classification": "eligible_property",
            "eligible_modes": ["numeric"],
            "target_families": ["glass_transition_temperature"],
            "reason": "reviewed",
        }],
    }
    survey = {
        "survey_schema_version": "test",
        "documents": [{
            "document_id": "reference_no_1",
            "tables": [{
                "table_id": "T_1",
                "caption": None,
                "direction": "row_samples",
                "numeric_cell_count": 1,
                "warnings": [],
            }],
        }],
    }
    shadow = {
        "shadow_version": "test",
        "documents": [{
            "document_id": "reference_no_1",
            "tables": [{"table_id": "T_1", "observations": [{"value_raw": "100"}]}],
        }],
    }

    report = audit_eligibility(fixture, survey, shadow)

    assert report["failure_count"] == 0
    assert report["summary"]["reviewed_table_count"] == 1
    assert report["summary"]["numeric_eligible_zero_output_table_count"] == 0


def test_audit_reports_candidate_semantic_and_publication_layers_separately() -> None:
    fixture = {
        "schema_version": "test",
        "cases": [{
            "doc_id": "reference_no_1",
            "table_id": "T_1",
            "classification": "eligible_property",
            "eligible_modes": ["numeric"],
            "target_families": ["glass_transition_temperature"],
            "reason": "reviewed",
        }],
    }
    survey = {
        "survey_schema_version": "test",
        "documents": [{
            "document_id": "reference_no_1",
            "tables": [{
                "table_id": "T_1",
                "caption": None,
                "direction": "row_samples",
                "numeric_cell_count": 2,
                "warnings": [],
            }],
        }],
    }
    shadow = {
        "shadow_version": "test",
        "documents": [{
            "document_id": "reference_no_1",
            "tables": [{
                "table_id": "T_1",
                "observations": [
                    {
                        "semantic_status": "unmapped",
                        "property_name_normalized": None,
                        "semantic_label": None,
                        "publication_gate": {"status": "candidate_only"},
                    },
                    {
                        "semantic_status": "normalized",
                        "property_name_normalized": "glass_transition_temperature",
                        "semantic_label": None,
                        "publication_gate": {"status": "eligible"},
                    },
                ],
            }],
        }],
    }

    report = audit_eligibility(fixture, survey, shadow, {"cases": []})
    summary = report["summary"]

    assert summary["tables_with_shadow_output"] == 1
    assert summary["tables_with_semantic_output"] == 1
    assert summary["tables_with_publication_eligible_output"] == 1
    assert summary["combined_numeric_table_output_coverage"] == 1.0
    assert summary["combined_numeric_semantic_output_coverage"] == 1.0
    assert summary["combined_numeric_publication_eligible_coverage"] == 1.0
