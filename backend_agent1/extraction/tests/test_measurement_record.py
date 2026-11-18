import pytest
from pydantic import ValidationError

from stages.measurement_record import (
    MeasurementRecord,
    build_measurement_id,
    measurement_record_from_candidate,
    publication_audit_for_final,
    publication_decision,
)


def _record(**overrides):
    payload = {
        "measurement_id": "measurement_001",
        "source_stage": "stage4t",
        "source_cell_ids": ["T1:r0001:c0002"],
        "property_name_raw": "Tg (°C)",
        "value_raw": "120",
        "sample_id": "s001",
        "binding_status": "resolved",
        "binding_evidence_ids": ["T1:r0001:c0000"],
    }
    payload.update(overrides)
    return MeasurementRecord.model_validate(payload)


def test_measurement_id_is_order_independent():
    first = build_measurement_id("ref1", ["c2", "c1", "c1"], "std:tg", "120", "°C", {"dose": "5"})
    second = build_measurement_id("ref1", ["c1", "c2"], "std:tg", "120", "°C", {"dose": "5"})
    assert first == second


def test_identity_states_are_explicit():
    assert _record().binding_status == "resolved"
    assert _record(
        sample_id=None, article_sample_key="article_sample_x", binding_status="article_alias_confirmed"
    ).article_sample_key == "article_sample_x"
    assert _record(sample_id=None, entity_id="pe001", binding_status="entity_only").entity_id == "pe001"
    with pytest.raises(ValidationError):
        _record(sample_id=None, binding_status="resolved")


def test_candidate_conversion_keeps_real_source_locations():
    record = measurement_record_from_candidate(
        {
            "observation_id": "o1",
            "cell_id": "T1:r0001:c0002",
            "table_id": "T1",
            "property_name_raw": "Tg (°C)",
            "value_raw": "120",
            "unit_raw": "°C",
        },
        document_id="ref1",
        source_stage="stage4t",
    )
    assert record is not None
    assert record.source_cell_ids == ["T1:r0001:c0002"]
    assert record.source_block_ids == ["T1"]
    assert record.binding_status == "unresolved"

    mapped = measurement_record_from_candidate(
        {
            "cell_id": "T1:r0001:c0003",
            "table_id": "T1",
            "property_name_raw": "Tg",
            "value_raw": "120",
            "unit_raw": "C",
        },
        document_id="ref1",
        source_stage="stage4t",
    )
    assert mapped is not None
    assert mapped.standard_status == "standard_alias"
    assert mapped.standard_property_code == "STD:glass_transition_temperature"


def test_publication_gate_separates_alias_policy_from_evidence_failure():
    alias = publication_decision(
        path_status="complete", standard_status="standard_exact", unit_status="confirmed",
        binding_status="article_alias_confirmed", evidence_ids=["e1"],
    )
    assert alias == {"publication_status": "candidate", "publication_reasons": ["article_alias_policy_block"]}
    allowed = publication_decision(
        path_status="complete", standard_status="standard_exact", unit_status="confirmed",
        binding_status="article_alias_confirmed", evidence_ids=["e1"], allow_article_alias=True,
    )
    assert allowed["publication_status"] == "final"
    missing = publication_decision(
        path_status="complete", standard_status="standard_exact", unit_status="confirmed",
        binding_status="resolved", evidence_ids=[],
    )
    assert missing["publication_status"] == "not_publishable"
    assert "evidence_missing" in missing["publication_reasons"]


def test_candidate_mapping_is_recomputed_instead_of_trusting_claims():
    record = measurement_record_from_candidate({
        "cell_id": "T1:r0001:c0001", "property_name_raw": "Tg", "value_raw": "120",
        "unit_raw": "MPa", "standard_status": "standard_exact",
        "standard_property_code": "STD:melting_temperature",
    }, document_id="test", source_stage="stage4t")
    assert record.standard_status == "standard_candidate"
    assert record.standard_property_code == "STD:glass_transition_temperature"
    assert {"unit_family_conflict", "standard_code_conflict"} <= set(record.standard_mapping_reasons)


def test_final_publication_audit_reports_status_and_reasons():
    audit = publication_audit_for_final({
        "property_observations": [{
            "property_id": "prop001",
            "property_name_raw": "Tg",
            "property_code": "std:tg",
            "value_raw": "120",
            "unit_raw": "°C",
            "sample_id": "s001",
            "evidence_ids": ["e1"],
        }],
        "unresolved_property_observations": [{
            "unresolved_id": "uprop001",
            "property_name_raw": "unknown property",
            "value_raw": "x",
            "entity_id": "pe001",
            "evidence_ids": ["e2"],
        }, {
            "unresolved_id": "uprop002",
            "property_name_raw": "unknown property",
            "value_raw": "y",
            "entity_id": "pe001",
            "evidence_ids": [],
        }],
    })
    by_id = {item["object_id"]: item for item in audit["records"]}
    assert by_id["prop001"]["publication_status"] == "not_publishable"
    assert "evidence_reference_unknown" in by_id["prop001"]["publication_reasons"]
    assert "source_input_missing" in by_id["prop001"]["publication_reasons"]
    assert by_id["uprop001"]["publication_status"] == "not_publishable"
    assert "standard_field_unresolved" in by_id["uprop001"]["publication_reasons"]
    assert by_id["uprop002"]["publication_status"] == "not_publishable"
    assert audit["counts"]["publication_status"]["final"] == 0
