from __future__ import annotations

import pytest

from schema.polymer_schema import Stage0Element
from stages.stage4t_table_property import shadow_extract_table
from stages.table_grid import parse_table_cells


# Verbatim table structure and values from reference_no_0021738 / T_3_51.
REAL_T_3_51_BODY = (
    "<table><tr><td>Polymer $PU_i$ where i=</td><td>$T_0^a$ (\u00b0C)</td>"
    "<td>MaxDTGa(\u00b0C)</td><td>Endob(\u00b0C)</td><td>Exob(\u00b0C)</td>"
    "<td>$T_g^c$ (\u00b0C)</td><td>$T_m^c$ (\u00b0C)</td></tr>"
    "<tr><td>1</td><td>330</td><td>370</td><td></td><td></td><td>*</td><td></td></tr>"
    "<tr><td>2</td><td>290</td><td>310</td><td>220</td><td></td><td>217</td><td></td></tr>"
    "<tr><td>3</td><td>300</td><td>330</td><td></td><td>110</td><td>235</td><td></td></tr>"
    "<tr><td>4</td><td>280</td><td>320</td><td>195</td><td></td><td>198</td><td></td></tr>"
    "<tr><td>5</td><td>270</td><td>360</td><td></td><td></td><td>*</td><td></td></tr>"
    "<tr><td>6</td><td>300</td><td>330</td><td></td><td>120</td><td>*</td><td></td></tr>"
    "<tr><td>7</td><td>280</td><td>320</td><td></td><td></td><td>*</td><td></td></tr>"
    "<tr><td>8</td><td>290</td><td>310</td><td></td><td></td><td>217</td><td></td></tr>"
    "<tr><td>9</td><td>290</td><td>300</td><td></td><td></td><td>*</td><td></td></tr>"
    "<tr><td>10</td><td>315</td><td>325</td><td></td><td></td><td>*</td><td></td></tr>"
    "<tr><td>11</td><td>300</td><td>330</td><td></td><td></td><td>200</td><td>245</td></tr>"
    "<tr><td>12</td><td>290</td><td>300/360</td><td></td><td></td><td>232</td><td></td></tr>"
    "<tr><td>13</td><td>300</td><td>315</td><td></td><td></td><td>*</td><td></td></tr>"
    "<tr><td>14</td><td>270</td><td>300</td><td></td><td></td><td>227</td><td></td></tr>"
    "<tr><td>15</td><td>290</td><td>325</td><td></td><td></td><td>*</td><td></td></tr>"
    "<tr><td>16</td><td>310</td><td>350</td><td></td><td></td><td>*</td><td></td></tr>"
    "<tr><td>17</td><td>300</td><td>310/355</td><td>170</td><td></td><td>150</td><td>180</td></tr>"
    "<tr><td>18</td><td>270</td><td>280/360</td><td></td><td>110</td><td>*</td><td></td></tr>"
    "<tr><td>19</td><td>290</td><td>320</td><td></td><td></td><td>*</td><td></td></tr>"
    "<tr><td>20</td><td>280</td><td>310</td><td></td><td></td><td>*</td><td></td></tr></table>"
)


def _table(body: str = REAL_T_3_51_BODY) -> Stage0Element:
    return Stage0Element(
        block_id="T_3_51",
        type="table",
        page=3,
        source_block_index=51,
        caption="Table 2. Thermal behaviour of the polyureas",
        table_body=body,
        table_cells=parse_table_cells(body, "T_3_51"),
    )


def _strong_applied(report: dict) -> bool:
    return "strong_pu_thermal_fingerprint_applied" in report["warnings"]


def test_real_t_3_51_expands_t0_and_ordered_max_dtg_points() -> None:
    report = shadow_extract_table(_table())

    assert _strong_applied(report)
    assert (report["direction"], report["sample_axis"], report["axis_role"]) == (
        "row_samples", "row", "generated_sample_family"
    )
    t0 = [item for item in report["observations"] if item["property_variant"] == "mass_loss_threshold"]
    max_dtg = [
        item for item in report["observations"]
        if item["property_variant"] == "maximum_decomposition_rate"
    ]
    assert len(t0) == 20
    assert len(max_dtg) == 23
    assert len(report["observations"]) == 43
    assert all(item["conditions"] == {"mass_loss_percent": 5.0} for item in t0)
    assert all(item["value_raw"] != "5" for item in report["observations"])
    assert all(item["unit_normalized"] == "\u00b0C" for item in report["observations"])
    assert all(item["value_kind"] == "numeric_scalar" for item in report["observations"])
    assert all(
        item["property_name_normalized"] is None
        and item["semantic_label"] == "max_dtg"
        and item["unit_normalized"] == "\u00b0C"
        for item in max_dtg
    )

    pu12 = [item for item in max_dtg if item["sample_label_raw"] == "PU12"]
    assert [item["value_raw"] for item in pu12] == ["300", "360"]
    assert [item["value_index"] for item in pu12] == [0, 1]
    assert {item["cell_id"] for item in pu12} == {"T_3_51:r0012:c0002"}
    assert [item["observation_id"] for item in pu12] == [
        "T_3_51:T_3_51:r0012:c0002:v01",
        "T_3_51:T_3_51:r0012:c0002:v02",
    ]
    assert [item["evidence_locator"]["value_index"] for item in pu12] == [0, 1]
    assert all(
        item["publication_gate"]["status"] == "candidate_only"
        and "sample_not_resolved" in item["publication_gate"]["blockers"]
        for item in report["observations"]
    )


@pytest.mark.parametrize("marker", ["", "-", "—", "–", "−"])
def test_explicit_missing_target_cell_is_skipped_without_disabling_table(marker: str) -> None:
    body = REAL_T_3_51_BODY.replace("<td>330</td>", f"<td>{marker}</td>", 1)
    report = shadow_extract_table(_table(body))

    assert _strong_applied(report)
    assert len(report["observations"]) == 42
    assert not any(
        item["sample_label_raw"] == "PU1"
        and item["property_variant"] == "mass_loss_threshold"
        for item in report["observations"]
    )


@pytest.mark.parametrize(
    "body",
    [
        REAL_T_3_51_BODY.replace("Polymer $PU_i$ where i=", "Polymer", 1),
        REAL_T_3_51_BODY.replace("<td>2</td>", "<td>4</td>", 1),
        REAL_T_3_51_BODY.replace("$T_0^a$ (\u00b0C)", "$T_0^a$", 1),
        REAL_T_3_51_BODY.replace("<td>330</td>", "<td>about 330</td>", 1),
    ],
)
def test_pu_thermal_rule_fails_closed_on_fingerprint_or_shape_violation(body: str) -> None:
    assert not _strong_applied(shadow_extract_table(_table(body)))


def test_pu_thermal_rule_fails_closed_on_unstable_target_locator() -> None:
    table = _table()
    cells = list(table.table_cells or [])
    cells[8] = cells[8].model_copy(update={"cell_id": "unstable"})
    table = table.model_copy(update={"table_cells": cells})

    assert not _strong_applied(shadow_extract_table(table))
