"""Retain source-labelled thermal criteria without claiming resolved sample IDs.

Scope is deliberately limited to an existing loss/temperature relation. The
source quote must explicitly attribute its associated temperature to its label;
mere presence of a label somewhere in the sentence is insufficient.
"""
import copy
import math
import re

from stages.source_prose_loss_facts import norm

VERSION = '1.1.0'


def temperature_attributed_to_label(quote, label, temperature):
    text, token = norm(quote), norm(label)
    if re.search(r'\b(?:not|never|no|neither|nor)\b', text, re.I):
        return False  # Conservative abstention for negated/mixed assertions.
    boundary = r'[\w/-]'
    subject = rf'(?<!{boundary}){re.escape(token)}(?!{boundary})'
    number = rf'(?<![\d.]){re.escape(f"{temperature:g}")}\s*°\s*C\b'
    # Enumeration form: "at 430°C for Q, 450°C for R".
    if re.search(number + r'\s+for\s+' + subject, text):
        return True
    # Subject-first assertion. Split only explicit clause boundaries, not a
    # decimal or the figure citation in a shared "and at ..." predicate.
    clauses = re.split(r';|,?\s+\b(?:while|whereas|but)\b\s*|(?<=[a-z])\.\s+(?=[A-Z])', text)
    assertion = subject + r'\s+(?:(?:polyimide|polymer|film|sample)\s+)?(?:exhibited|showed|shows|had)\s+'
    for clause in clauses:
        matches = list(re.finditer(assertion, clause))
        if len(matches) != 1:
            continue
        tail = clause[matches[0].end():]
        # Another stated subject/predicate or list-of-subjects is ambiguous.
        if re.search(r'\b(?:exhibited|showed|shows|had|respectively)\b', tail, re.I):
            continue
        if re.search(r'\b(?:not|never|no)\b', tail, re.I):
            continue
        if re.search(number, tail):
            return True
    return False


def preserve_prose_subject_labels(stage4, stage0):
    out = copy.deepcopy(stage4)
    blocks = {b['block_id']: b for b in stage0.get('elements', []) if b.get('type') == 'text'}
    decisions = []
    for series in out.get('property_series', []):
        for point in series.get('points', []):
            context = (point.get('measurement_context') or {}).get('other_conditions', {})
            if context.get('fact_role') != 'measurement_criterion' or not context.get('source_loss_relation_id'):
                continue
            labels = {c['value_raw'] for c in point.get('coordinates', [])
                      if c.get('name_raw') == 'source sample label' and c.get('value_raw')}
            temperatures = [c for c in point.get('coordinates', [])
                            if c.get('name_raw') == 'associated decomposition temperature' and c.get('unit_raw') == '°C']
            if len(labels) != 1 or len(temperatures) != 1 or point.get('sample_label_raw'):
                continue
            label = next(iter(labels))
            if not re.search(r'[A-Za-z]', label):
                continue
            try:
                temperature = float(temperatures[0]['value_raw'])
            except (ValueError, TypeError, KeyError):
                continue
            if not math.isfinite(temperature):
                continue
            for ev in point.get('evidence', []):
                block = blocks.get(ev.get('block_id'))
                quote = norm(ev.get('source_sentence', ''))
                if not block or not quote or quote not in norm(block.get('text', '')):
                    continue
                if not temperature_attributed_to_label(quote, label, temperature):
                    continue
                point['sample_label_raw'] = label
                decisions.append({'series_id': series['series_id'], 'point_id': point['point_id'],
                                  'sample_label_raw': label, 'associated_temperature_C': temperature,
                                  'source_block_id': block['block_id'], 'source_quote': ev['source_sentence'],
                                  'sample_id_inferred': False})
                break
    return out, {'version': VERSION, 'labels_preserved': len(decisions), 'decisions': decisions,
                 'new_numeric_observations': 0, 'gold_access': False}
