from copy import deepcopy
import json

import pytest

from tests.test_reference_sample_crosswalk import fixture
from tools.compare_stage4_ab import compare


def setup(tmp_path):
    crosswalk, _, record = fixture(tmp_path)
    reference = tmp_path / "reference.jsonl"
    reference.write_text(json.dumps({"standard_record_id": "gt1", "reference_no": "doc1", "article_sample_id": "external-1",
                                   "standard_property_code": record["standard_property_code"], "reviewed_unit": "C", "value_min": 146, "value_max": 146}) + '\n')
    roots = []
    for arm in ("A", "B"):
        root = tmp_path / arm
        directory = root / "doc1"
        directory.mkdir(parents=True)
        counts = {"final": 1, "candidate": 0, "not_publishable": 0, "measurement_group_count": 1}
        publication = {"schema_version": "measurement_publication.v1", "document_id": "doc1", "counts": counts,
                       "final": [{"measurement_id": "m1", "record": record, "publication_reasons": []}], "candidate": [], "not_publishable": []}
        case = {"document_id": "doc1", "request_sha256": "same", "status": "completed", "api_requests": 1, "elapsed_seconds": 1,
                "evaluation": {"counts": counts, "binding_counts": {}, "reason_counts": {}}}
        run = {"status": "completed", "original_inputs_unchanged": True, "rules_unchanged": True, "rule_hashes": {"rule": "same"},
               "transport": {"same": True}, "cases": [case], "arm": arm, "requested_model": arm}
        for name, data in (("summary.json", run), ("doc1/case_result.json", case), ("doc1/measurement_publication.json", publication)):
            (root / name).write_text(json.dumps(data), encoding="utf-8")
        roots.append(root)
    return roots, reference, crosswalk


def test_missing_cost_or_gold_is_not_zero_cost_or_perfect_accuracy(tmp_path):
    roots, reference, crosswalk = setup(tmp_path)
    result = compare(*roots, tmp_path / "comparison", reference_rows=reference, sample_crosswalk=crosswalk)
    assert result["same_requests_rules_and_transport"]
    for metric in result["metrics"]:
        assert metric["published_identity_value_match_rows"] == 1
        assert metric["cost_status"] == "unknown_or_partial"
        assert metric["independent_sample_binding_accuracy"] is None
        assert metric["conflicting_binding_false_acceptance_rate"] is None
    assert not result["production_model_replaced"]


def test_retry_metrics_keep_every_failed_attempt(tmp_path):
    roots, reference, crosswalk = setup(tmp_path)
    for root in roots:
        path = root / "summary.json"
        run = json.loads(path.read_text())
        case = run["cases"][0]
        case.update(api_requests=2, attempt_history=[
            {"status": "failed", "error_type": "ChunkedEncodingError", "timeout": True, "cost": {"total_cost": "0.2", "currency": "CNY"}},
            {"status": "completed", "timeout": True, "cost": {"total_cost": "0.3", "currency": "CNY"}},
        ])
        path.write_text(json.dumps(run))
        (root / "doc1/case_result.json").write_text(json.dumps(case))
    result = compare(*roots, tmp_path / "comparison", reference_rows=reference, sample_crosswalk=crosswalk)
    for metric in result["metrics"]:
        assert metric["known_cost"] == "0.5"
        assert metric["costed_requests"] == 2
        assert metric["timeout_rate"] == 1
        assert metric["failed_request_rate"] == 0.5
        assert metric["transport_interruption_requests"] == 1


def test_missing_arm_response_is_excluded_from_paired_quality_counts(tmp_path):
    roots, reference, crosswalk = setup(tmp_path)
    root = roots[1]
    path = root / "summary.json"
    run = json.loads(path.read_text())
    run["cases"][0]["status"] = "failed"
    path.write_text(json.dumps(run))
    (root / "doc1/case_result.json").write_text(json.dumps(run["cases"][0]))
    result = compare(*roots, tmp_path / "comparison", reference_rows=reference, sample_crosswalk=crosswalk)
    assert result["paired_completed_document_ids"] == []
    assert result["metrics"][0]["counts"]["final"] == 1
    assert all(m["paired_completed_counts"] == {} for m in result["metrics"])


@pytest.mark.parametrize("field", ["request", "rules", "transport", "unfinished"])
def test_unfair_or_unfinished_comparison_is_rejected(tmp_path, field):
    roots, reference, crosswalk = setup(tmp_path)
    path = roots[1] / "summary.json"
    run = json.loads(path.read_text(encoding="utf-8"))
    if field == "request": run["cases"][0]["request_sha256"] = "different"
    if field == "rules": run["rule_hashes"]["rule"] = "different"
    if field == "transport": run["transport"] = {"same": False}
    if field == "unfinished": run["status"] = "running"
    path.write_text(json.dumps(run))
    with pytest.raises(ValueError):
        compare(*roots, tmp_path / "comparison", reference_rows=reference, sample_crosswalk=crosswalk)
