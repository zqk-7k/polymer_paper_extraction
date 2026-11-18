from tools.audit_source_extraction import score


def test_same_value_at_wrong_property_axis_is_not_correct():
    labels = [{'document_id': 'd', 'source_cell_id': 'c', 'category': 'axis', 'expected': {'value_raw': '12', 'property_header_cell_ids': ['h1']}}]
    rows = [{'document_id': 'd', 'source_cell_id': 'c', 'extraction_status': 'usable', 'value_raw': '12', 'property_header_cell_ids': ['h2']}]
    result = score(labels, rows)
    assert result['incorrect_cells'] == 1 and result['correct_cells'] == 0
    assert score(labels, [])['missing_cells'] == 1
