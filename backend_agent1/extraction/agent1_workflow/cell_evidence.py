"""Canonicalize explicit same-table cell addresses after all annotations are added."""
from copy import deepcopy
import sys
from evidence_text import view
from range_evidence import range_view


def canonical(observation,blocks,cells,allowed):
    from condition_evidence import valid_refs
    o=deepcopy(observation);audit=[]
    conditions=o.get('conditions',[])
    if not isinstance(conditions,list):return o,audit
    table_id=cells.get(o.get('source_cell_id'),{}).get('table_id')
    for i,condition in enumerate(conditions):
        if not isinstance(condition,dict):continue
        explicit=condition.get('source_cell_ids',[])
        explicit=[explicit] if isinstance(explicit,str) else explicit if isinstance(explicit,list) else []
        if any(not isinstance(cid,str) for cid in explicit):continue
        refs=condition.get('evidence_refs')
        if refs is None and (condition.get('source_block_id') or explicit) and condition.get('quote'):
            refs=[{'source_block_id':condition.get('source_block_id'),'quote':condition['quote']}]
        if not isinstance(refs,list):continue
        result=[];changed=False
        for j,ref in enumerate(refs):
            valid_shape=isinstance(ref,dict) and isinstance(ref.get('source_block_id'),str) and isinstance(ref.get('quote'),str)
            if valid_shape and ref.get('kind')=='table_cell':valid_shape=isinstance(ref.get('source_cell_id'),str)
            if not isinstance(ref,dict) or (valid_shape and valid_refs([ref],blocks,cells,table_id,allowed)):
                result.append(ref);continue
            bid=ref.get('source_block_id') or condition.get('source_block_id')
            quote=ref.get('quote');direct=ref.get('source_cell_id')
            if direct is not None and not isinstance(direct,str):result.append(ref);continue
            cids=list(dict.fromkeys(([direct] if direct is not None else [])+explicit))
            if (bid is not None and (not isinstance(bid,str) or bid not in allowed or blocks.get(bid,{}).get('type')!='table')) or not isinstance(quote,str):
                result.append(ref);continue
            hits=[]
            for cid in cids:
                cell=cells.get(cid,{})
                cell_table=cell.get('table_id')
                if cell_table not in allowed or blocks.get(cell_table,{}).get('type')!='table' or (bid is not None and cell_table!=bid):continue
                same=view(cell.get('text',''))[0]==view(quote)[0] or range_view(cell.get('text',''))[0]==range_view(quote)[0]
                if same and quote:hits.append(cid)
            if len(hits)!=1:result.append(ref);continue
            cid=hits[0]
            bid=cells[cid]['table_id']
            typed={'kind':'table_cell','source_block_id':bid,'source_cell_id':cid,'quote':cells[cid]['text']}
            if not valid_refs([typed],blocks,cells,table_id,allowed):result.append(ref);continue
            result.append(typed);changed=True
            audit.append({'condition_index':i,'reference_index':j,'original_reference':deepcopy(ref),
                'canonical_reference':deepcopy(typed),'basis':'explicit_cell_id_same_table_unique_full_cell_quote',
                'condition_value_and_unit_unchanged':True})
        if changed:condition['evidence_refs']=result
    for field in ('value_raw','unit_raw','sample_id','target_id'):assert o.get(field)==observation.get(field)
    return o,audit


def install():
    import finalize,run_trial
    from stage4r import source_index
    if getattr(finalize,'cell_evidence_installed',False):return
    def wrap(function):
        def record(observation,ref,stage0,identity,catalog,owned_ids,evidence_ids=None):
            blocks,cells=source_index(stage0)
            o,audit=canonical(observation,blocks,cells,set(owned_ids if evidence_ids is None else evidence_ids))
            row=function(o,ref,stage0,identity,catalog,owned_ids,evidence_ids)
            if audit:row['cell_evidence_reference_adaptations']=audit
            return row
        return record
    base=finalize.observation_record;runner=run_trial.observation_record
    finalize.observation_record=wrap(base)
    run_trial.observation_record=finalize.observation_record if runner is base else wrap(runner)
    finalize.cell_evidence_installed=True
