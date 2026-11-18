"""Lossless table request transport. Source measurement strings are never parsed."""
from copy import deepcopy
import re

REF_KEYS = {'cell_id','source_cell_id','source_cell_ids','property_source_cell_ids','unit_source_cell_ids','cell_ids','source_ids'}

def short_id(row, column):
    return f'r{row}c{column}'

def pack(table):
    cells = table['cells']; mapping = {}; triples = []; spans = []; headers = []
    for c in cells:
        r, col = c['row_index'], c['column_index']; sid = short_id(r,col)
        assert sid not in mapping, 'Duplicate source table coordinate'
        mapping[sid] = c['cell_id']; triples.append([r,col,c['text']])
        rs, cs = c.get('row_span',1), c.get('column_span',1)
        if (rs,cs) != (1,1): spans.append([r,col,rs,cs])
        if c.get('is_header'): headers.append(sid)
    grid = {'format':'rc_text.v1','cells':triples,'spans':spans}
    if headers: grid['header_cells'] = headers
    compact = {k:deepcopy(table[k]) for k in ('table_id','caption','notes') if k in table}
    compact.update(grid)
    return compact, mapping

def unpack(compact, mapping):
    spans = {(x[0],x[1]):x[2:] for x in compact['spans']}; headers=set(compact.get('header_cells',[]))
    cells=[]
    for r,c,text in compact['cells']:
        sid=short_id(r,c);rs,cs=spans.get((r,c),(1,1))
        cells.append({'cell_id':mapping[sid],'row_index':r,'column_index':c,'row_span':rs,
                      'column_span':cs,'text':text,'is_header':sid in headers})
    return {**{k:deepcopy(compact[k]) for k in ('table_id','caption','notes') if k in compact},'cells':cells}

def restore_response(data, mapping):
    """Translate references only, never measurement strings, quotes or meanings."""
    unknown=[]
    def visit(value, key=None):
        if isinstance(value,dict): return {k:visit(v,k) for k,v in value.items()}
        if isinstance(value,list): return [visit(v,key) for v in value]
        if isinstance(value,str) and key in REF_KEYS:
            if value in mapping:return mapping[value]
            if re.fullmatch(r'r\d+c\d+',value):unknown.append(value)
        return value
    return visit(data), sorted(set(unknown))

INSTRUCTION = '''
Request packing: table.cells contains [row_index,column_index,EXACT_RAW_TEXT] triples,
with zero-based coordinates; spans contains [row,column,row_span,column_span] only for
non-default spans, all other spans are 1. Preserve empty cells and merged-cell structure.
Reference a supplied cell by r{row}c{column}, e.g. r1c2, in every cell-reference field;
do not invent coordinates or reference a covered merged-cell position lacking its own triple.
The program restores these short IDs to the original source IDs before reading raw values.
target_index lists every permitted field as section plus key. target_fields gives relevant
short definitions, NOT an exclusive whitelist; confidently supported other indexed fields
may be returned using their full section:key IDs. Preserve unknown mappings when uncertain.
Shared method fragments are exact source slices with original block IDs; they support
interpretation, while owned-source restrictions still apply. Do not repeat context-only values.
'''

TEXT_INSTRUCTION = '''
target_index lists all permitted fields as section plus key. target_fields contains relevant
short definitions, not an exclusive whitelist. Use the full section:key ID for a supported
indexed field even if its detailed definition was not selected; uncertain mappings remain null.
Shared method fragments retain original block IDs and exact source text. Owned blocks are
complete; context/method snippets support interpretation, not independent duplicate extraction.
'''

from condition_evidence import EVIDENCE_GUIDANCE
INSTRUCTION += EVIDENCE_GUIDANCE + '''
Condition axes must name their application scope with applies_to:{axis:"column"|"row",
indices:[...]}, and value_location:"header"|"data_axis". A frequency header such as
1 MHz labels results underneath that header; it is not a column containing frequency
values. Scope it only to the corresponding property columns, never to adjacent water
absorption or other unrelated properties. Measurement values under dielectric columns
are dielectric results, never test frequencies. For a genuine separate condition data
column, declare data_axis and an explicit application scope. Retain uncertain axes in
unresolved, without fabricating a condition or excluding its measurement cells.
'''
TEXT_INSTRUCTION += EVIDENCE_GUIDANCE
TEXT_INSTRUCTION += '''
For this full-text grouped trial, target_fields and target_index are the SAME EXCLUSIVE
task whitelist with complete definitions. The earlier general short-definition guidance
does not permit fields outside this task. table_context is losslessly packed structural
context, not an instruction to repeat table extraction. Every text block is supplied in full.
'''
