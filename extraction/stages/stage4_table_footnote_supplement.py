"""Recover explicit temperature footnotes with a unique source-table owner.

This source-only adapter does not inspect a reference ID, gold, or scores. It
does not assign a global sample identity. The value evidence stays a footnote;
the table cell supplies only the source sample label and marker association.
"""
from __future__ import annotations

import re

from stages.stage4_direct_table_supplement import evidence, plain


_START = re.compile(r'^\s*(?:<sup>\s*)?([a-z])[).](?:\s*</sup>)?\s*', re.I)
_PROPERTY = re.compile(r'\b(melting (?:point|temperature)|glass transition temperature)\b', re.I)
_LITERAL = re.compile(
    r'(?<![\d.])(?P<value>[+−-]?\s*\d(?:[\d\s]*\d)?(?:\.\s*\d(?:[\d\s]*\d)?)?)\s*'
    r'(?P<unit>\^\s*\{\s*\\circ\s*\}\s*\\(?:mathrm|text)\s*\{\s*C\s*\}|°\s*C|℃)'
)


def table_footnote_facts(stage0: dict) -> list[tuple[dict, dict]]:
    """Return source-verified facts and their independent row-label evidence.

    Deliberately bounded to a note immediately after its same-page table (or
    after other explicitly marked notes), a placeholder marker in one cell,
    an explicit sample-label column, and one literal Celsius temperature.
    Ambiguous markers, ranges, comparisons, and calculations remain unresolved.
    """
    output = []
    elements = stage0.get('elements', [])
    for index, note in enumerate(elements):
        source = note.get('text') or ''
        marker = _START.match(source)
        if note.get('type') not in {'text', 'footnote'} or not marker:
            continue
        table = None
        for previous in reversed(elements[max(0, index - 3):index]):
            if previous.get('page') != note.get('page'):
                break
            if previous.get('type') == 'table':
                table = previous
                break
            if not _START.match(previous.get('text') or ''):
                break
        if table is None:
            continue
        cells = table.get('table_cells') or []
        marked = [c for c in cells if re.fullmatch(
            r'\s*[-–—]?\s*\^?\s*' + re.escape(marker[1]) + r'[).]\s*', plain(c.get('text')), re.I)]
        if len(marked) != 1:
            continue
        owner = marked[0]
        headings = [c for c in cells if c.get('column_index') == 0
                    and c.get('row_index', -1) < owner['row_index']
                    and re.fullmatch(r'(?:polymer|sample|material)(?:\s+(?:code|label|no\.?|number))?',
                                     plain(c.get('text')), re.I)]
        labels = [c for c in cells if c.get('column_index') == 0
                  and c.get('row_index') == owner['row_index'] and c.get('row_span', 1) == 1
                  and 0 < len(plain(c.get('text'))) <= 80]
        if len(headings) != 1 or len(labels) != 1 or owner['column_index'] == 0:
            continue
        properties = list(_PROPERTY.finditer(plain(source)))
        literals = list(_LITERAL.finditer(source))
        if len(properties) != 1 or len(literals) != 1:
            continue
        prop, literal = properties[0], literals[0]
        prefix = plain(source[:literal.start()])
        # Require a direct assignment after the named property, not an
        # inequality, a range endpoint, a calculated result, or a negation.
        if (not re.search(_PROPERTY.pattern + r'\s*(?:at|a t|of|is|was|=|:)?\s*$', prefix, re.I)
                or re.search(r'\b(?:no|not|cannot|calculated|estimated|above|below|between)\b', plain(source), re.I)):
            continue
        raw = literal['value'].strip()
        # Spaced digits must be contained in an actual math fragment. Do not
        # join prose lists just because the last item has a temperature unit.
        if re.search(r'\d\s+\d', raw) and not any(raw in fragment for fragment in re.findall(r'\$([^$]+)\$', source)):
            continue
        label_cell = labels[0]
        label = plain(label_cell['text'])
        name = 'melting temperature' if prop[1].lower().startswith('melting') else 'glass transition temperature'
        table_info = {'table_id': table['block_id'], 'page': table['page'], 'bbox': table.get('bbox')}
        binding = {
            'subject_evidence': evidence(table_info, label_cell, row_label=label, column_label=headings[0]['text']),
            'table_id': table['block_id'], 'marker_cell_id': owner['cell_id'], 'footnote_marker': marker[1],
        }
        fact = {'block_id': note['block_id'], 'sample_evidence_block_id': table['block_id'],
                'sample_label': label, 'property_name': name, 'value_raw': raw,
                'unit_raw': literal['unit'], 'quote': source, 'role': 'material_property',
                'reported_origin': 'not_specified'}
        output.append((fact, binding))
    return output
