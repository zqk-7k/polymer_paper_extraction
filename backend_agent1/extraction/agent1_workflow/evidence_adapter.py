"""Deterministic source-interface adaptation after raw fresh inference. No values are fixed."""
from copy import deepcopy
import re,sys
from common import OUT,read,write as save,sha

from axis_adapter import align
from table_reader import matches
from mapping_contract import sources_for,exact_quote,proof_refs,read_table,finalize_mapping

def normalize_condition_refs(task,response):
    result=deepcopy(response);sources=sources_for(task);audit=[];tid=task['table_id']
    for group in ('property_axes','subject_axes','cell_overrides'):
        for i,axis in enumerate(result.get(group,[])):
            for j,condition in enumerate(axis.get('conditions',[])):
                refs=condition.get('evidence_refs',[])
                for k,ref in enumerate(refs):
                    sid=ref.get('source_id') or ref.get('source_block_id')
                    source=sources.get(sid);quote=ref.get('quote')
                    if not source and sid==tid:
                        matches=[s for s in sources.values() if s.get('table_id')==tid
                          and s.get('kind') in ('ocr_footnote','pdf_legend_visual_transcription')
                          and exact_quote(quote,s.get('text',''))]
                        if len(matches)==1:source=matches[0];sid=source['source_id']
                    if not source or source.get('table_id',tid)!=tid or not exact_quote(quote,source.get('text','')):continue
                    canonical=proof_refs([{'source_id':sid,'quote':quote}],sources)[0]
                    if ref!=canonical:
                        audit.append({'location':f'{group}[{i}].conditions[{j}].evidence_refs[{k}]',
                                      'original':deepcopy(ref),'canonical':canonical})
                        refs[k]=canonical
    return result,audit

def normalize_rule_refs(task,response):
    """Rule decisions use source_id; accept independently located typed proof addresses."""
    result=deepcopy(response);sources=sources_for(task);audit=[];tid=task['table_id']
    groups=[]
    for name in ('symbol_rules','field_decisions'):
        for i,rule in enumerate(result.get(name,[])):
            groups.append((f'{name}[{i}]',rule.get('evidence_refs',[]),rule))
            if name=='symbol_rules':
                groups.extend((f'{name}[{i}].conditions[{j}]',c.get('evidence_refs',[]),rule) for j,c in enumerate(rule.get('conditions',[])))
    for location,refs,scope in groups:
        for i,ref in enumerate(refs):
            sid=ref.get('source_id') or ref.get('source_cell_id') or ref.get('source_block_id')
            source=sources.get(sid)
            if not source and sid==tid:
                notes=[s for s in sources.values() if s.get('table_id')==tid
                   and s.get('kind') in ('ocr_footnote','pdf_legend_visual_transcription')
                   and exact_quote(ref.get('quote'),s.get('text',''))]
                if len(notes)==1:source=notes[0];sid=source['source_id']
                elif not notes:
                    # A table-level reference may quote a unique declared header.
                    # Never resolve it against data cells or outside its own axis.
                    axis=scope.get('applies_to',scope)
                    properties=[p for p in result.get('property_axes',[]) if p.get('axis')==axis.get('axis')
                        and set(p.get('indices',[]))&set(axis.get('indices',[]))]
                    header_ids={cid for p in properties for cid in p.get('source_cell_ids',[])}
                    rawcells={c['cell_id']:c for c in task['source_table']['cells']}
                    found=[]
                    for cid in header_ids:
                        c=rawcells.get(cid)
                        if c and not any(matches(subject,c) for subject in result.get('subject_axes',[])) and exact_quote(ref.get('quote'),c['text']):
                            found.append(cid)
                    if len(found)==1:sid=found[0];source=sources[sid]
            if not source or source.get('table_id',tid)!=tid or not exact_quote(ref.get('quote'),source.get('text','')):continue
            if ref.get('source_id')==sid:continue
            audit.append({'location':location+f'.evidence_refs[{i}]','original':deepcopy(ref),'added_source_id':sid})
            ref['source_id']=sid
    return result,audit

def alternative_state(observation):
    """Annotate an already preserved, literal temperature disjunction; never select a branch."""
    rule=observation.get('symbol_rule') or {}
    if rule.get('regime') not in ('heated','heated_alternative'):return observation,None
    candidates=[c for c in observation.get('conditions',[]) if 'temperature' in str(c.get('name_raw','')).casefold()
       and isinstance(c.get('value_raw'),str) and re.search(r'\bor\b',c['value_raw'])
       and exact_quote(c['value_raw'],rule.get('condition_text_raw',''))]
    if not candidates:return observation,None
    result=deepcopy(observation)
    result['condition_resolution']='alternative_preserved'
    result['test_regime_effective']='heated_alternative'
    return result,{'source_cell_id':observation['source_cell_id'],
        'original_declared_regime':rule['regime'],'effective_regime':'heated_alternative',
        'basis':'literal_or_branch_already_preserved_in_temperature_raw_and_validated_table_rule',
        'condition_values_and_units_unchanged':True}
