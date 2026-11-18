import json
from pathlib import Path

from tools.polyinfo_coverage_matcher import (
    classify_pred,
    classify_surface_component,
    extract_tga_threshold,
    load_gt,
    load_gt_points,
    load_pred,
    match_doc,
)


def test_viscosity_prediction_variants_use_distinct_buckets() -> None:
    assert classify_pred("inherent viscosity", "") == "viscosity_inherent"
    assert classify_pred("intrinsic viscosity", "") == "viscosity_intrinsic"
    assert classify_pred("[eta]", "") == "viscosity_intrinsic"
    assert classify_pred("η_red", "") == "viscosity_reduced"
    assert classify_pred("specific viscosity", "") == "viscosity_specific"


def test_inherent_viscosity_does_not_match_intrinsic_bucket() -> None:
    assert classify_pred("η_inh", "") == "viscosity_inherent"


def test_unrelated_parameter_name_does_not_match_viscosity() -> None:
    assert classify_pred("Fuoss-Kirkwood Parameters", "") is None


def test_thermal_mass_fraction_complement_conversion_is_logged() -> None:
    gt = [{
        "bucket": "thermal_mass_fraction",
        "quantity_kind": "residual_mass_fraction",
        "value_min": 34.0,
        "value_max": 34.0,
    }]
    pred = [{
        "bucket": "td_wl",
        "quantity_kind": "mass_loss_fraction",
        "values": [66.0],
        "container": "property_series",
        "pred_id": "s1/p1",
        "property_name_raw": "weight loss at 800 C",
        "unit_raw": "%",
        "sample_id": "sample-1",
    }]

    row = match_doc(gt, pred)[0]

    assert row["match_tier"] == "exact"
    assert row["pred_value"] == 34.0
    assert row["match_conversion"] == {
        "operation": "100_minus_x",
        "source_quantity_kind": "mass_loss_fraction",
        "target_quantity_kind": "residual_mass_fraction",
        "source_value": 66.0,
        "converted_value": 34.0,
    }


def test_thermal_mass_fraction_same_basis_does_not_convert() -> None:
    gt = [{
        "bucket": "thermal_mass_fraction",
        "quantity_kind": "mass_loss_fraction",
        "value_min": 75.0,
        "value_max": 75.0,
    }]
    pred = [{
        "bucket": "td_wl",
        "quantity_kind": "mass_loss_fraction",
        "values": [75.0],
        "container": "property_series",
        "pred_id": "s1/p1",
        "property_name_raw": "total wt. loss at 800 C",
        "unit_raw": "%",
        "sample_id": "sample-1",
    }]

    row = match_doc(gt, pred)[0]

    assert row["match_tier"] == "exact"
    assert row["pred_value"] == 75.0
    assert row["match_conversion"] is None


def test_versioned_gt_loader_preserves_missing_numeric_values(tmp_path) -> None:
    path = tmp_path / "curated.jsonl"
    path.write_text(json.dumps({
        "doc_id": "reference_no_test",
        "bucket": "tg",
        "value_min": "",
        "value_max": None,
    }) + "\n", encoding="utf-8")

    row = load_gt_points(path)["reference_no_test"][0]

    assert row["value_min"] is None
    assert row["value_max"] is None


def test_prediction_loader_includes_specialized_and_normalized_values(tmp_path) -> None:
    doc = tmp_path / "reference_no_test"
    doc.mkdir()
    (doc / "final.json").write_text(json.dumps({
        "specialized_property_observations": [{
            "specialized_id": "sp1",
            "semantic_label": "inherent viscosity",
            "value_raw": "0.001",
            "value_min": 0.001,
            "value_max": 0.001,
            "normalized_value": 1.0,
            "unit_raw": "mL/g",
            "unit_normalized": "dL/g",
            "sample_id": "s1",
        }],
    }) + "\n", encoding="utf-8")

    predictions = load_pred(str(tmp_path))

    assert len(predictions["reference_no_test"]) == 1
    prediction = predictions["reference_no_test"][0]
    assert prediction["container"] == "specialized_property_observations"
    assert prediction["bucket"] == "viscosity_inherent"
    assert prediction["unit_raw"] == "dL/g"
    assert prediction["values"] == [1.0]


def test_tga_threshold_from_header_and_condition_are_equivalent() -> None:
    assert extract_tga_threshold(name=r"$T_{d}^{10\%}$ (°C)") == 10.0
    assert extract_tga_threshold(
        measurement_context={"other_conditions": {"mass_loss_percent": "10.0"}}
    ) == 10.0


def test_tga_threshold_mismatch_does_not_match_same_temperature() -> None:
    gt = [{
        "bucket": "td",
        "value_min": 446.0,
        "value_max": 446.0,
        "paired_mass_loss_percent": 10.0,
    }]
    pred = [{
        "bucket": "td",
        "values": [446.0],
        "tga_threshold_percent": 5.0,
        "container": "property_observations",
        "pred_id": "p1",
        "property_name_raw": "TGA-5%",
        "unit_raw": "°C",
        "sample_id": "s1",
    }]

    assert match_doc(gt, pred)[0]["match_tier"] is None


def test_raw_polyinfo_loader_records_tga_pair() -> None:
    root = Path(__file__).resolve().parents[3]
    rows = load_gt(str(root), {"reference_no_0020284"})["reference_no_0020284"]

    td = next(row for row in rows if row["bucket"] == "td" and row["value_min"] == 446)
    paired_wl = next(row for row in rows
                     if row["bucket"] == "td_wl" and row["value_min"] == 10)
    assert td["paired_event_id"] == paired_wl["paired_event_id"]
    assert td["tga_threshold_percent"] == 10.0


def test_explicit_prediction_range_contains_gt_value() -> None:
    gt = [{"bucket": "tensile_modulus", "value_min": 3.5, "value_max": 3.5}]
    pred = [{
        "bucket": "tensile_modulus",
        "values": [2.8, 5.1],
        "interval_kind": "range",
        "interval_min": 2.8,
        "interval_max": 5.1,
        "container": "property_observations",
        "pred_id": "p-range",
        "property_name_raw": "Tensile modulus range",
        "unit_raw": "GPa",
        "sample_id": "s1",
    }]

    row = match_doc(gt, pred)[0]

    assert row["match_tier"] == "range_contains"
    assert row["pred_interval_min"] == 2.8
    assert row["pred_interval_max"] == 5.1


def test_explicit_ranges_can_overlap_gt_range() -> None:
    gt = [{"bucket": "tm", "value_min": 295.0, "value_max": 300.0}]
    pred = [{
        "bucket": "tm",
        "values": [290.0, 297.0],
        "interval_kind": "range",
        "interval_min": 290.0,
        "interval_max": 297.0,
        "container": "property_observations",
        "pred_id": "p-overlap",
        "property_name_raw": "melting temperature range",
        "unit_raw": "C",
        "sample_id": "s1",
    }]

    assert match_doc(gt, pred)[0]["match_tier"] == "range_overlap"


def test_uncertainty_center_is_retained_for_exact_match(tmp_path) -> None:
    doc = tmp_path / "reference_no_test"
    doc.mkdir()
    (doc / "final.json").write_text(json.dumps({
        "property_observations": [{
            "property_id": "p1",
            "property_name_raw": "melting temperature",
            "value_raw": "68.2 ± 0.6",
            "value_min": 67.6,
            "value_max": 68.8,
            "unit_raw": "C",
        }],
    }), encoding="utf-8")

    prediction = load_pred(str(tmp_path))["reference_no_test"][0]

    assert prediction["interval_kind"] == "uncertainty"
    assert prediction["values"] == [68.2, 67.6, 68.8]
    row = match_doc([{"bucket": "tm", "value_min": 68.2, "value_max": 68.2}], [prediction])[0]
    assert row["match_tier"] == "exact"


def test_known_property_aliases_are_mapped_without_cross_bucket_fallback() -> None:
    assert classify_pred(r"$T_{\text{g}}$", "") == "tg"
    assert classify_pred(r"$T_{\text{d}}$ (°C)", "") == "td"
    assert classify_pred(r"$\eta_{\text{inh}}$", "") == "viscosity_inherent"
    assert classify_pred("Water Uptake (%)", "") == "water_abs"
    assert classify_pred("mass_loss_fraction", "%") == "td_wl"
    assert classify_pred("TGA | $T_i$ (°C)", "") == "td"
    assert classify_pred("TGA | $T_d$ (°C)", "") == "td"
    assert classify_pred("transition_temperature_ti", "°C") == "lc_transition"


def test_explicit_glass_rubber_alpha_alias_maps_to_tg_only_with_equivalence() -> None:
    assert classify_pred(
        "glass–rubber process or a-relaxation",
        "K",
    ) == "tg"
    assert classify_pred("alpha-relaxation", "K") is None


def test_surface_energy_components_do_not_match_total_value() -> None:
    assert classify_surface_component(r"γ_s^p") == "polar"
    assert classify_surface_component(r"\gamma_s^d") == "dispersive"
    assert classify_surface_component("surface energy") is None
    # Thermal/viscometric subscripts must not be interpreted as surface-energy
    # components merely because they contain ``_d``/``_g``.
    assert classify_surface_component("T_d") is None
    assert classify_surface_component("T_g") is None
    assert classify_surface_component("TGA") is None
    assert classify_surface_component("Surface and Thermal Properties | η_inh ^d") is None

    total_gt = [{"bucket": "surface_tension", "value_min": 40.0, "value_max": 40.0}]
    polar_pred = [{
        "bucket": "surface_tension",
        "surface_component": "polar",
        "values": [40.0],
        "container": "property_observations",
        "pred_id": "polar-1",
        "property_name_raw": r"γ_s^p",
        "unit_raw": "mN/m",
        "sample_id": "s1",
    }]
    assert match_doc(total_gt, polar_pred)[0]["match_tier"] is None

    polar_gt = [{
        "bucket": "surface_tension",
        "surface_component": "polar",
        "value_min": 40.0,
        "value_max": 40.0,
    }]
    assert match_doc(polar_gt, polar_pred)[0]["match_tier"] == "exact"


def test_standalone_gamma_is_not_surface_tension() -> None:
    assert classify_pred(r"dielectric relaxation $\Delta\varepsilon_{\gamma}$", "") == "dielectric"
    assert classify_pred(r"$\gamma_s^p$", "mN/m") == "surface_tension"


def test_evidence_header_can_map_property_without_name(tmp_path) -> None:
    doc = tmp_path / "reference_no_test"
    doc.mkdir()
    (doc / "final.json").write_text(json.dumps({
        "specialized_property_observations": [{
            "specialized_id": "sp1",
            "semantic_label": None,
            "value_raw": "1.2",
            "value_min": 1.2,
            "value_max": 1.2,
            "unit_normalized": "mJ/m²",
            "evidence": [{"table_locator": {
                "column_label": r"${\gamma}_{s}^{p}$ (mJ/m2)",
            }}],
        }],
    }), encoding="utf-8")

    prediction = load_pred(str(tmp_path))["reference_no_test"][0]

    assert prediction["bucket"] == "surface_tension"
    assert prediction["surface_component"] == "polar"
    assert prediction["evidence_header_labels"]
