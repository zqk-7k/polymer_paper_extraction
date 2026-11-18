from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from copy import deepcopy
import importlib.util,traceback
from common import *
import run_trial,finalize,mapping_contract,citation_spacing,condition_branch
from intake_v2 import response as intake_response,table_response
from evidence_adapter import normalize_condition_refs,normalize_rule_refs,alternative_state
from axis_adapter import align as align_axis
from citation_continuations import align as align_continuations
from component_header_adapter import inherit
from condition_evidence import available_ids
from stage4r import source_index
def adapt_fixed(data,task,raw,identity,catalog,mode):
    if mode=='new':
        from evidence_handoff import expand as expand_handles
        data=expand_handles(data,task['packet'])
    if mode=='new':
        from range_evidence import install
        install()
        from cell_evidence import install as install_cells
        install_cells()
        from header_coordinates import install as install_headers
        install_headers()
    if mode != 'new': raise ValueError('Production receiver supports current contract only')
    blocks,cells=source_index(raw);owned=task.get('owned_source_ids') or []
    packet=task['packet'];allowed=available_ids(packet,owned)|{s['source_id'] for s in packet.get('evidence_sources',[])}
    is_table=bool(task.get('source_table')) or isinstance(packet.get('table'),dict);table_audit=None
    fm=old_final if mode=='old' else finalize;mapping=old_mapping if mode=='old' else mapping_contract
    spacing=old_spacing if mode=='old' else citation_spacing;branch=old_branch if mode=='old' else condition_branch
    if is_table:
        task['table_id']=task.get('table_id') or task['source_table']['table_id']
        restored,unknown=run_trial.restore_extra(data if mode=='old' else table_response(data),task.get('cell_id_map',{}))
        aligned,_=align_axis(task,restored);aligned,_=normalize_condition_refs(task,aligned);aligned,_=normalize_rule_refs(task,aligned)
        if mode=='new':
            from legend_scope import normalize
            aligned,_=normalize(task,aligned)
        observations,table_audit=mapping.read_table(task,aligned,{x['target_id'] for x in catalog['targets']},{s['sample_id'] for s in identity['samples']})
    else:observations=(data if mode=='old' else intake_response(data)).get('observations',[])
    if not isinstance(observations,list):
        if mode=='old':raise ValueError('unsupported legacy observations shape')
        observations=[observations]
    records=[]
    for i,original in enumerate(observations):
        o=deepcopy(original);ref=f'{task["task_id"]}:{i}'
        if o.get('declared_fact_recovery'):
            ref=f'{task["task_id"]}:declared:{o["declared_fact_recovery"]["key"]}'
        def expand(value):
            if isinstance(value,list):return [expand(x) for x in value]
            if isinstance(value,dict):
                shared=packet.get('shared_evidence_refs',{})
                if value.get('evidence_ref_id') in shared:
                    from evidence_handoff import expand as expand_handles
                    return expand_handles(value,packet)
                return {k:expand(v) for k,v in value.items()}
            return value
        o=expand(o)
        if is_table:o,_=alternative_state(o);o,_=inherit(o,cells)
        if isinstance(o,dict) and task.get('allowed_target_ids') is not None:o['task_allowed_target_ids']=task['allowed_target_ids']
        o,_=spacing.align(o,blocks,allowed);o,_=align_continuations(o,blocks,allowed);o,_=branch.adapt(o,blocks,cells,allowed)
        row=fm.observation_record(o,ref,raw,identity,catalog,owned,allowed)
        if mode=='new':
            from legend_scope import annotate_record
            row=annotate_record(row,o)
        if is_table:row=mapping.finalize_mapping(row,o)
        if isinstance(original,dict):assert row['value_raw']==original.get('value_raw') and row['unit_raw']==original.get('unit_raw')
        from declared_facts import hold_record
        row=hold_record(row,original)
        records.append(row)
    assert len(records)==len(observations)
    return records,table_audit
