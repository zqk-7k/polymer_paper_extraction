"""Isolated raw-result merger. No model, numerical parser, conversion, or fuzzy merge."""
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
import re
from catalog import resolve_target
from identity import bind_sample


def key(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def evidence_list(value):
    return [deepcopy(x) for x in (value if isinstance(value, list) else [value]) if isinstance(x, dict)]


def source_index(stage0):
    blocks = {b['block_id']: b for b in stage0['elements']}
    cells = {c['cell_id']: {**c, 'table_id': b['block_id']} for b in stage0['elements']
             if b.get('type') == 'table' for c in b.get('table_cells', [])}
    return blocks, cells


def expressions(document, origin):
    for collection in ('properties', 'unresolved_properties', 'specialized_property_observations'):
        for i, item in enumerate(document.get(collection, [])):
            yield deepcopy(item), f'{origin}:{collection}:{i}', {}
    for i, series in enumerate(document.get('property_series', [])):
        parent = {k: deepcopy(v) for k, v in series.items() if k != 'points'}
        for j, point in enumerate(series.get('points', [])):
            item = deepcopy(parent); item.update(deepcopy(point))
            for field in ('sample_id', 'entity_id', 'property_name_raw', 'property_name_normalized',
                          'specialized_property_key', 'unit_raw', 'measurement_context',
                          'determination_method_raw'):
                if point.get(field) is None:
                    item[field] = deepcopy(parent.get(field))
            # A series' evidence may reference every point. It supports inherited
            # metadata, not each point's value/owner. Prefer the point locator.
            point_evidence = evidence_list(point.get('evidence'))
            item['evidence'] = point_evidence or evidence_list(parent.get('evidence'))
            yield item, f'{origin}:property_series:{i}:points:{j}', {
                'unit': 'series_parent' if point.get('unit_raw') is None and parent.get('unit_raw') else 'point',
                'series_id': parent.get('series_id'),
                'unit_source_evidence': evidence_list(parent.get('evidence')) if point.get('unit_raw') is None else []}


def table_expressions(sidecar):
    """Preserve every source layer. Deduplication occurs later and is audited."""
    for table in sidecar.get('tables', []):
        for collection in ('shadow_observations', 'llm_enriched_observations', 'observations'):
            for i, original in enumerate(table.get(collection, [])):
                item = deepcopy(original)
                locator = deepcopy(item.get('evidence_locator') or {})
                locator.update({k: item[k] for k in ('table_id', 'cell_id') if item.get(k)})
                item['evidence'] = [{'block_id': table['table_id'], 'source_type': 'table',
                                     'table_locator': locator, 'source_sentence': item.get('value_raw')}]
                item['variant'] = item.get('property_variant')
                item['measurement_context'] = deepcopy(item.get('conditions') or {})
                yield item, f'stage4t:{table["table_id"]}:{collection}:{i}', {}


def raw_context(item):
    context = deepcopy(item.get('measurement_context') or item.get('conditions') or {})
    # Numeric fields already present in legacy metadata are not numerical conversions
    # performed here. Preserve only the explicitly raw view and its evidence.
    for field, value in list(context.items()):
        if isinstance(value, dict) and 'raw' in value:
            context[field] = {k: v for k, v in value.items() if k in ('raw', 'evidence', 'evidence_ids')}
    return context


def _literal(text):
    """Only typography for evidence matching; never use this string as output value."""
    return re.sub(r'[\s${}\\]', '', str(text))


def _text_contains_raw_value(value, text):
    needle, haystack = _literal(value), _literal(text)
    if not needle:
        return False
    # Evidence matching only, no conversion. A scalar fragment inside a longer
    # signed/decimal number is not literal support for that reported scalar.
    if re.fullmatch(r'[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?', needle):
        return bool(re.search(r'(?<![\d.+-])' + re.escape(needle) + r'(?![\d.])', haystack))
    return needle in haystack


def _source_support(item, blocks, cells):
    value = item.get('value_raw')
    valid = []; missing = []; literals = []
    for evidence in evidence_list(item.get('evidence')):
        locator = evidence.get('table_locator') or {}
        cid = locator.get('cell_id') or evidence.get('cell_id')
        bid = evidence.get('block_id') or locator.get('table_id')
        if cid:
            if cid not in cells:
                missing.append(cid); continue
            valid.append({'cell_id': cid, 'block_id': cells[cid]['table_id'], 'kind': 'table',
                          'source_value_raw': cells[cid]['text']})
            if value is not None and _literal(value) and _literal(value) == _literal(cells[cid]['text']):
                literals.append(cid)
        elif bid in blocks:
            block = blocks[bid]; kind = block.get('type')
            text = block.get('text') or ''
            valid.append({'block_id': bid, 'kind': kind})
            if kind not in ('image', 'figure', 'table') and value is not None and _text_contains_raw_value(value, text):
                literals.append(bid)
        elif bid:
            missing.append(bid)
    return valid, sorted(set(literals)), sorted(set(missing))


def role(item):
    semantics = item.get('value_semantics') or {}
    source = (item.get('value_derivation') or {}).get('source_semantics') or {}
    declared = semantics.get('value_role') or item.get('measurement_role') or 'unknown'
    if declared == 'experimental':
        declared = 'measured'
    sourced = source.get('source_role', 'unknown')
    # Historical source-scoped roles are evidence metadata, not computed actual_values.
    sources = source.get('role_sources') or semantics.get('footnote_links') or []
    if sourced in ('calculated', 'predicted', 'measured', 'reference') and sources:
        return sourced, 'legacy_source_scoped_interpretation', deepcopy(sources)
    if declared in ('calculated', 'predicted', 'measured', 'reference', 'difference', 'ratio', 'structural_parameter', 'reported_fact'):
        return declared, 'legacy_declared_role_not_independently_reviewed', deepcopy(sources)
    return 'unknown', 'not_confirmed', []


def header_role(support, cells):
    """Only literal role words in source headers spatially covering a value cell."""
    found = set(); proof = []
    for source in support:
        cid = source.get('cell_id')
        if cid not in cells: continue
        cell = cells[cid]
        for header in cells.values():
            if header['table_id'] != cell['table_id'] or header['row_index'] >= cell['row_index']:
                continue
            if not (header['column_index'] <= cell['column_index'] < header['column_index'] + header.get('column_span', 1)):
                continue
            # Header role words must be the whole cell or a parenthesized suffix;
            # free prose in preceding data rows is never a role declaration.
            text = re.sub(r'[$\\{}]', '', str(header['text'])).strip()
            match = re.search(r'(?i)(?:^|\()(cal(?:cd?|culated)?\.?|predicted|exp\.?|experimental|found|measured)(?:\)|$)', text)
            if match:
                word = match[1].casefold().rstrip('.')
                found.add('calculated' if word.startswith('cal') else 'predicted' if word == 'predicted' else 'measured')
                proof.append({'cell_id': header['cell_id'], 'text_raw': header['text'], 'target_cell_id': cid})
    return (next(iter(found)), proof) if len(found) == 1 else (None, proof)


def make_record(item, ref, inherited, catalog, identity, blocks, cells):
    target, original_target, basis = resolve_target(item, catalog)
    sid, binding = bind_sample(item, identity)
    sample = next((s for s in identity['samples'] if s['sample_id'] == sid), {})
    support, literal_refs, missing = _source_support(item, blocks, cells)
    value_role, role_basis, role_sources = role(item)
    source_role, header_proof = header_role(support, cells)
    if source_role:
        value_role, role_basis, role_sources = source_role, 'literal_scoped_source_header', header_proof
    reasons = []; status = 'adopted'
    if item.get('value_raw') is None or item.get('value_raw') == '': reasons.append('missing_raw_value')
    if not target: reasons.append('target_unmapped_or_ambiguous')
    if not sid: reasons.append(binding)
    if missing: reasons.append('invalid_source_reference')
    if not literal_refs: reasons.append('literal_source_support_not_verified')
    if value_role == 'unknown': reasons.append('measurement_role_not_confirmed')
    if item.get('observation_role') == 'aggregate': reasons.append('aggregate_scope_requires_confirmation')
    if item.get('metadata_conflicts') or (item.get('candidate_trace') or {}).get('stage4t_relations', {}).get('metadata_conflicts'):
        reasons.append('legacy_metadata_conflict')
    if reasons: status = 'needs_review'
    has_figure = bool(support) and all(x['kind'] in ('image', 'figure') for x in support)
    if has_figure:
        status = 'out_of_scope'; reasons = ['image_data_excluded']
    if value_role in ('calculated', 'predicted', 'reference'):
        if role_sources and literal_refs:
            status = 'out_of_scope'; reasons = [value_role + '_excluded']
        else:
            status = 'needs_review'
            reasons.append('role_exclusion_requires_source_evidence')
    subtype = item.get('molecular_weight_type') or item.get('variant') or item.get('property_variant')
    context = raw_context(item)
    return {'record_id': 'r_' + hashlib.sha256(ref.encode()).hexdigest()[:20],
        'expression_refs': [ref], 'document_id': identity['document_id'],
        'sample_id': sid, 'entity_id': sample.get('refers_to_entity') or item.get('entity_id'),
        'owner_scope': 'sample' if sid else 'group' if binding == 'group_scope_preserved' else 'unresolved',
        'article_sample_label_raw': item.get('sample_label_raw') or item.get('article_sample_key'),
        'binding_basis': binding, 'target_id': target, 'original_target_id': original_target,
        'target_basis': basis, 'property_name_raw': item.get('property_name_raw'),
        'subtype_raw': subtype, 'value_raw': deepcopy(item.get('value_raw')),
        'unit_raw': item.get('unit_raw'), 'unit_inheritance': inherited.get('unit', 'direct'),
        'unit_inheritance_evidence': inherited.get('unit_source_evidence', []),
        'conditions_raw': context, 'method_raw': item.get('determination_method_raw') or item.get('method_raw'),
        'spectral_assignment_raw': item.get('spectral_assignment'),
        'value_role': value_role, 'role_basis': role_basis, 'role_sources': role_sources,
        'scale_evidence_raw': deepcopy((item.get('value_semantics') or {}).get('scale')),
        'qualifiers_raw': deepcopy((item.get('value_semantics') or {}).get('qualifiers_raw', [])),
        'evidence': evidence_list(item.get('evidence')), 'source_support': support,
        'verified_literal_source_refs': literal_refs, 'invalid_source_refs': missing,
        'status': status, 'reasons': reasons, 'format_conversion_status': 'not_run',
        'model_quality_review_status': 'not_run', 'original_expression_preserved_by_ref': True}


def reconcile(records):
    """Merge exact-context, exact raw source expressions only; preserve contradictions."""
    groups = {}; result = []; ledger = []
    for original in records:
        row = deepcopy(original)
        source_refs = sorted({x.get('cell_id') or x.get('block_id') for x in row['source_support']})
        signature = key([row['sample_id'], row['entity_id'], row['owner_scope'], row['target_id'],
            row['subtype_raw'], row['property_name_raw'] if not row['target_id'] else None,
            row['value_raw'], row['unit_raw'], row['conditions_raw'], row['method_raw'],
            row['spectral_assignment_raw'], row['value_role'], row['status'], row['reasons'], source_refs,
            row.get('owner_resolution',{}).get('associated_sample_ids'),row.get('series_applicability')])
        # Unlocated records must never merge by coincidence.
        if source_refs and signature in groups:
            existing = groups[signature]
            existing['expression_refs'] += row['expression_refs']
            known = {key(e) for e in existing['evidence']}
            existing['evidence'] += [e for e in row['evidence'] if key(e) not in known]
            supplemental=existing.setdefault('supplementary_reviews',[])
            known_reviews={key(x) for x in supplemental}
            supplemental.extend(x for x in row.get('supplementary_reviews',[]) if key(x) not in known_reviews)
            if supplemental:existing['supplementary_status']='needs_review'
            ledger += [{'expression_ref': ref, 'record_id': existing['record_id'], 'action': 'exact_duplicate_merged'}
                       for ref in row['expression_refs']]
        else:
            groups[signature] = row; result.append(row)
            ledger += [{'expression_ref': ref, 'record_id': row['record_id'], 'action': row['status']}
                       for ref in row['expression_refs']]
    by_cell = defaultdict(list)
    for row in result:
        if not row['target_id']: continue
        for source in row['source_support']:
            if source.get('cell_id') in row['verified_literal_source_refs']:
                by_cell[source['cell_id']].append(row)
    conflicts = []
    for cid, rows in by_cell.items():
        # A cell may encode several properties; retain alternatives rather than deciding.
        owners = {r['sample_id'] for r in rows if r['sample_id']}
        chemical_owners = {r['entity_id'] for r in rows if r.get('entity_id')}
        targets = {r['target_id'] for r in rows if r['target_id']}
        # Missing metadata is not a contradictory alternative. Distinct explicit
        # owners/targets at the same source cell require review, without choosing.
        if len(owners) > 1 or len(chemical_owners) > 1 or len(targets) > 1:
            conflicts.append({'cell_id': cid, 'record_ids': sorted({r['record_id'] for r in rows}),
                              'reason': 'same_source_cell_owner_or_target_conflict'})
            for row in rows:
                if row['status'] != 'out_of_scope':
                    row['status'] = 'needs_review'
                    if 'same_cell_owner_or_target_conflict' not in row['reasons']:
                        row['reasons'].append('same_cell_owner_or_target_conflict')
    for row in result:row['core_status']=row['status']
    return result, ledger, conflicts


def merge_sources(stage0, stage4, sidecar, stage5, identity, catalog, reviewed_stage4=None):
    assert stage4['document_id'] == stage0['document_id'] == identity['document_id'] == stage5['document_id']
    assert sidecar['document_id'] == stage0['document_id'], 'Wrong table document'
    table_ids = {b['block_id'] for b in stage0['elements'] if b.get('type') == 'table'}
    assert table_ids == {t['table_id'] for t in sidecar.get('tables', [])}, 'Stage4T did not account for every table'
    blocks, cells = source_index(stage0)
    candidates = [*expressions(stage4, 'stage4n_saved'), *table_expressions(sidecar)]
    if reviewed_stage4 is not None:
        assert reviewed_stage4['document_id'] == stage0['document_id']
        candidates += list(expressions(reviewed_stage4, 'legacy_reviewed_adapter'))
    before = [make_record(item, ref, inherited, catalog, identity, blocks, cells)
              for item, ref, inherited in candidates]
    stage4_rows, stage4_ledger, stage4_conflicts = reconcile(before)
    extra = [make_record(item, ref, inherited, catalog, identity, blocks, cells)
             for item, ref, inherited in expressions(stage5, 'stage5_saved')]
    # Stage6 export layer applies the same rules to Stage5; raw legacy core is immutable.
    final, _, conflicts = reconcile(stage4_rows + extra)
    final_by_expression = {ref: row for row in final for ref in row['expression_refs']}
    all_refs = [ref for row in before + extra for ref in row['expression_refs']]
    assert len(set(all_refs)) == len(all_refs)
    assert set(all_refs) == set(final_by_expression), 'Candidate was silently lost'
    ledger = [{'expression_ref': ref, 'record_id': final_by_expression[ref]['record_id'],
        'final_status': final_by_expression[ref]['status'],
        'merged': len(final_by_expression[ref]['expression_refs']) > 1} for ref in all_refs]
    return {'records': final, 'ledger': ledger, 'conflicts': stage4_conflicts + conflicts,
        'stage4r_records': stage4_rows, 'stage4r_ledger': stage4_ledger,
        'stage4r_executed': True, 'stage4t_saved_results_consumed': True,
        'stage4t_model_rerun': False, 'stage6_mode': 'raw_export_contract_checks_not_legacy_core_rerun',
        'input_expression_count': len(all_refs), 'all_expressions_accounted_for': True}
