"""Typed source evidence; exact multi-block citation recovery, no numerical parsing."""
from copy import deepcopy
import re
from stage3_completion import surface,source_proof
from evidence_text import matches as evidence_match

def available_ids(packet,owned):
    ids=set(owned)
    from evidence_registry import protocol_source_ids
    ids.update(protocol_source_ids(packet))
    ids.update(r['source_block_id'] for r in packet.get('shared_evidence_refs',{}).values() if isinstance(r,dict) and r.get('source_block_id'))
    for key in ('owned_blocks','context_blocks','related_blocks','shared_methods'):
        ids.update(b['block_id'] for b in packet.get(key,[]) if isinstance(b,dict) and b.get('block_id'))
    if packet.get('table',{}).get('table_id'):ids.add(packet['table']['table_id'])
    return ids

def valid_refs(refs,blocks,cells,table_id,allowed):
    if not isinstance(refs,list) or not refs:return False
    for ref in refs:
        if not isinstance(ref,dict):return False
        bid=ref.get('source_block_id');kind=ref.get('kind');quote=surface(ref.get('quote'))
        if bid not in allowed or not quote:return False
        if kind=='text':
            if not source_proof(blocks,bid,ref.get('quote')) and not evidence_match(blocks.get(bid,{}).get('text',''),ref.get('quote')):return False
        elif kind=='table_caption':
            b=blocks.get(bid,{})
            if bid!=table_id or b.get('type')!='table' or quote not in surface(b.get('caption','')):return False
        elif kind=='table_cell':
            cid=ref.get('source_cell_id');c=cells.get(cid,{})
            if c.get('table_id')!=bid or quote not in surface(c.get('text','')):return False
        else:return False
    return True

def adapt(conditions,blocks,cells,table_id,allowed):
    result=deepcopy(conditions);audit=[]
    if not isinstance(result,list):return result,audit
    for index,c in enumerate(result):
        if not isinstance(c,dict) or 'evidence_refs' in c:continue
        bid=c.get('source_block_id');quote=c.get('quote');refs=None;reason=None
        b=blocks.get(bid,{})
        if b.get('type')=='table' and not c.get('source_cell_ids') and bid==table_id:
            if surface(quote) and surface(quote) in surface(b.get('caption','')):
                refs=[{'kind':'table_caption','source_block_id':bid,'quote':quote}]
                reason='exact_same_table_caption'
        elif bid and quote and not source_proof(blocks,bid,quote):
            # Every part must match uniquely in the task's supplied source IDs.
            # No nearest match, deletion, paraphrase repair or article-wide search.
            pieces=[p for p in re.split(r'(?<=[.!?])\s+(?=[A-Z])',quote) if p]
            if 2<=len(pieces)<=8:
                found=[]
                for piece in pieces:
                    matches=[key for key in sorted(allowed) if source_proof(blocks,key,piece)]
                    if len(matches)!=1:break
                    found.append({'kind':'text','source_block_id':matches[0],'quote':piece})
                if len(found)==len(pieces) and len({r['source_block_id'] for r in found})>1:
                    refs=found;reason='exact_unique_multi_block_citation_split'
        if refs and valid_refs(refs,blocks,cells,table_id,allowed):
            c['original_evidence_claim']={k:c.pop(k) for k in ('source_block_id','quote') if k in c}
            c['evidence_refs']=refs
            audit.append({'condition_index':index,'action':reason,'evidence_refs':refs,
                          'condition_value_unchanged':True})
    return result,audit

EVIDENCE_GUIDANCE='''
Condition evidence contract v2: each condition keeps name_raw, value_raw, unit_raw and
evidence_refs, a list of {kind:"text"|"table_caption"|"table_cell",source_block_id,
quote,source_cell_id(optional)}. Each quote must be one exact contiguous excerpt from
its own source. If two paragraphs jointly support a condition, supply two evidence_refs;
never concatenate paragraphs under a single source_block_id. Table-caption evidence is
valid only for that same table, using its supplied caption. Do not invent context.
Legacy source_cell_ids remain permitted for literal cell-derived conditions. Preserve
all raw values and units; this is evidence bookkeeping, not format conversion.
'''
