import copy
from stages.source_crystallinity_fraction import normalize_crystallinity_fractions, fraction_definitions
from schema.polymer_schema import MeasurementContext


def fixture():
    equation = dict(block_id='E_0_1', type='equation', page=0,
        text=r'$$X_{\mathrm{C,A}}=\Delta H_{\text{blend,A}}^{*}/\Delta H_{\mathrm{A}}^{\circ}\tag{4}$$')
    note = dict(block_id='P_0_2', type='text', page=0,
        text='the heat of melting per gram of 100% crystalline A')
    table = dict(block_id='T_1_3', type='table', page=1, caption='Experimental crystallinities', table_cells=[
        dict(cell_id='h', text='$X_{C,A}$ (exp)', row_index=0, column_index=1),
        dict(cell_id='v', text='0.3704', row_index=1, column_index=1)])
    point = dict(point_id='pt001', value_raw='0.3704', value_min=0.3704, value_max=0.3704,
        unit_raw=None, evidence=[dict(block_id='T_1_3', table_locator={'cell_id': 'v', 'table_id': 'T_1_3'})])
    stage4 = dict(property_series=[dict(series_id='series001', property_name_normalized='crystallinity', points=[point])])
    return dict(elements=[equation, note, table]), stage4


def test_fraction_is_display_conversion_not_new_measurement():
    source, stage4 = fixture()
    assert fraction_definitions(source)
    audit = normalize_crystallinity_fractions(stage4, source)
    assert audit['unique_cells'] == 1
    point = stage4['property_series'][0]['points'][0]
    assert point['value_raw'] == '0.3704' and point['unit_raw'] is None
    assert point['value_min'] == 37.04 and point['unit_normalized'] == '%'
    MeasurementContext.model_validate(point['measurement_context'])
    assert normalize_crystallinity_fractions(stage4, source)['unique_cells'] == 0


def test_no_assumption_based_on_value_less_than_one():
    source, stage4 = fixture();source['elements'] = source['elements'][1:]
    assert normalize_crystallinity_fractions(stage4, source)['unique_cells'] == 0


def test_reject_calculated_normalized_percent_and_different_symbol():
    for kind in ('calculated', 'normalized', 'percent', 'symbol', 'page', 'multiplier', 'nonfraction'):
        source, stage4 = fixture()
        table = source['elements'][-1]
        if kind == 'calculated': table['table_cells'][0]['text'] = '$X_{C,A}$ (cal)'
        if kind == 'normalized': stage4['property_series'][0]['property_name_normalized'] = 'normalized crystallinity'
        if kind == 'percent': table['table_cells'][0]['text'] = '$X_{C,A}$ (exp, %)'
        if kind == 'symbol': table['table_cells'][0]['text'] = '$X_{C,B}$ (exp)'
        if kind == 'page': table['page'] = 6
        if kind == 'multiplier': source['elements'][0]['text'] += '*100'
        if kind == 'nonfraction': table['table_cells'].append(dict(cell_id='v2', text='27', row_index=2, column_index=1))
        assert normalize_crystallinity_fractions(stage4, source)['unique_cells'] == 0, kind


def test_reject_unsupported_100_percent_reference_and_wrong_cell():
    for kind in ('reference', 'wrong_value', 'duplicate_definition'):
        source, stage4 = fixture()
        if kind == 'reference': source['elements'][1]['text'] = 'the melting enthalpy of pure A'
        if kind == 'wrong_value': stage4['property_series'][0]['points'][0]['value_raw'] = '0.35'
        if kind == 'duplicate_definition': source['elements'].insert(0, copy.deepcopy(source['elements'][0]))
        assert normalize_crystallinity_fractions(stage4, source)['unique_cells'] == 0
