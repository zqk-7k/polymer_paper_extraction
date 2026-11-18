import json

import pytest

from tests.test_audit_stage4_request_trace import fixture
from tools.freeze_stage4_ab_dataset import freeze


def case(tmp_path):
    root = tmp_path / "source"
    trace, inputs, output = fixture(root)
    for key, filename in (("stage0", "stage0_blocks.json"), ("stage2", "stage2_entities.json"), ("stage3", "stage3_process.json")):
        (root / filename).write_text(json.dumps(inputs[key]), encoding="utf-8")
    (root / "stage4_properties.json").write_text(json.dumps(output), encoding="utf-8")
    return root, trace


def test_freeze_preserves_exact_request_and_rejects_overwrite(tmp_path):
    root, trace = case(tmp_path)
    output = tmp_path / "frozen"
    manifest = freeze([(root, root)], output)
    packet = json.loads((output / "case_001.json").read_text(encoding="utf-8"))
    assert packet["request"] == trace.data["attempts"][0]["request"]
    assert manifest["api_requests"] == 0
    assert manifest["status"] == "awaiting_candidate_model"
    with pytest.raises(ValueError, match="already exists"):
        freeze([(root, root)], output)


@pytest.mark.parametrize("change", ["tampered_request", "offline_replay", "truncated"])
def test_unverified_baseline_is_not_frozen(tmp_path, change):
    root, trace = case(tmp_path)
    if change == "tampered_request":
        trace.data["attempts"][0]["request"]["user_message"] += "changed"
    elif change == "offline_replay":
        trace.data["mode"] = "offline_replay"
    else:
        trace.data["attempts"][0]["raw_response"]["finish_reason"] = "max_tokens"
    trace.save()
    with pytest.raises(ValueError, match="verified complete live"):
        freeze([(root, root)], tmp_path / "frozen")
