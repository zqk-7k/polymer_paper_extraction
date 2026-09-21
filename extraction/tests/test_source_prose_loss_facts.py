from stages.source_prose_loss_facts import literal_pairs,explicit_symbol_definitions,criterion_for_temperature,recover_prose_loss_facts


def test_direct_and_shared_predicate_not_ranges_or_guesses():
    assert literal_pairs('4% weight loss at $2 6 0 ~ ^ { \\circ } \\mathrm { C }$')==[(260.,4.)]
    assert literal_pairs('4% weight loss at 430°C in nitrogen (Fig. 2) and at 405°C in air')==[(430.,4.),(405.,4.)]
    assert literal_pairs('not 4% weight loss at 430°C')==[]
    assert literal_pairs('4% weight loss at 410–430°C')==[]
    assert literal_pairs('initial decomposition at 430°C')==[]


def test_symbol_requires_printed_definition_and_temperature_list():
    text='the temperature of 40% weight loss ($T_{d}^{40}$) occurring at 410°C for A, 420°C for B'
    defs=explicit_symbol_definitions(text);assert defs=={'T_d^40':40.}
    assert criterion_for_temperature(text,410.,defs)==40
    assert criterion_for_temperature('In air, $T_{d}^{40}$ occurred at 480°C for A.',480.,defs)==40
    assert criterion_for_temperature('In air, $T_{d}^{40}$ occurred at 480°C for A.',480.,{}) is None
    assert criterion_for_temperature(text,450.,defs) is None
    assert criterion_for_temperature('In air, T_d^40 occurred at 480°C, not 450°C.',450.,defs) is None
    assert criterion_for_temperature('T_d^40 occurred at 480°C and T_d^30 occurred at 460°C.',480.,{'T_d^40':40.,'T_d^30':30.}) is None


def test_emit_relation_not_temperature_and_no_replay_duplicate():
    q='Polymer Q showed a 4% weight loss at 430°C.'
    ev={'block_id':'p','page':0,'source_type':'text','source_sentence':q}
    s={'series_id':'series001','property_name_raw':'temperature at 4% weight loss','unit_normalized':'°C',
       'points':[{'point_id':'pt001','value_raw':'430','value_min':430.,'value_max':430.,
                  'coordinates':[{'name_raw':'source sample label','value_raw':'Polymer Q','evidence':ev}],
                  'evidence':[ev]}]}
    d={'elements':[{'block_id':'p','page':0,'type':'text','text':q}]}
    out,a=recover_prose_loss_facts({'property_series':[s]},d);assert a['new_criterion_relations']==1
    assert out['property_series'][-1]['points'][0]['value_min']==4
    assert out['property_series'][-1]['measurement_context']['other_conditions']['fact_role']=='measurement_criterion'
    assert out['property_series'][-1]['confidence']['score']==0.0
    assert recover_prose_loss_facts(out,d)[1]['new_criterion_relations']==0


def test_conflicting_symbol_definitions_never_restore_last_value():
    text='In air, T_d^40 occurred at 480°C for Q.'
    ev={'block_id':'p','page':0,'source_type':'text','source_sentence':text}
    s={'series_id':'series001','property_name_raw':'temperature at 40% weight loss','unit_normalized':'°C',
       'points':[{'point_id':'pt001','value_min':480.,'value_max':480.,'coordinates':[
           {'name_raw':'source sample label','value_raw':'Q','evidence':ev}],'evidence':[ev]}]}
    blocks=[{'block_id':'p','page':0,'type':'text','text':text}]
    for i,pct in enumerate([40,30,40]):
        blocks.append({'block_id':f'd{i}','page':0,'type':'text','text':f'temperature of {pct}% weight loss (T_d^40)'})
    assert recover_prose_loss_facts({'property_series':[s]},{'elements':blocks})[1]['new_criterion_relations']==0
