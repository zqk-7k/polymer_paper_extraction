"""Task-scoped R -> Stage5 handoff; preserve IDs/status, never silently promote a record."""
from copy import deepcopy
from common import digest

FIELDS=('record_id','target_id','sample_id','entity_id','owner_scope','value_raw','unit_raw',
        'value_role','subtype_raw','conditions_raw','status','reasons','source_support',
        'verified_literal_source_refs','expression_refs','core_status','supplementary_status','supplementary_reviews',
        'owner_resolution','series_applicability')

def pack_references(packet):
    result=deepcopy(packet);shared={}
    for row in result['already_extracted_property_digest']:
        for condition in (row.get('conditions_raw') or {}).get('reported_conditions',[]):
            refs=condition.get('evidence_refs')
            if not isinstance(refs,list):continue
            packed=[]
            for ref in refs:
                name='ev_'+digest(ref)[:16];shared[name]=ref;packed.append({'evidence_ref_id':name})
            condition['evidence_refs']=packed
    result['shared_evidence_refs']=shared
    result['shared_evidence_policy']='Resolve evidence_ref_id in shared_evidence_refs; these are the exact upstream citations, not new claims.'
    return result

def expand_references(packet):
    result=deepcopy(packet);shared=result.get('shared_evidence_refs',{})
    for row in result['already_extracted_property_digest']:
        for c in (row.get('conditions_raw') or {}).get('reported_conditions',[]):
            if isinstance(c.get('evidence_refs'),list):
                c['evidence_refs']=[deepcopy(shared[r['evidence_ref_id']]) if isinstance(r,dict) and 'evidence_ref_id' in r else r for r in c['evidence_refs']]
    return result

def build_stage5_handoff(task,merged,table_tasks):
    packet=deepcopy(task['packet'])
    allowed={f['target_id'] for f in packet['target_fields']}
    assert allowed and all(t.startswith('stage5_property_vocabulary:') for t in allowed)
    relevant=[{k:deepcopy(row.get(k)) for k in FIELDS} for row in merged if row.get('target_id') in allowed]
    direct=[row['record_id'] for row in merged if row.get('target_id') not in allowed]
    table_ids={s.get('block_id') for row in relevant for s in (row.get('source_support') or []) if s.get('cell_id') and s.get('block_id')}
    packet['already_extracted_property_digest']=relevant
    packet['upstream_record_policy']='Reference record_id when discussing upstream observations. Pending/conflicting records stay pending; do not overwrite or promote them. New observations require their own owned text evidence.'
    packet['field_owner_handoff']={'version':'characterization_only.v2',
        'allowed_target_ids':sorted(allowed),'upstream_characterization_records':len(relevant),
        'policy':'Only characterization records are supplied to Stage5. Other R records remain unchanged for Stage6; do not reconstruct or review their properties.'}
    return packet,{'related_table_ids':sorted(table_ids),'record_ids':[r['record_id'] for r in relevant],
                   'records_sha256':digest(relevant),'states_preserved':True,
                   'direct_final_record_ids':direct,'stage5_field_owner_only':True,
                   'other_records_preserved_in_final_export':len(direct)}

def split_handoff(packet,ceiling,system_bytes):
    """Bound large summaries without dropping or truncating source evidence."""
    import json
    packet=pack_references(packet)
    rows=packet['already_extracted_property_digest']
    base=deepcopy(packet);base['already_extracted_property_digest']=[]
    size=lambda p:len(json.dumps(p,ensure_ascii=False,separators=(',',':')).encode())+system_bytes
    assert size(base)<=ceiling,'Owned Stage5 source itself exceeds ceiling; no silent truncation'
    parts=[];current=deepcopy(base)
    for row in rows:
        test=deepcopy(current);test['already_extracted_property_digest'].append(row)
        if size(test)>ceiling:
            assert current['already_extracted_property_digest'],'One upstream record exceeds ceiling'
            parts.append(current);current=deepcopy(base);current['already_extracted_property_digest']=[row]
            assert size(current)<=ceiling
        else:current=test
    parts.append(current)
    # Usually one packet. For split summaries only the first part owns new claims;
    # later parts may attach methods to listed records but cannot repeat prose extraction.
    for i,p in enumerate(parts):
        p['handoff_partition']={'index':i+1,'count':len(parts),'new_prose_observations_allowed':i==0}
    return parts
