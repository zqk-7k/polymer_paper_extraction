from types import SimpleNamespace

import pytest

from stages.request_trace import RequestTrace
from stages.stage4_property import _user_message
from tests.test_stage4_property import stage0_document, stage2_document, stage3_document
from tools.audit_stage4_request_trace import audit_trace


def fixture(tmp_path, mode="live"):
    source, entities, process = stage0_document(), stage2_document(), stage3_document()
    process.samples[0].sample_label_raw = "PB-10"
    inputs = {"stage0": source.model_dump(mode="json"), "stage2": entities.model_dump(mode="json"), "stage3": process.model_dump(mode="json")}
    message = _user_message(source.document_id, entities, process, source.elements, {})
    trace = RequestTrace(tmp_path, document_id=source.document_id, inputs=inputs, mode=mode)
    class Client:
        last_raw_response = None
        def call_json(self, *args, **kwargs):
            self.last_raw_response = SimpleNamespace(provider="test", model="fake", finish_reason="stop", content='{}')
            return SimpleNamespace(data={})
    trace.call_json(Client(), "system", message, max_tokens=50)
    output = {"provenance": {"status": "candidate_partial"}}
    trace.finish(output=output)
    return trace, inputs, output


def test_verified_request_checks_tables_and_sample_identity(tmp_path):
    trace, inputs, output = fixture(tmp_path)
    result = audit_trace(trace.data, inputs, output)
    assert result["integrity_verified"]
    assert result["historical_live_request_verified"]
    assert not result["publication_status_changed"]
    assert result["attempts"][0]["omitted_table_ids"] == []
    assert result["attempts"][0]["altered_blocks"] == []
    assert result["attempts"][0]["missing_sample_fields"] == []


@pytest.mark.parametrize("change,reason", [
    ("request", "attempt_1_request_hash_mismatch"), ("response", "attempt_1_parsed_response_hash_mismatch"),
    ("input", "stage3_input_hash_mismatch"), ("output", "stage4_output_hash_mismatch"),
])
def test_mismatched_trace_is_not_treated_as_proof(tmp_path, change, reason):
    trace, inputs, output = fixture(tmp_path)
    if change == "request": trace.data["attempts"][0]["request"]["user_message"] += "altered"
    if change == "response": trace.data["attempts"][0]["parsed_response"] = {"invented": True}
    if change == "input": inputs["stage3"]["samples"][0]["sample_label_raw"] = "PB-20"
    if change == "output": output["provenance"]["status"] = "success"
    result = audit_trace(trace.data, inputs, output)
    assert not result["integrity_verified"]
    assert not result["historical_live_request_verified"]
    assert reason in result["reasons"]


def test_replay_and_missing_history_never_claim_historical_request(tmp_path):
    trace, inputs, output = fixture(tmp_path, mode="offline_replay")
    result = audit_trace(trace.data, inputs, output)
    assert result["integrity_verified"]
    assert not result["historical_live_request_verified"]
    assert audit_trace(None, inputs, output)["reasons"] == ["request_trace_missing"]


def test_real_omission_is_reported_separately_from_integrity(tmp_path):
    trace, inputs, output = fixture(tmp_path)
    from stages.request_trace import content_hash
    attempt = trace.data["attempts"][0]
    attempt["request"]["user_message"] = attempt["request"]["user_message"].replace('"sample_label_raw": "PB-10"', '"sample_label_raw": null')
    attempt["request_sha256"] = content_hash(attempt["request"])
    result = audit_trace(trace.data, inputs, output)
    assert result["integrity_verified"]
    assert result["attempts"][0]["missing_sample_fields"] == [{"sample_id": "s001", "field": "sample_label_raw"}]


def test_stage_failure_keeps_trace_without_credentials(tmp_path):
    from stages.stage4_property import run_stage4, load_property_vocabulary, DEFAULT_VOCABULARY_PATH
    from tests.test_stage4_property import FakeClient, rendered_prompt
    import json
    for filename, model in (("stage0_blocks.json", stage0_document()), ("stage2_entities.json", stage2_document()), ("stage3_process.json", stage3_document())):
        (tmp_path / filename).write_text(model.model_dump_json(), encoding="utf-8")
    class BrokenClient(FakeClient):
        def call_json(self, *args, **kwargs):
            raise RuntimeError("secret-in-transport-error")
    vocab, vhash = load_property_vocabulary(DEFAULT_VOCABULARY_PATH)
    with pytest.raises(RuntimeError):
        run_stage4(tmp_path / "stage0_blocks.json", tmp_path / "stage2_entities.json", tmp_path / "stage3_process.json",
                   tmp_path / "stage4_properties.json", BrokenClient(), rendered_prompt(), vocab, vhash)
    trace = json.loads((tmp_path / "stage4_request_trace.json").read_text(encoding="utf-8"))
    assert trace["status"] == "failed"
    assert trace["attempts"][0]["status"] == "call_failed"
    assert not (tmp_path / "stage4_properties.json").exists()
    assert "secret-in-transport-error" not in json.dumps(trace)


def test_truncation_blocks_completeness_without_erasing_request_link(tmp_path):
    from stages.request_trace import content_hash
    trace, inputs, output = fixture(tmp_path)
    attempt = trace.data["attempts"][0]
    attempt["status"] = "call_failed"
    attempt["error_type"] = "LLMOutputTruncatedError"
    attempt.pop("parsed_response")
    attempt.pop("parsed_response_sha256")
    attempt["raw_response"]["finish_reason"] = "max_tokens"
    attempt["raw_response_sha256"] = content_hash(attempt["raw_response"])
    result = audit_trace(trace.data, inputs, output)
    assert result["historical_live_request_verified"]
    assert not result["model_output_complete"]
    assert not result["publication_status_changed"]
