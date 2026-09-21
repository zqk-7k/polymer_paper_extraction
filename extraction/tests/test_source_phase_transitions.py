from types import SimpleNamespace
from stages import source_phase_transitions as module

LEGEND='g: glass transition; sA: smectic A; LC: liquid-crystalline; i: isotropic.'

def test_chain_only_with_actual_symbol_definitions():
    defs=module.phase_definitions(LEGEND)
    values=module.parse_phase_chain('g 7 LC 112 i',defs)
    assert [p['value'] for p in values]==[7,112]
    assert not module.parse_phase_chain('g 7 LC 112 i',set())
    for bad in ['7,112','g 7+3 LC 112 i','g 7 LC 112 < decomposition','g 7 LC (112) i','g 7 LC 112-118 i']:
        assert not module.parse_phase_chain(bad,defs)

def test_pdf_legend_recovery_is_verbatim_and_idempotent():
    old={'elements':[{'block_id':'T','type':'table','page':3}]}
    pages={3:[{'text':LEGEND,'bbox':[1,2,3,4]}]}
    updated,audit=module.recover_pdf_phase_legends(old,pages,'sha')
    assert audit['recovered']==1 and updated['elements'][1]['text']==LEGEND
    assert updated['elements'][1]['bbox'] is None
    assert module.recover_pdf_phase_legends(updated,pages,'sha')[0]==updated
    assert module.recover_pdf_phase_legends(old,{2:pages[3]},'sha')[0]==old

def test_source_chain_materialization_keeps_two_values_and_no_replay_inflation(monkeypatch):
    table={'table_id':'T','page':0,'caption':'Properties','cells':[
        {'cell_id':'sh','row_index':0,'column_index':0,'text':'Polymer'},
        {'cell_id':'h','row_index':0,'column_index':1,'text':'Thermal transitions °C'},
        {'cell_id':'s','row_index':1,'column_index':0,'text':'P2'},
        {'cell_id':'v','row_index':1,'column_index':1,'text':'g 7 LC 112 i'}]}
    monkeypatch.setattr(module,'table_requests',lambda _: [table])
    source={'elements':[{'block_id':'note','type':'footnote','page':0,'text':LEGEND}]}
    out,audit=module.recover_phase_transitions({},source)
    assert audit['points_added']==2
    assert [s['points'][0]['value_min'] for s in out['property_series']]==[7,112]
    assert all(s['points'][0]['evidence'][0]['table_locator']['cell_id']=='v' for s in out['property_series'])
    assert all(s['points'][0]['sample_id'] is None for s in out['property_series'])
    assert out['property_series'][0]['points'][0]['measurement_context']['other_condition_evidence']['source_phase_legend'][0]['source_type']=='footnote'
    assert module.recover_phase_transitions(out,source)[1]['points_added']==0
    source['elements'][0]['page']=1
    assert module.recover_phase_transitions({},source)[1]['points_added']==0
