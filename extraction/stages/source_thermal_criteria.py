"""Source-only table/prose links for explicit mass-loss temperature criteria.

Updates conditions on an existing, source-exact temperature. Never emits a
second temperature/percent response or invents onset=0%. No gold dependencies.
"""
import re
from stages.stage4_direct_table_supplement import plain, scalar, canonical_unit, header_applies, evidence

VERSION = '1.1.1'
KEY = 'weight_loss_threshold_percent'


def compact_math(text):
    text = re.sub(r'\\(?:mathrm|text|textrm)\b', '', plain(text))
    return re.sub(r'[\s_$^{}\\~]', '', text)


def explicit_loss_percentages(text):
    text = plain(text).replace('\\%', '%')
    values = set()
    # Includes shared percent notation: "5 and 50% weight loss".
    pattern = r'(?<![\d.])((?:\d+(?:\.\d+)?\s*(?:,\s*|and\s*))*\d+(?:\.\d+)?)\s*%\s*(?:weight|mass|gravimetric)\s+loss'
    for m in re.finditer(pattern, text, re.I):
        if re.search(r'\b(?:not|never|between|incorrect)\s*$', text[max(0,m.start()-30):m.start()], re.I):
            continue
        if re.match(r'\s+(?:was|is|were|are)\s+(?:not|never)\b', text[m.end():], re.I):
            continue
        values.update(float(x) for x in re.findall(r'\d+(?:\.\d+)?',m[1]))
    # A reverse definition, not an unlabeled temperature symbol.
    for m in re.finditer(r'(?:weight|mass)\s+loss\s+(?:is\s+)?(?:observed\s+)?at\s+(\d+(?:\.\d+)?)\s*%', text, re.I):
        values.add(float(m[1]))
    for m in re.finditer(r'(\d+(?:\.\d+)?)\s*%\s+loss\s+of\s+mass',text,re.I):
        values.add(float(m[1]))
    return {v for v in values if 0 < v <= 100}


def linked_criterion_bindings(stage0):
    blocks=stage0.get('elements',[])
    bindings={}
    for table in blocks:
        if table.get('type')!='table': continue
        caption=plain(table.get('caption',''))
        tag=re.search(r'\bTable\s+([IVXLC]+|\d+)\b',caption,re.I)
        if not tag: continue
        linked=[]
        for b in blocks:
            if b.get('type') not in {'text','footnote'} or b.get('page')!=table.get('page'): continue
            text=plain(b.get('text',''))
            if not re.search(r'\bTable\s+'+re.escape(tag[1])+r'\b',text,re.I):continue
            percentages=explicit_loss_percentages(text)
            if percentages and re.search(r'temperatur|TGA|thermal',text,re.I): linked.append((b,percentages))
        cells=table.get('table_cells',[])
        for cell in cells:
            value=scalar(cell.get('text'))
            if value is None:continue
            possibilities=[]
            for h in cells:
                if not header_applies(h,cell):continue
                # An independently transcribed footnote is an explicit table
                # relation even when it does not repeat the table number.
                # Require BOTH ownership and the literal header superscript.
                original = str(h.get('text') or '')
                markers = set(re.findall(r'\^\s*\{?\s*([a-z])\s*\}?|<sup>\s*([a-z])\s*</sup>', original))
                markers = {a or b for a, b in markers}
                if re.search(r'decomp|temperature|\btemp\b|T_d|T_\{d\}', plain(original), re.I):
                    for note in blocks:
                        if (note.get('type') != 'footnote'
                                or (note.get('content') or {}).get('owning_table_block_id') != table['block_id']):
                            continue
                        note_text = plain(note.get('text', ''))
                        marker = re.match(r'^\s*([a-z])(?:[.)]|\s)', note_text)
                        ps = explicit_loss_percentages(note_text)
                        if (marker and marker[1] in markers and len(ps) == 1
                                and re.search(r'temperatur', note_text, re.I)
                                and not re.search(r'\b(?:not|never|incorrect)\b', note_text, re.I)):
                            possibilities.append((next(iter(ps)), h, note, 'owned_header_footnote_loss_definition'))
                text=compact_math(h.get('text'))
                symbol=re.match(r'^T(?:d)?(\d+(?:\.\d+)?)%',text,re.I)
                bare=re.fullmatch(r'(\d+(?:\.\d+)?)%',text)
                td=re.fullmatch(r'Td\(?°?C\)?[a-z]?',text,re.I)
                if symbol:
                    percent=float(symbol[1])
                    for b,ps in linked:
                        if percent in ps:possibilities.append((percent,h,b,'percent_symbol_and_linked_definition'))
                elif bare and re.search(r'\bTGA\b',caption,re.I):
                    percent=float(bare[1])
                    for b,ps in linked:
                        if percent in ps:possibilities.append((percent,h,b,'TGA_percent_header_and_linked_definition'))
                elif td:
                    for b,ps in linked:
                        text_b=plain(b.get('text',''))
                        if len(ps)!=1 or not re.search(r'decomposition\s+temperatures?',text_b,re.I):continue
                        # Link the retained temperature literally, not merely
                        # all columns in a table discussing thermal behavior.
                        numbers=re.sub(r'(?<=[\d.])\s+(?=[\d.])','',text_b)
                        if re.search(r'(?<![\d.])'+re.escape(f'{value:g}')+r'(?![\d.])',numbers):
                            possibilities.append((next(iter(ps)),h,b,'Td_exact_temperature_in_linked_definition'))
            if len({p[0] for p in possibilities})==1:
                percent,header,block,method=possibilities[0]
                bindings[cell['cell_id']]={'value':value,'percent':percent,'table':table,'header':header,
                                          'block':block,'method':method}
    return bindings


def bind_linked_thermal_criteria(stage4,stage0):
    bindings=linked_criterion_bindings(stage0);decisions=[]
    records=[(r,None) for key in ('properties','unresolved_properties','specialized_property_observations') for r in stage4.get(key,[])]
    records += [(p,s) for s in stage4.get('property_series',[]) for p in s.get('points',[])]
    for record,series in records:
        unit=canonical_unit(record.get('unit_normalized') or record.get('unit_raw') or (series or {}).get('unit_normalized') or (series or {}).get('unit_raw'))
        if unit!='°C':continue
        value=record.get('value_min')
        if value is None:value=scalar(record.get('value_raw'))
        if value is None or record.get('value_max') not in (None,value):continue
        for ev in record.get('evidence') or []:
            loc=ev.get('table_locator') or {};binding=bindings.get(loc.get('cell_id'))
            if not binding or ev.get('block_id')!=binding['table']['block_id'] or value!=binding['value']:continue
            context=record.setdefault('measurement_context',{})
            conditions=context.setdefault('other_conditions',{})
            if KEY in conditions:break  # preserve previously retained assertions
            block=binding['block'];table=binding['table'];header=binding['header']
            conditions[KEY]=f"{binding['percent']:g}"
            conditions['weight_loss_criterion_binding']=binding['method']
            context['condition_status']='reported'
            context.setdefault('other_condition_evidence',{})[KEY]=[
                {'block_id':block['block_id'],'page':block['page'],'bbox':block.get('bbox'),
                 'source_type':block['type'],'source_sentence':block['text'],'table_locator':None},
                evidence({'table_id':table['block_id'],'page':table['page'],'bbox':table.get('bbox')},header,
                         row_label='property header',column_label=header['text'])]
            decisions.append({'cell_id':loc['cell_id'],'temperature_C':value,'weight_loss_percent':binding['percent'],
                              'definition_block_id':block['block_id'],'binding_method':binding['method'],
                              'record_id':record.get('property_id') or record.get('point_id'),
                              'series_id':(series or {}).get('series_id')})
            break
    prose_decisions = bind_literal_prose_criteria(stage4, stage0)
    return {'version':VERSION,'decisions':decisions,'unique_cells_bound':len({x['cell_id'] for x in decisions}),
            'prose_decisions':prose_decisions}


def literal_prose_pairs(text):
    """Only literal loss-at-temperature statements, not TGA curve readings."""
    text=plain(text).replace('\\mathrm','').replace('\\text','').replace('\\,',' ')
    text=re.sub(r'(?<=[\d.])\s+(?=[\d.])','',text).replace('^°','°')
    pairs=[]
    # Do not bridge another temperature/percent, a range or sentence boundary.
    pattern=r'(\d+(?:\.\d+)?)\s*%\s*(?:weight|mass)\s+loss\s+(?:was\s+observed\s+)?at\s*[~ ]*(\d+(?:\.\d+)?)\s*[~ ]*°\s*C\b'
    for m in re.finditer(pattern,text,re.I):
        prefix=text[max(0,m.start()-35):m.start()]
        if re.search(r'\b(?:not|no|never|between|from)\s*$',prefix,re.I):continue
        percent,temperature=map(float,m.groups())
        if 0<percent<=100:pairs.append((temperature,percent))
    return pairs


def bind_literal_prose_criteria(stage4,stage0):
    sources={b['block_id']:(b,literal_prose_pairs(b.get('text',''))) for b in stage0.get('elements',[])
             if b.get('type')=='text' and not re.search(r'references|bibliography',str(b.get('section') or ''),re.I)}
    records=[(r,None) for key in ('properties','unresolved_properties','specialized_property_observations') for r in stage4.get(key,[])]
    records += [(p,s) for s in stage4.get('property_series',[]) for p in s.get('points',[])]
    decisions=[]
    for record,parent in records:
        name=str((parent or record).get('property_name_normalized') or (parent or record).get('property_name_raw') or '').replace('_',' ')
        if not re.search(r'decomp|weight.?loss|mass.?loss|thermal.?stability',name,re.I):continue
        unit=canonical_unit(record.get('unit_normalized') or record.get('unit_raw') or (parent or {}).get('unit_normalized') or (parent or {}).get('unit_raw'))
        value=record.get('value_min')
        if unit!='°C' or value is None or record.get('value_max') not in (None,value):continue
        supported=[]
        for ev in record.get('evidence') or []:
            block,pairs=sources.get(ev.get('block_id'),({},[]))
            # Block co-occurrence alone is not enough: the retained evidence
            # quote must contain this exact numerical relation too.
            quoted_pairs=literal_prose_pairs(ev.get('source_sentence',''))
            for temperature,percent in pairs:
                if temperature==value and (temperature,percent) in quoted_pairs:supported.append((percent,block))
        if len({p for p,b in supported})!=1:continue
        context=record.setdefault('measurement_context',{});conditions=context.setdefault('other_conditions',{})
        if KEY in conditions:continue
        percent,block=supported[0]
        conditions[KEY]=f'{percent:g}';conditions['weight_loss_criterion_binding']='literal_loss_at_temperature_same_source_block'
        context['condition_status']='reported'
        context.setdefault('other_condition_evidence',{})[KEY]=[{'block_id':block['block_id'],'page':block['page'],
            'bbox':block.get('bbox'),'source_type':block['type'],'source_sentence':block['text']}]
        decisions.append({'record_id':record.get('property_id') or record.get('point_id'),
            'series_id':(parent or {}).get('series_id'),'definition_block_id':block['block_id'],
            'temperature_C':value,'weight_loss_percent':percent})
    return decisions
