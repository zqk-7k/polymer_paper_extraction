"""Explicit relation direction; never infer a reaction from generic from/to fields."""
CONTRACT = 'identity-relations/1.0'
TYPES = {'precursor_to_product','sample_state_of','physical_blend_component','graft_backbone_of',
         'graft_sidechain_of','source_of','derived_from','processed_from','comparison','series_members'}


def relation_errors(candidate, refs):
    if candidate.get('relation_policy') != CONTRACT: return []
    errors = []; materials = candidate.get('materials',{})
    relations = list(candidate.get('relations',[]))
    for m in materials.values(): relations.extend(m.get('relationships',[]))
    for i, r in enumerate(relations):
        kind = r.get('type') or r.get('relation'); prefix = 'RELATION_'+str(i)+':'
        from .adoption import CURRENT_POLICY, SOURCE_POLICY
        supported=TYPES|({'formulation_component'} if candidate.get('adoption_policy') in (SOURCE_POLICY, CURRENT_POLICY) else set())
        if kind not in supported: errors.append(prefix+'EXPLICIT_TYPE_REQUIRED'); continue
        ids = r.get('material_ids',[]) if kind in ('comparison','series_members') else [r.get('from_material_id'),r.get('to_material_id')]
        if len(ids) < 2 or len(set(ids)) != len(ids) or any(mid not in materials for mid in ids): errors.append(prefix+'MATERIAL_BINDING_REQUIRED')
        if not r.get('source_refs') or not set(r['source_refs']).issubset(refs) or not r.get('reason'): errors.append(prefix+'SOURCE_REASON_REQUIRED')
        if r.get('evidence_basis') not in ('source_supported','most_likely_hypothesis'): errors.append(prefix+'EVIDENCE_BASIS_REQUIRED')
        if r.get('evidence_basis') == 'most_likely_hypothesis' and not r.get('assumptions'): errors.append(prefix+'HYPOTHESIS_REQUIRED')
        target = materials.get(r.get('to_material_id'),{})
        if kind=='formulation_component' and (target.get('structure_expression',{}).get('kind')!='assembly' or
                not any(c.get('material_id')==r.get('from_material_id') for c in target.get('components',[]))):
            errors.append(prefix+'PHYSICAL_FORMULATION_ASSEMBLY_BINDING_REQUIRED')
        if kind == 'physical_blend_component' and target.get('kind') != 'blend': errors.append(prefix+'BLEND_TARGET_REQUIRED')
        if kind == 'precursor_to_product' and not r.get('connection_change'): errors.append(prefix+'CHEMICAL_CHANGE_REQUIRED')
    return errors
