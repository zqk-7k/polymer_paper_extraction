from __future__ import annotations

import json
from pathlib import Path

from schema.polymer_schema import Stage0Element
from stages.stage4t_table_property import shadow_extract_table
from stages.table_grid import parse_table_cells


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "stage4t_reference_no_0043541_t4_49_v0.1.json"
)


def _fixture() -> dict:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "stage4t_real_contact_angle_fixture.v0.1"
    return payload


def _table(body: str | None = None) -> Stage0Element:
    fixture = _fixture()
    table_body = body or fixture["table_body"]
    return Stage0Element(
        block_id=fixture["source_table_id"],
        type="table",
        page=4,
        source_block_index=49,
        caption=fixture["caption"],
        table_body=table_body,
        table_cells=parse_table_cells(table_body, fixture["source_table_id"]),
    )


def test_real_t4_49_recovers_column_samples_after_two_descriptor_columns() -> None:
    fixture = _fixture()
    report = shadow_extract_table(_table())

    assert (report["direction"], report["sample_axis"], report["axis_role"]) == (
        "column_samples",
        "column",
        "named_sample",
    )
    observations = report["observations"]
    assert len(observations) == fixture["expected_observation_count"]
    assert set(item["sample_label_raw"] for item in observations) == set(
        fixture["expected_sample_labels"]
    )
    assert all(
        item["property_name_normalized"] == "contact_angle"
        and item["unit_normalized"] == "deg"
        and item["unit_inference_basis"] == "explicit_angle_symbol_in_value"
        and item["binding_status"] == "bound"
        for item in observations
    )
    assert not any(item["value_raw"] in {"73", "50", "60"} for item in observations)
    for expected in fixture["frozen1542_recovered_values"]:
        assert any(str(expected) in item["value_raw"] for item in observations)


def test_two_blank_corner_rule_rejects_a_property_header_among_samples() -> None:
    fixture = _fixture()
    body = fixture["table_body"].replace(
        "<td>poly(METAI)</td>",
        "<td>Tg (°C)</td>",
        1,
    )
    report = shadow_extract_table(_table(body))

    assert report["direction"] != "column_samples"
    assert not any(
        item.get("sample_label_raw") == "Tg (°C)"
        and item.get("property_name_normalized") == "contact_angle"
        for item in report["observations"]
    )


def test_two_blank_corner_rule_requires_at_least_two_named_samples() -> None:
    body = (
        "<table><tr><td></td><td></td><td>poly(MPC)</td></tr>"
        "<tr><td>Water</td><td>(static)</td><td>$45^{\\circ}$</td></tr>"
        "</table>"
    )
    report = shadow_extract_table(_table(body))

    assert report["direction"] != "column_samples"

