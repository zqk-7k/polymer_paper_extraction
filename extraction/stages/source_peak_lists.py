"""Recover source-declared melting peak lists; no reference answers or model calls."""
import re
from stages.stage4_direct_table_supplement import (
    table_requests, header_applies, header_declared_peaks, plain, merge_supplement,
)

VERSION = '1.1.0'


def recover_peak_lists(stage4, stage0):
    responses = []
    for table in table_requests(stage0):
        cells = table['cells']
        groups = []
        for cell in cells:
            # A regular column with source sample headings is required. Do not
            # infer unnamed series, transposed subjects, or temperature units.
            if not any(s in str(cell.get('text', '')) for s in [';', '/']):
                continue
            headers = [h for h in cells if h['row_index'] < cell['row_index']
                       and header_applies(h, cell)
                       and re.search(r'fusion|melting|\bpeaks\b|glass\s+transition|crystallization', plain(h['text']), re.I)]
            header = ' | '.join(h['text'] for h in headers)
            components = header_declared_peaks(cell['text'], header, table.get('caption',''))
            if not components:
                continue
            subject_headers = [h for h in cells if h['row_index'] < cell['row_index']
                               and re.fullmatch(r'(?:sample|polymer)(?:\s+(?:number|no\.?|code|name))?',
                                                plain(h['text']), re.I)]
            double = components[0]['binding_method']=='source_caption_declares_double_transitions'
            if double:
                subject_headers += [h for h in cells if h['row_index'] < cell['row_index']
                                    and re.match(r'^Blend\s+Composition\b', plain(h['text']), re.I)]
            condition_headers = [h for h in cells if double and h['row_index'] < cell['row_index']
                                 and re.search(r'Extruder\s+Screw\s+Speed', plain(h['text']), re.I)]
            subjects = [s for s in cells if s['row_index'] == cell['row_index']
                        and s['column_index'] < cell['column_index'] and str(s['text']).strip()
                        and any(header_applies(h, s) for h in subject_headers)]
            if not subjects:
                continue
            conditions = [s for s in cells if s['row_index']==cell['row_index']
                          and any(header_applies(h,s) for h in condition_headers)]
            identity = subjects + conditions
            columns = [s['column_index'] for s in identity]
            signature = tuple(s['text'] for s in identity)
            other_rows = {x['row_index'] for x in cells if x['row_index'] != cell['row_index']}
            if any(tuple(next((s['text'] for s in cells if s['row_index'] == r
                               and s['column_index'] == c), '') for c in columns) == signature
                   for r in other_rows):
                continue
            name = ('glass transition temperature' if re.search(r'glass\s+transition', plain(header), re.I)
                    else 'cold crystallization temperature' if re.search(r'cold\s+crystallization',plain(header),re.I)
                    else 'crystallization temperature' if re.search(r'crystallization',plain(header),re.I)
                    else 'melting peak temperature')
            groups.append({'property_name_raw': header, 'property_name_normalized': name,
                'unit_raw': '°C', 'scale_exponent': 0,
                'header_cell_ids': [h['cell_id'] for h in headers],
                'points': [{'cell_id': cell['cell_id'],
                            'subject_cell_ids': [s['cell_id'] for s in subjects],
                            'condition_cell_ids': [s['cell_id'] for s in conditions]}]})
        if groups:
            responses.append((table, {'groups': groups}))
    output, audit = merge_supplement(stage4, responses)
    return output, {'version': VERSION, **audit, 'gold_access': False}
