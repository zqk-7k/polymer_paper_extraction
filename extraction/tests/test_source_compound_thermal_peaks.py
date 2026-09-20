import copy
import pytest
from stages.source_compound_thermal_peaks import recover_compound_thermal_peaks, source_peak_cells


def document():
    cells = []
    for row, values in enumerate([['Sample', 'Tm / °C'], ['poly-A', '48, (16)']]):
        for col, value in enumerate(values):
            cells.append({'cell_id':f'T_1_1:r{row:04}:c{col:04}', 'row_index':row, 'column_index':col,
                          'row_span':1, 'column_span':1, 'is_header':row==0, 'text':value})
    return {'elements':[{'block_id':'T_1_1', 'type':'table', 'page':1,
                         'caption':'Table 1 Melting point and other thermal properties.', 'table_cells':cells},
                        {'block_id':'P_1_2', 'type':'text', 'page':1,
                         'text':'Tm has two peaks. The lower-temperature peak values are given in parentheses.'}]}


def test_explicit_two_peaks_have_distinct_values_not_range_or_duplicate():
    doc = document(); original = copy.deepcopy(doc); output = {}
    audit = recover_compound_thermal_peaks(output, doc)
    assert audit['new_points'] == 2
    points = [s['points'][0] for s in output['property_series']]
    assert [p['value_min'] for p in points] == [48,16]
    assert all(p['value_min']==p['value_max'] for p in points)
    assert all(p['sample_resolution_status']=='unresolved' and p['sample_id'] is None for p in points)
    assert doc == original
    assert recover_compound_thermal_peaks(output, doc)['new_points'] == 0


def test_existing_main_peak_normalized_in_place():
    doc = document(); table, _ = doc['elements']
    output = {'properties':[{'property_id':'prop001', 'value_raw':'48, (16)', 'unit_normalized':'°C',
                             'evidence':[{'block_id':'T_1_1','table_locator':{'cell_id':table['table_cells'][3]['cell_id']}}]}]}
    audit = recover_compound_thermal_peaks(output, doc)
    assert len(output['properties']) == 1
    assert output['properties'][0]['value_min'] == 48
    assert output['properties'][0]['value_raw'] == '48, (16)'
    assert audit['new_points'] == 1
    assert recover_compound_thermal_peaks(output, doc)['decisions'] == []


@pytest.mark.parametrize('raw', ['48 (16)', '48 ± 16', '16–48', '48, (60)', '48, (16, 12)'])
def test_ambiguous_or_contradictory_compound_not_split(raw):
    doc = document(); doc['elements'][0]['table_cells'][3]['text'] = raw
    assert source_peak_cells(doc) == []


@pytest.mark.parametrize('change', ['no_definition','wrong_property','different_page','uncertainty','multiple_tables','no_sample_header'])
def test_missing_context_prevents_promotion(change):
    doc = document(); table, note = doc['elements']
    if change=='no_definition':note['text']='Tm values are shown.'
    if change=='wrong_property':table['table_cells'][1]['text']='Tg / °C'
    if change=='different_page':note['page']=2
    if change=='uncertainty':note['text'] += ' Standard deviation is reported.'
    if change=='multiple_tables':doc['elements'].append({**table,'block_id':'T_1_9','caption':'Table 2 Melting point.'})
    if change=='no_sample_header':table['table_cells'][0]['text']='Reaction time'
    assert source_peak_cells(doc) == []


def test_japanese_explicit_lower_peak_definition():
    doc = document()
    doc['elements'][1]['text']='Tmは2箇所に見られるが，低温側のピーク（値はカッコ内）はブロードである．'
    assert len(source_peak_cells(doc)) == 1
