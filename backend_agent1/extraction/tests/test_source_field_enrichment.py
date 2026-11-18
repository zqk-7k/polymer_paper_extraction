from stages.source_field_enrichment import enrich_fields, caption_material
from stages.source_claim_recovery import trace_claim


def test_footnotes_and_group_headers_do_not_prevent_optional_mapping():
    value=enrich_fields(['Polymer',r'$M_{\text{w}}^{b}$ (g/mol)'],'Polymer | Mw','g/mol')
    assert value['standard_property_code']=='STD:weight_average_molecular_weight'
    assert value['standard_status']=='standard_candidate'


def test_scale_and_reciprocal_unit_are_retained_without_changing_values():
    h=r'$\sigma$ ($10^{12} \Omega^{-1} \text{cm}^{-1}$)'
    value=enrich_fields([h],h,None)
    assert value['unit_raw'] is None and value['unit_interpreted']=='S/cm'
    assert value['scale_status']=='requires_interpretation'
    assert value['scale_source_texts']==[h]


def test_caption_does_not_guess_material_from_generic_topic():
    assert caption_material('Mechanical properties of PVC/ABS blends')['text']=='PVC/ABS'
    assert caption_material('Thermal properties of various polymers') is None


def test_text_source_is_found_but_not_promoted_to_table_measurement():
    c={'original':{'identity':{'value_raw':'random'},'evidence':[{'block_id':'P1'}]},'observation_ids':[], 'disposition':'source_missing_or_unlocated'}
    result=trace_claim(c,{'P1':{'type':'text','text':'random copolymer'}},{})
    assert result['status']=='text_evidence_available' and not result['auto_accepted']


def test_same_number_at_one_position_is_only_a_recovery_candidate():
    c={'original':{'identity':{'value_raw':'10'},'evidence':[{'block_id':'T1'}]},'observation_ids':[], 'disposition':'source_missing_or_unlocated'}
    cells={'C1':{'cell_id':'C1','table_id':'T1','text':'10'}}
    result=trace_claim(c,{'T1':{'type':'table'}},cells)
    assert result['candidate_cell_ids']==['C1'] and not result['auto_accepted']


def test_superscript_o_temperature_unit_is_interpreted_without_changing_raw_unit():
    for symbol, code in [('g','glass_transition_temperature'), ('m','melting_temperature')]:
        header = '$T_' + symbol + '^oC$'
        result = enrich_fields([header], header, None)
        assert result['standard_property_code'] == 'STD:' + code
        assert result['unit_interpreted'] == '°C' and result['unit_raw'] is None
    ambiguous = r'$T_g^2$'
    assert enrich_fields([ambiguous], ambiguous, None)['standard_property_code'] is None


def test_merged_evidence_ids_resolve_only_in_their_own_namespace():
    claim={'claim_kind':'publication','original':{'members':[{'collection':'property_observations','original_record':{'evidence_ids':['ev1']}}]},
           'observation_ids':[],'disposition':'source_missing_or_unlocated'}
    evidence=[{'evidence_id':'ev1','block_id':'P1','source_sentence':'Tg is 230 C'}]
    blocks={'P1':{'type':'text','text':'Tg is 230 C'}}
    result=trace_claim(claim,blocks,{},evidence)
    assert result['available_text_block_ids']==['P1'] and not result['auto_accepted']
    assert result['resolved_stage6_evidence'][0]['quote_exact_in_saved_text']
    historical={**claim,'claim_kind':'historical_candidate'}
    assert not trace_claim(historical,blocks,{},evidence)['available_text_block_ids']
    result=trace_claim(claim,blocks,{},evidence+evidence)
    assert not result['available_text_block_ids'] and result['ambiguous_stage6_evidence_ids']==['ev1']
