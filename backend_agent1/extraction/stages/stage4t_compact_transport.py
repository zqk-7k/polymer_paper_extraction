"""Lossless request encoding: individual cell aliases, never positional scopes."""
from copy import deepcopy
import json

TRANSPORT_VERSION = 'stage4t_compact_transport.v1'
_REFERENCE_FIELDS = {'cell_id', 'source_id', 'source_cell_ids', 'target_cell_ids', 'source_refs', 'cell_ids', 'exclude_cell_ids'}


def _map_references(value, mapping, field=None):
    if isinstance(value, dict):
        return {k: _map_references(v, mapping, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_map_references(v, mapping, field) for v in value]
    if isinstance(value, str) and field in _REFERENCE_FIELDS:
        return mapping.get(value, value)
    return deepcopy(value)


def compact_input(payload):
    """Return wire input and local-only map; preserve all cells and candidates."""
    ids = [c['cell_id'] for c in payload.get('cells', [])]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate input cell IDs')
    mapping = {f'c{i}': cell_id for i, cell_id in enumerate(ids)}
    other_source_ids = {s['source_id'] for s in payload.get('sources', [])}
    if set(mapping).intersection(set(ids) | other_source_ids):
        raise ValueError('cell alias collides with original ID')
    wire = _map_references(payload, {v: k for k, v in mapping.items()})
    # Intern only repeated whole evidence/process objects; never merge samples
    # or infer equality of their state, targets, or semantic relationships.
    objects = []
    def collect(value, field=None):
        if isinstance(value, dict):
            if field == 'evidence':
                objects.append(value)
            elif field == 'processes':
                objects.append(value)
            for k, v in value.items():
                collect(v, k)
        elif isinstance(value, list):
            for v in value:
                collect(v, field)
    collect(wire.get('subject_catalog', {}))
    key = lambda obj: json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    counts = {}
    originals = {}
    for obj in objects:
        canonical = key(obj)
        counts[canonical] = counts.get(canonical, 0) + 1
        originals[canonical] = obj
    registry = {canonical: f'd{i}' for i, canonical in enumerate(
        canonical for canonical in counts if counts[canonical] > 1 and len(canonical) > 100)}
    definitions = {ref: deepcopy(originals[canonical]) for canonical, ref in registry.items()}
    def intern(value, field=None):
        if isinstance(value, dict):
            canonical = key(value) if field in {'evidence', 'processes'} else None
            if canonical in registry:
                return {'$ref': registry[canonical]}
            return {k: intern(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [intern(v, field) for v in value]
        return deepcopy(value)
    if 'subject_catalog' in wire:
        wire['subject_catalog'] = intern(wire['subject_catalog'])
    wire['transport'] = {
        'version': TRANSPORT_VERSION,
        'cell_id_policy': 'Each cN denotes one individual cell, never a range. Use these exact IDs in references. No shared-subject or condition inheritance.',
        'definition_policy': 'A {$ref:dN} object is exactly the object in definitions[dN]; reuse its full evidence/process content. All sample candidates remain separate.',
        'definitions': definitions,
    }
    return wire, mapping


def restore_input(wire, mapping):
    """Engineering round-trip helper; not an extraction or correctness evaluator."""
    data = deepcopy(wire)
    definitions = data.pop('transport')['definitions']
    def expand(value):
        if isinstance(value, dict):
            if set(value) == {'$ref'}:
                return deepcopy(definitions[value['$ref']])
            return {k: expand(v) for k, v in value.items()}
        if isinstance(value, list):
            return [expand(v) for v in value]
        return value
    return _map_references(expand(data), mapping)


def restore_response(data, mapping):
    """Restore IDs only; unknown IDs remain unknown for node-local validation."""
    return _map_references(data, mapping)
