"""Extract explicit, local prose assignments; no pronoun or cross-sentence binding."""
import re

from stages.binding_identity import build_article_sample_key
from stages.sample_catalog import digest
from stages.standard_mapping import resolve_standard_property


# Deliberately bounded to an unambiguous property/unit and two explicit syntaxes.
# Broader prose remains in the source inventory and target coverage gap queue.
PROPERTIES = {'elongation at break': ('elongation at break', {'%'}),
              'tensile strength': ('tensile strength', {'MPa','GPa','kPa','Pa'}),
              'tensile strengths': ('tensile strength', {'MPa','GPa','kPa','Pa'}),
              'tensile modulus': ('tensile modulus', {'MPa','GPa','kPa','Pa'}),
              'glass transition temperature': ('glass transition temperature', {'°C','K'}),
              'melting temperature': ('melting temperature', {'°C','K'}),
              'melting point': ('melting temperature', {'°C','K'}),
              'crystallization temperature': ('crystallization temperature', {'°C','K'}),
              'water absorption': ('water absorption', {'%'}),
              'oxygen index': ('oxygen index', {'%'}),
              'contact angle': ('contact angle', {'°'})}
PROPERTY = r'(?P<property>' + '|'.join(re.escape(p) for p in PROPERTIES) + ')'
SENTENCE = r'(?:^|(?<=[.!?])\s+)(?:The\s+)?'
MATERIAL = r'[A-Za-z][A-Za-z0-9() ,+\-/]{0,60}?'
NUMBER = r'[-+]?\d+(?:\.\d+)?'
UNIT = r'(?:MPa|GPa|kPa|Pa|°C|K|%|°)'
PAIR = re.compile(SENTENCE + PROPERTY + r' of (?:the )?(?P<s1>' + MATERIAL + r') and (?:the )?(?P<s2>' + MATERIAL +
                  r') (?:is|was|are|were) (?P<v1>' + NUMBER + r')\s*(?P<u1>' + UNIT + r') and (?P<v2>' + NUMBER + r')\s*(?P<u2>' + UNIT + r'),? respectively\b', re.I)
SINGLE = re.compile(SENTENCE + PROPERTY + r' of (?:the )?(?P<s1>' + MATERIAL + r') (?:is|was) (?:only |about |approximately )?'
                    r'(?P<v1>' + NUMBER + r')\s*(?P<u1>' + UNIT + r')(?=[.,;\s]|$)', re.I)


def build_text_observations(document_id, blocks):
    rows = []
    for block in blocks:
        if (block.get('section') or '').casefold() in {'references', 'bibliography'}:
            continue
        text = block.get('text') or ''
        occupied = []
        matches = [(m, (1, 2)) for m in PAIR.finditer(text)]
        occupied.extend(m.span() for m, _ in matches)
        matches.extend((m, (1,)) for m in SINGLE.finditer(text)
                       if not any(start <= m.start() < end for start, end in occupied))
        for match, indexes in sorted(matches, key=lambda item: item[0].start()):
            if re.match(r'\s+(?:higher|lower|greater|less|more|larger|smaller)\b', text[match.end():], re.I):
                continue
            # A plural clause without "respectively" must not be truncated to
            # a single material/value association by the single-value pattern.
            if indexes == (1,) and (' and ' in match['s1'].lower() or re.match(r'\s+and\s+\d', text[match.end():])):
                continue
            for i in indexes:
                property_name, allowed_units = PROPERTIES[match['property'].casefold()]
                if match['u'+str(i)] not in allowed_units:
                    continue
                label = match['s' + str(i)]
                if label.casefold() in {'it', 'this', 'that', 'these', 'those', 'the sample', 'sample', 'samples', 'them'}:
                    continue
                spans = {name: {'start': match.start(group), 'end': match.end(group), 'text': match[group]}
                         for name, group in [('property', 'property'), ('sample', 's' + str(i)),
                                             ('value', 'v' + str(i)), ('unit', 'u' + str(i))]}
                bid = block['block_id']
                locator = f'{bid}:chars:{spans["value"]["start"]}:{spans["value"]["end"]}'
                mapping = resolve_standard_property(property_name, spans['unit']['text'])
                rows.append({'observation_id': 'text_observation_' + digest([document_id, locator])[:24],
                    'document_id': document_id, 'source_kind': 'text', 'source_block_id': bid,
                    'source_locator': locator, 'source_cell_id': None, 'table_id': None,
                    'source_text_sha256': digest(text), 'source_spans': spans,
                    'source_excerpt': text[match.start():match.end()],
                    'source_excerpt_span': {'start': match.start(), 'end': match.end()},
                    'value_raw': spans['value']['text'], 'value_normalized': None,
                    'property_name_raw': spans['property']['text'], 'property_header_path': [],
                    'property_header_cell_ids': [], 'sample_axis_cell_ids': [],
                    'article_sample_label_raw': label,
                    'article_sample_key': build_article_sample_key(document_id, bid, label,
                        variant_context={'text_assignment_start': match.start()}),
                    'sample_label_basis': 'explicit_same_clause', 'sample_id': None, 'entity_id': None,
                    'identity_status': 'article_label_only', 'unit_raw': spans['unit']['text'],
                    'unit_status': 'source_token', 'unit_source_texts': [spans['unit']['text']],
                    'condition_context_raw': [], 'conditions_status': 'not_exhaustively_extracted',
                    'record_kind': 'property', 'extraction_status': 'usable', 'review_fields': [],
                    'evidence_basis': 'explicit_text_assignment', 'historical_request_verified': False,
                    'standard_property_code': mapping['standard_property_code'], 'standard_status': mapping['standard_status'],
                    'standard_mapping_reasons': mapping['mapping_reasons'], 'claim_ids': [], 'legacy_final_measurement_ids': [],
                    'value_qualifier_raw': text[match.end('s' + str(i)):match.start('v' + str(i))] if indexes == (1,) else '',
                    'definition': 'One explicit source mention; repeated mentions are not deduplicated measurements.'})
    return rows
