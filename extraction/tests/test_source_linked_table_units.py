import copy
from stages.source_linked_table_units import resolve_linked_table_units
from stages.stage4_direct_text_supplement import scalar_is_range_endpoint, scalar_is_inequality_bound, merge_text


def fixture():
    cells = [dict(cell_id='t:h1', row_index=0, column_index=0, text='d'),
             dict(cell_id='t:h2', row_index=0, column_index=1, text='I/I0'),
             dict(cell_id='t:a', row_index=1, column_index=0, text='7.86'),
             dict(cell_id='t:b', row_index=2, column_index=0, text='4.02'),
             dict(cell_id='t:c', row_index=1, column_index=1, text='100')]
    doc = {'elements': [dict(block_id='t', type='table', page=2, caption='Table IV. WAXD results', table_cells=cells),
                        dict(block_id='p', type='text', page=2, text='Table IV lists peaks; d = 7 . 8 6 Å for polymer A.')]}
    points = [dict(point_id=str(i), value_raw=raw, value_min=float(raw), value_max=float(raw),
                   evidence=[{'block_id': 't', 'table_locator': {'cell_id': cell}}])
              for i, (cell, raw) in enumerate([('t:a', '7.86'), ('t:b', '4.02'), ('t:c', '100')])]
    stage = {'property_series': [dict(series_id='s', points=points)]}
    return stage, doc


def test_resolves_only_d_cells_preserving_values_and_raw_units():
    stage, doc = fixture()
    before = copy.deepcopy(stage)
    audit = resolve_linked_table_units(stage, doc)
    assert len(audit['changes']) == 2
    for i in (0, 1):
        point = stage['property_series'][0]['points'][i]
        assert point['unit_normalized'] == 'angstrom'
        assert point['value_raw'] == before['property_series'][0]['points'][i]['value_raw']
        assert not point.get('unit_raw')
    assert 'unit_normalized' not in stage['property_series'][0]['points'][2]
    assert resolve_linked_table_units(stage, doc)['changes'] == []


def test_requires_same_table_same_page_and_matching_assignment():
    for field, changed in [('text', 'Table V has d = 7.86 Å.'),
                           ('text', 'Table IV has d = 99 Å.'),
                           ('text', 'Table IV has d = 7.86 nm.'),
                           ('page', 3)]:
        stage, doc = fixture()
        doc['elements'][1][field] = changed
        assert resolve_linked_table_units(stage, doc)['changes'] == []


def test_does_not_override_reported_units_or_wrong_source_value():
    stage, doc = fixture()
    stage['property_series'][0]['points'][0]['unit_raw'] = 'nm'
    stage['property_series'][0]['points'][1]['value_raw'] = '4.68'
    assert resolve_linked_table_units(stage, doc)['changes'] == []


def test_range_endpoints_are_not_measured_scalars():
    for quote, raw in [('spacing 3–4 Å', '4'), ('temperature 200–500 C', '200'),
                       ('ranged from 30 to 40%', '40'), ('Tg -80--60 C', '-60')]:
        assert scalar_is_range_endpoint(quote, raw)
    for quote, raw in [('Tg -68 C', '-68'), ('values 3, 4 and 5 Å', '4')]:
        assert not scalar_is_range_endpoint(quote, raw)
    doc = {'elements': [{'block_id': 'p', 'type': 'text', 'page': 0, 'text': 'Polymer A has spacing 3–4 Å.'}]}
    fact = dict(block_id='p', quote=doc['elements'][0]['text'], property_name='d-spacing', value_raw='4',
                unit_raw='Å', sample_label='Polymer A', sample_evidence_block_id='p', role='material_property')
    out, audit = merge_text({}, doc, [{'facts': [fact]}])
    assert not out['property_series']
    assert audit['decisions'][0]['reason'] == 'range_endpoint_is_not_a_scalar_observation'


def test_bound_is_not_an_exact_scalar_but_approximate_value_is_allowed():
    for quote, raw in [('cooled >500 C/min', '500'), ('greater than 50 wt%', '50'),
                       ('12時間以上かくはん', '12'), ('at least 3 h', '3')]:
        assert scalar_is_inequality_bound(quote, raw)
    assert not scalar_is_inequality_bound('about 80 minutes', '80')
    assert not scalar_is_inequality_bound('Tg above 200 C, heating at 10 C/min', '10')
