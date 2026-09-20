"""Repair explicitly scaled source columns without reading reference answers.

Q times 10^n and Q / 10^n are different display conventions. Restrict repairs
to unambiguous property families; ambiguous positive molecular-weight headings
are deliberately left alone. Recompute from the source literal, never multiply
the already-normalized output repeatedly.
"""
from __future__ import annotations
import copy
import math
import re
from stages.stage4_direct_table_supplement import (table_requests, plain, table_cell_scalar, header_applies,
    canonical_unit, power_header, inline_heat_capacity_components)
from stages.source_intervals import reported_interval

VERSION = '1.1.0'


def scale_rule(header: str) -> tuple[float, str] | None:
    h = re.sub(r'\s+', '', power_header(header).replace(r'\times', '×').replace('−', '-'))
    h = h.replace('\\', '')
    powers = list(re.finditer(r'10\^([+-]?\d{1,2})(?!\d)', h))
    if len(powers) != 1:
        return None
    m = powers[0]; exponent = int(m[1]); prefix = h[:m.start()]
    if not 0 < abs(exponent) <= 12:
        return None
    # A unit multiplier explicitly enclosed after the molecular-weight symbol
    # scales the displayed number, unlike bare Q times 10^n.
    if (re.fullmatch(r'M_?[nwzv](?:\^[a-z]\)?)?[\[(]×', prefix, re.I)
            and re.fullmatch(r'(?:g/mol|gmol\^?-1)?[\])]', h[m.end():], re.I)):
        return 10. ** exponent, 'printed molecular-weight bracketed unit multiplier'
    molecular = bool(re.fullmatch(r'M_?[nwzv](?:\^[a-z]\)?)?[×/]', prefix, re.I))
    if molecular and prefix.endswith('/'):
        return 10. ** exponent, 'printed molecular-weight heading Q/10^n'
    if molecular and prefix.endswith('×') and exponent < 0:
        return 10. ** -exponent, 'printed molecular-weight heading Q times 10^-n'
    # Positive molecular-weight ×10^n can be a unit multiplier in historical
    # tables. Do not impose the inverse convention using polymer plausibility.
    if molecular:
        return None
    if (re.match(r'(?:Delta|Δ)?C_?p(?![A-Za-z])', prefix, re.I)
            and prefix.endswith(('×', '(×'))):
        return 10. ** -exponent, 'printed heat-capacity response times 10^n; inverse display scale'
    if (prefix.endswith('×') and
            (re.search(r'tan(?:delta|δ)', prefix, re.I)
             or re.search(r'(?:thermal)?expansion|expansioncoefficient', prefix, re.I))):
        return 10. ** -exponent, 'printed response Q times 10^n; inverse display scale'
    return None


def repair_display_scales(stage4: dict, stage0: dict) -> tuple[dict, dict]:
    output = copy.deepcopy(stage4)
    cells = {c['cell_id']: (t, c) for t in table_requests(stage0) for c in t['cells']}
    changes, skipped = [], []

    def repair(item, parent, path):
        ids = {e.get('table_locator', {}).get('cell_id') for e in item.get('evidence', [])
               if e.get('table_locator') and e['table_locator'].get('cell_id')}
        if len(ids) != 1 or next(iter(ids)) not in cells:
            return
        cid = next(iter(ids)); table, cell = cells[cid]
        rules = [(scale_rule(h['text']), h) for h in table['cells'] if header_applies(h, cell)]
        rules = [(rule, h) for rule, h in rules if rule]
        if not rules:
            return
        if len({rule[0] for rule, h in rules}) != 1:
            skipped.append({'path': path, 'cell_id': cid, 'reason': 'conflicting_source_scale'}); return
        source = table_cell_scalar(cell['text'])
        if source is None:
            name = parent.get('property_name_normalized') or parent.get('property_name_raw') or ''
            components = inline_heat_capacity_components(cell['text'], name)
            role = (item.get('measurement_context') or {}).get('other_conditions', {}).get('source_peak_role')
            matched = [c for c in components if c['role'] == role]
            if len(matched) == 1:
                source = matched[0]['value']
        interval = reported_interval(plain(cell['text'])) if source is None else None
        if source is None and not interval:
            return
        # No conversion over an already-converted dimensional unit. That is a
        # separate unit-normalization problem, not this display-scale repair.
        raw_unit = item.get('unit_raw') or parent.get('unit_raw')
        normalized = item.get('unit_normalized') or parent.get('unit_normalized') or raw_unit
        if canonical_unit(raw_unit) != canonical_unit(normalized):
            skipped.append({'path': path, 'cell_id': cid, 'reason': 'unit_conversion_already_applied'}); return
        low = interval['minimum'] if interval else source
        high = interval['maximum'] if interval else source
        factor, basis = rules[0][0]
        expected = (low * factor, high * factor)
        current = (item.get('value_min'), item.get('value_max', item.get('value_min')))
        if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in current):
            return
        if all(math.isclose(x, y, rel_tol=1e-12, abs_tol=0.) for x, y in zip(current, expected)):
            return
        # The complete source-cell literal and coordinates are retained. This
        # replaces an interpretation, not an additional measured observation.
        item['value_min'], item['value_max'] = expected
        context = item.setdefault('measurement_context', {})
        other = context.setdefault('other_conditions', {})
        other.update(source_display_scale_basis=basis, source_display_scale_factor=str(factor),
                     source_display_header=' | '.join(h['text'] for rule, h in rules),
                     source_display_original_cell=cell['text'],
                     source_display_previous_interpretation=str(current))
        # The context now records an explicitly printed display convention.
        # Keep its schema status consistent without inventing a measurement
        # temperature, method, sample identity or processing condition.
        context['condition_status'] = 'reported'
        changes.append({'path': path, 'cell_id': cid, 'header_ids': [h['cell_id'] for rule, h in rules],
                        'before': current, 'after': expected, 'factor': factor, 'basis': basis})

    for container in ['properties', 'specialized_property_observations']:
        for i, item in enumerate(output.get(container, [])):
            repair(item, item, f'{container}[{i}]')
    for i, series in enumerate(output.get('property_series', [])):
        for j, point in enumerate(series.get('points', [])):
            repair(point, series, f'property_series[{i}].points[{j}]')
    return output, {'version': VERSION, 'changes': changes, 'skipped': skipped, 'gold_access': False}
