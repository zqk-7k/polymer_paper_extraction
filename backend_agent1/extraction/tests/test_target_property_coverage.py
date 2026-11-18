from copy import deepcopy
import pytest

from stages.source_table_extraction import build_source_extraction
from stages.target_property_coverage import build_catalog, build_coverage


def fixture():
    schema = {'property_vocabulary': {'glass_transition_temperature': ['P3110','thermal'],
                                      'melting_temperature': ['P3120','thermal']}}
    registry = {'entries': [
        {'key': 'glass_transition_temperature', 'aliases': ['Tg'], 'pipeline_property_name': 'glass_transition_temperature'},
        {'key': 'melting_temperature', 'aliases': ['Tm'], 'pipeline_property_name': 'melting_temperature'}]}
    catalog = build_catalog(schema, registry, ['property_vocabulary'])
    source = {'document_id': 'reference_no_test', 'elements': [{'block_id':'T1', 'type':'table',
              'table_body':'<table><tr><td>Sample</td><td>Tg</td><td>Tm</td></tr><tr><td>A</td><td>120</td><td>—</td></tr></table>',
              'page':0, 'source_block_index':0}]}
    return build_source_extraction(source), catalog


def test_published_presence_does_not_certify_completeness_or_absence():
    data, catalog = fixture()
    result = build_coverage([data], catalog, data['observations'])
    tg, tm = result['ledger']
    assert tg['status'] == 'published_present_completeness_unchecked'
    assert tm['status'] == 'not_yet_located'
    assert not any(r['all_values_accounted_for'] or r['verified_not_reported'] for r in result['ledger'])


def test_missing_export_is_separate_from_missing_extraction():
    data, catalog = fixture()
    row = build_coverage([data], catalog, [])['ledger'][0]
    assert row['status'] == 'identified_but_not_exported'
    assert row['unpublished_observation_ids'] == [data['observations'][0]['observation_id']]


def test_export_same_id_with_changed_value_or_axis_is_rejected():
    data, catalog = fixture()
    for field, value in [('value_raw', '999'), ('article_sample_label_raw', 'B'), ('property_header_cell_ids', [])]:
        changed = deepcopy(data['observations'])
        changed[0][field] = value
        with pytest.raises(ValueError, match='inconsistent'):
            build_coverage([data], catalog, changed)


def test_reference_to_property_in_prose_is_a_hint_not_a_result():
    data, catalog = fixture()
    data['source_blocks'] = [{'block_id':'P1', 'text':'The melting temperature was not measured.'}]
    row = build_coverage([data], catalog, data['observations'])['ledger'][1]
    assert row['status'] == 'source_mention_needs_extraction'
    assert row['mention_block_ids'] == ['P1']
    assert not row['published_observation_ids'] and not row['verified_not_reported']


def test_shared_external_code_does_not_merge_different_properties():
    catalog = build_catalog({'property_vocabulary': {'density':['P1110','physical'], 'specific_volume':['P1110','physical']}},
                            {'entries':[]}, ['property_vocabulary'])
    assert len(catalog['targets']) == 2


def test_different_documents_cannot_share_export_identity():
    data, catalog = fixture()
    changed = deepcopy(data['observations'])
    changed[0]['document_id'] = 'reference_no_other'
    with pytest.raises(ValueError, match='inconsistent'):
        build_coverage([data], catalog, changed)


def test_unmapped_source_properties_remain_in_gap_queue():
    data, catalog = fixture()
    data['observations'][0].update(property_name_raw='Novel property', property_header_path=['Novel property'], standard_property_code=None)
    result = build_coverage([data], catalog, data['observations'])
    assert len(result['unassigned_properties']) == 1
    assert not result['assignments']


def test_audit_checks_actual_export_and_writes_distinct_target_subset(tmp_path):
    import json
    import yaml
    from tools.source_extraction_export import build_source_export
    from tools.audit_target_property_coverage import audit
    data, _ = fixture()
    source = tmp_path / 'source'
    (source / data['document_id']).mkdir(parents=True)
    (source / data['document_id'] / 'source_extraction.json').write_text(json.dumps(data), encoding='utf8')
    export = tmp_path / 'export'
    build_source_export(source, export)
    schema_path = tmp_path / 'schema.yaml'
    schema_path.write_text(yaml.safe_dump({'property_vocabulary': {'glass_transition_temperature':['P3110','thermal']}}), encoding='utf8')
    registry_path = tmp_path / 'registry.json'
    registry_path.write_text(json.dumps({'entries':[{'key':'glass_transition_temperature', 'aliases':['Tg']}]}), encoding='utf8')
    output = tmp_path / 'audit'
    summary = audit(source, export, output, 'draft', schema_path, registry_path, ['property_vocabulary'])
    assert summary['published_target_observations'] == 1
    assert summary['scope_status'] == 'draft' and summary['goal_complete'] is False
    row = json.loads((output / 'target_properties.jsonl').read_text())
    assert row['value_raw'] == '120'
    assert summary['original_inputs_unchanged']
