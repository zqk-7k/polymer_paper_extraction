"""Conservative recovery of experimental paragraphs mislabeled as citations.

Uses source text and section context only: no reference IDs, expected values,
gold files or model outputs. True bibliography and ambiguous blocks stay out.
"""
from __future__ import annotations

import re


def is_mislabeled_characterization(data: dict, current_section: str | None = None) -> bool:
    if data.get('element_type') != 'references':
        return False
    sections = ' '.join(str(x or '') for x in (data.get('section'), current_section))
    if re.search(r'references?|bibliography|参考文献', sections, re.I):
        return False
    if not re.search(r'experiment|method|synthes|prepar|results', sections, re.I):
        return False
    text = str(data.get('text') or '').strip()
    if not re.match(r'^characteri[sz]ation\s+(?:data\s+)?(?:for|of)\s+\S', text, re.I):
        return False
    # Multiple independent measurement cues distinguish a results paragraph
    # from a paper title which happens to begin with "Characterization of".
    cues = sum(bool(re.search(pattern, text, re.I)) for pattern in (
        r'\byield\s*[:=]?\s*\d', r'\bNMR\b', r'\b(?:GPC|SEC)\b', r'\bFTIR\b',
    ))
    return cues >= 2 and bool(re.search(r'\d', text))
