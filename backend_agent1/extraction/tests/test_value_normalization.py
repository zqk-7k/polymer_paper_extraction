from stages.value_normalization import normalize_observation


def test_scale_factor_restores_scalar_without_overwriting_raw_value() -> None:
    result = normalize_observation({
        "value_kind": "numeric_scalar",
        "value_raw": "2.6",
        "unit_raw": "S/cm",
        "unit_normalized": "S/cm",
        "scale_factor_exponent": -12,
    })

    assert result["value_raw"] == "2.6"
    assert result["restored_value"] == 2.6e-12
    assert result["normalized_value"] == 2.6e-12
    assert result["normalized_unit"] == "S/cm"
    assert result["normalization_status"] == "normalized"


def test_range_preserves_polyinfo_engineering_unit() -> None:
    result = normalize_observation({
        "value_kind": "numeric_range",
        "value_raw": "2–4",
        "unit_raw": "MPa",
    })

    assert result["normalized_unit"] == "MPa"
    assert result["normalized_value_min"] == 2.0
    assert result["normalized_value_max"] == 4.0
    assert result["normalization_status"] == "normalized"


def test_uncertainty_and_non_numeric_are_handled_without_false_warning() -> None:
    uncertainty = normalize_observation({
        "value_kind": "numeric_with_uncertainty",
        "value_raw": "4.2 ± 0.1",
        "unit_raw": "°C",
    })
    text = normalize_observation({
        "value_kind": "categorical",
        "value_raw": "amorphous",
    })

    assert uncertainty["normalized_value"] == 4.2
    assert uncertainty["normalized_uncertainty"] == 0.1
    assert uncertainty["normalization_status"] == "normalized"
    assert text["normalization_status"] == "skipped_non_numeric"
    assert "normalization_warning" not in text


def test_grouped_thousands_are_not_split_before_parsing() -> None:
    grouped = normalize_observation({
        "value_kind": "numeric_scalar",
        "value_raw": "67,500",
        "unit_raw": "g/mol",
    })
    spaced = normalize_observation({
        "value_kind": "numeric_scalar",
        "value_raw": "3 950",
        "unit_raw": "g/mol",
    })

    assert grouped["normalized_value"] == 67500.0
    assert spaced["normalized_value"] == 3950.0


def test_multiple_values_respect_explicit_list_instead_of_guessing_thousands() -> None:
    result = normalize_observation({
        "value_kind": "numeric_multiple",
        "value_raw": "67,500, 3 950, 42",
        "unit_raw": "g/mol",
    })

    assert result["normalized_values"] == [67.0, 500.0, 3950.0, 42.0]
    assert result["normalization_status"] == "normalized"


def test_unparseable_numeric_candidate_is_not_fabricated_as_zero() -> None:
    result = normalize_observation({
        "value_kind": "numeric_scalar",
        "value_raw": "not reported",
        "unit_raw": "MPa",
    })

    assert result["normalization_status"] == "warning"
    assert result["normalization_warning"] == "value_not_numeric"
    assert "normalized_value" not in result


def test_scientific_negative_exponent_is_not_a_range() -> None:
    result = normalize_observation({"value_raw": "3.65e-12", "unit_raw": "S/cm"})
    assert result["normalized_value"] == 3.65e-12
    assert "normalized_value_min" not in result


def test_annotated_range_and_zero_are_retained() -> None:
    result = normalize_observation({"value_raw": "227–393 (peaks)", "value_kind": "numeric_range"})
    assert result["normalized_values"] == [227, 393]
    assert normalize_observation({"value_raw": 0})["normalized_value"] == 0


def test_label_digits_and_trailing_prose_are_not_numeric_values() -> None:
    for value in ("P-12", "sample 123", "4.2 for sample A"):
        result = normalize_observation({"value_raw": value, "value_kind": "numeric_scalar"})
        assert "normalized_value" not in result


def test_renormalization_clears_stale_results_and_invalid_scale_is_not_ignored() -> None:
    first = normalize_observation({"value_raw": "2–4", "value_kind": "numeric_range"})
    invalid = normalize_observation({**first, "value_raw": "unavailable"})
    assert not any(key in invalid for key in ("normalized_value", "normalized_value_min", "normalized_value_max"))
    for scale in ("unknown", 0.5, 10000):
        result = normalize_observation({"value_raw": "3.6", "scale_factor_exponent": scale})
        assert result["normalization_warning"] == "invalid_header_scale"
        assert "normalized_value" not in result


def test_reapplication_is_idempotent_and_does_not_double_scale() -> None:
    first = normalize_observation({"value_raw": "3.6", "scale_factor_exponent": 4})
    assert first["normalized_value"] == 36000
    assert normalize_observation(first) == first
    second = normalize_observation({"value_raw": "3.6e4", "scale_factor_exponent": 4})
    assert second["normalization_warning"] == "scale_provenance_requires_review"
