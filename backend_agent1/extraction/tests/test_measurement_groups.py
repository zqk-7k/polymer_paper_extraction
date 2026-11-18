from copy import deepcopy

import pytest

from stages.measurement_groups import group_measurement_claims


def fixture():
    item = {"property_id": "p1", "property_name_raw": "Tg", "value_raw": "120", "unit_raw": "C"}
    payload = {"document_id": "test", "property_observations": [item, {**item, "property_id": "p2"}]}
    row = {"collection": "property_observations", "object_id": "p1", "value_raw": "120",
           "source_cell_ids": ["T1:r1:c1"], "evidence_status": "source_cell_verified",
           "property_name_raw": "Tg", "standard_status": "standard_alias", "standard_property_code": "STD:glass_transition_temperature",
           "binding_status": "unresolved", "publication_status": "candidate", "publication_reasons": ["binding_unresolved"]}
    return payload, {"records": [row, {**row, "object_id": "p2"}]}


def test_cross_stage_duplicate_keeps_all_originals_and_stable_group():
    payload, audit = fixture()
    audit["records"][0]["source_stage"] = "stage4"
    audit["records"][1]["source_stage"] = "stage5"
    before = deepcopy((payload, audit))
    result = group_measurement_claims(payload, audit)
    assert result["group_count"] == 1
    assert result["repeated_expression_count"] == 1
    assert [m["original_record"] for m in result["groups"][0]["members"]] == payload["property_observations"]
    audit["records"].reverse()
    assert group_measurement_claims(payload, audit)["groups"][0]["measurement_group_id"] == result["groups"][0]["measurement_group_id"]
    audit["records"].reverse()
    assert (payload, audit) == before


@pytest.mark.parametrize("field,value", [("value_raw", "121"), ("unit_raw", "K"), ("sample_id", "s002"), ("conditions", {"dose": "10 kGy"})])
def test_different_value_unit_subject_or_condition_never_merges(field, value):
    payload, audit = fixture()
    payload["property_observations"][1][field] = value
    audit["records"][1][field] = value
    result = group_measurement_claims(payload, audit)
    assert result["group_count"] == 2
    assert result["differing_source_count"] == 1
    assert all("same_source_claims_differ" in g["review_reasons"] for g in result["groups"])


def test_unverified_paths_are_never_deduplicated_by_equal_value():
    payload, audit = fixture()
    for row in audit["records"]:
        row["source_cell_ids"] = []
        row["evidence_status"] = "unverified"
    result = group_measurement_claims(payload, audit)
    assert result["group_count"] == 2
    assert result["repeated_expression_count"] == 0
