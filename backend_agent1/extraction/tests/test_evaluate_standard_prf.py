from tools.evaluate_standard_prf import calculate, maximum_matching


def gold(row, value, key='tg', name='glass transition temperature', unit='C', **kwargs):
    return dict(excel_row=row, document_id='article', property=name, property_key=key,
                minimum=value, maximum=value, unit=unit, raw_value=None, **kwargs)


def prediction(identifier, value, name='Tg', unit='C', **kwargs):
    return dict(observation_id=identifier, document_id='article', property_name_raw=name,
                value_raw=value, unit_raw=unit, extraction_status='usable', **kwargs)


def test_duplicates_units_extra_facts_and_sample_identity_do_not_inflate_tp():
    references = [gold(2, 100), gold(3, 100), gold(4, 200)]
    observations = [prediction('a', '100', article_sample_label_raw='sample 1'),
                    prediction('b', '373.15', unit='K', article_sample_label_raw='sample 2'),
                    prediction('c', '300'), prediction('d', '40', name='Mn', unit='g/mol')]
    summary, _, _, _ = calculate(references, observations)
    assert summary['unique_reference_facts'] == 2
    assert summary['unique_prediction_facts_in_scope'] == 2
    assert summary['true_positive_reference_pairs'] == 1
    assert summary['reference_precision'] == summary['reference_recall'] == summary['reference_f1'] == .5
    assert summary['covered_standard_rows'] == 2
    assert not summary['unlisted_predictions_are_confirmed_errors']


def test_conditions_count_only_explicit_model_fields_and_keep_actual_misses():
    references = [gold(2, 110, 'tc', 'crystallization temperature'),
                  gold(3, 20, 'treatment_condition', 'treatment condition', None),
                  gold(4, 500, 'treatment_condition', 'treatment condition', None)]
    observations = [prediction('a', '35', name='crystallinity', unit='%',
        condition_context_raw=[{'name_raw': 'Tc', 'value_raw': '110 °C'},
                               {'name_raw': 'treatment', 'value_raw': 'PSII treated (after 20 days)'}],
        source_excerpt='pulse frequency 500 Hz')]
    summary, facts, _, _ = calculate(references, observations)
    assert summary['true_positive_reference_pairs'] == 2
    assert summary['unique_reference_facts'] == 3
    assert facts[2]['status'] == 'unmatched_reference'


def test_invalid_and_figure_gold_are_excluded_but_ambiguous_gold_remains():
    references = [gold(2, 100, evaluation_category_v3='错误标准记录'),
                  gold(3, 0, 'weight_loss', 'weight loss', '%', evaluation_category_v3='条件或事件限定'),
                  gold(4, 300, evaluation_category_v3='图内结果'),
                  gold(5, 200, evaluation_category_v3='待裁定')]
    summary, _, _, excluded = calculate(references, [prediction('a', '200')])
    assert summary['excluded_rows'] == len(excluded) == 3
    assert summary['included_standard_rows'] == 1
    assert summary['reference_f1'] == 1


def test_maximum_matching_does_not_use_greedy_pairing():
    assert len(maximum_matching([[0, 1], [0]])) == 2


def test_gold_units_float_noise_and_missing_unit_duplicates_share_one_fact():
    references = [gold(2, .19321, 'izod', 'izod impact', 'kJ/m'),
                  gold(3, .19321000000000002, 'izod', 'izod impact', 'kJ/m'),
                  gold(4, 193.21, 'izod', 'izod impact', 'J/m')]
    summary, _, _, _ = calculate(references, [prediction('a', '193.21', name='izod impact', unit='J/m')])
    assert summary['unique_reference_facts'] == 1
    assert summary['covered_standard_rows'] == 3
    assert summary['reference_f1'] == 1
    references = [gold(2, 40, 'crystallinity', 'crystallinity', '%'),
                  gold(3, 40, 'crystallinity', 'crystallinity', None)]
    summary, _, _, _ = calculate(references, [prediction('a', '40', name='crystallinity', unit='%')])
    assert summary['unique_reference_facts'] == 1
    assert summary['reference_f1'] == 1


def test_missing_and_qualitative_values_are_not_numeric_predictions():
    summary, _, _, _ = calculate([gold(2, 100)], [prediction('a', '—'), prediction('b', 'not observed')])
    assert summary['unique_prediction_facts_in_scope'] == 0
    assert summary['nonnumeric_prediction_views'] == 2


def test_thresholds_do_not_multiply_measurements_and_bounds_remain_distinct():
    references = [gold(2, 5, 'weight_loss', 'weight loss', '%'),
                  gold(3, 350, 'td', 'decomposition temperature')]
    observation = prediction('a', '>350', name='T5', semantic_normalization={
        'interpretations': [{'relation': 'threshold', 'property_name': 'weight loss',
                             'value': '5', 'unit': '%'}]})
    summary, facts, _, _ = calculate(references, [observation])
    assert summary['true_positive_reference_pairs'] == 1
    assert summary['unique_prediction_facts_in_scope'] == 2
    assert facts[1]['status'] == 'unmatched_reference'
