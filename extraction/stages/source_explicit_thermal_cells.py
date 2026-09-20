"""Source-only literal assignments and explicitly described DTG double peaks.

Production source-only parser. No reference/prediction evaluator.
"""
import copy
import re
from schema.polymer_schema import PropertySeries
from stages.stage4_direct_table_supplement import plain, evidence, header_applies, unit_in_header

VERSION='1.0.0'
NUMBER=r'[+−-]?(?:\d+(?:\.\d+)?|\.\d+)'


def thermal_cell_components(cell_text,header_text,notes):
    """No arithmetic, endpoint splitting, onset-to-zero or new graph values."""
    clean=plain(cell_text).replace('−','-')
    header=plain(header_text)
    if not unit_in_header('°C',header_text,notes):return []
    # A labelled Tm inside a Tg column overrides the column's property label.
    match=re.fullmatch(rf'T_?m\s*=\s*({NUMBER})(?:\s*\^([a-z]))?',clean,re.I)
    if match and re.search(r'T_?[mgco](?![A-Za-z])|temperature|transition',header,re.I):
        return [{'raw':match[1],'value':float(match[1]),'name':'melting temperature',
                 'role':'explicit_Tm_assignment','marker':match[2] or '',
                 'basis':'literal_Tm_in_thermal_cell; unit inherited from its actual column'}]
    # Slash is not generally a pair: require a DTG maximum column and an
    # explicit same-page statement that there are two DTG maxima.
    if not re.search(r'max\s*DTG|DTG\s*max',header,re.I):return []
    definition=re.search(r'(?:two|double|dual)\s+(?:maxima|peaks)\s+(?:on|in)\s+(?:the\s+)?DTG\s+curves?',plain(notes),re.I)
    if not definition:return []
    m=re.fullmatch(rf'\s*({NUMBER})\s*/\s*({NUMBER})\s*',clean)
    if not m or float(m[1])==float(m[2]):return []
    return [{'raw':v,'value':float(v),'name':'temperature of maximum mass loss rate',
             'role':f'explicit_DTG_maximum_{i+1}','marker':'',
             'basis':'same-page prose explicitly describes two DTG maxima; complete slash-separated cell'}
            for i,v in enumerate(m.groups())]


def recover_explicit_thermal_cells(stage4,stage0):
    out=copy.deepcopy(stage4);series=out.setdefault('property_series',[])
    records=[(r,r) for k in ('properties','unresolved_properties','specialized_property_observations') for r in out.get(k,[])]
    records += [(p,s) for s in series for p in s.get('points',[])]
    index=max([int(s['series_id'][6:]) for s in series] or [0])+1
    decisions=[]
    for table in stage0.get('elements',[]):
        if table.get('type')!='table':continue
        notes=[b for b in stage0['elements'] if b.get('type') in {'text','footnote'} and b.get('page')==table.get('page')]
        note_text='\n'.join([table.get('caption') or '',*[b.get('text','') for b in notes]])
        cells=table.get('table_cells') or []
        for cell in cells:
            headers=[h for h in cells if header_applies(h,cell)]
            header_text=' | '.join(h.get('text','') for h in headers)
            components=thermal_cell_components(cell.get('text',''),header_text,note_text)
            if not components:continue
            # Exact source row identity, including spanning source cells. No
            # global sample identity or shorthand expansion is invented.
            labels=[c for c in cells if c['column_index']==0 and c['row_index']<=cell['row_index']<c['row_index']+c.get('row_span',1)
                    and c.get('column_span',1)==1 and plain(c.get('text',''))]
            if len(labels)!=1 or labels[0]['row_index']==0:continue
            label=labels[0]['text'];info={'table_id':table['block_id'],'page':table['page'],'bbox':table.get('bbox')}
            ev=evidence(info,cell,row_label=label,column_label=header_text)
            existing=[(p,s) for p,s in records if any(e.get('block_id')==table['block_id'] and
                (e.get('table_locator') or {}).get('cell_id')==cell['cell_id'] for e in p.get('evidence',[]))]
            for component in components:
                value=component['value']
                if any(p.get('value_min')==value and p.get('value_max') in (None,value)
                       and (p.get('unit_normalized') or p.get('unit_raw') or s.get('unit_normalized')) in ('°C','C')
                       for p,s in existing):continue
                ctx={'condition_status':'reported','other_conditions':{
                    'source_full_cell':cell['text'],'source_response_role':component['role'],
                    'source_binding_method':component['basis'],'source_footnote_marker':component['marker'],
                    'source_footnote_status':'literal marker retained; meaning not inferred',
                    'global_sample_binding':'unresolved; literal table row label retained',
                    'confidence_status':'not_estimated; 0.0 is a required schema placeholder'}}
                if len(components)>1:
                    relevant=[b for b in notes if re.search(r'(?:two|double|dual)\s+(?:maxima|peaks)\s+(?:on|in)\s+(?:the\s+)?DTG\s+curves?',plain(b.get('text','')),re.I)]
                    ctx['other_condition_evidence']={'source_response_role':[{'block_id':b['block_id'],'page':b['page'],
                        'bbox':b.get('bbox'),'source_type':b['type'],'source_sentence':b['text']} for b in relevant]}
                point={'point_id':'pt001','sample_resolution_status':'unresolved',
                    'coordinates':[{'name_raw':'source sample label','value_raw':label,
                        'evidence':evidence(info,labels[0],row_label=label,column_label='source row')},
                        {'name_raw':'source response role','value_raw':component['role'],'evidence':ev}],
                    'value_raw':component['raw'],'value_min':value,'value_max':value,'unit_raw':'°C','unit_normalized':'°C',
                    'measurement_context':ctx,'coverage_status':'covered','evidence':[ev],'confidence':{'score':0.0}}
                item={'series_id':f'series{index:03d}','sample_resolution_status':'unresolved',
                    'property_name_raw':component['name'],'property_name_normalized':component['name'],
                    'unit_raw':'°C','unit_normalized':'°C','measurement_context':ctx,'points':[point],
                    'coverage':{'expected':1,'covered':1,'missing':0,'not_applicable':0,'ratio':1.0},
                    'evidence':[ev],'confidence':{'score':0.0}}
                item=PropertySeries.model_validate(item).model_dump(mode='json');series.append(item);index+=1
                records.append((item['points'][0],item))
                decisions.append({'cell_id':cell['cell_id'],'value_C':value,'role':component['role'],
                    'series_id':item['series_id'],'source_full_cell':cell['text']})
    return out,{'version':VERSION,'decisions':decisions,'new_points':len(decisions),'gold_access':False}
