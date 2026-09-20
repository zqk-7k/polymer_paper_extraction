from stages.stage4_direct_table_supplement import (
    materialize, middle_dot_decimal_value, scalar, table_cell_scalar, inline_glass_peaks, footnoted_scalar,
)


def test_middle_dot_only_in_repeated_numeric_table_column():
    cells = {'a': {'text': '9·4', 'column_index': 2}, 'b': {'text': '9·6', 'column_index': 2}}
    assert middle_dot_decimal_value(cells['a'], cells) == 9.4
    assert middle_dot_decimal_value(cells['a'], {'a': cells['a']}) is None
    assert scalar('9·4') is None
    assert middle_dot_decimal_value({'text': '2·10^3', 'column_index': 2}, cells) is None


def test_em_dash_negative_is_not_missing_or_range():
    assert table_cell_scalar('—0.014') == -0.014
    assert table_cell_scalar('—') is None
    assert table_cell_scalar('1—5') is None
    assert table_cell_scalar('—-3') is None


def test_star_footnote_must_be_declared():
    assert footnoted_scalar('0.250*', '* Limiting viscosity in benzene.') == (0.25, '*')
    assert footnoted_scalar('0.250*', '') == (None, None)


def test_inline_peaks_reject_unlabelled_or_calculated_lists():
    peaks = inline_glass_peaks('$T_{g_1}=86.0$ $T_{g_2}=121.5$ $T_{g_3}=147.2$', 'glass transition temperature')
    assert [x['value'] for x in peaks] == [86, 121.5, 147.2]
    assert not inline_glass_peaks('86,121.5,147.2', 'glass transition temperature')
    assert not inline_glass_peaks('Tg1=86+2;Tg2=121', 'glass transition temperature')
    assert not inline_glass_peaks('Tg1=86;Tg1=121', 'glass transition temperature')


def test_same_cell_three_peaks_keep_physical_cell_and_peak_identity():
    table = {'table_id':'T', 'page':0, 'caption':'Thermal behaviour', 'cells':[
        {'cell_id':'a','row_index':1,'column_index':0,'text':'A'},
        {'cell_id':'h','row_index':0,'column_index':1,'text':'Tg (°C)'},
        {'cell_id':'v','row_index':1,'column_index':1,'text':'Tg1=86;Tg2=121.5;Tg3=147.2'}]}
    group = {'property_name_raw':'Tg (°C)', 'property_name_normalized':'glass transition temperature',
        'unit_raw':'°C','header_cell_ids':['h'],'points':[{'cell_id':'v','subject_cell_ids':['a']}]}
    result, _ = materialize(table, {'groups':[group]}, 1)
    assert len(result[0]['points']) == 3
    assert result[0]['points'][0]['sample_id'] is None
    assert 'table-local labels retained' in result[0]['points'][0]['measurement_context']['other_conditions']['source_subject_binding_scope']
    assert all(p['evidence'][0]['table_locator']['cell_id'] == 'v' for p in result[0]['points'])
    assert [p['measurement_context']['other_conditions']['source_peak_role'] for p in result[0]['points']] == ['Tg1','Tg2','Tg3']


def test_caption_property_requires_subject_and_condition_axes():
    table={'table_id':'T','page':0,'caption':'Refractive index increments of polymers', 'cells':[
        {'cell_id':'h','row_index':0,'column_index':0,'text':'solvent'},
        {'cell_id':'c','row_index':0,'column_index':1,'text':'benzene'},
        {'cell_id':'a','row_index':1,'column_index':0,'text':'A'},
        {'cell_id':'v','row_index':1,'column_index':1,'text':'—0.014'}]}
    group={'property_name_raw':'Refractive index increments','unit_raw':None,'header_cell_ids':['h'],
        'points':[{'cell_id':'v','subject_cell_ids':['a'],'condition_cell_ids':['c']}]}
    result,_=materialize(table,{'groups':[group]},1)
    assert result[0]['points'][0]['value_min']==-0.014
    group['points'][0]['condition_cell_ids']=[]
    assert not materialize(table,{'groups':[group]},1)[0]
    group['points'][0]['condition_cell_ids']=['c']; group['property_name_raw']='Glass transition temperatures'
    assert not materialize(table,{'groups':[group]},1)[0]
