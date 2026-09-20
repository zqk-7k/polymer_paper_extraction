from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from schema.polymer_schema import Stage4Document
from stages.stage4p_publication_recovery import (
    AUDIT_NAME,
    BACKUP_NAME,
    OUTPUT_NAME,
    recover_stage4_document,
    run_stage4p,
)


REF = "reference_no_0000001"


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


def _stage0(cell_text: str = "120", *, sample_label: str = "P1") -> dict:
    cells = [
        {
            "cell_id": "T_1:r0000:c0000",
            "row_index": 0,
            "column_index": 0,
            "text": "Sample",
            "is_header": True,
        },
        {
            "cell_id": "T_1:r0000:c0001",
            "row_index": 0,
            "column_index": 1,
            "text": "Tg (°C)",
            "is_header": True,
        },
        {
            "cell_id": "T_1:r0001:c0000",
            "row_index": 1,
            "column_index": 0,
            "text": sample_label,
        },
        {
            "cell_id": "T_1:r0001:c0001",
            "row_index": 1,
            "column_index": 1,
            "text": cell_text,
        },
    ]
    return {
        "schema_version": "1.1",
        "source_document_schema_version": "1.0",
        "document_id": REF,
        "paper": {
            "ref_no": REF,
            "pdf_filename": "paper.pdf",
            "source_pdf_path": "paper.pdf",
            "organized_pdf_path": "paper.pdf",
            "metadata_status": "failed",
            "metadata_extraction": {},
        },
        "source_files": {},
        "ocr": {},
        "elements": [{
            "block_id": "T_1",
            "type": "table",
            "page": 3,
            "bbox": [10.0, 20.0, 300.0, 400.0],
            "source_block_index": 0,
            "caption": "Thermal properties",
            "table_body": "<table><tr><td>Sample</td><td>Tg (°C)</td></tr>"
            f"<tr><td>{sample_label}</td><td>{cell_text}</td></tr></table>",
            "table_cells": cells,
        }],
        "warnings": [],
    }


def _stage2() -> dict:
    return {
        "document_id": REF,
        "polymer_entities": [{
            "entity_id": "pe001",
            "polymer_name": "Polymer One",
            "source_names": ["P1"],
        }],
    }


def _stage3(*, duplicate_label: bool = False) -> dict:
    samples = [{
        "sample_id": "s001",
        "sample_label_raw": "P1",
        "polymer_name": "Polymer One",
        "refers_to_entity": "pe001",
    }]
    if duplicate_label:
        samples.append({
            "sample_id": "s002",
            "sample_label_raw": "P1",
            "polymer_name": "Polymer One, annealed",
            "refers_to_entity": None,
        })
    return {"document_id": REF, "samples": samples}


def _empty_stage4() -> dict:
    return {
        "schema_version": "1.0",
        "document_id": REF,
        "measurement_conditions": [],
        "properties": [],
        "unresolved_properties": [],
        "property_series": [],
        "provenance": _provenance(),
        "warnings": [],
    }


def _series_stage0(*, response_value: str = "81", speed_value: str = "7") -> dict:
    payload = _stage0()
    cells = [
        {
            "cell_id": "T_1:r0000:c0000",
            "row_index": 0,
            "column_index": 0,
            "text": "Blend Composition (mol % PEN)",
            "is_header": True,
        },
        {
            "cell_id": "T_1:r0000:c0001",
            "row_index": 0,
            "column_index": 1,
            "text": "Extruder Screw Speed (rpm)",
            "is_header": True,
        },
        {
            "cell_id": "T_1:r0000:c0002",
            "row_index": 0,
            "column_index": 2,
            "text": "Glass Transition Temperature Tg (°C)",
            "is_header": True,
        },
        {
            "cell_id": "T_1:r0001:c0000",
            "row_index": 1,
            "column_index": 0,
            "text": "20",
        },
        {
            "cell_id": "T_1:r0001:c0001",
            "row_index": 1,
            "column_index": 1,
            "text": speed_value,
        },
        {
            "cell_id": "T_1:r0001:c0002",
            "row_index": 1,
            "column_index": 2,
            "text": response_value,
        },
    ]
    payload["elements"][0].update({
        "table_body": (
            "<table><tr><td>Blend Composition (mol % PEN)</td>"
            "<td>Extruder Screw Speed (rpm)</td>"
            "<td>Glass Transition Temperature Tg (°C)</td></tr>"
            f"<tr><td>20</td><td>{speed_value}</td>"
            f"<td>{response_value}</td></tr></table>"
        ),
        "table_cells": cells,
    })
    return payload


def _series_stage4(
    *,
    value_raw: str = "81",
    value_min: float = 81.0,
    value_max: float = 81.0,
    coordinate_value: str = "7",
    normalized_property: str | None = "glass_transition_temperature",
    normalized_unit: str | None = "°C",
    entity_id: str = "pe001",
) -> dict:
    context = {
        "temperature": None,
        "frequency": None,
        "humidity": None,
        "pressure": None,
        "wavelength": None,
        "other_conditions": {},
        "other_condition_evidence": {},
        "other_condition_evidence_ids": {},
        "condition_status": "not_reported",
    }
    table_evidence = {
        "block_id": "T_1",
        "page": 3,
        "bbox": [10.0, 20.0, 300.0, 400.0],
        "source_type": "table",
    }
    stage4 = _empty_stage4()
    stage4["property_series"] = [{
        "series_id": "series001",
        "sample_id": "s001",
        "entity_id": entity_id,
        "sample_resolution_status": "resolved",
        "property_name_raw": "Glass Transition Temperature Tg (°C)",
        "property_name_normalized": normalized_property,
        "property_code": "P3110",
        "property_category": "thermal_property",
        "determination_method_raw": None,
        "unit_raw": "°C" if normalized_unit else None,
        "unit_normalized": normalized_unit,
        "measurement_context": context,
        "points": [{
            "point_id": "pt001",
            "observation_role": "series_point",
            "sample_id": "s001",
            "entity_id": entity_id,
            "sample_resolution_status": "resolved",
            "coordinates": [
                {
                    "name_raw": "Blend Composition (mol % PEN)",
                    "value_raw": "20",
                    "unit_raw": "mol %",
                    "evidence": {
                        **table_evidence,
                        "source_sentence": "20",
                        "table_locator": {
                            "table_id": "T_1",
                            "row_label": "20",
                            "column_label": "Blend Composition (mol % PEN)",
                            "cell_value": "20",
                            "cell_id": "T_1:r0001:c0000",
                            "row_index": 1,
                            "column_index": 0,
                        },
                    },
                },
                {
                    "name_raw": "Extruder Screw Speed (rpm)",
                    "value_raw": coordinate_value,
                    "unit_raw": "rpm",
                    "evidence": {
                        **table_evidence,
                        "source_sentence": coordinate_value,
                        "table_locator": {
                            "table_id": "T_1",
                            "row_label": f"20 mol % PEN, {coordinate_value} rpm",
                            "column_label": "Extruder Screw Speed (rpm)",
                            "cell_value": coordinate_value,
                            "cell_id": None,
                            "row_index": None,
                            "column_index": None,
                        },
                    },
                },
            ],
            "value_raw": value_raw,
            "value_min": value_min,
            "value_max": value_max,
            "unit_raw": "°C" if normalized_unit else None,
            "unit_normalized": normalized_unit,
            "measurement_context": context,
            "coverage_status": "covered",
            "evidence": [{
                **table_evidence,
                "source_sentence": value_raw,
                "table_locator": {
                    "table_id": "T_1",
                    "row_label": "20",
                    "column_label": "Glass Transition Temperature Tg (°C)",
                    "cell_value": value_raw,
                    "cell_id": "T_1:r0001:c0002",
                    "row_index": 1,
                    "column_index": 2,
                },
            }],
            "confidence": {"score": 0.9},
        }],
        "coverage": {
            "expected": 1,
            "covered": 1,
            "missing": 0,
            "not_applicable": 0,
            "ratio": 1.0,
        },
        "evidence": [{
            **table_evidence,
            "source_sentence": "Glass Transition Temperature Tg (°C)",
            "table_locator": {
                "table_id": "T_1",
                "row_label": "20",
                "column_label": "Glass Transition Temperature Tg (°C)",
                "cell_value": "Glass Transition Temperature Tg (°C)",
                "cell_id": "T_1:r0000:c0002",
                "row_index": 0,
                "column_index": 2,
            },
        }],
        "confidence": {"score": 0.9},
    }]
    return stage4


def _candidate(**updates: object) -> dict:
    value = {
        "observation_id": "T_1:T_1:r0001:c0001",
        "table_id": "T_1",
        "sample_label_raw": "P1",
        "property_name_raw": "Tg (°C)",
        "property_name_normalized": "glass_transition_temperature",
        "semantic_label": None,
        "candidate_class": "official_property",
        "measurement_role": "reported_unknown",
        "value_raw": "120",
        "value_min": 120.0,
        "value_max": 120.0,
        "value_kind": "numeric_scalar",
        "value_has_footnote": False,
        "unit_raw": "°C",
        "unit_normalized": "°C",
        "cell_id": "T_1:r0001:c0001",
        "row_index": 1,
        "column_index": 1,
        "conditions": {},
        "evidence": {
            "table_id": "T_1",
            "cell_id": "T_1:r0001:c0001",
            "row_index": 1,
            "column_index": 1,
        },
        "evidence_locator": {
            "table_id": "T_1",
            "cell_id": "T_1:r0001:c0001",
            "row_index": 1,
            "column_index": 1,
            "row_label": "P1",
            "column_label": "Tg (°C)",
        },
        "publication_gate": {
            "status": "candidate_only",
            "target": "property_observation",
            "blockers": ["sample_not_resolved"],
        },
    }
    value.update(updates)
    return value


def _shadow(*candidates: dict) -> dict:
    return {
        "document_id": REF,
        "tables": [{"table_id": "T_1", "observations": list(candidates)}],
    }


def _evidence(cell_text: str = "120") -> dict:
    return {
        "block_id": "T_1",
        "page": 3,
        "bbox": [10.0, 20.0, 300.0, 400.0],
        "source_type": "table",
        "source_sentence": cell_text,
        "table_locator": {
            "table_id": "T_1",
            "cell_id": "T_1:r0001:c0001",
            "row_index": 1,
            "column_index": 1,
            "row_label": "P1",
            "column_label": "Tg (°C)",
            "cell_value": cell_text,
        },
    }


def _published_specialized() -> dict:
    return {
        "specialized_id": "sp001",
        "source_field": "crystallinity",
        "semantic_label": "crystallinity",
        "variant": None,
        "value_kind": "numeric_scalar",
        "value_raw": "120",
        "value_min": 120,
        "value_max": 120,
        "unit_raw": "%",
        "unit_normalized": "%",
        "unit_status": "normalized",
        "method_raw": None,
        "sample_id": "s001",
        "sample_resolution_status": "resolved",
        "source_stage": "stage4t",
        "evidence": [_evidence()],
        "evidence_ids": [],
        "publication_status": "published",
        "reason": None,
    }


def _pre_unified() -> dict:
    payload = _empty_stage4()
    payload["measurement_conditions"] = [{
        "condition_id": "mc001",
        "temperature": None,
        "frequency": None,
        "humidity": None,
        "pressure": None,
        "wavelength": None,
        "other_conditions": {},
        "other_condition_evidence": {},
        "condition_status": "not_reported",
        "evidence": _evidence(),
        "confidence": None,
    }]
    payload["properties"] = [{
        "property_id": "prop001",
        "sample_id": "s001",
        "property_name_raw": "Tg (°C)",
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
        "value_min": 120.0,
        "value_max": 120.0,
        "unit_raw": "°C",
        "unit_normalized": "°C",
        "measurement_condition_id": "mc001",
        "measurement_context": {"condition_status": "not_reported"},
        "source_type": "table",
        "evidence": [_evidence()],
        "confidence": None,
    }]
    Stage4Document.model_validate(payload)
    return payload


def test_shadow_candidate_publishes_as_complete_stage4_objects() -> None:
    merged, audit = recover_stage4_document(
        _stage0(), _stage2(), _stage3(), _empty_stage4(),
        _shadow(_candidate()), {}, {},
    )

    assert isinstance(merged, Stage4Document)
    assert len(merged.properties) == 1
    assert len(merged.measurement_conditions) == 1
    prop = merged.properties[0]
    assert prop.property_id == "prop001"
    assert prop.measurement_condition_id == "mc001"
    assert prop.sample_id == "s001"
    assert prop.property_name_normalized == "glass_transition_temperature"
    assert prop.evidence[0].page == 3
    assert prop.evidence[0].bbox == (10.0, 20.0, 300.0, 400.0)
    assert prop.evidence[0].table_locator["cell_id"] == "T_1:r0001:c0001"
    assert audit["summary"]["published_count"] == 1
    assert audit["gold_visible_at_runtime"] is False


def test_publication_recovery_preserves_published_specialized_channel() -> None:
    stage4 = _empty_stage4()
    stage4["specialized_property_observations"] = [_published_specialized()]

    merged, _ = recover_stage4_document(
        _stage0(), _stage2(), _stage3(), stage4, _shadow(), {}
    )

    assert [
        item.specialized_id
        for item in merged.specialized_property_observations
    ] == ["sp001"]


def test_plain_c_temperature_unit_is_a_supported_encoding_variant() -> None:
    merged, audit = recover_stage4_document(
        _stage0(), _stage2(), _stage3(), _empty_stage4(),
        _shadow(_candidate(unit_raw="C", unit_normalized="C")), {}, {},
    )
    assert audit["summary"]["published_count"] == 1
    assert merged.properties[0].unit_normalized == "°C"


def _crystallinity_candidate(**updates: object) -> dict:
    candidate = _candidate(
        sample_label_raw="100% Amylopectin (AP)",
        property_name_raw="Degree of Crystal-linity at 110 °C",
        property_name_normalized=None,
        semantic_label="crystallinity",
        candidate_class="material_characteristic",
        value_raw="81",
        value_min=81.0,
        value_max=81.0,
        unit_raw=None,
        unit_normalized=None,
    )
    candidate["direction"] = "row_samples"
    candidate["evidence_locator"].update({
        "row_label": "100% Amylopectin (AP)",
        "column_label": "Degree of Crystal-linity at 110 °C",
        "header_path": ["Degree of Crystal-linity at 110 °C"],
    })
    candidate.update(updates)
    return candidate


def test_sample_axis_percent_is_not_property_unit() -> None:
    candidate = _crystallinity_candidate()
    stage3 = _stage3_with_samples(_sample("s001", "100% Amylopectin (AP)"))
    stage0 = _stage0("81", sample_label="100% Amylopectin (AP)")
    merged, audit = recover_stage4_document(
        stage0, _stage2(), stage3, _empty_stage4(),
        _shadow(candidate), {}, {},
    )
    assert merged.properties == []
    assert any(
        row.get("reason") == "crystallinity_percent_source_unverified"
        for row in audit["candidate_outcomes"]
    )


def test_guarded_crystallinity_inference_and_unique_acronym_publish() -> None:
    candidate = _crystallinity_candidate(
        unit_raw="%",
        unit_normalized="%",
        unit_location="inferred_property_convention",
        unit_inference_basis="degree_crystallinity_column_0_100",
    )
    stage3 = _stage3_with_samples(_sample("s001", "100% Amylopectin"))
    stage0 = _stage0("81", sample_label="100% Amylopectin (AP)")
    merged, audit = recover_stage4_document(
        stage0, _stage2(), stage3, _empty_stage4(),
        _shadow(candidate), {}, {},
    )
    assert len(merged.properties) == 1
    prop = merged.properties[0]
    assert (prop.sample_id, prop.value_min, prop.unit_normalized) == ("s001", 81.0, "%")
    assert prop.evidence[0].table_locator["cell_id"] == "T_1:r0001:c0001"
    published = next(row for row in audit["candidate_outcomes"] if row["status"] == "published")
    assert published["sample_resolution_basis"] == "unique_trailing_acronym_stage3_alias"


@pytest.mark.parametrize(
    ("location", "basis"),
    [
        ("not_found", None),
        ("inferred_property_convention", None),
        ("inferred_property_convention", "untrusted_guess"),
    ],
)
def test_untrusted_crystallinity_percent_provenance_is_rejected(
    location: str,
    basis: str | None,
) -> None:
    candidate = _crystallinity_candidate(
        unit_raw="%",
        unit_normalized="%",
        unit_location=location,
        unit_inference_basis=basis,
    )
    stage3 = _stage3_with_samples(_sample("s001", "100% Amylopectin (AP)"))
    merged, audit = recover_stage4_document(
        _stage0("81", sample_label="100% Amylopectin (AP)"),
        _stage2(), stage3, _empty_stage4(), _shadow(candidate), {}, {},
    )
    assert merged.properties == []
    assert any(
        row.get("reason") == "crystallinity_percent_source_unverified"
        for row in audit["candidate_outcomes"]
    )


def test_trailing_acronym_alias_must_be_unique() -> None:
    candidate = _crystallinity_candidate(
        unit_raw="%",
        unit_normalized="%",
        unit_location="inferred_property_convention",
        unit_inference_basis="degree_crystallinity_column_0_100",
    )
    stage3 = _stage3_with_samples(
        _sample("s001", "100% Amylopectin"),
        _sample("s002", "100% Amylopectin"),
    )
    merged, audit = recover_stage4_document(
        _stage0("81", sample_label="100% Amylopectin (AP)"),
        _stage2(), stage3, _empty_stage4(), _shadow(candidate), {}, {},
    )
    assert merged.properties == []
    assert any(
        row.get("reason") == "ambiguous_trailing_acronym_alias"
        for row in audit["candidate_outcomes"]
    )


@pytest.mark.parametrize(
    "suffix",
    ["(MW:2000)", "(110 C)", "(50/50)", "(a)", "(A)", "(blend)"],
)
def test_trailing_parenthetical_non_acronyms_are_not_removed(suffix: str) -> None:
    label = f"Polymer One {suffix}"
    candidate = _candidate(sample_label_raw=label)
    candidate["evidence_locator"]["row_label"] = label
    merged, audit = recover_stage4_document(
        _stage0(sample_label=label), _stage2(), _stage3(), _empty_stage4(),
        _shadow(candidate), {}, {},
    )
    assert merged.properties == []
    assert not any(
        row.get("sample_resolution_basis") == "unique_trailing_acronym_stage3_alias"
        for row in audit["candidate_outcomes"]
    )


def test_transposed_axis_is_repaired_only_when_column_matches_stage3_sample() -> None:
    candidate = _candidate(sample_label_raw="Tg (°C)")
    candidate["evidence_locator"] = {
        "table_id": "T_1",
        "cell_id": "T_1:r0001:c0001",
        "row_index": 1,
        "column_index": 1,
        "row_label": "Tg (°C)",
        "column_label": "P1",
    }
    merged, audit = recover_stage4_document(
        _stage0(), _stage2(), _stage3(), _empty_stage4(),
        _shadow(candidate), {}, {},
    )

    assert len(merged.properties) == 1
    assert merged.properties[0].sample_id == "s001"
    locator = merged.properties[0].evidence[0].table_locator
    assert locator["row_label"] == "Tg (°C)"
    assert locator["column_label"] == "P1"
    published = next(
        row for row in audit["candidate_outcomes"] if row["status"] == "published"
    )
    assert published["axis_orientation_repaired"] is True


def test_specialized_molecular_weight_uses_direct_cell_and_regular_schema() -> None:
    stage0 = _stage0("16 600")
    stage0["elements"][0]["table_cells"][1]["text"] = "Mn (g/mol)"
    candidate = _candidate(
        property_name_raw="Mn (g/mol)",
        property_name_normalized=None,
        semantic_label="molecular_weight",
        property_variant="number_average",
        candidate_class="material_characteristic",
        value_raw="16 600",
        value_min=None,
        value_max=None,
        unit_raw="g/mol",
        unit_normalized="g/mol",
    )
    candidate["evidence_locator"]["column_label"] = "Mn (g/mol)"
    merged, audit = recover_stage4_document(
        stage0, _stage2(), _stage3(), _empty_stage4(),
        _shadow(candidate), {}, {},
    )

    assert audit["summary"]["published_count"] == 1
    prop = merged.properties[0]
    assert prop.property_name_normalized == "mn"
    assert prop.molecular_weight_type == "Mn"
    assert prop.value_min == 16600.0
    assert prop.unit_normalized == "g/mol"


def _published_malformed_mn(
    *,
    evidence_cell_value: str = "19 800",
) -> dict:
    item = _published_specialized()
    item.update({
        "source_field": "average_molecular_weight",
        "semantic_label": "molecular_weight",
        "variant": "number_average",
        "value_raw": "19 800",
        "value_min": 19.0,
        "value_max": 800.0,
        "unit_raw": "g/mol",
        "unit_normalized": "g/mol",
    })
    item["evidence"] = [_evidence(evidence_cell_value)]
    item["evidence"][0]["table_locator"]["column_label"] = "Mn (g/mol)"
    return item


def test_repairs_spaced_thousands_specialized_and_suppresses_normal_duplicate() -> None:
    stage0 = _stage0("19 800")
    stage0["elements"][0]["table_cells"][1]["text"] = "Mn (g/mol)"
    stage4 = _empty_stage4()
    stage4["specialized_property_observations"] = [_published_malformed_mn()]
    candidate = _candidate(
        property_name_raw="Mn (g/mol)",
        property_name_normalized=None,
        semantic_label="molecular_weight",
        property_variant="number_average",
        candidate_class="material_characteristic",
        value_raw="19 800",
        value_min=19800.0,
        value_max=19800.0,
        unit_raw="g/mol",
        unit_normalized="g/mol",
    )
    candidate["evidence_locator"]["column_label"] = "Mn (g/mol)"

    merged, audit = recover_stage4_document(
        stage0, _stage2(), _stage3(), stage4,
        _shadow(candidate), {}, {},
    )

    specialized = merged.specialized_property_observations[0]
    assert specialized.value_kind == "numeric_scalar"
    assert specialized.value_min == 19800.0
    assert specialized.value_max == 19800.0
    assert merged.properties == []
    assert audit["summary"]["specialized_spaced_thousands_repaired_count"] == 1
    assert audit["summary"]["duplicate_existing_specialized_count"] == 1
    assert audit["specialized_repairs"][0]["basis"] == (
        "exact_table_cell_grouped_integer"
    )
    assert any(
        row.get("status") == "duplicate_existing_specialized"
        and row.get("specialized_id") == "sp001"
        for row in audit["candidate_outcomes"]
    )


def test_spaced_thousands_specialized_requires_exact_cell_evidence() -> None:
    stage4 = _empty_stage4()
    stage4["specialized_property_observations"] = [
        _published_malformed_mn(evidence_cell_value="19,800")
    ]

    merged, audit = recover_stage4_document(
        _stage0("19 800"), _stage2(), _stage3(), stage4,
        _shadow(), {}, {},
    )

    specialized = merged.specialized_property_observations[0]
    assert specialized.value_min == 19.0
    assert specialized.value_max == 800.0
    assert audit["summary"]["specialized_spaced_thousands_repaired_count"] == 0
    assert audit["specialized_repairs"] == []


@pytest.mark.parametrize(
    ("stage3", "candidate", "cell_text", "reason"),
    [
        (_stage3(), _candidate(sample_label_raw="Unknown"), "120", "stage3_label_not_found"),
        (_stage3(duplicate_label=True), _candidate(), "120", "stage3_label_ambiguous"),
        (_stage3(), _candidate(value_has_footnote=True), "120*", "value_footnote_unresolved"),
        (_stage3(), _candidate(unit_raw="%", unit_normalized="%"), "120", "required_unit_missing_or_invalid"),
        (
            _stage3(),
            _candidate(value_kind="numeric_range", value_raw="110-120", value_min=110.0, value_max=120.0),
            "110-120",
            "non_scalar_value_not_released",
        ),
    ],
)
def test_unsafe_or_unbound_shadow_candidates_are_audited_not_published(
    stage3: dict,
    candidate: dict,
    cell_text: str,
    reason: str,
) -> None:
    merged, audit = recover_stage4_document(
        _stage0(cell_text), _stage2(), stage3, _empty_stage4(),
        _shadow(candidate), {}, {},
    )

    assert merged.properties == []
    assert merged.measurement_conditions == []
    assert audit["summary"]["published_count"] == 0
    assert any(row.get("reason") == reason for row in audit["candidate_outcomes"])


def _stage3_with_samples(*samples: dict) -> dict:
    return {"document_id": REF, "samples": list(samples)}


def _sample(
    sample_id: str,
    label: str,
    *,
    state_description: str | None = None,
) -> dict:
    return {
        "sample_id": sample_id,
        "sample_label_raw": label,
        "polymer_name": label,
        "state_description": state_description,
        "refers_to_entity": "pe001",
        "evidence": {
            "source_sentence": state_description or label,
        },
    }


def _candidate_at(
    *,
    row: int,
    column: int,
    sample_label: str,
    value: str,
) -> dict:
    candidate = _candidate(
        observation_id=f"T_1:T_1:r{row:04d}:c{column:04d}",
        sample_label_raw=sample_label,
        value_raw=value,
        value_min=float(value),
        value_max=float(value),
        cell_id=f"T_1:r{row:04d}:c{column:04d}",
        row_index=row,
        column_index=column,
    )
    candidate["evidence"] = {
        "table_id": "T_1",
        "cell_id": f"T_1:r{row:04d}:c{column:04d}",
        "row_index": row,
        "column_index": column,
    }
    candidate["evidence_locator"] = {
        "table_id": "T_1",
        "cell_id": f"T_1:r{row:04d}:c{column:04d}",
        "row_index": row,
        "column_index": column,
        "row_label": sample_label,
        "column_label": "Tg (°C)",
    }
    return candidate


def _stage0_table(cells: list[dict], body: str = "<table></table>") -> dict:
    payload = _stage0()
    payload["elements"][0]["table_cells"] = cells
    payload["elements"][0]["table_body"] = body
    return payload


def _cell(
    row: int,
    column: int,
    text: str,
    *,
    row_span: int = 1,
    column_span: int = 1,
    header: bool = False,
) -> dict:
    return {
        "cell_id": f"T_1:r{row:04d}:c{column:04d}",
        "row_index": row,
        "column_index": column,
        "row_span": row_span,
        "column_span": column_span,
        "text": text,
        "is_header": header,
    }


def test_unique_composition_ratio_alias_matches_stage3_evidence_boundary() -> None:
    stage3 = _stage3_with_samples(
        _sample("s001", "copolycarbonate 80/20", state_description="feed ratios 80 : 20"),
    )
    merged, audit = recover_stage4_document(
        _stage0(sample_label="80 : 20"), _stage2(), stage3, _empty_stage4(),
        _shadow(_candidate(sample_label_raw="80 : 20")), {}, {},
    )

    assert merged.properties[0].sample_id == "s001"
    published = next(row for row in audit["candidate_outcomes"] if row["status"] == "published")
    assert published["sample_resolution_basis"] == "unique_composition_ratio_stage3_alias"


def test_composition_ratio_alias_fails_closed_when_two_samples_own_it() -> None:
    stage3 = _stage3_with_samples(
        _sample("s001", "batch A", state_description="feed ratio 80 : 20"),
        _sample("s002", "batch B", state_description="measured ratio 80 : 20"),
    )
    merged, audit = recover_stage4_document(
        _stage0(sample_label="80 : 20"), _stage2(), stage3, _empty_stage4(),
        _shadow(_candidate(sample_label_raw="80 : 20")), {}, {},
    )

    assert merged.properties == []
    assert any(
        row.get("reason") == "stage3_label_ambiguous"
        and row.get("sample_matches") == ["s001", "s002"]
        for row in audit["candidate_outcomes"]
    )


def test_joined_numeric_ratios_use_the_only_stage3_owned_segment() -> None:
    label = "60 : 40 | 58 : 42"
    stage3 = _stage3_with_samples(
        _sample("s001", "copolymer 60/40", state_description="60 : 40"),
    )
    merged, audit = recover_stage4_document(
        _stage0(sample_label=label), _stage2(), stage3, _empty_stage4(),
        _shadow(_candidate(sample_label_raw=label)), {}, {},
    )

    assert merged.properties[0].sample_id == "s001"
    published = next(row for row in audit["candidate_outcomes"] if row["status"] == "published")
    assert published["sample_resolution_basis"] == "unique_joined_stage3_alias"


def test_joined_entry_and_exact_polymer_code_resolve_uniquely() -> None:
    label = "1a | 0-2-0-6"
    stage3 = _stage3_with_samples(_sample("s001", "0-2-0-6"))
    merged, audit = recover_stage4_document(
        _stage0(sample_label=label), _stage2(), stage3, _empty_stage4(),
        _shadow(_candidate(sample_label_raw=label)), {}, {},
    )

    assert merged.properties[0].sample_id == "s001"
    published = next(row for row in audit["candidate_outcomes"] if row["status"] == "published")
    assert published["sample_resolution_basis"] == "unique_joined_stage3_alias"


def test_joined_blend_label_never_collapses_to_one_component() -> None:
    label = "50/50 Blend | /P (EO/PO)"
    stage3 = _stage3_with_samples(_sample("s001", "P (EO/PO)"))
    merged, audit = recover_stage4_document(
        _stage0(sample_label=label), _stage2(), stage3, _empty_stage4(),
        _shadow(_candidate(sample_label_raw=label)), {}, {},
    )

    assert merged.properties == []
    assert any(
        row.get("reason") == "stage3_label_not_found"
        for row in audit["candidate_outcomes"]
    )


def test_bare_number_does_not_match_number_inside_polymer_code() -> None:
    stage3 = _stage3_with_samples(_sample("s001", "0-10"))
    merged, audit = recover_stage4_document(
        _stage0(sample_label="10"), _stage2(), stage3, _empty_stage4(),
        _shadow(_candidate(sample_label_raw="10")), {}, {},
    )

    assert merged.properties == []
    assert any(
        row.get("reason") in {
            "stage3_label_not_found",
            "sample_axis_is_property_or_condition",
        }
        for row in audit["candidate_outcomes"]
    )


def test_blank_continuation_row_is_not_published_as_exact_parent_sample() -> None:
    cells = [
        _cell(0, 0, "No.", header=True),
        _cell(0, 1, "Code", header=True),
        _cell(0, 2, "Tg (°C)", header=True),
        _cell(1, 0, "1a"), _cell(1, 1, "0-2-0-6"), _cell(1, 2, "300"),
        _cell(2, 0, "b"), _cell(2, 1, ""), _cell(2, 2, "295"),
        _cell(3, 0, "c"), _cell(3, 1, ""), _cell(3, 2, "290"),
    ]
    stage3 = _stage3_with_samples(_sample("s001", "0-2-0-6"))
    candidate = _candidate_at(row=3, column=2, sample_label="c", value="290")
    merged, audit = recover_stage4_document(
        _stage0_table(cells), _stage2(), stage3, _empty_stage4(),
        _shadow(candidate), {}, {},
    )

    assert merged.properties == []
    rejected = next(
        row for row in audit["candidate_outcomes"]
        if row.get("reason") == "continuation_sample_binding_not_exact"
    )
    assert rejected["sample_resolution_basis"] == (
        "table_blank_continuation_parent_exact_alias"
    )
    assert rejected["sample_resolution_status"] == "inferred_parent_only"


def _paired_shift_case(row_method: str, producer_method: str | None) -> tuple[dict, dict, dict]:
    cells = [
        _cell(0, 0, "No.", header=True),
        _cell(0, 1, "Code", header=True),
        _cell(0, 2, "Method", header=True),
        _cell(0, 3, "PMT (°C)", header=True),
        _cell(0, 4, "Viscosity", header=True),
        _cell(1, 0, "a"),
        _cell(1, 1, "P1"),
        _cell(1, 2, row_method),
        _cell(1, 3, ""),
        _cell(1, 4, "342"),
    ]
    candidate = _candidate_at(
        row=1,
        column=4,
        sample_label="a | P1",
        value="342",
    )
    candidate.update({
        "property_name_raw": "PMT (°C)",
        "property_name_normalized": "melting_temperature",
        "unit_raw": "°C",
        "unit_normalized": "°C",
        "header_column_index": 3,
        "alignment_status": "paired_right_shift",
    })
    candidate["evidence_locator"]["column_label"] = "PMT (°C)"
    stage3 = _stage3_with_samples(_sample("s001", "P1"))
    if producer_method is not None:
        stage3["process_steps"] = [{
            "step_id": "ps001",
            "process_type": "polymerization",
            "input_sample_ids": [],
            "output_sample_ids": ["s001"],
            "parameters": {"method": producer_method},
        }]
    return _stage0_table(cells), stage3, candidate


def test_paired_shift_publishes_when_row_and_sample_process_methods_match() -> None:
    stage0, stage3, candidate = _paired_shift_case("LTS", "LTS")
    merged, audit = recover_stage4_document(
        stage0, _stage2(), stage3, _empty_stage4(),
        _shadow(candidate), {}, {},
    )

    assert merged.properties[0].sample_id == "s001"
    published = next(
        row for row in audit["candidate_outcomes"]
        if row["status"] == "published"
    )
    assert published["process_binding_basis"] == (
        "paired_shift_row_method_matches_stage3_producer"
    )


@pytest.mark.parametrize(
    ("row_method", "producer_method", "reason"),
    [
        ("HTS", "LTS", "paired_shift_process_binding_conflict"),
        ("HTS", None, "paired_shift_process_binding_unverified"),
    ],
)
def test_paired_shift_fails_closed_without_matching_sample_process(
    row_method: str,
    producer_method: str | None,
    reason: str,
) -> None:
    stage0, stage3, candidate = _paired_shift_case(row_method, producer_method)
    merged, audit = recover_stage4_document(
        stage0, _stage2(), stage3, _empty_stage4(),
        _shadow(candidate), {}, {},
    )

    assert merged.properties == []
    assert any(
        row.get("reason") == reason
        for row in audit["candidate_outcomes"]
    )


def test_blank_continuation_does_not_borrow_from_a_later_row() -> None:
    cells = [
        _cell(0, 0, "No.", header=True),
        _cell(0, 1, "Code", header=True),
        _cell(0, 2, "Tg (°C)", header=True),
        _cell(1, 0, "b"), _cell(1, 1, ""), _cell(1, 2, "295"),
        _cell(2, 0, "2a"), _cell(2, 1, "0-2-0-6"), _cell(2, 2, "300"),
    ]
    stage3 = _stage3_with_samples(_sample("s001", "0-2-0-6"))
    candidate = _candidate_at(row=1, column=2, sample_label="b", value="295")
    merged, audit = recover_stage4_document(
        _stage0_table(cells), _stage2(), stage3, _empty_stage4(),
        _shadow(candidate), {}, {},
    )

    assert merged.properties == []
    assert any(row.get("reason") == "stage3_label_not_found" for row in audit["candidate_outcomes"])


def test_blank_continuation_stops_at_first_new_group_without_a_code() -> None:
    cells = [
        _cell(0, 0, "No.", header=True),
        _cell(0, 1, "Code", header=True),
        _cell(0, 2, "Tg (°C)", header=True),
        _cell(1, 0, "1a"), _cell(1, 1, "0-2-0-6"), _cell(1, 2, "300"),
        _cell(2, 0, "2a"), _cell(2, 1, ""), _cell(2, 2, "280"),
        _cell(3, 0, "b"), _cell(3, 1, ""), _cell(3, 2, "275"),
    ]
    stage3 = _stage3_with_samples(_sample("s001", "0-2-0-6"))
    candidate = _candidate_at(row=3, column=2, sample_label="b", value="275")
    merged, audit = recover_stage4_document(
        _stage0_table(cells), _stage2(), stage3, _empty_stage4(),
        _shadow(candidate), {}, {},
    )

    assert merged.properties == []
    assert any(row.get("reason") == "stage3_label_not_found" for row in audit["candidate_outcomes"])


def test_explicit_rowspan_parent_resolves_by_unique_exact_alias() -> None:
    cells = [
        _cell(0, 0, "Sample", header=True),
        _cell(0, 1, "Role", header=True),
        _cell(0, 2, "Tg (°C)", header=True),
        _cell(1, 0, "P1", row_span=2),
        _cell(1, 1, "Calcd"), _cell(1, 2, "101"),
        _cell(2, 1, "Found"), _cell(2, 2, "103"),
    ]
    candidate = _candidate_at(row=2, column=2, sample_label="Found", value="103")
    merged, audit = recover_stage4_document(
        _stage0_table(cells), _stage2(), _stage3(), _empty_stage4(),
        _shadow(candidate), {}, {},
    )

    assert merged.properties[0].sample_id == "s001"
    published = next(row for row in audit["candidate_outcomes"] if row["status"] == "published")
    assert published["sample_resolution_basis"] == "table_rowspan_parent_exact_alias"


def test_pre_unified_requires_explicit_safe_audit_outcome() -> None:
    safe_audit = {
        "document_id": REF,
        "candidate_outcomes": [{
            "status": "pre_unified_release_eligible",
            "stage4_property_id": "prop001",
            "cell_id": "T_1:r0001:c0001",
        }],
    }
    merged, audit = recover_stage4_document(
        _stage0(), _stage2(), _stage3(), _empty_stage4(),
        {}, safe_audit, _pre_unified(),
    )
    assert len(merged.properties) == 1
    assert merged.properties[0].property_id == "prop001"
    assert audit["summary"]["published_count"] == 1

    blocked, blocked_audit = recover_stage4_document(
        _stage0(), _stage2(), _stage3(), _empty_stage4(),
        {}, {}, _pre_unified(),
    )
    assert blocked.properties == []
    assert any(
        row.get("reason") == "pre_unified_not_allowed_by_audit"
        for row in blocked_audit["candidate_outcomes"]
    )


def test_upstream_source_conflict_is_never_released() -> None:
    audit_input = {
        "document_id": REF,
        "pre_unified_release_allowlist": ["prop001"],
        "candidate_outcomes": [{
            "status": "source_conflict",
            "stage4_property_id": "prop001",
            "cell_id": "T_1:r0001:c0001",
        }],
    }
    merged, audit = recover_stage4_document(
        _stage0(), _stage2(), _stage3(), _empty_stage4(),
        {}, audit_input, _pre_unified(),
    )
    assert merged.properties == []
    assert any(
        row.get("reason") == "upstream_source_conflict"
        for row in audit["candidate_outcomes"]
    )


def test_current_stage4_same_cell_semantic_conflict_is_not_overwritten() -> None:
    current = _pre_unified()
    current["properties"][0]["property_name_raw"] = "Tm (°C)"
    current["properties"][0]["property_name_normalized"] = "melting_temperature"
    Stage4Document.model_validate(current)
    merged, audit = recover_stage4_document(
        _stage0(), _stage2(), _stage3(), current,
        _shadow(_candidate()), {}, {},
    )
    assert len(merged.properties) == 1
    assert merged.properties[0].property_name_normalized == "melting_temperature"
    assert any(
        row.get("reason") == "current_stage4_cell_conflict"
        for row in audit["candidate_outcomes"]
    )


def test_scaled_shadow_repairs_compatible_same_cell_display_placeholder() -> None:
    stage0 = _stage0("4.76")
    stage0["elements"][0]["table_cells"][1]["text"] = (
        "Conductivity (10^12 ohm^-1 cm^-1)"
    )
    stage0["elements"][0]["table_body"] = (
        "<table><tr><td>Sample</td>"
        "<td>Conductivity (10^12 ohm^-1 cm^-1)</td></tr>"
        "<tr><td>P1</td><td>4.76</td></tr></table>"
    )
    current = _pre_unified()
    current["properties"][0].update({
        "property_name_raw": "Conductivity (10^12 ohm^-1 cm^-1)",
        "property_name_normalized": "electric_conductivity",
        "value_raw": "4.76",
        "value_min": None,
        "value_max": None,
        "unit_raw": "ohm^-1 cm^-1",
        "unit_normalized": "S/cm",
    })
    current["properties"][0]["evidence"][0]["source_sentence"] = "4.76"
    current["properties"][0]["evidence"][0]["table_locator"].update({
        "column_label": "Conductivity (10^12 ohm^-1 cm^-1)",
        "cell_value": "4.76",
    })
    current["measurement_conditions"][0]["evidence"]["source_sentence"] = "4.76"
    current["measurement_conditions"][0]["evidence"]["table_locator"].update({
        "column_label": "Conductivity (10^12 ohm^-1 cm^-1)",
        "cell_value": "4.76",
    })
    candidate = _candidate(
        property_name_raw="Conductivity (10^12 ohm^-1 cm^-1)",
        property_name_normalized="electric_conductivity",
        value_raw="4.76",
        value_min=None,
        value_max=None,
        unit_raw="ohm^-1 cm^-1",
        unit_normalized="S/cm",
        display_multiplier_exponent=12,
        value_scale_factor=1e-12,
        scale_interpretation="display_value_equals_physical_value_times_10^n",
    )
    candidate["evidence_locator"]["column_label"] = (
        "Conductivity (10^12 ohm^-1 cm^-1)"
    )

    merged, audit = recover_stage4_document(
        stage0, _stage2(), _stage3(), current,
        _shadow(candidate), {}, {},
    )

    assert len(merged.properties) == 1
    repaired = merged.properties[0]
    assert repaired.property_id == "prop001"
    assert repaired.value_min == pytest.approx(4.76e-12)
    assert repaired.value_max == pytest.approx(4.76e-12)
    assert repaired.unit_normalized == "S/cm"
    assert any(
        row.get("reason") == "same_cell_display_value_scaled"
        and row.get("repaired_existing") is True
        for row in audit["candidate_outcomes"]
    )


def test_scaled_shadow_repairs_truncated_conductivity_unit_fragment() -> None:
    stage0 = _stage0("4.76")
    stage0["elements"][0]["table_cells"][1]["text"] = (
        "Conductivity (10^12 ohm^-1 cm^-1)"
    )
    stage0["elements"][0]["table_body"] = (
        "<table><tr><td>Sample</td>"
        "<td>Conductivity (10^12 ohm^-1 cm^-1)</td></tr>"
        "<tr><td>P1</td><td>4.76</td></tr></table>"
    )
    current = _pre_unified()
    current["properties"][0].update({
        "property_name_raw": "Conductivity (10^12 ohm^-1 cm^-1)",
        "property_name_normalized": "electric_conductivity",
        "value_raw": "4.76",
        "value_min": None,
        "value_max": None,
        # A real Stage 4 response kept only the denominator length token.
        "unit_raw": "cm",
        "unit_normalized": None,
    })
    current["properties"][0]["evidence"][0]["source_sentence"] = "4.76"
    current["properties"][0]["evidence"][0]["table_locator"].update({
        "column_label": "Conductivity (10^12 ohm^-1 cm^-1)",
        "cell_value": "4.76",
    })
    current["measurement_conditions"][0]["evidence"]["source_sentence"] = "4.76"
    current["measurement_conditions"][0]["evidence"]["table_locator"].update({
        "column_label": "Conductivity (10^12 ohm^-1 cm^-1)",
        "cell_value": "4.76",
    })
    candidate = _candidate(
        property_name_raw="Conductivity (10^12 ohm^-1 cm^-1)",
        property_name_normalized="electric_conductivity",
        value_raw="4.76",
        value_min=None,
        value_max=None,
        unit_raw="ohm^-1 cm^-1",
        unit_normalized="S/cm",
        display_multiplier_exponent=12,
        value_scale_factor=1e-12,
        scale_interpretation="display_value_equals_physical_value_times_10^n",
    )
    candidate["evidence_locator"]["column_label"] = (
        "Conductivity (10^12 ohm^-1 cm^-1)"
    )

    merged, audit = recover_stage4_document(
        stage0, _stage2(), _stage3(), current,
        _shadow(candidate), {}, {},
    )

    assert len(merged.properties) == 1
    repaired = merged.properties[0]
    assert repaired.value_min == pytest.approx(4.76e-12)
    assert repaired.unit_normalized == "S/cm"
    assert audit["summary"]["published_count"] == 1


def test_scaled_shadow_does_not_replace_a_different_nonempty_unit() -> None:
    current = _pre_unified()
    current["properties"][0].update({
        "property_name_normalized": "electric_conductivity",
        "value_raw": "4.76",
        "unit_raw": "S/m",
        "unit_normalized": "S/m",
    })
    candidate = _candidate(
        property_name_normalized="electric_conductivity",
        display_multiplier_exponent=12,
        value_scale_factor=1e-12,
        scale_interpretation="display_value_equals_physical_value_times_10^n",
    )
    candidate["property_name_raw"] = "Conductivity (10^12 ohm^-1 cm^-1)"
    candidate["unit_raw"] = "ohm^-1 cm^-1"
    candidate["unit_normalized"] = "S/cm"
    candidate["evidence_locator"]["column_label"] = (
        "Conductivity (10^12 ohm^-1 cm^-1)"
    )

    merged, audit = recover_stage4_document(
        _stage0(), _stage2(), _stage3(), current,
        _shadow(candidate), {}, {},
    )

    assert merged.properties[0].unit_normalized == "S/m"
    assert any(
        row.get("reason") == "current_stage4_cell_conflict"
        for row in audit["candidate_outcomes"]
    )


def test_property_series_scalar_locator_repair_is_exact_and_narrow() -> None:
    current = _series_stage4()
    frozen = json.loads(json.dumps(current))

    merged, audit = recover_stage4_document(
        _series_stage0(), _stage2(), _stage3(), current, {}, {}, {},
    )

    point = merged.property_series[0].points[0]
    repaired = point.coordinates[1].evidence.table_locator
    assert repaired == {
        "table_id": "T_1",
        "row_label": "20",
        "column_label": "Extruder Screw Speed (rpm)",
        "cell_value": "7",
        "cell_id": "T_1:r0001:c0001",
        "row_index": 1,
        "column_index": 1,
    }
    assert point.value_raw == "81"
    assert point.value_min == 81.0
    assert point.value_max == 81.0
    assert point.unit_normalized == "°C"
    assert point.sample_id == "s001"
    assert point.entity_id == "pe001"
    assert current == frozen
    assert audit["summary"]["property_series_locator_repaired_count"] == 1
    assert audit["summary"]["property_series_locator_rejected_count"] == 0
    assert audit["summary"]["property_series_coordinate_occurrence_repaired_count"] == 1
    assert audit["property_series_locator_repairs"][0]["source_id"] == "pt001"


@pytest.mark.parametrize(
    ("stage0_updates", "stage4_updates", "expected_reason"),
    [
        (
            {"response_value": "81/112"},
            {"value_raw": "81/112", "value_min": 81.0, "value_max": 112.0},
            "property_series_non_scalar_not_repaired",
        ),
        (
            {},
            {"value_raw": "80", "value_min": 80.0, "value_max": 80.0},
            "property_series_response_cell_value_mismatch",
        ),
        (
            {"speed_value": "7"},
            {"coordinate_value": "8"},
            "property_series_coordinate_cell_value_mismatch",
        ),
        (
            {},
            {"normalized_property": None},
            "property_series_semantic_or_unit_missing",
        ),
        (
            {},
            {"normalized_unit": None},
            "property_series_semantic_or_unit_missing",
        ),
        (
            {},
            {"entity_id": "pe999"},
            "property_series_sample_entity_not_exact",
        ),
    ],
)
def test_property_series_locator_repair_fails_closed(
    stage0_updates: dict,
    stage4_updates: dict,
    expected_reason: str,
) -> None:
    current = _series_stage4(**stage4_updates)
    merged, audit = recover_stage4_document(
        _series_stage0(**stage0_updates),
        _stage2(),
        _stage3(),
        current,
        {},
        {},
        {},
    )

    locator = merged.property_series[0].points[0].coordinates[1].evidence.table_locator
    assert locator["cell_id"] is None
    assert audit["summary"]["property_series_locator_repaired_count"] == 0
    assert audit["summary"]["property_series_locator_rejected_count"] == 1
    assert audit["property_series_locator_rejections"][0]["reason"] == expected_reason


def test_property_series_locator_repair_is_idempotent() -> None:
    first, first_audit = recover_stage4_document(
        _series_stage0(), _stage2(), _stage3(), _series_stage4(), {}, {}, {},
    )
    second, second_audit = recover_stage4_document(
        _series_stage0(), _stage2(), _stage3(), first, {}, {}, {},
    )

    assert second.model_dump(mode="json") == first.model_dump(mode="json")
    assert first_audit["summary"]["property_series_locator_repaired_count"] == 1
    assert second_audit["summary"]["property_series_locator_repaired_count"] == 0


def test_recovery_is_idempotent() -> None:
    first, first_audit = recover_stage4_document(
        _stage0(), _stage2(), _stage3(), _empty_stage4(),
        _shadow(_candidate()), {}, {},
    )
    second, second_audit = recover_stage4_document(
        _stage0(), _stage2(), _stage3(), first,
        _shadow(_candidate()), {}, {},
    )

    assert second.model_dump(mode="json") == first.model_dump(mode="json")
    assert first_audit["summary"]["published_count"] == 1
    assert second_audit["summary"]["duplicate_existing_count"] == 1


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_runner_apply_keeps_backup_and_reuses_hash_cache(tmp_path: Path) -> None:
    root = tmp_path / "run"
    ref_root = root / REF
    _write(ref_root / "stage0_blocks.json", _stage0())
    _write(ref_root / "stage2_entities.json", _stage2())
    _write(ref_root / "stage3_process.json", _stage3())
    _write(ref_root / "stage4_properties.json", _empty_stage4())
    _write(ref_root / "stage4t_shadow.json", _shadow(_candidate()))

    first = run_stage4p(
        REF, input_root=root, output_root=root, apply=True,
    )
    assert first["status"] == "executed"
    assert (ref_root / OUTPUT_NAME).is_file()
    assert (ref_root / AUDIT_NAME).is_file()
    assert (ref_root / BACKUP_NAME).is_file()
    applied = Stage4Document.model_validate_json(
        (ref_root / "stage4_properties.json").read_text(encoding="utf-8")
    )
    assert len(applied.properties) == 1

    second = run_stage4p(
        REF, input_root=root, output_root=root, apply=True,
    )
    assert second["status"] == "cached"
    backup = Stage4Document.model_validate_json(
        (ref_root / BACKUP_NAME).read_text(encoding="utf-8")
    )
    assert backup.properties == []


def test_runner_archives_old_backup_and_tracks_fresh_upstream_base(
    tmp_path: Path,
) -> None:
    root = tmp_path / "run"
    ref_root = root / REF
    _write(ref_root / "stage0_blocks.json", _stage0())
    _write(ref_root / "stage2_entities.json", _stage2())
    _write(ref_root / "stage3_process.json", _stage3())
    _write(ref_root / "stage4_properties.json", _empty_stage4())
    _write(ref_root / "stage4t_shadow.json", _shadow(_candidate()))

    run_stage4p(REF, input_root=root, output_root=root, apply=True)
    backup_path = ref_root / BACKUP_NAME
    original_backup_bytes = backup_path.read_bytes()
    original_backup_hash = hashlib.sha256(original_backup_bytes).hexdigest()

    # Simulate a fresh upstream Stage 4 run in the same document directory.
    fresh_base = _pre_unified()
    _write(ref_root / "stage4_properties.json", fresh_base)
    fresh_base_hash = hashlib.sha256(
        (ref_root / "stage4_properties.json").read_bytes()
    ).hexdigest()
    run_stage4p(
        REF, input_root=root, output_root=root, apply=True, force=True,
    )

    audit = json.loads((ref_root / AUDIT_NAME).read_text(encoding="utf-8"))
    assert audit["input_hashes"]["base_stage4"] == fresh_base_hash
    assert hashlib.sha256(backup_path.read_bytes()).hexdigest() == fresh_base_hash
    assert audit["pre_p2_backup"]["sha256"] == fresh_base_hash

    archive_path = backup_path.with_name(
        f"{backup_path.stem}.{original_backup_hash}{backup_path.suffix}"
    )
    assert archive_path.read_bytes() == original_backup_bytes
    assert audit["pre_p2_backup"]["archived_previous_path"] == str(archive_path)
    assert (
        audit["pre_p2_backup"]["archived_previous_sha256"]
        == original_backup_hash
    )
