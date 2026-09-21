import copy

from stages.source_symbol_recovery import recover_symbol_definitions
from stages.stage4_symbol_condition_binding import bind_symbol_conditions, symbol_in_header
from schema.polymer_schema import MeasurementContext, Stage0Element


def fixture():
    definition = {'block_id': 'P_0_1', 'page': 0, 'type': 'text', 'bbox': None,
                  'text': 'temperatures for 2% gravimetric loss (Ti)'}
    cells = [dict(cell_id='T_0_2:r0000:c0001', row_index=0, column_index=1,
                  row_span=1, column_span=1, text='$T_{i}$ (°C)'),
             dict(cell_id='T_0_2:r0001:c0001', row_index=1, column_index=1,
                  row_span=1, column_span=1, text='229')]
    table = dict(block_id='T_0_2', type='table', page=0, table_cells=cells)
    record = dict(property_id='prop001', value_raw='229', value_min=None, value_max=None,
                  unit_normalized='°C', evidence=[dict(block_id='T_0_2', table_locator={
                      'table_id': 'T_0_2', 'cell_id': 'T_0_2:r0001:c0001'})])
    return {'elements': [definition, table]}, {'properties': [record]}


def test_pdf_recovery_keeps_original_and_is_idempotent():
    source = {'elements': [dict(block_id='P_0_1', type='text', page=0,
                               text='2% gravimetric loss (T )')]}
    pages = {0: 'temperatures for 2% gravimetric loss (Ti) of the polymers'}
    out, audit = recover_symbol_definitions(source, pages, 'sha')
    assert out['elements'][0] == source['elements'][0]
    assert audit['recovered'] == 1
    assert out['elements'][1]['text'] == '2% gravimetric loss (Ti)'
    Stage0Element.model_validate(out['elements'][1])
    again, audit = recover_symbol_definitions(out, pages, 'sha')
    assert again == out and audit['recovered'] == 0


def test_pdf_recovery_rejects_conflicting_symbols_and_wrong_page():
    source = {'elements': [dict(block_id='P_0_1', type='text', page=0, text='2% weight loss (T )')]}
    for pages in ({1: '2% weight loss (Ti)'}, {0: '2% weight loss (Ti), 2% weight loss (T2)'}):
        out, audit = recover_symbol_definitions(source, pages, 'sha')
        assert out == source and audit['recovered'] == 0


def test_symbol_binding_preserves_response_and_valid_context():
    source, stage4 = fixture()
    audit = bind_symbol_conditions(stage4, source)
    assert audit['unique_cells_bound'] == 1
    record = stage4['properties'][0]
    assert record['value_raw'] == '229' and record['value_min'] is None
    context = MeasurementContext.model_validate(record['measurement_context'])
    assert context.other_conditions['weight_loss_threshold_percent'] == '2'
    assert context.other_condition_evidence['weight_loss_threshold_percent'][0].table_locator is None
    assert bind_symbol_conditions(stage4, source)['unique_cells_bound'] == 0


def test_binds_both_ordinary_and_series():
    source, stage4 = fixture()
    point = copy.deepcopy(stage4['properties'][0]); point['point_id'] = 'pt001'
    stage4['property_series'] = [{'series_id': 'series001', 'points': [point]}]
    audit = bind_symbol_conditions(stage4, source)
    assert audit['unique_cells_bound'] == 1 and len(audit['decisions']) == 2


def test_no_inference_from_bare_t10_or_neighboring_loading_percent():
    source, stage4 = fixture()
    for text in ('2% filler loading (Ti)', 'Ti is initial decomposition temperature',
                 'not 2% gravimetric loss (Ti)', '10% weight loss (T2)'):
        source['elements'][0]['text'] = text
        assert bind_symbol_conditions(stage4, source)['unique_cells_bound'] == 0


def test_wrong_cell_value_unit_page_and_definition_conflict_rejected():
    for change in ('value', 'unit', 'cell', 'page', 'conflict'):
        source, stage4 = fixture()
        record = stage4['properties'][0]
        if change == 'value': record['value_raw'] = '228'
        if change == 'unit': record['unit_normalized'] = '%'
        if change == 'cell': record['evidence'][0]['table_locator']['cell_id'] = 'other'
        if change == 'page': source['elements'][0]['page'] = 1
        if change == 'conflict': source['elements'][0]['text'] += '; 5% weight loss (Ti)'
        assert bind_symbol_conditions(stage4, source)['unique_cells_bound'] == 0


def test_rejects_unrelated_and_accepts_tex_headers():
    assert symbol_in_header('$T_{i}$ (°C)') == 'ti'
    assert symbol_in_header('$T_{10}$ (°C)') == 't10'
    assert symbol_in_header('Tmax (°C)') is None
    assert symbol_in_header('at Ti (%)') is None


def test_explicit_own_header_criterion_uses_header_not_response_locator():
    source, stage4 = fixture()
    source['elements'] = source['elements'][1:]
    source['elements'][0]['table_cells'][0]['text'] = 'Td at 5 wt%Loss (°C)'
    audit = bind_symbol_conditions(stage4, source)
    assert audit['unique_cells_bound'] == 1
    context = stage4['properties'][0]['measurement_context']
    assert context['other_conditions']['weight_loss_threshold_percent'] == '5'
    loc = context['other_condition_evidence']['weight_loss_threshold_percent'][0]['table_locator']
    assert loc['cell_id'] == 'T_0_2:r0000:c0001'
    assert loc['cell_value'] == 'Td at 5 wt%Loss (°C)'
    MeasurementContext.model_validate(context)


def test_tga_header_requires_celsius_ancestor_and_not_mass_response():
    source, stage4 = fixture();source['elements'] = source['elements'][1:]
    header = source['elements'][0]['table_cells'][0]
    header['text'] = 'TGA-5%'
    assert bind_symbol_conditions(stage4, source)['unique_cells_bound'] == 0
    header['text'] = 'TGA-5% (°C)'
    stage4['properties'][0]['unit_normalized'] = '%'
    assert bind_symbol_conditions(stage4, source)['unique_cells_bound'] == 0


def test_explicit_t0_definition_overrides_no_numeric_guess():
    source, stage4 = fixture()
    source['elements'][0]['text'] = 'the 5% weight loss temperature ($T_{0}$)'
    source['elements'][1]['table_cells'][0]['text'] = '$T_0^a$ (°C)'
    assert bind_symbol_conditions(stage4, source)['unique_cells_bound'] == 1
    assert stage4['properties'][0]['measurement_context']['other_conditions']['weight_loss_threshold_percent'] == '5'
    source, stage4 = fixture()
    source['elements'][1]['table_cells'][0]['text'] = '$T_0^a$ (°C)'
    assert bind_symbol_conditions(stage4, source)['unique_cells_bound'] == 0


def test_split_header_preserves_criterion_and_parent_evidence():
    source, stage4 = fixture();source['elements']=source['elements'][1:]
    cells=source['elements'][0]['table_cells']
    cells[0]['text']='Temperature (°C) with following wt loss'
    cells[1]['row_index']=2
    cells.append(dict(cell_id='T_0_2:r0001:c0001',row_index=1,column_index=1,row_span=1,column_span=1,text='5%'))
    assert bind_symbol_conditions(stage4, source)['unique_cells_bound'] == 1
    ev=stage4['properties'][0]['measurement_context']['other_condition_evidence']['weight_loss_threshold_percent']
    assert len(ev)==2
    MeasurementContext.model_validate(stage4['properties'][0]['measurement_context'])
    for wrong in ['Temperature (°C) with filler loading','Residual wt % at 800°C']:
        copy4=fixture()[1]; cells[0]['text']=wrong
        assert bind_symbol_conditions(copy4, source)['unique_cells_bound'] == 0


def test_abbreviated_weight_loss_and_dotted_tga_headers():
    for text in ['temp of 10% wt loss (°C)','5 wt% t.g.a. $^d$ (°C)']:
        source, stage4=fixture();source['elements']=source['elements'][1:]
        source['elements'][0]['table_cells'][0]['text']=text
        assert bind_symbol_conditions(stage4,source)['unique_cells_bound']==1


def test_equal_temperatures_different_columns_never_cross_bind():
    source,stage4=fixture();source['elements']=source['elements'][1:]
    cells=source['elements'][0]['table_cells'];cells[0]['text']='5% weight loss (°C)'
    cells += [dict(cell_id='h2',row_index=0,column_index=2,row_span=1,column_span=1,text='10% weight loss (°C)'),
              dict(cell_id='v2',row_index=1,column_index=2,row_span=1,column_span=1,text='229')]
    other=copy.deepcopy(stage4['properties'][0]);other['property_id']='prop002'
    other['evidence'][0]['table_locator']['cell_id']='v2';stage4['properties'].append(other)
    assert bind_symbol_conditions(stage4,source)['unique_cells_bound']==2
    assert [r['measurement_context']['other_conditions']['weight_loss_threshold_percent'] for r in stage4['properties']]==['5','10']
    record=fixture()[1]['properties'][0]
    record['evidence'].append(copy.deepcopy(other['evidence'][0]))
    assert bind_symbol_conditions({'properties':[record]},source)['unique_cells_bound']==0
    record['evidence'][0]['table_locator']['cell_id']='unrelated_same_value'
    record['evidence']=record['evidence'][:1]
    assert bind_symbol_conditions({'properties':[record]},source)['unique_cells_bound']==0


def test_symbol_unit_separate_header_child():
    source,stage4=fixture();source['elements'][0]['text']='10% weight loss (T10)'
    cells=source['elements'][1]['table_cells'];cells[0]['text']='$T10^b$';cells[1]['row_index']=2
    cells.append(dict(cell_id='unit',row_index=1,column_index=1,row_span=1,column_span=1,text='°C'))
    assert bind_symbol_conditions(stage4,source)['unique_cells_bound']==1
