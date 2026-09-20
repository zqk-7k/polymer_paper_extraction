import copy
from stages.source_standard_unit_resolution import resolve_standard_units


def fixture():
    source = {'elements':[
        {'block_id':'m','type':'text','section':'Methods','text':'The LOI was determined according to ASTM D-2863-77.'},
        {'block_id':'t','type':'table','table_cells':[
            {'cell_id':'v','text':'26','row_index':1,'column_index':1},
            {'cell_id':'h','text':'LOI','row_index':0,'column_index':1}]}]}
    point = {'value_min':26.,'value_max':26.,'value_raw':'26','unit_raw':None,
             'unit_normalized':None,'measurement_context':{'condition_status':'reported','other_conditions':{}},
             'evidence':[{'block_id':'t','table_locator':{'cell_id':'v','column_label':'LOI'}}]}
    return source, {'property_series':[{'property_name_normalized':'limiting oxygen index',
                                      'unit_raw':None,'points':[point]}]}


def test_explicit_standard_resolves_unit_but_does_not_create_or_rescale_value():
    source, stage4 = fixture();original=copy.deepcopy(stage4)
    out,audit=resolve_standard_units(stage4,source)
    point=out['property_series'][0]['points'][0]
    assert point['unit_normalized']=='%' and point['unit_raw'] is None
    assert point['value_min']==26 and len(audit['decisions'])==1
    assert point['measurement_context']['other_conditions']['unit_resolution_basis']=='standard_defined_not_printed'
    assert original==stage4
    again,audit=resolve_standard_units(out,source)
    assert again==out and not audit['decisions']


def test_no_method_wrong_property_fraction_or_source_mismatch_is_not_inferred():
    source, stage4=fixture()
    for mutation in ['missing_method','references','wrong_property','fraction','wrong_cell','explicit_unit','false_header']:
        s,d=copy.deepcopy(source),copy.deepcopy(stage4);p=d['property_series'][0]['points'][0]
        if mutation=='missing_method':s['elements'][0]['text']='LOI was measured.'
        if mutation=='references':s['elements'][0]['section']='References'
        if mutation=='wrong_property':d['property_series'][0]['property_name_normalized']='oxygen permeability'
        if mutation=='fraction':p['value_min']=p['value_max']=.26;p['value_raw']='.26'
        if mutation=='wrong_cell':s['elements'][1]['table_cells'][0]['text']='99'
        if mutation=='explicit_unit':p['unit_raw']='fraction'
        if mutation=='false_header':s['elements'][1]['table_cells'][1]['column_index']=2
        out,a=resolve_standard_units(d,s)
        assert out==d and not a['decisions'],mutation
