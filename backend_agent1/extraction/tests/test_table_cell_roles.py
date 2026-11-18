from stages.table_grid import parse_table_cells
from stages.table_cell_roles import classify_table_cells
import pytest


def _roles(body: str):
    cells = parse_table_cells(body, "T_roles")
    return {item["cell_id"]: item for item in classify_table_cells(cells)}


def test_roles_separate_sample_property_and_unit_cells():
    roles = _roles(
        "<table><tr><th>Sample</th><th>Tg (°C)</th><th>Modulus (MPa)</th></tr>"
        "<tr><td>IZO-3</td><td>120</td><td>4.2</td></tr></table>"
    )
    assert roles["T_roles:r0001:c0000"]["cell_role"] == "sample_label"
    assert roles["T_roles:r0001:c0001"]["cell_role"] == "property_value"
    assert roles["T_roles:r0000:c0001"]["cell_role"] == "property_header"


def test_roles_keep_conditions_compositions_and_scales_distinct():
    roles = _roles(
        "<table><tr><th>Dose (kGy)</th><th>Composition (wt%)</th><th>Value ×10^3</th></tr>"
        "<tr><td>5 kGy</td><td>30/70</td><td>1.2</td></tr></table>"
    )
    assert roles["T_roles:r0001:c0000"]["cell_role"] == "condition"
    assert roles["T_roles:r0001:c0001"]["cell_role"] == "composition"
    assert roles["T_roles:r0000:c0002"]["cell_role"] == "scale_header"


@pytest.mark.parametrize("header", ["Glass transition temperature (°C)", "Relaxation time (s)",
    "Conductivity after UV exposure", "Critical pressure (MPa)", "Poisson ratio",
    "Evaporation rate", "Polymer yield (%)", "Crystallinity (wt%)"])
def test_property_names_containing_axis_words_are_not_conditions(header):
    roles = _roles(f"<table><tr><th>Sample</th><th>{header}</th></tr>"
                   "<tr><td>A</td><td>120</td></tr></table>")
    assert roles["T_roles:r0000:c0001"]["cell_role"] == "property_header"
    assert roles["T_roles:r0001:c0001"]["cell_role"] == "property_value"


def test_numeric_sample_id_and_scientific_value_are_not_measurement_and_scale_header():
    roles = _roles("<table><tr><th>Sample</th><th>Value</th></tr>"
                   "<tr><td>12</td><td>2 × 10 3</td></tr></table>")
    assert roles["T_roles:r0001:c0000"]["cell_role"] == "sample_label"
    assert roles["T_roles:r0001:c0001"]["cell_role"] == "property_value"


def test_nearest_semantic_header_prevents_condition_group_from_masking_properties():
    roles = _roles("<table><tr><th rowspan='2'>Sample</th><th colspan='2'>Temperature</th></tr>"
                   "<tr><th>Tg</th><th>Tm</th></tr><tr><td>A</td><td>120</td><td>160</td></tr></table>")
    assert roles["T_roles:r0002:c0001"]["cell_role"] == "property_value"
    assert roles["T_roles:r0002:c0002"]["cell_role"] == "property_value"


def test_td_header_inference_is_explicit_and_does_not_mutate_source():
    cells = parse_table_cells("<table><tr><td>Dose/kGy</td><td>Viscosity</td><td>State</td></tr>"
                              "<tr><td>0.533</td><td>248</td><td>L</td></tr></table>", "T")
    roles = {r["cell_id"]: r for r in classify_table_cells(cells)}
    dose = roles["T:r0001:c0000"]
    assert dose["cell_role"] == "condition"
    assert dose["role_confidence"] == "candidate"
    assert any(e["rule"] == "simple_first_row_header_inferred" for e in dose["role_evidence"])
    assert roles["T:r0001:c0001"]["cell_role"] == "property_value"
    assert all(not c.is_header for c in cells)


def test_numeric_first_row_is_not_inferred_to_be_a_header():
    roles = _roles("<table><tr><td>Sample</td><td>120</td></tr>"
                   "<tr><td>A</td><td>100</td></tr></table>")
    assert not roles["T_roles:r0000:c0001"]["is_effective_header"]
