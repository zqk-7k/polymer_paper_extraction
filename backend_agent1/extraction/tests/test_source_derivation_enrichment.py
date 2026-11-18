from copy import deepcopy
import pytest

from stages.source_derivation_enrichment import build_source_interpretations
from stages.source_table_extraction import build_source_extraction
from tests.test_source_table_extraction import source
from tools.source_extraction_export import render_source_report, validate_source_result


def fixture():
    data = source('<table><tr><td rowspan="2">Sample</td><td rowspan="2">Mw × 10^-4</td><td>C(%)</td></tr><tr><td>Found</td></tr><tr><td>A</td><td>3·95</td><td>59.14</td></tr></table>')
    stage = {'document_id': data['document_id'], 'properties': []}
    for col, name, raw, unit in [(1, 'Mw', '3·95', None), (2, 'C', '59.14', '%')]:
        stage['properties'].append({'property_id': str(col), 'property_name_raw': name, 'value_raw': raw,
            'unit_raw': unit, 'evidence': [{'block_id': 'T1', 'page': 0, 'source_type': 'table',
                'source_sentence': raw, 'table_locator': {'table_id': 'T1', 'cell_id': f'T1:r0002:c000{col}',
                'row_index': 2, 'column_index': col, 'cell_value': raw}}]})
    return data, stage


def test_inherit_candidates_and_roles_without_mutating_raw_or_publication(tmp_path):
    data, stage = fixture()
    original = deepcopy((data, stage))
    bundle = build_source_interpretations(data, stage)
    publication = {'document_id': data['document_id'], 'source_interpretation_bundle': bundle}
    result = build_source_extraction(data, publication)
    mw, carbon = result['observations']
    assert mw['value_raw'] == '3·95' and mw['value_normalized'] is None
    assert mw['derived_interpretations'][0]['value_derivation']['candidate_values'] == [39500]
    assert carbon['result_origin'] == 'experimental'
    assert (data, stage) == original
    validate_source_result(result)
    report = tmp_path/'report.html'
    render_source_report(result, report)
    html = report.read_text(encoding='utf-8')
    assert '39500' in html and '派生候选' in html and '3·95' in html


def test_wrong_value_at_existing_cell_does_not_inherit_verified_derivation():
    data, stage = fixture()
    stage['properties'][1]['value_raw'] = '999'
    bundle = build_source_interpretations(data, stage)
    result = build_source_extraction(data, {'document_id': data['document_id'], 'source_interpretation_bundle': bundle})
    row = result['observations'][1]
    assert row['value_raw'] == '59.14'
    assert not row['derived_interpretations'][0]['source_literal_verified']
    assert row['derived_interpretations'][0]['value_derivation'] is None


def test_methods_remain_scoped_and_cross_document_input_is_rejected():
    data, stage = fixture()
    s5 = {'document_id': data['document_id'], 'characterizations': [
        {'characterization_id':'c1', 'method_raw':'contact angle', 'parameters':{'drop_volume':'2 μl'}}]}
    bundle = build_source_interpretations(data, stage, s5)
    assert bundle['methods'][0]['parameters']['drop_volume'] == '2 μl'
    assert all('drop_volume' not in str(row['measurement_context']) for row in bundle['records'])
    s5['document_id'] = 'other'
    with pytest.raises(ValueError):
        build_source_interpretations(data, stage, s5)
