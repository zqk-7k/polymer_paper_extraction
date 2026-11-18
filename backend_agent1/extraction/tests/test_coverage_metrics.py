from schema.polymer_schema import CompletenessMetric, SeriesCoverage


def test_empty_series_coverage_is_zero_not_false_success() -> None:
    coverage = SeriesCoverage(
        expected=0,
        covered=0,
        missing=0,
        ratio=0.0,
    )

    assert coverage.ratio == 0.0


def test_empty_completeness_metric_is_zero_not_false_success() -> None:
    metric = CompletenessMetric(complete=0, total=0, ratio=0.0)

    assert metric.ratio == 0.0
