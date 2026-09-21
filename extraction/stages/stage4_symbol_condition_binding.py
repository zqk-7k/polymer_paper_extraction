"""Bind explicit same-page loss-symbol definitions to actual temperature cells.

No new response values, no inferred T10=10%, no fabricated percent cells.
"""
from __future__ import annotations

import re

from stages.source_symbol_recovery import EXPLICIT
from stages.stage4_direct_table_supplement import plain, scalar, canonical_unit, header_applies, evidence

VERSION = '1.2.1'
KEY = 'weight_loss_threshold_percent'
LOSS_DEFINITION = re.compile(
    r'(?P<percent>\d+(?:\.\d+)?)\s*%\s+(?:gravimetric|weight|mass)\s+loss'
    r'(?:\s+temperatures?)?\s*\(\s*(?P<symbol>T(?:_?\s*(?:i|\d+)))\s*\)', re.I)


def symbol_in_header(text):
    # An alphabetic superscript is a footnote marker, not part of T0.
    text = re.sub(r'\^\s*(?:\{\s*[a-z]\s*\}|[a-z])(?![a-z])', '', text or '', flags=re.I)
    surface = re.sub(r'[\s_$^{}]', '', plain(text))
    match = re.fullmatch(r'(T(?:i|\d+))(?:\(?(?:°C|℃)\)?)?', surface, re.I)
    return match[1].lower() if match else None


def explicit_header_percent(text):
    surface = plain(text)
    matches = re.findall(r'(?<![\d.])(\d+(?:\.\d+)?)\s*(?:wt\s*)?%\s*(?:(?:weight|mass|wt)\s*)?loss\b', surface, re.I)
    matches += re.findall(r'\bTGA\s*[-–]?\s*(\d+(?:\.\d+)?)\s*%', surface, re.I)
    matches += re.findall(r'(?<![\d.])(\d+(?:\.\d+)?)\s*(?:wt\s*)?%\s*t\.g\.a\.', surface, re.I)
    values = {float(m) for m in matches}
    return next(iter(values)) if len(values) == 1 and 0 < next(iter(values)) <= 100 else None


def bind_symbol_conditions(stage4, stage0):
    """Mutate retained records in place; independently validate each source cell."""
    definitions = {}
    elements = {e['block_id']: e for e in stage0.get('elements', [])}
    for e in elements.values():
        if e.get('type') not in {'text', 'footnote'}:
            continue
        for m in LOSS_DEFINITION.finditer(plain(e.get('text') or '')):
            percent = float(m['percent'])
            if not 0 < percent <= 100:
                continue
            symbol = re.sub(r'[_\s]', '', m['symbol'].lower())
            if symbol != 't0' and symbol[1:].isdigit() and float(symbol[1:]) != percent:
                continue
            # Do not bind negated statements.
            prefix = plain(e.get('text') or '')[max(0, m.start()-35):m.start()]
            if re.search(r'\b(?:not|never|incorrect|erroneous)\b', prefix, re.I):
                continue
            definitions.setdefault((e.get('page'), symbol), []).append((percent, e, m[0]))
    cell_bindings = {}
    for table in elements.values():
        if table.get('type') != 'table':
            continue
        cells = table.get('table_cells') or []
        for cell in cells:
            value = scalar(cell.get('text'))
            if value is None:
                continue
            applicable = [h for h in cells if h['row_index'] < cell['row_index'] and header_applies(h, cell)]
            explicit = [(h, explicit_header_percent(h.get('text'))) for h in applicable
                        if explicit_header_percent(h.get('text')) is not None]
            # A percent subheader inherits its own spanning loss parent only.
            # Percent filler loading, residue, and adjacent thermal columns
            # cannot provide a decomposition criterion.
            for h in applicable:
                bare = re.fullmatch(r'(\d+(?:\.\d+)?)\s*%', plain(h.get('text')))
                parents = [p for p in applicable if p['row_index'] < h['row_index'] and header_applies(p,h)
                           and re.search(r'(?:weight|mass|wt)\s*loss', plain(p.get('text')), re.I)]
                if bare and parents and 0 < float(bare[1]) <= 100:
                    explicit.append((h, float(bare[1])))
            if (len(explicit) == 1 and any('°C' in plain(h.get('text')).replace(' ', '').replace('℃', '°C')
                                           for h in applicable)):
                header, percent = explicit[0]
                header_ev = [evidence({'table_id': table['block_id'], 'page': table['page'], 'bbox': table.get('bbox')},
                                     h, row_label='property header', column_label=h['text']) for h in applicable
                             if h == header or re.search(r'(?:weight|mass|wt)\s*loss|°C',plain(h.get('text')),re.I)]
                cell_bindings[cell['cell_id']] = (value, percent, table, table, header['text'], header_ev,
                                                  'explicit_own_table_header')
                continue
            headers = [h for h in applicable if symbol_in_header(h.get('text'))]
            if len(headers) != 1 or not any('°C' in plain(h.get('text')).replace(' ', '').replace('℃', '°C') for h in applicable):
                continue
            header = headers[0]
            defs = definitions.get((table.get('page'), symbol_in_header(header.get('text'))), [])
            if not defs or len({d[0] for d in defs}) != 1:
                continue
            percent, block, quote = defs[0]
            cell_bindings[cell['cell_id']] = (value, percent, table, block, quote, None,
                                              'explicit_same_page_symbol_definition')
    records = [(r, None) for key in ('properties', 'unresolved_properties', 'specialized_property_observations')
               for r in stage4.get(key, [])]
    records += [(p, series) for series in stage4.get('property_series', []) for p in series.get('points', [])]
    decisions = []
    for record, series in records:
        unit = canonical_unit(record.get('unit_normalized') or record.get('unit_raw')
                              or (series or {}).get('unit_normalized') or (series or {}).get('unit_raw'))
        if unit != '°C':
            continue
        value = record.get('value_min')
        if value is None:
            value = scalar(record.get('value_raw'))
        if value is None or record.get('value_max') not in (None, value):
            continue
        matches = []
        for ev in record.get('evidence') or []:
            loc = ev.get('table_locator') or {}
            binding = cell_bindings.get(loc.get('cell_id'))
            if (binding and ev.get('block_id') == binding[2]['block_id']
                    and loc.get('table_id') == binding[2]['block_id']
                    and abs(value-binding[0]) < 1e-9):
                matches.append((loc['cell_id'], binding))
        if len({b[1][1] for b in matches}) != 1 or len({b[0] for b in matches}) != 1:
            continue
        cell_id, (_, percent, table, block, quote, header_ev, method) = matches[0]
        context = record.setdefault('measurement_context', {})
        conditions = context.setdefault('other_conditions', {})
        before = conditions.get(KEY)
        if before is not None and str(before) != f'{percent:g}':
            decisions.append({'cell_id': cell_id, 'status': 'conflicting_retained_condition'})
            continue
        if before is not None:
            continue
        conditions[KEY] = f'{percent:g}'
        conditions['weight_loss_criterion_binding'] = method
        context['condition_status'] = 'reported'
        context.setdefault('other_condition_evidence', {})[KEY] = header_ev or [{
            'block_id': block['block_id'], 'page': block['page'], 'bbox': block.get('bbox'),
            'source_type': block['type'], 'source_sentence': quote, 'table_locator': None}]
        decisions.append({'status': 'bound', 'cell_id': cell_id, 'temperature_C': value,
                          'weight_loss_percent': percent, 'definition_block_id': block['block_id'],
                          'binding_method': method,
                          'record_id': record.get('property_id') or record.get('point_id'),
                          'series_id': (series or {}).get('series_id')})
    return {'version': VERSION, 'decisions': decisions,
            'unique_cells_bound': len({d['cell_id'] for d in decisions if d['status'] == 'bound'})}
