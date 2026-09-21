"""Source-preserving quantity normalization, independent of benchmark values.

Only explicit units and source multipliers are used. Raw values/units/evidence
remain unchanged. This is a publication representation pass, not re-extraction.
"""
from __future__ import annotations
import copy
import math
import re
from typing import Any

from stages.stage4_direct_table_supplement import canonical_unit, scalar

VERSION = "1.1.0"


def normalization_rule(name: str, unit: str) -> tuple[float, float, str, str] | None:
    key = (canonical_unit(unit) or '').casefold()
    typography = {'dl./g':'dL/g', 'g./cc':'g/cm3', 'g/cc':'g/cm3'}
    if key in typography:
        return (1.,0.,typography[key],
                'explicit unit abbreviation punctuation normalized; cc = cm3; numeric value unchanged')
    thermal = bool(re.search(r'temperature|transition|melting|softening|\bt[_ ]?[gcm]\b', name, re.I))
    difference = bool(re.search(r'difference|interval|\bdelta\b|Δ|width|shift|change|depression|elevation|increase|decrease|supercooling|amplitude', name, re.I))
    if key == 'k' and thermal:
        if re.search(r'gradient|range|window|span', name, re.I) and not difference:
            return None  # An ambiguous temperature window is not an absolute scalar.
        return (1., 0. if difference else -273.15, '°C',
                'temperature interval K to degC, no offset' if difference else 'T(degC) = T(K) - 273.15')
    if key in {'å', 'ångström', 'ångstrom', 'angstroem'} or (key == 'angstrom' and str(unit) != 'angstrom'):
        return (1., 0., 'angstrom', 'angstrom typography normalization')
    if re.search(r'molar mass|molecular weight|\bm[wnvz]\b', name, re.I):
        match = re.fullmatch(r'(million|thousand)(g/mol|gram/mol|grams/mol)', key)
        if match:
            scale = 1e6 if match[1] == 'million' else 1e3
            return (scale, 0., 'g/mol', f'explicit {match[1]} multiplier in source unit')
        if key in {'gram/mol', 'grams/mol'}:
            return (1., 0., 'g/mol', 'gram to g typography normalization')
    return None


def normalize_source_quantities(stage4: dict) -> tuple[dict, dict]:
    output = copy.deepcopy(stage4)
    changes, skipped = [], []

    def normalize(record: dict, name: str, path: str, inherited_unit: str | None = None):
        raw_unit = record.get('unit_raw') or inherited_unit
        current_unit = record.get('unit_normalized') or raw_unit
        if not current_unit:
            return
        rule = normalization_rule(name, str(current_unit))
        if rule is None:
            return
        factor, offset, target, reason = rule
        if canonical_unit(raw_unit) != canonical_unit(current_unit):
            skipped.append({'path': path, 'reason': 'already_normalized_or_raw_unit_disagrees'})
            return
        low, high = record.get('value_min'), record.get('value_max')
        if not isinstance(low, (int,float)) or isinstance(low,bool) or not math.isfinite(low):
            return
        if high is not None and high != low:
            return
        raw = str(record.get('value_raw') or '').strip()
        raw_number = scalar(raw)
        if raw_number is None and raw_unit and raw.endswith(str(raw_unit)):
            raw_number = scalar(raw[:-len(str(raw_unit))].strip())
        if raw_number is None or not math.isclose(raw_number, low, rel_tol=1e-10, abs_tol=0.):
            skipped.append({'path': path, 'reason': 'raw_number_not_equal_to_current_number'})
            return
        if str(current_unit).casefold() == 'k' and offset and low < 0:
            skipped.append({'path':path,'reason':'negative_absolute_kelvin'})
            return
        value = low * factor + offset
        record['value_min'] = value
        record['value_max'] = value
        record['unit_normalized'] = target
        context = record.get('measurement_context') or {'condition_status':'reported','other_conditions':{}}
        context['condition_status'] = 'reported'
        context.setdefault('other_conditions',{})['quantity_normalization'] = reason
        record['measurement_context'] = context
        changes.append({'path':path,'property':name,'source_value':low,'source_unit':current_unit,
                        'normalized_value':value,'normalized_unit':target,'rule':reason})

    for container in ['properties','specialized_property_observations']:
        for i, record in enumerate(output.get(container) or []):
            normalize(record, ' '.join(str(record.get(k) or '') for k in ['property_name_normalized','property_name_raw','semantic_label']), f'{container}[{i}]')
    for i, series in enumerate(output.get('property_series') or []):
        name = ' '.join(str(series.get(k) or '') for k in ['property_name_normalized','property_name_raw'])
        for j, point in enumerate(series.get('points') or []):
            normalize(point, name, f'property_series[{i}].points[{j}]', series.get('unit_raw'))
        # Do not advertise one normalized series unit if some points differ.
        point_units = {p.get('unit_normalized') or p.get('unit_raw') or series.get('unit_raw') for p in series.get('points') or []}
        if len(point_units)==1:
            series['unit_normalized'] = next(iter(point_units))
    if changes:
        output.setdefault('warnings',[]).append({'stage':'source_quantity_normalization','code':'explicit_source_units_normalized',
            'message':'Only explicit source units/multipliers were converted; raw text/units/evidence retained. No benchmark values were read.',
            'version':VERSION,'changed_quantity_count':len(changes)})
    return output, {'version':VERSION,'changes':changes,'skipped':skipped}
