from __future__ import annotations

import json
from pathlib import Path

from schema.polymer_schema import Stage0Document, Stage0Element
from stages.stage4t_interpretation_apply import apply_table_interpretation, _sample_binding
from stages.stage4t_table_interpretation import Stage4TTableInterpretation
from stages.table_grid import parse_table_cells


TEST_ROOT = Path(__file__).parent
PROJECT_ROOT = TEST_ROOT.parents[1]
# 使用当前可复现的 0902 批次；fixture 中的解释仍作为冻结 LLM 结果输入。
BATCH_ROOT = PROJECT_ROOT / "batch_results" / "preview_batch_31_0902"
FIXTURE_PATH = TEST_ROOT / "fixtures" / "stage4t_table_interpretation_v0.1.json"


def _table(table_id: str, body: str) -> Stage0Element:
    return Stage0Element(
        block_id=table_id,
        type="table",
        page=1,
        source_block_index=0,
        table_body=body,
        table_cells=parse_table_cells(body, table_id),
    )


def _observation(table_id: str, row: int, column: int, value: str) -> dict:
    cell_id = f"{table_id}:r{row:04d}:c{column:04d}"
    return {
        "observation_id": f"{table_id}:{cell_id}",
        "table_id": table_id,
        "direction": "row_samples",
        "sample_label_raw": None,
        "property_name_raw": "unknown",
        "property_name_normalized": None,
        "semantic_label": None,
        "semantic_status": "unmapped",
        "candidate_class": "unknown_observation",
        "authority_target": None,
        "conditions": {},
        "measurement_role": "reported_unknown",
        "value_raw": value,
        "value_kind": "numeric_scalar",
        "value_has_footnote": False,
        "unit_raw": None,
        "unit_normalized": None,
        "unit_location": "not_found",
        "cell_id": cell_id,
        "row_index": row,
        "column_index": column,
        "binding_status": "unresolved",
        "publication_gate": {
            "status": "candidate_only",
            "target": None,
            "blockers": ["semantic_unmapped", "sample_not_resolved"],
        },
    }


def _assignment(
    cell_ids: list[str],
    role: str,
    *,
    normalized_name: str | None = None,
    semantic_label: str | None = None,
    measurement_role: str | None = None,
) -> dict:
    return {
        "source_cell_ids": cell_ids,
        "role": role,
        "normalized_name": normalized_name,
        "semantic_label": semantic_label,
        "measurement_role": measurement_role,
        "confidence": 0.99,
        "reason": "test fixture",
    }


def test_sample_binding_does_not_append_unmapped_structural_columns() -> None:
    table = _table("T_axis", "<table><tr><td>Polymer</td><td>m</td><td>x:y</td></tr>"
                   "<tr><td>P1</td><td>4</td><td>4:1</td></tr></table>")
    interpretation = Stage4TTableInterpretation.model_validate({
        "table_id": table.block_id, "direction": "row_samples", "axis_role": "named_sample",
        "sample_binding_strategy": "direct_row", "requires_human_review": True,
        "header_assignments": [
            _assignment(["T_axis:r0000:c0000"], "sample_axis", normalized_name="polymer_sample"),
            _assignment(["T_axis:r0000:c0001"], "composition_axis"),
            _assignment(["T_axis:r0000:c0002"], "composition_axis", normalized_name="comonomer_ratio")],
    })
    label, _ = _sample_binding(interpretation, interpretation.header_assignments,
        cells=table.table_cells, cell_by_id={c.cell_id:c for c in table.table_cells},
        row=1, column=1)
    assert label == "P1"


def test_apply_uses_spans_and_excludes_condition_header_observation() -> None:
    table = _table(
        "T_span",
        "<table><tr><td rowspan='2'>Polymer</td><td colspan='2'>TGA</td></tr>"
        "<tr><td>5%</td><td>50%</td></tr>"
        "<tr><td>P-1</td><td>291</td><td>335</td></tr></table>",
    )
    shadow = {
        "table_id": "T_span",
        "direction": "row_samples",
        "axis_role": "named_sample",
        "warnings": [],
        "observations": [
            _observation("T_span", 1, 1, "5%"),
            _observation("T_span", 1, 2, "50%"),
            _observation("T_span", 2, 1, "291"),
            _observation("T_span", 2, 2, "335"),
        ],
    }
    interpretation = {
        "schema_version": "stage4t_table_interpretation_schema.v1",
        "table_id": "T_span",
        "direction": "row_samples",
        "axis_role": "named_sample",
        "sample_binding_strategy": "direct_row",
        "header_assignments": [
            _assignment(
                ["T_span:r0000:c0000"],
                "sample_axis",
                normalized_name="polymer_sample",
            ),
            _assignment(
                ["T_span:r0000:c0001"],
                "official_property",
                normalized_name="thermal_decomposition_temperature",
            ),
            _assignment(
                ["T_span:r0001:c0001", "T_span:r0001:c0002"],
                "condition_axis",
                normalized_name="mass_loss_threshold",
            ),
        ],
        "requires_human_review": False,
        "warnings": [],
    }

    result, audit = apply_table_interpretation(table, shadow, interpretation)

    assert [item["value_raw"] for item in result["observations"]] == ["291", "335"]
    assert [item["sample_label_raw"] for item in result["observations"]] == [
        "P-1",
        "P-1",
    ]
    assert [item["conditions"] for item in result["observations"]] == [
        {"mass_loss_threshold": "5%"},
        {"mass_loss_threshold": "50%"},
    ]
    assert all(
        item["property_name_normalized"] == "thermal_decomposition_temperature"
        and item["unit_normalized"] is None
        and item["publication_gate"]["status"] == "candidate_only"
        and item["source_layer"] == "llm_enriched"
        and item["interpretation_status"] == "applied"
        and item["confidence_source"] == "llm_header_assignment"
        and item["interpretation_confidence"] == 0.99
        for item in result["observations"]
    )
    assert audit["input_observation_count"] == 4
    assert audit["output_observation_count"] == 2
    assert audit["shadow_observation_count"] == 4
    assert len(audit["excluded_header_observation_ids"]) == 2


def test_apply_column_samples_uses_grouped_header_and_rowspan_condition() -> None:
    table = _table(
        "T_column",
        "<table><tr><td></td><td></td><td colspan='2'>HT</td></tr>"
        "<tr><td rowspan='2'>Water</td><td>Metric A</td><td>10</td><td>20</td></tr>"
        "<tr><td>Metric B</td><td>30</td><td>40</td></tr></table>",
    )
    shadow = {
        "table_id": "T_column",
        "direction": "row_samples",
        "axis_role": "unknown",
        "warnings": [],
        "observations": [_observation("T_column", 2, 3, "40")],
    }
    interpretation = {
        "schema_version": "stage4t_table_interpretation_schema.v1",
        "table_id": "T_column",
        "direction": "column_samples",
        "axis_role": "grouped_sample",
        "sample_binding_strategy": "grouped_columns",
        "header_assignments": [
            _assignment(
                ["T_column:r0000:c0002"],
                "sample_axis",
                normalized_name="sample_group",
            ),
            _assignment(
                ["T_column:r0001:c0000"],
                "condition_axis",
                normalized_name="probe_phase",
            ),
            _assignment(
                ["T_column:r0002:c0001"],
                "material_characteristic",
                semantic_label="custom_metric",
            ),
            _assignment(
                ["T_column:r0002:c0001"],
                "measurement_role",
                measurement_role="calculated",
            ),
        ],
        "requires_human_review": False,
        "warnings": [],
    }

    result, _ = apply_table_interpretation(table, shadow, interpretation)
    candidate = result["observations"][0]

    assert candidate["direction"] == "column_samples"
    assert candidate["sample_label_raw"] == "HT"
    assert candidate["semantic_label"] == "custom_metric"
    assert candidate["conditions"] == {"probe_phase": "Water"}
    assert candidate["measurement_role"] == "calculated"
    assert "calculated_property_policy_not_resolved" in candidate[
        "publication_gate"
    ]["blockers"]
    assert candidate["binding_status"] == "bound"


def test_apply_grouped_columns_projects_property_headers_by_column() -> None:
    table = _table(
        "T_grouped_columns",
        "<table><tr><td colspan='2'>HS</td><td colspan='2'>HI</td></tr>"
        "<tr><td>2theta</td><td>d</td><td>2theta</td><td>d</td></tr>"
        "<tr><td>22.1</td><td>4.02</td><td>13.0</td><td>6.80</td></tr></table>",
    )
    shadow = {
        "table_id": "T_grouped_columns",
        "direction": "column_samples",
        "axis_role": "grouped_sample",
        "warnings": [],
        "observations": [
            _observation("T_grouped_columns", 2, 0, "22.1"),
            _observation("T_grouped_columns", 2, 1, "4.02"),
            _observation("T_grouped_columns", 2, 2, "13.0"),
            _observation("T_grouped_columns", 2, 3, "6.80"),
        ],
    }
    interpretation = {
        "schema_version": "stage4t_table_interpretation_schema.v1",
        "table_id": "T_grouped_columns",
        "direction": "column_samples",
        "axis_role": "grouped_sample",
        "sample_binding_strategy": "grouped_columns",
        "header_assignments": [
            _assignment(
                ["T_grouped_columns:r0000:c0000"],
                "sample_axis",
                normalized_name="polymer_sample",
            ),
            _assignment(
                ["T_grouped_columns:r0000:c0002"],
                "sample_axis",
                normalized_name="polymer_sample",
            ),
            _assignment(
                ["T_grouped_columns:r0001:c0000"],
                "material_characteristic",
                semantic_label="xray_diffraction_peak",
            ),
            _assignment(
                ["T_grouped_columns:r0001:c0001"],
                "material_characteristic",
                semantic_label="d_spacing",
            ),
            _assignment(
                ["T_grouped_columns:r0001:c0002"],
                "material_characteristic",
                semantic_label="xray_diffraction_peak",
            ),
            _assignment(
                ["T_grouped_columns:r0001:c0003"],
                "material_characteristic",
                semantic_label="d_spacing",
            ),
        ],
        "requires_human_review": False,
        "warnings": [],
    }

    result, audit = apply_table_interpretation(table, shadow, interpretation)

    assert audit["applied_observation_count"] == 4
    assert [
        item["semantic_label"] for item in result["observations"]
    ] == [
        "xray_diffraction_peak",
        "d_spacing",
        "xray_diffraction_peak",
        "d_spacing",
    ]
    assert all(
        item["source_layer"] == "llm_enriched"
        and item["interpretation_status"] == "applied"
        for item in result["observations"]
    )


def test_apply_reroutes_uncontrolled_molecular_weight_header_to_specialized() -> None:
    table = _table(
        "T_mn_route",
        "<table><tr><td>Sample</td><td>M_n</td></tr>"
        "<tr><td>P-1</td><td>1000</td></tr></table>",
    )
    shadow = {
        "table_id": "T_mn_route",
        "direction": "row_samples",
        "axis_role": "named_sample",
        "warnings": [],
        "observations": [_observation("T_mn_route", 1, 1, "1000")],
    }
    interpretation = {
        "schema_version": "stage4t_table_interpretation_schema.v1",
        "table_id": "T_mn_route",
        "direction": "row_samples",
        "axis_role": "named_sample",
        "sample_binding_strategy": "direct_row",
        "header_assignments": [
            _assignment(
                ["T_mn_route:r0000:c0000"],
                "sample_axis",
                normalized_name="polymer_sample",
            ),
            _assignment(
                ["T_mn_route:r0000:c0001"],
                "official_property",
                normalized_name="molecular_weight",
            ),
        ],
        "requires_human_review": False,
        "warnings": [],
    }

    result, audit = apply_table_interpretation(table, shadow, interpretation)
    candidate = result["observations"][0]

    assert candidate["property_name_normalized"] is None
    assert candidate["semantic_label"] == "molecular_weight"
    assert candidate["semantic_resolution"]["status"] == "specialized"
    assert "semantic_rerouted_to_specialized" in candidate[
        "interpretation_application"
    ]["warnings"]
    assert audit["semantic_resolution_counts"] == {"specialized": 1}


def test_apply_semantic_conflict_keeps_original_candidate() -> None:
    table = _table(
        "T_conflict",
        "<table><tr><td>Sample</td><td>Metric</td></tr>"
        "<tr><td>P-1</td><td>12</td></tr></table>",
    )
    original = _observation("T_conflict", 1, 1, "12")
    shadow = {
        "table_id": "T_conflict",
        "direction": "row_samples",
        "warnings": [],
        "observations": [original],
    }
    interpretation = {
        "schema_version": "stage4t_table_interpretation_schema.v1",
        "table_id": "T_conflict",
        "direction": "row_samples",
        "axis_role": "named_sample",
        "sample_binding_strategy": "direct_row",
        "header_assignments": [
            _assignment(
                ["T_conflict:r0000:c0001"],
                "official_property",
                normalized_name="glass_transition_temperature",
            ),
            _assignment(
                ["T_conflict:r0000:c0001"],
                "material_characteristic",
                semantic_label="custom_metric",
            ),
        ],
        "requires_human_review": True,
        "warnings": [],
    }

    result, audit = apply_table_interpretation(table, shadow, interpretation)
    candidate = result["observations"][0]

    assert candidate["property_name_normalized"] is None
    assert candidate["semantic_label"] is None
    assert candidate["interpretation_application"]["status"] == "semantic_conflict"
    assert candidate["publication_gate"]["status"] == "candidate_only"
    assert audit["status"] == "applied_with_conflicts"


def test_apply_real_five_table_fixture_produces_98_semantic_candidates() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    output: list[dict] = []
    excluded = 0
    for case in fixture["cases"]:
        document_dir = BATCH_ROOT / case["doc_id"]
        document = Stage0Document.model_validate_json(
            (document_dir / "stage0_blocks.json").read_text(encoding="utf-8")
        )
        sidecar = json.loads(
            (document_dir / "stage4t_shadow.json").read_text(encoding="utf-8")
        )
        table = next(
            item for item in document.elements if item.block_id == case["table_id"]
        )
        shadow = next(
            item for item in sidecar["tables"] if item["table_id"] == case["table_id"]
        )
        if "rule_observations" in shadow:
            shadow = {
                **shadow,
                "observations": shadow["rule_observations"],
            }
        result, audit = apply_table_interpretation(
            table,
            shadow,
            case["interpretation"],
        )
        output.extend(result["observations"])
        excluded += len(audit["excluded_header_observation_ids"])

    assert len(output) == 98
    assert excluded == 5
    assert all(
        item.get("property_name_normalized") or item.get("semantic_label")
        for item in output
    )
    assert all(
        item["extraction_source"] == "llm_structure_interpretation"
        and item["publication_gate"]["status"] == "candidate_only"
        for item in output
    )
    decomposition = [
        item
        for item in output
        if item.get("property_name_normalized")
        == "thermal_decomposition_temperature"
    ]
    residual_mass = [
        item for item in output if item.get("semantic_label") == "residual_mass_fraction"
    ]
    assert decomposition and all(item["unit_normalized"] is None for item in decomposition)
    assert residual_mass and all(item["unit_normalized"] == "%" for item in residual_mass)
    assert all(
        "Water" not in str(item.get("property_name_raw"))
        for item in output
        if item.get("property_name_normalized") == "contact_angle"
    )


def test_unmapped_property_keeps_source_name_and_measurement_role():
    table = _table("T_new", "<table><tr><td>Sample</td><td>Novel response</td></tr>"
                   "<tr><td></td><td>Found</td></tr><tr><td>A</td><td>12.7</td></tr></table>")
    interpretation = Stage4TTableInterpretation.model_validate({
        "table_id": "T_new", "direction": "row_samples", "axis_role": "named_sample",
        "sample_binding_strategy": "direct_row", "requires_human_review": False,
        "header_assignments": [
            _assignment(["T_new:r0000:c0000"], "sample_axis", normalized_name="polymer_sample"),
            _assignment(["T_new:r0000:c0001"], "unmapped_property"),
            _assignment(["T_new:r0001:c0001"], "measurement_role", measurement_role="experimental")],
    })
    shadow = {"observations": [_observation("T_new", 2, 1, "12.7")]}
    result, _ = apply_table_interpretation(table, shadow, interpretation)
    item = result["observations"][0]
    assert item["value_raw"] == "12.7"
    assert "Novel response" in item["property_name_raw"]
    assert item["measurement_role"] == "experimental"
    assert item["property_name_normalized"] is None and item["semantic_label"] is None
    assert item["publication_gate"]["status"] == "candidate_only"
    assert interpretation.requires_human_review


def test_metadata_survives_unknown_property_and_conflicting_roles():
    table = _table("T_meta", "<table><tr><td>Sample</td><td>Found</td></tr>"
                   "<tr><td>A</td><td>7</td></tr></table>")
    assignments = [_assignment(["T_meta:r0000:c0001"], "measurement_role", measurement_role="experimental")]
    payload = {"table_id": "T_meta", "direction": "row_samples", "axis_role": "named_sample",
               "sample_binding_strategy": "direct_row", "requires_human_review": True,
               "header_assignments": assignments}
    shadow = {"observations": [_observation("T_meta", 1, 1, "7")]}
    result, _ = apply_table_interpretation(table, shadow, payload)
    assert result["observations"][0]["measurement_role"] == "experimental"
    assignments.append(_assignment(["T_meta:r0000:c0001"], "measurement_role", measurement_role="calculated"))
    result, _ = apply_table_interpretation(table, shadow, payload)
    item = result["observations"][0]
    assert item["measurement_role"] == "reported_unknown"
    assert "multiple_measurement_roles" in item["metadata_interpretation"]["warnings"]
    # The property-mapped path must preserve the same independent metadata.
    assignments.append(_assignment(["T_meta:r0000:c0001"], "unmapped_property"))
    shadow["observations"][0]["conditions"] = {"temperature": "25 C"}
    result, _ = apply_table_interpretation(table, shadow, payload)
    item = result["observations"][0]
    assert item["measurement_role"] == "reported_unknown"
    assert item["conditions"]["temperature"] == "25 C"
    assert "multiple_measurement_roles" in item["interpretation_application"]["warnings"]
