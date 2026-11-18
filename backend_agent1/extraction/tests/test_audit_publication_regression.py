import hashlib
import json

import pytest

from tools.audit_publication_regression import run_regression


def fixture(tmp_path):
    source = tmp_path / "batch"
    doc = source / "reference_no_001"
    doc.mkdir(parents=True)
    item = {"property_id": "prop001", "property_name_raw": "Tg", "value_raw": "120", "unit_raw": "C", "evidence_ids": ["e1"]}
    payload = {"document_id": doc.name, "property_observations": [item, item]}
    publication = doc / "candidate.json"
    publication.write_text(json.dumps(payload), encoding="utf-8")
    baseline = tmp_path / "baseline.json"
    row = {"collection": "property_observations", "object_id": "prop001", "publication_status": "final", "publication_reasons": []}
    baseline.write_text(json.dumps([{
        "document_id": doc.name, "source_file": "candidate.json",
        "sha256": hashlib.sha256(publication.read_bytes()).hexdigest(),
        "audit": {"records": [row, row], "counts": {"publication_status": {"final": 2, "candidate": 0, "not_publishable": 0}}},
    }]), encoding="utf-8")
    return source, baseline, publication


def test_report_keeps_duplicate_occurrences_and_preserves_inputs(tmp_path):
    source, baseline, publication = fixture(tmp_path)
    before = publication.read_bytes()
    output = tmp_path / "report"
    result = run_regression(source, baseline, output)
    assert result["original_inputs_unchanged"]
    assert result["api_requests"] == 0
    assert result["record_count"] == 2
    rows = [json.loads(line) for line in (output / "differences.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["frozen_occurrence"] for row in rows] == [0, 1]
    assert all(row["after"] == "not_publishable" for row in rows)
    assert publication.read_bytes() == before


def test_stale_baseline_and_overwrite_are_rejected(tmp_path):
    source, baseline, publication = fixture(tmp_path)
    with pytest.raises(ValueError, match="separate"):
        run_regression(source, baseline, source / "report")
    publication.write_text(publication.read_text() + " ", encoding="utf-8")
    output = tmp_path / "report"
    with pytest.raises(ValueError, match="changed since baseline"):
        run_regression(source, baseline, output)
    assert not output.exists()
