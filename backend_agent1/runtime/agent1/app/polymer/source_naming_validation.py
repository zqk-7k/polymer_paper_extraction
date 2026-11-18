"""Explicit source-name comparison against the complete saved identity tree.

The old descriptor namespace and old name-check default remain replayable.
This is a scoped model comparison, not preferred-IUPAC certification.
"""
from copy import deepcopy
from .common import key

CONTRACT = 'source-name-identity-attributes/1.0'
SCOPE = 'source_definition_and_reported_identity_attributes_without_composition_or_sample'


def projection(passport):
    core = passport['chemical_core']
    tree = deepcopy(core['definition_tree'])
    def without_fractions(node):
        node.pop('fractions', None)
        for child in node.get('children', []):
            without_fractions(child)
    without_fractions(tree)
    attrs = {}
    for name in ('tacticity', 'end_groups'):
        field = core.get('attributes', {}).get(name, {})
        attrs[name] = {'knowledge_status': field.get('knowledge_status'),
                       'value': deepcopy(field.get('value'))}
    return {'definition_tree': tree, 'identity_attributes': attrs}


def compare(kernel, passport, text):
    verified = kernel.dispatch('validate_passport', {'passport': passport})
    if verified.get('status') != 'PARSED':
        return {'accepted': False, 'reason_code': 'SOURCE_NAME_PASSPORT_INTEGRITY_INVALID'}
    if passport['chemical_core'].get('conflicts'):
        return {'accepted': False, 'reason_code': 'CONFLICTING_DESCRIPTION_NOT_NAMED'}
    expected = key(CONTRACT, projection(passport))
    rebuilt = kernel.dispatch('create_passport', {
        'name': text, 'interpretation_policy': 'evidence_only',
        'naming_profile': passport['naming_snapshot']['profile']})
    candidate = rebuilt.get('passport')
    observed = key(CONTRACT, projection(candidate)) if candidate else None
    accepted = bool(rebuilt.get('status') == 'PARSED' and expected == observed)
    return {'accepted': accepted, 'reason_code': None if accepted else 'IDENTITY_OR_SCOPE_MISMATCH',
            'expected_key': expected, 'observed_key': observed,
            'validation_contract': CONTRACT, 'comparison_scope': SCOPE,
            'passport_modified': False, 'preferred_iupac_asserted': False,
            'excluded_from_name_comparison': ['composition', 'repeat_count', 'number_average_molar_mass', 'sample_identity']}
