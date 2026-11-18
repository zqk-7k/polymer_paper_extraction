from stages.property_path_resolver import resolve_property_paths
from stages.table_grid import parse_table_cells


def test_property_path_connects_value_header_condition_and_sample():
    cells = parse_table_cells(
        "<table><tr><th>Sample</th><th>Dose (kGy)</th><th>Tg (°C)</th></tr>"
        "<tr><td>IZO-3</td><td>5</td><td>120</td></tr></table>",
        "T_path",
    )
    paths = resolve_property_paths(cells)
    path = next(item for item in paths if item["target_cell_id"] == "T_path:r0001:c0002")
    assert path["path_status"] == "complete"
    assert path["property_header_path"] == ["Tg (°C)"]
    assert path["sample_axis"]["label_raw"] == "IZO-3"
    assert path["condition_axes"][0]["name"] == "Dose (kGy)"
    assert path["condition_axes"][0]["value_raw"] == "5"
    assert path["unit_raw"] == "°C"
    assert path["evidence_cell_ids"] == [
        "T_path:r0001:c0002", "T_path:r0000:c0002", "T_path:r0001:c0000", "T_path:r0001:c0001",
        "T_path:r0000:c0001",
    ]


def test_property_path_is_candidate_when_sample_axis_is_missing():
    cells = parse_table_cells(
        "<table><tr><th>Value</th></tr><tr><td>120</td></tr></table>",
        "T_path_missing",
    )
    path = resolve_property_paths(cells)[0]
    assert path["path_status"] == "candidate"
    assert path["sample_axis"]["label_raw"] is None


def test_td_header_paths_retain_condition_but_remain_candidate():
    cells = parse_table_cells(
        "<table><tr><td>Sample</td><td>Dose/kGy</td><td>Glass transition temperature (°C)</td></tr>"
        "<tr><td>A</td><td>5</td><td>120</td></tr></table>", "T")
    paths = resolve_property_paths(cells)
    assert len(paths) == 1
    assert paths[0]["path_status"] == "candidate"
    assert paths[0]["property_name_raw"] == "Glass transition temperature (°C)"
    assert paths[0]["condition_axes"][0]["value_raw"] == "5"
    assert paths[0]["condition_axes"][0]["name"] == "Dose/kGy"


def test_shared_dose_rowspan_links_each_value_without_borrowing_another_row():
    cells = parse_table_cells(
        "<table><tr><th>Sample</th><th>Dose/kGy</th><th>Tg</th></tr>"
        "<tr><td>A</td><td rowspan='2'>5</td><td>120</td></tr>"
        "<tr><td>B</td><td>130</td></tr>"
        "<tr><td>C</td><td>10</td><td>140</td></tr></table>", "T")
    paths = resolve_property_paths(cells)
    assert [p["condition_axes"][0]["value_raw"] for p in paths] == ["5", "5", "10"]
    assert paths[1]["condition_axes"][0]["association_basis"] == "shared_rowspan"
    assert paths[1]["condition_axes"][0]["association_status"] == "source_aligned"
    assert paths[2]["condition_axes"][0]["cell_id"] == "T:r0003:c0001"


def test_merged_property_across_different_doses_preserves_both_as_ambiguous():
    cells = parse_table_cells(
        "<table><tr><th>Sample</th><th>Dose/kGy</th><th>Tg</th></tr>"
        "<tr><td rowspan='2'>A</td><td>5</td><td rowspan='2'>120</td></tr>"
        "<tr><td>10</td></tr></table>", "T")
    path = resolve_property_paths(cells)[0]
    assert path["path_status"] == "ambiguous"
    assert [a["value_raw"] for a in path["condition_axes"]] == ["5", "10"]
    assert all(a["association_status"] == "ambiguous" for a in path["condition_axes"])
    assert "T:r0002:c0001" in path["evidence_cell_ids"]


def test_condition_unit_header_and_composition_evidence_are_retained():
    cells = parse_table_cells(
        "<table><tr><th rowspan='2'>Sample</th><th>Frequency</th><th rowspan='2'>Composition (wt%)</th><th rowspan='2'>Tg</th></tr>"
        "<tr><th>kHz</th></tr><tr><td>A</td><td>10</td><td>30/70</td><td>120</td></tr></table>", "T")
    path = resolve_property_paths(cells)[0]
    axis = path["condition_axes"][0]
    assert axis["header_path"] == ["Frequency", "kHz"]
    assert axis["header_cell_ids"] == ["T:r0000:c0001", "T:r0001:c0001"]
    assert path["composition_axes"][0]["value_raw"] == "30/70"
    assert set(axis["header_cell_ids"]).issubset(path["evidence_cell_ids"])
    assert "T:r0000:c0002" in path["evidence_cell_ids"]
