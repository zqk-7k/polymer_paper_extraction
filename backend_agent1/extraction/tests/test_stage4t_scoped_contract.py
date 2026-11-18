import copy

from schema.polymer_schema import Stage0Element
from stages.table_grid import parse_table_cells
from stages.stage4t_table_interpretation import build_interpretation_input, validate_interpretation
from stages.stage4t_table_property import shadow_extract_table, _measurement_role_for_row
from stages.stage4t_interpretation_apply import apply_table_interpretation
from stages.stage4t_llm_interpreter import _structural_completeness_reasons
from stages.stage4t_subject_context import subject_summary, resolve_subject, load_subject_summary
from stages.stage4t_scoped_relations import merge_units


def table(body, caption='Properties of Resin'):
    return Stage0Element(block_id='T_test', type='table', page=1, source_block_index=0,
                         caption=caption, table_body=body, table_cells=parse_table_cells(body, 'T_test'))


def cell(row, col):
    return f'T_test:r{row:04d}:c{col:04d}'


def interpretation(**kwargs):
    return dict(table_id='T_test', direction='column_samples', axis_role='implicit_subject',
                sample_binding_strategy='implicit_subject', requires_human_review=False, **kwargs)


def relation(kind, quote, targets, **kwargs):
    return dict(kind=kind, source_refs=['T_test:caption'], source_quote=quote,
                target_cell_ids=targets, reason='Explicit source scope', **kwargs)


def test_full_ocr_context_keeps_late_sample_and_inline_conditions():
    t = table('<table><tr><td>Sample</td><td>Viscosity</td></tr>' + ''.join(
        f'<tr><td>P{i}</td><td>630 (60% resin / 40% acetone)</td></tr>' for i in range(24)) + '</table>')
    request = build_interpretation_input(t)
    assert request['coverage']['complete']
    assert len(request['cells']) == len(t.table_cells)
    assert request['cells'][-1]['text'] == '630 (60% resin / 40% acetone)'
    limited = build_interpretation_input(t, max_data_rows=2, survey={'header_rows':[0]})
    assert not limited['coverage']['complete']
    visible = {c['cell_id'] for c in limited['cells']}
    assert all(s['source_id'] in visible for s in limited['sources'] if s['kind'] == 'cell')


def test_headerless_keeps_first_mixed_and_text_values():
    t = table('<table><tr><td>Density</td><td>1.2</td></tr><tr><td>Viscosity</td>'
              '<td>630 (60% resin / 40% acetone)</td></tr><tr><td>Color</td><td>yellow</td></tr></table>')
    result = shadow_extract_table(t)
    values = {x['cell_id']:x['value_raw'] for x in result['observations']}
    assert values[cell(0, 1)] == '1.2'
    assert values[cell(1, 1)] == '630 (60% resin / 40% acetone)'
    assert values[cell(2, 1)] == 'yellow'
    assert next(o for o in result['observations'] if o['cell_id'] == cell(2,1))['value_kind'] == 'text'


def test_caption_property_and_partial_rejection_do_not_lose_valid_nodes():
    t = table('<table><tr><td>Time</td><td>10 s</td></tr><tr><td>400 nm</td><td>0.2</td></tr></table>',
              'Attenuation of films')
    good = dict(source_refs=['T_test:caption'], source_quote='Attenuation', target_cell_ids=[cell(1, 1)],
                role='unmapped_property', confidence=0.9, reason='Caption defines property')
    bad = dict(source_cell_ids=['foreign:cell'], role='unknown', confidence=0.2, reason='Invalid source')
    raw = interpretation(header_assignments=[good, bad])
    frozen = copy.deepcopy(raw)
    parsed = validate_interpretation(raw, build_interpretation_input(t), partial=True)
    assert len(parsed.header_assignments) == 1 and len(parsed.rejected_items) == 1
    assert not _structural_completeness_reasons(parsed)
    result, _ = apply_table_interpretation(t, shadow_extract_table(t), parsed)
    value = next(x for x in result['observations'] if x['cell_id'] == cell(1, 1))
    assert value['property_name_raw'] == 'Attenuation' and value['value_raw'] == '0.2'
    assert raw == frozen


def test_forged_quote_scope_and_sample_are_quarantined():
    t = table('<table><tr><td>Density</td><td>1.2</td></tr></table>')
    raw = interpretation(scoped_relations=[
        relation('subject', 'not in original', [cell(0, 1)]),
        relation('subject', 'Resin', ['another-table-cell']),
        relation('subject', 'Resin', [cell(0, 1)], candidate_sample_ids=['s999'])])
    parsed = validate_interpretation(raw, build_interpretation_input(t), partial=True)
    assert len(parsed.rejected_items) == 3 and not parsed.scoped_relations


def test_unnamed_metadata_and_property_roles_survive_shared_unit_inheritance():
    t = table('<table><tr><td rowspan="2">Sample</td><td colspan="2">IR (cm-1)</td></tr>'
              '<tr><td>P=O</td><td>P-O-C</td></tr><tr><td>P1</td><td>1294</td><td>959</td></tr></table>')
    assignments = [dict(source_cell_ids=[cell(0, 1)], role='process_metadata', confidence=1, reason='group')]
    assignments += [dict(source_cell_ids=[cell(1, c)], role='unmapped_property', measurement_role='experimental',
                        confidence=1, reason='IR peak') for c in (1, 2)]
    raw = interpretation(header_assignments=assignments)
    raw['direction'] = 'row_samples'
    parsed = validate_interpretation(raw, build_interpretation_input(t), partial=True)
    assert not parsed.rejected_items and 'metadata_name_unresolved' in parsed.warnings
    result, _ = apply_table_interpretation(t, shadow_extract_table(t), parsed)
    for x in result['observations']:
        if x['row_index'] == 2 and x['column_index'] in (1, 2):
            assert x['unit_normalized'] in {'cm-1', 'cm⁻¹'}
            assert x['measurement_role'] == 'experimental'


def test_yield_note_does_not_contaminate_other_columns_and_scope_is_local():
    t = table('<table><tr><td>Sample</td><td>Yield</td><td>Mw</td></tr>'
              '<tr><td>P1</td><td>90</td><td>2.4</td></tr></table>', 'Yield calculated; Mw measured')
    assert _measurement_role_for_row(t.table_cells, 1, table_context=t.caption) == 'reported_unknown'
    raw = interpretation(scoped_relations=[relation('measurement_role', 'calculated', [cell(1, 1)],
                                                   measurement_role='calculated')])
    result, _ = apply_table_interpretation(t, shadow_extract_table(t), raw)
    values = {x['cell_id']:x for x in result['observations']}
    assert values[cell(1, 1)]['measurement_role'] == 'calculated'
    assert values[cell(1, 2)]['measurement_role'] != 'calculated'


def test_missing_unit_cannot_erase_known_unit_and_conflict_is_retained():
    c = {'unit_raw': 'cm-1', 'unit_normalized': 'cm-1'}
    merge_units(c, {'unit_raw': None, 'unit_normalized': None})
    assert c['unit_raw'] == 'cm-1'
    merge_units(c, {'unit_raw': 'Hz', 'unit_normalized': 'Hz'})
    assert c['unit_raw'] == 'cm-1' and c['metadata_conflicts'][0]['proposed']['unit_raw'] == 'Hz'


def test_summary_has_process_evidence_and_material_only_is_not_unique_sample():
    sample = dict(sample_id='s001', refers_to_entity='pe001', polymer_name='Resin',
                  sample_label_raw='Resin', state_description='liquid', evidence={'block_id':'P1'})
    catalog = subject_summary({'polymer_entities':[{'entity_id':'pe001', 'canonical_name':'Resin'}]},
         {'samples':[sample], 'process_steps':[{'step_id':'ps001','output_sample_ids':['s001'],
             'parameters':{'time':'10 s'}, 'evidence':{'block_id':'P2'}}]})
    assert catalog['samples'][0]['processes'][0]['evidence']['block_id'] == 'P2'
    candidate = {'subject_relations':[relation('subject', 'Resin', [cell(0,1)], candidate_sample_ids=['s001'])]}
    assert resolve_subject(candidate, catalog)['status'] == 'entity_matched'


def test_sample_ambiguity_and_state_conflict_cannot_be_overridden_by_proposed_id():
    samples = [dict(sample_id=sid, sample_label_raw='P1', polymer_name='Resin',
                    refers_to_entity='pe001', state_description='liquid') for sid in ('s001','s002')]
    c = {'subject_relations':[relation('subject', 'P1', [cell(0,1)], candidate_sample_ids=['s001'])]}
    assert resolve_subject(c, {'samples':samples})['status'] == 'ambiguous_sample'
    c['scoped_relations'] = [relation('condition', 'dry film', [cell(0,1)], name='sample_state', condition_kind='state')]
    result = resolve_subject(c, {'samples':samples})
    assert result['status'] != 'matched' and 'sample_state_or_processing_conflict' in result['anchors']


def test_foreign_document_summary_is_not_used(tmp_path):
    import json
    (tmp_path/'stage3_process.json').write_text(json.dumps({'document_id':'foreign','samples':[{'sample_id':'s001'}]}))
    summary, hashes = load_subject_summary(tmp_path, 'current')
    assert not summary['samples'] and hashes['stage3_process.json']
    assert any('document_mismatch' in w for w in summary['warnings'])


def test_scoped_subject_survives_R_schema_and_source_display():
    from test_stage4r_unified_preview import _stage0, _stage2, _stage3, _stage4, _candidate, _sidecar
    from stages.stage4r_unified_preview import unify_documents
    from stages.source_derivation_enrichment import build_source_interpretations
    from tools.source_extraction_export import _derived_display
    document = _stage0()
    document.elements[0].caption = 'Sample-A thermal properties'
    cid = 'T_1:r0001:c0001'
    r = dict(kind='subject', source_refs=['T_1:caption'], source_quote='Sample-A', target_cell_ids=[cid],
             candidate_sample_ids=['s001'], reason='caption')
    candidate = _candidate(sample_label_raw=None, subject_relations=[r], scoped_relations=[r])
    merged, audit = unify_documents(document, _stage2(), _stage3(), _stage4(), _sidecar(candidate))
    assert len(merged.properties) == 1
    assert merged.properties[0].sample_id == 's001'
    relation_trace = merged.properties[0].candidate_trace['stage4t_relations']
    assert relation_trace['subject_resolution']['status'] == 'matched'
    bundle = build_source_interpretations(document.model_dump(mode='json'), merged.model_dump(mode='json'))
    assert bundle['records'][0]['stage4t_relations'] == relation_trace
    assert '已关联具体样品' in _derived_display(bundle['records'])


def test_scoped_scale_and_conditions_preserve_raw_and_do_not_spread():
    t = table('<table><tr><td>Sample</td><td>Mw</td><td>Mn</td></tr>'
              '<tr><td>P1</td><td>2.4</td><td>1.2</td></tr></table>', 'Mw ×10^-4 measured at 20 °C')
    raw = interpretation(scoped_relations=[
        relation('scale', t.caption, [cell(1,1)]),
        relation('condition', '20 °C', [cell(1,1)], name='temperature', condition_kind='measurement')])
    result, _ = apply_table_interpretation(t, shadow_extract_table(t), raw)
    rows = {o['cell_id']:o for o in result['observations']}
    assert rows[cell(1,1)]['value_raw'] == '2.4'
    assert rows[cell(1,1)]['conditions']['temperature'] == '20 °C'
    assert rows[cell(1,1)]['scale_factor_exponent'] == 4
    assert not rows[cell(1,2)]['conditions'].get('temperature')


def test_two_condition_axes_produce_coordinate_values_not_header_names():
    t = table('<table><tr><td rowspan="2">Wavelength (nm)</td><td colspan="2">Curing time (s)</td></tr>'
              '<tr><td>10</td><td>20</td></tr><tr><td>400</td><td>90.0</td><td>90.5</td></tr></table>')
    raw = interpretation(header_assignments=[
        dict(source_cell_ids=[cell(0,0)], role='condition_axis', normalized_name='wavelength', confidence=1, reason='row axis'),
        dict(source_cell_ids=[cell(0,1)], role='condition_axis', normalized_name='curing_time', confidence=1, reason='column axis')])
    shadow = shadow_extract_table(t)
    assert len(shadow['observations']) == 2
    result, _ = apply_table_interpretation(t, shadow, raw)
    rows = {x['cell_id']:x for x in result['observations']}
    assert rows[cell(2,1)]['conditions'] == {'wavelength':'400 nm', 'curing_time':'10 s'}
    assert rows[cell(2,2)]['conditions']['curing_time'] == '20 s'
    assert not rows[cell(2,1)]['property_name_raw']


def test_sidecar_sample_summary_change_invalidates_cache(tmp_path, monkeypatch):
    import json
    from test_stage4t_preview_sidecar import _complex_document
    from stages.stage4t_preview_sidecar import run_sidecar
    directory = tmp_path/'reference_no_test'
    directory.mkdir()
    doc = _complex_document()
    (directory/'stage0_blocks.json').write_text(doc.model_dump_json(), encoding='utf-8')
    config = tmp_path/'pipeline.yaml'
    config.write_text('{}', encoding='utf-8')
    # An offline, disabled sidecar still must refresh the recorded summary.
    args = dict(input_root=tmp_path, output_root=tmp_path, ref_no='reference_no_test', config_path=config)
    path, cached = run_sidecar(**args)
    assert not cached
    _, cached = run_sidecar(**args)
    assert cached
    (directory/'stage2_entities.json').write_text(json.dumps({'document_id':doc.document_id,
        'polymer_entities':[{'entity_id':'pe001','polymer_name':'Resin'}]}), encoding='utf-8')
    _, cached = run_sidecar(**args)
    assert not cached
    assert json.loads(path.read_text(encoding='utf-8'))['subject_catalog']['entities'][0]['polymer_name'] == 'Resin'


def test_latex_scale_requires_footnote_definition_before_splitting_letter():
    from stages.stage4t_table_property import _unit_info
    header = r'$M_w \times 10^{-4c}$'
    assert _unit_info([header], None)['scale_factor_status'] == 'ambiguous_display_scale'
    assert _unit_info([r'$M_w \times 10^{-4}$'], None)['scale_factor_exponent'] == 4
    t = table('<table><tr><td>Sample</td><td>' + header + '</td></tr><tr><td>P1</td><td>2.4</td></tr></table>')
    r = dict(kind='scale', source_refs=[cell(0,1),'F1'], source_quote=header, target_cell_ids=[cell(1,1)],
             footnote_marker='c', reason='Cited footnote')
    raw = interpretation(scoped_relations=[r])
    ctx = {'footnotes':[{'block_id':'F1','text':'c Measured by light scattering.'}]}
    parsed = validate_interpretation(raw, build_interpretation_input(t, context=ctx), partial=True)
    assert not parsed.rejected_items
    applied, _ = apply_table_interpretation(t, shadow_extract_table(t), parsed, context=ctx)
    value = next(o for o in applied['observations'] if o['cell_id'] == cell(1,1))
    assert value['value_raw'] == '2.4' and value['scale_factor_exponent'] == 4
    forged = validate_interpretation(raw, build_interpretation_input(t), partial=True)
    assert len(forged.rejected_items) == 1
