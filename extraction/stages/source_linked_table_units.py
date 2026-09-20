"""Resolve omitted table units from an explicit, linked source assignment.

No assumed conventional units, physical calculations, reference answers or
paper IDs. Currently supports d-spacing: a captioned diffraction table, a
linked prose reference to that table and d = <its printed cell value> Å.
The Stage0 page is a block locator; recovered paragraphs may span PDF pages.
Other columns and explicitly unit-bearing records are left untouched.
"""
import re
from stages.stage4_direct_table_supplement import plain, scalar, header_applies

VERSION = '1.0.0'


def table_unit_witnesses(stage0):
    elements = stage0.get('elements', [])
    result = {}
    for table in elements:
        if table.get('type') != 'table':
            continue
        caption = plain(table.get('caption', ''))
        tag = re.search(r'\bTable\s+([IVXLC]+|\d+)\b', caption, re.I)
        if not tag or not re.search(r'WAXD|diffraction|d[ -]spacing', caption, re.I):
            continue
        cells = table.get('table_cells') or []
        headers = [c for c in cells if plain(c.get('text')) == 'd']
        d_cells = [c for c in cells if scalar(c.get('text', '')) is not None
                   and any(header_applies(h, c) for h in headers)]
        if not d_cells:
            continue
        values = {scalar(c.get('text', '')) for c in d_cells}
        witnesses = []
        for block in elements:
            if block.get('type') != 'text' or block.get('page') != table.get('page'):
                continue
            text = plain(block.get('text', ''))
            if not re.search(r'\bTable\s+' + re.escape(tag[1]) + r'\b', text, re.I):
                continue
            # Preserve the original paragraph as evidence. Strip only TeX
            # number spacing when recognizing the explicit symbol assignment.
            normalized = re.sub(r'(?<=[\d.])\s+(?=[\d.])', '', text)
            assignments = list(re.finditer(r'(?<!\w)d\s*=\s*(\d+(?:\.\d+)?)\s*~?\s*(Å|nm|pm|angstrom)\b', normalized, re.I))
            if any(m[2].casefold() not in {'å', 'angstrom'} for m in assignments):
                witnesses = []; break  # conflicting unit definitions: abstain
            for match in assignments:
                if float(match[1]) in values:
                    witnesses.append({'block_id': block['block_id'], 'stage0_page': block['page'],
                                      'page_scope': 'Stage0 block locator; merged paragraph may span PDF pages',
                                      'quote': block['text'], 'literal_assignment': match[0],
                                      'reference_value': float(match[1])})
        if witnesses:
            result[table['block_id']] = {'cells': {c['cell_id']: c for c in d_cells},
                                         'witnesses': witnesses}
    return result


def resolve_linked_table_units(stage4, stage0):
    sources, changes = table_unit_witnesses(stage0), []
    records = [(r, None) for key in ('properties', 'unresolved_properties', 'specialized_property_observations')
               for r in stage4.get(key, [])]
    records += [(p, s) for s in stage4.get('property_series', []) for p in s.get('points', [])]
    for record, parent in records:
        if any(record.get(k) or (parent or {}).get(k) for k in ('unit_raw', 'unit_normalized')):
            continue
        for ev in record.get('evidence') or []:
            proof = sources.get(ev.get('block_id'))
            locator = ev.get('table_locator') or {}
            cell = (proof or {}).get('cells', {}).get(locator.get('cell_id'))
            if not cell:
                continue
            value = scalar(cell['text'])
            raw = scalar(str(record.get('value_raw') or ''))
            if raw != value or record.get('value_min') not in (None, value) or record.get('value_max') not in (None, value):
                continue
            record['unit_normalized'] = 'angstrom'
            record.setdefault('measurement_context', {}).setdefault('other_conditions', {}).update({
                'unit_resolution_basis': 'linked_table_prose_and_explicit_d_assignment',
                'unit_source_block_id': proof['witnesses'][0]['block_id'],
                'unit_source_quote': proof['witnesses'][0]['quote'],
                'unit_source_assignment': proof['witnesses'][0]['literal_assignment'],
                'unit_resolution_value_rescaled': 'false',
                'unit_not_printed_in_table_header': 'true'})
            changes.append({'record_id': record.get('property_id') or record.get('point_id'),
                            'series_id': (parent or {}).get('series_id'),
                            'cell_id': cell['cell_id'], 'value_raw': record['value_raw'],
                            'unit_after': 'angstrom', 'source_witnesses': proof['witnesses']})
            break
    for series in stage4.get('property_series', []):
        units = {p.get('unit_normalized') or p.get('unit_raw') for p in series.get('points', [])}
        if units == {'angstrom'} and not series.get('unit_raw'):
            series['unit_normalized'] = 'angstrom'
    return {'version': VERSION, 'changes': changes}
