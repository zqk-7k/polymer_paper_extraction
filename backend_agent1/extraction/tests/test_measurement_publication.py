from copy import deepcopy

from stages.measurement_publication import build_measurement_publication
from tests.test_publication_checks import source_fixture


def fixture():
    payload, inputs = source_fixture()
    payload["samples"] = deepcopy(inputs["stage3"]["samples"])
    inputs["stage2"] = {"document_id": "test", "polymer_entities": payload["polymer_entities"]}
    inputs["stage4"]["document_id"] = "test"
    return payload, inputs


def test_publish_source_checked_scalar_and_preserve_original():
    payload, inputs = fixture()
    before = deepcopy((payload, inputs))
    result = build_measurement_publication(payload, **inputs)
    assert result["counts"]["final"] == 1
    group = result["final"][0]
    assert group["record"]["sample_id"] == "s001"
    assert group["record"]["source_cell_ids"] == ["T1:r0001:c0001"]
    assert group["members"][0]["original_record"] == payload["property_observations"][0]
    assert (payload, inputs) == before


def test_cross_collection_exact_duplicate_is_one_record_and_order_stable():
    payload, inputs = fixture()
    other = deepcopy(payload["property_observations"][0])
    other["specialized_id"] = other.pop("property_id")
    payload["specialized_property_observations"] = [other]
    result = build_measurement_publication(payload, **inputs)
    assert result["counts"]["final"] == 1
    assert result["counts"]["repeated_expression_count"] == 1
    assert len(result["final"][0]["members"]) == 2
    original_id = result["final"][0]["measurement_id"]
    payload["property_observations"][0]["property_id"] = "different_id"
    assert build_measurement_publication(payload, **inputs)["final"][0]["measurement_id"] == original_id


def test_conflicting_sample_cannot_be_hidden_by_correct_claim():
    payload, inputs = fixture()
    other = deepcopy(payload["property_observations"][0])
    other.update(property_id="prop002", sample_id="s002")
    payload["property_observations"].append(other)
    result = build_measurement_publication(payload, **inputs)
    assert not result["final"]
    assert result["counts"]["candidate"] == 1
    assert result["counts"]["not_publishable"] == 1
    assert "same_source_claims_differ" in result["candidate"][0]["publication_reasons"]
    assert result["not_publishable"][0]["record"]["sample_id"] is None


def test_aggregate_not_counted_again_and_quarantine_preserved():
    payload, inputs = fixture()
    item = payload["property_observations"][0]
    item.update(observation_role="aggregate", series_id="series001")
    inputs["stage4"]["warnings"] = [{"code": "preview_objects_quarantined", "objects": [{"object_id": "bad", "candidate_at_rejection": {"value_raw": "120"}}]}]
    result = build_measurement_publication(payload, **inputs)
    assert result["counts"]["measurement_group_count"] == 0
    assert result["aggregate_records"][0]["original_record"] == item
    assert result["quarantined_records"][0]["candidate_at_rejection"]["value_raw"] == "120"


def test_link_to_series_does_not_turn_a_scalar_into_an_aggregate():
    payload, inputs = fixture()
    payload["property_observations"][0].update(observation_role="individual", series_id="series001")
    result = build_measurement_publication(payload, **inputs)
    assert result["counts"]["aggregate_count"] == 0
    assert result["counts"]["source_expression_count"] == 1
    assert result["counts"]["final"] == 1


def test_removed_sample_blocks_publication_and_missing_location_is_preserved():
    payload, inputs = fixture()
    payload["samples"] = []
    result = build_measurement_publication(payload, **inputs)
    assert not result["final"]
    assert "publication_sample_reference_unknown" in result["not_publishable"][0]["publication_reasons"]
    payload["property_observations"][0]["evidence_ids"] = []
    result = build_measurement_publication(payload, **inputs)
    assert result["not_publishable"][0]["record"] is None
    assert result["counts"]["source_expression_count"] == 1


def test_series_point_is_preserved_but_not_published_without_trace():
    from tests.test_series_point_audit import fixture as series_fixture
    stage0, stage2, stage3, stage4 = series_fixture()
    payload = {"document_id": "test", "samples": stage3["samples"], "polymer_entities": stage2["polymer_entities"]}
    result = build_measurement_publication(payload, stage0=stage0, stage2=stage2, stage3=stage3, stage4=stage4)
    assert result["counts"]["not_publishable"] == 1
    member = result["not_publishable"][0]["members"][0]
    assert member["collection"] == "property_series.points"
    assert "input_incomplete" in member["audit"]["publication_reasons"]
