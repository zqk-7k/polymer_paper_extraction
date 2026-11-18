import json

import pytest

from stages.measurement_publication import build_measurement_publication
from tests.test_measurement_publication import fixture
from tools.production_export import build_measurement_export


def publication(tmp_path):
    payload, inputs = fixture()
    payload["document_id"] = "reference_no_test"
    for stage in ("stage0", "stage2", "stage3", "stage4"):
        inputs[stage]["document_id"] = payload["document_id"]
    data = build_measurement_publication(payload, **inputs)
    root = tmp_path / "input"
    doc = root / payload["document_id"]
    doc.mkdir(parents=True)
    path = doc / "measurement_publication.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return root, path, data


def test_export_only_gated_records_without_reading_standard_answers(tmp_path):
    root, path, data = publication(tmp_path)
    before = path.read_bytes()
    # Legacy content must not leak into the new export.
    (path.parent / "final.json").write_text('{"property_observations": [{"value_raw":"999"}]}', encoding="utf-8")
    result = build_measurement_export(root, tmp_path / "export")
    assert result["counts"]["final"] == 1
    exported = json.loads((tmp_path / "export/final_measurements.jsonl").read_text(encoding="utf-8"))
    assert exported["value_raw"] == "120" and exported["sample_id"] == "s001"
    assert "source_claims" in exported
    assert path.read_bytes() == before
    with pytest.raises(ValueError, match="exists"):
        build_measurement_export(root, tmp_path / "export")


@pytest.mark.parametrize("case", ["missing_proof", "wrong_sample", "wrong_unit", "wrong_entity", "wrong_status", "duplicate", "wrong_source_condition"])
def test_inconsistent_final_is_rejected_before_writing(tmp_path, case):
    root, path, data = publication(tmp_path)
    group = data["final"][0]
    if case == "missing_proof": group["members"][0]["audit"]["input_complete"] = False
    if case == "wrong_sample": group["record"]["sample_id"] = "s999"
    if case == "wrong_unit": group["record"]["unit_raw"] = "K"
    if case == "wrong_entity": group["record"]["entity_id"] = "pe999"
    if case == "wrong_status": group["publication_status"] = "candidate"
    if case == "wrong_source_condition": group["record"]["source_condition_context"] = {"dose": "999 kGy"}
    if case == "duplicate":
        data["final"].append(group)
        data["counts"]["final"] = 2
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        build_measurement_export(root, tmp_path / "export")
    assert not (tmp_path / "export").exists()


def test_legacy_final_is_never_an_implicit_fallback(tmp_path):
    root = tmp_path / "input"
    root.mkdir()
    (root / "final.json").write_text('{}', encoding="utf-8")
    with pytest.raises(ValueError, match="not a fallback"):
        build_measurement_export(root, tmp_path / "export")


@pytest.mark.parametrize("kind", ["article_alias_confirmed", "entity_only"])
def test_source_proven_identity_can_export_without_stage3_sample(tmp_path, kind):
    payload, inputs = fixture()
    payload["document_id"] = "reference_no_test"
    for stage in ("stage0", "stage2", "stage3", "stage4"):
        inputs[stage]["document_id"] = payload["document_id"]
    payload["samples"] = inputs["stage3"]["samples"] = []
    item = payload["property_observations"][0]
    item.pop("sample_id")
    if kind == "article_alias_confirmed":
        item.pop("entity_id")
    else:
        payload["polymer_entities"][0].update(polymer_name="A", source_names=["A"], evidence={"block_id": "T1", "source_sentence": "A"})
        inputs["stage2"]["polymer_entities"] = payload["polymer_entities"]
    data = build_measurement_publication(payload, **inputs)
    assert data["counts"]["final"] == 1
    root = tmp_path / "input"
    path = root / payload["document_id"] / "measurement_publication.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    assert build_measurement_export(root, tmp_path / "export")["counts"]["final"] == 1
    group = data["final"][0]
    assert group["record"]["binding_status"] == kind and group["record"]["sample_id"] is None
    group["members"][0]["audit"].pop("binding_basis")
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="identity proof"):
        build_measurement_export(root, tmp_path / "bad-export")


def test_missing_batch_document_is_reported_and_stale_failed_output_rejected(tmp_path):
    root, path, data = publication(tmp_path)
    summary = {"original_inputs_unchanged": True, "documents": [
        {"document_id": "reference_no_missing", "status": "missing_input", "missing_inputs": ["stage4_properties.json"]},
        {"document_id": "reference_no_test", "status": "published"}]}
    raw_dir = root / "reference_no_missing"
    raw_dir.mkdir()
    (raw_dir / "raw_candidate_ledger.json").write_text(json.dumps({
        "schema_version": "raw_measurement_ledger.v1", "document_id": raw_dir.name,
        "records": [{"measurement_id": "raw1", "publication_status": "not_publishable", "original_record": {"value_raw": "120"}}]}), encoding="utf-8")
    (root / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    result = build_measurement_export(root, tmp_path / "export")
    assert result["unavailable_documents"][0]["document_id"] == "reference_no_missing"
    assert result["counts"]["raw_candidate"] == 1
    assert result["counts"]["final"] == 1
    summary["documents"][1]["status"] = "execution_failed"
    (root / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(ValueError, match="stale"):
        build_measurement_export(root, tmp_path / "export2")
