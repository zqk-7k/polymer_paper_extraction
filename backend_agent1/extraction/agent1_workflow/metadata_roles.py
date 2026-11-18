"""Method metadata cannot veto an independently supported observation.

No scientific condition is guessed or rewritten. The original condition payload
stays in the record; an unsupported standalone method is separately marked as a
candidate. Unknown/mixed parameter roles retain the original conservative check.
"""
from copy import deepcopy
import re
from common import digest,sha
from condition_evidence import valid_refs
from stage3_completion import source_proof
from evidence_text import original_span
LOADED_SOURCE_SHA256=sha(__file__)

def is_standalone_method(condition):
    if not isinstance(condition,dict):return False
    name=re.sub(r'([a-z])([A-Z])',r'\1_\2',str(condition.get('name_raw') or '')).casefold()
    tokens=set(re.findall(r'[a-z]+',name))
    if tokens & {'temperature','pressure','frequency','humidity','concentration','duration','time','strain','stress',
                 'rate','ratio','composition','solvent','atmosphere','load','wavelength','voltage','current','fraction'}:return False
    allowed={'measurement','measuring','test','testing','determination','characterization','method','raw','name','of'}
    explicit=condition.get('condition_role') in ('method','supplementary_method')
    if not (explicit or 'method' in tokens and tokens<=allowed):return False
    if condition.get('unit_raw'):return False
    value=str(condition.get('value_raw') or '')
    # A method name containing a parameter is mixed information, so keep it in
    # the core channel rather than treating the parameter as optional.
    if re.search(r'\b(?:temperature|pressure|frequency|humidity|concentration|duration|strain|stress|cooling\s+rate|heating\s+rate)\b',value,re.I):return False
    if re.search(r'\b(?:in|under|at)\s+\S',value,re.I):return False
    if re.search(r'\d\s*(?:°|%|MPa\b|GPa\b|kPa\b|[kMG]?Hz\b|[ck]\b|mm\b|min\b|hours?\b)',value,re.I):return False
    # Do not rely on an ever-growing unit list. Alphanumeric instrument model
    # tokens may contain digits; any remaining scalar is conservatively mixed.
    without_models=re.sub(r'\b[A-Z][A-Z0-9-]*\d[A-Z0-9-]*\b','',value)
    if re.search(r'\d',without_models):return False
    return True

def signature(c):return digest([c.get('name_raw'),c.get('value_raw'),c.get('unit_raw')])

def verified(c,blocks,cells,table_id,allowed):
    if 'evidence_refs' in c:return valid_refs(c['evidence_refs'],blocks,cells,table_id,allowed)
    if c.get('source_block_id') and c.get('quote'):return source_proof(blocks,c['source_block_id'],c['quote'])
    refs=c.get('source_cell_ids') or []
    return bool(refs and all(cid in cells and cells[cid]['table_id'] in allowed for cid in refs) and
        any(original_span(cells[cid]['text'],str(c.get('value_raw') or '')) for cid in refs))

def separate(observation,row,raw,identity,catalog,owned_ids,evidence_ids,base_record):
    from stage4r import source_index
    original=deepcopy(row);blocks,cells=source_index(raw)
    allowed=set(owned_ids if evidence_ids is None else evidence_ids)
    table=cells.get(observation.get('source_cell_id'),{}).get('table_id')
    normalized=(row.get('conditions_raw') or {}).get('reported_conditions',[])
    bad=[c for c in normalized if is_standalone_method(c) and not verified(c,blocks,cells,table,allowed)]
    if not bad:return original
    bad_keys={signature(c) for c in bad};clean=deepcopy(observation)
    conditions=clean.get('conditions')
    if not isinstance(conditions,list):return original
    retained=[c for c in conditions if not isinstance(c,dict) or signature(c) not in bad_keys]
    if len(retained)==len(conditions):return original
    clean['conditions']=retained
    core=base_record(clean,raw=raw,identity=identity,catalog=catalog,owned_ids=owned_ids,evidence_ids=evidence_ids)
    for field in ['value_raw','unit_raw','sample_id','entity_id','target_id']:
        assert original.get(field)==core.get(field),('Method metadata changed scientific core',field)
    original['status']=core['status'];original['core_status']=core['status'];original['reasons']=deepcopy(core['reasons'])
    original.setdefault('supplementary_reviews',[]).extend({'condition':deepcopy(c),'status':'needs_review',
        'reason':'standalone_method_reference_unverified','authority':'method_candidate_not_a_core_measurement_condition'} for c in bad)
    original['supplementary_status']='needs_review';original['method_verification_status']='needs_review'
    original['method_metadata_reception']={'raw_conditions_preserved':True,'unverified_method_conditions':len(bad),
        'core_rechecked_with_all_other_conditions':True,'scientific_values_changed':False,
        'policy':'Unsupported standalone method remains a candidate; critical or mixed parameters keep veto authority.'}
    assert original['conditions_raw']==row['conditions_raw']
    return original
