"""Relocate a verbatim condition citation to a unique supplied neighbouring paragraph.

The original payload is retained. Only a validation view changes its address;
neither condition contents nor measurement values are reconstructed.
"""
from copy import deepcopy
import re
from common import sha
LOADED_SOURCE_SHA256=sha(__file__)

def occurrences(text,quote):
    wanted=''.join(str(quote).split());source=''.join(str(text).split())
    return len(list(re.finditer('(?='+re.escape(wanted)+')',source))) if wanted else 0

def exact_span(text,quote):
    # Whitespace layout alone is ignored; no punctuation or number substitution.
    chars=[];offsets=[]
    for i,c in enumerate(str(text)):
        if not c.isspace():chars.append(c);offsets.append(i)
    wanted=''.join(str(quote).split());source=''.join(chars)
    if not wanted:return None
    found=[m.start() for m in re.finditer('(?='+re.escape(wanted)+')',source)]
    if len(found)!=1:return None
    i=found[0];a=offsets[i];b=offsets[i+len(wanted)-1]+1
    return {'quote':str(text)[a:b],'source_start':a,'source_end':b}

def align(observation,blocks,allowed):
    result=deepcopy(observation);audit=[]
    prose=[(k,b) for k,b in blocks.items() if b.get('type') in ('text','paragraph')
           and str(b.get('text') or '').strip() and isinstance(b.get('source_block_index'),int)]
    prose.sort(key=lambda x:x[1]['source_block_index']);order={k:i for i,(k,b) in enumerate(prose)}
    for ci,c in enumerate(result.get('conditions') or []):
        if not isinstance(c,dict):continue
        refs=c.get('evidence_refs')
        for ref in refs if isinstance(refs,list) else [c]:
            if not isinstance(ref,dict) or ref.get('kind','text')!='text':continue
            bid=ref.get('source_block_id');quote=ref.get('quote');declared=blocks.get(bid,{})
            if bid not in allowed or bid not in order or not isinstance(quote,str):continue
            if len(quote)<32 or len(re.findall(r'\w+',quote))<5:continue
            if occurrences(declared.get('text',''),quote):continue
            if sum(occurrences(b.get('text',''),quote) for k,b in prose if k in allowed)!=1:continue
            matches=[(k,b,exact_span(b.get('text',''),quote)) for k,b in prose if k in allowed]
            matches=[x for x in matches if x[2]]
            if len(matches)!=1:continue
            dest,block,span=matches[0]
            if abs(order[dest]-order[bid])!=1:continue
            if not declared.get('section') or block.get('section')!=declared['section']:continue
            if not isinstance(block.get('page'),int) or not isinstance(declared.get('page'),int):continue
            if abs(block['page']-declared['page'])>1:continue
            original=deepcopy(ref)
            ref.update(source_block_id=dest,quote=span['quote'])
            audit.append({'condition_index':ci,'original_reference':original,
                'canonical_reference':deepcopy(ref),'source_start':span['source_start'],'source_end':span['source_end'],
                'policy':'verbatim_unique_supplied_adjacent_paragraph_same_section',
                'semantic_support_independently_verified':False})
    return result,audit

def receive(observation,row,blocks,allowed,validate):
    clean,audit=align(observation,blocks,allowed)
    if not audit:return row
    checked=validate(clean);result=deepcopy(row)
    for key in ['value_raw','unit_raw','target_id','sample_id','entity_id','value_role']:
        assert row.get(key)==checked.get(key),('Citation relocation changed core',key)
    result['status']=checked['status'];result['reasons']=deepcopy(checked['reasons'])
    if 'core_status' in checked:result['core_status']=checked['core_status']
    result['reference_location_audit']=audit
    result['validated_condition_evidence']=deepcopy(checked.get('conditions_raw'))
    assert result['conditions_raw']==row['conditions_raw']
    return result
