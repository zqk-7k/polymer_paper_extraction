import copy
from stages.source_thermal_criteria import bind_linked_thermal_criteria,explicit_loss_percentages,literal_prose_pairs


def fixture(header='Td (°C)',caption='Table 2 Thermal properties',text='The decomposition temperatures (Td) in Table 2 at 5% weight loss are 435 °C.'):
    doc={'elements':[{'block_id':'t','type':'table','page':0,'caption':caption,'table_cells':[
        {'cell_id':'t:h','text':header,'row_index':0,'column_index':1},
        {'cell_id':'t:a','text':'435','row_index':1,'column_index':1}]},
        {'block_id':'p','type':'text','page':0,'text':text}]}
    stage={'properties':[{'property_id':'x','value_raw':'435','value_min':435,'value_max':435,'unit_normalized':'°C',
        'evidence':[{'block_id':'t','table_locator':{'cell_id':'t:a','table_id':'t'}}]}]}
    return stage,doc


def test_linked_literal_Td_definition_adds_condition_not_a_response():
    stage,doc=fixture();before=copy.deepcopy(stage)
    result=bind_linked_thermal_criteria(stage,doc)
    assert result['unique_cells_bound']==1
    prop=stage['properties'][0]
    assert prop['measurement_context']['other_conditions']['weight_loss_threshold_percent']=='5'
    for k in ('value_raw','value_min','value_max','unit_normalized'):assert prop[k]==before['properties'][0][k]
    assert len(stage['properties'])==1
    assert bind_linked_thermal_criteria(stage,doc)['unique_cells_bound']==0


def test_requires_table_link_exact_number_and_thermal_definition():
    for text in ['Table 3 at 5% weight loss has decomposition temperatures 435 °C.',
                 'Table 2 decomposition temperatures at 5% weight loss are 430 °C.',
                 'Table 2 temperature 435 °C; mixture concentration 5%.']:
        stage,doc=fixture(text=text);assert not bind_linked_thermal_criteria(stage,doc)['decisions']
    stage,doc=fixture();stage['properties'][0]['unit_normalized']='%'
    assert not bind_linked_thermal_criteria(stage,doc)['decisions']


def test_shared_percent_headers_require_explicit_loss_context():
    stage,doc=fixture(header='5%',caption='Table 2 TGA data',text='Temperatures at 5 and 50% weight loss are given in Table 2.')
    assert bind_linked_thermal_criteria(stage,doc)['unique_cells_bound']==1
    stage,doc=fixture(header='5%',caption='Table 2 Composition',text='Temperatures at 5 and 50% weight loss are given in Table 2.')
    assert not bind_linked_thermal_criteria(stage,doc)['decisions']
    assert explicit_loss_percentages('5 and 50% weight loss')=={5.,50.}
    assert explicit_loss_percentages('0% weight loss')==set()


def test_symbol_with_printed_percent_is_not_a_bare_T5_guess():
    stage,doc=fixture(header='T_3\\% (N2)',text='T3% is temperature where weight loss is observed at 3%, shown in Table 2.')
    assert bind_linked_thermal_criteria(stage,doc)['unique_cells_bound']==1
    stage,doc=fixture(header='T5 (°C)',text='Table 2 lists thermal temperatures.')
    assert not bind_linked_thermal_criteria(stage,doc)['decisions']


def test_explicit_owned_superscript_criterion_without_table_number_in_note():
    stage,doc=fixture(header='initial decomp $temp^a$ (°C)',text='Thermal analysis results.')
    note={'block_id':'f','type':'footnote','page':0,'text':'a Temperature of 2.0% weight loss.',
          'content':{'owning_table_block_id':'t'}}
    doc['elements'].append(note)
    assert bind_linked_thermal_criteria(stage,doc)['unique_cells_bound']==1
    assert stage['properties'][0]['measurement_context']['other_conditions']['weight_loss_threshold_percent']=='2'
    assert not bind_linked_thermal_criteria(stage,doc)['decisions']


def test_owned_note_must_match_marker_owner_unique_percent_and_temperature():
    for header,owner,note in [
        ('initial decomp $temp^b$ (°C)','t','a Temperature of 2% weight loss.'),
        ('initial decomp $temp^a$ (°C)','other','a Temperature of 2% weight loss.'),
        ('initial decomp $temp^a$ (°C)','t','a Temperatures of 2 and 5% weight loss.'),
        ('initial decomp $temp^a$ (°C)','t','a This is not a temperature of 2% weight loss.'),
        ('initial decomp $temp^a$ (°C)','t','a Mixture contains 2% solvent.'),
        ('char yield^a (%)','t','a Temperature of 2% weight loss.'),
    ]:
        stage,doc=fixture(header=header,text='Thermal analysis results.')
        doc['elements'].append({'block_id':'f','type':'footnote','page':0,'text':note,
                               'content':{'owning_table_block_id':owner}})
        assert not bind_linked_thermal_criteria(stage,doc)['decisions']


def test_prose_criterion_is_attached_to_retained_same_block_temperature():
    stage,doc=fixture(text='Polymer Q showed a 4% weight loss at 435 °C.')
    p=stage['properties'][0];p['property_name_normalized']='thermal_decomposition_temperature'
    p['evidence']=[{'block_id':'p','source_sentence':doc['elements'][1]['text']}]
    assert len(bind_linked_thermal_criteria(stage,doc)['prose_decisions'])==1
    assert p['measurement_context']['other_conditions']['weight_loss_threshold_percent']=='4'
    assert not bind_linked_thermal_criteria(stage,doc)['prose_decisions']


def test_prose_pairs_do_not_cross_temperatures_or_missing_quotes():
    text='Polymer A showed a 2% weight loss at 430 °C. Polymer B showed a 7% weight loss at 460 °C.'
    assert literal_prose_pairs(text)==[(430.,2.),(460.,7.)]
    stage,doc=fixture(text=text)
    p=stage['properties'][0];p.update(value_raw='430',value_min=430,value_max=430,property_name_normalized='thermal decomposition temperature')
    p['evidence']=[{'block_id':'p','source_sentence':'Polymer A decomposition temperature was 430 °C.'}]
    assert not bind_linked_thermal_criteria(stage,doc)['prose_decisions']
    p['evidence'][0]['source_sentence']=text
    assert bind_linked_thermal_criteria(stage,doc)['prose_decisions'][0]['weight_loss_percent']==2
    assert explicit_loss_percentages('5% weight loss was not observed')==set()
    stage,doc=fixture(header='T_{d,onset}',text='Table 2 lists thermal temperatures.')
    assert not bind_linked_thermal_criteria(stage,doc)['decisions']
    assert literal_prose_pairs('4% weight loss at 410–435 °C')==[]
    assert literal_prose_pairs('not 4% weight loss at 435 °C')==[]
    stage,doc=fixture(text='Polymer Q showed a 4% weight loss at 435 °C.')
    stage['properties'][0]['property_name_normalized']='glass_transition_temperature'
    stage['properties'][0]['evidence']=[{'block_id':'p'}]
    assert not bind_linked_thermal_criteria(stage,doc)['prose_decisions']
