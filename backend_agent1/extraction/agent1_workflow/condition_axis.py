"""Resolve explicit header conditions by geometry, never by measurement values."""
from copy import deepcopy
from table_reader import interpret as legacy_interpret, matches, condition_family


def interpret(table, response, target_ids, sample_ids):
    clean = deepcopy(response)
    # The existing matrix paths already validate solvent/frequency labels,
    # including row-label axes whose applies_to axis is orthogonal. Preserve
    # those semantics rather than tightening an unrelated contract this round.
    def new_header(a):
        return a.get('value_location') == 'header' and condition_family(a.get('name_raw')) not in ('solvent', 'frequency')
    headers = [a for a in clean['condition_axes'] if new_header(a)]
    clean['condition_axes'] = [a for a in clean['condition_axes'] if not new_header(a)]
    rows, audit = legacy_interpret(table, clean, target_ids, sample_ids)
    cells = {c['cell_id']: c for c in table['cells']}
    resolved = []; issues = []
    for number, axis in enumerate(headers):
        scope = axis.get('applies_to', {})
        direction = scope.get('axis')
        indices = scope.get('indices', [])
        refs = axis.get('source_cell_ids', [])
        valid = (direction in ('row', 'column') and indices and refs
                 and all(r in cells for r in refs))
        coordinate = 'column_index' if direction == 'column' else 'row_index'
        span = 'column_span' if direction == 'column' else 'row_span'
        labels = {}
        if valid:
            sources = [cells[r] for r in refs]
            covered = {i for c in sources for i in range(c[coordinate], c[coordinate] + c.get(span, 1))}
            valid = covered == set(indices) and all(
                not any(matches(s, c) for s in response['subject_axes']) for c in sources)
            for index in indices:
                found = {c['cell_id']: c for c in sources
                         if c[coordinate] <= index < c[coordinate] + c.get(span, 1)}
                if len(found) != 1:
                    valid = False; break
                labels[index] = next(iter(found.values()))
        if not valid:
            issues.append({'reason': 'header_condition_scope_or_source_not_unique', 'axis': axis})
        for row in rows:
            cell = cells[row['source_cell_id']]
            if direction in ('row', 'column') and not matches(scope, cell):
                continue
            if not valid:
                row.setdefault('condition_contract_issues', []).append('header_condition_scope_or_source_not_unique')
                continue
            source = labels[cell[coordinate]]
            # A header must precede the result along the orthogonal dimension.
            precedes = (source['row_index'] + source.get('row_span', 1) <= cell['row_index']
                        if direction == 'column' else
                        source['column_index'] + source.get('column_span', 1) <= cell['column_index'])
            if not precedes or source['cell_id'] == cell['cell_id']:
                row.setdefault('condition_contract_issues', []).append('header_condition_overlaps_measurement')
                continue
            condition = {'name_raw': axis.get('name_raw'), 'value_raw': source['text'],
                         'unit_raw': axis.get('unit_raw'), 'source_cell_ids': [source['cell_id']]}
            row.setdefault('conditions', []).append(condition)
            resolved.append({'measurement_cell_id': cell['cell_id'], 'condition_axis_index': number,
                             'source_cell_id': source['cell_id'], 'value_raw': source['text'],
                             'declared_axis': axis.get('axis'), 'effective_axis': direction,
                             'basis': 'explicit_header_location_scope_and_unique_original_geometry'})
    # Keep header cells as headers in the ledger, even though their axes were
    # removed from the legacy data-column lookup. Never publish them as results.
    header_ids = {r for a in headers for r in a.get('source_cell_ids', [])}
    rows = [r for r in rows if r['source_cell_id'] not in header_ids or r.get('declared_fact_recovery')]
    for item in audit['cell_ledger']:
        if item['cell_id'] in header_ids and item['status']!='referenced_property_cell_retained_needs_review':
            item['status'] = 'declared_header_or_subject_axis'
            item.pop('candidate_count', None)
    audit['issues'].extend(issues)
    audit['header_condition_resolution'] = resolved
    audit['condition_axis_policy'] = 'explicit_header_geometry.v1'
    return rows, audit
