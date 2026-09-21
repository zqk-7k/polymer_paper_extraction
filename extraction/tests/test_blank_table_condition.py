from stages.stage4_direct_table_supplement import materialize

def test_blank_condition_not_invented_and_does_not_abort_valid_point():
    table={'table_id':'T_0_0','page':0,'caption':'','cells':[
        {'cell_id':'h','row_index':0,'column_index':1,'text':'Tg (°C)'},
        {'cell_id':'s','row_index':1,'column_index':0,'text':'Polymer A'},
        {'cell_id':'v','row_index':1,'column_index':1,'text':'85'},
        {'cell_id':'c','row_index':1,'column_index':2,'text':''}]}
    response={'groups':[{'property_name_raw':'Tg','property_name_normalized':'glass transition temperature',
        'unit_raw':'°C','header_cell_ids':['h'],'points':[{'cell_id':'v','subject_cell_ids':['s'],'condition_cell_ids':['c']}]}]}
    series,audit=materialize(table,response,1)
    assert len(series)==1 and series[0]['points'][0]['value_min']==85
    point=series[0]['points'][0]
    assert all(x['value_raw'] for x in point['coordinates'])
    assert point['measurement_context']['other_conditions']['source_blank_condition_cell_ids']=='["c"]'
    response['groups'][0]['points'][0]['condition_cell_ids']=['nonexistent']
    assert not materialize(table,response,1)[0]
