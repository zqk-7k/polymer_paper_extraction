from copy import deepcopy

import pytest

from llm_client import LLMClient
from stages.request_trace import content_hash
from tests.test_stage4_property import FakeClient
from tests.test_freeze_stage4_ab_dataset import case
from tools.freeze_stage4_ab_dataset import freeze
from tools.run_stage4_ab import FrozenClient, load_dataset


def test_frozen_input_hashes_are_checked_before_calls(tmp_path):
    source, _ = case(tmp_path)
    target = tmp_path / "frozen"
    freeze([(source, source)], target)
    cases, hashes = load_dataset(target)
    assert len(cases) == 1
    assert cases[0][0]["request_sha256"] == content_hash(cases[0][0]["request"])
    (source / "stage3_process.json").write_text('{}')
    with pytest.raises(ValueError, match="source changed"):
        load_dataset(target)


def test_changed_request_or_second_attempt_never_reaches_model(monkeypatch):
    request = {"system_prompt": "same schema", "user_message": "same evidence", "max_tokens": 128000}
    calls = []
    monkeypatch.setattr(LLMClient, "call_json", lambda *args, **kwargs: calls.append(kwargs))
    client = FrozenClient(FakeClient().resolved, api_key="test", request=request)
    changed = deepcopy(request)
    changed["max_tokens"] = 1000
    with pytest.raises(ValueError, match="exactly match"):
        client.call_json(**changed)
    assert not calls and client.request_count == 0
    client.call_json(**request)
    with pytest.raises(ValueError, match="no validation retries"):
        client.call_json(**request)
    assert len(calls) == 1 and client.request_count == 1


@pytest.mark.parametrize("sample_id,expected_final", [("s001", 1), ("s999", 0)])
def test_evaluation_preserves_real_sample_registry(tmp_path, sample_id, expected_final):
    from tests.test_measurement_publication import fixture
    from tools.run_stage4_ab import evaluate, write
    payload, data = fixture()
    item = deepcopy(payload["property_observations"][0])
    item.update(sample_id=sample_id, evidence=payload["evidence"])
    item.pop("evidence_ids")
    stage4 = {**data["stage4"], "properties": [item]}
    paths = {}
    for key, filename in (("stage0", "stage0_blocks.json"), ("stage2", "stage2_entities.json"), ("stage3", "stage3_process.json")):
        paths[filename] = tmp_path / filename
        write(paths[filename], data[key])
    write(tmp_path / "stage4_properties.json", stage4)
    write(tmp_path / "stage4_request_trace.json", None)
    result = evaluate(tmp_path, paths)
    assert result["counts"]["final"] == expected_final
    if sample_id == "s001":
        assert not result["reason_counts"].get("publication_sample_reference_unknown")
