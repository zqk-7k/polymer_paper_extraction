"""Repair retained source-exact units whose font commands leaked into units."""
import re
from stages.stage4_direct_table_supplement import canonical_unit

VERSION = '1.0.0'
FONT = re.compile(r'mathrm|mathbf|textrm|mathsf|mathtt|mathit|text')
KNOWN = {'°C', '°F', 'K', 'J/g', 'kJ/g', 'J/mol', 'kJ/mol', 'kJmol-1', 'Jmol-1',
         'cm-1', 'μs', 's', 'g/cm3', 'g/mol', 'g·mol-1', 'dL/g', 'mL/g',
         'angstrom', 'cm2/(Vs)', 'MPa', 'GPa', '%'}


def repair_source_unit_fonts(stage4, stage0):
    blocks = {e['block_id']: e for e in stage0.get('elements', [])}
    rows = [(r, None) for key in ('properties', 'unresolved_properties', 'specialized_property_observations')
            for r in stage4.get(key, [])]
    rows += [(point, series) for series in stage4.get('property_series', []) for point in series.get('points', [])]
    audit = []
    for record, series in rows:
        raw = record.get('unit_raw') or (series or {}).get('unit_raw')
        current = record.get('unit_normalized') or ''
        if not raw or not FONT.search(current):
            continue
        corrected = canonical_unit(raw)
        if corrected not in KNOWN or corrected == current:
            continue
        witnesses = []
        for ev in record.get('evidence') or []:
            block = blocks.get(ev.get('block_id'))
            if not block:
                continue
            source = (block.get('text') or block.get('table_body') or '')
            if re.sub(r'\s+', '', raw) in re.sub(r'\s+', '', source):
                witnesses.append(block['block_id'])
        if not witnesses:
            continue
        record['unit_normalized'] = corrected
        context = record.setdefault('measurement_context', {})
        context.setdefault('other_conditions', {})['unit_typography_repair'] = 'font directives removed; value and source unit preserved'
        audit.append({'record_id': record.get('property_id') or record.get('point_id'),
                      'series_id': (series or {}).get('series_id'), 'unit_before': current,
                      'unit_after': corrected, 'value_raw': record.get('value_raw'), 'source_blocks': witnesses})
    for series in stage4.get('property_series', []):
        units = {p.get('unit_normalized') or p.get('unit_raw') or series.get('unit_raw') for p in series.get('points', [])}
        if len(units) == 1:
            series['unit_normalized'] = next(iter(units))
    return {'version': VERSION, 'changes': audit}
