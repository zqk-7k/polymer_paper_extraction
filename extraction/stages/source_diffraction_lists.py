"""Retain individually printed d spacings; never calculate them from a curve.

Semicolon-separated responses in an explicit d (angstrom) column, with a
source sample row, are a list, not a range. Ambiguous comma tokens stay pending.
"""
import copy,json,re
from schema.polymer_schema import PropertySeries
from stages.stage4_direct_table_supplement import table_requests,plain,header_applies,evidence,canonical_unit

VERSION='1.1.0'


def spacing_components(text):
    parts=plain(text).split(';')
    if not 2<=len(parts)<=32:return [],[]
    valid=[];pending=[]
    for index,part in enumerate(parts):
        raw=part.strip()
        if re.fullmatch(r'\+?(?:\d+(?:\.\d+)?|\.\d+)',raw) and float(raw)>0:
            valid.append((index+1,raw,float(raw)))
        else:pending.append({'component_index':index+1,'raw':raw,'reason':'ambiguous_nonliteral_spacing_token'})
    return valid,pending


def recover_diffraction_lists(stage4,stage0):
    output=copy.deepcopy(stage4);series=output.setdefault('property_series',[])
    records=[r for key in ['properties','unresolved_properties','specialized_property_observations'] for r in output.get(key,[])]
    records += [dict(p,unit_raw=p.get('unit_raw') or s.get('unit_raw'),unit_normalized=p.get('unit_normalized') or s.get('unit_normalized')) for s in series for p in s.get('points',[])]
    seen={(e.get('table_locator',{}).get('cell_id'),r.get('value_min'),canonical_unit(r.get('unit_normalized') or r.get('unit_raw')))
          for r in records for e in r.get('evidence',[]) if e.get('table_locator')}
    next_id=max([int(s['series_id'][6:]) for s in series] or [0])+1;decisions=[]
    for table in table_requests(stage0):
        cells=table['cells']
        for cell in cells:
            components,pending=spacing_components(cell['text'])
            if not components:continue
            headings=[h for h in cells if h['row_index']<cell['row_index'] and header_applies(h,cell)
                      and re.fullmatch(r'd\s*\(\s*Å\s*\)\s*\^?[a-z]?',plain(h['text']),re.I)]
            if len(headings)!=1:continue
            subject_headers=[h for h in cells if h['row_index']<cell['row_index']
                             and re.match(r'^(?:Polymer|Sample)\b',plain(h['text']),re.I)]
            labels=[s for s in cells if s['row_index']==cell['row_index'] and s['column_index']<cell['column_index']
                    and plain(s['text']) and any(header_applies(h,s) for h in subject_headers)]
            if len(labels)!=1:continue
            label=labels[0];header=headings[0]
            if sum(s['column_index']==label['column_index'] and plain(s['text'])==plain(label['text']) for s in cells)>1:continue
            ev=evidence(table,cell,row_label=label['text'],column_label=header['text'])
            header_ev=evidence(table,header,row_label='property header',column_label=header['text'])
            points=[]
            for index,raw,value in components:
                if (cell['cell_id'],value,canonical_unit('Å')) in seen:continue
                seen.add((cell['cell_id'],value,canonical_unit('Å')))
                context={'condition_status':'reported','other_conditions':{
                    'source_property_header':header['text'],'full_source_cell':cell['text'],
                    'source_list_component_index':str(index),'source_binding_method':'explicit_d_spacing_semicolon_list',
                    'source_list_equal_value_occurrences':str(sum(v==value for _,_,v in components)),
                    'source_list_unresolved_tokens':json.dumps(pending,ensure_ascii=False),
                    'confidence_status':'not_estimated; 0.0 is a schema placeholder',
                    'source_subject_binding_scope':'table-local sample label; canonical sample identity unresolved',
                    'source_footnote_status':'column marker preserved; instrument/state meaning not inferred'},
                    'other_condition_evidence':{'source_property_header':[header_ev]}}
                points.append({'point_id':f'pt{len(points)+1:03d}','sample_resolution_status':'unresolved',
                    'coordinates':[{'name_raw':'source sample label','value_raw':label['text'],
                                    'evidence':evidence(table,label,row_label=label['text'],column_label='sample')}],
                    'value_raw':raw,'value_min':value,'value_max':value,'unit_raw':'Å','unit_normalized':'Å',
                    'measurement_context':context,'coverage_status':'covered','evidence':[ev],'confidence':{'score':0.0}})
            if points:
                s={'series_id':f'series{next_id:03d}','sample_resolution_status':'unresolved',
                   'property_name_raw':header['text'],'property_name_normalized':'lattice spacing',
                   'unit_raw':'Å','unit_normalized':'Å','points':points,'evidence':[ev],
                   'measurement_context':{'condition_status':'reported','other_conditions':{
                       'source_property_header':header['text'],'source_caption':table.get('caption',''),
                       'source_list_unresolved_tokens':json.dumps(pending,ensure_ascii=False),
                       'source_list_literal_entries':str(len(components)),
                       'source_list_unresolved_entries':str(len(pending)),
                       'confidence_status':'not_estimated; 0.0 is a schema placeholder',
                       'coverage_scope':'parsed literal components only; unresolved tokens retained in extraction audit'}},
                   'coverage':{'expected':len(points),'covered':len(points),'missing':0,'not_applicable':0,'ratio':1.0},
                   'confidence':{'score':0.0}}
                series.append(PropertySeries.model_validate(s).model_dump(mode='json'));next_id+=1
            decisions.append({'cell_id':cell['cell_id'],'row_label':label['text'],'added':len(points),
                              'unresolved_components':pending,'full_source_cell':cell['text']})
    return output,{'version':VERSION,'new_points':sum(d['added'] for d in decisions),'decisions':decisions,'gold_access':False}
