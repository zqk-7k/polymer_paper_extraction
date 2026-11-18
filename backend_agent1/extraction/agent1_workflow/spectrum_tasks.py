"""Disjoint Stage5 fields; complete prose is retained in every task."""
from copy import deepcopy
from field_groups import rendered

def partition(tasks,catalog):
    result=[]
    for task in tasks:
        buckets={'vibrational':[],'nmr':[],'other_characterization':[]}
        ids=set(task['allowed_target_ids'])
        for target in catalog['targets']:
            if target['target_id'] not in ids:continue
            key=target['property_key'].lower()
            group='nmr' if 'nmr' in key else 'vibrational' if 'ftir' in key or 'raman' in key else 'other_characterization'
            buckets[group].append(target)
        for group,targets in buckets.items():
            if not targets:continue
            t=deepcopy(task);t['task_id']='s5_'+group
            t['allowed_target_ids']=[x['target_id'] for x in targets]
            t['packet'].update(rendered(targets))
            t['packet']['task_contract'].update(group=group,allowed_target_ids=t['allowed_target_ids'])
            t['packet']['spectrum_contract']={'version':'shared_spectrum_groups.v2','flat_legacy_observations_allowed':True,
                'share_only_identical_explicit_metadata':True,'peak_values_never_generated_from_images':True}
            result.append(t)
    flattened=[x for t in result for x in t['allowed_target_ids']]
    assert len(flattened)==len(set(flattened))
    assert set(flattened)=={x for t in tasks for x in t['allowed_target_ids']}
    return result
