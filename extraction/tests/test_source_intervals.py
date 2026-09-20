from stages.source_intervals import reported_interval


def test_range_is_one_observation_and_preserves_sign():
    assert reported_interval('−17–−12')=={'minimum':-17.,'maximum':-12.,'kind':'range','inequality':None}
    assert reported_interval('2e-4 to 3e-4')['maximum']==3e-4


def test_bound_remains_bound():
    assert reported_interval('>40')['inequality']=='>'
    assert reported_interval('≤0.01')['inequality']=='<='


def test_no_arithmetic_or_guessing():
    for raw in ['3-4','5, 7','3/4','50+20','20–10','3 ± 1','—','about 40']:
        assert reported_interval(raw) is None
