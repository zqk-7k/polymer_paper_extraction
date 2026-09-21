"""Read independently PDF-verified exponent continuation, never guess a run.

The literal cell remains unchanged. The certificate only identifies a source
notation; numerical exponents are re-read from real preceding reset cells.
"""
import copy
import math
import re
from stages.stage4_direct_table_supplement import plain, table_cell_scalar, canonical_unit

VERSION='1.0.0'


def verified_run_scales(stage0):
    certificate=stage0.get('ocr',{}).get('source_pdf_verification',{})
    if (certificate.get('version')!='pdf-two-engine-transcription/1.0.0'
        or certificate.get('reference_values_accessed') is not False
        or certificate.get('predictions_accessed') is not False):return {}
    tables={t['block_id']:t for t in stage0.get('elements',[]) if t.get('type')=='table'}
    result={};conflicts=set()
    for n in certificate.get('shared_exponent_notations',[]):
        if n.get('kind')!='shared_scientific_notation_exponent' or not n.get('review_sha256') or not n.get('image_sha256'):continue
        table=tables.get(n.get('table_block_id'),{});cells={c['cell_id']:c for c in table.get('table_cells',[])}
        reset_ids=n.get('reset_cell_ids') or []
        targets=n.get('applies_to_cell_ids') or []
        col=n.get('column_index')
        if len(reset_ids)<2 or set(reset_ids)&set(targets):continue
        if any(cid not in cells or cells[cid]['column_index']!=col for cid in reset_ids+targets):continue
        resets=[]
        for cid in reset_ids:
            text=plain(cells[cid]['text']).replace(r'\times','×').replace('−','-')
            m=re.fullmatch(r'\s*[+-]?\d+(?:\.\d+)?\s*×\s*10\^([+-]?\d{1,2})\s*',text)
            if not m or abs(int(m[1]))>12:break
            resets.append((cells[cid]['row_index'],cid,int(m[1])))
        else:
            for cid in targets:
                cell=cells[cid];value=table_cell_scalar(cell['text'])
                # A target carrying its own exponent is not an unadorned cell.
                if value is None or not re.fullmatch(r'[+-]?\d+(?:\.\d+)?',plain(cell['text'])):continue
                preceding=[r for r in resets if r[0]<cell['row_index']]
                if not preceding:continue
                row,reset,exponent=max(preceding)
                item={'factor':10.**exponent,'reset_cell_id':reset,'literal':cell['text'],
                      'value':value,'review_sha256':n['review_sha256'],'image_sha256':n['image_sha256']}
                if cid in result and result[cid]['factor']!=item['factor']:conflicts.add(cid)
                result[cid]=item
    return {cid:item for cid,item in result.items() if cid not in conflicts}


def repair_verified_exponent_runs(stage4,stage0):
    output=copy.deepcopy(stage4);scales=verified_run_scales(stage0);changes=[]
    records=[(r,r,k) for k in ['properties','specialized_property_observations'] for r in output.get(k,[])]
    records += [(p,s,'property_series') for s in output.get('property_series',[]) for p in s.get('points',[])]
    for item,parent,container in records:
        ids={(e.get('table_locator') or {}).get('cell_id') for e in item.get('evidence',[])}-{None}
        if len(ids)!=1:continue
        cid=next(iter(ids));n=scales.get(cid)
        if not n:continue
        raw=item.get('unit_raw') or parent.get('unit_raw')
        normalized=item.get('unit_normalized') or parent.get('unit_normalized') or raw
        if canonical_unit(raw)!=canonical_unit(normalized):continue
        before=(item.get('value_min'),item.get('value_max',item.get('value_min')))
        if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in before):continue
        after=n['value']*n['factor']
        if all(math.isclose(v,after,rel_tol=1e-12,abs_tol=0) for v in before):continue
        item['value_min']=item['value_max']=after
        ctx=item.setdefault('measurement_context',{});ctx['condition_status']='reported'
        ctx.setdefault('other_conditions',{}).update(
            source_exponent_run_reset_cell=n['reset_cell_id'],source_exponent_run_factor=str(n['factor']),
            source_exponent_run_raw_cell=n['literal'],source_exponent_run_pdf_review_sha256=n['review_sha256'],
            source_exponent_run_basis='PDF-verified omitted repeated exponent; reset magnitude read from original source cell')
        changes.append({'container':container,'cell_id':cid,'before':before,'after':after,**n})
    return output,{'version':VERSION,'changes':changes,'certified_source_cells':len(scales),'gold_access':False}
