from copy import deepcopy

from stages.series_point_audit import audit_series_points
from tests.test_publication_checks import source_fixture


def fixture():
    payload, inputs = source_fixture()
    scalar = payload["property_observations"][0]
    point = {**scalar, "point_id": "pt001", "coverage_status": "covered", "sample_resolution_status": "resolved",
             "evidence": [{k: v for k, v in payload["evidence"][0].items() if k != "evidence_id"}]}
    point.pop("evidence_ids")
    stage4 = {"document_id": "test", "property_series": [{"series_id": "series001", "property_name_raw": "Tg",
              "sample_resolution_status": "unresolved", "points": [point]}]}
    return inputs["stage0"], {"document_id": "test", "polymer_entities": payload["polymer_entities"]}, inputs["stage3"], stage4


def test_point_subject_is_checked_independently_without_publishing():
    args = fixture()
    before = deepcopy(args)
    result = audit_series_points(*args)
    row = result["records"][0]
    assert row["binding_status"] == "resolved"
    assert row["source_audit_status"] == "passed"
    assert row["publication_status"] == "not_publishable"
    assert "input_incomplete" in row["publication_reasons"]
    assert args == before


def test_wrong_point_subject_and_parent_context_are_not_accepted():
    args = fixture()
    series = args[3]["property_series"][0]
    series["points"][0]["sample_id"] = "s002"
    assert audit_series_points(*args)["records"][0]["binding_status"] == "conflict"
    series["points"][0]["sample_id"] = "s001"
    series["measurement_context"] = {"temperature": "25 C"}
    series["points"][0]["measurement_context"] = {"temperature": "30 C"}
    row = audit_series_points(*args)["records"][0]
    assert "series_point_context_conflict" in row["source_audit_reasons"]


def test_duplicate_points_and_uncovered_points_stay_pending():
    args = fixture()
    points = args[3]["property_series"][0]["points"]
    points.append(deepcopy(points[0]))
    assert all("duplicate_object_id" in r["source_audit_reasons"] for r in audit_series_points(*args)["records"])
    points.pop()
    points[0]["coverage_status"] = "missing"
    assert audit_series_points(*args)["records"][0]["source_audit_status"] == "requires_review"


def test_parent_conditions_are_not_lost_when_point_context_has_nulls():
    args = fixture()
    series = args[3]["property_series"][0]
    series["measurement_context"] = {"method": "DMA"}
    series["points"][0]["measurement_context"] = {"method": None}
    args[0]["elements"][0]["caption"] = "Measured using DSC"
    row = audit_series_points(*args)["records"][0]
    assert "measurement_method_conflict" in row["source_audit_reasons"]
