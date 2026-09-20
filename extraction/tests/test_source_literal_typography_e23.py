from stages.stage4_direct_text_supplement import parse_value,merge_text,numeric_part_with_declared_unit
from stages.source_intervals import reported_interval


def test_unicode_overbar_explicit_molecular_assignment_not_prose_list():
    assert parse_value('125 000',source_quote='M̄_w = 125 000 g mol⁻¹')==125000
    assert parse_value('125 000',source_quote='M_w = 125 000 g/mol')==125000
    assert parse_value('125 000',source_quote='Samples 125 000 were measured') is None


def test_approximate_complete_range_preserves_qualifier_and_not_scalar():
    q=reported_interval('~2–4');assert q['minimum']==2 and q['maximum']==4 and q['approximate']
    assert reported_interval('~4') is None
    assert reported_interval('~2 + 4') is None
    assert reported_interval('2–4')=={'minimum':2.,'maximum':4.,'kind':'range','inequality':None}


def test_exact_declared_percent_suffix_keeps_raw_unit_and_quote():
    quote='Polymer Q contains 70% trans, 2% 3,4-vinyl.'
    doc={'elements':[{'block_id':'p','page':0,'type':'text','text':quote}]}
    facts=[{'block_id':'p','quote':quote,'property_name':name,'value_raw':raw,'unit_raw':'%',
            'sample_label':'Polymer Q','sample_evidence_block_id':'p','role':'material_property'}
           for raw,name in [('70%','trans content'),('2%','3,4-vinyl content')]]
    out,a=merge_text({},doc,[{'facts':facts}]);assert sum(d['accepted'] for d in a['decisions'])==2
    assert out['property_series'][0]['points'][0]['value_raw']=='70%'
    assert out['property_series'][0]['points'][0]['value_min']==70
    assert out['property_series'][1]['points'][0]['value_min']==2
    assert numeric_part_with_declared_unit('70%','°C')=='70%'
    assert numeric_part_with_declared_unit('70% + 2%','%')=='70% + 2'
