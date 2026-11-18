from copy import deepcopy

import pytest

from stages.publication_input_scope import record_input_scope, stage4_input_diagnostics


def test_stage4_complete_saved_response_does_not_certify_partial_input():
    stage = {"provenance": {"status": "candidate_partial"}, "warnings": [{"code": "series_subject_unresolved"}]}
    response = {"status": "received", "raw_response": {"finish_reason": "end_turn", "content": '{"properties": []}'}}
    result = stage4_input_diagnostics(stage, response)
    assert result["diagnostic_categories"] == ["series_binding_unresolved"]
    assert result["strict_json_object"]
    assert not result["request_input_link_verified"]
    assert not result["publication_status_changed"]
    assert result["input_status"] == "candidate_partial"


def test_stage4_diagnostic_distinguishes_missing_and_incomplete():
    missing = stage4_input_diagnostics(None)
    assert missing["next_action"] == "restore_missing_stage_input"
    partial = stage4_input_diagnostics({"provenance": {"status": "candidate_partial"}, "warnings": [{"code": "preview_incomplete_response"}]})
    assert partial["diagnostic_categories"] == ["response_declared_incomplete"]
    assert not partial["strict_json_object"]


def fixture():
    evidence = {"block_id": "T1", "source_sentence": "A 120", "table_locator": {"cell_id": "T1:r0001:c0001"}}
    item = {"property_id": "prop_s5_009", "property_name_raw": "Tg", "value_raw": "120", "unit_raw": "C", "sample_id": "s001", "evidence_ids": ["ev001"]}
    payload = {"document_id": "test", "evidence": [{**evidence, "evidence_id": "ev001"}]}
    local = {**item, "property_id": "prop_s5_001", "evidence": [evidence]}
    local.pop("evidence_ids")
    stage = {"provenance": {"status": "candidate_partial"}}
    manifest = {"schema_version": "stage5_shards.v0.2", "document_id": "test", "status": "candidate_partial", "shard_count": 2, "unrouted_block_ids": [], "shards": [
        {"shard_id": "good", "status": "complete", "block_ids": ["T1"], "result": {"properties": [local]}},
        {"shard_id": "bad", "status": "failed", "block_ids": ["T2"], "result": {}},
    ]}
    return item, payload, stage, manifest


def test_complete_shard_record_is_independent_of_unrelated_failure():
    args = fixture()
    before = deepcopy(args)
    result = record_input_scope(*args)
    assert result["input_complete"]
    assert result["input_scope_basis"] == "complete_shard_record"
    assert result["input_shard_ids"] == ["good"]
    assert args == before


@pytest.mark.parametrize("case,reason", [
    ("running", "shard_manifest_incomplete"), ("missing_shard", "shard_manifest_incomplete"),
    ("overlap", "input_shard_incomplete"), ("unrouted", "input_scope_uncovered"),
    ("mismatched_value", "shard_record_not_unique"), ("missing_result", "shard_record_not_unique"),
    ("wrong_document", "shard_manifest_incomplete"),
])
def test_uncertain_scope_remains_blocked(case, reason):
    item, payload, stage, manifest = fixture()
    if case == "running": manifest["status"] = "running"
    if case == "missing_shard": manifest["shard_count"] = 3
    if case == "overlap": manifest["shards"][1]["block_ids"].append("T1")
    if case == "unrouted": manifest["unrouted_block_ids"] = ["T1"]
    if case == "mismatched_value": item["value_raw"] = "999"
    if case == "missing_result": manifest["shards"][0]["result"] = {}
    if case == "wrong_document": manifest["document_id"] = "other"
    result = record_input_scope(item, payload, stage, manifest)
    assert not result["input_complete"]
    assert reason in result["input_scope_reasons"]


def test_partial_without_manifest_is_never_promoted():
    item, payload, stage, _ = fixture()
    assert not record_input_scope(item, payload, stage)["input_complete"]
    assert not record_input_scope(item, payload, None)["input_complete"]


def test_condition_reference_and_failed_dependency_are_not_ignored():
    item, payload, stage, manifest = fixture()
    item["measurement_context"] = {"temperature_evidence_ids": ["ev999"]}
    result = record_input_scope(item, payload, stage, manifest)
    assert not result["input_complete"]
    assert "input_scope_reference_unknown" in result["input_scope_reasons"]
    payload["evidence"].append({"evidence_id": "ev999", "block_id": "T2", "source_sentence": "25 C"})
    result = record_input_scope(item, payload, stage, manifest)
    assert not result["input_complete"]
    assert "input_shard_incomplete" in result["input_scope_reasons"]
def test_traced_scalar_requires_exact_output_membership_and_condition_dependencies():
    from copy import deepcopy
    from stages.publication_input_scope import stage4_record_input_scope
    item = {"property_name_raw": "Tg", "value_raw": "120", "unit_raw": "C", "sample_id": "s1",
            "measurement_context": {"dose": "8.1 kGy"}, "evidence": [{"block_id": "T1", "source_sentence": "A 120"}]}
    stage = {"provenance": {"status": "candidate_partial"}, "properties": [deepcopy(item)]}
    proof = {"verified": True, "basis": "verified_live_trace", "reasons": [], "selected_block_ids": ["T1"]}
    assert stage4_record_input_scope(item, {}, stage, proof)["input_complete"]
    for field, value in [("value_raw", "121"), ("sample_id", "s2"), ("measurement_context", {"dose": "9 kGy"})]:
        changed = {**item, field: value}
        assert not stage4_record_input_scope(changed, {}, stage, proof)["input_complete"]
    changed = deepcopy(item)
    changed["measurement_context"]["evidence"] = [{"block_id": "outside_request"}]
    assert not stage4_record_input_scope(changed, {}, stage, proof)["input_complete"]
    stage["properties"].append(deepcopy(item))
    assert not stage4_record_input_scope(item, {}, stage, proof)["input_complete"]

