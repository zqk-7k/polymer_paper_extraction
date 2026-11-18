"""Shared fresh-result adaptation and Stage6 raw-export contract validation."""
from copy import deepcopy
from collections import Counter, defaultdict
import re
from common import *
from catalog import resolve_target
from stage4r import make_record, reconcile, source_index
from stage3_completion import surface, source_proof
from condition_evidence import adapt,valid_refs
from note_reference import normalize as normalize_evidence
from intake_v2 import observation as normalize_observation

# A change/difference of a quantity (Δn, "change of ...", birefringence) is not the
# absolute quantity itself. The frozen 117-target catalog has no change-quantity
# carrier field, so such a claim never maps to an absolute field; the original
# value is preserved for review instead. The catalog is not extended here.
CHANGE_QUANTITY=re.compile(r'(?:Δ|△|\bdelta\b|\bchange(?:s|d)?\s+(?:in|of)\b|\bdifference\s+(?:in|of)\b|\bbirefringence\b)',re.I)

def change_quantity_claim(o):
    for key in ('property_name_raw','subtype_raw'):
        if CHANGE_QUANTITY.search(str(o.get(key) or '')):return key
    return None

# Relaxed-validation steps A/B: records blocked ONLY by a missing catalog carrier
# field, or owned by a deliberately-excluded monomer, are real extractions with a
# preserved value — they leave the pending pool as extracted_uncategorized.
# change_quantity_boundary (Δn policy) explicitly stays needs_review.
FIELD_ANNOTATION_REASONS={'target_unmapped_or_ambiguous','catalog_missing_field'}
_MONOMER_LABELS={}

def monomer_labels(document_id):
    """normalized label -> raw label for deliberately excluded monomers.

    Lookup covers this round's inputs plus the sealed prior rounds' inputs
    (read-only fallback) so historical replay contexts annotate identically.
    """
    if document_id in _MONOMER_LABELS:return _MONOMER_LABELS[document_id]
    from catalog import norm
    from unified_directory import DELIBERATE_EXCLUSIONS
    monomer_reasons=set(DELIBERATE_EXCLUSIONS.values())
    labels={}
    candidates=[OUT/'inputs'/(document_id or '')/'agent1_handoff.json']
    for path in candidates:
        if document_id and path.is_file():
            for x in read(path).get('excluded_objects',[]):
                if x.get('reason') not in monomer_reasons:continue
                obj=x['object']
                names=[obj.get('标签')]+[s.strip() for s in str(obj.get('来源名') or '').splitlines() if s.strip()]
                for name in names:
                    if isinstance(name,str) and name.strip():
                        labels.setdefault(norm(name.strip()),name.strip())
            break
    _MONOMER_LABELS[document_id]=labels
    return labels

def reclassify_catalog_annotation(row,observation):
    """Steps A+B. Idempotent; hard checks (values, catalog membership) untouched."""
    reasons = set(row.get('reasons') or [])
    if (row.get('target_id') is None
            and 'outside_configured_target_directory' in reasons
            and row.get('status') in ('out_of_scope', 'needs_review')
            and 'change_quantity_boundary' not in reasons):
        row['catalog_policy_reclassification'] = {
            'prior_status': row['status'], 'prior_reasons': sorted(reasons),
        }
        row['reasons'] = [reason for reason in row['reasons']
                          if reason != 'outside_configured_target_directory'] + ['catalog_missing_field']
        row['status'] = 'needs_review'
    if row.get('status')!='needs_review':return row
    reasons=set(row.get('reasons') or [])
    if 'change_quantity_boundary' in reasons:return row
    from catalog import norm
    hit=None
    if 'owner_not_resolved' in reasons:
        raw=(observation or {}).get('sample_label_raw') or row.get('article_sample_label_raw')
        if raw:
            labels=monomer_labels(row.get('document_id'))
            hit=labels.get(norm(str(raw).strip()))
    field_reasons=reasons&FIELD_ANNOTATION_REASONS
    if not field_reasons and hit is None:return row
    if field_reasons:row['in_property_catalog']=False
    if hit is not None:
        row['monomer_excluded']=True;row['monomer_label_raw']=hit
    blocking=reasons-FIELD_ANNOTATION_REASONS-({'owner_not_resolved'} if hit is not None else set())
    if blocking:return row  # other real issues stay pending, with annotations attached
    row['status']='extracted_uncategorized';row['core_status']='extracted_uncategorized'
    row['annotation_reclassification']={'step':'A_field_catalog' if field_reasons else 'B_monomer',
        'prior_reasons':sorted(reasons)}
    return row

def multi_block_proof(blocks,allowed,quote):
    """Verify each sentence of a merged cross-section quote against allowed blocks.

    Every part must be a literal substring of some allowed block and at least two
    distinct blocks must be involved. Nothing is rewritten or recombined; parts
    that fail keep the original unverified warning.
    """
    parts=[p.strip() for p in re.split(r'(?<=[.。;；])\s+',str(quote or '')) if len(p.strip())>=20]
    if len(parts)<2:return None
    located={}
    for part in parts:
        hit=next((b for b in sorted(allowed) if source_proof(blocks,b,part)),None)
        if hit is None:return {'verified':False,'parts':len(parts)}
        located[part]=hit
    distinct=sorted({*located.values()})
    return {'verified':len(distinct)>=2,'parts':len(parts),'source_block_ids':distinct}


def merge_condition_value(other, name, value):
    """Merge a summary only; missing text is not an opposing scientific claim."""
    def blank(v):return v is None or isinstance(v,str) and not v.strip()
    if not name or value is None:return False
    prior=other.get(name)
    conflict=name in other and not blank(prior) and not blank(value) and prior!=value
    if name not in other or blank(prior) or not blank(value):other[name]=value
    return conflict


def observation_record(observation, ref, stage0, identity, catalog, owned_ids, evidence_ids=None):
    blocks,cells=source_index(stage0); o=normalize_observation(observation,blocks)
    if not isinstance(o,dict):
        o={'value_raw':None,'source_block_id':None,'malformed_input':observation}
    target=next((t for t in catalog['targets'] if t['target_id']==o.get('target_id')),None)
    bid=o.get('source_block_id');cid=o.get('source_cell_id')
    role=o.get('value_role','unknown')
    conditions=deepcopy(o.get('conditions') or []); other={};warnings=[]
    allowed=set(evidence_ids) if evidence_ids is not None else set(owned_ids)|{bid}
    conditions,reference_audit=normalize_evidence(conditions,stage0,identity,allowed)
    conditions,evidence_audit=adapt(conditions,blocks,cells,bid if cid else None,allowed)
    evidence_audit=reference_audit+evidence_audit
    supplementary_reviews=[];kept=[]
    roles=read(OUT/'condition_roles.json')
    for condition in conditions if isinstance(conditions,list) else []:
        if not isinstance(condition,dict):kept.append(condition);continue
        name=str(condition.get('name_raw','')).strip().casefold().replace(' ','_')
        if name in roles['supplementary_names'] and not valid_refs(condition.get('evidence_refs'),blocks,cells,bid if cid else None,allowed):
            supplementary_reviews.append({'condition':deepcopy(condition),'status':'needs_review','reason':'supplementary_reference_unverified'})
        else:kept.append(condition)
    conditions=kept if isinstance(conditions,list) else conditions
    if not isinstance(conditions,list): conditions=[];warnings.append('invalid_conditions_shape')
    for condition in conditions:
        if not isinstance(condition,dict):warnings.append('invalid_condition');continue
        name=condition.get('name_raw'); value=condition.get('value_raw')
        if merge_condition_value(other,name,value):warnings.append('condition_value_conflict')
        refs=condition.get('source_cell_ids',[])
        if any(x not in cells for x in refs):warnings.append('condition_reference_invalid')
        if 'evidence_refs' in condition:
            if not valid_refs(condition['evidence_refs'],blocks,cells,bid if cid else None,allowed):
                warnings.append('condition_quote_unverified')
            continue
        if condition.get('source_block_id'):
            condition_bid=condition['source_block_id']
            if blocks.get(condition_bid,{}).get('type')=='table':
                # A table quote is checked against its referenced source cells,
                # never against the prose-only validator. No value conversion.
                valid_cells=[cells[x] for x in refs if x in cells and cells[x]['table_id']==condition_bid]
                quote=surface(condition.get('quote'))
                supported=bool(valid_cells and quote and any(quote in surface(c['text']) for c in valid_cells))
            else:
                supported=source_proof(blocks,condition_bid,condition.get('quote'))
            if not supported:warnings.append('condition_quote_unverified')
    evidence={'block_id':bid,'source_type':'table' if cid else 'text','source_sentence':o.get('quote')}
    if cid:evidence['table_locator']={'table_id':bid,'cell_id':cid,'header_path':[]}
    role_sources=[]
    if cid:
        for source_id in o.get('property_source_cell_ids',[]):
            if source_id in cells:
                role_sources.append({'source_cell_id':source_id,'text_raw':cells[source_id]['text'],
                                     'target_cell_id':cid,'scope':'property_axis'})
    elif o.get('role_source_block_id') and source_proof(blocks,o['role_source_block_id'],o.get('role_quote')):
        role_sources=[{'source_block_id':o['role_source_block_id'],'text_raw':o['role_quote']}]
    is_group=o.get('owner_scope') in ('group','material')
    item={'sample_id':None if is_group else o.get('sample_id'),
        'sample_ids':o.get('sample_ids',[]) or (['group_scope'] if is_group else []),
        'sample_label_raw':o.get('owner_label_raw'),'property_name_raw':o.get('property_name_raw'),
        'property_name_normalized':target['property_key'] if target else None,
        'specialized_property_key':target['property_key'] if target and target['section']=='specialized_property_vocabulary' else None,
        'variant':o.get('subtype_raw'),'value_raw':o.get('value_raw'),'unit_raw':o.get('unit_raw'),
        'method_raw':o.get('method_raw'),'measurement_context':{'other_conditions':other,'reported_conditions':conditions},
        'value_semantics':{'value_role':role,'footnote_links':role_sources,'scale':o.get('scale_evidence_raw'),
                           'qualifiers_raw':o.get('qualifiers_raw',[])},'evidence':[evidence]}
    row=make_record(item,ref,{},catalog,identity,blocks,cells)
    row.update(owner_scope_claim=o.get('owner_scope'),group_sample_ids=o.get('sample_ids',[]),
        method_source_quote=o.get('quote'),model_observation=deepcopy(o),
        semantic_verification='fresh_extraction_not_independent_quality_review')
    change_hit=change_quantity_claim(o)
    if change_hit and row.get('target_id'):
        # Boundary guard: a change/difference quantity never adopts an absolute
        # field; the claim and original value stay reviewable.
        row['pre_guard_target_id']=row['target_id']
        row['target_id']=None;row['status']='needs_review';row['core_status']='needs_review'
        row['reasons']=list(dict.fromkeys(row.get('reasons',[])+['change_quantity_boundary','catalog_missing_field']))
        row['change_quantity_guard']={'matched_field':change_hit,
            'property_name_raw':o.get('property_name_raw'),'subtype_raw':o.get('subtype_raw'),
            'note':'Change/difference quantity has no carrier field in the frozen target catalog; kept for review, original value preserved.'}
    row['condition_evidence_adaptation']=evidence_audit
    row['information_kind']=o.get('information_kind','unknown')
    row['intake_adaptations']=o.get('intake_adaptations',[])
    if o.get('spectrum_group_ref') is not None:row['spectrum_group_ref']=o['spectrum_group_ref']
    if role=='reported_fact':
        row['description_support']={'source_excerpt_raw':o.get('fact_excerpt_raw') or o.get('quote'),
            'model_summary_raw':o.get('summary_raw'),'independent_entailment_review':False}
        if o.get('owner_scope')=='group' and (not o.get('sample_ids') or not source_proof(blocks,o.get('scope_source_block_id'),o.get('scope_quote'))):
            warnings.append('description_scope_evidence_missing')
    if role=='reported_fact' and (not target or target['property_key'] not in ('primary_structure_informations','morphology','stereoregularity','characteristics_of_material')):
        warnings.append('reported_fact_role_outside_descriptive_field_contract')
    row['series_applicability']={k:deepcopy(o.get(k)) for k in ('sample_ids','applicability_kind','scope_source_block_id','scope_quote')}
    row['supplementary_reviews']=supplementary_reviews
    row['supplementary_status']='needs_review' if supplementary_reviews else 'no_unverified_supplementary_condition_detected'
    if bid not in owned_ids:warnings.append('source_outside_task_ownership')
    if o.get('sample_id') and o['sample_id'] not in {s['sample_id'] for s in identity['samples']}:
        warnings.append('model_sample_id_invalid')
    if cid and (cid not in cells or cells[cid]['table_id']!=bid):warnings.append('source_cell_not_in_declared_table')
    if not cid and not source_proof(blocks,bid,o.get('quote')):
        # A merged cross-section quote may be literally supported part by part;
        # parts are verified independently, never recombined into a new quote.
        split=multi_block_proof(blocks,allowed,o.get('quote'))
        if split and split.get('verified'):
            row['quote_verification']={'mode':'multi_block_split_verified',
                'source_block_ids':split['source_block_ids'],'parts':split['parts'],
                'note':'Each sentence verified literally in its own source block.'}
        else:
            warnings.append('model_quote_not_verified')
            if split:row['quote_verification']={'mode':'multi_block_split_failed',**split}
    if o.get('target_id') and not target:warnings.append('model_target_id_invalid')
    if o.get('task_allowed_target_ids') is not None and o.get('target_id') not in o['task_allowed_target_ids']:
        warnings.append('target_outside_assigned_field_group')
    if o.get('condition_contract_issues'):warnings.extend(o['condition_contract_issues'])
    # Missing marker interpretation is semantic, not numeric parsing.
    if str(o.get('value_raw')).strip().casefold() in ('-','—','–','n/a','n.d.','nd'):
        key=target['property_key'] if target else ''
        if key not in ('solvent','non_solvent','poor_solvent','good_solvent','characteristics_of_material'):
            row['status']='out_of_scope';row['reasons']=['source_missing_marker']
    if o.get('is_target') is False and o.get('target_id') is None:
        row['status']='out_of_scope';row['reasons']=['outside_configured_target_directory']
    if o.get('owner_scope') in ('component','reference'):
        row['status']='out_of_scope';row['reasons']=['non_target_subject_role']
    if warnings:
        row['status']='needs_review';row['reasons']=list(dict.fromkeys(row['reasons']+warnings))
    from ownership import annotate
    annotated=annotate(row,o,identity,blocks,source_proof)
    return reclassify_catalog_annotation(annotated,o)


def finish(paper,arm,stage0,identity,catalog,n_rows,t_rows,s5_rows,table_audits,method_rows,*,fresh_model_outputs_only=True):
    dest=folder(paper,arm)
    stage4,ledger4,conflicts4=reconcile(n_rows+t_rows)
    write(dest/'stage4r_records.json',stage4);write(dest/'stage4r_audit.json',{'ledger':ledger4,'conflicts':conflicts4})
    final,_,conflicts=reconcile(stage4+s5_rows)
    from subject_roles import explicit_monomers, annotate as annotate_role
    blocks, _ = source_index(stage0)
    roles = explicit_monomers(identity, blocks, source_proof)
    for row in final:
        reclassify_catalog_annotation(row, row.get('model_observation'))
        annotate_role(row, roles)
    initial=n_rows+t_rows+s5_rows
    byref={ref:r for r in final for ref in r['expression_refs']}
    refs=[ref for r in initial for ref in r['expression_refs']]
    assert len(refs)==len(set(refs)) and set(refs)==set(byref), 'Candidate conservation failed'
    samples={s['sample_id'] for s in identity['samples']}
    targets={t['target_id'] for t in catalog['targets']}
    adopted=[r for r in final if r['status']=='adopted']
    entity_ids={e['entity_id'] for e in identity['entities']}
    assert all(r['target_id'] in targets and (r['sample_id'] in samples or
        r.get('owner_scope')=='material' and r.get('entity_id') in entity_ids and r.get('owner_resolution',{}).get('evidence_verified') or
        r.get('owner_scope')=='group' and r.get('owner_resolution',{}).get('shared_description_verified')) for r in adopted)
    assert all(r['value_raw'] is not None and r['verified_literal_source_refs'] for r in adopted)
    assert all(r['format_conversion_status']=='not_run' for r in final)
    assert not any(set(r)&{'value_min','value_max','actual_values','value_normalized','unit_normalized'} for r in final)
    expected_tables={b['block_id'] for b in stage0['elements'] if b.get('type')=='table'}
    assert expected_tables==set(table_audits), 'Mandatory table route incomplete'
    ledger=[{'expression_ref':ref,'record_id':byref[ref]['record_id'],'status':byref[ref]['status'],
             'exact_duplicate_merged':len(byref[ref]['expression_refs'])>1} for ref in refs]
    index=defaultdict(list)
    for row in final:index[(row['sample_id'],row['target_id'])].append(row)
    coverage=[]
    for sample in identity['samples']:
        for target in catalog['targets']:
            rows=index.get((sample['sample_id'],target['canonical_target_id']),[])
            coverage.append({'sample_id':sample['sample_id'],'target_id':target['target_id'],
                'record_ids':[r['record_id'] for r in rows],
                'status':'reported_present_completeness_unchecked' if any(r['status']=='adopted' for r in rows)
                         else 'candidate_needs_review' if any(r['status']=='needs_review' for r in rows)
                         else 'extracted_uncategorized' if any(r.get('status')=='extracted_uncategorized' for r in rows)
                         else 'only_out_of_scope' if rows else 'not_yet_located',
                'verified_not_reported':False,'all_source_values_verified':False})
    outputs={'final.json':{'document_id':stage0['document_id'],'schema_version':'raw_sample_information.v1',
        'samples':identity['samples'],'protocols':identity['protocols'],'state_transitions':identity.get('state_transitions',[]),
        'observations':final,'methods':method_rows,'model_quality_review':False,'numeric_conversion':False},
        'all_records.json':final,'sample_information.json':adopted,
        'review.json':[r for r in final if r['status']=='needs_review'],
        'excluded.json':[r for r in final if r['status']=='out_of_scope'],
        'coverage.json':coverage,'candidate_ledger.json':ledger,
        'table_source_ledger.json':table_audits,'conflicts.json':conflicts4+conflicts,
        'stage6_validation.json':{'raw_schema_valid':True,'candidate_conservation_passed':True,
            'all_tables_processed':True,'normalization_not_executed':True,'independent_quality_review':False,
            'scope':'New raw export contract; old normalized numeric FinalDocument schema is intentionally not applied.'}}
    links=[]
    for row in final:
        scope=row.get('series_applicability') or {};members=scope.get('sample_ids') or []
        if row.get('owner_scope')!='group':continue
        supported=source_proof(source_index(stage0)[0],scope.get('scope_source_block_id'),scope.get('scope_quote'))
        transferable=scope.get('applicability_kind')=='all_listed_members' and bool(members) and set(members)<=samples and supported
        links.append({'group_record_id':row['record_id'],'sample_ids':members,'source_scope':scope,
            'link_status':'source_declared_shared_fact' if transferable else 'scope_needs_review',
            'shared_record_status':row['status'],'view_only':True,'member_measurements_generated':False,
            'semantic_scope_independently_reviewed':False})
    outputs['series_links.json']=links
    # Steps A+B export: extracted values without a catalog carrier or owned by an
    # excluded monomer, value verbatim, explicitly not adopted and not pending.
    outputs['uncategorized_properties.json']=[r for r in final
        if r.get('status')=='extracted_uncategorized' or r.get('monomer_excluded')]
    from ownership import associations,graph
    outputs['owner_associations.json']=associations(final,identity)
    outputs['ownership_graph.json']=identity.get('ownership_graph') or graph(identity)
    outputs['final.json']['materials']=deepcopy(identity['entities'])
    outputs['final.json']['owner_associations']=deepcopy(outputs['owner_associations.json'])
    for name,value in outputs.items():write(dest/name,value)
    summary={'paper':paper,'arm':arm,'samples':len(samples),'input_expressions':len(refs),
        'records':len(final),'duplicates_merged':len(refs)-len(final),
        'status_counts':dict(Counter(r['status'] for r in final)),
        'review_reasons':dict(Counter(reason for r in final if r['status']=='needs_review' for reason in r['reasons'])),
        'protocols':len(identity['protocols']),'protocol_steps':sum(len(p['steps']) for p in identity['protocols']),
        'state_samples_added':sum(bool(s.get('parent_sample_id')) for s in identity['samples']),
        'remaining_state_gaps':len(identity.get('remaining_state_gaps',[])),
        'stage3_held':len(identity.get('completion_held',[])),'stage3_unresolved':len(identity.get('model_unresolved',[])),
        'table_issues':sum(len(x.get('issues',[]))+len(x.get('unresolved',[])) for x in table_audits.values()),
        'numeric_conversion':False,'model_quality_review':False,'candidate_conservation_passed':True}
    write(dest/'run_result.json',{'status':'completed','fresh_model_outputs_only':fresh_model_outputs_only,**summary})
    return summary
