from copy import deepcopy
import hashlib
import json

import pytest

from tools.reference_sample_crosswalk import identity_match, load_crosswalk
from tools.audit_measurement_reference_alignment import compare_reference


def fixture(tmp_path):
    entry = {"document_id": "doc1", "reference_sample_id": "external-1", "status": "reviewed_identity",
             "reviewer": "test", "basis": "Independent name and preparation evidence", "table_id": "t1",
             "sample_axis": {"cell_id": "label", "value_raw": "polyAAM"},
             "preparation_axes": [{"cell_id": "dose", "value_raw": "8.1"}],
             "identity_excerpts": [{"field_path": ["polymer_name"], "value": ["polyacrylamide"]}]}
    for name, payload in {
        "reference_source": {"sample_id": "external-1", "polymer_name": ["polyacrylamide"]},
        "article_source": {"document_id": "doc1", "elements": [{"block_id": "t1", "table_cells": [
            {"cell_id": "label", "text": "polyAAM"}, {"cell_id": "dose", "text": "8.1"}]}]},
    }.items():
        content = json.dumps(payload).encode()
        path = tmp_path / (name + ".json")
        path.write_bytes(content)
        entry[name] = {"path": path.name, "sha256": hashlib.sha256(content).hexdigest()}
    crosswalk = tmp_path / "crosswalk.json"
    crosswalk.write_text(json.dumps({"schema_version": "reference_sample_crosswalk.v1", "entries": [entry]}))
    record = {"standard_property_code": "STD:glass_transition_temperature", "value_raw": "146", "unit_raw": "C",
              "binding_status": "article_alias_confirmed", "binding_evidence_ids": ["label"],
              "source_condition_context": {"table_id": "t1", "status": "source_aligned", "condition_axes": [
                  {"cell_id": "dose", "value_raw": "8.1", "condition_kind": "sample_preparation"}]}}
    return crosswalk, entry, record


def test_independent_identity_value_match_is_not_full_condition_match(tmp_path):
    path, entry, record = fixture(tmp_path)
    crosswalk, snapshots = load_crosswalk(path)
    assert len(snapshots) == 3
    expected = {"standard_record_id": "gt", "reference_no": "doc1", "article_sample_id": "external-1",
                "standard_property_code": record["standard_property_code"], "reviewed_unit": "C", "value_min": 146, "value_max": 146}
    data = {"schema_version": "measurement_publication.v1", "document_id": "doc1", "final": [{"measurement_id": "m1", "record": record}]}
    result = compare_reference(expected, data, crosswalk)
    assert result["identity_verified_value_matches"] == [{"measurement_id": "m1", "publication_status": "final"}]
    assert result["status"] == "published_identity_value_match_conditions_unverified"
    assert not result["fully_verified_match"]
    for field, value in [("binding_status", "conflict"), ("binding_evidence_ids", ["different_label"])]:
        changed = deepcopy(record)
        changed[field] = value
        assert not identity_match(changed, entry)
    record["source_condition_context"]["condition_axes"][0]["value_raw"] = "50.8"
    assert not identity_match(record, entry)


def test_crosswalk_rejects_changed_source_and_property_based_identity(tmp_path):
    path, entry, record = fixture(tmp_path)
    source = tmp_path / entry["reference_source"]["path"]
    source.write_text('{}')
    with pytest.raises(ValueError, match="source changed"):
        load_crosswalk(path)
    path, entry, record = fixture(tmp_path)
    entry["identity_excerpts"] = [{"field_path": ["property"], "value": 146}]
    path.write_text(json.dumps({"schema_version": "reference_sample_crosswalk.v1", "entries": [entry]}))
    with pytest.raises(ValueError, match="Property values"):
        load_crosswalk(path)


def test_conflicting_reference_does_not_establish_identity(tmp_path):
    path, entry, record = fixture(tmp_path)
    entry["status"] = "reference_identity_conflict"
    assert not identity_match(record, entry)
