"""Preserve imported identities and protocols; never invent physical batch edges."""
from copy import deepcopy
from collections import defaultdict
from catalog import norm


def build_identity(stage2, stage3):
    entities = {e['entity_id']: deepcopy(e) for e in stage2.get('polymer_entities', [])}
    samples = deepcopy(stage3.get('samples', []))
    assert len({s['sample_id'] for s in samples}) == len(samples), 'Duplicate sample ID'
    contexts = {x.get('sample_id'): deepcopy(x) for x in stage3.get('identity_contexts', []) if x.get('sample_id')}
    aliases = defaultdict(set)
    for sample in samples:
        sid = sample['sample_id']; entity = entities.get(sample.get('refers_to_entity'), {})
        context = contexts.get(sid, {})
        names = [sample.get('sample_label_raw'), sample.get('polymer_name'), context.get('agent_label')]
        # Entity aliases may intentionally map to several state samples: keep ambiguity.
        names += entity.get('source_names', []) + entity.get('aliases', [])
        for name in names:
            if isinstance(name, str) and norm(name):
                aliases[norm(name)].add(sid)
    protocols = []
    for number, original in enumerate(stage3.get('protocol_contexts', []), 1):
        protocol = deepcopy(original)
        pid = original.get('protocol_id') or original.get('id') or f'protocol_context_{number}'
        protocol['protocol_id'] = pid
        for i, step in enumerate(protocol.get('steps', []), 1):
            step['parent_protocol_id'] = pid
            step['step_number'] = i
            step['step_count'] = len(protocol['steps'])
        protocol['physical_batch_edges_inferred'] = False
        protocols.append(protocol)
    gaps = []
    for sample in samples:
        sid = sample['sample_id']; context = contexts.get(sid, {})
        if not sample.get('state_description'):
            gaps.append({'sample_id': sid, 'kind': 'state_scope_not_explicit',
                'action': 'Inspect only relevant original preparation and measurement context; do not invent a state.'})
        if context.get('raw_preparation') and not stage3.get('process_steps'):
            gaps.append({'sample_id': sid, 'kind': 'preparation_text_not_physical_graph',
                'action': 'Determine applicability and input/output only where source supports them.'})
    result = {'document_id': stage3['document_id'], 'entities': list(entities.values()),
        'samples': samples, 'identity_contexts': list(contexts.values()),
        'alias_index': {k: sorted(v) for k, v in sorted(aliases.items())},
        'protocols': protocols, 'physical_process_steps': deepcopy(stage3.get('process_steps', [])),
        'stage3_gap_tasks': gaps, 'stage3_gap_completion_status': 'not_model_completed',
        'catalogue_is_reviewed_legacy_import': bool(contexts),
        'original_machine_handoff_verified': False}
    from ownership import graph
    result['ownership_graph'] = graph(result)
    return result


def bind_sample(item, identity):
    samples = {s['sample_id']: s for s in identity['samples']}
    original = item.get('sample_id')
    if original:
        return (original, 'existing_explicit_id') if original in samples else (None, 'invalid_sample_id')
    # A supplied plural owner is not a license to distribute a series/group result.
    if item.get('sample_ids') or item.get('observation_role') == 'aggregate':
        return None, 'group_scope_preserved'
    label = item.get('sample_label_raw') or item.get('article_sample_key')
    matches = identity['alias_index'].get(norm(label), [])
    if len(matches) == 1:
        return matches[0], 'unique_existing_alias'
    return None, 'ambiguous_alias' if matches else 'owner_not_resolved'
