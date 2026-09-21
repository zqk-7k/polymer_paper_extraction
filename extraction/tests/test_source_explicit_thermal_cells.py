import copy
from stages.source_explicit_thermal_cells import thermal_cell_components,recover_explicit_thermal_cells


def test_full_literal_assignment_not_formula_or_plain_number():
    assert thermal_cell_components('$T_m = 17^e$','$T_g, ^\\circ C.$','')[0]['value']==17
    assert thermal_cell_components('$T_m = 17^e$','$T_g, ^\\circ C.$','')[0]['name']=='melting temperature'
    for s in ['17','Tm = 17 + 3','Tm = 17/23','Tm = 17–23','Tm > 17','Tg = 17']:
        assert thermal_cell_components(s,'Tg (°C)','')==[]
    assert thermal_cell_components('Tm = 17','Tg (K)','')==[]
    assert thermal_cell_components('Tm = 17','Thermal stability (°C)','')==[]


def test_dtg_slash_needs_explicit_pair_definition():
    text='Two maxima on the DTG curves were observed in some cases.'
    assert len(thermal_cell_components('285/345','MaxDTGa(°C)',text))==2
    assert not thermal_cell_components('285/345','MaxDTGa(°C)','Thermal curves were measured.')
    assert not thermal_cell_components('285/345','Tg (°C)',text)
    assert not thermal_cell_components('285/345/365','MaxDTGa(°C)',text)


def test_source_identity_and_idempotence():
    cells=[{'cell_id':'t:h0','text':'Sample','row_index':0,'column_index':0},
           {'cell_id':'t:h1','text':'Tg (°C)','row_index':0,'column_index':1},
           {'cell_id':'t:r','text':'Q','row_index':1,'column_index':0},
           {'cell_id':'t:v','text':'Tm = 17^e','row_index':1,'column_index':1}]
    doc={'elements':[{'block_id':'t','page':0,'type':'table','table_cells':cells}]};before=copy.deepcopy(doc)
    out,a=recover_explicit_thermal_cells({},doc);assert a['new_points']==1
    assert out['property_series'][0]['confidence']['score']==0.0
    assert out['property_series'][0]['points'][0]['evidence'][0]['table_locator']['cell_id']=='t:v'
    assert doc==before
    _,a2=recover_explicit_thermal_cells(out,doc);assert a2['new_points']==0


def test_same_row_two_different_cells_not_collapsed():
    cells=[{'cell_id':'t:h0','text':'Sample','row_index':0,'column_index':0},
           {'cell_id':'t:h1','text':'Tg (°C)','row_index':0,'column_index':1},
           {'cell_id':'t:h2','text':'MaxDTG (°C)','row_index':0,'column_index':2},
           {'cell_id':'t:r','text':'Q','row_index':1,'column_index':0},
           {'cell_id':'t:v','text':'Tm = 17^e','row_index':1,'column_index':1},
           {'cell_id':'t:w','text':'17/280','row_index':1,'column_index':2}]
    doc={'elements':[{'block_id':'t','page':0,'type':'table','table_cells':cells},
        {'block_id':'p','page':0,'type':'text','text':'Two maxima on the DTG curves were observed.'}]}
    out,a=recover_explicit_thermal_cells({},doc);assert a['new_points']==3
    assert sum(d['value_C']==17 for d in a['decisions'])==2
