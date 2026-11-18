"""Recover table semantics using source evidence only (no reference values)."""
from __future__ import annotations

from copy import deepcopy
import html
import re
from stages.final_unit_conversion import parse_numeric


def plain_label(value):
    text = html.unescape(str(value or ''))
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\\(?:text|mathrm|mathbf|mathit|operatorname)\s*', '', text)
    text = text.replace(r'\circ', '°')
    text = re.sub(r'\^\{[^{}]*\}', '', text)
    return re.sub(r'\s+', ' ', re.sub(r'[${}_\\]', '', text)).strip().casefold()


def locator_of(item):
    candidates = [item.get('evidence_locator'), item.get('table_locator'), item]
    evidence = item.get('evidence') or []
    if isinstance(evidence, dict):
        evidence = [evidence]
    for ev in evidence:
        if isinstance(ev, dict):
            candidates.extend([ev.get('table_locator'), ev])
    for loc in candidates:
        if isinstance(loc, dict) and loc.get('table_id') and loc.get('row_index') is not None and loc.get('column_index') is not None:
            return loc
    return {}


def source_context(elements):
    """Precompute source text once per paper, retaining block identities."""
    return {
        'tables': {e['block_id']: e for e in elements if e.get('type') == 'table'},
        'text': [(e['block_id'], plain_label(e.get('text'))) for e in elements if e.get('text')],
        'equations': [e for e in elements if e.get('type') == 'equation'],
    }


def recover_observation(item, context):
    """Attach explicit symbol definitions and the original cell locator.

    Ambiguous symbols require a supporting definition in this source paper.
    Existing values and units are left intact.
    """
    out = deepcopy(item)
    loc = locator_of(item)
    table = context.get('tables', {}).get(loc.get('table_id'), {})
    cells = table.get('table_cells', [])
    r, c = loc.get('row_index'), loc.get('column_index')
    cell = next((x for x in cells if x.get('row_index') == r and x.get('column_index') == c), None)
    label = item.get('property_name_raw') or item.get('semantic_label') or ''
    caption = plain_label(table.get('caption'))
    # Transposed tables have property labels on the left and sample names on
    # top. Use the source row header, not the numeric value or reference label.
    left = next((x for x in cells if x.get('row_index') == r and x.get('column_index') == 0), {})
    left_label = plain_label(left.get('text'))
    if re.match(r'^(?:pn|p\s*n|mu.*inh|eta.*inh|μ.*inh|η.*inh)', left_label) and c not in (0, None):
        label = left.get('text')
        unit_match = re.search(r'\(\s*(dl\s+g\s*\$?\^\{-1\}\$?)\s*\)', str(label), re.I)
        if unit_match and not (out.get('unit_raw') or out.get('unit_normalized')):
            out['indexed_unit_before_recovery'] = {'unit_raw': out.get('unit_raw'), 'unit_normalized': out.get('unit_normalized')}
            out['unit_raw'] = unit_match[1]
            out['unit_normalized'] = 'dl/g'
            out['index_unit_recovery_rule'] = 'explicit_transposed_row_unit'
            out['index_unit_evidence'] = dict(left)
    name = plain_label(label)
    compact = name.replace(' ', '')
    code, rule, qualifier = None, None, {}
    support = []

    def defined(pattern):
        matches = [(bid, s) for bid, s in context.get('text', []) if re.search(pattern, s)]
        support.extend(bid for bid, _ in matches)
        return bool(matches)

    if re.match(r'^(?:pn|p\s+n)(?:\b|$)', name) and ('poly' in caption or defined(r'degree.*polymerization')):
        code, rule = 'degree_of_polymerization', 'polymer_table_pn'
    elif re.fullmatch(r'x(?:\([^)]+\))?', compact) and defined(r'degree[s]? of polymerization\s*\(x\)'):
        code, rule = 'degree_of_polymerization', 'source_definition_x'
    elif name.startswith('initial modulus') and 'tensile' in caption:
        code, rule = 'tensile_modulus', 'tensile_table_initial_modulus'
    elif re.match(r'^ts(?:\b|\()', compact) and defined(r'softening temperatures?\s*\(\s*t\s*s\s*\)'):
        code, rule = 'softening_temperature', 'source_definition_ts'
    elif re.match(r'^tr(?:\b|\()', compact) and defined(r'recrystallization temperature\s*\(\s*t\s*r\s*\)'):
        code, rule = 'crystallization_temperature', 'source_definition_tr'
        qualifier['event_raw'] = 'recrystallization'
    elif re.match(r'^t[12](?:\b|,)', name) and 'thermal' in caption and defined(r'two (?:thermal )?decomposition (?:peaks|stages)'):
        code, rule = 'thermal_decomposition_temperature', 'source_definition_decomposition_peak'
        qualifier['decomposition_peak_index'] = int(name[1])
    elif 'dielectric constant' in name:
        freq = [x for x in cells if x.get('row_index', 99) <= 1 and c is not None
                and x.get('column_index', -1) <= c < x.get('column_index', -1) + x.get('column_span', 1)
                and re.fullmatch(r'\d+(?:\.\d+)?\s*[kmg]?hz', plain_label(x.get('text')))]
        if freq:
            code, rule = 'dielectric_constant_ac', 'frequency_header_confirms_ac'
            qualifier['frequency_raw'] = freq[-1]['text']
            support.extend(x['cell_id'] for x in freq)
    elif re.match(r'^(?:wt\.?|weight)\s*loss', name) and ('thermal' in caption or defined(r'tga.*weight loss')):
        code, rule = 'thermal_decomposition_weight_loss', 'thermal_table_weight_loss'
    if code:
        out['recovered_property_code'] = 'STD:' + code
        out['index_recovery_rule'] = rule
        out['index_qualifiers'] = qualifier
        out['index_semantic_evidence'] = sorted(set(support + ([table['block_id']] if table else [])))
        out['index_property_label'] = label
    if cell:
        out['source_cell_locator'] = {
            'table_id': table['block_id'], 'cell_id': cell['cell_id'],
            'row_index': r, 'column_index': c, 'cell_value': cell['text'],
            'column_label': label, 'table_caption': table.get('caption'),
        }
        out.setdefault('table_id', table['block_id'])
        out.setdefault('cell_id', cell['cell_id'])
    return out


def recover_missing_peak_cells(shadow, context):
    """Restore omitted peak/range cells in an already identified Td column.

    The property/column/unit come from Stage4T; numbers come only from the
    indexed source grid. No reference workbook is accepted by this function.
    """
    for table in shadow.get('tables') or []:
        if table.get('direction') != 'row_samples':
            continue
        source = context['tables'].get(table.get('table_id'), {})
        if not source:
            continue
        last_header = max(table.get('header_rows') or [0])
        occupied = {o.get('cell_id') for key in ('shadow_observations', 'llm_enriched_observations') for o in table.get(key) or []}
        for meta in table.get('property_candidates') or []:
            if meta.get('property_name_normalized') != 'thermal_decomposition_temperature':
                continue
            for cell in source.get('table_cells') or []:
                raw = cell.get('text', '')
                if (cell.get('column_index') != meta.get('column_index') or cell.get('row_index', -1) <= last_header
                        or cell.get('cell_id') in occupied or not re.search(r'\(peaks?\)\s*$', raw, re.I)
                        or not parse_numeric(raw)):
                    continue
                loc = {k: cell[k] for k in ('cell_id', 'row_index', 'column_index')}
                loc['table_id'] = source['block_id']
                yield {
                    **loc, 'property_name_raw': meta['property_name_raw'],
                    'property_name_normalized': meta['property_name_normalized'],
                    'value_raw': raw, 'unit_raw': meta.get('unit_raw'),
                    'source_file': 'stage0_blocks.json', 'source_stage': 'stage0',
                    'source_collection': 'recovered_table_cells',
                    'routing_source_file': 'stage4t_shadow.json',
                    'index_recovery_rule': 'unflattened_decomposition_peak_cell',
                    'index_qualifiers': {'event_raw': 'peak' if '(peak)' in raw else 'peaks'},
                    'evidence': [dict(loc)], 'evidence_locator': loc,
                }


def recover_equation_observations(context):
    """Index a directly stated Mw/Mn decimal assignment in a source equation."""
    for block in context.get('equations', []):
        raw = block.get('text', '')
        text = re.sub(r'\\(?:overline|bar|mathrm|text)\s*', '', raw)
        text = re.sub(r'[${}_]', '', text).strip()
        match = re.search(r'\bM\s*w\s*/\s*M\s*n\s*=\s*([0-9]+\s*\.\s*[0-9](?:\s*[0-9])*)\.?\s*$', text, re.I)
        if not match or not parse_numeric(match[1]):
            continue
        yield {
            'property_name_raw': 'Mw/Mn', 'property_name_normalized': 'molecular_weight_dispersity',
            'value_raw': match[1], 'unit_raw': '1',
            'source_file': 'stage0_blocks.json', 'source_stage': 'stage0',
            'source_collection': 'equation_property_recovery',
            'index_recovery_rule': 'explicit_source_equation_mw_mn',
            'index_semantic_evidence': [block['block_id']],
            'evidence': [{'block_id': block['block_id'], 'page': block.get('page'),
                          'source_type': 'equation', 'source_sentence': raw}],
        }


# A specific observation may support a deliberately unspecified reference.
# Never use these relations in reverse or erase source method distinctions.
GENERALIZATIONS = {
    'STD:solution_viscosity_unspecified': {'STD:intrinsic_viscosity', 'STD:inherent_viscosity', 'STD:reduced_viscosity', 'STD:specific_viscosity'},
    'STD:tensile_strength_unspecified': {'STD:tensile_stress_at_break', 'STD:tensile_strength_at_yield', 'STD:tensile_strength_ultimate'},
    'STD:impact_strength_unspecified': {'STD:izod_impact', 'STD:charpy_impact'},
}


def property_compatible(expected_code, observation):
    actual = observation.get('candidate_code')
    if actual == expected_code:
        return True
    if actual in GENERALIZATIONS.get(expected_code, set()):
        return True
    if expected_code == 'STD:d_spacing' and actual == 'STD:lattice_spacing':
        labels = [plain_label(str(observation.get(k) or '').replace('_', ' ')) for k in ('semantic_label', 'specialized_property_key', 'property_name_raw')]
        return any(x in {'d spacing', 'd-spacing', 'd'} or x.startswith(('d-spacing (', 'd spacing (')) for x in labels)
    return False
