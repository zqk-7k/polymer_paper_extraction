"""Opt-in component target integrity; never infer or repair chemical identity."""

CONTRACT = 'identity-material-references/1.0'
FIELD = 'material_reference_policy'
TARGET_FIELDS = ('material_id', 'source_molecule_material_id')


def errors(candidate, expected_policy=None):
    policy = candidate.get(FIELD)
    out = []
    if expected_policy is not None and policy != expected_policy:
        out.append('MATERIAL_REFERENCE_POLICY_REQUIRED')
    if policy is None and expected_policy is None:
        return out  # Replay historical candidates using their original contract.
    if policy != CONTRACT or expected_policy not in (None, CONTRACT):
        out.append('MATERIAL_REFERENCE_POLICY_UNSUPPORTED')
        return out
    materials = candidate.get('materials', {})
    for owner, material in materials.items():
        components = material.get('components', [])
        if not isinstance(components, list):
            out.append('MATERIAL_COMPONENT_LIST_REQUIRED:' + owner)
            continue
        for position, use in enumerate(components):
            location = owner + ':' + str(position)
            if not isinstance(use, dict):
                out.append('MATERIAL_COMPONENT_OBJECT_REQUIRED:' + location)
                continue
            for field in TARGET_FIELDS:
                if field not in use:
                    continue  # A source fragment can deliberately have no material ID.
                target = use[field]
                if not isinstance(target, str) or not target.strip():
                    out.append('MATERIAL_COMPONENT_TARGET_INVALID:' + location + ':' + field)
                elif target not in materials:
                    out.append('MATERIAL_COMPONENT_TARGET_NOT_FOUND:' + location + ':' + field + ':' + target)
    return out
