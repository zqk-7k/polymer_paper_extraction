from copy import deepcopy

from tools.audit_measurement_reference_alignment import compare_reference


def fixture():
    expected = {"standard_record_id": "gt1", "reference_no": "doc1", "article_sample_id": "external-1",
                "standard_property_code": "STD:glass_transition_temperature", "reviewed_unit": "C", "value_min": 86.1, "value_max": 86.1}
    data = {"schema_version": "measurement_publication.v1", "document_id": "doc1", "final": [{
        "measurement_id": "m1", "record": {"standard_property_code": expected["standard_property_code"],
        "sample_id": "s001", "value_raw": "359.2", "unit_raw": "K"}}]}
    return expected, data


def test_converted_value_does_not_establish_reference_sample_identity():
    expected, data = fixture()
    before = deepcopy((expected, data))
    row = compare_reference(expected, data)
    assert row["status"] == "published_value_match_sample_unverified"
    assert row["published_value_matches"][0]["value_comparison"] == "converted_matches_reference_rounding"
    assert not row["fully_verified_match"]
    assert (expected, data) == before


def test_candidates_and_unknown_units_cannot_count_as_published_matches():
    expected, data = fixture()
    data["candidate"] = data.pop("final")
    assert compare_reference(expected, data)["status"] == "unpublished_value_match"
    data["candidate"][0]["record"].update(value_raw="86.1", unit_raw=None)
    row = compare_reference(expected, data)
    assert row["status"] == "unit_review_required"
    assert not row["published_value_matches"]


def test_missing_publication_and_mapping_remain_distinct():
    expected, data = fixture()
    assert compare_reference(expected, None)["status"] == "publication_input_missing"
    expected["standard_property_code"] = None
    assert compare_reference(expected, data)["status"] == "reference_mapping_unresolved"
