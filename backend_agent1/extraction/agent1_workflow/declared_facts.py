"""Evidence citations have no authority to silently exclude property-bearing cells.

No values are parsed. Ambiguous dual-use cells are preserved, never promoted.
"""
from copy import deepcopy
import re
from common import digest
from contextvars import ContextVar
ENABLED=ContextVar('retain_declared_facts',default=True)

def label_key(text):
    # Typography-only label comparison, never used to transform a measurement.
    return re.sub(r'[\s$\\{}_^()\[\]:;,]+','',str(text or '')).casefold()

def exact_axis_title(cell, prop):
    name=label_key(prop.get('property_name_raw'))
    unit=label_key(prop.get('unit_raw'))
    value=label_key(cell['text'])
    return bool(name and value in {name,name+unit})

def retain_declared(table,response,observations,ledger):
    if not ENABLED.get():return [],{}
    from table_reader import matches
    byid={c['cell_id']:c for c in table['cells']}
    existing={o['source_cell_id'] for o in observations}
    byledger={x['cell_id']:x for x in ledger}
    recovered=[];destinations=[]
    for pi,prop in enumerate(response['property_axes']):
        for cid in dict.fromkeys(prop.get('source_cell_ids',[])):
            c=byid.get(cid)
            item={'property_axis_index':pi,'cell_id':cid,'target_id':prop.get('target_id')}
            if c is None:
                item.update(destination='unresolved',reason='invalid_source_cell_reference')
            elif cid in existing:
                item.update(destination='existing_candidate',reason='original_cell_has_candidate')
            elif not str(c['text']).strip():
                item.update(destination='source_exclusion',reason='empty_original_cell')
            elif exact_axis_title(c,prop):
                item.update(destination='source_exclusion',reason='literal_property_name_and_optional_unit_only',source_text=c['text'])
            elif not matches(prop,c):
                item.update(destination='structural_evidence_only',reason='reference_outside_own_property_axis',source_text=c['text'])
            else:
                subjects=[s for s in response['subject_axes'] if matches(s,c)]
                if not subjects:
                    item.update(destination='unresolved',reason='referenced_property_axis_cell_without_subject_intersection',source_text=c['text'])
                else:
                    key=digest([table['table_id'],cid,pi,prop])[:24]
                    claim={'property_axis':deepcopy(prop),'subject_axes':deepcopy(subjects),
                           'condition_axes':deepcopy(response['condition_axes']),
                           'cell_overrides':[deepcopy(x) for x in response['cell_overrides'] if x.get('cell_id')==cid]}
                    recovered.append({'target_id':prop.get('target_id'),'is_target':prop.get('is_target',True),
                        'property_name_raw':prop.get('property_name_raw'),'subtype_raw':prop.get('subtype_raw'),
                        'sample_id':None,'sample_ids':[],'owner_scope':'unknown','owner_label_raw':None,
                        'value_raw':c['text'],'unit_raw':prop.get('unit_raw'),'value_role':prop.get('value_role','unknown'),
                        'conditions':[],'method_raw':prop.get('method_raw'),'source_block_id':table['table_id'],
                        'source_cell_id':cid,'quote':c['text'],'qualifiers_raw':[],
                        'property_source_cell_ids':prop.get('source_cell_ids',[]),'unit_source_cell_ids':prop.get('unit_source_cell_ids',[]),
                        'table_id':table['table_id'],'declared_fact_recovery':{'key':key,'source_cell_id':cid,
                            'reason':'cell_role_and_subject_scope_require_resolution','original_model_claims':claim,
                            'raw_text_preserved':True,'numeric_parsing':False,'state_inherited':False}})
                    item.update(destination='retained_candidate_needs_review',reason='dual_use_property_reference_not_a_header_exclusion',candidate_key=key)
                    byledger[cid]['status']='referenced_property_cell_retained_needs_review'
            destinations.append(item)
    return recovered,{'property_reference_destinations':destinations,
        'declared_reference_count':len(destinations),'references_without_destination':0,
        'recovered_candidates':len(recovered),'scope':'model-declared property references, not undeclared source facts'}

def hold_record(row, observation):
    if observation.get('role_handoff'):row['role_handoff']=deepcopy(observation['role_handoff'])
    recovery=observation.get('declared_fact_recovery')
    if not recovery:return row
    row['declared_fact_recovery']=deepcopy(recovery)
    row['status']=row['core_status']='needs_review'
    row['reasons']=list(dict.fromkeys(row.get('reasons',[])+['cell_role_and_subject_scope_require_resolution']))
    # Retain the model's claims as claims, not as a resolved material or state.
    row.update(sample_id=None,entity_id=None,owner_scope='unknown')
    return row
