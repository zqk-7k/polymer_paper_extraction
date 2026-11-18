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


def _stage3_series() -> dict:
    return {
        "samples": [
            {
                "sample_id": "s001",
                "sample_label_raw": "PC-1",
                "polymer_name": "Polymer A",
                "refers_to_entity": "pe001",
            },
            {
                "sample_id": "s002",
                "sample_label_raw": "PC-2",
                "polymer_name": "Polymer B",
                "refers_to_entity": "pe002",
            },
        ]
    }


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
    assert audit["summary"]["candidate_conservation"] == {
        "input_candidate_count": 1,
        "accounted_candidate_count": 1,
        "unaccounted_candidate_count": 0,
        "balanced": True,
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
    assert len(merged.specialized_property_observations) == 2
    assert all(
        item.publication_status == "unresolved"
        and item.sample_resolution_status == "unresolved"
        and item.sample_id is None
        for item in merged.specialized_property_observations
    )
    assert [item.value_raw for item in merged.specialized_property_observations] == [
        "120",
        "120",
    ]
    assert audit["summary"]["unmatched_sample_count"] == 1
    assert audit["summary"]["ambiguous_sample_count"] == 1


def test_explicit_evidence_row_label_supports_delayed_sample_binding() -> None:
    candidate = _candidate(
        sample_label_raw=None,
        evidence_locator={"header_path": ["Tg (°C)"], "row_label": "Sample-A"},
    )
    merged, audit = unify_documents(
        _stage0(), _stage2(), _stage3(), _stage4(), _sidecar(candidate)
    )

    assert len(merged.properties) == 1
    assert merged.properties[0].evidence[0].table_locator["row_label"] == "Sample-A"
    assert merged.properties[0].evidence[0].table_locator["locator_status"] == "stable_cell"
    assert merged.properties[0].evidence[0].table_locator["header_path"] == ["Tg (°C)"]
    outcome = audit["candidate_outcomes"][0]
    assert outcome["sample_id"] == "s001"
    assert outcome["sample_resolution_basis"] == "normalized_evidence_row_label"


def test_unresolved_sample_keeps_table_context_for_rebinding() -> None:
    sidecar = {
        "tables": [{
            "table_id": "T_1",
            "caption": "Thermal properties",
            "direction": "row_samples",
            "sample_axis": "row",
            "axis_role": "named_sample",
            "header_rows": [0, 1],
            "context": {"source_block_ids": ["P_before"]},
            "observations": [_candidate(
                sample_label_raw=None,
                source_layer="llm_enriched",
                interpretation_status="applied",
                interpretation_confidence=0.7,
                confidence_source="llm_header_assignment",
            )],
        }]
    }
    merged, audit = unify_documents(
        _stage0(), _stage2(), _stage3(), _stage4(), sidecar
    )

    assert merged.properties == []
    assert len(merged.specialized_property_observations) == 1
    observation = merged.specialized_property_observations[0]
    assert observation.publication_status == "unresolved"
    assert observation.sample_resolution_status == "unresolved"
    assert observation.sample_id is None
    assert observation.value_raw == "120"
    context = audit["candidate_outcomes"][0]["sample_binding_context"]
    assert context["caption"] == "Thermal properties"
    assert context["direction"] == "row_samples"
    assert context["header_rows"] == [0, 1]
    assert context["context_source_block_ids"] == ["P_before"]
    outcome = audit["candidate_outcomes"][0]
    assert outcome["source_layer"] == "llm_enriched"
    assert outcome["interpretation_status"] == "applied"
    assert outcome["interpretation_confidence"] == 0.7


def test_numeric_row_label_uses_explicit_sample_series_context() -> None:
    candidate = _candidate(
        sample_label_raw="2",
        row_label="2",
        table_sample_axis="row",
        table_caption="Properties for PC-1–PC-2 samples",
        table_context_text="Several polycarbonates (PC-1–PC-2) were synthesized.",
        observation_id="numeric-series-1",
    )
    merged, audit = unify_documents(
        _stage0(), _stage2(), _stage3_series(), _stage4(), _sidecar(candidate)
    )

    assert len(merged.properties) == 1
    assert merged.properties[0].sample_id == "s002"
    outcome = audit["candidate_outcomes"][0]
    assert outcome["sample_resolution_basis"] == "table_sample_series_index"
    assert outcome["sample_binding_anchors"] == [
        "numeric_row_label",
        "sample_series_context",
    ]


def test_range_sample_label_does_not_masquerade_as_individual_sample() -> None:
    stage3 = {
        "samples": [
            {
                "sample_id": "s001",
                "sample_label_raw": "PI-1 to PI-7",
                "polymer_name": "Polyimide series",
                "refers_to_entity": "pe001",
            },
            {
                "sample_id": "s002",
                "sample_label_raw": None,
                "polymer_name": "Polyimide series",
                "refers_to_entity": "pe001",
            },
        ]
    }
    candidate = _candidate(
        sample_label_raw="PI-3",
        observation_id="range-alias-1",
    )
    merged, audit = unify_documents(
        _stage0(), _stage2(), stage3, _stage4(), _sidecar(candidate)
    )

    assert len(merged.properties) == 0
    assert audit["candidate_outcomes"][0]["sample_resolution_status"] == "unmatched_sample"
    assert merged.specialized_property_observations[0].value_raw == "120"


def test_unique_context_sample_anchor_binds_without_explicit_label() -> None:
    candidate = _candidate(
        sample_label_raw=None,
        row_label=None,
        table_context_text="The Sample-A film was measured after annealing.",
        observation_id="context-anchor-1",
    )
    merged, audit = unify_documents(
        _stage0(), _stage2(), _stage3(), _stage4(), _sidecar(candidate)
    )

    assert len(merged.properties) == 1
    assert merged.properties[0].sample_id == "s001"
    outcome = audit["candidate_outcomes"][0]
    assert outcome["sample_resolution_basis"] == "shared_context_anchor"
    assert "context_sample_label" in outcome["sample_binding_anchors"]


def test_implicit_condition_axis_does_not_guess_sample_from_context() -> None:
    candidate = _candidate(
        sample_label_raw=None,
        row_label=None,
        table_sample_axis="implicit",
        table_axis_role="condition",
        table_context_text="The P4THPMA sample was measured at several temperatures.",
        observation_id="implicit-condition-1",
    )
    merged, audit = unify_documents(
        _stage0(), _stage2(), _stage3(), _stage4(), _sidecar(candidate)
    )

    assert merged.properties == []
    assert merged.specialized_property_observations[0].sample_id is None
    assert audit["candidate_outcomes"][0]["sample_resolution_status"] == (
        "unmatched_sample"
    )


def test_ambiguous_explicit_label_is_not_overridden_by_context() -> None:
    candidate = _candidate(
        table_context_text="Sample-A was measured by DSC.",
        observation_id="ambiguous-context-1",
    )
    merged, audit = unify_documents(
        _stage0(), _stage2(), _stage3(duplicate_label=True), _stage4(), _sidecar(candidate)
    )

    assert merged.properties == []
    assert audit["candidate_outcomes"][0]["sample_resolution_status"] == (
        "ambiguous_sample"
    )


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


def test_numeric_uncertainty_is_integrated_with_center_bounds() -> None:
    candidate = _candidate(
        value_raw="120 ± 3",
        value_kind="numeric_with_uncertainty",
        observation_id="uncertainty-1",
    )
    merged, audit = unify_documents(
        _stage0(), _stage2(), _stage3(), _stage4(), _sidecar(candidate)
    )

    assert len(merged.properties) == 1
    assert merged.properties[0].value_min == 120.0
    assert merged.properties[0].value_max == 120.0
    assert audit["summary"]["integrated_count"] == 1


def test_same_cell_semantic_conflict_retains_both_candidates_for_review() -> None:
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

    assert len(merged.properties) == 1
    assert len(merged.measurement_conditions) == 1
    assert len(merged.specialized_property_observations) == 1
    conflict = merged.specialized_property_observations[0]
    assert conflict.publication_status == "unresolved"
    assert conflict.reason == "same_cell_semantic_conflict"
    assert audit["summary"]["source_conflict_count"] == 1
    assert audit["summary"]["quarantined_stage4_property_count"] == 0
    assert audit["summary"]["conflict_stage4_property_count"] == 1
    assert audit["summary"]["specialized_unresolved_count"] == 1


def test_material_candidate_routes_to_specialized_by_vocabulary() -> None:
    # xray_diffraction_peak 在登记表内映射到 two_theta 且可发布，故不再暂扣。
    # official 侧仍必须为空——specialized 是加法通道，不回流 properties。
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
    assert outcome["status"] == "integrated_specialized"
    assert outcome["vocabulary_key"] == "two_theta"
    assert outcome["sample_resolution_status"] == "matched"
    assert outcome["sample_id"] == "s001"

    observation = merged.specialized_property_observations[0]
    assert observation.specialized_id == "sp001"
    assert observation.publication_status == "published"
    assert observation.source_field == "crystallographic_data"
    assert observation.sample_id == "s001"
    assert observation.sample_resolution_status == "resolved"
    assert observation.reason is None
    assert observation.evidence[0].table_locator["cell_id"] == "T_1:r0001:c0001"


def test_unmapped_semantic_label_stays_unresolved_in_specialized_array() -> None:
    # 未登记 label 必须留在同一数组标 unresolved，守恒式才成立（方案 §3）。
    unknown = _candidate(
        property_name_normalized=None,
        semantic_label="totally_unknown_label",
        candidate_class="unknown_observation",
    )
    merged, audit = unify_documents(
        _stage0(), _stage2(), _stage3(), _stage4(), _sidecar(unknown)
    )

    assert merged.properties == []
    outcome = audit["candidate_outcomes"][0]
    assert outcome["status"] == "retained_specialized"
    assert outcome["reason"] == "semantic_unmapped"

    observation = merged.specialized_property_observations[0]
    assert observation.publication_status == "unresolved"
    assert observation.reason == "semantic_unmapped"
    assert observation.source_field is None
    assert observation.semantic_label == "totally_unknown_label"
    assert observation.evidence


def test_registered_out_of_scope_label_reports_its_reason() -> None:
    out_of_scope = _candidate(
        property_name_normalized=None,
        semantic_label="char_yield",
        candidate_class="material_characteristic",
    )
    merged, audit = unify_documents(
        _stage0(), _stage2(), _stage3(), _stage4(), _sidecar(out_of_scope)
    )

    observation = merged.specialized_property_observations[0]
    assert observation.publication_status == "unresolved"
    assert observation.reason == "not_in_specialized_scope"
    assert audit["summary"]["specialized_unresolved_count"] == 1
    assert audit["summary"]["specialized_reason_counts"] == {
        "not_in_specialized_scope": 1
    }


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

def test_uncertain_scale_does_not_publish_even_when_sample_matches():
    candidate = _candidate(scale_factor_status='ambiguous_display_scale',
        normalization_status='warning', normalization_warning='scale_direction_requires_review')
    merged, audit = unify_documents(_stage0(), _stage2(), _stage3(), _stage4(), _sidecar(candidate))
    assert merged.properties == []
    result = audit['candidate_outcomes'][0]
    assert result['status'] == 'retained_candidate'
    assert result['reason'] == 'scale_direction_requires_review'
    assert result['raw_candidate']['value_raw'] == '120'


def test_specialized_projection_retains_all_normalized_values():
    candidate = _candidate(property_name_normalized=None, property_name_raw='Molecular weight',
        semantic_label='molecular_weight', candidate_class='material_characteristic',
        value_kind='numeric_multiple', value_raw='12000, 13500, 67500',
        normalized_value=12000, normalized_values=[12000, 13500, 67500],
        normalization_status='normalized', unit_raw='g/mol', unit_normalized='g/mol')
    merged, audit = unify_documents(_stage0(), _stage2(), _stage3(), _stage4(), _sidecar(candidate))
    observation = merged.specialized_property_observations[0]
    assert observation.numeric_values == [12000, 13500, 67500]
    assert observation.value_max == 67500



def _review_source(header,values,notes=()):
    source=_stage0();tbl=source.elements[0]
    tbl.table_body='<table><tr><th>Sample</th><th>'+header+'</th></tr>'+''.join(
        f'<tr><td>X{i}</td><td>{v}</td></tr>' for i,v in enumerate(values))+'</table>'
    tbl.table_cells=parse_table_cells(tbl.table_body,'T_1');tbl.table_notes=list(notes)
    return source


def test_source_backed_composite_parts_enter_unresolved_channel_and_are_idempotent():
    source=_review_source('C% Found (Calcd)',['71.63(71.90)'])
    candidate=_candidate(value_raw='71.63(71.90)',property_name_raw='C% Found (Calcd)',
        property_name_normalized=None,candidate_class='unknown_observation',unit_raw='%',
        normalization_status='warning',normalization_warning='value_not_numeric')
    original=source.model_dump(mode='json')
    merged,audit=unify_documents(source,_stage2(),_stage3(),_stage4(),_sidecar(candidate))
    parts=merged.specialized_property_observations
    assert [p.value_raw for p in parts]==['71.63','71.90']
    assert all(p.publication_status=='unresolved' and p.sample_id is None for p in parts)
    assert [p.value_derivation['source_semantics']['source_role'] for p in parts]==['measured','calculated']
    assert all(p.candidate_trace['source_cell_raw']=='71.63(71.90)' for p in parts)
    assert audit['summary']['candidate_conservation']['balanced']
    second,_=unify_documents(source,_stage2(),_stage3(),merged.model_dump(mode='json'),_sidecar(candidate))
    assert len(second.specialized_property_observations)==2 and source.model_dump(mode='json')==original


def test_calcd_alone_does_not_make_outer_value_measured():
    source=_review_source('Elementary analysis (Calcd) | C%',['71.63(71.90)'])
    candidate=_candidate(value_raw='71.63(71.90)',property_name_raw='Elementary analysis | C%',
        normalization_status='warning',normalization_warning='value_not_numeric',unit_raw='%')
    merged,_=unify_documents(source,_stage2(),_stage3(),_stage4(),_sidecar(candidate))
    assert [p.value_derivation['source_semantics']['source_role'] for p in merged.specialized_property_observations]==['unknown','calculated']


def test_uncertainty_without_role_definition_and_concatenation_are_not_split():
    for raw in ['1.234(5)','5.906.03']:
        source=_review_source('Density',['1.234(5)' if raw.startswith('1') else raw])
        candidate=_candidate(value_raw=raw,property_name_raw='Density',normalization_status='warning',normalization_warning='value_not_numeric')
        merged,_=unify_documents(source,_stage2(),_stage3(),_stage4(),_sidecar(candidate))
        assert len(merged.specialized_property_observations)==1
        kept=merged.specialized_property_observations[0]
        assert kept.value_raw==raw and kept.value_derivation['status']=='not_numeric'


def test_formula_and_incorrect_locator_never_create_review_properties():
    for raw,row in [('$C_{19}H_{19}N_5$',1),('71.63(71.90)',9)]:
        source=_review_source('Elementary analysis (Calcd) | C%',[raw])
        candidate=_candidate(value_raw=raw,row_index=row,normalization_status='warning',normalization_warning='value_not_numeric')
        merged,_=unify_documents(source,_stage2(),_stage3(),_stage4(),_sidecar(candidate))
        assert merged.specialized_property_observations==[]


def test_outside_catalog_middle_dot_and_star_value_are_visible_with_source_notes():
    source=_review_source('Hv, kcal/mole',['13·30','15·01','13·60*'],['* Measured by dynamic calorimetry at 25 °C.'])
    candidate=_candidate(value_raw='13·60*',cell_id='T_1:r0003:c0001',row_index=3,
        property_name_raw='Hv, kcal/mole',property_name_normalized=None,unit_raw=None,unit_normalized=None,
        normalization_status='warning',normalization_warning='value_not_numeric')
    merged,_=unify_documents(source,_stage2(),_stage3(),_stage4(),_sidecar(candidate))
    kept=merged.specialized_property_observations[0]
    assert kept.value_raw=='13·60*' and kept.publication_status=='unresolved'
    assert kept.value_derivation['actual_values']==[13.6]
    assert kept.value_derivation['actual_unit']=='kcal/mol'
    semantics=kept.value_derivation['source_semantics']
    assert semantics['source_role']=='measured'
    assert any(c['parameter']=='temperature' and c['value_raw']=='25 °C' for c in semantics['conditions_from_source'])



def test_concatenated_elemental_cell_has_no_confirmed_whole_calculated_role():
    source=_review_source('Elementary analysis (Calcd) | H%',['5.906.03'])
    candidate=_candidate(value_raw='5.906.03',property_name_raw='Elementary analysis | H%',
        normalization_status='warning',normalization_warning='value_not_numeric',unit_raw='%')
    merged,_=unify_documents(source,_stage2(),_stage3(),_stage4(),_sidecar(candidate))
    semantics=merged.specialized_property_observations[0].value_derivation['source_semantics']
    assert semantics['source_role']=='unknown' and 'composite_role_requires_review' in semantics['warnings']


def test_old_scale_ambiguity_is_not_erased_by_scalar_numeric_parse():
    candidate=_candidate(scale_factor_status='ambiguous_display_scale',normalization_status='warning',
                         normalization_warning='scale_direction_requires_review')
    merged,_=unify_documents(_stage0(),_stage2(),_stage3(),_stage4(),_sidecar(candidate))
    kept=merged.specialized_property_observations[0]
    assert kept.publication_status=='unresolved'
    assert kept.value_derivation['status']=='review_required' and 'actual_values' not in kept.value_derivation



def test_ocr_note_symbol_mismatch_stays_candidate_and_does_not_borrow_whole_column():
    source=_review_source('Hv, kcal/mole',['13·30','15·01','13·60*'],['• Measured by dynamic calorimetry at 25 °C.'])
    item=_candidate(value_raw='13·60*',row_index=3,cell_id='T_1:r0003:c0001',
        property_name_raw='Hv, kcal/mole',normalization_status='warning',normalization_warning='value_not_numeric',
        unit_raw=None,unit_normalized=None)
    merged,_=unify_documents(source,_stage2(),_stage3(),_stage4(),_sidecar(item))
    derived=merged.specialized_property_observations[0].value_derivation
    assert derived['candidate_values']==[13.6] and 'actual_values' not in derived
    semantic=derived['source_semantics']
    assert semantic['source_role']=='unknown' and semantic['footnote_associations'][0]['status']=='candidate'
    assert all(c['status']=='candidate' for c in semantic['conditions_from_source'])
    item.update(value_raw='13·30',row_index=1,cell_id='T_1:r0001:c0001')
    merged,_=unify_documents(source,_stage2(),_stage3(),_stage4(),_sidecar(item))
    assert not merged.specialized_property_observations[0].value_derivation['source_semantics']['footnote_associations']



def test_composite_offsets_use_actual_cell_not_candidate_whitespace():
    source=_review_source('Found (Calcd) | C%',['71.63(71.90)'])
    item=_candidate(value_raw=' 71.63(71.90) ',normalization_status='warning',normalization_warning='value_not_numeric',unit_raw='%')
    merged,_=unify_documents(source,_stage2(),_stage3(),_stage4(),_sidecar(item))
    for p in merged.specialized_property_observations:
        trace=p.candidate_trace;a,b=trace['source_span']
        assert trace['source_cell_raw'][a:b]==p.value_raw
        assert trace['source_candidate_value_raw']==' 71.63(71.90) '
