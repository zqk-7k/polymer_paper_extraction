"""Apply explicitly bounded metadata; raw OCR values never change."""
from copy import deepcopy
import json
import re


def merge_units(candidate, incoming, *, resolved_scale=False):
    """Missing metadata cannot erase known units/scales; disagreement is visible."""
    for prefix, sentinel in (('unit_', 'unit_raw'), ('scale_factor_', 'scale_factor_raw')):
        if prefix.rstrip('_') in candidate.get('unresolved_metadata_fields', []):
            continue
        if not incoming.get(sentinel):
            continue
        old = candidate.get(sentinel)
        key = 'unit_normalized' if prefix == 'unit_' else 'scale_factor_exponent'
        agrees = old == incoming[sentinel] or (
            candidate.get(key) is not None and candidate.get(key) == incoming.get(key))
        if old and not agrees:
            candidate.setdefault('metadata_conflicts', []).append({
                'kind': prefix.rstrip('_'), 'previous': {k:v for k,v in candidate.items() if k.startswith(prefix)},
                'proposed': {k:v for k,v in incoming.items() if k.startswith(prefix)}})
            candidate.setdefault('warnings', []).append(prefix + 'conflict')
            # Explicit residual percentage distinguishes a measured unit from
            # the temperature condition embedded in the same source header.
            if prefix == 'scale_factor_' and resolved_scale and candidate.get('scale_factor_status') == 'ambiguous_display_scale':
                candidate['metadata_conflicts'][-1]['resolution'] = 'cited_footnote_disambiguates_exponent'
            elif (prefix == 'unit_' and candidate.get('semantic_label') == 'residual_mass_fraction'
                    and incoming.get('unit_normalized') == '%' and '%' in str(candidate.get('property_name_raw', ''))):
                candidate['metadata_conflicts'][-1]['resolution'] = 'explicit_residual_percentage'
            else:
                continue
        candidate.update({k:v for k,v in incoming.items() if k.startswith(prefix) and v is not None})


def apply_scoped_metadata(candidate, relations, *, append=False):
    from stages.stage4t_table_property import _unit_info
    relevant = [r for r in relations if candidate['cell_id'] in r.target_cell_ids]
    if not relevant:
        return
    canonical = lambda r: json.dumps(r.model_dump(mode='json'), sort_keys=True, ensure_ascii=False)
    relevant = [r for _, r in sorted({canonical(r): r for r in relevant}.items())]
    candidate['scoped_relations'] = ([*candidate.get('scoped_relations', [])] if append else []) + [r.model_dump(mode='json') for r in relevant]
    grouped = {}
    for relation in relevant:
        grouped.setdefault((relation.kind, relation.name), []).append(relation)
    for (kind, name), group in sorted(grouped.items(), key=str):
        relation = group[0]
        if relation.kind == 'subject':
            candidate.setdefault('subject_relations', []).extend(r.model_dump(mode='json') for r in group)
        elif relation.kind in {'unit', 'scale'}:
            prefix = 'unit_' if relation.kind == 'unit' else 'scale_factor_'
            parsed = []
            for item in group:
                expression = item.source_quote
                if item.kind == 'scale' and item.footnote_marker:
                    expression = re.sub(r'(10\s*\^\s*\{\s*[+-]?\d+)'
                        + re.escape(item.footnote_marker) + r'(\s*\})', r'\1\2', expression)
                info = {k:v for k,v in _unit_info([expression], None).items() if k.startswith(prefix)}
                parsed.append((item, expression, info))
            key = 'unit_normalized' if kind == 'unit' else 'scale_factor_exponent'
            values = {info.get(key) for _, _, info in parsed}
            if len(values) > 1:
                candidate.setdefault('metadata_conflicts', []).append({'kind': kind, 'proposals': [info for _,_,info in parsed]})
                unresolved = candidate.setdefault('unresolved_metadata_fields', [])
                if prefix.rstrip('_') not in unresolved:
                    unresolved.append(prefix.rstrip('_'))
                for field in list(candidate):
                    if field.startswith(prefix):
                        candidate.pop(field)
                candidate[prefix + 'status'] = 'unresolved'
                candidate.setdefault('warnings', []).append(prefix + 'conflict')
                continue
            item, expression, info = parsed[0]
            if kind == 'scale' and item.footnote_marker:
                candidate['scale_expression_interpreted'] = expression
            merge_units(candidate, info, resolved_scale=kind == 'scale' and bool(item.footnote_marker))
        elif relation.kind == 'condition':
            conditions = candidate.setdefault('conditions', {})
            values = {r.source_quote for r in group}
            if name in conditions:
                values.add(str(conditions[name]))
            field = 'condition:' + str(name)
            if len(values) > 1 or field in candidate.get('unresolved_metadata_fields', []):
                candidate.setdefault('metadata_conflicts', []).append({'kind': kind, 'name': name, 'proposals': sorted(values)})
                conditions.pop(name, None)
                unresolved = candidate.setdefault('unresolved_metadata_fields', [])
                if field not in unresolved:
                    unresolved.append(field)
            else:
                conditions[name] = relation.source_quote
        elif relation.kind == 'measurement_role':
            previous = candidate.get('measurement_role', 'reported_unknown')
            values = {r.measurement_role for r in group}
            if previous not in {None, 'reported_unknown'}:
                values.add(previous)
            if len(values) > 1:
                candidate.setdefault('metadata_conflicts', []).append({
                    'kind': 'measurement_role', 'proposals': sorted(values)})
                candidate['measurement_role'] = 'reported_unknown'
            elif not any(c.get('kind') == 'measurement_role' for c in candidate.get('metadata_conflicts', [])):
                candidate['measurement_role'] = relation.measurement_role
