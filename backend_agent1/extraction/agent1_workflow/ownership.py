"""Evidence-bounded owner scope. No chemical inference or member measurements."""
from copy import deepcopy
from catalog import norm
from contextvars import ContextVar
import re
ENABLED=ContextVar('ownership_enabled',default=True)

OWNER_REASONS={'group_scope_preserved','ambiguous_alias','owner_not_resolved'}

def graph(identity):
    entities={e['entity_id']:e for e in identity.get('entities',[])}
    samples={s['sample_id']:s for s in identity.get('samples',[])}
    aliases={};members={eid:[] for eid in entities};edges=[];issues=[]
    def alias(label,eid):
        if isinstance(label,str) and norm(label):aliases.setdefault(norm(label),set()).add(eid)
    for eid,e in entities.items():
        for label in [e.get('polymer_name'),*e.get('source_names',[]),*e.get('aliases',[])]:alias(label,eid)
    for sid,s in samples.items():
        eid=s.get('refers_to_entity')
        if eid not in entities:
            issues.append({'sample_id':sid,'reason':'entity_missing'});continue
        members[eid].append(sid)
        for label in [s.get('sample_label_raw'),s.get('polymer_name')]:alias(label,eid)
        edges.append({'from':sid,'to':eid,'relation':'declared_entity','basis':'existing_directory_reference'})
        parent=s.get('parent_sample_id')
        if parent:
            if parent in samples and samples[parent].get('refers_to_entity')==eid:
                edges.append({'from':sid,'to':parent,'relation':'declared_physical_state',
                              'basis':s.get('parent_relation_basis','existing_directory_reference')})
            else:issues.append({'sample_id':sid,'reason':'invalid_or_cross_entity_parent','parent_sample_id':parent})
    return {'version':'owner_scope.v1','entities':[{**deepcopy(e),'member_sample_ids':sorted(members[eid])} for eid,e in entities.items()],
            'samples':deepcopy(list(samples.values())),'edges':edges,'issues':issues,
            'material_alias_index':{k:sorted(v) for k,v in aliases.items()},'inferred_materials':[]}

def resolve(observation,identity,blocks,source_proof):
    g=identity.get('ownership_graph') or graph(identity)
    samples={s['sample_id']:s for s in identity['samples']};entities={e['entity_id']:e for e in g['entities']}
    label=observation.get('owner_label_raw') or observation.get('sample_label_raw')
    matches=g['material_alias_index'].get(norm(label),[]) if label else []
    sid=observation.get('sample_id');eid=observation.get('entity_id')
    claim=observation.get('owner_scope','unknown')
    result={'requested_scope':claim,'scope':'unresolved','entity_id':None,'sample_id':None,
            'candidate_entity_ids':matches,'candidate_sample_ids':identity.get('alias_index',{}).get(norm(label),[]),
            'evidence_verified':False,'reason':'owner_not_resolved','member_measurements_generated':False}
    if claim in ('component','reference'):
        return {**result,'scope':claim,'reason':'non_target_subject_role'}
    if eid and eid not in entities:return {**result,'reason':'invalid_entity_id'}
    if sid and sid not in samples:return {**result,'reason':'invalid_sample_id'}
    if sid and eid and samples[sid].get('refers_to_entity')!=eid:
        return {**result,'reason':'conflicting_sample_entity'}
    if claim=='material':
        if eid and matches and eid not in matches:return {**result,'reason':'conflicting_material_label_and_id'}
        if sid:
            sid_entity=samples[sid].get('refers_to_entity')
            if eid and sid_entity!=eid:return {**result,'reason':'conflicting_sample_entity'}
            eid=eid or sid_entity
        eid=eid or (matches[0] if len(matches)==1 else None)
        if eid not in entities:return {**result,'reason':'material_identity_ambiguous'}
        bid=observation.get('scope_source_block_id') or observation.get('source_block_id')
        quote=observation.get('scope_quote') or observation.get('quote')
        proof=source_proof(blocks,bid,quote)
        # A model's material declaration remains an extraction claim, not independent entailment review.
        # Require an actual quoted identity anchor unless an explicit existing entity is given.
        anchor=bool(observation.get('entity_id')) or bool(label and re.search(r'(?<![a-z0-9])'+re.escape(norm(label))+r'(?![a-z0-9])',norm(quote)))
        if not (proof and anchor):return {**result,'entity_id':eid,'reason':'material_scope_evidence_missing'}
        return {**result,'scope':'material','entity_id':eid,'evidence_verified':True,
                'reason':'explicit_material_scope_existing_entity','state_scope':'not_assigned',
                'associated_sample_ids':entities[eid]['member_sample_ids']}
    if claim=='group' or observation.get('sample_ids'):
        members=observation.get('sample_ids') or []
        valid=bool(members) and isinstance(members,list) and len(members)==len(set(members)) and set(members)<=set(samples)
        proof=source_proof(blocks,observation.get('scope_source_block_id'),observation.get('scope_quote'))
        mode=observation.get('applicability_kind')
        shared=bool(valid and proof and mode=='all_listed_members' and observation.get('value_role')=='reported_fact')
        return {**result,'scope':'group','reason':'explicit_shared_description' if shared else 'group_scope_preserved',
                'evidence_verified':bool(proof),'associated_sample_ids':members if valid else [],
                'applicability_kind':mode,'shared_description_verified':shared}
    if sid:
        return {**result,'scope':'sample','sample_id':sid,'entity_id':samples[sid].get('refers_to_entity'),
                'reason':'existing_explicit_id'}
    return result

def annotate(row,observation,identity,blocks,source_proof):
    if not ENABLED.get():
        row['core_status']=row['status']
        return row
    owner=resolve(observation,identity,blocks,source_proof)
    row['owner_resolution']=owner
    claim=observation.get('owner_scope')
    if owner['reason'] in ('invalid_entity_id','conflicting_sample_entity','conflicting_material_label_and_id'):
        if row['status']!='out_of_scope':
            row['status']='needs_review';row['reasons']=list(dict.fromkeys(row['reasons']+[owner['reason']]))
    if owner['scope']=='material':
        row['owner_scope']=owner['scope'];row['entity_id']=owner['entity_id'];row['sample_id']=None
        row['binding_basis']=owner['reason']
        row['reasons']=[r for r in row['reasons'] if r not in OWNER_REASONS]
        if row['status']=='needs_review' and not row['reasons']:row['status']='adopted'
    elif claim=='material':
        # Preserve useful candidate scope without accepting an unsupported material assignment.
        row['owner_scope']='unresolved';row['sample_id']=None
        row['status']='needs_review' if row['status']!='out_of_scope' else row['status']
        row['reasons']=list(dict.fromkeys(row['reasons']+[owner['reason']]))
    row['core_status']=row['status']
    return row

def associations(records,identity):
    links=[];known={s['sample_id'] for s in identity['samples']}
    for row in records:
        owner=row.get('owner_resolution') or {}
        members=owner.get('associated_sample_ids') or []
        if not members:continue
        assert set(members)<=known
        links.append({'record_id':row['record_id'],'scope':row['owner_scope'],'entity_id':row.get('entity_id'),
            'sample_ids':members,'status':row['status'],'relation':'material_context' if row['owner_scope']=='material' else 'source_declared_shared_description',
            'direct_sample_measurement':False,'member_measurements_generated':False,
            'applicability_kind':owner.get('applicability_kind'),'independent_semantic_review':False})
    return links
