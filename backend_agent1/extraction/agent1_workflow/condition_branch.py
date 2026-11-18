"""Recognize an already explicit, source-backed failure branch; preserve text."""
from copy import deepcopy
import re
from condition_evidence import valid_refs


def explicit_failure_branch(value):
    text = ' '.join(str(value).casefold().split())
    return bool(re.search(r'\b(?:heated?|heating|boiling)\b', text) and
                re.search(r'\b(?:if|when)\b.{0,100}\b(?:not\s+dissolv\w*|fail\w*\s+to\s+dissolve|insoluble)\b', text))


def source_failure_branch(quote):
    text = ' '.join(str(quote).casefold().split())
    return bool(re.search(r'\b(?:samples?|polymers?|specimens?)\b.{0,80}\b(?:did not|do not|failed to)\s+dissolve\b.{0,200}\bheated\b', text))


def adapt(observation, blocks, cells, allowed):
    result = deepcopy(observation); audit = []
    for i, condition in enumerate(result.get('conditions', [])):
        if not isinstance(condition, dict) or condition.get('applies_when') is not None:
            continue
        name = str(condition.get('name_raw', '')).casefold()
        declared_guard=condition.get('trigger') or condition.get('guard')
        if isinstance(declared_guard,dict):declared_guard=declared_guard.get('kind') or declared_guard.get('trigger')
        explicit_name=bool(re.search(r'\b(?:for|if|when|after)\b.{0,100}\b(?:not\s+dissolv\w*|fail\w*\s+to\s+dissolve|insoluble)\b',name))
        if not any(t in name for t in ('heat', 'temperature')) or not (explicit_failure_branch(condition.get('value_raw')) or explicit_name or declared_guard=='initial_test_failure'):
            continue
        refs = condition.get('evidence_refs', [])
        if not valid_refs(refs, blocks, cells, result.get('table_id'), allowed):
            continue
        if not any(source_failure_branch(r.get('quote')) for r in refs):
            continue
        condition['applies_when'] = 'initial_test_failure'
        condition['condition_role'] = 'protocol_branch'
        regime = result.get('test_regime')
        condition['applies_to_current_observation'] = False if regime == 'room_temperature' else None
        audit.append({'condition_index': i, 'action': 'explicit_source_backed_failure_branch',
                      'value_raw_unchanged': True, 'name_raw_unchanged': True,
                      'evidence_refs_unchanged': True, 'regime': regime,
                      'actual_heating_inferred': False})
    return result, audit
