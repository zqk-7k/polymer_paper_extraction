from __future__ import annotations

from schema.polymer_schema import Stage0Document, Stage4Document, Stage0Element
from stages.stage4r_unified_preview import unify_documents
from stages.table_grid import parse_table_cells


def _stage0() -> Stage0Document:
    body = (
        "<table><tr><td>Sample</td><td>Tg (°C)</td></tr>"
        "<tr><td>Sample-A</td><td>120</td></tr></table>"
    )
    table = Stage0Element(
        block_id="T_1",
        type="table",
        page=1,
        source_block_index=0,
        table_body=body,
        table_cells=parse_table_cells(body, "T_1"),
    )
    return Stage0Document.model_validate({
        "schema_version": "1.1",
        "source_document_schema_version": "1.0",
        "document_id": "reference_no_test",
        "paper": {
            "ref_no": "reference_no_test",
            "pdf_filename": "test.pdf",
            "source_pdf_path": "test.pdf",
            "organized_pdf_path": "test.pdf",
            "metadata_status": "failed",
            "metadata_extraction": {},
        },
        "source_files": {},
        "ocr": {},
        "elements": [table.model_dump(mode="json")],
        "warnings": [],
    })


def _stage2() -> dict:
    return {
        "polymer_entities": [{
            "entity_id": "pe001",
            "canonical_name": "Polymer A",
            "source_names": ["PA"],
        }],
    }


def _stage3(*, duplicate_label: bool = False) -> dict:
    samples = [{
        "sample_id": "s001",
        "sample_label_raw": "Sample-A",
        "polymer_name": "Polymer A",
        "refers_to_entity": "pe001",
    }]
    if duplicate_label:
        samples.append({
            "sample_id": "s002",
            "sample_label_raw": "Sample-A",
            "polymer_name": "Polymer A treated",
            "refers_to_entity": "pe001",
        })
    return {"samples": samples}


def _provenance() -> dict:
    return {
        "stage": "stage4_property",
        "provider": "test",
        "model": "test-model",
        "models": ["test-model"],
        "prompt_id": "test",
        "prompt_version": "1",
        "prompt_sha256": "0" * 64,
        "vocabulary_sha256": "1" * 64,
        "input_hash": "2" * 64,
        "model_config_hash": "3" * 64,
        "cache_key": "4" * 64,
        "output_schema_version": "property_observation_schema.v7",
        "implementation_version": "1.7.10",
        "context_block_count": 1,
        "context_chars": 1,
        "call_count": 1,
        "status": "success",
    }


def _stage4() -> dict:
    return {
        "schema_version": "1.0",
        "document_id": "reference_no_test",
        "measurement_conditions": [],
        "properties": [],
        "unresolved_properties": [],
        "property_series": [],
        "provenance": _provenance(),
        "warnings": [],
    }


def _candidate(**updates) -> dict:
    value = {
        "observation_id": "T_1:T_1:r0001:c0001",
        "table_id": "T_1",
        "sample_label_raw": "Sample-A",
        "property_name_raw": "Tg (°C)",
        "property_name_normalized": "glass_transition_temperature",
        "semantic_label": None,
        "candidate_class": "official_property",
        "value_raw": "120",
        "value_kind": "numeric_scalar",
        "unit_raw": "°C",
        "unit_normalized": "°C",
        "conditions": {},
        "cell_id": "T_1:r0001:c0001",
        "row_index": 1,
        "column_index": 1,
        "evidence_locator": {
            "header_path": ["Tg (°C)"],
        },
    }
    value.update(updates)
    return value


def _sidecar(*candidates: dict) -> dict:
    return {"tables": [{"table_id": "T_1", "observations": list(candidates)}]}


def _condition() -> dict:
    evidence = {
        "block_id": "P_1",
        "page": 1,
        "bbox": None,
        "source_type": "text",
        "source_sentence": "Sample-A showed a Tg of 120 °C.",
        "table_locator": None,
    }
    return {
        "condition_id": "mc001",
        "temperature": None,
        "frequency": None,
        "humidity": None,
        "pressure": None,
        "wavelength": None,
        "other_conditions": {},
        "other_condition_evidence": {},
        "condition_status": "not_reported",
        "evidence": evidence,
        "confidence": None,
    }


def _text_property() -> dict:
    return {
        "property_id": "prop001",
        "sample_id": "s001",
        "property_name_raw": "Tg",
        "property_name_normalized": "glass_transition_temperature",
        "property_code": None,
        "property_category": None,
        "molecular_weight_type": None,
        "determination_method_raw": None,
        "observation_group_id": None,
        "observation_role": "single",
        "series_id": None,
        "series_ids": None,
        "value_raw": "120",
        "value_min": None,
        "value_max": None,
        "unit_raw": "°C",
        "unit_normalized": "°C",
        "measurement_condition_id": "mc001",
        "measurement_context": {"condition_status": "not_reported"},
        "source_type": "text",
        "evidence": [_condition()["evidence"]],
        "confidence": None,
    }


def test_unique_stage3_sample_integrates_official_property() -> None:
    merged, audit = unify_documents(
        _stage0(), _stage2(), _stage3(), _stage4(), _sidecar(_candidate())
    )

    assert isinstance(merged, Stage4Document)
    assert len(merged.properties) == 1
    assert merged.properties[0].sample_id == "s001"
    assert merged.properties[0].evidence[0].table_locator["cell_id"] == (
        "T_1:r0001:c0001"
    )
    assert audit["summary"]["integrated_count"] == 1
    assert audit["summary"]["sample_resolution_status_counts"] == {
        "matched": 1
    }


def test_unmatched_and_ambiguous_samples_remain_auditable() -> None:
    unmatched = _candidate(sample_label_raw="Unknown", observation_id="candidate-1")
    ambiguous = _candidate(observation_id="candidate-2")
    merged, audit = unify_documents(
        _stage0(),
        _stage2(),
        _stage3(duplicate_label=True),
        _stage4(),
        _sidecar(unmatched, ambiguous),
    )

    assert merged.properties == []
    assert audit["summary"]["unmatched_sample_count"] == 1
    assert audit["summary"]["ambiguous_sample_count"] == 1


def test_exact_text_table_duplicate_merges_evidence() -> None:
    stage4 = _stage4()
    stage4["measurement_conditions"] = [_condition()]
    stage4["properties"] = [_text_property()]
    merged, audit = unify_documents(
        _stage0(), _stage2(), _stage3(), stage4, _sidecar(_candidate())
    )

    assert len(merged.properties) == 1
    assert len(merged.properties[0].evidence) == 2
    assert audit["summary"]["duplicate_merged_count"] == 1
    assert audit["candidate_outcomes"][0]["relationship"] == "exact"


def test_same_cell_semantic_conflict_quarantines_stage4_property() -> None:
    stage4 = _stage4()
    stage4["measurement_conditions"] = [_condition()]
    property_item = _text_property()
    property_item["source_type"] = "table"
    property_item["evidence"][0] = {
        "block_id": "T_1",
        "page": 1,
        "bbox": None,
        "source_type": "table",
        "source_sentence": "120",
        "table_locator": {
            "table_id": "T_1",
            "cell_id": "T_1:r0001:c0001",
            "row_index": 1,
            "column_index": 1,
            "row_label": "Sample-A",
            "column_label": "Tg (°C)",
            "cell_value": "120",
        },
    }
    stage4["properties"] = [property_item]
    characteristic = _candidate(
        property_name_normalized=None,
        semantic_label="char_yield",
        candidate_class="material_characteristic",
    )
    merged, audit = unify_documents(
        _stage0(), _stage2(), _stage3(), stage4, _sidecar(characteristic)
    )

    assert merged.properties == []
    assert merged.measurement_conditions == []
    assert audit["summary"]["source_conflict_count"] == 1
    assert audit["summary"]["quarantined_stage4_property_count"] == 1


def test_material_candidate_keeps_sample_resolution_in_audit() -> None:
    characteristic = _candidate(
        property_name_normalized=None,
        semantic_label="xray_diffraction_peak",
        candidate_class="material_characteristic",
    )
    merged, audit = unify_documents(
        _stage0(), _stage2(), _stage3(), _stage4(), _sidecar(characteristic)
    )

    assert merged.properties == []
    outcome = audit["candidate_outcomes"][0]
    assert outcome["status"] == "retained_candidate"
    assert outcome["sample_resolution_status"] == "matched"
    assert outcome["sample_id"] == "s001"


def test_different_conditions_do_not_merge_equal_text_and_table_values() -> None:
    stage4 = _stage4()
    stage4["measurement_conditions"] = [_condition()]
    stage4["properties"] = [_text_property()]
    candidate = _candidate(conditions={"temperature_celsius": 100})
    merged, audit = unify_documents(
        _stage0(), _stage2(), _stage3(), stage4, _sidecar(candidate)
    )

    assert len(merged.properties) == 2
    assert audit["summary"]["integrated_count"] == 1


def test_invalid_candidate_is_retained_without_blocking_document() -> None:
    invalid = _candidate(value_raw="")
    merged, audit = unify_documents(
        _stage0(), _stage2(), _stage3(), _stage4(), _sidecar(invalid)
    )

    assert merged.properties == []
    assert audit["summary"]["invalid_candidate_count"] == 1
    assert audit["candidate_outcomes"][0]["reason"] == (
        "missing_required_fields:value_raw"
    )


def test_unified_document_is_idempotent_for_cached_preview_rerun() -> None:
    first, _ = unify_documents(
        _stage0(), _stage2(), _stage3(), _stage4(), _sidecar(_candidate())
    )
    second, _ = unify_documents(
        _stage0(),
        _stage2(),
        _stage3(),
        first.model_dump(mode="json"),
        _sidecar(_candidate()),
    )

    assert second.model_dump(mode="json") == first.model_dump(mode="json")
