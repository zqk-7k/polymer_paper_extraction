from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from stages.sample_catalog import digest
from stages.source_table_extraction import build_source_extraction
from stages.source_model_extraction import build_packets, validate_response, source_fingerprint, attach_bundle
from tools.source_extraction_export import validate_source_result, build_source_export
from tools.run_source_workflow import run as run_workflow


def run(*args, **kwargs):
    # This suite explicitly exercises the retained legacy paragraph workflow.
    kwargs.setdefault('context_mode', 'local')
    return run_workflow(*args, **kwargs)


def fixture():
    return build_source_extraction({'document_id':'reference_no_unseen', 'elements':[
        {'block_id':'H1','type':'title','text':'Synthesis of monomer NEW-Q','source_block_index':0},
        {'block_id':'P1','type':'text','text':'The purified crystals had a melting point of 147 °C by DSC.', 'source_block_index':1},
        {'block_id':'P2','type':'text','text':'No tensile strength was measured.', 'source_block_index':2},
        {'block_id':'R1','type':'text','text':'Melting point 999 C.', 'section':'References', 'source_block_index':3}]})


def response():
    def cite(text,bid='P1'):
        return {'block_id':bid,'quote':text}
    return {'observations':[{'property':cite('melting point'),'value':cite('147'),
         'material':cite('NEW-Q','H1'),'unit':cite('°C'),
         'conditions':[{'name':'method','evidence':cite('DSC')}],
         'target_id':'property_vocabulary:melting_temperature','assertion':'reported','rationale':'Explicit product melting point under its synthesis title.'}],
         'has_more':False,'unresolved':[]}


def bundle(data, result=None):
    packet=build_packets(data)[0]
    return {'source_fingerprint':source_fingerprint(data),'packet_options':{},
            'target_ids':['property_vocabulary:melting_temperature'],
            'responses':{packet['packet_id']:{'request_packet_sha256':digest(packet),'response':result or response()}}}


def test_unseen_material_cross_heading_conditions_and_export(tmp_path):
    data=fixture(); packets=build_packets(data)
    assert len(packets)==2 and packets[0]['evidence_blocks'][1]['block_id']=='H1'
    result=attach_bundle(data,bundle(data))
    row=result['observations'][0]
    assert row['value_raw']=='147' and row['article_sample_label_raw']=='NEW-Q'
    assert row['sample_id'] is None and row['condition_context_raw'][0]['value_raw']=='DSC'
    assert row['source_support'][0]['block_id']=='H1'
    assert result['model_text_coverage']['pending_packet_ids']==[packets[1]['packet_id']]
    validate_source_result(result)
    root=tmp_path/'source'; (root/data['document_id']).mkdir(parents=True)
    (root/data['document_id']/'source_extraction.json').write_text(json.dumps(result),encoding='utf8')
    assert build_source_export(root,tmp_path/'export')['counts']['usable_property']==1
    result['source_context_blocks'][0]['text']='Changed title'
    with pytest.raises(ValueError,match='Model source changed'):
        validate_source_result(result)


def test_bad_record_is_local_missing_optional_fields_do_not_block_value():
    data=fixture(); packet=build_packets(data)[0]; result=response()
    bad=deepcopy(result['observations'][0]); bad['value']['quote']='999'
    result['observations'].append(bad)
    good=result['observations'][0]; good['unit']=None;good['material']=None;good['target_id']='unknown'
    rows,issues,complete=validate_response(data,packet,result,[])
    assert len(rows)==1 and complete and rows[0]['unit_raw'] is None
    assert rows[0]['model_target_ids']==[] and rows[0]['unresolved_context_fields']==['material_unresolved']
    assert {i['reason'] for i in issues}=={'unknown_target_preserved_as_raw','source_quote_missing_or_ambiguous'}


def test_conditions_are_not_silently_invented_and_incomplete_output_stays_pending():
    data=fixture(); result=response(); result['has_more']=True
    result['observations'][0]['conditions'][0]['evidence']['block_id']='not_sent'
    output=attach_bundle(data,bundle(data,result))
    assert not output['observations']
    assert len(output['model_text_coverage']['pending_packet_ids'])==2
    assert any(i['reason']=='citation_outside_request' for i in output['model_text_coverage']['issues'])


def test_long_blocks_cover_every_character_without_dropping_context():
    data=fixture(); data['source_blocks'][0]['text']='X '*1400
    packets=build_packets(data,max_chars=100,context_chars=100)
    spans=[(p['focal_start'],p['focal_end']) for p in packets if p['focal_block_id']=='P1']
    assert spans[0][0]==0 and spans[-1][1]==2800
    assert all(a[1]==b[0] for a,b in zip(spans,spans[1:]))
    assert all(not p['omitted_context_ids'] for p in packets)
    assert any(p['context_budget_exceeded'] for p in packets)


def test_compact_table_preserves_every_cell_and_notes_even_over_soft_budget():
    from stages.source_model_extraction import compact_table
    data=fixture()
    table={'table_id':'T1','caption':'Table 1. Full original table','table_notes':['a: measured in nitrogen'],
           'nearby_text_blocks':[{'block_id':'P1'}],
           'cells':[{'cell_id':f'T1:r{i}:c0','table_id':'T1','row_index':i,'column_index':0,
                     'row_span':2 if i==0 else 1,'column_span':1,'is_header':i==0,'text':'raw value '+str(i)} for i in range(100)]}
    data['tables']=[table]
    packet=build_packets(data,max_chars=100,context_chars=100)[0]
    compact=packet['related_tables'][0]
    assert not packet['omitted_context_ids'] and packet['context_budget_exceeded']
    assert compact['table_notes']==table['table_notes'] and compact==compact_table(table)
    restored=[{**dict(zip(compact['cell_columns'],row)),'table_id':'T1'} for row in compact['cells']]
    assert restored==table['cells']


def test_resume_retries_failed_call_without_repeating_successful_call(tmp_path):
    data=fixture(); source=tmp_path/'source'; (source/data['document_id']).mkdir(parents=True)
    (source/data['document_id']/'source_extraction.json').write_text(json.dumps(data),encoding='utf8')
    calls=[]
    class Client:
        last_raw_response=None
        def call_json(self,**request):
            focal=json.loads(request['user_message'])['packet']['focal_block_id']
            calls.append(focal)
            if len(calls)==2:
                raise TimeoutError()
            return SimpleNamespace(data=response() if focal=='P1' else {'observations':[],'unresolved':[],'has_more':False})
    first=run(source,tmp_path/'out',model='test',client_factory=Client)
    assert first['pending_packets']==1 and first['export_counts']['usable_property']==1
    second=run(source,tmp_path/'out',model='test',client_factory=Client,resume=True)
    assert calls==['P1','P2','P2'] and second['pending_packets']==0
    assert second['export_counts']['usable_property']==1 and not second['goal_complete']
    with pytest.raises(ValueError,match='Resume contract differs'):
        run(source,tmp_path/'out',model='other',client_factory=Client,resume=True)


def test_unknown_response_structure_never_counts_as_completed():
    data=fixture()
    rows,issues,complete=validate_response(data,build_packets(data)[0],{'observations':[]},[])
    assert not rows and not complete and issues[0]['reason']=='invalid_response_schema'


def test_truncation_splits_focal_range_preserves_context_and_resumes(tmp_path):
    from llm_client import LLMOutputTruncatedError
    data=fixture(); data['source_blocks'][0]['text'] += ' Context remains available.'*12
    source=tmp_path/'source'; (source/data['document_id']).mkdir(parents=True)
    (source/data['document_id']/'source_extraction.json').write_text(json.dumps(data),encoding='utf8')
    calls=[]
    class Client:
        last_raw_response=None
        def call_json(self,**request):
            packet=json.loads(request['user_message'])['packet'];calls.append(packet)
            if len(calls)==1:
                raise LLMOutputTruncatedError('fixture')
            return SimpleNamespace(data={'observations':[],'unresolved':[],'has_more':False})
    first=run(source,tmp_path/'out',model='test',client_factory=Client,max_requests=1)
    assert first['pending_packets']==3
    second=run(source,tmp_path/'out',model='test',client_factory=Client,resume=True)
    assert second['pending_packets']==0 and len(calls)==4
    assert calls[0]['evidence_blocks']==calls[1]['evidence_blocks']==calls[2]['evidence_blocks']
    assert calls[1]['focal_end']==calls[2]['focal_start']


def test_stage0_entry_needs_no_previous_stages_or_manual_text_reviews(tmp_path):
    source=tmp_path/'source'; (source/'reference_no_new').mkdir(parents=True)
    raw={'document_id':'reference_no_new','elements':[{'block_id':'P1','type':'text','text':'A material is described.'}]}
    (source/'reference_no_new/stage0_blocks.json').write_text(json.dumps(raw),encoding='utf8')
    class Client:
        last_raw_response=None
        def call_json(self,**request):
            return SimpleNamespace(data={'observations':[],'unresolved':[],'has_more':False})
    result=run(source,tmp_path/'out',model='test',client_factory=Client,input_kind='stage0')
    assert result['pending_packets']==0 and result['original_inputs_unchanged']


def test_tampered_published_model_result_is_rejected():
    data=fixture();result=attach_bundle(data,bundle(data))
    result['observations'][0]['article_sample_label_raw']='Other material'
    with pytest.raises(ValueError,match='source spans'):
        validate_source_result(result)


def test_unique_quote_recovers_wrong_model_offset_but_not_ambiguous_quote():
    from stages.source_model_extraction import resolve_citation
    packet=build_packets(fixture())[0]
    assert resolve_citation({'block_id':'P1','quote':'147','start':999},packet)['start']==45
    packet['evidence_blocks'][0]['text']='147 and 147'
    with pytest.raises(ValueError,match='ambiguous'):
        resolve_citation({'block_id':'P1','quote':'147','start':999},packet)


def test_no_value_comparison_is_reviewed_not_published():
    data=fixture();data['source_blocks'][0]['text']='NEW-Q had different surface energies.'
    result=response();result['observations']=[{'property':{'block_id':'P1','quote':'surface energies'},
        'value':{'block_id':'P1','quote':'different surface energies'},'assertion':'reported','rationale':'comparison'}]
    rows,issues,_=validate_response(data,build_packets(data)[0],result,[])
    assert not rows and issues[0]['reason']=='comparison_without_concrete_value'


def test_metadata_and_figure_gaps_are_accounted_for():
    data=fixture();data['source_blocks'].append({'block_id':'DOI','type':'text','text':'DOI: 10.1000/example'})
    data['source_figure_blocks']=[{'block_id':'I1','type':'image','caption':'Figure 1. Curves','image_path':'source.jpg'}]
    result=attach_bundle(data,bundle(data))
    coverage=result['model_text_coverage']
    assert any(b['reason']=='doi_metadata' for b in coverage['excluded_blocks'])
    assert coverage['figure_locations'][0]['figure_block_id']=='I1'
    assert coverage['figure_review_queue']==[]
    assert not coverage['figure_value_extraction_required']
    assert not coverage['all_properties_complete']


def test_failure_circuit_preserves_export_and_pending_work(tmp_path):
    data=fixture();source=tmp_path/'source';(source/data['document_id']).mkdir(parents=True)
    (source/data['document_id']/'source_extraction.json').write_text(json.dumps(data),encoding='utf8')
    class Client:
        last_raw_response=None
        def call_json(self,**request):
            raise TimeoutError()
    result=run(source,tmp_path/'out',model='test',client_factory=Client,max_consecutive_failures=1)
    assert result['api_requests_this_run']==1 and result['stopped_after_consecutive_failures']
    assert result['pending_packets']==2
    assert (tmp_path/'out/export_001/model_text_coverage.jsonl').exists()


def test_offline_replay_uses_actual_request_without_any_client(tmp_path):
    data=fixture();source=tmp_path/'source';(source/data['document_id']).mkdir(parents=True)
    (source/data['document_id']/'source_extraction.json').write_text(json.dumps(data),encoding='utf8')
    class Client:
        last_raw_response=None
        def call_json(self,**request):
            return SimpleNamespace(data=response())
    run(source,tmp_path/'first',model='test',client_factory=Client,max_requests=1)
    def forbidden():
        raise AssertionError('Offline must never instantiate a client')
    result=run(source,tmp_path/'replay',model='test',client_factory=forbidden,
               replay_from=tmp_path/'first',offline=True)
    assert result['api_requests_this_run']==0 and result['export_counts']['usable_property']==1


def test_citation_schema_repair_is_bounded_and_keeps_original_response(tmp_path):
    data=fixture();source=tmp_path/'source';(source/data['document_id']).mkdir(parents=True)
    (source/data['document_id']/'source_extraction.json').write_text(json.dumps(data),encoding='utf8')
    calls=[]
    class Client:
        last_raw_response=None
        def call_json(self,**request):
            payload=json.loads(request['user_message']);calls.append(payload)
            result=response()
            if len(calls)==1:
                result['observations'][0]['value']='147'
            return SimpleNamespace(data=result)
    result=run(source,tmp_path/'out',model='test',client_factory=Client,max_requests=2,retry_review=True)
    assert len(calls)==2 and 'validation_errors' in calls[1]
    assert result['export_counts']['usable_property']==1
    saved=json.loads((tmp_path/'out/sources/reference_no_unseen/model_text_bundle.json').read_text(encoding='utf8'))
    record=next(iter(saved['responses'].values()))
    assert record['repair_history']['original_response']['observations'][0]['value']=='147'


def test_repeated_material_quote_is_located_near_value_and_scope_exception_preserved():
    data=fixture();data['source_blocks'][0]['text']='All polymers except R1 were amorphous. R1 was crystalline.'
    result={'observations':[{'property':{'block_id':'P1','quote':'were amorphous'},
        'value':{'block_id':'P1','quote':'amorphous'},'material':{'block_id':'P1','quote':'All polymers'},
        'assertion':'reported','rationale':'Categorical result with exception'},
        {'property':{'block_id':'P1','quote':'was crystalline'},
         'value':{'block_id':'P1','quote':'crystalline'},'material':{'block_id':'P1','quote':'R1'},
         'assertion':'reported','rationale':'Explicitly named material'}], 'unresolved':[],'has_more':False}
    rows,issues,_=validate_response(data,build_packets(data)[0],result,[])
    assert len(rows)==2 and not issues
    assert rows[0]['article_sample_key'] is None and rows[0]['material_scope_qualifier']['text'].startswith('except R1')
    assert rows[1]['source_spans']['sample']['start']==39


@pytest.mark.parametrize('property_name,value,unit',[
    ('relative permittivity','3.25',None),
    ('oxygen permeability','2.1 to 3.7','Barrer'),
    ('IR band',r'1 7 7 8',r'cm^{-1}'),
    ('solubility','insoluble',None),
])
def test_new_properties_and_raw_notation_use_same_contract(property_name,value,unit):
    data=fixture();text=f'For New-R: {property_name} = {value}'+(' '+unit if unit else '')
    data['source_blocks'][0]['text']=text
    def cite(s): return {'block_id':'P1','quote':s}
    result={'observations':[{'property':cite(property_name),'value':cite(value),'material':cite('New-R'),
            'unit':cite(unit) if unit else None,'assertion':'reported','rationale':'Direct source assignment',
            'target_id':None}], 'unresolved':[],'has_more':False}
    rows,issues,_=validate_response(data,build_packets(data)[0],result,[])
    assert not issues and rows[0]['value_raw']==value and rows[0]['value_normalized'] is None


def test_repair_cannot_erase_usable_neighbor_and_chained_replay_preserves_cache(tmp_path):
    data=fixture();source=tmp_path/'source';(source/data['document_id']).mkdir(parents=True)
    (source/data['document_id']/'source_extraction.json').write_text(json.dumps(data),encoding='utf8')
    calls=[]
    class Client:
        last_raw_response=None
        def call_json(self,**request):
            calls.append(request)
            if len(calls)>1:
                return SimpleNamespace(data={'observations':[],'unresolved':[],'has_more':False})
            result=response();result['observations'].append({'value':'malformed'})
            result['observations'][1].update(assertion='reported',rationale='Needs repair')
            return SimpleNamespace(data=result)
    first=run(source,tmp_path/'first',model='test',client_factory=Client,max_requests=2,retry_review=True)
    assert first['export_counts']['usable_property']==1
    replay=run(source,tmp_path/'replay',model='test',offline=True,replay_from=tmp_path/'first')
    again=run(source,tmp_path/'again',model='test',offline=True,replay_from=tmp_path/'replay')
    assert replay['pending_packets']==again['pending_packets']==first['pending_packets']
    assert again['export_counts']['usable_property']==1
