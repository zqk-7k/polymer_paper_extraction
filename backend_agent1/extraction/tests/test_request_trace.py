import json
from types import SimpleNamespace

import pytest

from stages.request_trace import RequestTrace, content_hash


def test_request_is_saved_before_call_and_bound_to_response(tmp_path):
    trace = RequestTrace(tmp_path, document_id="test", inputs={"stage0": {"text": "A"}})
    class Client:
        api_key = "secret-never-serialize"
        last_raw_response = None
        def call_json(self, system, user, **kwargs):
            saved = json.loads((tmp_path / "stage4_request_trace.json").read_text())
            assert saved["attempts"][0]["request"]["user_message"] == user
            self.last_raw_response = SimpleNamespace(provider="test", model="fake", finish_reason="stop", content='{"value": 1}')
            return SimpleNamespace(data={"value": 1})
    response = trace.call_json(Client(), "instructions", "source evidence", max_tokens=50)
    response.data["value"] = 9
    trace.finish(output={"provenance": {"status": "success"}})
    saved = json.loads((tmp_path / "stage4_request_trace.json").read_text())
    assert saved["attempts"][0]["parsed_response"] == {"value": 1}
    assert saved["attempts"][0]["request_sha256"] == content_hash(saved["attempts"][0]["request"])
    assert saved["status"] == "completed"
    assert "secret-never-serialize" not in json.dumps(saved)


def test_failure_retry_and_stale_response_remain_distinguishable(tmp_path):
    trace = RequestTrace(tmp_path, document_id="test", inputs={}, mode="offline_replay")
    stale = SimpleNamespace(content="old")
    class Client:
        last_raw_response = stale
        def call_json(self, *args, **kwargs):
            raise RuntimeError("credential-must-not-appear")
    for user in ("first request", "retry with validation feedback"):
        with pytest.raises(RuntimeError):
            trace.call_json(Client(), "instructions", user, max_tokens=10)
    trace.finish(error_type="RuntimeError")
    saved = json.loads((tmp_path / "stage4_request_trace.json").read_text())
    assert len(saved["attempts"]) == 2
    assert all(a["status"] == "call_failed" and "raw_response" not in a for a in saved["attempts"])
    assert "credential-must-not-appear" not in json.dumps(saved)
    assert saved["mode"] == "offline_replay"
    RequestTrace(tmp_path, document_id="test", inputs={})
    assert len(list((tmp_path / "stage4_request_traces").glob("*.json"))) == 2
