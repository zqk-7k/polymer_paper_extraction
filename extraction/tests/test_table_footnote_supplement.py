import copy

import pytest

from stages.stage4_direct_text_supplement import merge_text
from stages.stage4_table_footnote_supplement import table_footnote_facts


def document(note=r'<sup>a)</sup> Only the melting point $\mathrm { a t } - 1 7 ^ { \circ } \mathrm { C }$could be detected.'):
    cells = []
    for row, values in enumerate([['Polymer', 'Tg'], ['A', '84'], ['B', '-a)']]):
        for column, value in enumerate(values):
            cells.append({'cell_id': f't:r{row:04}:c{column:04}', 'row_index': row,
                          'column_index': column, 'row_span': 1, 'column_span': 1, 'text': value})
    return {'elements': [{'block_id': 't', 'type': 'table', 'page': 2, 'table_cells': cells},
                         {'block_id': 'n', 'type': 'text', 'page': 2, 'text': note}]}


def test_footnote_recovers_negative_melting_point_not_column_tg():
    result, audit = merge_text({}, document(), [])
    assert audit['decisions'][0]['reason'] == 'unique_table_footnote'
    series = result['property_series'][0]
    point = series['points'][0]
    assert series['property_name_normalized'] == 'melting temperature'
    assert point['value_min'] == point['value_max'] == -17
    assert point['unit_normalized'] == '°C'
    assert point['sample_id'] is None
    assert point['coordinates'][0]['value_raw'] == 'B'
    assert point['coordinates'][0]['evidence']['table_locator']['cell_id'] == 't:r0002:c0000'
    assert point['evidence'][0]['block_id'] == 'n'
    assert not point['evidence'][0].get('table_locator')
    assert point['measurement_context']['other_conditions']['marker_cell_id'] == 't:r0002:c0001'
    assert point['measurement_context']['other_conditions']['reported_origin'] == 'not_specified'


def test_footnote_replay_is_idempotent_and_does_not_mutate_input():
    doc = document()
    before = copy.deepcopy(doc)
    one, _ = merge_text({}, doc, [])
    two, audit = merge_text(one, doc, [])
    assert len(one['property_series']) == len(two['property_series']) == 1
    assert audit['decisions'][0]['reason'] == 'duplicate_same_source_fact'
    assert doc == before


def test_ambiguous_marker_cannot_copy_value_to_multiple_rows():
    doc = document()
    doc['elements'][0]['table_cells'][3]['text'] = '-a)'
    assert table_footnote_facts(doc) == []


@pytest.mark.parametrize('note', [
    'a) Only a transition at -17 °C could be detected.',
    'a) The melting point was -17.',
    'a) The melting point was between -17 and 24 °C.',
    'a) The melting point was calculated at -17 °C.',
    'a) The melting point was not detected at -17 °C.',
    'a) The melting point was -17 °C and Tg was -35 °C.',
    'a) The melting point was 1 7 °C.',
    'a) The melting point was below -17 °C.',
])
def test_missing_or_ambiguous_property_value_is_not_recovered(note):
    assert table_footnote_facts(document(note)) == []


def test_different_page_or_intervening_prose_breaks_association():
    doc = document()
    doc['elements'][1]['page'] = 3
    assert table_footnote_facts(doc) == []
    doc = document()
    doc['elements'].insert(1, {'block_id': 'p', 'type': 'text', 'page': 2, 'text': 'New unrelated paragraph.'})
    assert table_footnote_facts(doc) == []


def test_unknown_first_column_does_not_become_sample_label():
    doc = document()
    doc['elements'][0]['table_cells'][0]['text'] = 'Reaction time'
    assert table_footnote_facts(doc) == []


def test_external_model_cannot_claim_verified_table_binding():
    doc = document()
    fact, binding = table_footnote_facts(doc)[0]
    doc['elements'][0]['table_cells'][3]['text'] = '-a)'  # Break the unique marker.
    fact['footnote_binding'] = binding
    result, audit = merge_text({}, doc, [{'facts': [fact]}])
    assert result['property_series'] == []
    assert audit['decisions'][0]['reason'] == 'sample_label_not_in_source'


def test_plain_positive_temperature_is_allowed_with_explicit_source_label():
    result, _ = merge_text({}, document('a) The glass transition temperature was 48.5 °C.'), [])
    assert result['property_series'][0]['property_name_normalized'] == 'glass transition temperature'
    assert result['property_series'][0]['points'][0]['value_min'] == 48.5
