"""Locate exact original citation spans despite one narrowly defined TeX layout space.

Only a tilde BETWEEN a digit and a TeX superscript degree sign, inside dollar math,
is layout. Approximation markers, digits, words, punctuation and all values stay intact.
"""
from copy import deepcopy
import re
from stage3_completion import source_proof
from intake_v2 import observation as normalize_observation

def layout_positions(text):
    positions=set()
    for math in re.finditer(r'(?<!\\)\$(.*?)(?<!\\)\$',text,re.S):
        for space in re.finditer(r'(?<=\d)\s*(~)\s*(?=\^\s*\{\s*\\circ\s*\})',math.group(1)):
            positions.add(math.start(1)+space.start(1))
    return positions

def citation_index(text):
    ignored=layout_positions(text);characters=[];offsets=[]
    for index,value in enumerate(text):
        if value.isspace() or index in ignored:continue
        characters.append(value);offsets.append((index,index+1))
    return ''.join(characters),offsets

def exact_original_span(source,quote):
    if not isinstance(quote,str) or not layout_positions(quote):return None
    text,offsets=citation_index(source);wanted,_=citation_index(quote)
    if not wanted:return None
    positions=[m.start() for m in re.finditer('(?='+re.escape(wanted)+')',text)]
    if len(positions)!=1:return None
    index=positions[0];start=offsets[index][0];end=offsets[index+len(wanted)-1][1]
    before=text[index-1] if index else ''
    after=text[index+len(wanted):index+len(wanted)+1]
    if wanted[0].isdigit() and before and before in '0123456789.,':return None
    if wanted[-1].isdigit() and after and after in '0123456789.,':return None
    # Include closing source math punctuation so the original excerpt is readable.
    while end<len(source) and source[end] in '}$':end+=1
    return {'quote':source[start:end],'source_start':start,'source_end':end}

def align(observation,blocks,allowed):
    o=normalize_observation(observation,blocks)
    changes=[{'action':a,'value_raw_unchanged':True} for a in o.get('intake_adaptations',[])]
    for c in o.get('conditions',[]) or []:
        if not isinstance(c,dict):continue
        refs=c.get('evidence_refs')
        candidates=refs if isinstance(refs,list) else [c]
        for ref in candidates:
            if not isinstance(ref,dict) or ref.get('kind','text')!='text':continue
            bid=ref.get('source_block_id');quote=ref.get('quote');block=blocks.get(bid,{})
            if bid not in allowed or block.get('type') not in ('text','paragraph'):continue
            if source_proof(blocks,bid,quote):continue
            span=exact_original_span(block.get('text',''),quote)
            if not span or not source_proof(blocks,bid,span['quote']):continue
            ref['quote_original_before_alignment']=quote;ref['quote']=span['quote']
            changes.append({'source_block_id':bid,'original_model_quote':quote,**span,
                            'condition_name_raw':c.get('name_raw'),'condition_value_unchanged':True})
    return o,changes
