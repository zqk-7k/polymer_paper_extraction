"""Normalize explicit prose loss/temperature relations into criterion records.

A criterion is not an extra material temperature.
Only existing source-labelled temperature records can supply sample identity.
"""
import copy
import hashlib
import json
import re
from schema.polymer_schema import PropertySeries
from stages.stage4_direct_table_supplement import plain,canonical_unit

VERSION='1.0.0'


def norm(text):
    t=plain(text)
    t=re.sub(r'\\(?:mathrm|text|textrm|mathbf|mathit)\b','',t)
    t=t.replace('\\,',' ').replace('\\ ',' ').replace('~',' ').replace('^ °','°').replace('^°','°')
    t=re.sub(r'(?<=[\d.])\s+(?=[\d.])','',t)
    return re.sub(r'\s+',' ',t).strip()


def literal_pairs(text):
    t=norm(text);pairs=[]
    # Full positive assertion, with a directly adjacent physical temperature.
    pat=r'(?<![\d.])(\d+(?:\.\d+)?)\s*%\s*(?:weight|mass)\s+loss\s+at\s+(\d+(?:\.\d+)?)\s*°\s*C\b'
    for m in re.finditer(pat,t,re.I):
        if re.search(r'\b(?:not|never|no|from|between)\s*$',t[max(0,m.start()-35):m.start()],re.I):continue
        percent=float(m[1]);temp=float(m[2])
        if not 0<percent<=100:continue
        pairs.append((temp,percent))
        # Shared predicate: "... at X°C in nitrogen (Fig. N) and at Y°C
        # in air". Do not cross a sentence or another percentage/quantity.
        tail=t[m.end():]
        shared=re.match(r'[^%\d.;]{0,45}(?:\(Fig\.?\s*\d+\))?\s*and\s+at\s+(\d+(?:\.\d+)?)\s*°\s*C\b',tail,re.I)
        if shared:pairs.append((float(shared[1]),percent))
    return pairs


def explicit_symbol_definitions(text):
    # Symbol meaning must be printed, never assume bare Td50 means 50%.
    t=norm(text);result={}
    pat=r'temperature\s+of\s+(\d+(?:\.\d+)?)\s*%\s*(?:weight|mass)\s+loss\s*\(\s*(T\s*_?d\s*\^\s*\d+(?:\.\d+)?)\s*\)'
    for m in re.finditer(pat,t,re.I):
        if 0<float(m[1])<=100:result[re.sub(r'\s+','',m[2])]=float(m[1])
    return result


def criterion_for_temperature(quote,value,definitions):
    t=norm(quote);found={p for temp,p in literal_pairs(t) if temp==value}
    for symbol,percent in definitions.items():
        compact=re.sub(r'\s+','',t)
        if re.sub(r'\s+','',symbol) not in compact:continue
        # A printed temperature list bound to this symbol. The list may use a
        # shared terminal °C. Reject other percent predicates in that quote.
        percents={float(m) for m in re.findall(r'(\d+(?:\.\d+)?)\s*%',t)}
        if percents-{percent}:continue
        if not re.search(r'occurr(?:ing|ed)\s+at',t,re.I):continue
        if re.search(r'\b(?:not|never)\s+(?:observed|occurr(?:ed|ing))',t,re.I):continue
        # The number must be an asserted temperature, not a heating setting,
        # a negated alternative, a figure index or a material label.
        literal=rf'(?:\bat\b|\band\b|,)\s*{re.escape(f"{value:g}")}\s*°\s*C\b'
        if re.search(literal,t,re.I):found.add(percent)
    return next(iter(found)) if len(found)==1 else None


def recover_prose_loss_facts(stage4,stage0):
    out=copy.deepcopy(stage4);all_series=out.setdefault('property_series',[])
    elements={b['block_id']:b for b in stage0.get('elements',[]) if b.get('type')=='text'}
    definitions={};definition_blocks={}
    for bid,b in elements.items():
        for symbol,percent in explicit_symbol_definitions(b.get('text','')).items():
            if symbol in definitions and definitions[symbol]!=percent:definitions[symbol]=None
            else:definitions[symbol]=percent;definition_blocks[symbol]=b
    definitions={s:p for s,p in definitions.items() if p is not None}
    seen={(s.get('measurement_context') or {}).get('other_conditions',{}).get('source_loss_relation_id') for s in all_series}
    index=max([int(s['series_id'][6:]) for s in all_series] or [0])+1;decisions=[]
    for series in list(all_series):
        name=(series.get('property_name_normalized') or series.get('property_name_raw') or '').replace('_',' ')
        if not re.search(r'loss|decomp',name,re.I):continue
        for point in series.get('points',[]):
            unit=canonical_unit(point.get('unit_normalized') or series.get('unit_normalized'))
            value=point.get('value_min')
            if unit!='°C' or value is None or point.get('value_max') not in (None,value):continue
            labels=[c for c in point.get('coordinates',[]) if c.get('name_raw')=='source sample label' and c.get('value_raw')]
            if len(labels)!=1:continue
            for ev in point.get('evidence',[]):
                block=elements.get(ev.get('block_id'));quote=ev.get('source_sentence') or ''
                if not block or not quote or norm(quote) not in norm(block.get('text','')):continue
                percent=criterion_for_temperature(quote,value,definitions)
                if percent is None:continue
                identity=hashlib.sha256(json.dumps([block['block_id'],labels[0]['value_raw'],value,percent],ensure_ascii=False).encode()).hexdigest()[:24]
                if identity in seen:continue
                seen.add(identity)
                ctx={'condition_status':'reported','other_conditions':{'fact_role':'measurement_criterion',
                    'source_loss_relation_id':identity,'source_parent_temperature_C':f'{value:g}',
                    'source_parent_series_id':series['series_id'],'source_parent_point_id':point['point_id'],
                    'source_binding_method':'direct printed prose loss-at-temperature relation; not a new temperature',
                    'confidence_status':'not_estimated; 0.0 is a required schema placeholder'}}
                proofs=[copy.deepcopy(ev)]
                for symbol,pct in definitions.items():
                    if pct==percent and re.sub(r'\s+','',symbol) in re.sub(r'\s+','',norm(quote)):
                        b=definition_blocks[symbol]
                        if b['block_id']!=block['block_id']:proofs.append({'block_id':b['block_id'],'page':b['page'],
                            'bbox':b.get('bbox'),'source_type':'text','source_sentence':b['text']})
                coordinates=copy.deepcopy(labels)+[{'name_raw':'associated decomposition temperature','value_raw':f'{value:g}',
                    'unit_raw':'°C','evidence':copy.deepcopy(ev)}]
                p={'point_id':'pt001','sample_resolution_status':'unresolved','coordinates':coordinates,
                    'value_raw':f'{percent:g}','value_min':percent,'value_max':percent,'unit_raw':'%','unit_normalized':'%',
                    'measurement_context':ctx,'coverage_status':'covered','evidence':proofs,'confidence':{'score':0.0}}
                item={'series_id':f'series{index:03d}','sample_resolution_status':'unresolved',
                    'property_name_raw':'thermal decomposition weight loss','property_name_normalized':'thermal decomposition weight loss',
                    'unit_raw':'%','unit_normalized':'%','measurement_context':ctx,'points':[p],
                    'coverage':{'expected':1,'covered':1,'missing':0,'not_applicable':0,'ratio':1.0},
                    'evidence':proofs,'confidence':{'score':0.0}}
                all_series.append(PropertySeries.model_validate(item).model_dump(mode='json'));index+=1
                decisions.append({'block_id':block['block_id'],'sample_label':labels[0]['value_raw'],
                    'temperature_C':value,'criterion_percent':percent,'relation_id':identity})
    return out,{'version':VERSION,'decisions':decisions,'new_criterion_relations':len(decisions),'gold_access':False}
