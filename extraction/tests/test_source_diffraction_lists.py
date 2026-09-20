from stages import source_diffraction_lists as m


def table():
    return {'table_id':'T','page':0,'caption':'X-ray diffraction data','cells':[
        dict(cell_id='sh',row_index=0,column_index=0,text='Polymer PU_i'),
        dict(cell_id='h',row_index=0,column_index=1,text='d (Å)a'),
        dict(cell_id='s',row_index=1,column_index=0,text='1'),
        dict(cell_id='v',row_index=1,column_index=1,text='10,199; 4.861; 4.610; 3.577; 3.172')]}


def test_literal_list_components_not_arithmetic_or_decimal_guess():
    good,pending=m.spacing_components('10,199; 4.861; 4.610; 3.577; 3.172')
    assert [x[2] for x in good]==[4.861,4.610,3.577,3.172]
    assert pending[0]['raw']=='10,199'
    for text in ['3/4','3-4','3,4','3+4; 6*7','-3; 0']:
        assert not m.spacing_components(text)[0]


def test_spacing_unit_source_row_and_idempotence(monkeypatch):
    t=table();monkeypatch.setattr(m,'table_requests',lambda _:[t])
    out,a=m.recover_diffraction_lists({},{});assert a['new_points']==4
    assert all(p['evidence'][0]['table_locator']['cell_id']=='v' for p in out['property_series'][0]['points'])
    assert m.recover_diffraction_lists(out,{})[0]==out
    t['cells'][1]['text']='d (nm)'
    assert not m.recover_diffraction_lists({},{})[0]['property_series']
    t['cells'][1]['text']='d (Å)a';t['cells'][0]['text']='Index'
    assert not m.recover_diffraction_lists({},{})[0]['property_series']


def test_pending_and_multiplicity_visible_in_series_not_only_audit(monkeypatch):
    t=table();t['cells'][-1]['text']='10,199; 4.861; 4.861'
    monkeypatch.setattr(m,'table_requests',lambda _:[t])
    out,a=m.recover_diffraction_lists({},{});s=out['property_series'][0]
    assert len(s['points'])==1  # one numerical observation, multiplicity retained
    assert s['points'][0]['measurement_context']['other_conditions']['source_list_equal_value_occurrences']=='2'
    assert '10,199' in s['measurement_context']['other_conditions']['source_list_unresolved_tokens']
    assert '10,199' in s['points'][0]['measurement_context']['other_conditions']['full_source_cell']


def test_existing_ordinary_value_and_header_ambiguity(monkeypatch):
    t=table();monkeypatch.setattr(m,'table_requests',lambda _:[t])
    prior={'properties':[{'value_min':4.861,'unit_raw':'Å','evidence':[{'table_locator':{'cell_id':'v'}}]}]}
    out,a=m.recover_diffraction_lists(prior,{})
    assert a['new_points']==3 and out['properties']==prior['properties']
    t['cells'][1]['text']='d (A)a'
    assert not m.recover_diffraction_lists({},{})[0]['property_series']
    t['cells'][1]['text']='d (Å)a'
    t['cells'].append(dict(t['cells'][1],cell_id='h2'))
    assert not m.recover_diffraction_lists({},{})[0]['property_series']


def test_equal_values_in_different_sample_rows_are_not_collapsed(monkeypatch):
    t=table();t['cells'][-1]['text']='3.1; 4.2'
    t['cells'] += [dict(cell_id='s2',row_index=2,column_index=0,text='2'),
                   dict(cell_id='v2',row_index=2,column_index=1,text='3.1; 4.2')]
    monkeypatch.setattr(m,'table_requests',lambda _:[t])
    out,a=m.recover_diffraction_lists({},{});assert a['new_points']==4
    assert {p['evidence'][0]['table_locator']['cell_id'] for s in out['property_series'] for p in s['points']}=={'v','v2'}
