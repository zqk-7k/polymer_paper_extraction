"""Fresh original Stage2 vs fixed agent1; shared Stage3, grouped N/T, R, 5 and raw 6."""
import argparse,os,traceback
from copy import deepcopy
from common import *
from directory_adapter import source_directory,fresh_stage3_base
from identity import build_identity
from stage3_completion import apply as complete_stage3
from packets import stage3_packet
from compact_packets import build_packets
from output_executor import request
from mapping_contract import GUIDANCE,read_table,finalize_mapping
from table_transport import INSTRUCTION,TEXT_INSTRUCTION,restore_response
from evidence_adapter import normalize_condition_refs,normalize_rule_refs,alternative_state
from axis_adapter import align as align_axis
from citation_spacing import align as align_spacing
from citation_continuations import align as align_continuations
from condition_evidence import available_ids
from condition_branch import adapt as adapt_branch
from field_groups import owner as field_owner
from evidence_registry import registry
from unified_directory import envelope
from component_header_adapter import inherit
from finalize import observation_record,finish
from stage4r import reconcile,source_index
from handoff import build_stage5_handoff,split_handoff
import prompts
from intake_v2 import response as intake_response,table_response
from live_receiver import prepare_tables,receive
from role_contract import GUIDANCE as ROLE_GUIDANCE

def restore_extra(data,mapping):
    restored,unknown=restore_response(data,mapping)
    def visit(v):
        if isinstance(v,list):return [visit(x) for x in v]
        if isinstance(v,dict):return {k:(mapping.get(x,x) if k=='source_id' and isinstance(x,str) else visit(x)) for k,x in v.items()}
        return v
    return visit(restored),unknown

def enrich_tables(paper,tasks):
    supplied=read(OUT/'inputs'/('reference_no_'+paper)/'table_evidence.json')
    for task in tasks:
        tid=task['source_table']['table_id'];task.update(paper=paper,table_id=tid)
        packet=task['packet'];evidence=supplied.get(tid)
        sources=deepcopy(evidence['sources']) if evidence else []
        # General tables receive original footnotes and the exact available prose slices.
        if not evidence:
            sources=[{'source_id':tid+':ocr_footnote:'+str(i),'text':n,'kind':'ocr_footnote','table_id':tid}
                     for i,n in enumerate(task['source_table'].get('notes',[])) if isinstance(n,str)]
        known={s['source_id'] for s in sources}
        for key in ('related_blocks','shared_methods'):
            for b in packet.get(key,[]):
                if b['block_id'] not in known:
                    sources.append({'source_id':b['block_id'],'text':b.get('text',''),'kind':'text'})
                    known.add(b['block_id'])
        packet['evidence_sources']=sources
        packet['evidence_bundle_version']=digest(sources)
    return tasks

def extract(paper,arm,worker_lease=None):
    check_frozen();check_protected();dest=folder(paper,arm);dest.mkdir(parents=True,exist_ok=True)
    from run_lifecycle import has_failures
    if (dest/'run_result.json').exists() and read(dest/'run_result.json').get('status')=='completed' and not has_failures(dest):return
    from run_lifecycle import Lease
    lease=worker_lease or Lease(dest/'branch.lock').acquire()
    try:
        # Archive active failure flags on explicit resume; retain original calls/responses.
        for name in ('task_failures.json','branch_failure.json'):
            path=dest/name
            if path.exists():
                write(dest/'failure_history'/(digest(read(path))+'.'+name),read(path))
                path.unlink()
        raw=read(OUT/'inputs'/('reference_no_'+paper)/'stage0_blocks.json');write(dest/'stage0_blocks.json',raw)
        catalog=read(OUT/'target_catalog.json')
        stage2,seed=source_directory(paper,arm,raw)
        stage3=fresh_stage3_base(dest,raw,stage2,seed)
        packet=stage3_packet(raw,build_identity(stage2,stage3));write(dest/'stage3_gap_input.json',packet)
        data=request(dest,'stage3_gap','stage3_sample_process',prompts.STAGE3,packet,config()['stage3_max_output_tokens'],native=True).data
        completed,identity,audit=complete_stage3(raw,stage2,stage3,data)
        write(dest/'unified_directory_after_stage3.json',envelope(stage2,completed,arm))
        write(dest/'evidence_registry.json',registry(raw))
        write(dest/'stage3_process.json',completed);write(dest/'identity.json',identity);write(dest/'stage3_completion_audit.json',audit)
        assert {s['sample_id'] for s in seed['samples']}.issubset({s['sample_id'] for s in identity['samples']})
        n_tasks,t_tasks,s5_tasks,packing=build_packets(raw,identity,catalog);enrich_tables(paper,t_tasks)
        t_tasks,raw=prepare_tables(t_tasks,raw)
        write(dest/'stage0_blocks.json',raw);write(dest/'evidence_registry.json',registry(raw))
        plan={'stage4n':n_tasks,'stage4t':t_tasks,'stage5':s5_tasks,'fresh_stage3_per_arm':True}
        write(dest/'task_plan.json',plan);write(dest/'packing_audit.json',packing)
        n=[];t=[];extra=[];tables={};methods=[];unresolved=[];adaptations=[]
        blocks,cells=source_index(raw);target_ids={x['target_id'] for x in catalog['targets']};sample_ids={s['sample_id'] for s in identity['samples']}
        def record(o,ref,task):
            def expand(value):
                if isinstance(value,list):return [expand(x) for x in value]
                if isinstance(value,dict):
                    shared=task['packet'].get('shared_evidence_refs',{})
                    if value.get('evidence_ref_id') in shared:return deepcopy(shared[value['evidence_ref_id']])
                    return {k:expand(v) for k,v in value.items()}
                return value
            o=expand(o)
            if task.get('allowed_target_ids') is not None:o['task_allowed_target_ids']=task['allowed_target_ids']
            allowed=available_ids(task['packet'],task['owned_source_ids'])|{s['source_id'] for s in task['packet'].get('evidence_sources',[])}
            o,changes=align_spacing(o,blocks,allowed);o,more=align_continuations(o,blocks,allowed)
            o,branch=adapt_branch(o,blocks,cells,allowed)
            if changes or more:adaptations.append({'ref':ref,'citation_changes':changes+more})
            row=observation_record(o,ref,raw,identity,catalog,task['owned_source_ids'],allowed)
            row['field_owner_stage']=field_owner(row['target_id']) if row.get('target_id') else None
            row['source_processing_stage']='stage4t' if o.get('source_cell_id') else 'stage5' if task['task_id'].startswith('s5_') else 'stage4n'
            row['condition_branch_adaptation']=branch
            return row
        for task in t_tasks:
            data=request(dest,task['task_id'],'stage4t_table_interpretation',prompts.STAGE4T+INSTRUCTION+GUIDANCE+ROLE_GUIDANCE,
                         task['packet'],config()['stage4t_max_output_tokens']).data
            rows,ta=receive(data,task,raw,identity,catalog,'stage4t');tables[task['table_id']]=ta
            t.extend(rows)
            write(dest/'stage4t_records.json',t);write(dest/'table_interpretations.json',tables)
        for task in n_tasks:
            data=request(dest,task['task_id'],'stage4_property',prompts.STAGE4N+TEXT_INSTRUCTION,
                         task['packet'],config()['stage4n_max_output_tokens']).data
            data=intake_response(data)
            rows,_=receive(data,task,raw,identity,catalog,'stage4n');n.extend(rows)
            unresolved.append({'stage':'stage4n','task_id':task['task_id'],'unresolved':data['unresolved']})
            write(dest/'stage4n_records.json',n)
        t_n=[r for r in t if r.get('field_owner_stage')!='stage5']
        t_s5=[r for r in t if r.get('field_owner_stage')=='stage5']
        write(dest/'table_field_routes.json',{'stage4n_record_ids':[r['record_id'] for r in t_n],
            'stage5_record_ids':[r['record_id'] for r in t_s5],
            'shared_structural_interpretation_once':True})
        merged,ledger,conflicts=reconcile(n+t_n+t_s5)
        write(dest/'stage4r_before_stage5.json',{'records':merged,'ledger':ledger,'conflicts':conflicts,'actual_execution_before_stage5':True})
        handoffs=[]
        for task in s5_tasks:
            packet,ha=build_stage5_handoff(task,merged,t_tasks);handoffs.append({'task_id':task['task_id'],**ha})
            system=prompts.STAGE5+TEXT_INSTRUCTION+'\nPreserve upstream record statuses. If handoff_partition.new_prose_observations_allowed is false, return observations:[]; only attach explicitly evidenced methods to the supplied records.\n'
            parts=split_handoff(packet,config()['group_input_utf8_bytes']-1000,len(system.encode()))
            for part_index,packet in enumerate(parts):
                tid=task['task_id'] if len(parts)==1 else task['task_id']+f'_part{part_index+1}'
                write(dest/'actual_stage5_packets'/(tid+'.json'),packet)
                data=request(dest,tid,'stage5_characterization',system,packet,config()['stage5_max_output_tokens']).data
                data=intake_response(data)
                if part_index and data['observations']:raise ValueError('Stage5 repeated observations outside partition ownership')
                actual_task={**task,'task_id':tid,'packet':packet}
                rows,_=receive(data,actual_task,raw,identity,catalog,'stage5');extra.extend(rows)
                methods.extend({'task_id':tid,**m} for m in data['methods'] if isinstance(m,dict))
                unresolved.append({'stage':'stage5','task_id':tid,'unresolved':data['unresolved']})
            write(dest/'stage5_records.json',extra)
        write(dest/'stage5_handoff_audit.json',handoffs);write(dest/'unresolved_model_claims.json',unresolved)
        write(dest/'citation_adaptation_audit.json',adaptations)
        result=finish(paper,arm,raw,identity,catalog,n,t,extra,tables,methods)
        write(dest/'engineering_acceptance.json',{'full_chain_executed':True,'agent1_ids_preserved':True if arm=='B' else None,
            'R_executed_before_5':True,'raw_stage6_contract':True,'legacy_numeric_stage6_not_run':True,
            'production_optional_workflow':True,'quality_review':False,'format_conversion':False})
        if (dest/'task_failures.json').exists():
            final_status=read(dest/'run_result.json');final_status['status']='incomplete';final_status['failed_tasks']=read(dest/'task_failures.json')
            write(dest/'run_result.json',final_status)
            validation=read(dest/'stage6_validation.json');validation['all_model_tasks_completed']=False
            write(dest/'stage6_validation.json',validation)
            raise RuntimeError('Independent tasks completed; failed tasks require recovery, partial output preserved')
        check_frozen();check_protected();print('BRANCH COMPLETE',arm,paper,result,flush=True)
    finally:
        if worker_lease is None:lease.release()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--paper',choices=PAPERS,required=True);p.add_argument('--arm',choices=('A','B'),required=True)
    args=p.parse_args()
    try:extract(args.paper,args.arm)
    except Exception as e:
        write(folder(args.paper,args.arm)/'branch_failure.json',{'error_type':type(e).__name__,'traceback':traceback.format_exc(),'historical_substitution':False})
        print(args.arm,args.paper,'FAILED',type(e).__name__,flush=True);raise
