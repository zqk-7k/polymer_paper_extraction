from stages.source_table_extraction import build_source_extraction
from tools.source_extraction_export import validate_source_result


def extract(body, caption):
    result=build_source_extraction({'document_id':'reference_no_test','elements':[
        {'block_id':'T1','type':'table','page':0,'source_block_index':0,'caption':caption,'table_body':body}]})
    validate_source_result(result)
    return result


def test_inline_temperature_is_not_material_or_treatment_and_groups_stop_at_next_material():
    data=extract('<table><tr><td colspan="2"></td><td>Contact angle</td></tr>'
        '<tr><td>PS</td><td>Untreated</td><td>79</td></tr>'
        '<tr><td>$T_{g1}$ : 104°C</td><td>PSII treated (immediately)</td><td>2</td></tr>'
        '<tr><td>P(S-6.6-AA)</td><td>Untreated</td><td>84</td></tr>'
        '<tr><td>$T_{g1}$ : 114°C</td><td>PSII treated (after 20 days)</td><td>53</td></tr></table>',
        'Glass-transition temperatures and water contact angles')
    rows=data['observations']
    assert len(rows)==6 and all(r['extraction_status']=='usable' for r in rows)
    angles=[r for r in rows if r['property_name_raw']=='Contact angle']
    assert [r['article_sample_label_raw'] for r in angles]==['PS','PS','P(S-6.6-AA)','P(S-6.6-AA)']
    assert angles[1]['condition_context_raw'][0]['value_raw']=='PSII treated (immediately)'
    temperatures=[r for r in rows if r['standard_property_code']=='STD:glass_transition_temperature']
    assert len(temperatures)==2
    assert temperatures[0]['value_raw']=='$T_{g1}$ : 104°C'
    assert not temperatures[0]['condition_context_raw']
    assert temperatures[0]['unresolved_context_fields']==['inline_temperature_treatment_not_assigned']


def test_substituent_structures_are_not_numeric_properties_or_inherited_through_blanks():
    data=extract('<table><tr><td>R</td><td>R\'</td><td>DA-Polyesters</td></tr>'
        '<tr><td>$-CH_2-$</td><td>$-(CH_2)_2$</td><td>HS</td></tr>'
        '<tr><td></td><td></td><td>HT</td></tr></table>', 'Structures of Various R and R\' Groups')
    assert len(data['observations'])==2
    assert all(r['record_kind']=='composition' and r['article_sample_label_raw']=='HS' for r in data['observations'])
    assert len(data['tables'][0]['cells'])==9


def test_energy_rows_keep_values_without_guessing_conformation_columns():
    data=extract('<table><tr><td colspan="3"></td><td>Energy Barrier (kJ/mol)</td></tr>'
        '<tr><td>MMX</td><td>33.348</td><td>53.517</td><td>20.169</td></tr>'
        '<tr><td>Str</td><td>2.613</td><td>2.842</td><td></td></tr>'
        '<tr><td>Bnd</td><td>13.322</td><td>14.057</td><td></td></tr></table>',
        'Energy Contributions: MMX (energy); Str (Stretching contribution); Bnd (Bond contribution)')
    rows=data['observations']
    assert len(rows)==7 and all(r['extraction_status']=='usable' for r in rows)
    assert rows[0]['property_name_raw']=='MMX' and rows[0]['article_sample_label_raw'] is None
    assert rows[0]['unresolved_context_fields']==['column_conformation_label']
    assert rows[2]['property_name_raw']=='Energy Barrier (kJ/mol)'


def test_undefined_energy_rows_are_not_promoted_by_similar_caption():
    data=extract('<table><tr><td colspan="3"></td><td>Energy Barrier</td></tr>'
        '<tr><td>MMX</td><td>1</td><td>2</td><td>3</td></tr>'
        '<tr><td>Str</td><td>2</td><td>3</td><td></td></tr>'
        '<tr><td>Bnd</td><td>3</td><td>4</td><td></td></tr></table>', 'Energy Contributions')
    assert data['tables'][0]['layout']['orientation']!='named_property_rows_unlabeled_columns'


def test_setpoint_is_context_and_experimental_and_calculated_crystallinity_stay_distinct():
    body='<table><tr><td>wtPEP</td><td>$T_c$ (°C)</td><td>$X_{C, PEP}$ (exp)</td><td>$X_{C, PEP}$ (cal)</td></tr><tr><td>0.5</td><td>130</td><td>0.25</td><td>0.24</td></tr></table>'
    data=extract(body,'Comparison of Experimental and Calculated Crystallinities of PEP and sPP for Various Values of wtPEP and Tc')
    rows=data['observations']
    temp=next(r for r in rows if r['value_raw']=='130')
    assert temp['record_kind']=='context'
    crystal=[r for r in rows if r['record_kind']=='property']
    assert len(crystal)==2
    assert [r['result_origin'] for r in crystal]==['experimental','calculated']
    assert all(any(c['value_raw']=='130' for c in r['condition_context_raw']) for r in crystal)
    assert all('symbol_interpretation_requires_review' not in r['standard_mapping_reasons'] for r in crystal)
    other=extract(body,'Measured crystallization temperatures')
    assert next(r for r in other['observations'] if r['value_raw']=='130')['record_kind']=='property'
