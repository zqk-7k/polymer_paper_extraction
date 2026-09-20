from stages.stage4_direct_text_supplement import covered_text_facts


def test_source_local_hints_keep_property_and_quote_without_reference_answers():
    ev = {'block_id': 'P1', 'source_sentence': 'Polymer A has Tg 85 C.'}
    stage = {'properties': [{'property_name_raw': 'Tg', 'value_raw': '85', 'unit_raw': 'C', 'evidence': [ev]}],
             'property_series': [{'property_name_raw': 'Tg', 'points': [
                 {'value_raw': '85', 'unit_raw': 'C', 'evidence': [ev]},
                 {'value_raw': '90', 'evidence': [{'block_id': 'P2', 'source_sentence': 'B 90 C'}]}]}]}
    result = covered_text_facts(stage, {'P1'})
    assert len(result) == 1
    assert result[0]['source_quote'] == ev['source_sentence']
    assert result[0]['value_raw'] == '85'
    assert set(result[0]) == {'block_id', 'property_name', 'value_raw', 'unit_raw', 'source_quote'}


def test_no_source_sentence_is_not_a_verified_coverage_hint():
    stage = {'properties': [{'value_raw': '5', 'evidence': [{'block_id': 'P1'}]}]}
    assert covered_text_facts(stage, {'P1'}) == []
