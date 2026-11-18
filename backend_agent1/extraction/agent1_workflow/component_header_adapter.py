"""Optional deterministic regression repair; raw trial results remain immutable.

Only an explicit X_{c, COMPONENT} declared header covering the measured value may
provide a missing component condition. No guessing from names, target truth or samples.
"""
from copy import deepcopy
import re
import shutil
from common import *

def inherit(observation, table_cells):
    original=deepcopy(observation);o=deepcopy(observation)
    if o.get('target_id')!='specialized_property_vocabulary:crystallinity' or o.get('value_role')!='measured':return o,None
    if o.get('subtype_raw'):return o,None
    if not isinstance(o.get('conditions',[]),list):return o,None
    if any('component' in str(c.get('name_raw','')).casefold() or 'phase' in str(c.get('name_raw','')).casefold()
           for c in o.get('conditions',[]) if isinstance(c,dict)):return o,None
    source=table_cells.get(o.get('source_cell_id'))
    if not source:return o,None
    matches=[]
    for cid in o.get('property_source_cell_ids',[]):
        header=table_cells.get(cid)
        if not header or header['table_id']!=source['table_id']:continue
        if header['row_index']>=source['row_index']:continue
        if not header['column_index']<=source['column_index']<header['column_index']+header.get('column_span',1):continue
        found=re.search(r'\bX\s*_\s*\{\s*[cC]\s*,\s*([A-Za-z][A-Za-z0-9-]*)\s*\}',header['text'])
        if found:matches.append((header,found.group(1)))
    unique={(h['cell_id'],label):(h,label) for h,label in matches}
    if len(unique)!=1:return o,None
    header,label=next(iter(unique.values()))
    condition={'name_raw':'component','value_raw':label,'source_cell_ids':[header['cell_id']],
       'source_block_id':header['table_id'],'quote':header['text'],
       'inheritance':'literal_component_from_declared_covering_Xc_header'}
    o.setdefault('conditions',[]).append(condition)
    for key in ('target_id','sample_id','value_raw','unit_raw','value_role','quote','source_cell_id'):
        assert o.get(key)==original.get(key)
    return o,condition

