"""Bind explicit primary-model source checks; never certify their chemistry."""
from copy import deepcopy
from .adoption import CURRENT_POLICY, SOURCE_POLICY, context
from .storage import digest
from .source_conflicts import conflicts_for
from .diagnostics import fail, ordered, reference_set

LIMITS = ('salt_charge', 'stereo_isotope', 'end_groups', 'assembly_topology')
CONTRACT = 'identity-source-review/1.1'

def required(candidate):
    return candidate.get('adoption_policy') in (SOURCE_POLICY, CURRENT_POLICY)

def source_context(candidate):
    return digest({mid:context(m,candidate) for mid,m in candidate.get('materials',{}).items() if m.get('major')})

def bind(candidate, checks, valid_refs):
    majors={mid for mid,m in candidate.get('materials',{}).items() if m.get('major')}
    covered={'identity':set(),'quantities':set()}
    if not isinstance(checks,list) or not checks:
        fail('SOURCE_CHECKS_REQUIRED', path='source_checks', required_type='nonempty list')
    for ci, c in enumerate(checks):
        base={'check_index':ci, 'path':f'source_checks[{ci}]'}
        if not isinstance(c,dict): fail('SOURCE_CHECK_ENTRY_REQUIRED', **base, required_type='object')
        ids=c.get('material_ids',[]);refs=c.get('source_refs',[])
        topic=c.get('topic')
        if topic not in covered or not isinstance(ids,list) or not ids or not set(ids).issubset(majors):
            fail('SOURCE_CHECK_SCOPE_REQUIRED', **base, material_ids=ids, topic=topic,
                 allowed_topics=list(covered), allowed_material_ids=ordered(majors),
                 invalid_material_ids=ordered(reference_set(ids)-majors), material_ids_type=type(ids).__name__)
        if not isinstance(refs,list) or not refs or not set(refs).issubset(valid_refs):
            fail('SOURCE_CHECK_VALID_REFS_REQUIRED', **base, field='source_refs',
                 unrecognized_source_refs=ordered(reference_set(refs)-reference_set(valid_refs)), source_refs_type=type(refs).__name__)
        if c.get('disposition') not in ('consistent','conflict_preserved','unknown') or not c.get('reason'):
            fail('SOURCE_CHECK_EXPLICIT_FINDING_REQUIRED', **base, disposition=c.get('disposition'),
                 allowed_dispositions=['consistent','conflict_preserved','unknown'], missing_fields=['reason'] if not c.get('reason') else [])
        covered[topic].update(ids)
    if any(v!=majors for v in covered.values()):
        fail('SOURCE_CHECK_EACH_MAIN_IDENTITY_AND_QUANTITY_REQUIRED', path='source_checks',
             missing_material_ids_by_topic={topic:ordered(majors-ids) for topic,ids in covered.items()})
    detailed = candidate.get('adoption_policy') == CURRENT_POLICY
    if detailed: _detailed_checks(candidate, checks, valid_refs)
    result = {'contract':CONTRACT if detailed else 'identity-source-review/1.0','context_sha256':source_context(candidate),
            'checks':deepcopy(checks),
            'reviewer':'SAME_PRIMARY_MODEL','independent_review':'NOT_REVIEWED',
            'validation_scope':'declared coverage and state binding; source interpretation not independently verified'}
    if detailed: result['checks_sha256']=digest(checks)
    return result

def _detailed_checks(candidate, checks, valid_refs):
    declared = {mid:{c.get('id') for c in conflicts_for(m, candidate)}
                for mid,m in candidate['materials'].items() if m.get('major')}
    acknowledged = {mid:set() for mid in declared}
    for ci, c in enumerate(checks):
        ids=set(c['material_ids']); refs=set(c['source_refs'])
        base={'check_index':ci,'path':f'source_checks[{ci}]','material_ids':ordered(ids),'topic':c['topic']}
        linked=c.get('conflict_ids', [])
        if not isinstance(linked, list) or not set(linked).issubset(set().union(*(declared[mid] for mid in ids))):
            allowed=set().union(*(declared[mid] for mid in ids))
            fail('SOURCE_CHECK_DECLARED_CONFLICT_IDS_REQUIRED', **base, field='conflict_ids',
                 allowed_conflict_ids=ordered(allowed), extra_conflict_ids=ordered(reference_set(linked)-allowed),
                 conflict_ids_type=type(linked).__name__)
        if linked and c['disposition'] != 'conflict_preserved':
            fail('SOURCE_CHECK_CONFLICT_DISPOSITION_REQUIRED', **base, required_disposition='conflict_preserved', conflict_ids=linked)
        for mid in ids:
            if not refs.intersection(candidate['materials'][mid].get('source_refs', [])):
                fail('SOURCE_CHECK_MATERIAL_REFERENCE_REQUIRED:'+mid, **base, material_id=mid,
                     material_source_refs=candidate['materials'][mid].get('source_refs', []), examined_source_refs=ordered(refs))
            acknowledged[mid].update(set(linked) & declared[mid])
        observations=c.get('observations')
        if not isinstance(observations,list) or not observations:
            fail('SOURCE_CHECK_OBSERVATIONS_REQUIRED', **base, field='observations', required_type='nonempty list')
        observed=set()
        for oi, o in enumerate(observations):
            obase={**base,'observation_index':oi,'path':f'source_checks[{ci}].observations[{oi}]'}
            if not isinstance(o,dict): fail('SOURCE_CHECK_OBSERVATION_ENTRY_REQUIRED', **obase, required_type='object')
            mids=o.get('material_ids'); ors=o.get('source_refs')
            if not isinstance(mids,list) or not mids or not set(mids).issubset(ids):
                fail('SOURCE_CHECK_OBSERVATION_MATERIAL_REQUIRED', **obase, field='material_ids',
                     invalid_material_ids=ordered(reference_set(mids)-ids), material_ids_type=type(mids).__name__)
            if not isinstance(ors,list) or not ors or not set(ors).issubset(refs & valid_refs):
                fail('SOURCE_CHECK_OBSERVATION_REFERENCE_REQUIRED', **obase, field='source_refs',
                     allowed_check_source_refs=ordered(refs & valid_refs),
                     outside_check_source_refs=ordered(reference_set(ors)-refs),
                     unrecognized_source_refs=ordered(reference_set(ors)-valid_refs), source_refs_type=type(ors).__name__)
            for key in ('locator','as_reported','state_basis'):
                if not isinstance(o.get(key),str) or not o[key].strip():
                    fail('SOURCE_CHECK_OBSERVATION_'+key.upper()+'_REQUIRED', **obase, missing_or_invalid_fields=[key])
            if o.get('material_scope') != 'this_material':
                fail('SOURCE_CHECK_THIS_MATERIAL_SCOPE_REQUIRED', **obase, field='material_scope', required_value='this_material')
            # This remains a declaration, not proof of seeing or interpreting pixels.
            if any(r.startswith('page:') for r in valid_refs):
                if o.get('representation')!='page_image' or not any(r.startswith('page:') for r in ors):
                    fail('SOURCE_CHECK_ORIGINAL_PAGE_OBSERVATION_REQUIRED', **obase, required_representation='page_image', required_reference='page:N')
            elif o.get('representation') not in ('pdf_text','author_statement','page_image'):
                fail('SOURCE_CHECK_OBSERVATION_REPRESENTATION_REQUIRED', **obase, allowed_representations=['pdf_text','author_statement','page_image'])
            for mid in mids:
                if not set(ors).intersection(candidate['materials'][mid].get('source_refs', [])):
                    fail('SOURCE_CHECK_OBSERVATION_MATERIAL_REFERENCE_REQUIRED:'+mid, **obase, material_id=mid,
                         material_source_refs=candidate['materials'][mid].get('source_refs', []), examined_source_refs=ors)
            observed.update(mids)
        if observed!=ids:
            fail('SOURCE_CHECK_OBSERVATION_EACH_MATERIAL_REQUIRED', **base, missing_observed_material_ids=ordered(ids-observed))
        if c['topic']=='identity':
            limits=c.get('identity_limits')
            if not isinstance(limits,dict) or any(not isinstance(limits.get(k),str) or not limits[k].strip() for k in LIMITS):
                fail('SOURCE_CHECK_IDENTITY_LIMITS_REQUIRED', **base, field='identity_limits',
                     missing_or_invalid_fields=[k for k in LIMITS if not isinstance(limits,dict) or not isinstance(limits.get(k),str) or not limits[k].strip()])
    if any(acknowledged[mid]!=cs for mid,cs in declared.items()):
        fail('SOURCE_CHECK_ALL_DECLARED_CONFLICTS_REQUIRED', path='source_checks',
             missing_conflict_ids_by_material={mid:ordered(cs-acknowledged[mid]) for mid,cs in declared.items() if cs!=acknowledged[mid]})

def errors(candidate, index=None):
    if not required(candidate): return []
    r=candidate.get('source_review') or {}
    detailed=candidate.get('adoption_policy')==CURRENT_POLICY
    contract=CONTRACT if detailed else 'identity-source-review/1.0'
    if r.get('contract')!=contract or r.get('context_sha256')!=source_context(candidate):
        return ['CURRENT_EXPLICIT_MODEL_SOURCE_REVIEW_REQUIRED']
    if detailed:
        if r.get('checks_sha256')!=digest(r.get('checks')):
            return ['SOURCE_REVIEW_CHECKS_CHANGED']
        try:
            if index is not None:
                refs={b['id'] for b in index.get('blocks',[])}|{'page:'+str(n) for n in range(1,index.get('page_count',0)+1)}|{'text:input'}
            else:
                refs=set().union(*(set(m.get('source_refs',[])) for m in candidate['materials'].values()))
            bind(candidate,r.get('checks'),refs)
        except (ValueError,TypeError,KeyError) as e:
            return ['SOURCE_REVIEW_DECLARATION_INVALID:'+str(e)]
    return []
