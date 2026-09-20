from stages.stage4_direct_table_supplement import inline_contact_angle, materialize


def test_angle_degree_symbol_is_not_temperature_or_exponent():
    f=lambda s:inline_contact_angle(s,'static contact angle','Contact angles of brushes')
    assert f('$145^{\\circ}$')['minimum']==145
    assert f('$41^{°c)}$')['marker']=='c)'
    assert f('$<5^{\\circ}$')['inequality']=='<'
    assert f('$1 \\sim 3^{\\circ}$')['maximum']==3
    for bad in ['145','145°C','2^7°','41+2°','200°','-5°']:
        assert f(bad) is None
    assert inline_contact_angle('90°','temperature','Contact angles') is None


def test_inline_degrees_can_supply_missing_heading_unit_per_point():
    table={'table_id':'T','page':0,'caption':'Contact angles of brushes','cells':[
        {'cell_id':'s','row_index':0,'column_index':1,'text':'Polymer A'},
        {'cell_id':'h','row_index':1,'column_index':0,'text':'Water (static)'},
        {'cell_id':'v','row_index':1,'column_index':1,'text':'$145^{\\circ}$'}]}
    group={'property_name_raw':'Water (static)','property_name_normalized':'Static water contact angle',
           'unit_raw':'°','header_cell_ids':['h'],'points':[{'cell_id':'v','subject_cell_ids':['s'],'condition_cell_ids':['h']}]}
    out,_=materialize(table,{'groups':[group]},1)
    point=out[0]['points'][0]
    assert point['value_raw']=='145' and point['unit_normalized']=='degree'
    assert point['evidence'][0]['table_locator']['cell_value']=='$145^{\\circ}$'
    table['cells'][-1]['text']='145'
    assert not materialize(table,{'groups':[group]},1)[0]


def test_one_inline_angle_does_not_release_neighbor_without_unit():
    table={'table_id':'T','page':0,'caption':'Contact angles of brushes','cells':[
        {'cell_id':'s','row_index':0,'column_index':1,'text':'Polymer A'},
        {'cell_id':'h','row_index':1,'column_index':0,'text':'Water (static)'},
        {'cell_id':'v','row_index':1,'column_index':1,'text':'145°'},
        {'cell_id':'s2','row_index':0,'column_index':2,'text':'Polymer B'},
        {'cell_id':'v2','row_index':1,'column_index':2,'text':'120'}]}
    group={'property_name_raw':'Water (static)','property_name_normalized':'Static water contact angle',
           'unit_raw':'°','header_cell_ids':['h'],'points':[
               {'cell_id':'v','subject_cell_ids':['s'],'condition_cell_ids':['h']},
               {'cell_id':'v2','subject_cell_ids':['s2'],'condition_cell_ids':['h']}]}
    out,audit=materialize(table,{'groups':[group]},1)
    assert sum(len(s['points']) for s in out)==1
    assert any(r.get('reason')=='unit_header_does_not_apply_to_response' for r in audit)


def test_short_units_do_not_match_ordinary_words():
    from stages.stage4_direct_table_supplement import unit_in_header
    for unit,heading in [('g','Tg of polymers'),('s','tensile stress'),('Pa','Parameter')]:
        assert not unit_in_header(unit,heading)
