import copy
from stages.stage4_direct_table_supplement import materialize, source_unit


def example():
    table = {'table_id': 'T1', 'page': 0, 'caption': 'X-Ray Reflections of Poly-Example', 'cells': [
        {'cell_id': 'h', 'row_index': 0, 'column_index': 0, 'text': 'd, A.'},
        {'cell_id': 'v', 'row_index': 1, 'column_index': 0, 'text': '9.9'},
        {'cell_id': 'c', 'row_index': 1, 'column_index': 1, 'text': '(200)'}]}
    group = {'property_name_raw': 'd, A.', 'property_name_normalized': 'lattice spacing',
        'unit_raw': 'A.', 'header_cell_ids': ['h'], 'points': [{'cell_id': 'v',
        'subject_cell_ids': [], 'condition_cell_ids': ['c'],
        'subject_caption_scope': 'single_material_table', 'subject_caption_quote': 'Poly-Example'}]}
    return table, group


def test_caption_subject_preserves_source_not_fake_sample_cell():
    t, g = example()
    result, audit = materialize(t, {'groups': [g]}, 1)
    p = result[0]['points'][0]
    assert p['value_min'] == 9.9 and p['unit_normalized'] == 'angstrom'
    assert p['sample_id'] is None and p['sample_resolution_status'] == 'unresolved'
    assert p['coordinates'][0]['value_raw'] == 'Poly-Example'
    assert not p['coordinates'][0]['evidence'].get('table_locator')
    assert p['coordinates'][1]['value_raw'] == '(200)'


def test_caption_quote_must_be_verbatim_and_explicitly_scoped():
    for updates in [{'subject_caption_quote': 'Another polymer'}, {'subject_caption_scope': ''},
                    {'subject_caption_quote': 'Polymer'}, {'subject_caption_quote': ''}]:
        t, g = example(); g['points'][0].update(updates)
        assert materialize(t, {'groups': [g]}, 1)[0] == []


def test_conflicting_caption_attributions_not_silently_picked():
    t, g = example(); t['caption'] += ' and Poly-Other'
    h = copy.deepcopy(g); h['points'][0]['subject_caption_quote'] = 'Poly-Other'
    assert materialize(t, {'groups': [g, h]}, 1)[0] == []


def test_ampere_not_globally_changed_to_length():
    assert source_unit('A', 'current (A)', 'Electrical properties') == 'A'
    assert source_unit('A', 'd, A.', 'Unspecified experiment') == 'A'
    assert source_unit('A.', 'd, A.', 'X-Ray Reflections of Poly-Example') == 'angstrom'


def test_one_inline_angle_does_not_authorize_unitless_other_point():
    t, g = example(); t['caption'] = 'Contact angles of Poly-Example'
    t['cells'][0]['text'] = 'Contact angle'; t['cells'][1]['text'] = '90°'
    t['cells'].append({'cell_id': 'v2', 'row_index': 2, 'column_index': 0, 'text': '80'})
    g.update(property_name_raw='Contact angle', property_name_normalized='Contact angle', unit_raw='degree')
    g['points'][0]['condition_cell_ids'] = []
    g['points'].append(dict(g['points'][0], cell_id='v2'))
    series, audit = materialize(t, {'groups': [g]}, 1)
    assert [p['value_min'] for p in series[0]['points']] == [90]
    assert any(x.get('reason') == 'unit_header_does_not_apply_to_response' for x in audit)


def test_frozen_identity_survives_downstream_unit_repair():
    from stages.stage4_direct_table_supplement import merge_supplement
    t, g = example()
    first, _ = merge_supplement({'property_series': []}, [(t, {'groups': [g]})])
    first['property_series'][0]['points'][0]['unit_normalized'] = 'angstrom'
    first['property_series'][0]['points'][0]['value_min'] = 9.90000000001
    second, audit = merge_supplement(first, [(t, {'groups': [g]})])
    assert sum(len(s['points']) for s in second['property_series']) == 1
    assert audit['tables'][0]['duplicate_points_skipped'] == 1
