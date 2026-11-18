"""Semantic prose groups, complete tables and compact shared identities."""
import json
import re
from common import config


def compact_identity(identity):
    contexts = {x.get('sample_id'): x for x in identity.get('identity_contexts', [])}
    return {'samples': [{'sample_id': s['sample_id'], 'entity_id': s.get('refers_to_entity'),
        'label': s.get('sample_label_raw'), 'name': s.get('polymer_name'),
        'state': s.get('state_description'), 'parent_sample_id': s.get('parent_sample_id'),
        'composition_axis': contexts.get(s['sample_id'], {}).get('composition_axis'),
        'agent_id':contexts.get(s['sample_id'],{}).get('agent_id'),
        'identity_key':contexts.get(s['sample_id'],{}).get('identity_key'),
        'directory_source_status':contexts.get(s['sample_id'],{}).get('identity_source_status'),
        'directory_composition_raw':contexts.get(s['sample_id'],{}).get('raw_composition'),
        'category':contexts.get(s['sample_id'],{}).get('agent1_category') or s.get('agent1_category'),
        'agent_role':contexts.get(s['sample_id'],{}).get('agent1_role'),
        'derived_from':contexts.get(s['sample_id'],{}).get('derived_from')}
        for s in identity['samples']], 'aliases': identity['alias_index'],
        'materials':[{'entity_id':e['entity_id'],'name':e.get('polymer_name'),
            'polymer_type':e.get('polymer_type'),'agent1_category':e.get('agent1_category'),
            'source_names':e.get('source_names',[]),'member_sample_ids':e['member_sample_ids']}
            for e in (identity.get('ownership_graph') or __import__('ownership').graph(identity))['entities']],
        'owner_scope_policy':'Use material scope with an existing entity_id for a material fact whose physical state is not specified. Keep conditions. Associations are not member measurements. Distinct chemical entities remain separate. Polymer networks and restructured products are distinct chemical subjects chemically derived from their base polymer, not physical states of it.',
        'protocols': [{'protocol_id': p.get('protocol_id'), 'scope_raw': p.get('scope_raw') or p.get('scope'),
            'scope_evidence_ref':{'source_block_id':p.get('scope_source_block_id'),'quote':p.get('scope_quote')},
            'applicable_sample_ids': p.get('applicable_sample_ids', []),
            'steps': [{'step_number': t.get('step_number'), 'process_type': t.get('process_type'),
                'parameters_raw': t.get('parameters_raw') or t.get('parameters'),
                'evidence_ref':{'source_block_id':t.get('source_block_id'),'quote':t.get('quote')}} for t in p.get('steps', [])]}
            for p in identity.get('protocols', [])]}


def compact_targets(catalog, stage):
    targets = (list(catalog['targets']) if stage=='stage4t' else
        [t for t in catalog['targets'] if (t['section'] == 'stage5_property_vocabulary') == (stage == 'stage5')])
    return [{'target_id': t['target_id'], 'key': t['property_key'],
             'aliases': t['aliases'], 'methods': t.get('methods', []),
             'subtype_required': t.get('subtype_required', False)} for t in targets]


def prose_groups(stage0):
    groups = []; current = []; chars = 0; section = None
    for block in stage0['elements']:
        if block.get('type') not in ('text', 'paragraph'): continue
        text = block.get('text') or ''
        # References remain accounted for, but bibliography entries are not claims.
        if str(block.get('section','')).casefold() in ('references','bibliography'): continue
        record = {'block_id': block['block_id'], 'section': block.get('section'), 'text': text}
        new_section = block.get('section')
        if current and (new_section != section or chars + len(text) > config()['prose_group_chars']):
            groups.append(current);current=[];chars=0
        current.append(record);chars+=len(text);section=new_section
    if current: groups.append(current)
    return groups


def shared_methods(stage0):
    return [{'block_id': b['block_id'], 'text': b.get('text','')} for b in stage0['elements']
            if b.get('type') in ('text','paragraph') and b.get('section') == 'Methods']


def stage3_packet(stage0, identity):
    # Whole prose is modest for the three fixed articles; never silently truncate.
    return {'document_id': stage0['document_id'], 'base_directory': compact_identity(identity),
        'gap_tasks': identity['stage3_gap_tasks'],
        'source_blocks': [b for group in prose_groups(stage0) for b in group],
        'existing_process_steps': identity.get('physical_process_steps', []),
        'imported_preparation_hints':[{'sample_id':c['sample_id'],
            'raw_preparation':c.get('raw_preparation'),'raw_composition':c.get('raw_composition'),
            'source_kind':'agent1_directory_hint_requires_original_text_confirmation'}
            for c in identity.get('identity_contexts',[])],
        'scope': 'Fill missing explicit state and protocol associations; leave unreported gaps unresolved.'}


def extraction_packets(stage0, identity, catalog):
    groups = prose_groups(stage0); methods = shared_methods(stage0)
    common = {'document_id': stage0['document_id'], 'identity_directory': compact_identity(identity)}
    n_tasks=[];t_tasks=[];s5_tasks=[]
    for i, group in enumerate(groups):
        context = []
        if i: context.append(groups[i-1][-1])
        if i+1<len(groups):context.append(groups[i+1][0])
        packet = {**common, 'target_fields': compact_targets(catalog,'stage4n'),
            'owned_blocks': group, 'context_blocks': context, 'shared_methods': methods}
        n_tasks.append({'task_id': f'n_{i+1:03d}', 'packet': packet,
            'owned_source_ids': [b['block_id'] for b in group]})
    for i,b in enumerate(stage0['elements']):
        if b.get('type') != 'table':continue
        nearby=[{'block_id': x['block_id'],'text': x.get('text','')} for x in stage0['elements'][max(0,i-3):i+5]
            if x.get('type') in ('text','paragraph')]
        packet={**common,'target_fields':compact_targets(catalog,'stage4t'),
            'table':{'table_id':b['block_id'],'caption':b.get('caption'),
                     'cells':b.get('table_cells',[]),'notes':b.get('table_notes',[])},
            'related_blocks':nearby,'shared_methods':methods}
        t_tasks.append({'task_id':f't2_{len(t_tasks)+1:03d}','packet':packet,'owned_source_ids':[b['block_id']]})
    # Characterization targets are evaluated over every prose group too: methods-only
    # routing would miss explicit peaks in synthesis/results. Separate scope avoids re-extraction.
    for task in n_tasks:
        packet={**task['packet'],'target_fields':compact_targets(catalog,'stage5')}
        s5_tasks.append({'task_id':task['task_id'].replace('n_','s5_'),'packet':packet,
                        'owned_source_ids':task['owned_source_ids']})
    return n_tasks,t_tasks,s5_tasks
