from stages.stage4_direct_text_supplement import parse_value, text_requests, equation_reports_literal_value, merge_text


def test_reported_scientific_assignment_not_formula_evaluation():
    assert parse_value(r'6 2 \times 1 0 ^ {3}') == 62000
    assert parse_value(r'1.2 \times 10^{9999}') is None
    assert equation_reports_literal_value(r'$M_w=62\times10^3$',r'62\times10^3')
    assert not equation_reports_literal_value(r'$M_w=62\times10^3$','62')
    assert not equation_reports_literal_value('$x=1+2$','1')
    assert not equation_reports_literal_value('$x=a/2$','2')


def test_spaced_number_with_explicit_mass_assignment_across_tex_delimiter():
    assert parse_value('70 600',source_quote=r'P2: $M_{w}:$70 600;')==70600
    assert parse_value('2 5 3 0 0',source_quote=r'P1: $M_{w}{:2 5 3 0 0};')==25300
    assert parse_value('12 345',source_quote='The entries 12 345 were used.') is None
    assert parse_value('12 345',source_quote='M_w: 12 345 + 9') is None


def test_keep_sample_context_and_reported_assignment_only():
    doc={'elements':[
        {'block_id':'p','type':'text','text':'The following values refer to polymer A.'},
        {'block_id':'e','type':'equation','text':'$M_w=62000$'},
        {'block_id':'f','type':'equation','text':'$M_w=M_n PDI$'}]}
    request=text_requests(doc)[0]
    assert [b['block_id'] for b in request['blocks']]==['p','e']


def test_equation_fact_retains_source_and_replay_is_idempotent():
    doc={'elements':[
        {'block_id':'p','type':'text','page':0,'text':'The following data refer to polymer A.'},
        {'block_id':'e','type':'equation','page':0,'text':'$M_w=62000$'}]}
    response={'facts':[{'block_id':'e','quote':'$M_w=62000$','property_name':'weight-average molecular weight',
        'value_raw':'62000','unit_raw':None,'sample_label':'polymer A','sample_evidence_block_id':'p','role':'material_property'}]}
    one,audit=merge_text({'property_series':[]},doc,[response])
    assert audit['decisions'][0]['accepted']
    assert one['property_series'][0]['points'][0]['evidence'][0]['source_type']=='equation'
    two,_=merge_text(one,doc,[response])
    assert len(two['property_series'])==1


def test_equation_number_before_sentence_period_is_not_rejected():
    doc={'elements':[{'block_id':'e','type':'equation','page':0,'text':'$$PDI = 1. 3 2.$$'},
                     {'block_id':'p','type':'text','page':0,'text':'polymer A'}]}
    fact={'block_id':'e','quote':'PDI = 1. 3 2.','property_name':'polydispersity index',
          'value_raw':'1. 3 2','sample_label':'polymer A','sample_evidence_block_id':'p','role':'material_property'}
    out,audit=merge_text({'property_series':[]},doc,[{'facts':[fact]}])
    assert audit['decisions'][0]['accepted']
    assert out['property_series'][0]['points'][0]['value_min']==1.32
    fact['value_raw']='1. 3'
    _,audit=merge_text({'property_series':[]},doc,[{'facts':[fact]}])
    assert not audit['decisions'][0]['accepted']
