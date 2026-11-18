from stages.table_grid import parse_table_cells
from stages.table_value_inventory import build_inventory, capture_coverage


def test_inventory_retains_every_source_cell_and_coverage_requires_original_value():
    cells = parse_table_cells("<table><tr><td>Sample</td><td>Unknown</td></tr>"
        "<tr><td>A</td><td>227–393 (peaks)</td></tr>"
        "<tr><td>B</td><td>0.0550</td></tr></table>", "T")
    inventory = build_inventory("T", cells, {0})
    assert len(inventory) == 6
    assert [r["value_raw"] for r in inventory] == [c.text for c in cells]
    assert capture_coverage(inventory, [])["expected"] == 2
    assert capture_coverage(inventory, [])["ratio"] == 0
    one = {"cell_id": "T:r0001:c0001", "value_raw": "227–393 (peaks)"}
    wrong = {"cell_id": "T:r0002:c0001", "value_raw": "0.05"}
    coverage = capture_coverage(inventory, [one, one, wrong])
    assert coverage["captured"] == 1
    assert coverage["missing_cell_ids"] == ["T:r0002:c0001"]
    assert coverage["pending_interpretation"] == 2
    assert coverage["metric_scope"] == "candidate_capture_not_property_recall"


def test_empty_inventory_has_no_false_perfect_coverage():
    coverage = capture_coverage([], [])
    assert coverage["ratio"] is None
    assert coverage["status"] == "empty_or_unclassified"


def test_inventory_exposes_roles_and_property_path_without_changing_capture_gate():
    cells = parse_table_cells(
        "<table><tr><th>Sample</th><th>Dose (kGy)</th><th>Tg (°C)</th></tr>"
        "<tr><td>IZO-3</td><td>5</td><td>120</td></tr></table>",
        "T_roles",
    )
    inventory = build_inventory("T_roles", cells, {0})
    value = next(row for row in inventory if row["cell_id"] == "T_roles:r0001:c0002")
    assert value["cell_role"] == "property_value"
    assert value["property_path"]["path_status"] == "complete"
    assert value["property_path"]["sample_axis"]["label_raw"] == "IZO-3"
    assert value["property_path"]["condition_axes"][0]["value_raw"] == "5"
    assert value["eligible_for_capture"] is True



def test_composite_candidates_preserve_offsets_and_never_guess_concatenations():
    from stages.table_value_inventory import composite_candidates
    text="71.63(71.90)"
    result=composite_candidates(text)
    assert result["status"]=="explicit_parenthetical_pair"
    assert [c["value_raw"] for c in result["candidates"]]==["71.63","71.90"]
    assert all(text[c["source_start"]:c["source_end"]]==c["value_raw"] for c in result["candidates"])
    assert composite_candidates("5.906.03")=={"status":"ambiguous_concatenated_numbers","candidates":[]}
    assert composite_candidates("$C_{19}H_{19}N_5$")["candidates"]==[]
