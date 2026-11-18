"""Typed source resolution only. Never change measurements or infer semantic support."""
from copy import deepcopy
import re
from stage3_completion import surface

def registry(raw):
    result={}
    for b in raw['elements']:
        tid=b['block_id'];istable=b.get('type')=='table'
        result[tid]={'source_id':tid,'source_block_id':tid,'kind':'table_caption' if istable else 'text',
                     'text':b.get('caption','') if istable else b.get('text','')}
        if istable:
            for c in b.get('table_cells',[]):
                result[c['cell_id']]={'source_id':c['cell_id'],'source_block_id':tid,'source_cell_id':c['cell_id'],
                    'kind':'table_cell','text':c['text']}
    return result

def original_quote(quote,text):
    if not quote:return None,None
    if surface(quote) and surface(quote) in surface(text):return quote,None
    # Evidence comparison only: the known OCR control character immediately before
    # C/F can stand for a degree mark. Return the original span, never a cleaned value.
    view=re.sub(r'\x01(?=\s*[CF]\b)','°',text)
    if view==text:return None,None
    positions=[i for i,c in enumerate(view) if not c.isspace()]
    compact=''.join(view[i] for i in positions);needle=''.join(str(quote).split())
    start=compact.find(needle)
    if start<0:return None,None
    recovered=text[positions[start]:positions[start+len(needle)-1]+1]
    return recovered,'original_span_recovered_from_context_limited_temperature_glyph'

def resolve(ref,sources,allowed,protocols):
    before=deepcopy(ref);sid=ref.get('source_id') or ref.get('source_cell_id') or ref.get('source_block_id')
    source=sources.get(sid);quote=ref.get('quote');action=None
    if not source:
        matches=[]
        for p in protocols:
            if p.get('protocol_id')!=sid:continue
            ids={s.get('source_block_id') for s in p.get('steps',[])}|{p.get('scope_source_block_id')}
            for bid in ids & allowed:
                s=sources.get(bid)
                if s and original_quote(quote,s['text'])[0]:matches.append(s)
        if len(matches)==1:source=matches[0];action='protocol_reference_resolved_to_unique_declared_original_source'
    if not source:return before,{'state':'unresolved','original':before,'reason':'unknown_or_ambiguous_reference'}
    if source['source_block_id'] not in allowed:return before,{'state':'unresolved','original':before,'reason':'source_not_supplied_to_task'}
    recovered,repair=original_quote(quote,source['text'])
    if recovered is None:return before,{'state':'unresolved','original':before,'reason':'quote_not_found_in_declared_source'}
    out={'kind':source['kind'],'source_block_id':source['source_block_id'],'quote':recovered}
    if source.get('source_cell_id'):out['source_cell_id']=source['source_cell_id']
    if before==out:return out,None
    return out,{'state':'resolved','original':before,'canonical':out,'action':repair or action or 'typed_address_completed',
                'semantic_support_independently_verified':False,'measurement_unchanged':True}

def normalize(conditions,raw,identity,allowed):
    if not isinstance(conditions,list):return conditions,[]
    sources=registry(raw);result=deepcopy(conditions);audit=[]
    for i,c in enumerate(result):
        if not isinstance(c,dict):continue
        refs=c.get('evidence_refs')
        if refs is None and c.get('source_block_id') and c.get('quote'):
            refs=[{k:c[k] for k in ('source_block_id','quote')}]
        if not isinstance(refs,list):continue
        normalized=[]
        for ref in refs:
            if not isinstance(ref,dict):normalized.append(ref);continue
            canonical,change=resolve(ref,sources,allowed,identity.get('protocols',[]));normalized.append(canonical)
            if change:audit.append({'condition_index':i,**change})
        c['evidence_refs']=normalized
    return result,audit

def protocol_source_ids(packet):
    ids=set()
    for p in packet.get('identity_directory',{}).get('protocols',[]):
        for s in p.get('steps',[]):
            ref=s.get('evidence_ref') or {}
            if ref.get('source_block_id') and ref.get('quote'):ids.add(ref['source_block_id'])
        ref=p.get('scope_evidence_ref') or {}
        if ref.get('source_block_id') and ref.get('quote'):ids.add(ref['source_block_id'])
    return ids
