from copy import deepcopy
import json
from pathlib import Path

from stages.source_semantic_normalization import normalize_observations
from stages.source_model_extraction import build_packets
from stages.source_table_extraction import build_source_extraction
from stages.stage0_load_document import recover_missing_equations, load_document_elements, run_stage0
from schema.polymer_schema import SourceDocument
from tools.evaluate_article_standard import semantic_value_match
from test_stage0_load_document import source_document, element


def row(name,value='12',unit=None,**kw):
    return dict(property_name_raw=name,value_raw=value,unit_raw=unit,
                observation_id='unchanged',extraction_status='usable',**kw)


def test_semantics_preserve_raw_and_are_idempotent():
    inputs=[row('λem','525','nm'),row('λmax','440','nm',table_id='T1'),
        row('Dielectric constant (Dry)','3.4',condition_context_raw=[{'name_raw':'frequency','value_raw':'10 kHz'}]),
        row('crystallinity','X_C,PEP exp=0.0550; X_C,PEP cal=0.0560'),row('Tg','433','K')]
    before=deepcopy(inputs)
    context={'related_tables':[{'table_id':'T1','caption':'UV-vis absorption','cells':[]}]}
    result=normalize_observations(inputs,context)
    assert inputs==before
    assert [len(r['semantic_normalization']['interpretations']) for r in result]==[1,1,1,2,1]
    assert result[3]['semantic_normalization']['interpretations'][0]['value']=='5.5'
    assert result[4]['semantic_normalization']['interpretations'][0]['value']=='159.85'
    assert normalize_observations(result,context)==result
    for a,b in zip(inputs,result):assert all(b[k]==v for k,v in a.items())


def test_ambiguous_names_units_and_conditions_do_not_create_measurements():
    inputs=[row('λmax','440','nm'),row('crystallinity','.55'),row('T_i','220','°C'),
        row('Dielectric constant DC','3',condition_context_raw=[{'name_raw':'frequency','value_raw':'10 kHz'}]),
        row('Mw','1234'),row('tensile strength','50','MPa'),
        row('crystallinity','.55','%',condition_context_raw=[{'name_raw':'Tc','value_raw':'110 °C'}])]
    result=normalize_observations(inputs,{})
    assert not any(r['semantic_normalization']['interpretations'] for r in result)
    assert result[-1]['semantic_normalization']['condition_views'][0]['relation']=='condition'


def test_threshold_requires_explicit_definition_and_preserves_qualifier():
    context={'evidence_blocks':[{'block_id':'P1','text':'Temperatures for 3% gravimetric loss (T_i) were measured.'}]}
    result=normalize_observations([row('T_i','>210','°C'),row('T10','300','°C')],context)
    assert result[0]['value_raw']=='>210'
    assert result[0]['semantic_normalization']['interpretations'][0]['value']=='3.0'
    assert result[1]['semantic_normalization']['interpretations'][0]['relation']=='threshold'
    context['evidence_blocks'][0]['text']='Temperatures for 3% gravimetric loss (T ) were measured.'
    assert not normalize_observations([row('T_i','210','°C')],context)[0]['semantic_normalization']['interpretations']


def test_temperature_precision_only_applies_to_explicit_conversion():
    gold={'minimum':160.,'maximum':160.,'unit':'C'}
    assert semantic_value_match(gold,row('Tg','433','K'))[0]
    assert not semantic_value_match(gold,row('Tg','160.3','C'))[0]
    assert not semantic_value_match(gold,row('Tg','>433','K'))[0]
    assert not semantic_value_match(gold,row('Tg','400–440','K'))[0]
    assert not semantic_value_match({**gold,'raw_value':'>160'},row('Tg','433','K'))[0]


def test_legacy_formula_recovery_invalidates_cache_and_reaches_one_packet(tmp_path):
    pdf=tmp_path/'organized'/'origin.pdf';pdf.parent.mkdir()
    content=pdf.with_name('content.json')
    blocks=[{'type':'text','page_idx':0,'text':'Polymer properties'},
            {'type':'equation','page_idx':0,'text':r'$$M_w=62\times10^3; M_w/M_n=1.32$$','bbox':[1,2,3,4]}]
    raw=source_document([element('P_0_0','text',0,text='Polymer properties')])
    raw['paper']['organized_pdf_path']=str(pdf)
    path=tmp_path/'reference_no_0000001_document.json';path.write_text(json.dumps(raw))
    dest=tmp_path/'stage0'
    output,_=run_stage0(path,dest)
    content.write_text(json.dumps({'document_id':raw['document_id'],'blocks':blocks}))
    output,cached=run_stage0(path,dest)
    assert not cached
    recovered=recover_missing_equations(SourceDocument.model_validate(raw))
    assert len(recover_missing_equations(recovered).elements)==2
    stage0=load_document_elements(recovered).model_dump(mode='json')
    packets=build_packets(build_source_extraction(stage0,include_local_reviews=False),context_mode='article_once')
    assert len(packets)==1
    assert any(b['type']=='equation' and '1.32' in b['text'] for b in packets[0]['evidence_blocks'])
    assert run_stage0(path,dest)[1]
    assert json.loads(path.read_text())==raw


def test_offline_normalization_accepts_regular_workflow_summary(tmp_path):
    from tools.normalize_source_results import normalize_batch
    run=tmp_path/'run';export=run/'export';export.mkdir(parents=True)
    record=row('λem','525','nm',document_id='reference_no_new')
    source=export/'model_extractions.jsonl';source.write_text(json.dumps(record)+'\n',encoding='utf-8')
    summary=run/'summary.json';summary.write_text(json.dumps({'documents':[{'document_id':'reference_no_new'}],
        'export_dir':str(export),'status':'text_scan_finished'}),encoding='utf-8')
    request=run/'calls/reference_no_new/packet/request.json';request.parent.mkdir(parents=True)
    request.write_text(json.dumps({'user_message':json.dumps({'packet':{'document_id':'reference_no_new'}})}),encoding='utf-8')
    result=normalize_batch(summary,tmp_path/'normalized')
    assert result['api_requests']==0 and result['model_rows']==1
    assert json.loads(source.read_text())==record
    assert result['documents'][0]['model_rows']==1
