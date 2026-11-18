"""Spatial refinements for source tables; never infer values or cross-table identity."""
import re
from stages.standard_mapping import normalize_source_notation


def inline_temperature(text):
    return re.fullmatch(r'Tg[12]?\s*:\s*[-+]?\d+(?:\.\d+)?\s*°C', normalize_source_notation(text)) is not None


def preceding_material(cells, cell, depth):
    """Continue a material section only across recognized inline Tg labels."""
    left = sorted((c for c in cells if c['column_index'] == 0 and depth <= c['row_index'] <= cell['row_index']),
                  key=lambda c:c['row_index'], reverse=True)
    for candidate in left:
        if material_label(candidate['text']):
            return candidate
        if candidate['text'] and not inline_temperature(candidate['text']):
            return None
    return None


def material_label(text):
    text = text.strip().strip('$')
    if text.upper() in {'THF', 'DMF', 'DMSO', 'NMP', 'DMA', 'DMAc'.upper(), 'KBR', 'POLYMER', 'POLYMERS', 'SAMPLE', 'SAMPLES'}:
        return False
    return bool(re.match(r'(?:P[A-Z(\d]|poly\b|poly\(|[A-Z]{2,}(?:[-(]|$)|(?:m|p)-Phenylenediamine|Melamine|Monomer\s+\d)', text, re.I if text.lower().startswith(('poly', 'monomer', 'melamine')) else 0))


def refine_layout(cells, layout, caption=''):
    first = [c for c in cells if c['row_index'] == 0]
    second = [c for c in cells if c['row_index'] == 1]
    if not first or not second:
        return layout
    corner = min(first, key=lambda c: c['column_index'])
    # Headerless key/value tables: the first number is data, not a material label.
    width = max(c['column_index'] + c['column_span'] for c in cells)
    property_words = re.compile(r'viscosity|density|hardness|refractive|specific gravity|molecular|colour|color|strength|modulus|elongation', re.I)
    if (width == 2 and len(first) == 2 and not any(c.get('is_header') for c in first)
            and re.match(r'^[~≈+-]?\d', first[1]['text'].strip())
            and sum(bool(property_words.search(c['text'])) for c in cells if c['column_index'] == 0) >= 2
            and all(not re.match(r'^\d', c['text'].strip()) for c in cells if c['column_index'] == 0)):
        return dict(orientation='property_value_pairs', header_rows=0, basis='property_names_and_headerless_values')
    condition = re.compile(r'^(?:(?:curing|exposure|irradiation|reaction|waiting|measurement)\s+)?(?:time|temperature|frequency|wave\s*length|pressure|humidity)\b', re.I)
    if (condition.search(corner['text']) and len(first) > 1
            and all(condition.search(c['text']) for c in first if c['column_index'] > 0)):
        return dict(orientation='two_condition_axes', header_rows=max(c['row_span'] for c in first),
                    basis='two_explicit_condition_axes', unresolved_fields=['property_axis_requires_interpretation'])
    left = [c for c in cells if c['column_index'] == 0 and c['row_index'] > 0 and c['text']]
    states = [c for c in cells if c['column_index'] == 1 and c['row_index'] > 0 and c['text']]
    if (not corner['text'] and corner['column_span'] == 2 and left and states
            and any(inline_temperature(c['text']) for c in left)
            and all(material_label(c['text']) or inline_temperature(c['text']) for c in left)
            and all(re.fullmatch(r'Untreated|[A-Za-z0-9-]+ treated(?:\s*\([^)]*\))?', c['text'], re.I) for c in states)):
        return dict(orientation='material_sections_with_inline_properties', header_rows=1,
                    basis='explicit_material_inline_temperature_and_treatment_columns')
    if ([c['text'] for c in first[:2]] == ['R', "R'"] and re.search(r'Structures of.*Groups', caption, re.I)):
        return dict(orientation='structure_substituents', header_rows=1, basis='caption_and_R_group_headers')
    energy_labels = {'MMX','Str','Bnd','OOP','StrBnd','Tor','VDW','DPDP','HF','SE','μ'}
    if (not corner['text'] and len(left) >= 3 and all(c['text'] in energy_labels for c in left)
            and re.search(r'Energy Contributions', caption, re.I)
            and all(re.search(re.escape(c['text']) + r'\s*\(', caption) for c in left if c['text'] != 'μ')):
        return dict(orientation='named_property_rows_unlabeled_columns', header_rows=1,
                    basis='row_symbols_defined_in_caption', unresolved_fields=['column_conformation_label'])
    labels = [c for c in first if c['column_index'] >= corner['column_span'] and c['text']]
    groups = [c for c in first if c['text'] and material_label(c['text'])]
    if not corner['text'] and sum(c['text'].casefold() in {'chair','boat','half-chair'} for c in first)>=2:
        return dict(orientation='property_rows_with_column_conditions',header_rows=1,basis='named_conformations_and_row_properties')
    if len(groups) >= 2 and all(c['column_span'] > 1 for c in groups) and len(groups) == len([c for c in first if c['text']]):
        return dict(orientation='samples_in_column_groups', header_rows=2, basis='material_groups_above_property_headers')
    # A blank or Sample corner plus material names is the transposed sample axis.
    if (not corner['text'] or corner['text'].casefold() in {'sample', 'samples', 'da-polyester'}) and labels and all(material_label(c['text']) for c in labels):
        first_sample = min(c['column_index'] for c in labels)
        return dict(orientation='samples_in_columns', header_rows=1, property_columns=list(range(first_sample)), basis='material_names_in_column_headers')
    anchor = re.compile(r'^(?:conc\.|concentration|sample|polymer|temperature|T\s*\(K\)|f\s*\(?Hz)', re.I)
    if any(c['column_span'] > 1 for c in first) and any(anchor.search(c['text']) for c in second):
        return dict(orientation='samples_in_rows', header_rows=2, basis='group_header_with_named_second_axis')
    if layout['orientation'] == 'unknown' and (any(anchor.search(c['text']) for c in first) or
            (not corner['text'] and any(material_label(c['text']) for c in cells if c['row_index'] > 0 and c['column_index'] == 0))):
        return dict(orientation='samples_in_rows', header_rows=max(c['row_span'] for c in first), basis='named_condition_or_material_row_axis')
    return layout


def inferred_sample_columns(cells, headers, depth, explicit):
    if explicit:
        return explicit
    corner = next((h for h in headers if h['column_index'] == 0), None)
    left = [c for c in cells if c['row_index'] >= depth and c['column_index'] == 0 and c['column_span'] == 1 and c['text']]
    if corner and not corner['text'] and left and all(material_label(c['text']) for c in left):
        return {0}
    return set()


def active_material_group(cells, cell, depth, width):
    groups = [c for c in cells if depth <= c['row_index'] < cell['row_index'] and c['column_index'] == 0
              and c['column_span'] >= width and c['text']]
    if not groups:
        return None
    group = max(groups, key=lambda c: c['row_index'])
    return group if material_label(group['text']) else None
