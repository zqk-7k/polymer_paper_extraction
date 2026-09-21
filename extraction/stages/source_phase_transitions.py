"""Reported phase-chain values, gated by explicit same-page symbol definitions.

No arithmetic, figure reading, generic numeric-list splitting or gold access.
"""
from __future__ import annotations
import copy
import hashlib
import re
from schema.polymer_schema import PropertySeries
from stages.stage4_direct_table_supplement import table_requests, plain, evidence, header_applies

VERSION='1.0.1'
NUMBER=r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)'
CHAIN=re.compile(rf'^g\s+({NUMBER})\s+(s_?A|LC)\s+({NUMBER})\s+i$')


def phase_definitions(text):
    text=re.sub(r'\s+',' ',plain(text))
    if not re.search(r'\bg\s*:\s*glass transition',text,re.I):return set()
    if not re.search(r'\bi\s*:\s*isotropic',text,re.I):return set()
    phases=set()
    if re.search(r'\bs_?A\s*:\s*smectic A',text,re.I):phases.add('sA')
    if re.search(r'\bLC\s*:\s*liquid[\s-]*crystalline',text,re.I):phases.add('LC')
    return phases


def parse_phase_chain(surface, definitions):
    match=CHAIN.fullmatch(plain(surface).replace('−','-'))
    if not match or match[2].replace('_','') not in definitions:return []
    phase=match[2].replace('_','')
    return [{'raw':match[1],'value':float(match[1]),'from':'g','to':phase,'kind':'glass transition temperature'},
            {'raw':match[3],'value':float(match[3]),'from':phase,'to':'i',
             'kind':'smectic A-to-isotropic transition temperature' if phase=='sA' else 'liquid-crystalline-to-isotropic transition temperature'}]


def recover_pdf_phase_legends(stage0, page_blocks, pdf_sha256):
    """Append actual native PDF blocks; retain original OCR and stable IDs."""
    out=copy.deepcopy(stage0);existing={b['block_id'] for b in out['elements']};audit=[]
    pages={b.get('page') for b in out['elements'] if b['type']=='table'}
    index=max((b.get('source_block_index') or 0 for b in out['elements']),default=0)+1
    for page,blocks in page_blocks.items():
        if page not in pages:continue
        for block in blocks:
            text=block['text']
            if not phase_definitions(text):continue
            digest=hashlib.sha256((str(page)+text).encode()).hexdigest()[:16]
            bid=f'PDFPHASE_{page}_{digest}'
            if bid in existing:continue
            if any(b.get('page')==page and text in (b.get('text') or '') for b in out['elements']):continue
            out['elements'].append({'block_id':bid,'type':'footnote','page':page,'bbox':None,
                'text':text,'source_block_index':index,'alignment_status':'verbatim_pdf_text_layer_legend'})
            existing.add(bid);index+=1
            audit.append({'block_id':bid,'page':page,'verbatim_text':text,'pdf_sha256':pdf_sha256,
                'native_bbox_points':block.get('bbox'),'bbox_in_stage0':'null; do not mix PDF points with OCR pixel coordinates'})
    return out,{'version':VERSION,'recovered':len(audit),'blocks':audit,'gold_access':False}


def recover_phase_transitions(stage4,stage0):
    out=copy.deepcopy(stage4);series=out.setdefault('property_series',[]);decisions=[]
    existing=set()
    for s in series:
        for p in s.get('points',[]):
            ctx=(p.get('measurement_context') or {}).get('other_conditions') or {}
            if ctx.get('source_binding_method')!='explicit_phase_chain_with_source_legend':continue
            for ev in p.get('evidence',[]):
                cid=(ev.get('table_locator') or {}).get('cell_id')
                if cid:existing.add((cid,ctx.get('source_phase_from'),ctx.get('source_phase_to'),p.get('value_raw')))
    start=max([int(s['series_id'][6:]) for s in series] or [0])+1
    for table in table_requests(stage0):
        legends=[b for b in stage0['elements'] if b.get('page')==table.get('page') and phase_definitions(b.get('text',''))]
        if not legends:continue
        # Conflicting definitions are not reconciled by guessing; require a
        # common interpretation among all matching local legends.
        defs=set.intersection(*(phase_definitions(b['text']) for b in legends))
        if not defs:
            decisions.append({'accepted':False,'table_id':table['table_id'],'reason':'no_common_same_page_phase_definition'})
            continue
        cells=table['cells'];groups={}
        for cell in cells:
            parsed=parse_phase_chain(cell['text'],defs)
            if not parsed:continue
            heads=[c for c in cells if c['row_index']<cell['row_index'] and header_applies(c,cell)
                   and (re.search(r'(?:thermal|phase)\s+transitions?',plain(c['text']),re.I)
                        or re.fullmatch(r'°\s*C',plain(c['text'])))]
            header=' | '.join(c['text'] for c in heads)
            if not re.search(r'(?:thermal|phase)\s+transitions?',plain(header),re.I) or not re.search(r'°\s*C',plain(header)):
                continue
            sample_heads=[c for c in cells if c['row_index']<cell['row_index'] and re.fullmatch(r'Polymer|Sample',plain(c['text']),re.I)]
            sample_cols={c['column_index'] for c in sample_heads}
            labels=[c for c in cells if c['row_index']==cell['row_index'] and c['column_index'] in sample_cols and c['text'].strip()]
            if len(labels)!=1:continue
            label=labels[0];legend=legends[0]
            for component in parsed:
                key=(cell['cell_id'],component['from'],component['to'],component['raw'])
                if key in existing:
                    decisions.append({'accepted':False,'reason':'duplicate_phase_chain_source_value','cell_id':cell['cell_id']});continue
                existing.add(key)
                context={'condition_status':'reported','other_conditions':{
                    'source_binding_method':'explicit_phase_chain_with_source_legend',
                    'source_phase_from':component['from'],'source_phase_to':component['to'],
                    'full_source_cell':cell['text'],'source_property_header':header,
                    'source_phase_legend':legend['text'],'confidence_status':'not_estimated',
                    'source_subject_binding_scope':'table-local label retained; canonical sample unresolved'},
                    'other_condition_evidence':{'source_phase_legend':[{'block_id':legend['block_id'],'page':legend.get('page'),
                            'bbox':legend.get('bbox'),'source_type':legend['type'],'source_sentence':legend['text']}]}}
                points=groups.setdefault(component['kind'],[])
                points.append({'point_id':f'pt{len(points)+1:03d}','sample_resolution_status':'unresolved',
                    'coordinates':[{'name_raw':'source sample label','value_raw':label['text'],
                        'evidence':evidence(table,label,row_label=label['text'],column_label='Polymer')}],
                    'value_raw':component['raw'],'value_min':component['value'],'value_max':component['value'],
                    'unit_raw':'°C','unit_normalized':'°C','measurement_context':context,'coverage_status':'covered',
                    'evidence':[evidence(table,cell,row_label=label['text'],column_label=header)],'confidence':{'score':0.0}})
                decisions.append({'accepted':True,'cell_id':cell['cell_id'],'property':component['kind'],
                    'value':component['value'],'sample_label':label['text'],'legend_block_id':legend['block_id']})
        for kind,points in groups.items():
            record={'series_id':f'series{start:03d}','sample_resolution_status':'unresolved',
                'property_name_raw':kind,'property_name_normalized':kind,'unit_raw':'°C','unit_normalized':'°C',
                'measurement_context':{'condition_status':'reported','other_conditions':{'source_binding_method':'explicit_phase_chain_with_source_legend'}},
                'points':points,'coverage':{'expected':len(points),'covered':len(points),'missing':0,'not_applicable':0,'ratio':1.0},
                'evidence':[p['evidence'][0] for p in points],'confidence':{'score':0.0}}
            series.append(PropertySeries.model_validate(record).model_dump(mode='json'));start+=1
    return out,{'version':VERSION,'decisions':decisions,'points_added':sum(d['accepted'] for d in decisions),'gold_access':False}
