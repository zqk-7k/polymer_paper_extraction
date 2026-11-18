from copy import deepcopy

import pytest

from stages.request_trace import content_hash
from stages.series_input_scope import verify_series_input_trace, point_input_scope
from tests.test_audit_stage4_request_trace import fixture as trace_fixture


def fixture(tmp_path):
    trace, inputs, output = trace_fixture(tmp_path)
    output.update(document_id=inputs["stage0"]["document_id"], warnings=[{"code": "series_subject_unresolved", "blocking": True}])
    trace.finish(output=output)
    return inputs, output, trace.data


def test_complete_response_certifies_only_covered_point_dependencies(tmp_path):
    inputs, output, trace = fixture(tmp_path)
    proof = verify_series_input_trace(inputs["stage0"], inputs["stage2"], inputs["stage3"], output, trace)
    assert proof["verified"], proof
    series = {"evidence": [{"block_id": "P_1_0"}], "points": [{"evidence": [{"block_id": "unrelated_missing"}]}]}
    point = {"evidence": [{"block_id": "P_2_0"}]}
    assert point_input_scope(series, point, proof)["input_complete"]
    point["measurement_context"] = {"evidence": [{"block_id": "missing_dependency"}]}
    assert not point_input_scope(series, point, proof)["input_complete"]


@pytest.mark.parametrize("case", ["changed_input", "changed_output", "changed_request", "truncated", "semantics_bypassed", "salvaged", "unknown_partial", "unknown_blocking"])
def test_incomplete_or_unverified_trace_never_opens_input_gate(tmp_path, case):
    inputs, output, trace = fixture(tmp_path)
    if case == "changed_input": inputs["stage3"]["samples"][0]["sample_label_raw"] = "altered"
    if case == "changed_output": output["warnings"].append({"code": "altered"})
    if case == "changed_request": trace["attempts"][-1]["request"]["user_message"] += "altered"
    if case == "truncated":
        raw = trace["attempts"][-1]["raw_response"]
        raw["finish_reason"] = "max_tokens"
        trace["attempts"][-1]["raw_response_sha256"] = content_hash(raw)
    if case in {"semantics_bypassed", "salvaged", "unknown_partial", "unknown_blocking"}:
        code = {"semantics_bypassed": "preview_semantic_validation_bypassed", "salvaged": "preview_objects_salvaged", "unknown_partial": "unknown", "unknown_blocking": "new_blocker"}[case]
        output["warnings"] = [{"code": code, "blocking": case == "unknown_blocking"}]
        trace["output_sha256"] = content_hash(output)
    assert not verify_series_input_trace(inputs["stage0"], inputs["stage2"], inputs["stage3"], output, trace)["verified"]


def test_replay_requires_identical_live_request_and_response(tmp_path):
    inputs, output, live = fixture(tmp_path)
    replay = deepcopy(live)
    replay["mode"] = "offline_replay"
    replay["attempts"][-1].pop("raw_response")
    replay["attempts"][-1].pop("raw_response_sha256")
    args = (inputs["stage0"], inputs["stage2"], inputs["stage3"], output)
    assert not verify_series_input_trace(*args, replay)["verified"]
    proof = verify_series_input_trace(*args, replay, live)
    assert proof["verified"] and proof["basis"] == "verified_replay_of_live_response"
    replay["attempts"][-1]["parsed_response"] = {"changed": True}
    replay["attempts"][-1]["parsed_response_sha256"] = content_hash({"changed": True})
    assert not verify_series_input_trace(*args, replay, live)["verified"]


def test_complete_live_response_with_local_failure_can_be_reprocessed(tmp_path):
    inputs, output, live = fixture(tmp_path)
    replay = deepcopy(live)
    replay["mode"] = "offline_replay"
    live.update(status="failed", error_type="AttributeError")
    live.pop("output_sha256")
    args = (inputs["stage0"], inputs["stage2"], inputs["stage3"], output)
    assert verify_series_input_trace(*args, replay, live)["verified"]
    live["attempts"][-1]["status"] = "failed"
    assert not verify_series_input_trace(*args, replay, live)["verified"]


@pytest.mark.parametrize("content", ['```json\n{}\n```', ' \n```\r\n{}\r\n```\n '])
def test_single_complete_json_fence_preserves_trace_proof(tmp_path, content):
    inputs, output, trace = fixture(tmp_path)
    attempt = trace["attempts"][-1]
    attempt["raw_response"]["content"] = content
    attempt["raw_response_sha256"] = content_hash(attempt["raw_response"])
    proof = verify_series_input_trace(inputs["stage0"], inputs["stage2"], inputs["stage3"], output, trace)
    assert proof["verified"]
    assert proof["response_format"] == "single_json_code_fence"


@pytest.mark.parametrize("content,finish", [
    ('Explanation\n```json\n{}\n```', 'stop'),
    ('```json\n{}\n```\nMore text', 'stop'),
    ('```json\n{}', 'stop'),
    ('```json\n{}\n```\n```json\n{}\n```', 'stop'),
    ('```json\n{"changed":true}\n```', 'stop'),
    ('```json\n{}\n```', 'max_tokens'),
    ('```json\n[]\n```', 'stop'),
    ('```json\n{"x":1,}\n```', 'stop'),
])
def test_wrapper_never_repairs_or_hides_incomplete_response(tmp_path, content, finish):
    inputs, output, trace = fixture(tmp_path)
    attempt = trace["attempts"][-1]
    attempt["raw_response"].update(content=content, finish_reason=finish)
    attempt["raw_response_sha256"] = content_hash(attempt["raw_response"])
    assert not verify_series_input_trace(inputs["stage0"], inputs["stage2"], inputs["stage3"], output, trace)["verified"]


def test_verified_r_chain_does_not_certify_r_added_or_changed_records(tmp_path):
    inputs, original, trace = fixture(tmp_path)
    scalar = {"property_id": "p1", "value_raw": "12", "evidence": [{"block_id": "P_1_0"}]}
    original["properties"] = [scalar]
    trace["output_sha256"] = content_hash(original)
    merged = deepcopy(original)
    merged["properties"].append({**scalar, "property_id": "p2", "value_raw": "13"})
    sidecar = {"document_id": original["document_id"], "tables": []}
    audit = {"document_id": original["document_id"], "stage": "stage4r_unified_preview", "implementation_version": "test",
             "input_content_hashes": {k: content_hash(v) for k, v in {**inputs, "stage4n": original, "stage4t": sidecar}.items()},
             "output_content_sha256": content_hash(merged)}
    def verify():
        return verify_series_input_trace(inputs["stage0"], inputs["stage2"], inputs["stage3"], merged, trace,
                                         stage4n=original, stage4t=sidecar, stage4r_audit=audit)
    proof = verify()
    assert proof["verified"] and proof["stage4r_lineage"]["verified"]
    assert point_input_scope({}, scalar, proof)["input_complete"]
    assert not point_input_scope({}, merged["properties"][1], proof)["input_complete"]
    merged["properties"][0]["value_raw"] = "99"
    assert not verify()["verified"]
    merged["properties"][0]["value_raw"] = "12"
    sidecar["document_id"] = "other_article"
    assert not verify()["verified"]


def test_r_null_materialization_preserves_only_same_record_and_semantic_scope():
    from stages.series_input_scope import traced_object_hashes
    from stages.stage4_object_validation import object_key
    series = {"series_id": "s1", "measurement_context": {"other_conditions": {"solvent": "water"}}}
    point = {"point_id": "p1", "value_raw": "12", "evidence": [{"block_id": "P_1_0"}]}
    rejected = {**point, "point_id": "p2"}
    original = {"property_series": [{**series, "points": [point, rejected]}]}
    accepted = [object_key(series, point)]
    proof = {"verified": True, "basis": "verified_live_trace", "reasons": [],
             "selected_block_ids": ["P_1_0"], "semantic_scope": "per_object",
             "traced_object_hashes": traced_object_hashes(original),
             "accepted_traced_object_hashes": traced_object_hashes(original, accepted)}
    materialized = deepcopy(series)
    materialized["measurement_context"]["temperature"] = None
    materialized_point = deepcopy(point)
    materialized_point["evidence"][0]["table_locator"] = None
    assert point_input_scope(materialized, materialized_point, proof)["input_complete"]
    assert "stage4_object_semantic_validation_failed" in point_input_scope(materialized, rejected, proof)["input_scope_reasons"]
    materialized["measurement_context"]["other_conditions"]["solvent"] = "acetone"
    assert "record_not_in_traced_stage4n_output" in point_input_scope(materialized, materialized_point, proof)["input_scope_reasons"]
