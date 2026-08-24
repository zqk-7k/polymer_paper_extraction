from __future__ import annotations

from schema.polymer_schema import Stage0Element
from stages.stage4t_table_property import shadow_extract_table
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


def test_wide_candidate_layer_keeps_unmapped_but_excludes_yield() -> None:
    report = shadow_extract_table(_table(
        "T_wide_candidates",
        "<table><tr><td>Sample</td><td>custom score q</td><td>Yield (%)</td></tr>"
        "<tr><td>AP-PCL</td><td>-0.15</td><td>87</td></tr></table>",
    ))

    assert len(report["observations"]) == 1
    candidate = report["observations"][0]
    assert candidate["property_name_raw"] == "custom score q"
    assert candidate["semantic_status"] == "unmapped"
    assert candidate["candidate_class"] == "unknown_observation"
    assert candidate["authority_target"] is None
    assert candidate["publication_gate"]["blockers"] == [
        "semantic_unmapped",
        "sample_not_resolved",
    ]


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
    assert report["observations"] == []
    assert report["unresolved"] == []
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
