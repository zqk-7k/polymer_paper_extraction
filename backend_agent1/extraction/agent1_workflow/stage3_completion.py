"""Apply source-backed state/protocol additions without inventing identities/batches."""
from copy import deepcopy
import re
from common import digest
from identity import build_identity


def surface(value):
    text = str(value or '').replace('\\circ', '°')
    text = re.sub(r'\\(?:mathrm|text|mathbf|operatorname)\s*', '', text)
    return re.sub(r'[\s${}_^\\]', '', text)


def source_proof(blocks, bid, quote):
    block = blocks.get(bid)
    return bool(block and block.get('type') in ('text','paragraph') and surface(quote)
                and surface(quote) in surface(block.get('text','')))


def apply(stage0, stage2, stage3, response):
    for name in ('sample_updates','state_samples','protocols','state_transitions','unresolved'):
        if not isinstance(response.get(name),list): raise ValueError('Invalid Stage3 response list: '+name)
    result=deepcopy(stage3); samples=result['samples']; by_id={s['sample_id']:s for s in samples}
    blocks={b['block_id']:b for b in stage0['elements']}; accepted=[]; held=[]; local={}
    for update in response['sample_updates']:
        sid=update.get('sample_id')
        if sid not in by_id or not source_proof(blocks,update.get('source_block_id'),update.get('quote')):
            held.append({'kind':'sample_update','candidate':update,'reason':'unknown_sample_or_unverified_quote'});continue
        by_id[sid]['state_description']=update.get('state_description_raw')
        by_id[sid]['state_evidence']={'block_id':update['source_block_id'],'quote':update['quote']}
        accepted.append({'kind':'sample_update','sample_id':sid,'source_block_id':update['source_block_id']})
    next_id=max([9000]+[int(sid[1:]) for sid in by_id if re.fullmatch(r's\d+',sid)])+1
    for candidate in response['state_samples']:
        if candidate.get('identity_relation')!='physical_state':
            held.append({'kind':'state_sample','candidate':candidate,
                         'reason':'chemical_identity_relation_not_confirmed_physical_state'});continue
        parent=candidate.get('parent_sample_id'); label=candidate.get('label_raw'); local_key=candidate.get('local_key')
        if (parent not in by_id or not label or not local_key or local_key in local
            or not source_proof(blocks,candidate.get('source_block_id'),candidate.get('quote'))):
            held.append({'kind':'state_sample','candidate':candidate,'reason':'parent_or_source_not_verified'});continue
        # Only a new state of an existing material, not a new material/formulation.
        identical=[s for s in samples if s.get('parent_sample_id')==parent
                   and surface(s.get('state_description'))==surface(candidate.get('state_description_raw'))]
        if identical:local[local_key]=identical[0]['sample_id'];continue
        sid=f's{next_id}';next_id+=1;sample=deepcopy(by_id[parent])
        sample.update(sample_id=sid,parent_sample_id=parent,sample_label_raw=label,
            sample_kind='processed_material',state_description=candidate.get('state_description_raw'),
            state_evidence={'block_id':candidate['source_block_id'],'quote':candidate['quote']},
            physical_batch_asserted=False)
        sample['evidence']={'block_id':candidate['source_block_id'],'source_type':'text',
                            'source_sentence':candidate['quote']}
        samples.append(sample);by_id[sid]=sample;local[local_key]=sid
        accepted.append({'kind':'state_sample','sample_id':sid,'parent_sample_id':parent,'source_block_id':candidate['source_block_id']})
    protocols=[];pkeys={}
    for candidate in response['protocols']:
        pkey=candidate.get('local_key'); steps=candidate.get('steps')
        if not pkey or pkey in pkeys or not isinstance(steps,list) or not steps:
            held.append({'kind':'protocol','candidate':candidate,'reason':'invalid_parent_or_steps'});continue
        ids=candidate.get('applicable_sample_ids',[])
        states=candidate.get('applicable_state_keys',[])
        if (any(sid not in by_id for sid in ids) or any(k not in local for k in states)
            or not source_proof(blocks,candidate.get('scope_source_block_id'),candidate.get('scope_quote'))):
            held.append({'kind':'protocol','candidate':candidate,'reason':'applicability_or_scope_quote_unverified'});continue
        if any(not source_proof(blocks,s.get('source_block_id'),s.get('quote')) for s in steps):
            held.append({'kind':'protocol','candidate':candidate,'reason':'step_quote_not_verified'});continue
        pid='protocol_'+digest([stage0['document_id'],pkey])[:12]
        ordered=[]
        # Preserve declared source order; reject ambiguous/repeated numbering.
        numbers=[s.get('step_number') for s in steps]
        if numbers != list(range(1,len(steps)+1)):
            held.append({'kind':'protocol','candidate':candidate,'reason':'nonsequential_steps'});continue
        for step in steps:
            ordered.append({**deepcopy(step),'parent_protocol_id':pid,'step_count':len(steps)})
        protocols.append({'protocol_id':pid,'title_raw':candidate.get('title_raw'),
            'scope_raw':candidate.get('scope_raw'),'scope_source_block_id':candidate['scope_source_block_id'],
            'scope_quote':candidate['scope_quote'],'applicable_sample_ids':ids+[local[k] for k in states],
            'steps':ordered,'physical_batch_edges_inferred':False})
        pkeys[pkey]=pid;accepted.append({'kind':'protocol','protocol_id':pid,'steps':len(ordered)})
    transitions=[]
    for candidate in response['state_transitions']:
        pkey=candidate.get('protocol_key')
        keys=candidate.get('input_sample_or_state_keys',[])+candidate.get('output_state_keys',[])
        if (pkey not in pkeys or any(k not in local and k not in by_id for k in keys)
            or not source_proof(blocks,candidate.get('source_block_id'),candidate.get('quote'))):
            held.append({'kind':'state_transition','candidate':candidate,'reason':'transition_scope_or_source_not_verified'});continue
        transitions.append({**deepcopy(candidate),'protocol_id':pkeys[pkey],
            'input_sample_ids':[local.get(k,k) for k in candidate.get('input_sample_or_state_keys',[])],
            'output_sample_ids':[local.get(k,k) for k in candidate.get('output_state_keys',[])]})
    result['protocol_contexts']=protocols
    result['state_transitions']=transitions
    result['stage3_completion_raw']=response
    identity=build_identity(stage2,result)
    identity['stage3_gap_completion_status']='model_executed_source_quotes_checked'
    identity['completion_accepted']=accepted;identity['completion_held']=held
    identity['model_unresolved']=response['unresolved'];identity['state_transitions']=transitions
    # Keep source-not-reported/held cases explicit, not "all gaps solved".
    identity['remaining_state_gaps']=[g for g in identity['stage3_gap_tasks'] if g['kind']=='state_scope_not_explicit']
    return result,identity,{'accepted':accepted,'held':held,'unresolved':response['unresolved'],
        'protocol_count':len(protocols),'ordered_steps':sum(len(p['steps']) for p in protocols),
        'state_samples_added':len(local),'transitions_accepted':len(transitions)}
