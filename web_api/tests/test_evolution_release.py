import json
from web_api.app import get_evolution_report, get_evolution_report_data
from web_api.evolution_report import fraction, release_info

def test_release_is_explicit_about_runtime_and_experimental_scope():
    data = json.loads(get_evolution_report_data().body)
    assert data['runtime_version'] == 'E25-core-20260920'
    assert data['supplementary_model_requests_enabled'] is False
    assert data['enhanced_process_graph_enabled'] is False
    p = data['property_experiment']
    assert p['final_hits'] <= p['all_stage_hits'] <= p['denominator']
    assert (p['papers'], p['denominator'], p['all_stage_hits'], p['final_hits']) == (101, 3525, 3315, 3211)
    assert data['process_experiment']['papers'] == 26
    assert 'not held-out' in p['reference_scope']

def test_aggregate_report_keeps_limits_visible_and_has_no_raw_source():
    body = get_evolution_report().body.decode('utf-8')
    for text in ('94.04%', '91.09%', '91.11%', '97.98%', '不是未见测试集', '不是当前网页批次的实时评分', '可能增加'):
        assert text in body
    assert 'D:/' not in body
    assert 'source_sentence' not in json.dumps(release_info())
    assert fraction(0, 0) == '不适用（分母为 0）'
