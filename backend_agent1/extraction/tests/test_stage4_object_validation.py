from copy import deepcopy

from stages.stage4_object_validation import validate_objects, object_key
from stages.series_input_scope import verify_series_input_trace, point_input_scope
from stages.request_trace import content_hash
from tests.test_audit_stage4_request_trace import fixture as traced_fixture
from tests.test_stage4_property import FakeClient, SeriesClient, stage0_document, stage2_document, stage3_document


def payload(client=FakeClient):
    return client().call_json("", "").data


def test_bad_scalar_does_not_certify_itself_or_block_valid_sibling(tmp_path):
    stage = payload()
    good = stage["properties"][0]
    bad = deepcopy(good)
    bad.update(property_id="prop099", value_raw="99999", value_min=99999, value_max=99999)
    stage["properties"].append(bad)
    before = deepcopy(stage)
    trace, inputs, _ = traced_fixture(tmp_path)
    stage.update(document_id=inputs["stage0"]["document_id"], provenance={"status": "candidate_partial"},
                 warnings=[{"code": "preview_semantic_validation_bypassed"}])
    trace.finish(output=stage)
    proof = verify_series_input_trace(inputs["stage0"], inputs["stage2"], inputs["stage3"], stage, trace.data)
    assert proof["verified"]
    assert proof["object_semantic_audit"]["accepted_count"] == 1
    assert point_input_scope({}, good, proof)["input_complete"]
    assert not point_input_scope({}, bad, proof)["input_complete"]
    changed = deepcopy(good)
    changed["unit_raw"] = "invented"
    assert not point_input_scope({}, changed, proof)["input_complete"]
    assert stage["properties"] == before["properties"]
    trace.data["attempts"][0]["request"]["user_message"] += "changed"
    assert not verify_series_input_trace(inputs["stage0"], inputs["stage2"], inputs["stage3"], stage, trace.data)["verified"]


def test_shared_condition_failure_blocks_all_dependent_scalars():
    data = payload()
    data["measurement_conditions"][0]["temperature"]["raw"] = "99999 K"
    result = validate_objects(data, stage0_document(), stage2_document(), stage3_document())
    assert result["accepted_count"] == 0


def test_multi_subject_projection_preserves_parent_and_checks_method():
    data = payload(SeriesClient)
    series = data["property_series"][0]
    series.update(sample_id=None, entity_id=None, sample_resolution_status="unresolved")
    point = series["points"][0]
    point.update(sample_id="s001", entity_id="pe001", sample_resolution_status="resolved")
    point["measurement_context"] = deepcopy(series["measurement_context"])
    before = deepcopy(data)
    result = validate_objects(data, stage0_document(), stage2_document(), stage3_document())
    assert object_key(series, point) in result["accepted_object_hashes"], result
    assert data == before
    series["determination_method_raw"] = "invented unrelated method"
    result = validate_objects(data, stage0_document(), stage2_document(), stage3_document())
    assert result["accepted_count"] == 0
