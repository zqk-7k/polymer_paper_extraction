"""Opt-in supplied-graph contract. Never derive a product from a source name."""
from copy import deepcopy
from .periodic import canonicalize_unit

CONTRACT = 'supplied-repeat-constitution/1.0'

def validate(value):
    if not isinstance(value, dict) or value.get('contract') != CONTRACT:
        raise ValueError('SUPPLIED_CONSTITUTION_CONTRACT_REQUIRED')
    if value.get('scope') != 'repeat_unit' or value.get('coverage') != 'ideal_repeat':
        raise ValueError('SUPPLIED_WHOLE_REPEAT_SCOPE_REQUIRED')
    if not isinstance(value.get('source_refs'), list) or not value['source_refs']:
        raise ValueError('SUPPLIED_CONSTITUTION_SOURCE_REQUIRED')
    if not isinstance(value.get('graph_id'), str) or not value['graph_id']:
        raise ValueError('SUPPLIED_CONSTITUTION_GRAPH_ID_REQUIRED')
    periodic = canonicalize_unit(value.get('smiles'))
    return {'contract': CONTRACT, 'supplied': deepcopy(value), 'periodic': periodic,
            'scope': 'supplied_ideal_repeat_not_actual_material',
            'actual_product_verified': False, 'independent_review': 'NOT_REVIEWED'}
