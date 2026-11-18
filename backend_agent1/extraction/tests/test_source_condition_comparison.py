from copy import deepcopy

import pytest

from stages.source_condition_comparison import compare_source_conditions


def context(value="8.1", status="source_aligned"):
    return {"condition_axes": [{"name": "Dose/kGy", "value_raw": value,
        "cell_id": "T:r1:c1", "header_cell_ids": ["T:r0:c1"],
        "header_path": ["Dose/kGy"], "association_status": status}], "composition_axes": []}


@pytest.mark.parametrize("declaration", ["8.1 kGy", "8100 Gy", "8.1e3 Gy",
    {"value": 8100, "unit": "Gy"}, {"raw": "8.1 kGy", "value": 8.1, "unit": "kGy"}])
def test_explicit_doses_match_after_exact_unit_conversion(declaration):
    source, candidate = context(), {"measurement_context": {"other_conditions": {"irradiation_dose": declaration}}}
    before = deepcopy((source, candidate))
    result = compare_source_conditions(source, candidate)
    assert result["status"] == "matched"
    assert result["axes"][0]["numeric_comparison"] == "equal"
    assert result["axes"][0]["source_normalized"]["factor_to_gy"] == "1000"
    assert (source, candidate) == before
    assert not result["updates_model_context"] and not result["changes_publication_status"]


@pytest.mark.parametrize("value", ["8.1", "8.1 MGy", "8.1 kGy/h", "8–9 kGy", "8.1 ± 0.1 kGy", "about 8.1 kGy", True,
    {"raw": "8.1 kGy", "value": 9, "unit": "kGy"}, {"value": 8.1, "unit": "kGy", "approximate": True}])
def test_missing_unit_ranges_rates_qualifiers_and_internal_conflicts_require_review(value):
    result = compare_source_conditions(context(), {"conditions": {"dose": value}})
    assert result["status"] == "needs_review"
    assert result["axes"][0]["numeric_comparison"] == "not_available"


def test_numeric_difference_is_conflict_only_with_source_aligned_axis():
    candidate = {"conditions": {"dose": "9 kGy"}}
    assert compare_source_conditions(context(), candidate)["status"] == "conflict"
    inferred = compare_source_conditions(context(status="candidate"), candidate)
    assert inferred["status"] == "needs_review"
    assert inferred["axes"][0]["numeric_comparison"] == "different"
    equal = compare_source_conditions(context(status="candidate"), {"conditions": {"dose": "8100 Gy"}})
    assert equal["status"] == "needs_review"
    assert equal["axes"][0]["numeric_comparison"] == "equal"


def test_missing_is_distinct_from_zero_and_not_applicable():
    assert compare_source_conditions(context("0"), {})["status"] == "declaration_missing"
    assert compare_source_conditions(context("0"), {"conditions": {"dose": "0 Gy"}})["status"] == "matched"
    result = compare_source_conditions(context("N/A"), {})
    assert result["status"] == "needs_review"
    assert result["axes"][0]["source_normalized"] is None
    assert compare_source_conditions(context(), {"conditions": {"dose": 0}})["status"] == "needs_review"


def test_unstructured_prose_is_not_reported_as_proven_absence():
    result = compare_source_conditions(context(), {"measurement_context": {"other_conditions": "dose is 8.1 kGy"}})
    assert result["status"] == "needs_review"
    assert "unstructured_conditions_not_compared" in result["axes"][0]["reasons"]


def test_ambiguous_source_and_multiple_dose_axes_are_not_arbitrarily_selected():
    candidate = {"conditions": {"dose": "8.1 kGy"}}
    assert compare_source_conditions(context(status="ambiguous"), candidate)["status"] == "needs_review"
    source = context()
    source["condition_axes"].append({**deepcopy(source["condition_axes"][0]), "value_raw": "9", "cell_id": "T:r2:c1"})
    result = compare_source_conditions(source, candidate)
    assert all(r["numeric_comparison"] == "not_available" for r in result["axes"])


def test_conflicting_declared_fields_cannot_hide_behind_one_matching_value():
    candidate = {"conditions": {"dose": "9 kGy"}, "measurement_context": {"dose": "8100 Gy"}}
    result = compare_source_conditions(context(), candidate)
    assert result["status"] == "conflict"
    assert "declared_doses_disagree" in result["axes"][0]["reasons"]
    assert len(result["axes"][0]["declarations"]) == 2


def test_separate_unit_header_is_kept_and_conflicting_or_scaled_headers_are_not_guessed():
    source = context()
    axis = source["condition_axes"][0]
    axis.update(name="Dose", header_path=["Dose", "kGy"], header_cell_ids=["h1", "h2"])
    candidate = {"conditions": {"dose": "8100 Gy"}}
    assert compare_source_conditions(source, candidate)["status"] == "matched"
    for path in (["Dose/kGy", "Gy"], ["Dose/kGy", "×10^3"], ["Dose"]):
        axis["header_path"] = path
        assert compare_source_conditions(source, candidate)["status"] == "needs_review"


def test_other_conditions_and_long_decimals_cannot_false_match():
    source = context()
    source["condition_axes"][0]["name"] = "Temperature"
    assert compare_source_conditions(source, {"conditions": {"dose": "8100 Gy"}})["status"] == "needs_review"
    source = context("8.123456789012345678901234567891")
    result = compare_source_conditions(source, {"conditions": {"dose": "8.123456789012345678901234567892 kGy"}})
    assert result["status"] == "conflict"
