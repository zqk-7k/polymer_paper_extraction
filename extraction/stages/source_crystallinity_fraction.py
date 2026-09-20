"""Standardize already reported crystallinity fractions; never calculate Xc.

The source must explicitly define the component's Xc as its melting enthalpy
divided by the enthalpy of the 100%-crystalline reference. Only experimental
table cells of that same symbol are eligible. Raw values/evidence stay intact.
"""
from __future__ import annotations

import re
from stages.stage4_direct_table_supplement import plain, scalar, header_applies

VERSION = '1.0.0'


def compact(text):
    text = re.sub(r'\\tag\s*\{[^}]*\}', '', str(text or ''))
    text = re.sub(r'\\(?:mathrm|mathbf|text|bf|thinspace)\b\s*', '', text)
    text = text.replace('\\circ', '°')
    return re.sub(r'[\s${}]', '', text).casefold()


def fraction_definitions(stage0):
    definitions = {}
    elements = stage0.get('elements', [])
    for i, equation in enumerate(elements):
        if equation.get('type') != 'equation':
            continue
        match = re.fullmatch(r'x_c,(?P<component>[a-z][a-z0-9]*)=\\deltah_blend,(?P=component)\^\*/\\deltah_(?P=component)\^°',
                             compact(equation.get('text')))
        if not match:
            continue
        component = match['component']
        notes = [e for e in elements[i+1:i+6] if e.get('type') == 'text'
                 and e.get('page') == equation.get('page')
                 and re.search(r'heat of melting per gram of 100\s*% crystalline', plain(e.get('text')), re.I)
                 and re.search(r'\b' + re.escape(component) + r'\b', plain(e.get('text')), re.I)]
        if len(notes) == 1:
            definitions.setdefault(component, []).append((equation, notes[0]))
    return {component: items[0] for component, items in definitions.items() if len(items) == 1}


def normalize_crystallinity_fractions(stage4, stage0):
    definitions = fraction_definitions(stage0)
    bindings = {}
    for table in stage0.get('elements', []):
        if (table.get('type') != 'table' or not re.search('crystallinit', table.get('caption') or '', re.I)
                or re.search('normalized', table.get('caption') or '', re.I)):
            continue
        cells = table.get('table_cells') or []
        for header in cells:
            match = re.fullmatch(r'x_c,([a-z][a-z0-9]*)\((?:exp|experimental)\)', compact(header.get('text')))
            if not match or match[1] not in definitions:
                continue
            equation, note = definitions[match[1]]
            # Bounded neighboring-page definition, not a remote reused symbol.
            if not 0 <= table.get('page', -1) - equation.get('page', -1) <= 1:
                continue
            body = [(c, scalar(c.get('text'))) for c in cells if header_applies(header, c)]
            numeric = [(c, v) for c, v in body if v is not None]
            if not numeric or any(not 0 <= v <= 1 for _, v in numeric):
                continue
            for cell, value in numeric:
                bindings[cell['cell_id']] = (value, table, equation, note, match[1])
    rows = [(r, None) for key in ('properties', 'unresolved_properties', 'specialized_property_observations')
            for r in stage4.get(key, [])]
    rows += [(point, series) for series in stage4.get('property_series', []) for point in series.get('points', [])]
    audit = []
    for record, series in rows:
        current_unit = record.get('unit_normalized') or record.get('unit_raw') or (series or {}).get('unit_raw')
        if current_unit not in (None, '', 'fraction', '1'):
            continue
        name = ' '.join(str(r.get(k) or '') for r in [record, series or {}]
                        for k in ('property_name_raw', 'property_name_normalized'))
        if re.search('normalized|ratio|calculated|theoretical', name, re.I):
            continue
        raw = scalar(record.get('value_raw'))
        if raw is None or record.get('value_min') not in (None, raw) or record.get('value_max') not in (None, raw):
            continue
        matches = []
        for ev in record.get('evidence') or []:
            loc = ev.get('table_locator') or {}
            b = bindings.get(loc.get('cell_id'))
            if b and raw == b[0] and ev.get('block_id') == b[1]['block_id'] and loc.get('table_id') == b[1]['block_id']:
                matches.append((loc['cell_id'], b))
        if len({cell for cell, _ in matches}) != 1:
            continue
        cell, (_, table, equation, note, component) = matches[0]
        record['value_min'] = record['value_max'] = round(raw * 100, 12)
        record['unit_normalized'] = '%'
        context = record.setdefault('measurement_context', {})
        context['condition_status'] = 'reported'
        context.setdefault('other_conditions', {})['quantity_normalization'] = (
            'reported crystallinity fraction to percent (x100); not recomputed from enthalpy')
        context['other_conditions']['fraction_basis'] = 'explicit source enthalpy ratio to 100%-crystalline reference'
        context.setdefault('other_condition_evidence', {})['quantity_normalization'] = [
            {'block_id': e['block_id'], 'page': e['page'], 'bbox': e.get('bbox'), 'source_type': e['type'],
             'source_sentence': e['text'], 'table_locator': None} for e in (equation, note)]
        audit.append({'cell_id': cell, 'source_value': raw, 'normalized_value': record['value_min'],
                      'component': component, 'unit_normalized': '%', 'definition_block_id': equation['block_id'],
                      'record_id': record.get('property_id') or record.get('point_id'),
                      'series_id': (series or {}).get('series_id')})
    for series in stage4.get('property_series', []):
        if series.get('points') and all(p.get('unit_normalized') == '%' for p in series['points']):
            series['unit_normalized'] = '%'
    return {'version': VERSION, 'changes': audit, 'unique_cells': len({r['cell_id'] for r in audit})}
