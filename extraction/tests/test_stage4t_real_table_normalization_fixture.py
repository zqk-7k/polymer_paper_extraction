from __future__ import annotations

import json
from pathlib import Path

import pytest

from schema.polymer_schema import Stage0Element
from stages.property_publication_policy import decide_quantity
from stages.stage4t_table_property import shadow_extract_table
from stages.table_grid import parse_table_cells


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "stage4t_real_table_normalization_v0.1.json"
)


def _cases() -> dict[str, dict]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == (
        "stage4t_real_table_normalization_fixture.v0.1"
    )
    return {item["case_id"]: item for item in payload["cases"]}


def _table(case: dict) -> Stage0Element:
    table_id = case["table_id"]
    body = case["table_body"]
    return Stage0Element(
        block_id=table_id,
        type="table",
        page=1,
        source_block_index=0,
        caption=case.get("caption"),
        table_body=body,
        table_cells=parse_table_cells(body, table_id),
    )


def test_conductivity_display_multiplier_is_explicit_and_inverse_scaled() -> None:
    case = _cases()["conductivity_display_multiplier"]
    report = shadow_extract_table(_table(case))

    assert report["header_rows"] == case["expected_header_rows"]
    observations = [
        item
        for item in report["observations"]
        if item["property_name_normalized"] == "electric_conductivity"
    ]
    assert [item["value_raw"] for item in observations] == case["expected_values"]
    assert all(item["unit_normalized"] == "S/cm" for item in observations)
    assert all(item["display_multiplier_exponent"] == 12 for item in observations)
    assert all(item["value_scale_factor"] == pytest.approx(1e-12) for item in observations)
    assert observations[0]["conditions"] == {"uv_exposure_state": "before"}
    assert observations[1]["conditions"] == {"uv_exposure_hours": 2.0}
    assert observations[2]["conditions"] == {"uv_exposure_hours": 6.0}
    assert "10^{12}" in observations[0]["property_name_raw"]
    assert observations[0]["value_raw"] == "2.58"

    decision = decide_quantity(
        observations[0],
        cell_text="2.58",
        header=observations[0]["property_name_raw"],
    )
    assert decision.accepted is True
    assert decision.reason == "accepted_direct_scaled_scalar"
    assert decision.value_min == pytest.approx(2.58e-12)
    assert decision.unit_normalized == "S/cm"


def test_display_multiplier_cannot_escape_the_conductivity_unit_contract() -> None:
    case = _cases()["conductivity_display_multiplier"]
    observation = next(
        item
        for item in shadow_extract_table(_table(case))["observations"]
        if item["property_name_normalized"] == "electric_conductivity"
    )
    invalid = dict(observation)
    invalid["property_name_raw"] = "Electrical conductivity (10^12 S/cm)"
    invalid["unit_raw"] = "S/cm"

    decision = decide_quantity(
        invalid,
        cell_text="2.58",
        header=invalid["property_name_raw"],
    )

    assert decision.accepted is False
    assert decision.reason == "display_scale_reciprocal_unit_missing"


def test_parenthetical_degrees_is_contact_angle_unit_only() -> None:
    contact_case = _cases()["contact_angle_degrees"]
    contact = shadow_extract_table(_table(contact_case))["observations"][0]

    assert contact["property_name_normalized"] == "contact_angle"
    assert contact["unit_raw"] == "Degrees"
    assert contact["unit_normalized"] == contact_case["expected_unit"]

    crystallinity_case = _cases()["crystallinity_temperature_condition"]
    crystallinity = shadow_extract_table(_table(crystallinity_case))["observations"][0]
    assert crystallinity["unit_normalized"] is None
    assert crystallinity["unit_raw"] is None


def test_crystallinity_temperature_is_condition_not_response_unit() -> None:
    case = _cases()["crystallinity_temperature_condition"]
    item = shadow_extract_table(_table(case))["observations"][0]

    assert item["property_name_normalized"] is None
    assert item["semantic_label"] == case["expected_semantic_label"]
    assert item["conditions"] == {
        "temperature_celsius": case["expected_temperature_celsius"]
    }
    assert item["condition_binding_validated"] is True
    assert item["publication_gate"]["checks"]["conditions_validated"] is True
    assert item["unit_normalized"] is None
    assert item["unit_raw"] is None
