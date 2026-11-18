"""Exact citations spanning two adjacent prose blocks; no word/number rewriting."""
from copy import deepcopy
import re
from stage3_completion import source_proof

def index(text):
    offsets=[i for i,c in enumerate(text) if not c.isspace()]
    return ''.join(text[i] for i in offsets),offsets

def split(ref,blocks,allowed):
    bid=ref.get('source_block_id');quote=ref.get('quote')
    if not isinstance(quote,str) or not quote or bid not in allowed or source_proof(blocks,bid,quote):return None
    wanted,_=index(quote)
    if not wanted:return None
    prose=[(key,b) for key,b in blocks.items() if b.get('type') in ('text','paragraph') and b.get('text','').strip()]
    matches=[]
    for (left_id,left),(right_id,right) in zip(prose,prose[1:]):
        if bid not in (left_id,right_id) or left_id not in allowed or right_id not in allowed:continue
        l,lo=index(left['text']);r,ro=index(right['text']);combined=l+r;boundary=len(l)
        for m in re.finditer('(?='+re.escape(wanted)+')',combined):
            start=m.start();end=start+len(wanted)
            if not start<boundary<end:continue
            a,b=lo[start],ro[end-boundary-1]+1
            refs=[{'kind':'text','source_block_id':left_id,'quote':left['text'][a:],
                   'source_start':a,'source_end':len(left['text'])},
                  {'kind':'text','source_block_id':right_id,'quote':right['text'][:b],
                   'source_start':0,'source_end':b}]
            if all(source_proof(blocks,x['source_block_id'],x['quote']) for x in refs):matches.append(refs)
    return matches[0] if len(matches)==1 else None

def align(observation,blocks,allowed):
    o=deepcopy(observation);changes=[]
    for c in o.get('conditions',[]) or []:
        if not isinstance(c,dict):continue
        typed=isinstance(c.get('evidence_refs'),list)
        refs=c['evidence_refs'] if typed else [{'kind':'text','source_block_id':c.get('source_block_id'),'quote':c.get('quote')}]
        updated=[];local=[]
        for ref in refs:
            if not isinstance(ref,dict) or ref.get('kind')!='text':updated.append(deepcopy(ref));continue
            pieces=split(ref,blocks,allowed)
            if pieces is None:updated.append(deepcopy(ref));continue
            updated.extend(pieces)
            local.append({'action':'exact_adjacent_prose_continuation','original_evidence_claim':deepcopy(ref),
                'split_evidence_refs':pieces,'condition_name_raw':c.get('name_raw'),'condition_value_unchanged':True})
        if local:
            if not typed:c['original_evidence_claim']={k:c.pop(k) for k in ('source_block_id','quote') if k in c}
            c['evidence_refs']=updated;c['citation_continuation_audit']=local;changes.extend(local)
    return o,changes
