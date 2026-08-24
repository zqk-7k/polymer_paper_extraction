import json
from pathlib import Path

from web_api.app import (
    _alignment_metrics,
    _candidate_completeness,
    _completeness_quality,
    _display_text,
    _polyinfo_properties,
    _read_collection_index,
    _select_batch_root,
)


def _write_index(root: Path, result_date: str, generated_at: str = "") -> None:
    root.mkdir(parents=True)
    (root / "RESULT_INDEX.json").write_text(
        json.dumps({"result_date": result_date, "generated_at": generated_at}),
        encoding="utf-8",
    )


def test_selects_newest_indexed_collection(tmp_path: Path) -> None:
    _write_index(tmp_path / "older", "2026-08-08")
    _write_index(tmp_path / "newer", "2026-08-09")

    root, index = _select_batch_root(tmp_path)

    assert root.name == "newer"
    assert index["result_date"] == "2026-08-09"


def test_explicit_collection_overrides_newest(tmp_path: Path) -> None:
    _write_index(tmp_path / "pinned", "2026-08-08")
    _write_index(tmp_path / "newer", "2026-08-09")

    root, _ = _select_batch_root(tmp_path, "pinned")

    assert root.name == "pinned"


def test_ignores_invalid_and_unsafe_collection_names(tmp_path: Path) -> None:
    (tmp_path / "invalid").mkdir()
    _write_index(tmp_path / "valid", "2026-08-09")

    root, _ = _select_batch_root(tmp_path, "../invalid")

    assert root.name == "valid"


def test_ignores_non_production_review_collection(tmp_path: Path) -> None:
    _write_index(tmp_path / "published", "2026-08-22")
    review = tmp_path / "review"
    review.mkdir()
    (review / "REVIEW_INDEX.json").write_text(
        json.dumps({"result_date": "2026-08-23", "production_eligible": False}),
        encoding="utf-8",
    )

    root, _ = _select_batch_root(tmp_path)

    assert root.name == "published"


def test_explicit_review_index_is_read_without_promoting_it_to_production(tmp_path: Path) -> None:
    review = tmp_path / "demo30"
    review.mkdir()
    (review / "REVIEW_INDEX.json").write_text(
        json.dumps({"result_date": "2026-08-24", "production_eligible": False}),
        encoding="utf-8",
    )

    hidden, hidden_kind = _read_collection_index(review)
    visible, visible_kind = _read_collection_index(review, include_review=True)

    assert hidden == {}
    assert hidden_kind == ""
    assert visible["result_date"] == "2026-08-24"
    assert visible_kind == "review"


def test_formats_nested_polyinfo_measurement_conditions_as_text() -> None:
    conditions = [
        {
            "solution_viscosity_measurement_condition": "Solvent",
            "solution_viscosity_measurement_condition_information": "DMF",
        },
        {
            "solution_viscosity_measurement_condition": "Concentration",
            "solution_viscosity_measurement_condition_information": "0.5 g/dL",
        },
    ]

    assert _display_text(conditions) == "Solvent: DMF; Concentration: 0.5 g/dL"


def test_polyinfo_property_api_never_returns_structured_method_or_condition() -> None:
    sample = {
        "sample_id": "sample-1",
        "polymer_id": "P000001",
        "property": [],
        "average_molecular_weight": [],
        "solution_viscosity": {
            "solution_viscosity_kind": "eta inh",
            "solution_viscosity_min": 1.2,
            "solution_viscosity_unit": "dL/g",
            "solution_viscosity_measurement_method": ["Ubbelohde viscometer"],
            "solution_viscosity_measurement_conditions": [
                {
                    "solution_viscosity_measurement_condition": "Temp.",
                    "solution_viscosity_measurement_condition_information": "25 C",
                }
            ],
        },
    }

    [property_record] = _polyinfo_properties([sample])

    assert property_record["method"] == "Ubbelohde viscometer"
    assert property_record["condition"] == "Temp.: 25 C"


def test_alignment_metrics_treat_value_conflicts_as_both_precision_and_recall_errors() -> None:
    metrics = _alignment_metrics({
        "matched": 8,
        "value_diff": 2,
        "polyinfo_only": 2,
        "extraction_only": 0,
    })

    assert metrics["precision"] == 0.8
    assert metrics["recall"] == round(8 / 12, 4)
    assert metrics["f1"] == round(2 * 0.8 * (8 / 12) / (0.8 + 8 / 12), 4)


def test_candidate_completeness_requires_valid_sample_and_evidence_links() -> None:
    candidate = {
        "samples": [{"sample_id": "s001"}],
        "evidence": [{"evidence_id": "ev001"}],
        "measurement_conditions": [{"condition_id": "mc002", "condition_status": "not_reported"}],
        "property_observations": [
            {
                "sample_id": "s001",
                "evidence_ids": ["ev001"],
                "unit_raw": "MPa",
                "measurement_condition_id": "mc001",
                "measurement_context": {"condition_status": "reported", "temperature": "25 C"},
            },
            {
                "sample_id": "missing",
                "evidence_ids": ["missing"],
                "measurement_condition_id": "mc002",
            },
        ],
    }

    assert _candidate_completeness(candidate) == {
        "properties": 2,
        "sample_bound": 1,
        "evidence_bound": 1,
        "unit_complete": 1,
        "condition_bound": 1,
    }


def test_completeness_quality_exposes_single_paper_coverage_rates() -> None:
    quality = _completeness_quality({
        "properties": 4,
        "sample_bound": 3,
        "evidence_bound": 4,
        "unit_complete": 2,
        "condition_bound": 1,
    })

    assert quality["sample_binding_coverage"] == 0.75
    assert quality["evidence_coverage"] == 1.0
    assert quality["unit_completeness"] == 0.5
    assert quality["condition_coverage"] == 0.25
