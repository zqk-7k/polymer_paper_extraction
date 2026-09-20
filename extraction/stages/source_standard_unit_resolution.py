"""Resolve a missing reporting unit only from an explicitly named standard.

Does not generate a value or claim the unit was printed in a table. The original
value/unit remain untouched; the standard evidence and inference are explicit.
No benchmark, DOI, sample whitelist or evaluator dependency.
"""
import copy
import math
import re

from stages.stage4_direct_table_supplement import plain, scalar, header_applies

VERSION = '1.0.1'
STANDARD_SOURCE = 'https://store.astm.org/d2863-23.html'


def resolve_standard_units(stage4: dict, stage0: dict) -> tuple[dict, dict]:
    output = copy.deepcopy(stage4)
    decisions = []
    # Require the paper to identify the oxygen-index method, not just list a
    # standard in references or mention it for another test.
    method_blocks = []
    for block in stage0.get('elements', []):
        if block.get('type') != 'text' or re.search(r'references|bibliography', str(block.get('section') or ''), re.I):
            continue
        text = plain(block.get('text', ''))
        for sentence in re.split(r'(?<=[.;])\s+', text):
            if (re.search(r'\b(?:LOI|oxygen[ -]index)\b', sentence, re.I)
                    and re.search(r'\bASTM\s*D[\s-]*2863\b', sentence, re.I)
                    and re.search(r'measur|determin|test|according', sentence, re.I)):
                method_blocks.append((block, sentence))
    if not method_blocks:
        return output, {'version': VERSION, 'decisions': decisions}
    block, sentence = method_blocks[0]
    elements = {b['block_id']: b for b in stage0.get('elements', [])}
    for i, series in enumerate(output.get('property_series') or []):
        name = str(series.get('property_name_normalized') or series.get('property_name_raw') or '').replace('_', ' ')
        if not re.search(r'\b(?:LOI|(?:limiting )?oxygen index)\b', name, re.I):
            continue
        for j, point in enumerate(series.get('points') or []):
            if any(point.get(k) or series.get(k) for k in ['unit_raw', 'unit_normalized']):
                continue  # Never override an explicit unit or rescale a fraction.
            value = point.get('value_min')
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or not 1 < value <= 100
                    or point.get('value_max') not in (None, value)
                    or scalar(str(point.get('value_raw') or '')) != value):
                continue
            supported = False
            for ev in point.get('evidence') or []:
                source = elements.get(ev.get('block_id'), {})
                if source.get('type') != 'table':
                    continue
                locator = ev.get('table_locator') or {}
                header = str(locator.get('column_label') or '')
                if re.search(r'\b(?:LOI|oxygen index)\b', header, re.I):
                    # The selected cell must actually contain the retained value.
                    cells = {c.get('cell_id'): c for c in source.get('table_cells') or []}
                    cell = cells.get(locator.get('cell_id'), {})
                    actual_headers = [c for c in cells.values()
                        if re.search(r'\b(?:LOI|oxygen index)\b', plain(c.get('text','')), re.I)
                        and all(k in c and k in cell for k in ['row_index','column_index'])
                        and header_applies(c,cell)]
                    supported |= scalar(cell.get('text', '')) == value and bool(actual_headers)
            if not supported:
                continue
            point['unit_normalized'] = '%'
            context = point.setdefault('measurement_context', {})
            context.setdefault('other_conditions', {}).update({
                'unit_resolution_basis': 'standard_defined_not_printed',
                'unit_standard': 'ASTM D2863 oxygen index: volume percent',
                'unit_standard_source': STANDARD_SOURCE,
                'unit_standard_evidence_block': block['block_id'],
                'unit_standard_evidence_quote': sentence,
                'unit_resolution_value_rescaled': 'false',
            })
            decisions.append({'series_index': i, 'point_index': j, 'value': value,
                              'normalized_unit': '%', 'rule': 'explicit_D2863_method',
                              'source_block_id': block['block_id'], 'source_quote': sentence})
        units = {p.get('unit_normalized') or p.get('unit_raw') for p in series.get('points') or []}
        if units == {'%'}:
            series['unit_normalized'] = '%'
    return output, {'version': VERSION, 'decisions': decisions}
