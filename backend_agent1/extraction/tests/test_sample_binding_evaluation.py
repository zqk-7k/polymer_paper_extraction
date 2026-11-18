import pytest
from tools.sample_binding_evaluation import evaluate_gold


def test_unannotated_queue_does_not_claim_zero_errors_or_accuracy():
    metrics = evaluate_gold([{"adjudicated": False}], [])
    assert metrics["precision"] is None
    assert metrics["false_accept_count"] is None
    assert metrics["pending_count"] == 1


def test_wrong_sample_is_false_accept_and_missed_correct_binding():
    label = {"review_id": "r1", "input_sha256": "hash", "adjudicated": True, "annotator": "reviewer",
             "expected_status": "accepted", "expected_sample_id": "A"}
    review = {"review_id": "r1", "input_sha256": "hash", "validated_review": {"reasoning_status": "accepted", "selected_sample_id": "B"}}
    metrics = evaluate_gold([label], [review])
    assert metrics["precision"] == metrics["recall"] == 0
    assert metrics["false_accept_count"] == 1
    with pytest.raises(ValueError):
        evaluate_gold([{**label, "input_sha256": "stale"}], [review])
