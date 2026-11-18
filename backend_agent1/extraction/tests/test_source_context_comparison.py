"""Full-context experiments preserve scope, provenance and configured limits."""
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from stages.source_model_extraction import build_packets, source_fingerprint, attach_bundle
from stages.source_table_extraction import build_source_extraction
from stages.sample_catalog import digest
from tools.run_source_workflow import run
from tools.source_extraction_export import validate_source_result


def source():
    return build_source_extraction({'document_id':'reference_no_new','elements':[
        {'block_id':'H1','type':'title','text':'Material QX','source_block_index':0},
        {'block_id':'P0','type':'text','text':'QX is the copolymer.','source_block_index':1},
        *[{'block_id':f'P{i}','type':'text','text':'The procedure was repeated.',
           'source_block_index':i+1} for i in range(1,4)],
        {'block_id':'T1','type':'table','page':0,'caption':'Table 1. Complete values',
         'table_notes':['a: under nitrogen'], 'source_block_index':5,
         'table_body':'<table><tr><th>Sample</th><th>Tg</th></tr><tr><td>QX</td><td>147</td></tr></table>'},
        {'block_id':'P4','type':'text','text':'The glass transition temperature was 147 °C.',
         'section':'Results','source_block_index':6},
        {'block_id':'F1','type':'image','caption':'Figure 1. Thermal behavior',
         'image_path':'images/figure1.jpg','source_block_index':7},
        {'block_id':'R1','type':'text','text':'Reference material has Tg 999.',
         'section':'References','source_block_index':8}]},include_local_reviews=False)


def test_full_context_keeps_all_sources_and_identical_focal_scope():
    data=source()
    local=build_packets(data); full=build_packets(data,context_mode='full_article')
    scope=lambda p:(p['focal_block_id'],p['focal_start'],p['focal_end'])
    assert list(map(scope,local))==list(map(scope,full))
    assert full[0]['focal_block_id']=='P4'
    all_blocks=data['source_blocks']+data['source_context_blocks']
    assert {b['block_id']:b['text'] for b in full[0]['evidence_blocks']}=={b['block_id']:b['text'] for b in all_blocks}
    assert 'P0' not in {b['block_id'] for b in local[0]['evidence_blocks']}
    assert full[0]['related_tables'][0]['source_block_index']==5
    assert [b['id'] for b in full[0]['article_order']]==['H1','P0','P1','P2','P3','T1','P4','F1','R1']
    assert full[0]['referenced_figures'][0]['image_path']=='images/figure1.jpg'
    assert 'R1' not in {p['focal_block_id'] for p in full}
    assert not any(p['omitted_context_ids'] for p in full)


def test_far_material_citation_exports_and_cannot_change_focal_value():
    data=source(); packet=build_packets(data,context_mode='full_article')[0]
    cite=lambda text,bid='P4':{'block_id':bid,'quote':text}
    response={'observations':[{'property':cite('glass transition temperature'), 'value':cite('147'),
        'material':cite('QX','P0'),'unit':cite('°C'),'conditions':[], 'target_id':None,
        'assertion':'reported','rationale':'The distant paragraph defines the material.'}],
        'has_more':False,'unresolved':[]}
    bundle={'source_fingerprint':source_fingerprint(data),'packet_options':{'context_mode':'full_article'},
        'target_ids':[],'responses':{packet['packet_id']:{'request_packet_sha256':digest(packet),'response':response}}}
    result=attach_bundle(data,bundle)
    validate_source_result(result)
    rows=[r for r in result['observations'] if r.get('semantic_verification')=='model_only']
    assert len(rows)==1 and rows[0]['article_sample_label_raw']=='QX'
    response['observations'][0]['value']=cite('999','R1')
    result=attach_bundle(data,bundle)
    assert any(i['reason']=='value_outside_focal_range' for i in result['model_text_coverage']['issues'])


def test_configured_output_and_timeout_reach_client_and_resume_is_frozen(tmp_path):
    data=source(); root=tmp_path/'source'; (root/data['document_id']).mkdir(parents=True)
    (root/data['document_id']/'source_extraction.json').write_text(json.dumps(data),encoding='utf8')
    config=tmp_path/'config.yaml'
    config.write_text('llm:\n  default:\n    provider: test\n    model: test\n    base_url: https://example.invalid\n    timeout_seconds: 777\nstages:\n  stage4_property:\n    max_tokens: 64000\n',encoding='utf8')
    seen=[]
    class Client:
        last_raw_response=None
        def __init__(self,resolved,**kwargs): self.resolved=resolved
        def call_json(self,**request):
            seen.append((self.resolved,request))
            return SimpleNamespace(data={'observations':[],'unresolved':[],'has_more':False})
    with patch('tools.run_source_workflow.LLMClient',Client):
        run(root,tmp_path/'out',model='test',config_path=config,max_requests=1,context_mode='full_article')
    assert seen[0][0].timeout_seconds==777
    assert seen[0][1]['max_tokens']==64000
    with pytest.raises(ValueError,match='Resume contract differs'):
        run(root,tmp_path/'out',model='test',config_path=config,resume=True,offline=True,context_mode='local')
    config.write_text(config.read_text().replace('64000','65000'))
    with pytest.raises(ValueError,match='Resume contract differs'):
        run(root,tmp_path/'out',model='test',config_path=config,resume=True,offline=True,context_mode='full_article')


def test_comparison_freezes_sources_runs_both_arms_and_never_calls_counts_accuracy(tmp_path):
    from tools.run_source_context_comparison import prepare, execute, check_frozen
    stage=tmp_path/'stage'; (stage/'reference_no_new').mkdir(parents=True)
    original=stage/'reference_no_new/stage0_blocks.json'
    original.write_text(json.dumps({'document_id':'reference_no_new','elements':[
        {'block_id':'P1','type':'text','text':'No measured properties are reported.'}]}),encoding='utf8')
    config=tmp_path/'config.yaml'
    config.write_text('llm:\n  default:\n    provider: test\n    model: test\n    base_url: https://example.invalid\n',encoding='utf8')
    root=tmp_path/'experiment'; prepare(stage,root,['reference_no_new'],config)
    class Client:
        last_raw_response=None
        def __init__(self,*args,**kwargs): pass
        def call_json(self,**request):
            return SimpleNamespace(data={'observations':[],'unresolved':[],'has_more':False})
    with patch('tools.run_source_workflow.LLMClient',Client):
        result=execute(root,max_requests=1)
    assert result['paired_completed_ranges']==1 and result['execution_complete']
    assert result['accuracy'] is None and result['recall'] is None and not result['quality_review_complete']
    assert all(m['calls_without_usage']==1 and m['calls_without_cost']==1 for m in result['metrics'])
    frozen=root/'sources/reference_no_new/source_extraction.json'
    data=json.loads(frozen.read_text(encoding='utf8')); data['source_blocks'][0]['text']='Changed'
    frozen.write_text(json.dumps(data),encoding='utf8')
    with pytest.raises(ValueError,match='Frozen source changed'): check_frozen(root)
