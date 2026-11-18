"""Table-scoped semantic rules. Numerical strings and raw symbols are never rewritten."""
from copy import deepcopy
import re
from table_reader import matches
from condition_axis import interpret as original_interpret
from evidence_text import matches as evidence_match

GUIDANCE='''
R1 table semantics contract. Read supplied evidence_sources including separately sourced
PDF legend transcriptions and original OCR notes; retain any disagreements explicitly.
The PDF transcriptions are source evidence, not a per-cell answer list. Interpret the
entire table once; do NOT output measured cell values. Add these arrays to the normal
Stage4T JSON schema:
symbol_rules:[{rule_id:"local",symbol_raw:"exact symbol",result:"soluble|insoluble|unknown",
 target_id:"indexed field or null",regime:"room_temperature|heated|heated_alternative|tested_conditions|unknown",
 condition_text_raw:"exact supporting words",applies_to:{axis:"row|column",indices:[]},
 conditions:[{name_raw:"...",value_raw:"exact raw expression",unit_raw:null,
 evidence_refs:[{source_id:"evidence source ID",quote:"exact separate excerpt"}]}],
 evidence_refs:[{source_id:"...",quote:"exact legend excerpt"}]}].
field_decisions:[{axis:"row|column",indices:[],kind:"initial_modulus|ultimate_tensile_strength|stress_at_break|uncertain",
 mapping_state:"confirmed|ambiguous|catalog_missing_field|out_of_scope",
 source_name_raw:"literal source label",evidence_refs:[{source_id:"...",quote:"exact excerpt"}]}].
symbol_rules must declare a row/column scope ONLY over the solubility result axes.
Set the affected property_axes quantity_kind to "solubility". Keep solvents as
condition_axes labels and keep the raw matrix symbols as measured results. Do not use
the number of plus signs to infer thermodynamic good/poor-solvent classification.
A symbol may carry different meanings in different tables: never reuse another table's rules.
Each regime must retain its own source conditions: room-temperature dissolution is not
evidence that heating was performed. Conditional escalation after a failed initial test
applies only to the appropriate outcome branch, not to all observations in the table.
Declare conditional heating conditions with applies_when:"initial_test_failure" and
the exact supporting source quotation. Never report conditional heating as applied
unconditionally to a room-temperature soluble observation.
If the source allows alternative heating conditions, retain the alternative explicitly
instead of choosing a temperature or computing a boiling point/concentration.
Distinguish the tested sample amount/solvent volume from a calculated concentration.
Unknown symbols remain mapping_state ambiguous; a minus in a non-solubility column may
be missing data and MUST NOT inherit a solubility symbol rule.
Initial tensile modulus can map to tensile_modulus with the literal source subtype.
Project-approved mapping: source Tensile Strength, including ultimate tensile strength,
maps to property_vocabulary:tensile_stress_at_break. Preserve exact source property name
and subtype. This is the project field mapping convention, not evidence that endpoints
are scientifically identical. Yield stress remains distinct. Do not declare a missing
catalog field for this source label or silently extend the target catalog.
For property field_decisions use evidence_sources text IDs; the program also accepts
table cell IDs in source_id for literal header evidence. A multi-block quote needs
separate evidence_refs; never combine paragraphs under one source ID.
'''

def symbol_key(value):
    # Semantic lookup only; value_raw stays byte-for-byte equal to the source cell.
    return str(value).strip().replace('−','-')

def exact_quote(quote,text):
    # Whitespace is the only tolerated transport difference, never words/digits.
    return bool(quote and (re.sub(r'\s+','',quote) in re.sub(r'\s+','',text) or evidence_match(text,quote)))

def sources_for(task):
    sources={s['source_id']:{**s,'source_block_id':s['source_id']}
             for s in task['packet'].get('evidence_sources',[])}
    tid=task['table_id']
    sources[tid]={'source_id':tid,'source_block_id':tid,'table_id':tid,
                  'kind':'table_caption','text':task['source_table'].get('caption') or ''}
    for c in task['source_table']['cells']:
        sources[c['cell_id']]={'text':c['text'],'kind':'table_cell','source_cell_id':c['cell_id'],
                              'source_block_id':task['table_id'],'table_id':task['table_id']}
    return sources

def refs_valid(refs,sources,tid,require_legend=False):
    if not isinstance(refs,list) or not refs:return False
    legend=False
    for r in refs:
        s=sources.get(r.get('source_id'),{})
        if not s or not exact_quote(r.get('quote'),s.get('text','')):return False
        if s.get('table_id') and s['table_id']!=tid:return False
        legend|=s.get('kind') in ('pdf_legend_visual_transcription','ocr_footnote')
    return not require_legend or legend

def proof_refs(refs,sources):
    out=[]
    for r in refs:
        s=sources[r['source_id']]
        item={'kind':s['kind'] if s.get('kind') in ('table_cell','table_caption') else 'text',
              'source_block_id':s['source_block_id'],'quote':r['quote']}
        if s.get('source_cell_id'):item['source_cell_id']=s['source_cell_id']
        out.append(item)
    return out

def read_table(task,response,target_ids,sample_ids):
    table=task['source_table'];tid=task['table_id'];sources=sources_for(task)
    rows,audit=original_interpret(table,response,target_ids,sample_ids)
    byid={c['cell_id']:c for c in table['cells']}
    rules=[];rejected=[]
    for rule in response.get('symbol_rules',[]):
        scope=rule.get('applies_to',{})
        valid=(scope.get('axis') in ('row','column') and bool(scope.get('indices'))
            and refs_valid(rule.get('evidence_refs'),sources,tid,True)
            and all(refs_valid(c.get('evidence_refs'),sources,tid) for c in rule.get('conditions',[]))
            and rule.get('result') in ('soluble','insoluble')
            and rule.get('target_id')==('property_vocabulary:solvent' if rule.get('result')=='soluble' else 'property_vocabulary:non_solvent')
            and rule.get('target_id') in target_ids
            and rule.get('regime') in ('room_temperature','heated','heated_alternative','tested_conditions'))
        if valid:rules.append(rule)
        else:rejected.append({'rule':rule,'reason':'rule_scope_source_or_semantic_contract_invalid'})
    changes=[]
    for o in rows:
        cell=byid[o['source_cell_id']]
        props=[p for p in response['property_axes'] if matches(p,cell)]
        is_solubility=any(p.get('quantity_kind')=='solubility' or 'solubil' in str(p.get('property_name_raw','')).casefold() for p in props)
        o['mapping_state']='model_mapping_not_independently_reviewed'
        if is_solubility:
            candidates=[r for r in rules if matches(r['applies_to'],cell) and symbol_key(r.get('symbol_raw'))==symbol_key(o['value_raw'])]
            # A broad symbol rule cannot reach other result columns merely by its scope.
            o.update(is_target=True,semantic_quantity='solubility',mapping_state='ambiguous')
            if len(candidates)!=1:
                o['target_id']=None;o['mapping_issue']='no_unique_valid_table_symbol_rule'
                continue
            rule=candidates[0]
            o.update(target_id=rule['target_id'],mapping_state='confirmed',
                     solubility_result=rule['result'],test_regime=rule['regime'],
                     legend_raw=rule['condition_text_raw'],
                     symbol_rule={**deepcopy(rule),'bound_table_id':tid,
                                  'bound_evidence_version':task['packet']['evidence_bundle_version']})
            for c in rule.get('conditions',[]):
                o.setdefault('conditions',[]).append({**deepcopy(c),'evidence_refs':proof_refs(c['evidence_refs'],sources)})
            o['mapping_evidence_refs']=proof_refs(rule['evidence_refs'],sources)
            o['condition_resolution']='alternative_preserved' if rule['regime']=='heated_alternative' else 'source_regime_preserved'
            changes.append({'cell_id':cell['cell_id'],'action':'table_scoped_symbol_rule','rule_id':rule['rule_id']})
        for d in response.get('field_decisions',[]):
            if not matches(d,cell):continue
            if not refs_valid(d.get('evidence_refs'),sources,tid):
                # An unsupported optional annotation has no authority to invalidate
                # independently supported mapping. Keep its claim and reason visible.
                rejected.append({'cell_id':cell['cell_id'],'decision':deepcopy(d),
                                 'reason':'field_decision_source_unverified_no_override'})
                o.setdefault('mapping_advisories',[]).append('field_decision_source_unverified_no_override')
                continue
            if d.get('kind')=='initial_modulus':
                headers=[byid[c] for p in props for c in p.get('source_cell_ids',[]) if c in byid]
                literal=[c for c in headers if re.search(r'initial\s+modulus',c['text'],re.I)]
                if len(literal)==1 and 'property_vocabulary:tensile_modulus' in target_ids:
                    o.update(target_id='property_vocabulary:tensile_modulus',subtype_raw='Initial Modulus',
                             mapping_state='confirmed',mapping_evidence_refs=proof_refs(d['evidence_refs'],sources))
            elif d.get('kind')=='ultimate_tensile_strength':
                if any(re.search(r'ultimate\s+tensile\s+strength',r['quote'],re.I) for r in d['evidence_refs']):
                    o.update(target_id='property_vocabulary:tensile_stress_at_break',is_target=True,mapping_state='confirmed',
                        subtype_raw='ultimate tensile strength',mapping_policy='user_approved_tensile_strength_as_break_stress',
                        mapping_evidence_refs=proof_refs(d['evidence_refs'],sources))
            elif d.get('mapping_state') in ('ambiguous','catalog_missing_field'):
                if d.get('mapping_state')=='catalog_missing_field' and o.get('target_id') in target_ids and d.get('kind')=='uncertain':
                    # Catalog membership is a program fact. A broad annotation cannot
                    # negate an existing field; specific semantic conflicts stay pending.
                    o.setdefault('mapping_advisories',[]).append('existing_target_catalog_missing_claim_has_no_override_authority')
                    rejected.append({'cell_id':cell['cell_id'],'decision':deepcopy(d),'reason':'catalog_membership_is_program_authority'})
                    continue
                if o.get('mapping_state')=='confirmed':
                    # Contradictory source-backed claims are retained as a conflict,
                    # not silently replaced by a broad catalog-missing label.
                    o['mapping_conflicting_decision']=deepcopy(d)
                    o['mapping_issue']='source_backed_mapping_conflict'
                    o['mapping_state']='ambiguous'
                else:o.update(target_id=None,is_target=True,mapping_state=d['mapping_state'])
        assert o['value_raw']==cell['text'],'Raw measurement rewritten'
    audit.update(accepted_symbol_rules=rules,rejected_symbol_rules=rejected,semantic_changes=changes,
                 semantic_mapping_independent_quality_review=False)
    return rows,audit

def finalize_mapping(row,observation):
    row=deepcopy(row)
    for k in ('mapping_state','mapping_issue','mapping_evidence_refs','semantic_quantity',
              'solubility_result','test_regime','condition_resolution','symbol_rule',
              'mapping_advisories','mapping_conflicting_decision'):
        if k in observation:row[k]=deepcopy(observation[k])
    if observation.get('mapping_state') in ('catalog_missing_field','ambiguous'):
        row['target_id']=None;row['status']='needs_review'
        row['reasons']=list(dict.fromkeys(row.get('reasons',[])+[observation['mapping_state']]))
    row['core_status']=row['status']
    if observation.get('semantic_quantity')=='solubility' and not any(str(c.get('name_raw','')).casefold()=='solvent' and c.get('value_raw') for c in observation.get('conditions',[])):
        row['status']=row['core_status']='needs_review'
        row['reasons']=list(dict.fromkeys(row['reasons']+['required_solvent_condition_missing']))
    if observation.get('test_regime')=='room_temperature':
        for c in observation.get('conditions',[]):
            name=str(c.get('name_raw','')).casefold();value=str(c.get('value_raw','')).casefold()
            heating=('heat' in name or 'temperature' in name) and bool(re.search(r'boil|heat|100',value))
            guarded=c.get('applies_when')=='initial_test_failure' or bool(re.search(r'failed|failure|conditional|\bif\b',name.replace('_',' ')))
            if heating and not guarded:
                row['status']=row['core_status']='needs_review'
                row['reasons']=list(dict.fromkeys(row['reasons']+['condition_applicability_not_explicit']))
    # Step A may re-classify a catalog-missing table row after this mapping pass.
    from finalize import reclassify_catalog_annotation
    return reclassify_catalog_annotation(row,observation)
