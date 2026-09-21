"""Publish guarded source-labelled rows recovered from missing table colspans.

Reuses the existing Stage 4T paired PMT/viscosity alignment test. No global
sample ID is guessed. Each row retains its code, subrow and HTS/LTS method.
"""
from __future__ import annotations
import copy
import re
from schema.polymer_schema import PropertySeries, Stage0Document
from stages.stage4t_table_property import shadow_extract_table
from stages.stage4_direct_table_supplement import evidence, plain, scalar
from stages.table_grid import table_cells_for

VERSION = '1.0.1'


def aligned_source_key(point):
    """A claimed source row survives downstream Celsius/unit normalization."""
    context=(point.get('measurement_context') or {}).get('other_conditions') or {}
    if context.get('alignment_status')!='paired_right_shift':return None
    cells=tuple(sorted(((e.get('table_locator') or {}).get('table_id',''),
                        (e.get('table_locator') or {}).get('cell_id',''))
                       for e in point.get('evidence',[]) if (e.get('table_locator') or {}).get('cell_id')))
    if not cells:return None
    labels=tuple((c.get('name_raw',''),c.get('value_raw','')) for c in point.get('coordinates',[]))
    return (cells,point.get('value_raw'),labels)


def recover_aligned_temperature_rows(stage4: dict, stage0: dict) -> tuple[dict, dict]:
    out=copy.deepcopy(stage4); series=out.setdefault('property_series',[])
    seen={k for s in series for p in s.get('points',[]) if (k:=aligned_source_key(p)) is not None}
    start=max([int(s['series_id'][6:]) for s in series] or [0])+1
    audit=[]
    for element in Stage0Document.model_validate(stage0).elements:
        if element.type!='table':continue
        shadow=shadow_extract_table(element)
        candidates=[o for o in shadow['observations'] if o.get('alignment_status')=='paired_right_shift'
                    and o.get('property_name_normalized')=='melting_temperature']
        if not candidates:continue
        cells=[c.model_dump(mode='json') for c in table_cells_for(element)]
        byid={c['cell_id']:c for c in cells}
        headers=set(shadow['header_rows'])
        codes=[c for c in cells if c['row_index'] in headers and re.match(r'^Code\b|^Code[a-z]$',plain(c['text']))]
        if len(codes)!=1:continue
        code_column=codes[0]['column_index']; points=[]
        table={'table_id':element.block_id,'page':element.page,'bbox':element.bbox}
        for o in candidates:
            cell=byid.get(o['cell_id']); row=o['row_index']
            value=scalar(cell['text']) if cell else None
            code_cells=[c for c in cells if c['column_index']==code_column and c['row_index']<=row
                        and c['row_index'] not in headers and c['text'].strip()]
            row_cells=[c for c in cells if c['row_index']==row]
            methods=[c for c in row_cells if re.fullmatch(r'(HTS|LTS)',c['text'].strip())]
            property_headers=[c for c in cells if c['row_index'] in headers and c['column_index']==o['header_column_index']
                              and re.search(r'PMT',c['text']) and re.search(r'°\s*C',plain(c['text']))]
            if value is None or not code_cells or len(methods)!=1 or len(property_headers)!=1:
                audit.append({'accepted':False,'cell_id':o['cell_id'],'reason':'row_identity_method_or_header_unverified'});continue
            code=max(code_cells,key=lambda c:c['row_index']);header=property_headers[0]
            label=code['text'];ev=evidence(table,cell,row_label=label,column_label=header['text'])
            coords=[{'name_raw':'source sample code','value_raw':label,'evidence':evidence(table,code,row_label=label,column_label='Code')},
                    {'name_raw':'source polymerization method','value_raw':methods[0]['text'],
                     'evidence':evidence(table,methods[0],row_label=label,column_label='Method of polymerization')}]
            tags=[c for c in row_cells if c['column_index']<code_column and c['text'].strip()]
            coords += [{'name_raw':'source subrow label','value_raw':c['text'],'evidence':evidence(table,c,row_label=label,column_label='No.')} for c in tags]
            context={'condition_status':'reported','other_conditions':{
                'alignment_status':'paired_right_shift','alignment_basis':'existing Stage4T paired PMT/viscosity missing-colspan rule',
                'source_property_header':header['text'],'source_caption':element.caption or '',
                'global_sample_binding':'unresolved; source code, subrow and synthesis method retained separately'}}
            point={'point_id':f'pt{len(points)+1:03d}','sample_resolution_status':'unresolved','coordinates':coords,
                'value_raw':cell['text'],'value_min':value,'value_max':value,'unit_raw':'°C','unit_normalized':'°C',
                'measurement_context':context,'coverage_status':'covered','evidence':[ev],'confidence':{'score':0.0}}
            key=aligned_source_key(point)
            if key in seen:
                audit.append({'accepted':False,'cell_id':cell['cell_id'],'reason':'duplicate_existing_aligned_source_row'})
                continue
            seen.add(key);points.append(point)
            audit.append({'accepted':True,'cell_id':cell['cell_id'],'value':value,'source_code':label,'method':methods[0]['text']})
        if points:
            record={'series_id':f'series{start:03d}','sample_resolution_status':'unresolved',
                'property_name_raw':'PMT','property_name_normalized':'polymer melting temperature','unit_raw':'°C','unit_normalized':'°C',
                'measurement_context':{'condition_status':'reported','other_conditions':{'alignment_status':'paired_right_shift'}},
                'points':points,'coverage':{'expected':len(points),'covered':len(points),'missing':0,'not_applicable':0,'ratio':1.0},
                'evidence':[p['evidence'][0] for p in points],'confidence':{'score':0.0}}
            series.append(PropertySeries.model_validate(record).model_dump(mode='json'));start+=1
    if any(d['accepted'] for d in audit) and not any(w.get('code')=='source_labelled_aligned_rows' for w in out.get('warnings',[])):
        out.setdefault('warnings',[]).append({'stage':'stage4_aligned_table_release','code':'source_labelled_aligned_rows',
            'message':'Source table alignment was reconstructed with the existing guarded paired-column rule. Source row identity/method retained; no global sample or process binding invented. Confidence 0.0 means not estimated.', 'version':VERSION})
    return out,{'version':VERSION,'decisions':audit}
