import json

import pytest

from tests.test_compare_stage4_ab import setup
from tools import reevaluate_stage4_ab as tool


def prepare(tmp_path, monkeypatch):
    roots, _, _ = setup(tmp_path)
    monkeypatch.setattr(tool, "load_dataset", lambda _: ([({"document_id": "doc1", "request_sha256": "same"}, {})], {}))
    monkeypatch.setattr(tool, "evaluate", lambda directory, inputs: {"rechecked": True})
    for root in roots:
        (root / "doc1/stage4_properties.json").write_text('{}')
    return roots


def test_transport_recovery_keeps_failed_attempt_in_metrics(tmp_path, monkeypatch):
    roots = prepare(tmp_path, monkeypatch)
    recovery = tmp_path / "recovery"
    (recovery / "doc1").mkdir(parents=True)
    original = tool.read(roots[0] / "summary.json")
    tool.write(recovery / "summary.json", original)
    (recovery / "doc1/stage4_properties.json").write_text('{}')
    original["cases"][0].update(status="failed", error_type="ChunkedEncodingError")
    tool.write(roots[0] / "summary.json", original)
    (roots[0] / "doc1/stage4_properties.json").unlink()
    output = tmp_path / "reevaluated"
    tool.reevaluate("unused", *roots, output, recovery_a=recovery)
    result = tool.read(output / "A/summary.json")
    assert result["new_api_requests"] == 0
    assert result["api_requests"] == 2
    assert result["cases"][0]["initial_status"] == "failed"
    assert result["cases"][0]["recovery_used"]
    assert len(result["cases"][0]["attempt_history"]) == 2


def test_semantic_failure_cannot_be_replaced_with_better_retry(tmp_path, monkeypatch):
    roots = prepare(tmp_path, monkeypatch)
    recovery = tmp_path / "recovery"
    recovery.mkdir()
    original = tool.read(roots[0] / "summary.json")
    tool.write(recovery / "summary.json", original)
    original["cases"][0].update(status="failed", error_type="ValueError")
    tool.write(roots[0] / "summary.json", original)
    with pytest.raises(ValueError, match="single identical-input transport retry"):
        tool.reevaluate("unused", *roots, tmp_path / "reevaluated", recovery_a=recovery)


def test_failed_recovery_is_counted_without_replacing_result(tmp_path, monkeypatch):
    roots = prepare(tmp_path, monkeypatch)
    original = tool.read(roots[0] / "summary.json")
    original["cases"][0].update(status="failed", error_type="ChunkedEncodingError")
    tool.write(roots[0] / "summary.json", original)
    (roots[0] / "doc1/stage4_properties.json").unlink()
    recovery = tmp_path / "recovery"
    recovery.mkdir()
    tool.write(recovery / "summary.json", original)
    output = tmp_path / "reevaluated"
    tool.reevaluate("unused", *roots, output, recovery_a=recovery)
    result = tool.read(output / "A/summary.json")
    assert result["api_requests"] == 2
    assert result["cases"][0]["status"] == "failed"
    assert not result["cases"][0]["recovery_used"]
    assert len(result["cases"][0]["attempt_history"]) == 2


@pytest.mark.parametrize("field", ["transport", "rule_hashes"])
def test_recovery_cannot_change_settings(tmp_path, monkeypatch, field):
    roots = prepare(tmp_path, monkeypatch)
    original = tool.read(roots[0] / "summary.json")
    recovery = tmp_path / "recovery"
    recovery.mkdir()
    original[field] = {"changed": True}
    tool.write(recovery / "summary.json", original)
    with pytest.raises(ValueError, match="not verified"):
        tool.reevaluate("unused", *roots, tmp_path / "reevaluated", recovery_a=recovery)
