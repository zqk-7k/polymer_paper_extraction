import copy
from stages.stage4_direct_table_supplement import merge_supplement, source_point_identity


def fixture():
    table = {'table_id': 'T1', 'page': 0, 'caption': 'Measured properties', 'cells': [
        {'cell_id': 'h', 'row_index': 0, 'column_index': 1, 'text': 'Tg (°C)'},
        {'cell_id': 'a', 'row_index': 1, 'column_index': 0, 'text': 'A'},
        {'cell_id': 'v', 'row_index': 1, 'column_index': 1, 'text': '85'},
        {'cell_id': 'b', 'row_index': 2, 'column_index': 0, 'text': 'B'},
        {'cell_id': 'w', 'row_index': 2, 'column_index': 1, 'text': '85'}]}
    response = {'groups': [{'property_name_raw': 'Tg', 'property_name_normalized': 'glass transition temperature',
        'unit_raw': '°C', 'header_cell_ids': ['h'],
        'points': [{'cell_id': 'v', 'subject_cell_ids': ['a']}, {'cell_id': 'w', 'subject_cell_ids': ['b']}]}]}
    return table, response


def test_identical_replay_retains_two_distinct_samples_but_adds_no_duplicate():
    table, response = fixture()
    first, audit1 = merge_supplement({'property_series': []}, [(table, response)])
    second, audit2 = merge_supplement(first, [(table, response)])
    assert first == second
    assert len(second['property_series'][0]['points']) == 2
    assert audit1['tables'][0]['points_added'] == 2
    assert audit2['tables'][0]['points_added'] == 0
    assert audit2['tables'][0]['duplicate_points_skipped'] == 2
    assert not any(d['accepted'] for d in audit2['tables'][0]['decisions'])


def test_replay_never_removes_or_rewrites_existing_enriched_evidence():
    table, response = fixture()
    first, _ = merge_supplement({'property_series': []}, [(table, response)])
    first['property_series'][0]['points'][0]['measurement_context']['other_conditions']['verified_method'] = 'DSC'
    before = copy.deepcopy(first)
    second, _ = merge_supplement(first, [(table, response)])
    assert second == before
    assert first == before


def test_changed_value_interpretation_is_not_silently_deduplicated():
    table, response = fixture()
    first, _ = merge_supplement({'property_series': []}, [(table, response)])
    series = first['property_series'][0]
    point = series['points'][0]
    altered = copy.deepcopy(point); altered['value_max'] = 90
    altered['measurement_context']['other_conditions'].pop('source_supplement_identity_v1')
    assert source_point_identity(series, point) != source_point_identity(series, altered)
    altered = copy.deepcopy(point)
    altered['measurement_context']['other_conditions'].pop('source_supplement_identity_v1')
    altered['measurement_context']['other_conditions']['source_peak_role'] = 'secondary'
    assert source_point_identity(series, point) != source_point_identity(series, altered)


def test_downstream_unit_resolution_preserves_frozen_source_identity():
    table, response = fixture()
    first, _ = merge_supplement({'property_series': []}, [(table, response)])
    point = first['property_series'][0]['points'][0]
    point.update(value_min=358.15, value_max=358.15, unit_normalized='K')
    second, audit = merge_supplement(first, [(table, response)])
    assert first == second
    assert audit['tables'][0]['points_added'] == 0


def test_no_responses_does_not_claim_supplement_added():
    original = {'property_series': []}
    result, audit = merge_supplement(original, [])
    assert result == original
    assert audit['tables'] == []
