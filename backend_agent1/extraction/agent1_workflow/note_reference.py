"""Resolve a parent-table citation to one explicitly supplied original footnote."""
from copy import deepcopy
import re
from evidence_registry import registry, original_quote, normalize as base_normalize


MARKER = re.compile(r'^\s*<sup>\s*([^<>]+?)\s*</sup>\s*', re.I)


def alias(ref, raw, sources, allowed):
    if not isinstance(ref, dict) or ref.get('source_cell_id'):
        return ref, None
    sid = ref.get('source_id') or ref.get('source_block_id')
    tables = {b['block_id']: b for b in raw['elements'] if b.get('type') == 'table'}
    if sid not in tables or sid not in allowed or not isinstance(ref.get('quote'), str):
        return ref, None
    if original_quote(ref['quote'], sources[sid]['text'])[0] is not None:
        return ref, None  # A real caption citation already has a valid address.
    children = {key for key in sources if key.startswith(sid + ':ocr_footnote:')}
    for item in tables[sid].get('table_note_evidence', []):
        key = item.get('source_id') or item.get('evidence_id')
        if key in sources: children.add(key)
    matches = []
    for child in sorted(children & set(allowed)):
        text = sources[child]['text']; quote = ref['quote']
        model_marker = MARKER.match(quote)
        source_marker = MARKER.match(text)
        if model_marker:
            if not source_marker or model_marker[1] != source_marker[1]: continue
            quote = quote[model_marker.end():]
            if not quote.strip(): continue
        recovered, _ = original_quote(quote, text)
        if recovered is not None:
            matches.append({'kind': 'text', 'source_block_id': child, 'quote': recovered})
    if len(matches) != 1:
        return ref, None
    return matches[0], {'action': 'unique_same_table_footnote_address',
        'original_reference': deepcopy(ref), 'canonical_reference': deepcopy(matches[0]),
        'semantic_support_independently_verified': False,
        'measurement_and_condition_values_unchanged': True}


def normalize(conditions, raw, identity, allowed):
    if not isinstance(conditions, list): return base_normalize(conditions, raw, identity, allowed)
    result = deepcopy(conditions); sources = registry(raw); changes = []
    for i, condition in enumerate(result):
        if not isinstance(condition, dict): continue
        refs = condition.get('evidence_refs')
        if refs is None and condition.get('source_block_id') and condition.get('quote'):
            refs = [{k: condition[k] for k in ('source_block_id', 'quote')}]
        if not isinstance(refs, list): continue
        fixed = []; local = []
        for ref in refs:
            resolved, audit = alias(ref, raw, sources, allowed)
            fixed.append(resolved)
            if audit: local.append({'condition_index': i, **audit})
        if local: condition['evidence_refs'] = fixed; changes.extend(local)
    normalized, old_audit = base_normalize(result, raw, identity, allowed)
    return normalized, changes + old_audit
