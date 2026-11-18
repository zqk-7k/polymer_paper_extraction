"""Bounded output partitioning, independent task failure isolation, full input retained."""
from copy import deepcopy
from common import *
from execution import request as original_request
from intake_v2 import response as expand_response
from llm_client import LLMJSONResponse

class ResumeOutputPartition(Exception):pass
MAX_SOURCE_PARTITION_DEPTH=3

def request(dest,task_id,stage,system,packet,max_tokens,*,native=False,require_complete=True,_depth=0,_source_depth=0):
    # Field subdivision and source subdivision have independent budgets.
    # Every field split strictly reduces the finite assigned field list; sources
    # halve at most three times (eight output groups), with full input preserved.
    fields=packet.get('target_fields',[])
    sources=packet.get('output_partition',{}).get('source_block_ids') or packet.get('owned_blocks',[])
    may_partition=len(fields)>1 or (len(sources)>1 and _source_depth<MAX_SOURCE_PARTITION_DEPTH)
    try:
        saved_partition=dest/'output_partitions'/(task_id+'.json')
        has_children=len(packet.get('target_fields',[]))>1 or len(packet.get('output_partition',{}).get('source_block_ids') or packet.get('owned_blocks',[]))>1
        if saved_partition.exists() and not (dest/'tasks'/(task_id+'.json')).exists() and has_children and stage in ('stage4_property','stage5_characterization') and may_partition:
            previous=read(saved_partition)
            if previous.get('full_input_preserved') is True and previous.get('depth')==_depth and previous.get('source_depth',0)==_source_depth and previous.get('children')==2 and previous.get('basis') in ('disjoint_assigned_fields','disjoint_output_source_anchors_full_input'):
                # Each child request still validates its exact frozen input signature.
                raise ResumeOutputPartition('Resume verified child requests from prior output partition')
        return original_request(dest,task_id,stage,system,packet,max_tokens,native=native,require_complete=require_complete)
    except Exception as exc:
        # Use this invocation's terminal cause, never stale parent/child attempt files.
        # A transport retry followed by output truncation still permits bounded partitioning.
        truncated=isinstance(exc,ResumeOutputPartition) or getattr(exc,'last_error_type',None)=='LLMOutputTruncatedError'
        if truncated and stage in ('stage4_property','stage5_characterization') and may_partition:
            fields=packet.get('target_fields',[]);children=[]
            if len(fields)>1:
                mid=(len(fields)+1)//2
                for subset in [fields[:mid],fields[mid:]]:
                    p=deepcopy(packet);p['target_fields']=subset
                    p['target_index']={section:[f['target_id'].split(':',1)[1] for f in subset if f['target_id'].startswith(section+':')] for section in packet.get('target_index',{})}
                    p['task_contract']['allowed_target_ids']=[f['target_id'] for f in subset]
                    children.append(p)
                basis='disjoint_assigned_fields'
            else:
                owned=packet.get('output_partition',{}).get('source_block_ids') or [b['block_id'] for b in packet.get('owned_blocks',[])]
                if len(owned)>1:
                    mid=(len(owned)+1)//2
                    for ids in [owned[:mid],owned[mid:]]:
                        p=deepcopy(packet);p['output_partition']={'source_block_ids':ids,'full_input_preserved':True}
                        children.append(p)
                basis='disjoint_output_source_anchors_full_input'
            if children:
                write(dest/'output_partitions'/(task_id+'.json'),{'basis':basis,'children':len(children),'depth':_depth,'full_input_preserved':True,
                    'source_depth':_source_depth,'maximum_source_partition_depth':MAX_SOURCE_PARTITION_DEPTH,
                    'resumed_existing_partition':isinstance(exc,ResumeOutputPartition),'child_requests_validate_exact_inputs':True})
                joined={'observations':[],'methods':[],'unresolved':[],'has_more':False}
                for i,p in enumerate(children):
                    addition='\nOutput ONLY the assigned target fields. If output_partition is supplied, observation source_block_id must belong to output_partition.source_block_ids; retain complete original input for context.\n'
                    part=request(dest,task_id+f'_outpart{i+1}',stage,system+addition,p,config()['output_truncation_fallback_tokens'],_depth=_depth+1,
                                 _source_depth=_source_depth+(basis=='disjoint_output_source_anchors_full_input'))
                    data=expand_response(part.data)
                    for o in data['observations']:
                        if isinstance(o,dict):
                            ids=p.get('output_partition',{}).get('source_block_ids')
                            if ids and o.get('source_block_id') not in ids:o.setdefault('condition_contract_issues',[]).append('output_partition_source_violation')
                            if o.get('target_id') and o['target_id'] not in p['task_contract']['allowed_target_ids']:o.setdefault('condition_contract_issues',[]).append('target_outside_output_partition')
                    for k in ['observations','methods','unresolved']:joined[k].extend(data.get(k,[]))
                return LLMJSONResponse(data=joined,provider=part.provider,model=part.model)
        if native:raise
        path=dest/'task_failures.json';rows=read(path) if path.exists() else []
        rows.append({'task_id':task_id,'stage':stage,'error_type':type(exc).__name__,'error':str(exc)[:500],
            'original_response_retained':True,'task_status':'failed_no_scientific_result_inferred'})
        write(path,rows)
        empty={k:[] for k in ['observations','methods','property_axes','subject_axes','condition_axes','cell_overrides','notes','symbol_rules','field_decisions']}
        empty.update(has_more=False,unresolved=[{'issue':'pipeline_task_failed','task_id':task_id}])
        return LLMJSONResponse(data=empty,provider='failed_task',model='no_result')
