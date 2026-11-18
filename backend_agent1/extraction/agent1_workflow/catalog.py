"""One target directory; no numerical normalization or answer data."""
import re
import unicodedata


SECTIONS = ('property_vocabulary', 'stage5_property_vocabulary', 'specialized_property_vocabulary')


def norm(value):
    text = unicodedata.normalize('NFKC', str(value or '')).casefold()
    return re.sub(r'\s+', ' ', text.replace('_', ' ')).strip()


def build_catalog(schema):
    targets = []
    for section in SECTIONS:
        for key, definition in schema[section].items():
            info = definition if isinstance(definition, dict) else {}
            target_id = section + ':' + key
            # Exact intrinsic viscosity reroutes, but inherent viscosity remains a subtype.
            canonical = ('specialized_property_vocabulary:solution_viscosity'
                         if key == 'intrinsic_viscosity' else target_id)
            targets.append({'target_id': target_id, 'property_key': key,
                'section': section, 'canonical_target_id': canonical,
                'aliases': sorted({key, key.replace('_', ' '), *info.get('aliases', [])}),
                'definition': definition, 'source_field': info.get('source_field'),
                'value_kinds': info.get('value_kinds', ['raw_value']),
                'methods': info.get('methods', []),
                'subtype_required': key in ('molecular_weight', 'solution_viscosity',
                                           'thermal_decomposition_temperature'),
                'owner_policy': 'existing_sample_or_explicit_material_or_series_scope'})
    return {'version': 'unified_targets.1020.v1', 'targets': targets,
        'configured_field_count': len(targets),
        'section_counts': {s: len(schema[s]) for s in SECTIONS},
        'relationships': [
            {'left': 'property_vocabulary:intrinsic_viscosity',
             'right': 'specialized_property_vocabulary:solution_viscosity',
             'kind': 'exact_intrinsic_subtype_reroute'},
            {'left': 'stage5_property_vocabulary:xrd_diffraction_peak_2theta',
             'right': 'specialized_property_vocabulary:two_theta',
             'kind': 'related_requires_same_method_source_and_context'},
            {'left': 'stage5_property_vocabulary:xrd_crystallinity',
             'right': 'specialized_property_vocabulary:crystallinity',
             'kind': 'method_specific_subtype_not_blindly_merged'},
            {'left': 'property_vocabulary:thermal_decomposition_weight_loss',
             'right': 'property_vocabulary:thermal_decomposition_temperature',
             'kind': 'threshold_relation_not_duplicate'}],
        'field_count_is_not_distinct_scientific_property_count': True}


def resolve_target(item, catalog):
    """Use explicit existing keys first. Raw aliases require a unique exact match."""
    targets = catalog['targets']
    for field in ('specialized_property_key', 'semantic_label', 'property_name_normalized'):
        value = item.get(field)
        if not value:
            continue
        matched = [t for t in targets if t['property_key'] == value]
        if len(matched) == 1:
            t = matched[0]
            return t['canonical_target_id'], t['target_id'], field
    field = item.get('source_field')
    matched = [t for t in targets if field and t['source_field'] == field]
    if len(matched) == 1:
        t = matched[0]
        return t['canonical_target_id'], t['target_id'], 'source_field'
    name = norm(item.get('property_name_raw'))
    matched = [t for t in targets if name and name in {norm(a) for a in t['aliases']}]
    ids = {t['canonical_target_id'] for t in matched}
    if len(ids) == 1:
        return next(iter(ids)), matched[0]['target_id'], 'exact_source_alias'
    return None, None, 'unmapped_or_ambiguous'
