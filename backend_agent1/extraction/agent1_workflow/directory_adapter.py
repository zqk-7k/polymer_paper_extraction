"""Two explicit directory providers. Agent1 errors fail closed, never fall back to A."""
from copy import deepcopy
from common import *
from identity import build_identity
from catalog import norm
from execution import native_client
from llm_client import load_pipeline_config
from prompt_loader import PromptLoader
from schema.polymer_schema import (Stage0Document,Stage1Document,Stage2Document,
    Stage2Provenance,MentionChunkResponse,PolymerEntityResponse,SampleProcessResponse)
from stages import stage1_material_mention as s1,stage2_polymer_entity as s2,stage3_sample_process as s3
from unified_directory import envelope

class ImportedStage2(Stage2Document):
    provenance: Stage2Provenance | dict

def native_document(raw):
    # Supplemental legend records have their own provenance, not OCR block indices.
    # Keep them in the raw evidence store/downstream packets; the legacy identity
    # schema accepts original OCR blocks and their table_notes, not synthetic indices.
    view=deepcopy(raw);view['elements']=[b for b in view['elements'] if 'source_block_index' in b]
    for b in view['elements']:b.pop('table_note_evidence',None)
    return Stage0Document.model_validate(view)

def source_directory(paper,arm,raw):
    dest=folder(paper,arm);src=OUT/'inputs'/('reference_no_'+paper)
    if arm=='B':
        required=['agent1_entities.json','agent1_directory_samples.json','agent1_handoff.json']
        if not all((src/n).is_file() for n in required):
            write(dest/'directory_failure.json',{'reason':'agent1_files_missing','valid_B':False,'fallback':False})
            raise FileNotFoundError('Agent1 source bundle incomplete; no fallback')
        stage2=read(src/required[0]);seed=read(src/required[1]);handoff=read(src/required[2])
        assert stage2['document_id']==seed['document_id']==raw['document_id']
        ImportedStage2.model_validate(stage2)
        assert {s['sample_id'] for s in seed['samples']}=={s['sample_id'] for s in handoff['identities']}
        assert all(s['refers_to_entity'] in {e['entity_id'] for e in stage2['polymer_entities']} for s in seed['samples'])
        write(dest/'stage2_entities.json',stage2);write(dest/'agent1_handoff.json',handoff)
        write(dest/'unified_directory.json',envelope(stage2,seed,'agent1_actual_export'))
        write(dest/'directory_seed.json',seed)
        write(dest/'directory_provenance.json',{'source':'actual_agent1_export_conversion','valid_B':True,'fallback':False,
            'input_sha256':sha(src/required[0]),'sample_input_sha256':sha(src/required[1]),
            'handoff_sha256':sha(src/required[2]),'historical_generation_cost':None,
            'reviewed_import_scope':'Actual existing export conversion, no historical Stage2/Stage3 directory copied'})
        return stage2,seed
    cfg=load_pipeline_config(Path(config()['pipeline_config']));doc=native_document(raw)
    for i,(module,response_schema,name) in enumerate(((s1,MentionChunkResponse,'stage1_mentions.json'),
                                                     (s2,PolymerEntityResponse,'stage2_entities.json'))):
        if (dest/name).exists():continue
        stage=module.STAGE_ID;settings=cfg['stages'][stage]
        prompt=PromptLoader().render_stage_prompt(settings['prompt_id'],response_schema,
            expected_stage=stage,expected_output_schema=module.OUTPUT_SCHEMA_VERSION)
        client=native_client(dest,stage)
        options=dict(max_tokens=min(settings['max_tokens'],config()['native_max_output_tokens']),
                     max_validation_retries=2 if i else 1,preview_relaxed=True)
        if i==0:
            output=s1.extract_material_mentions(doc,client,prompt,max_chunk_chars=settings['max_chunk_chars'],
                primary_sections=tuple(settings['input_sections']),fallback_sections=tuple(settings['fallback_sections']),**options)
        else:
            output=s2.extract_polymer_entities(doc,Stage1Document.model_validate(read(dest/'stage1_mentions.json')),client,prompt,
                input_sections=tuple(settings['input_sections']),max_input_chars=settings['max_input_chars'],**options)
        write(dest/name,output.model_dump(mode='json'))
    stage2=read(dest/'stage2_entities.json')
    seed={'document_id':raw['document_id'],'samples':[],'process_steps':[],'identity_contexts':[],'protocol_contexts':[]}
    write(dest/'directory_seed.json',seed)
    write(dest/'unified_directory.json',envelope(read(dest/'stage2_entities.json'),seed,'original_stage2'))
    write(dest/'directory_provenance.json',{'source':'fresh_original_stage1_stage2','agent1_read':False,
                                          'fallback':False,'input_sha256':digest(raw)})
    return stage2,seed

def merge_native_stage3(native,seed):
    """Retain supplied catalog IDs; match unique same-entity labels only, preserving ambiguity."""
    result=deepcopy(native);samples=deepcopy(seed['samples']);contexts=deepcopy(seed.get('identity_contexts',[]))
    ids={s['sample_id'] for s in samples};migration=[];renamed={}
    for sample in native['samples']:
        parent_matches=[s for s in seed['samples'] if s.get('refers_to_entity')==sample.get('refers_to_entity')
                        and norm(s.get('sample_label_raw')) and norm(s.get('sample_label_raw'))==norm(sample.get('sample_label_raw'))]
        found=[s for s in samples if s.get('refers_to_entity')==sample.get('refers_to_entity')
               and norm(s.get('sample_label_raw')) and norm(s.get('sample_label_raw'))==norm(sample.get('sample_label_raw'))
               and not s.get('state_description') and not sample.get('state_description')]
        if len(found)==1:
            sid=found[0]['sample_id'];found[0]['stage3_native_evidence']=deepcopy(sample.get('evidence'))
        else:
            new=deepcopy(sample);sid=sample['sample_id']
            if sid in ids:sid='s'+str(3000+len(samples))
            while sid in ids:sid='s'+str(int(sid[1:])+1)
            new['sample_id']=sid
            if len(parent_matches)==1 and sample.get('state_description'):
                new['parent_sample_id']=parent_matches[0]['sample_id']
                new['parent_relation_basis']='same_entity_and_literal_sample_label_with_explicit_state'
                inherited=next((c for c in seed.get('identity_contexts',[]) if c['sample_id']==parent_matches[0]['sample_id']),None)
                if inherited:contexts.append({**deepcopy(inherited),'sample_id':sid,'inherited_directory_context_from':parent_matches[0]['sample_id']})
            samples.append(new);ids.add(sid)
        renamed[sample['sample_id']]=sid
        migration.append({'native_sample_id':sample['sample_id'],'candidate_sample_id':sid,
            'basis':'unique_same_entity_and_label_no_state' if len(found)==1 else 'native_sample_preserved'})
    def remap(value,key=None):
        if isinstance(value,list):return [remap(v,key) for v in value]
        if isinstance(value,dict):return {k:remap(v,k) for k,v in value.items()}
        return renamed.get(value,value) if isinstance(value,str) and key in ('sample_id','input_sample_ids','output_sample_ids','parent_sample_id') else value
    result.update(samples=samples,process_steps=remap(native.get('process_steps',[])),
                  identity_contexts=contexts,protocol_contexts=[])
    return result,migration

def fresh_stage3_base(dest,raw,stage2,seed):
    path=dest/'stage3_native.json'
    if not path.exists():
        cfg=load_pipeline_config(Path(config()['pipeline_config']));settings=cfg['stages'][s3.STAGE_ID]
        prompt=PromptLoader().render_stage_prompt(settings['prompt_id'],SampleProcessResponse,
            expected_stage=s3.STAGE_ID,expected_output_schema=s3.OUTPUT_SCHEMA_VERSION)
        client=native_client(dest,s3.STAGE_ID)
        original_call=client.call_json
        def call(system,message,**kwargs):
            addition={'source_directory_samples':seed['samples'],
                'directory_identity_contexts':[{'sample_id':x['sample_id'],'identity_source_status':x.get('identity_source_status'),
                    'raw_composition':x.get('raw_composition'),'source_page_raw':x.get('source_page_raw'),
                    'agent1_category':x.get('agent1_category'),'agent1_role':x.get('agent1_role'),
                    'derived_from':x.get('derived_from')} for x in seed.get('identity_contexts',[])],
                'rules':['Retain supplied catalog labels and identities when source supports them.',
                         'Imported page-context evidence locates context only and is not literal proof of the material name. Use the whole article and composition to establish concrete state/property applicability; preserve uncertainty.',
                         'Chemical precursors and final polymers are distinct chemical subjects; do not label a precursor as merely a physical state of its product.',
                         'Polymer networks and restructured products are distinct chemical subjects chemically derived from their base polymer; they are never physical states of the base material such as pressed films.',
                         'No measurements from images; no numerical conversions or property calculations.']}
            return original_call(system,message+'\nSOURCE DIRECTORY CONTEXT\n'+json.dumps(addition,ensure_ascii=False),**kwargs)
        client.call_json=call
        output=s3.extract_samples_processes(native_document(raw),ImportedStage2.model_validate(stage2),client,prompt,
            input_sections=tuple(settings['input_sections']),max_input_chars=settings['max_input_chars'],
            max_tokens=min(settings['max_tokens'],config()['native_max_output_tokens']),max_validation_retries=1,preview_relaxed=True)
        write(path,output.model_dump(mode='json'))
    stage3,migration=merge_native_stage3(read(path),seed)
    write(dest/'stage3_base.json',stage3)
    write(dest/'id_migration.json',{'native_to_candidate':migration,'agent1_to_candidate':[
        {'agent_id':c.get('agent_id'),'sample_id':c['sample_id'],'entity_id':c.get('entity_id'),'identity_key':c.get('identity_key')}
        for c in seed.get('identity_contexts',[])], 'two_arm_ids_forced_equal':False})
    return stage3
