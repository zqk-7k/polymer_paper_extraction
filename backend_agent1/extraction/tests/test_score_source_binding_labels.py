from tools.score_source_binding_labels import score


def test_missing_and_unresolved_are_not_invented_wrong_bindings():
    labels = [{"document_id": "doc", "source_cell_id": "cell", "expected_sample_id": "s1", "expected_entity_id": "e1", "expected_article_alias": "A", "sample_axis_cell_id": "axis"}]
    assert score(labels, {})["binding_accuracy_on_covered_cells"] is None
    group = {"measurement_id": "m1", "identity": {"source_cell_ids": ["cell"], "sample_id": None, "entity_id": None}, "record": None}
    result = score(labels, {"doc": {"not_publishable": [group]}})
    assert result["unresolved_binding_claims"] == 1
    assert result["incorrect_binding_claims"] == 0
    assert result["false_acceptance_on_incorrect_claims"] is None


def test_wrong_final_is_counted_even_when_a_correct_claim_exists():
    labels = [{"document_id": "doc", "source_cell_id": "cell", "expected_sample_id": "s1", "expected_entity_id": "e1"}]
    good = {"measurement_id": "good", "identity": {"source_cell_ids": ["cell"], "sample_id": "s1", "entity_id": "e1"}}
    bad = {"measurement_id": "bad", "identity": {"source_cell_ids": ["cell"], "sample_id": "s2", "entity_id": "e1"}}
    result = score(labels, {"doc": {"final": [good, bad]}})
    assert result["correct_binding_cells"] == 0
    assert result["incorrect_binding_claims_published"] == 1
    assert result["false_acceptance_on_incorrect_claims"] == 1


def test_conflicting_preparation_cannot_be_scored_as_correct_sample():
    labels = [{"document_id": "doc", "source_cell_id": "cell", "expected_sample_id": None,
               "expected_entity_id": "e1", "forbidden_sample_ids": ["s2"]}]
    claim = {"measurement_id": "m", "identity": {"source_cell_ids": ["cell"], "sample_id": "s2", "entity_id": "e1"}}
    result = score(labels, {"doc": {"not_publishable": [claim]}})
    assert result["incorrect_binding_claims"] == 1
    assert result["false_acceptance_on_incorrect_claims"] == 0
    claim["identity"]["sample_id"] = "unreviewed"
    unknown = score(labels, {"doc": {"candidate": [claim]}})
    assert unknown["incorrect_binding_claims"] == 0
    assert unknown["unresolved_binding_claims"] == 1
    claim["identity"]["sample_id"] = None
    assert score(labels, {"doc": {"candidate": [claim]}})["correct_binding_cells"] == 1
