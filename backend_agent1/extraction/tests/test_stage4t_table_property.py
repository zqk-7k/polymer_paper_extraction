from __future__ import annotations

from schema.polymer_schema import Stage0Document, Stage0Element, Stage0TableCell
from stages.stage4t_table_property import (
    _row_value_column, build_table_interpretation_context, shadow_extract_table,
)
from stages.table_grid import parse_table_cells


def _table(table_id: str, body: str, *, caption: str | None = None) -> Stage0Element:
    return Stage0Element(
        block_id=table_id,
        type="table",
        page=1,
        source_block_index=0,
        caption=caption,
        table_body=body,
        table_cells=parse_table_cells(body, table_id),
    )


def test_table_context_keeps_own_notes_separate_from_nearby_footnotes():
    table = _table("T_notes", "<table><tr><td>Mw</td></tr></table>")
    table.table_notes = ["a) GPC peak maximum; CHCl3 against polystyrene."]
    footnote = Stage0Element(
        block_id="F_1", type="footnote", page=1, source_block_index=1,
        text="b) Broad peak.",
    )
    # Only elements are read by this context helper.
    document = Stage0Document.model_construct(elements=[table, footnote])
    context = build_table_interpretation_context(document, table)
    assert context["footnotes"] == [
        {"block_id": "T_notes", "page": 1, "text": table.table_notes[0], "table_note_index": 0},
        {"block_id": "F_1", "page": 1, "text": "b) Broad peak."},
    ]
    assert context["source_block_ids"] == ["T_notes", "F_1"]


def test_explicit_molecular_weight_and_heat_capacity_display_scales_are_inverted():
    from stages.stage4t_table_property import _unit_info
    for header, exponent in [("Mw ×10^-3 (g/mol)", 3), ("ΔCp (cal/g°C) (×10^2)", -2)]:
        result = _unit_info([header], None)
        assert result["scale_factor_exponent"] == exponent
        assert result["scale_factor_status"] == "explicit_inverse_display_scale"


def test_shadow_extracts_row_samples_with_stable_cell_locators() -> None:
    report = shadow_extract_table(_table(
        "T_row",
        "<table><tr><td>Polymer</td><td>Tg (°C)</td><td>Yield (%)</td></tr>"
        "<tr><td>PC-1</td><td>120</td><td>87.2</td></tr>"
        "<tr><td>PC-2</td><td>130</td><td>86.5</td></tr></table>",
    ))

    assert report["direction"] == "row_samples"
    tg = [
        item for item in report["observations"]
        if item["property_name_normalized"] == "glass_transition_temperature"
    ]
    assert [(item["sample_label_raw"], item["value_raw"]) for item in tg] == [
        ("PC-1", "120"),
        ("PC-2", "130"),
    ]
    assert tg[0]["cell_id"] == "T_row:r0001:c0001"
    assert tg[0]["row_index"] == 1
    assert tg[0]["column_index"] == 1
    assert tg[0]["unit_normalized"] == "°C"
    assert tg[0]["normalized_value"] == 120.0
    assert tg[0]["normalization_status"] == "normalized"
    assert tg[0]["semantic_status"] == "normalized"
    assert tg[0]["candidate_class"] == "official_property"
    assert tg[0]["authority_target"] == "property_observation"
    assert tg[0]["publication_gate"]["status"] == "candidate_only"
    assert tg[0]["publication_gate"]["blockers"] == ["sample_not_resolved"]
    assert tg[0]["evidence"] == {
        "table_id": "T_row",
        "cell_id": "T_row:r0001:c0001",
        "row_index": 1,
        "column_index": 1,
    }
    assert tg[0]["candidate_role"] == "property_candidate"
    assert tg[0]["candidate_state"] == "raw_candidate"
    assert tg[0]["evidence_locator"] == {
        "source": "table",
        "table_id": "T_row",
        "cell_id": "T_row:r0001:c0001",
        "row_index": 1,
        "column_index": 1,
        "header_path": ["Tg (°C)"],
        "axis_role": "row_samples",
    }


def test_shadow_repairs_numeric_property_shifted_after_method_column() -> None:
    # Some source HTML omits a method/status sub-column in the header.  The
    # PMT header is then one column left of the numeric cells; the repair must
    # be shape-based and retain an auditable inferred_right_shift status.
    cells = [
        Stage0TableCell(cell_id="T_shift:r0000:c0000", row_index=0, column_index=0, text="Sample"),
        Stage0TableCell(cell_id="T_shift:r0000:c0001", row_index=0, column_index=1, text="PMT (°C)"),
        Stage0TableCell(cell_id="T_shift:r0000:c0002", row_index=0, column_index=2, text="Comments"),
        Stage0TableCell(cell_id="T_shift:r0000:c0003", row_index=0, column_index=3, text="Other 1"),
        Stage0TableCell(cell_id="T_shift:r0000:c0004", row_index=0, column_index=4, text="Other 2"),
        Stage0TableCell(cell_id="T_shift:r0001:c0000", row_index=1, column_index=0, text="A"),
        Stage0TableCell(cell_id="T_shift:r0001:c0001", row_index=1, column_index=1, text="LTS"),
        Stage0TableCell(cell_id="T_shift:r0001:c0002", row_index=1, column_index=2, text="240"),
        Stage0TableCell(cell_id="T_shift:r0001:c0003", row_index=1, column_index=3, text="1"),
        Stage0TableCell(cell_id="T_shift:r0001:c0004", row_index=1, column_index=4, text="2"),
        Stage0TableCell(cell_id="T_shift:r0002:c0000", row_index=2, column_index=0, text="B"),
        Stage0TableCell(cell_id="T_shift:r0002:c0001", row_index=2, column_index=1, text="HTS"),
        Stage0TableCell(cell_id="T_shift:r0002:c0002", row_index=2, column_index=2, text="210"),
        Stage0TableCell(cell_id="T_shift:r0002:c0003", row_index=2, column_index=3, text="3"),
        Stage0TableCell(cell_id="T_shift:r0002:c0004", row_index=2, column_index=4, text="4"),
        Stage0TableCell(cell_id="T_shift:r0003:c0000", row_index=3, column_index=0, text="C"),
        Stage0TableCell(cell_id="T_shift:r0003:c0001", row_index=3, column_index=1, text="LTS"),
        Stage0TableCell(cell_id="T_shift:r0003:c0002", row_index=3, column_index=2, text="350"),
        Stage0TableCell(cell_id="T_shift:r0003:c0003", row_index=3, column_index=3, text="5"),
        Stage0TableCell(cell_id="T_shift:r0003:c0004", row_index=3, column_index=4, text="6"),
    ]
    table = Stage0Element(
        block_id="T_shift",
        type="table",
        page=1,
        source_block_index=0,
        table_body="<table></table>",
        table_cells=cells,
    )

    report = shadow_extract_table(table)
    pmt = [
        item for item in report["observations"]
        if item["property_name_normalized"] == "melting_temperature"
    ]

    assert [(item["sample_label_raw"], item["value_raw"], item["alignment_status"])
            for item in pmt] == [
        ("A", "240", "inferred_right_shift"),
        ("B", "210", "inferred_right_shift"),
        ("C", "350", "inferred_right_shift"),
    ]


def _shift_profile_cells(
    current_values: list[str],
    right_values: list[str],
    *,
    current_column: int = 1,
    column_count: int = 3,
) -> list[Stage0TableCell]:
    cells = []
    for row, value in enumerate(current_values, start=1):
        cells.append(Stage0TableCell(
            cell_id=f"T_profile:r{row:04d}:c{current_column:04d}",
            row_index=row,
            column_index=current_column,
            text=value,
        ))
    for row, value in enumerate(right_values, start=1):
        cells.append(Stage0TableCell(
            cell_id=f"T_profile:r{row:04d}:c{current_column + 1:04d}",
            row_index=row,
            column_index=current_column + 1,
            text=value,
        ))
    return cells


def test_numeric_column_shift_requires_all_shape_signals() -> None:
    """右移恢复的每个信号缺失时都应保持原列。"""

    cases = [
        (["LTS", "HTS", "LTS"], ["240", "210", "350"], None, "missing_unit"),
        (["LTS", "HTS", "LTS"], ["240", "", "350"], "°C", "right_values_too_few"),
        (["LTS", "240", "LTS"], ["210", "350", "290"], "°C", "current_column_mixed"),
        (["240", "210", "350"], ["1", "2", "3"], "°C", "both_columns_numeric"),
        (["LTS", "HTS", "LTS"], ["-", "N/A", ""], "°C", "right_column_placeholders"),
    ]
    for current_values, right_values, unit_raw, _case in cases:
        cells = _shift_profile_cells(current_values, right_values)
        column, status = _row_value_column(
            {
                "column_index": 1,
                "property_name_normalized": "melting_temperature",
                "unit_raw": unit_raw,
            },
            cells,
            data_start=1,
            row_count=4,
            column_count=3,
        )
        assert (column, status) == (1, "exact"), _case


def test_numeric_column_shift_does_not_run_past_last_column() -> None:
    cells = _shift_profile_cells(
        ["LTS", "HTS", "LTS"], ["240", "210", "350"],
        current_column=2,
        column_count=3,
    )
    assert _row_value_column(
        {
            "column_index": 2,
            "property_name_normalized": "melting_temperature",
            "unit_raw": "°C",
        },
        cells,
        data_start=1,
        row_count=4,
        column_count=3,
    ) == (2, "exact")


def test_intrinsic_viscosity_shift_requires_a_solubility_state_anchor() -> None:
    cells = _shift_profile_cells(
        ["342", "290", "310"], ["1.43", "0.12", "0.04"],
    )
    assert _row_value_column(
        {
            "column_index": 1,
            "property_name_normalized": "intrinsic_viscosity",
            "unit_raw": "dL/g",
        },
        cells,
        data_start=1,
        row_count=4,
        column_count=3,
    ) == (1, "exact")


def test_unit_raw_does_not_capture_tga_threshold_or_conductivity_denominator() -> None:
    tga = shadow_extract_table(_table(
        "T_unit_tga",
        r"<table><tr><td>Polymer</td><td>$T_d^{20\%}$ (°C)</td></tr>"
        r"<tr><td>P-1</td><td>473</td></tr></table>",
    ))
    conductivity = shadow_extract_table(_table(
        "T_unit_conductivity",
        "<table><tr><td>Polymer</td><td>Conductivity (S/cm)</td></tr>"
        "<tr><td>P-1</td><td>4.2</td></tr></table>",
    ))

    assert tga["observations"][0]["unit_raw"] == "°C"
    assert tga["observations"][0]["unit_normalized"] == "°C"
    assert conductivity["observations"][0]["unit_raw"] == "S/cm"
    assert conductivity["observations"][0]["unit_normalized"] == "S/cm"


def test_shadow_extracts_table_header_scale_factor_metadata() -> None:
    report = shadow_extract_table(_table(
        "T_scale",
        "<table><tr><td>Sample</td><td>Conductivity (×10^-12 S/cm)</td></tr>"
        "<tr><td>PC-1</td><td>4.2</td></tr></table>",
    ))

    conductivity = report["observations"][0]
    assert conductivity["scale_factor_raw"] == "×10^-12"
    assert conductivity["scale_factor_exponent"] == -12
    assert conductivity["scale_factor_location"] == "header"
    assert conductivity["restored_value"] == 4.2e-12


def test_shadow_inverts_explicit_inverse_ohm_display_scale() -> None:
    report = shadow_extract_table(_table(
        "T_inverse_scale",
        r"<table><tr><td>Sample</td><td>$\sigma (10^{12} \Omega^{-1} \text{cm}^{-1})$</td></tr>"
        r"<tr><td>PC-1</td><td>3.65</td></tr></table>",
    ))

    conductivity = report["observations"][0]
    assert conductivity["scale_factor_raw"] == "10^{12}"
    assert conductivity["scale_factor_exponent"] == -12
    assert conductivity["scale_factor_status"] == "explicit_inverse_display_scale"
    assert conductivity["restored_value"] == 3.65e-12


def test_shadow_leaves_scale_factor_metadata_empty_when_not_reported() -> None:
    report = shadow_extract_table(_table(
        "T_no_scale",
        "<table><tr><td>Sample</td><td>Tg (°C)</td></tr>"
        "<tr><td>PC-1</td><td>120</td></tr></table>",
    ))

    observation = report["observations"][0]
    assert observation["scale_factor_raw"] is None
    assert observation["scale_factor_exponent"] is None
    assert observation["scale_factor_location"] == "not_found"


def test_shadow_extracts_explicit_sample_series_from_caption_only() -> None:
    report = shadow_extract_table(_table(
        "T_sample_series",
        "<table><tr><td>Run</td><td>Tg (°C)</td></tr>"
        "<tr><td>1</td><td>120</td></tr>"
        "<tr><td>2</td><td>130</td></tr></table>",
        caption="Glass transition temperatures for PC-1–PC-2 samples",
    ))

    assert report["sample_series"] == "PC-1–PC-2"
    assert report["sample_axis"] == "row"
    assert [
        (item["sample_label_raw"], item["value_raw"])
        for item in report["observations"]
    ] == [("1", "120"), ("2", "130")]


def test_shadow_does_not_infer_sample_series_from_numeric_range() -> None:
    report = shadow_extract_table(_table(
        "T_numeric_series",
        "<table><tr><td>Run</td><td>Tg (°C)</td></tr>"
        "<tr><td>1</td><td>120</td></tr>"
        "<tr><td>2</td><td>130</td></tr></table>",
        caption="Measurements at runs 1–15",
    ))

    assert report["sample_series"] is None


def test_wide_candidate_layer_preserves_yield_without_classifying_as_property() -> None:
    report = shadow_extract_table(_table(
        "T_wide_candidates",
        "<table><tr><td>Sample</td><td>custom score q</td><td>Yield (%)</td></tr>"
        "<tr><td>AP-PCL</td><td>-0.15</td><td>87</td></tr></table>",
    ))

    assert len(report["observations"]) == 2
    candidate = report["observations"][0]
    assert candidate["property_name_raw"] == "custom score q"
    assert candidate["semantic_status"] == "unmapped"
    assert candidate["candidate_class"] == "unknown_observation"
    assert candidate["authority_target"] is None
    assert candidate["publication_gate"]["blockers"] == [
        "semantic_unmapped",
        "sample_not_resolved",
    ]
    raw_yield = report["observations"][1]
    assert raw_yield["value_raw"] == "87"
    assert raw_yield["extraction_source"] == "input_cell_preservation"
    assert raw_yield["property_name_normalized"] is None
    assert raw_yield["authority_target"] is None


def test_interaction_parameter_is_mapped_characteristic_not_morphology() -> None:
    report = shadow_extract_table(_table(
        "T_interaction",
        "<table><tr><td>Sample</td><td>χ23</td></tr>"
        "<tr><td>AP-PCL</td><td>-0.15</td></tr></table>",
    ))

    candidate = report["observations"][0]
    assert candidate["semantic_status"] == "mapped_characteristic"
    assert candidate["semantic_label"] == "polymer_polymer_interaction_parameter"
    assert candidate["candidate_class"] == "material_characteristic"
    assert candidate["authority_target"] == "material_characteristic_observation"
    assert candidate["property_name_normalized"] is None


def test_scientific_notation_is_not_treated_as_numeric_range() -> None:
    report = shadow_extract_table(_table(
        "T_scientific",
        "<table><tr><td>Sample</td><td>custom parameter</td></tr>"
        "<tr><td>P-1</td><td>9.63 × 10-5</td></tr></table>",
    ))

    assert report["observations"][0]["value_kind"] == "numeric_scalar"
    assert report["observations"][0]["normalized_value"] == 9.63e-5


def test_shadow_extracts_transposed_table_and_deduplicates_properties() -> None:
    report = shadow_extract_table(_table(
        "T_column",
        "<table><tr><td></td><td>HS</td><td>HI</td><td>HT</td></tr>"
        "<tr><td>$T_{m}$ (°C)</td><td>103</td><td>—</td><td>156</td></tr>"
        "<tr><td>$\\Delta H_{m}$ (J/g)</td><td>36.0</td><td>—</td><td>12.0</td></tr></table>",
    ))

    assert report["direction"] == "column_samples"
    assert len(report["property_candidates"]) == 2
    assert {
        item["property_name_normalized"] for item in report["property_candidates"]
    } == {"melting_temperature", "heat_of_fusion"}
    assert [
        (item["sample_label_raw"], item["property_name_normalized"], item["value_raw"])
        for item in report["observations"]
    ] == [
        ("HS", "melting_temperature", "103"),
        ("HS", "heat_of_fusion", "36.0"),
        ("HT", "melting_temperature", "156"),
        ("HT", "heat_of_fusion", "12.0"),
    ]


def test_explicit_polymer_column_accepts_roman_numeral_sample_labels() -> None:
    report = shadow_extract_table(_table(
        "T_roman",
        "<table><tr><td>Polymer</td><td>$T_{\\text{d}}$ (°C)</td></tr>"
        "<tr><td>I</td><td>435</td></tr>"
        "<tr><td>II</td><td>438</td></tr></table>",
    ))

    assert [
        (item["sample_label_raw"], item["property_name_normalized"], item["value_raw"])
        for item in report["observations"]
    ] == [
        ("I", "thermal_decomposition_temperature", "435"),
        ("II", "thermal_decomposition_temperature", "438"),
    ]


def test_explicit_plural_polymer_column_accepts_long_and_numeric_labels() -> None:
    report = shadow_extract_table(_table(
        "T_explicit_samples",
        "<table><tr><td>Name of Polymers or Blends</td><td>$T_g$ (°C)</td></tr>"
        "<tr><td>100% Poly (3-hydroxy butyric acid) (PHBA)</td><td>48</td></tr>"
        "<tr><td>10</td><td>46</td></tr>"
        "<tr><td>P-1</td><td>50</td></tr></table>",
    ))

    assert [item["sample_label_raw"] for item in report["observations"]] == [
        "100% Poly (3-hydroxy butyric acid) (PHBA)",
        "10",
        "P-1",
    ]


def test_tga_mass_loss_threshold_header_maps_to_decomposition_temperature() -> None:
    report = shadow_extract_table(_table(
        "T_tga_threshold",
        "<table><tr><td>Polymer</td><td>TGA-5%</td></tr>"
        "<tr><td>P-1</td><td>331</td></tr></table>",
    ))

    assert report["observations"][0]["property_name_normalized"] == (
        "thermal_decomposition_temperature"
    )


def test_shadow_preserves_mixed_sample_binding_when_property_is_unmapped() -> None:
    report = shadow_extract_table(_table(
        "T_mixed",
        "<table><tr><td>Polymer</td><td>λmax (nm)</td>"
        "<td>Polymer</td><td>λmax (nm)</td></tr>"
        "<tr><td>P-1</td><td>401</td><td>P-2</td><td>384</td></tr></table>",
    ))

    assert report["direction"] == "mixed"
    assert [
        (item["sample_label_raw"], item["value_raw"])
        for item in report["observations"]
    ] == [("P-1", "401"), ("P-2", "384")]
    assert all(
        item["property_name_normalized"] is None
        and item["binding_status"] == "unresolved"
        for item in report["observations"]
    )
    assert {item["reason"] for item in report["unresolved"]} == {
        "property_mapping_not_found"
    }


def test_shadow_does_not_guess_row_binding_for_unknown_direction() -> None:
    report = shadow_extract_table(_table(
        "T_unknown",
        "<table><tr><td>A</td><td>B</td></tr>"
        "<tr><td>1</td><td>2</td></tr></table>",
    ))

    assert report["direction"] == "unknown"
    assert report["property_candidates"] == []
    assert len(report["observations"]) == 1
    candidate = report["observations"][0]
    assert candidate["value_raw"] == "2"
    assert candidate["sample_label_raw"] is None
    assert candidate["property_name_normalized"] is None
    assert candidate["extraction_source"] == "input_cell_preservation"
    assert candidate["publication_gate"]["status"] != "accepted"
    assert report["input_capture_coverage"]["status"] == "captured_pending_interpretation"
    assert "shadow_direction_unknown" in report["warnings"]


def test_char_yield_is_not_mapped_to_decomposition_temperature() -> None:
    report = shadow_extract_table(_table(
        "T_char_yield",
        "<table><tr><td>Polymer</td><td>Tg (°C)</td>"
        "<td>Char yield at 700°C (%)</td></tr>"
        "<tr><td>P-1</td><td>300</td><td>49</td></tr></table>",
    ))

    assert [
        item["property_name_normalized"] for item in report["observations"]
    ] == ["glass_transition_temperature", None]
    char_yield = report["observations"][1]
    assert char_yield["semantic_label"] == "char_yield"
    assert char_yield["conditions"] == {"temperature_celsius": 700.0}
    assert char_yield["binding_status"] == "unresolved"
    assert all(
        item["property_name_normalized"] != "thermal_decomposition_temperature"
        for item in report["property_candidates"]
    )


def test_contact_angle_degree_footnotes_are_numeric_candidates() -> None:
    report = shadow_extract_table(_table(
        "T_contact_angle_footnote",
        "<table><tr><td></td><td></td><td>poly(MPC)</td></tr>"
        "<tr><td>Water</td><td>(static)</td><td>$1 \\sim 3^{\\circ}$</td></tr>"
        "<tr><td></td><td>(advancing)</td><td>$13^{°b)}$</td></tr>"
        "<tr><td></td><td>(receding)</td><td>$<5^{°b)}$</td></tr>"
        "<tr><td></td><td>(sliding)</td><td>$15^{°b)}$</td></tr></table>",
    ))

    assert report["direction"] == "row_samples"
    assert [item["cell_id"] for item in report["observations"]] == [
        "T_contact_angle_footnote:r0001:c0002",
        "T_contact_angle_footnote:r0002:c0002",
        "T_contact_angle_footnote:r0003:c0002",
        "T_contact_angle_footnote:r0004:c0002",
    ]


def test_contact_angle_latex_degree_footnotes_are_numeric_candidates() -> None:
    report = shadow_extract_table(_table(
        "T_contact_angle_latex_footnote",
        "<table><tr><td>Polymer</td><td>Tg (°C)</td></tr>"
        "<tr><td>P-0</td><td>12</td></tr>"
        "<tr><td>P-1</td><td>$13^{\\circ b)}$</td></tr></table>",
    ))

    assert len(report["observations"]) == 2
    assert report["observations"][1]["value_raw"] == "$13^{\\circ b)}$"


def test_solubility_symbols_are_categorical_candidates_with_solvent_condition() -> None:
    report = shadow_extract_table(_table(
        "T_solubility",
        "<table><tr><td>Polymer</td><td>DMF</td><td>THF</td></tr>"
        "<tr><td>P-1</td><td>++</td><td>-</td></tr>"
        "<tr><td>P-2</td><td>+-</td><td>±</td></tr></table>",
        caption="Solubility of polymers",
    ))

    assert len(report["observations"]) == 4
    assert all(item["semantic_label"] == "solubility" for item in report["observations"])
    assert [item["property_variant"] for item in report["observations"]] == [
        "soluble",
        "partially_soluble",
        "insoluble",
        "partially_soluble",
    ]
    assert [item["conditions"]["solvent"] for item in report["observations"]] == [
        "DMF",
        "DMF",
        "THF",
        "THF",
    ]
    assert all(item["value_kind"] == "categorical" for item in report["observations"])


def test_thermal_decomposition_variants_keep_general_conditions() -> None:
    report = shadow_extract_table(_table(
        "T_thermal_variants",
        "<table><tr><td>Polymer</td><td>$T_i$ (°C)</td>"
        "<td>$T_{10}$ (°C)</td><td>$T_{max}$ (°C)</td></tr>"
        "<tr><td>P-1</td><td>229</td><td>327</td><td>475</td></tr></table>",
    ))

    assert [item["property_name_normalized"] for item in report["observations"]] == [
        "thermal_decomposition_temperature",
        "thermal_decomposition_temperature",
        "thermal_decomposition_temperature",
    ]
    assert [item["property_variant"] for item in report["observations"]] == [
        "initial_decomposition",
        "mass_loss_threshold",
        "maximum_decomposition_rate",
    ]
    assert report["observations"][1]["conditions"] == {"mass_loss_percent": 10.0}


def test_bare_ti_without_degradation_context_stays_unmapped() -> None:
    report = shadow_extract_table(_table(
        "T_isotropic_transition",
        "<table><tr><td>Polymer</td><td>DSC (°C)</td></tr>"
        "<tr><td></td><td>$T_i$</td></tr>"
        "<tr><td>LC-1</td><td>212</td></tr></table>",
        caption="Liquid crystalline transition temperatures",
    ))

    assert report["observations"][0]["property_name_normalized"] is None
    assert report["observations"][0]["semantic_label"] == "transition_temperature_ti"
    assert report["observations"][0]["binding_status"] == "unresolved"


def test_grouped_polymer_header_does_not_override_run_sample_axis() -> None:
    report = shadow_extract_table(_table(
        "T_group_header",
        "<table><tr><td rowspan='2'>Run</td><td colspan='3'>Polymer</td></tr>"
        "<tr><td>Yield (%)</td><td>$η_{inh}$ (dL/g)</td><td>State</td></tr>"
        "<tr><td>1</td><td>76.7</td><td>0.21</td><td>ppt.</td></tr>"
        "<tr><td>A2</td><td>80.0</td><td>0.25</td><td>solution</td></tr></table>",
    ))

    assert report["observations"][0]["sample_label_raw"] == "1"
    assert report["observations"][0]["property_variant"] == "inherent"


def test_characteristic_semantics_do_not_enter_wrong_property_buckets() -> None:
    report = shadow_extract_table(_table(
        "T_characteristics",
        "<table><tr><td>Sample</td><td>$M_n$ (g/mol)</td><td>$M_w$ (g/mol)</td>"
        "<td>Degree of Crystallinity (%)</td><td>Cell Density (cells/cm3)</td>"
        "<td>wt loss (%)</td></tr>"
        "<tr><td>S-1</td><td>10000</td><td>20000</td><td>45</td><td>2.3</td><td>75</td></tr></table>",
    ))

    assert [item["semantic_label"] for item in report["observations"]] == [
        "molecular_weight",
        "molecular_weight",
        "crystallinity",
        "cell_density",
        "mass_loss_fraction",
    ]
    assert [item["property_variant"] for item in report["observations"][:2]] == [
        "number_average",
        "weight_average",
    ]
    assert all(item["property_name_normalized"] is None for item in report["observations"])


def test_molecular_weight_ratio_is_distribution_not_weight_average() -> None:
    report = shadow_extract_table(_table(
        "T_molecular_weight_distribution",
        "<table><tr><td>Polymer</td><td>$M_w$</td><td>$M_w/M_n$</td>"
        "<td>$\\overline{M_n}/\\overline{M_w}$</td></tr>"
        "<tr><td>P-1</td><td>23800</td><td>1.21</td><td>0.83</td></tr></table>",
    ))

    assert [item["semantic_label"] for item in report["observations"]] == [
        "molecular_weight",
        "molecular_weight_distribution",
        "molecular_weight_distribution",
    ]
    assert report["observations"][0]["property_variant"] == "weight_average"
    assert report["observations"][1]["property_variant"] is None


def test_viscosity_column_shift_requires_strong_adjacent_evidence() -> None:
    report = shadow_extract_table(_table(
        "T_shifted_viscosity",
        "<table><tr><td>Codea</td><td>Method</td><td>PMT (°C)</td>"
        "<td>$η_{inh}$</td><td>Comments</td></tr>"
        "<tr><td>P-1</td><td></td><td>LTS</td><td>342</td><td>1.43</td></tr>"
        "<tr><td>P-2</td><td></td><td>HTS</td><td>290</td><td>0.12</td></tr>"
        "<tr><td>P-3</td><td></td><td>HTS</td><td>310</td><td>Insoluble</td></tr>"
        "<tr><td>P-4</td><td></td><td>HTS</td><td>250</td><td>0.04</td></tr></table>",
    ))

    viscosity = [
        item for item in report["observations"]
        if item["property_name_normalized"] == "intrinsic_viscosity"
    ]
    assert [item["cell_id"] for item in viscosity] == [
        "T_shifted_viscosity:r0001:c0004",
        "T_shifted_viscosity:r0002:c0004",
        "T_shifted_viscosity:r0004:c0004",
    ]
    assert all(item["header_column_index"] == 3 for item in viscosity)
    assert all(
        item["alignment_status"] == "inferred_right_shift"
        for item in viscosity
    )
    insoluble = next(
        item for item in report["observations"]
        if item["value_raw"] == "Insoluble"
    )
    assert insoluble["semantic_label"] == "solubility"
    assert insoluble["candidate_class"] == "material_characteristic"
    assert "shadow_inferred_column_shift" in report["warnings"]


def test_multicolumn_sample_axis_combines_group_and_child_labels() -> None:
    report = shadow_extract_table(_table(
        "T_multicolumn_sample",
        "<table><tr><td colspan='2'>Sample</td><td>Tg (°C)</td></tr>"
        "<tr><td rowspan='2'>50/50 Blend</td><td>NBR18/PEO</td><td>-70</td></tr>"
        "<tr><td>/P (EO/PO)</td><td>-69</td></tr></table>",
    ))

    assert [item["sample_label_raw"] for item in report["observations"]] == [
        "50/50 Blend | NBR18/PEO",
        "50/50 Blend | /P (EO/PO)",
    ]


def test_td_thresholds_and_residual_mass_keep_conditions_and_semantics() -> None:
    report = shadow_extract_table(_table(
        "T_thermal_mass",
        "<table><tr><td>Polymer</td><td>$T_d^i$ (°C)</td>"
        "<td>$T_d^{20\\%}$ (°C)</td><td>RM (%)</td></tr>"
        "<tr><td>P-1</td><td>394</td><td>473</td><td>27</td></tr></table>",
    ))

    assert report["observations"][0]["property_variant"] == "initial_decomposition"
    assert report["observations"][1]["property_variant"] == "mass_loss_threshold"
    assert report["observations"][1]["conditions"] == {"mass_loss_percent": 20.0}
    assert report["observations"][2]["semantic_label"] == "residual_mass_fraction"


def test_numeric_composition_axis_binds_property_rows() -> None:
    report = shadow_extract_table(_table(
        "T_composition_axis",
        "<table><tr><td>ABS content (phr)</td><td>Tg (°C)</td></tr>"
        "<tr><td>0</td><td>112</td></tr>"
        "<tr><td>10</td><td>105</td></tr></table>",
    ))

    assert report["direction"] == "row_samples"
    assert report["axis_role"] == "composition"
    assert [item["sample_label_raw"] for item in report["observations"]] == [
        "0",
        "10",
    ]


def test_composition_levels_with_named_control_remain_conditions() -> None:
    report = shadow_extract_table(_table(
        "T_composition_condition",
        "<table><tr><td>SMIA content (phr)</td><td>Tg (°C)</td></tr>"
        "<tr><td>0</td><td>91.2</td></tr>"
        "<tr><td>10</td><td>89.3</td></tr>"
        "<tr><td>SMIA</td><td>132.0</td></tr></table>",
    ))

    assert [item["sample_label_raw"] for item in report["observations"]] == [
        None,
        None,
        "SMIA",
    ]


def test_measurement_subrows_inherit_spanning_sample_group() -> None:
    report = shadow_extract_table(_table(
        "T_grouped_rows",
        "<table><tr><td>Polymer</td><td>Tg (°C)</td></tr>"
        "<tr><td colspan='2'>P-1</td></tr>"
        "<tr><td>Calcd</td><td>101</td></tr>"
        "<tr><td>Found</td><td>103</td></tr></table>",
    ))

    assert [item["sample_label_raw"] for item in report["observations"]] == [
        "P-1",
        "P-1",
    ]
    assert [item["measurement_role"] for item in report["observations"]] == [
        "calculated",
        "experimental",
    ]
    assert "calculated_property_policy_not_resolved" in (
        report["observations"][0]["publication_gate"]["blockers"]
    )


def test_grouped_column_samples_bind_each_subproperty_column() -> None:
    report = shadow_extract_table(_table(
        "T_grouped_columns",
        "<table><tr><td colspan='2'>HS</td><td colspan='2'>HI</td></tr>"
        "<tr><td>Tg (°C)</td><td>Tm (°C)</td><td>Tg (°C)</td><td>Tm (°C)</td></tr>"
        "<tr><td>101</td><td>151</td><td>102</td><td>152</td></tr></table>",
    ))

    assert report["direction"] == "column_samples"
    assert report["axis_role"] == "grouped_sample"
    assert [
        (item["sample_label_raw"], item["property_name_normalized"], item["value_raw"])
        for item in report["observations"]
    ] == [
        ("HS", "glass_transition_temperature", "101"),
        ("HS", "melting_temperature", "151"),
        ("HI", "glass_transition_temperature", "102"),
        ("HI", "melting_temperature", "152"),
    ]


def test_grouped_column_axis_title_is_not_emitted_as_observation() -> None:
    report = shadow_extract_table(_table(
        "T_grouped_dma_axis_title",
        "<table><tr><td rowspan='2'>Sample History</td>"
        "<td colspan='2'>HT</td><td colspan='2'>OT(2)</td></tr>"
        "<tr><td>as-Cast</td><td>Second Run</td>"
        "<td>as-Processed</td><td>Second Run</td></tr>"
        "<tr><td>Tg (°C)</td><td>143</td><td>>220</td>"
        "<td>133</td><td>218</td></tr>"
        "<tr><td>Tan δ</td><td>0.22</td><td>—</td>"
        "<td>1.06</td><td>0.15</td></tr>"
        "<tr><td>E' (GPa) @ 25°C</td><td>0.66</td><td>1.63</td>"
        "<td>0.46</td><td>1.71</td></tr></table>",
    ))

    assert report["direction"] == "column_samples"
    assert report["axis_role"] == "grouped_sample"
    assert len(report["observations"]) == 11
    assert all(
        item["sample_label_raw"] != "Sample History"
        for item in report["observations"]
    )
    assert {
        item["property_name_raw"] for item in report["observations"]
    } == {"Tg (°C)", "Tan δ", "E' (GPa) @ 25°C"}


def test_bare_t1_without_tga_context_is_not_a_decomposition_temperature() -> None:
    report = shadow_extract_table(_table(
        "T_bare_t1",
        "<table><tr><td>Sample</td><td>$T_1$ (°C)</td></tr>"
        "<tr><td>P-1</td><td>212</td></tr></table>",
        caption="Thermal analysis summary",
    ))

    observation = report["observations"][0]
    assert observation["property_name_normalized"] is None
    assert observation["semantic_label"] is None
    assert observation["property_name_raw"] == "$T_1$ (°C)"


def test_electrochromic_state_values_keep_state_and_sample_binding() -> None:
    report = shadow_extract_table(_table(
        "T_electrochromic",
        "<table><tr><td></td><td>L</td><td>a</td><td>b</td></tr>"
        "<tr><td>P-1</td><td>Ox = 47</td><td>Ox = -4</td><td>Ox = 8</td></tr>"
        "<tr><td></td><td>Red = 53</td><td>Red = 1</td><td>Red = 21</td></tr></table>",
        caption="Electrochromic Properties of P-1",
    ))

    assert len(report["observations"]) == 6
    assert {item["sample_label_raw"] for item in report["observations"]} == {"P-1"}
    assert {item["semantic_label"] for item in report["observations"]} == {
        "electrochromic_color_coordinate"
    }
    assert [item["conditions"]["electrochemical_state"] for item in report["observations"]] == [
        "oxidized",
        "reduced",
        "oxidized",
        "reduced",
        "oxidized",
        "reduced",
    ]


def test_average_molar_mass_and_weight_average_length_are_characteristics() -> None:
    report = shadow_extract_table(_table(
        "T_characteristic_aliases",
        "<table><tr><td>Sample</td><td>Av. Molar Mass (g/mol)</td>"
        "<td>Wt. Average Length (μm)</td></tr>"
        "<tr><td>P-1</td><td>6600000</td><td>172</td></tr></table>",
    ))

    assert [item["semantic_label"] for item in report["observations"]] == [
        "molecular_weight",
        "fiber_length",
    ]
    assert report["observations"][1]["property_variant"] == "weight_average"


def test_condition_series_keeps_axis_as_condition_without_fake_sample() -> None:
    report = shadow_extract_table(_table(
        "T_condition_series",
        "<table><tr><td>T (K)</td><td>σ [S/cm]</td><td>τ [s]</td>"
        "<td>1/Tmax,β (K-1)</td></tr>"
        "<tr><td>448</td><td>4.003e-13</td><td>0.00856</td><td>0.0032</td></tr>"
        "<tr><td>453</td><td>7.58e-13</td><td>0.00342</td><td>0.0033</td></tr></table>",
        caption="Havriliak-Negami fit parameters at different temperatures",
    ))

    assert report["direction"] == "condition_series"
    assert report["sample_axis"] == "implicit"
    assert report["axis_role"] == "condition"
    assert [item["conditions"]["temperature_kelvin"] for item in report["observations"]] == [
        448.0,
        453.0,
        448.0,
        453.0,
        448.0,
        453.0,
    ]
    assert all(item["sample_label_raw"] is None for item in report["observations"])
    conductivity = report["observations"][:2]
    assert all(item["binding_status"] == "condition_bound" for item in conductivity)
    assert all(
        item["property_name_normalized"] != "thermal_decomposition_temperature"
        for item in report["observations"]
    )
    assert report["observations"][-1]["semantic_label"] == (
        "dielectric_relaxation_parameter"
    )


def test_xrd_two_theta_header_variants_are_recognized() -> None:
    # _normalized_text 不剥反斜杠，故 '$2\theta$' 到匹配层是 '2\theta'。
    body = (
        "<table><tr><td>Sample</td>"
        r"<td>$2\theta$ (deg)</td>"
        "<td>2theta (deg)</td>"
        "<td>2θ (deg)</td></tr>"
        "<tr><td>PP-1</td><td>14.2</td><td>16.8</td><td>18.5</td></tr></table>"
    )
    report = shadow_extract_table(_table(
        "T_xrd_2t", body, caption="XRD diffraction peaks of the samples"
    ))

    peaks = [
        item for item in report["observations"]
        if item["semantic_label"] == "xray_diffraction_peak"
    ]
    assert [item["value_raw"] for item in peaks] == ["14.2", "16.8", "18.5"]
    assert all(item["property_variant"] == "two_theta" for item in peaks)
    assert all(item["unit_normalized"] == "deg" for item in peaks)


def test_two_theta_is_recognized_without_xrd_caption() -> None:
    report = shadow_extract_table(_table(
        "T_two_theta_no_caption",
        r"<table><tr><td>Sample</td><td>$2\theta$ (deg)</td></tr>"
        r"<tr><td>PP-1</td><td>18.5</td></tr></table>",
    ))

    observation = report["observations"][0]
    assert observation["semantic_label"] == "xray_diffraction_peak"
    assert observation["property_variant"] == "two_theta"
    assert observation["value_raw"] == "18.5"


def test_d_spacing_is_recognized_without_xrd_caption() -> None:
    report = shadow_extract_table(_table(
        "T_d_spacing_no_caption",
        r"<table><tr><td>Sample</td><td>$d (\text{\AA})^{a,b}$</td></tr>"
        r"<tr><td>PP-1</td><td>40.1</td></tr></table>",
    ))

    observation = report["observations"][0]
    assert observation["semantic_label"] == "d_spacing"
    assert observation["value_raw"] == "40.1"


def test_onset_of_decomposition_is_a_thermal_variant() -> None:
    report = shadow_extract_table(_table(
        "T_onset_decomposition",
        "<table><tr><td>Sample</td><td>Onset of decomposition (°C)</td></tr>"
        "<tr><td>P-1</td><td>365</td></tr></table>",
    ))

    observation = report["observations"][0]
    assert observation["property_name_normalized"] == (
        "thermal_decomposition_temperature"
    )
    assert observation["property_variant"] == "onset"


def test_theta_maps_to_contact_angle_only_with_contact_context() -> None:
    contextual = shadow_extract_table(_table(
        "T_contact_angle_context",
        r"<table><tr><td>Sample</td><td>$\theta$ (°)</td></tr>"
        r"<tr><td>P-1</td><td>87</td></tr></table>",
        caption="Water Contact Angles of the samples",
    ))
    generic = shadow_extract_table(_table(
        "T_theta_generic",
        r"<table><tr><td>Sample</td><td>$\theta$ (°)</td></tr>"
        r"<tr><td>P-1</td><td>87</td></tr></table>",
    ))

    assert contextual["observations"][0]["property_name_normalized"] == (
        "contact_angle"
    )
    assert contextual["observations"][0]["unit_raw"] == "°"
    assert contextual["observations"][0]["unit_normalized"] == "deg"
    assert generic["observations"][0]["property_name_normalized"] is None


def test_neighbor_context_is_shared_with_shadow_semantics() -> None:
    report = shadow_extract_table(
        _table(
            "T_contact_angle_neighbor",
            r"<table><tr><td>Sample</td><td>$\theta$ (°)</td></tr>"
            r"<tr><td>P-1</td><td>87</td></tr></table>",
        ),
        context={
            "preceding_text": [{
                "block_id": "P_before",
                "page": 1,
                "text": "Water contact angles were measured for all films.",
            }],
            "following_text": [],
            "footnotes": [],
            "source_block_ids": ["P_before"],
        },
    )

    observation = report["observations"][0]
    assert observation["property_name_normalized"] == "contact_angle"
    assert report["context"]["source_block_ids"] == ["P_before"]


def test_xrd_d_spacing_header_variants_are_recognized() -> None:
    body = (
        "<table><tr><td>Sample</td>"
        "<td>d-Spacing (Å)</td>"
        "<td>d (Å)</td>"
        "<td>d</td>"
        r"<td>$d (\text{\AA})^{a,b}$</td>"
        "<td>I/I0</td></tr>"
        "<tr><td>PP-1</td><td>6.22</td><td>4.15</td><td>3.98</td>"
        "<td>3.54</td><td>100</td></tr></table>"
    )
    report = shadow_extract_table(_table(
        "T_xrd_d", body, caption="WAXD d-spacing and Bragg reflections"
    ))

    spacing = [
        item for item in report["observations"]
        if item["semantic_label"] == "d_spacing"
    ]
    assert [item["value_raw"] for item in spacing] == [
        "6.22", "4.15", "3.98", "3.54",
    ]
    intensity = [
        item for item in report["observations"]
        if item["semantic_label"] == "relative_intensity"
    ]
    assert [item["value_raw"] for item in intensity] == ["100"]


def test_diffraction_patterns_do_not_capture_unrelated_headers() -> None:
    body = (
        "<table><tr><td>Sample</td>"
        "<td>Log d-spacing ratio</td>"
        "<td>Cell Size Dn/Dw</td>"
        "<td>density (g/cm3)</td>"
        "<td>delta (ppm)</td></tr>"
        "<tr><td>PP-1</td><td>0.21</td><td>1.08</td><td>0.92</td>"
        "<td>7.26</td></tr></table>"
    )
    report = shadow_extract_table(_table(
        "T_xrd_neg", body, caption="XRD derived morphology summary"
    ))

    assert all(
        item["semantic_label"] not in {
            "d_spacing", "xray_diffraction_peak", "relative_intensity",
        }
        for item in report["observations"]
    )

def test_spanning_sample_header_keeps_power_subheader_out_of_values():
    report = shadow_extract_table(_table('T_power',
        '<table><tr><td rowspan="2">Polymer code</td><td>Mn</td><td>Mw</td></tr>'
        '<tr><td>10^4</td><td>10^4</td></tr>'
        '<tr><td>PI-1</td><td>3.6</td><td>6.2</td></tr></table>'))
    assert len(report['observations']) == 2
    assert [c['normalized_value'] for c in report['observations']] == [36000, 62000]
    assert report['input_capture_coverage']['expected'] == 2
    assert report['observations'][0]['scale_factor_evidence_cell_ids'] == ['T_power:r0001:c0001']


def test_inverse_ohm_cm_is_whole_unit_and_explicit_display_scale_is_inverted():
    report = shadow_extract_table(_table('T_sigma',
        r'<table><tr><td colspan="2">Before UV exposure</td><td colspan="2">sigma after UV (10^{12} \Omega^{-1} \text{cm}^{-1})</td></tr>'
        r'<tr><td>Conc. by weight</td><td>sigma (10^{12} \Omega^{-1} \text{cm}^{-1})</td><td>2 h</td><td>4 h</td></tr>'
        '<tr><td>PVC</td><td>2.58</td><td>3.65</td><td>4.21</td></tr></table>'))
    assert len(report['observations']) == 3
    for item in report['observations']:
        assert item['unit_normalized'] == 'S/cm'
        assert item['scale_factor_exponent'] == -12
        assert item['scale_factor_status'] == 'explicit_inverse_display_scale'
        assert 'normalized_value' in item
        assert item.get('normalization_status') == 'normalized'
