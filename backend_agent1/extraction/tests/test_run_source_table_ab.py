from tools.run_source_table_ab import score_case


def test_table_ab_rejects_same_value_with_wrong_sample_or_duplicate():
    case = {'labels': [{'source_cell_id': 'v', 'expected': {'value_raw': '12', 'sample_axis_cell_ids': ['s1']}}]}
    wrong = {'source_cell_id': 'v', 'value_raw': '12', 'sample_axis_cell_ids': ['s2']}
    assert score_case(case, {'observations': [wrong]})['correct_cells'] == 0
    good = {**wrong, 'sample_axis_cell_ids': ['s1']}
    assert score_case(case, {'observations': [good]})['correct_cells'] == 1
    assert score_case(case, {'observations': [good, wrong]})['correct_cells'] == 0
