"""Resolve two printed Tm peaks only when source prose explains parentheses.

No paper IDs, gold values, or inferred global sample identities. A table cell
may legitimately contain two different reported responses; it is not a range.
"""
import re
from schema.polymer_schema import PropertySeries
from stages.stage4_direct_table_supplement import plain, evidence, header_applies
from stages.source_thermal_criteria import compact_math

VERSION = '1.0.0'
_NUMBER = r'[+−-]?(?:\d+(?:\.\d+)?|\.\d+)'
_PAIR = re.compile(rf'^\s*({_NUMBER})\s*,\s*\(\s*({_NUMBER})\s*\)\s*$')


def _definition(text):
    text = plain(text)
    if re.search(r'standard deviation|standard error|uncertainty|not\s+(?:the\s+)?(?:lower|peak)|標準偏差|誤差', text, re.I):
        return False
    return bool(re.search(r'lower[- ]temperature\s+peaks?[^.;]{0,90}(?:parenthes[ei]s|parenthetical|brackets)', text, re.I)
                or re.search(r'低温側のピーク\s*[（(]\s*値はカッコ内\s*[）)]', text))


def source_peak_cells(stage0):
    elements = stage0.get('elements', [])
    tables = [e for e in elements if e.get('type') == 'table']
    found = []
    for table in tables:
        caption = plain(table.get('caption', ''))
        if not re.search(r'melting (?:point|temperature)', caption, re.I):
            continue
        tag = re.search(r'\bTable\s+([IVXLC]+|\d+)\b', caption, re.I)
        notes = []
        for block in elements:
            if block.get('page') != table.get('page') or block.get('type') not in {'text', 'footnote'}:
                continue
            text = block.get('text', '')
            if not _definition(text) or not re.search(r'Tm|melting', compact_math(text), re.I):
                continue
            if sum(t.get('page') == table.get('page') for t in tables) > 1:
                if not tag or not re.search(r'\bTable\s+'+re.escape(tag[1])+r'\b', plain(text), re.I):
                    continue
            notes.append(block)
        if len(notes) != 1:
            continue
        cells = table.get('table_cells', [])
        for cell in cells:
            pair = _PAIR.fullmatch(plain(cell.get('text', '')))
            if not pair:
                continue
            values = [float(v.replace('−', '-')) for v in pair.groups()]
            if values[1] >= values[0]:
                continue
            headings = [h for h in cells if header_applies(h, cell)
                        and re.fullmatch(r'Tm/?[（(]?°C[）)]?', compact_math(h.get('text', '')), re.I)]
            if len(headings) != 1:
                continue
            row = cell['row_index']
            labels = [c for c in cells if c['column_index'] < cell['column_index']
                      and c['row_index'] <= row < c['row_index']+c.get('row_span', 1)
                      and c['column_index'] < 2 and plain(c.get('text', ''))]
            sample_headers = [h for h in cells if h['row_index'] < row
                              and re.fullmatch(r'Samples?', plain(h.get('text', '')), re.I)]
            if not labels or not all(any(h['column_index'] <= c['column_index'] < h['column_index']+h.get('column_span', 1)
                                         for h in sample_headers) for c in labels):
                continue
            label = ' | '.join(plain(c['text']) for c in sorted(labels, key=lambda c:c['column_index']))
            found.append({'table': table, 'cell': cell, 'header': headings[0], 'definition': notes[0],
                          'labels': labels, 'row_label': label, 'values': values, 'raw_components': pair.groups()})
    return found


def recover_compound_thermal_peaks(stage4, stage0):
    records = [(r, None) for key in ('properties', 'unresolved_properties', 'specialized_property_observations')
               for r in stage4.get(key, [])]
    series = stage4.setdefault('property_series', [])
    records += [(p, s) for s in series for p in s.get('points', [])]
    start = max([int(s['series_id'][6:]) for s in series] or [0])+1
    decisions = []
    for binding in source_peak_cells(stage0):
        table, cell, header, note = [binding[k] for k in ('table', 'cell', 'header', 'definition')]
        info = {'table_id': table['block_id'], 'page': table['page'], 'bbox': table.get('bbox')}
        label = binding['row_label']
        cell_ev = evidence(info, cell, row_label=label, column_label=header['text'])
        note_ev = {'block_id': note['block_id'], 'page': note['page'], 'bbox': note.get('bbox'),
                   'source_type': note['type'], 'source_sentence': note['text']}
        same = [(r,s) for r,s in records if any(e.get('block_id') == table['block_id']
                and (e.get('table_locator') or {}).get('cell_id') == cell['cell_id'] for e in r.get('evidence', []))]
        for index, value in enumerate(binding['values']):
            role = 'primary' if index == 0 else 'lower_temperature_parenthesized'
            conditions = {'source_peak_role':role, 'full_source_cell':cell['text'],
                          'source_property_header':header['text'], 'source_binding_method':'explicit_parenthesized_peak_definition',
                          'global_sample_binding':'unresolved for source-only rows; do not infer shorthand expansions'}
            context = {'condition_status':'reported', 'other_conditions':conditions,
                       'other_condition_evidence':{'source_peak_role':[note_ev]}}
            existing = [(r,s) for r,s in same if r.get('value_min') == value
                        and r.get('value_max') in (None, value)]
            if existing:
                continue
            compound = [(r,s) for r,s in same if index == 0 and r.get('value_min') is None
                        and plain(r.get('value_raw', '')) == plain(cell['text'])]
            if compound:
                for record,_ in compound:
                    record.update(value_min=value, value_max=value, unit_normalized='°C')
                    retained = record.setdefault('measurement_context', {})
                    retained.setdefault('other_conditions', {}).update(conditions)
                    retained.setdefault('other_condition_evidence', {})['source_peak_role'] = [note_ev]
                    retained['condition_status'] = 'reported'
                decisions.append({'cell_id':cell['cell_id'], 'value_C':value, 'role':role, 'action':'normalize_existing_primary_in_place'})
                continue
            point = {'point_id':'pt001', 'sample_resolution_status':'unresolved',
                     'coordinates':[{'name_raw':'source sample label', 'value_raw':label,
                        'evidence':evidence(info, binding['labels'][-1], row_label=label, column_label='Sample')},
                        {'name_raw':'source peak role', 'value_raw':role, 'evidence':note_ev}],
                     'value_raw':binding['raw_components'][index], 'value_min':value, 'value_max':value,
                     'unit_raw':'°C', 'unit_normalized':'°C', 'measurement_context':context,
                     'coverage_status':'covered', 'evidence':[cell_ev], 'confidence':{'score':0.0}}
            record = {'series_id':f'series{start:03d}', 'sample_resolution_status':'unresolved',
                      'property_name_raw':'melting temperature', 'property_name_normalized':'melting temperature',
                      'unit_raw':'°C', 'unit_normalized':'°C', 'measurement_context':context, 'points':[point],
                      'coverage':{'expected':1,'covered':1,'missing':0,'not_applicable':0,'ratio':1.0},
                      'evidence':[cell_ev], 'confidence':{'score':0.0}}
            record = PropertySeries.model_validate(record).model_dump(mode='json')
            series.append(record); records.append((record['points'][0], record)); start += 1
            decisions.append({'cell_id':cell['cell_id'], 'value_C':value, 'role':role, 'row_label':label,
                              'action':'add_source_peak', 'series_id':record['series_id']})
    return {'version':VERSION, 'decisions':decisions, 'new_points':sum(d['action']=='add_source_peak' for d in decisions)}
