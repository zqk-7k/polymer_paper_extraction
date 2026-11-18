import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from stages.source_article_extraction import validate_article_response
from stages.source_model_extraction import build_packets, split_packet
from stages.source_table_extraction import build_source_extraction
from tools.run_source_workflow import run
from tools.source_extraction_export import validate_source_result


def source():
    return build_source_extraction({'document_id':'reference_no_new','elements':[
        {'block_id':'H1','type':'title','text':'Polymer A and B'},
        {'block_id':'P1','type':'text','text':'A and B have Tg 120 and 130 C, respectively.'},
        {'block_id':'P2','type':'text','text':'Both are soluble in water. '*300},
        {'block_id':'T1','type':'table','page':0,'source_block_index':3,'caption':'Table 1. Modulus','table_notes':['At room temperature'],
         'table_body':'<table><tr><th>Sample</th><th>Modulus</th></tr><tr><td>A</td><td>3</td></tr></table>'},
        {'block_id':'F1','type':'image','caption':'Figure 1. Curves','image_path':'images/f1.png'}]},include_local_reviews=False)


def test_whole_article_preserves_everything_and_does_not_split():
    data=source(); packets=build_packets(data,context_mode='article_once',max_chars=100)
    assert len(packets)==1
    packet=packets[0]
    assert packet['extraction_scope']=='entire_article' and not split_packet(packet)
    assert [b['text'] for b in packet['evidence_blocks']]==[b['text'] for b in sorted(data['source_blocks']+data['source_context_blocks'],key=lambda b:(b.get('source_block_index') is None,b.get('source_block_index') or 0,b['block_id']))]
    assert sum(len(t['cells']) for t in packet['related_tables'])==sum(len(t['cells']) for t in data['tables'])
    assert packet['referenced_figures']==data['source_figure_blocks']


def test_basic_validation_preserves_missing_ambiguous_and_normalized_evidence():
    data=source(); packet=build_packets(data,context_mode='article_once')[0]
    observations=[
        {'property':'glass transition temperature','value':120,'material':'A','unit':'C'},
        {'property':{'quote':'Tg'},'value':{'quote':'130','block_id':'unknown'},'material':'B','source':{'block_id':['bad']}},
        {'property':'solubility','value':'soluble','assertion':'uncertain','conditions':'water'},
        {'property':'modulus','value':'3','source':{'cell_id':data['tables'][0]['cells'][-1]['cell_id']}},
        {'property':'zero','value':0}, {'property':'unknown','value':None}, 'bad record']
    rows,issues,complete=validate_article_response(data,packet,{'observations':observations},[])
    assert complete and len(rows)==5
    assert all(r['extraction_status']=='usable' for r in rows)
    assert rows[0]['property_name_raw']=='glass transition temperature'
    assert rows[2]['review_fields'] and rows[2]['model_raw_observation']==observations[2]
    assert rows[3]['table_id']==data['tables'][0]['table_id']
    assert rows[4]['value_raw']=='0'
    assert {'missing_property_or_value','malformed_observation'} <= {i['reason'] for i in issues}


@pytest.mark.parametrize('outcome',['complete','partial','failure'])
def test_default_calls_once_exports_partial_and_never_silently_retries(tmp_path,outcome):
    data=source(); root=tmp_path/'input'; doc=root/data['document_id']; doc.mkdir(parents=True)
    (doc/'source_extraction.json').write_text(json.dumps(data),encoding='utf8')
    config=tmp_path/'config.yaml'
    config.write_text('stages:\n  stage4_property:\n    max_tokens: 64000\n',encoding='utf8')
    calls=[]
    class Client:
        last_raw_response=None
        def call_json(self,**request):
            calls.append(request)
            if outcome=='failure': raise RuntimeError('test transport failure')
            return SimpleNamespace(data={'observations':[{'property':'Tg','value':'120','material':'A'}],
                                         'has_more':outcome=='partial'})
    out=tmp_path/'output'
    result=run(root,out,config_path=config,client_factory=Client,retry_review=True)
    assert len(calls)==1 and result['api_requests_this_run']==1
    assert result['pending_packets']==(0 if outcome=='complete' else 1)
    assert json.loads(calls[0]['user_message'])['packet']['extraction_scope']=='entire_article'
    assert calls[0]['max_tokens']==64000
    catalog=json.loads(calls[0]['user_message'])['packet']['property_catalog']
    molecular=next(t for t in catalog if t['property_key']=='molecular_weight')
    assert 'mn' in molecular['aliases'] and 'Mn' in molecular['subtype_examples']
    assert molecular['definition']['source_field']=='average_molecular_weight'
    saved=json.loads((out/'sources'/data['document_id']/'source_extraction.json').read_text(encoding='utf8'))
    validate_source_result(saved)
    model=[r for r in saved['observations'] if r['observation_id'].startswith('model_article_')]
    assert len(model)==(0 if outcome=='failure' else 1)
    exported=[json.loads(l) for l in (Path(result['export_dir'])/'model_extractions.jsonl').read_text(encoding='utf8').splitlines()]
    assert exported==model
    resumed=run(root,out,config_path=config,client_factory=Client,resume=True,retry_review=True)
    assert len(calls)==1 and resumed['api_requests_this_run']==0
    assert resumed['pending_packets']==result['pending_packets']


def test_catalog_subtype_survives_export_without_blocking_unknown_properties():
    data=source()
    target='specialized_property_vocabulary:molecular_weight'
    catalog=[{'target_id':target,'standard_definitions':[
        {'key':'number_average_molecular_weight','aliases':['mn']},
        {'key':'weight_average_molecular_weight','aliases':['mw']}]}]
    packet=build_packets(data,context_mode='article_once',property_catalog=catalog)[0]
    rows,_,_=validate_article_response(data,packet,{'observations':[
        {'property':'Mn','standard_property_name':'molecular_weight','property_subtype':'Mn','target_id':target,'value':'30000'},
        {'property':'Mw','standard_property_name':'molecular_weight','property_subtype':'Mw','target_id':target,'value':'30000'},
        {'property':'novel response','target_id':'unknown','value':'strong'}]},[target])
    assert len(rows)==3 and len({r['observation_id'] for r in rows})==3
    assert rows[0]['standard_property_code']=='STD:number_average_molecular_weight'
    assert rows[1]['standard_property_code']=='STD:weight_average_molecular_weight'
    assert rows[0]['property_name_raw']=='Mn' and rows[0]['property_subtype']=='Mn'
    assert rows[2]['extraction_status']=='usable' and rows[2]['standard_property_name'] is None
