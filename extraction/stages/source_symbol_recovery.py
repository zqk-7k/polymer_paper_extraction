"""Bounded PDF text-layer recovery of damaged temperature-symbol definitions.

Pure standard library: the caller supplies page text, not scores or labels.
Keep OCR evidence unchanged and append the recovered verbatim fragment.
"""
from __future__ import annotations

import copy
import hashlib
import re

VERSION = '1.0.0'
LOSS = r'(?P<percent>\d+(?:\.\d+)?)\s*%\s+(?:gravimetric|weight|mass)\s+loss\s*'
BROKEN = re.compile(LOSS + r'\(\s*T\s*\)', re.I)
EXPLICIT = re.compile(LOSS + r'\(\s*(?P<symbol>T(?:i|\d+))\s*\)', re.I)


def recover_symbol_definitions(stage0: dict, page_texts: dict[int, str], pdf_sha256: str):
    out = copy.deepcopy(stage0)
    additions, audit = [], []
    existing = {e['block_id'] for e in out.get('elements', [])}
    next_index = max((e.get('source_block_index') or 0 for e in out.get('elements', [])), default=0) + 1
    for element in out.get('elements', []):
        additions.append(element)
        if element.get('type') not in {'text', 'footnote'}:
            continue
        page = element.get('page')
        for damaged in BROKEN.finditer(element.get('text') or ''):
            percent = float(damaged['percent'])
            if not 0 < percent <= 100:
                continue
            candidates = [m for m in EXPLICIT.finditer(page_texts.get(page, ''))
                          if float(m['percent']) == percent]
            symbols = {m['symbol'].lower() for m in candidates}
            if len(symbols) != 1:
                audit.append({'parent_block_id': element['block_id'], 'percent': percent,
                              'status': 'ambiguous_or_absent_pdf_definition'})
                continue
            # A numeric symbol must not contradict its literal loss criterion.
            symbol = next(iter(symbols))
            if symbol[1:].isdigit() and float(symbol[1:]) != percent:
                continue
            quote = candidates[0][0]
            suffix = hashlib.sha256((element['block_id'] + quote).encode()).hexdigest()[:12]
            block_id = f'PDFDEF_{page}_{suffix}'
            if block_id in existing:
                continue
            existing.add(block_id)
            additions.append({'block_id': block_id, 'type': 'text', 'page': page,
                              'bbox': None, 'section': element.get('section'), 'text': quote,
                              'source_block_index': next_index, 'alignment_status': 'pdf_text_layer_fragment'})
            next_index += 1
            audit.append({'status': 'recovered', 'block_id': block_id, 'page': page,
                          'parent_block_id': element['block_id'], 'original_ocr_fragment': damaged[0],
                          'verbatim_pdf_fragment': quote, 'percent': percent, 'symbol': symbol,
                          'pdf_sha256': pdf_sha256, 'bbox_status': 'not_localized'})
    out['elements'] = additions
    return out, {'version': VERSION, 'decisions': audit,
                 'recovered': sum(x['status'] == 'recovered' for x in audit)}
