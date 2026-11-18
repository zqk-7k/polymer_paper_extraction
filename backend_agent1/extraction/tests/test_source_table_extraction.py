from copy import deepcopy

from stages.source_table_extraction import build_source_extraction


def source(body, caption=""):
    return {"document_id": "reference_no_test", "elements": [{"block_id": "T1", "type": "table", "page": 0,
            "source_block_index": 0, "table_body": body, "caption": caption}]}


def test_unmapped_property_without_unit_or_stage3_is_usable_and_unchanged():
    data = source('<table><tr><td>Sample</td><td>Novel property</td></tr><tr><td>A</td><td>12 ± 2</td></tr></table>')
    before = deepcopy(data)
    result = build_source_extraction(data)
    row = result["observations"][0]
    assert row["extraction_status"] == "usable"
    assert row["value_raw"] == "12 ± 2" and row["value_normalized"] is None
    assert row["article_sample_label_raw"] == "A" and row["sample_id"] is None
    assert row["unit_raw"] is None and row["standard_property_code"] is None
    assert not row["historical_request_verified"]
    assert before == data


def test_nested_td_headers_and_qualitative_minus_keep_source_meaning():
    data = source('<table><tr><td rowspan="2">Polymer</td><td colspan="2">Solubility</td></tr><tr><td>DMF</td><td>THF</td></tr><tr><td>A</td><td>+</td><td>-</td></tr></table>')
    rows = build_source_extraction(data)["observations"]
    assert [r["value_raw"] for r in rows] == ["+", "-"]
    assert rows[1]["property_header_path"] == ["Solubility", "THF"]
    assert all(r["extraction_status"] == "usable" for r in rows)


def test_transposed_table_uses_row_property_and_column_sample():
    data = source('<table><tr><td>Properties</td><td>A</td><td>B</td></tr><tr><td>Tensile strength (MPa)</td><td>12</td><td>20</td></tr></table>')
    rows = build_source_extraction(data)["observations"]
    assert [r["article_sample_label_raw"] for r in rows] == ["A", "B"]
    assert rows[0]["property_name_raw"] == "Tensile strength (MPa)"


def test_different_doses_and_bad_claim_do_not_merge_or_replace_source():
    data = source('<table><tr><td>Sample</td><td>Dose/kGy</td><td>Tg (°C)</td></tr><tr><td>A</td><td>8.1</td><td>125</td></tr><tr><td>A</td><td>8.5</td><td>126</td></tr></table>')
    bad = {"measurement_id": "bad", "identity": {"source_cell_ids": ["T1:r0001:c0002"], "value_raw": "999"}, "record": {"sample_id": "wrong"}}
    pub = {"document_id": data["document_id"], "not_publishable": [bad]}
    result = build_source_extraction(data, pub)
    rows = [r for r in result["observations"] if r["record_kind"] == "property"]
    assert [r["value_raw"] for r in rows] == ["125", "126"]
    assert rows[0]["article_sample_key"] != rows[1]["article_sample_key"]
    assert all(r["sample_id"] is None for r in rows)
    assert result["claims"][0]["value_check"] == "interpretation_retained_separately"


def test_missing_value_is_not_zero_and_duplicate_claims_have_one_source_record():
    data = source('<table><tr><td>Sample</td><td>Tg</td><td>Tm</td></tr><tr><td>A</td><td>120</td><td>—</td></tr></table>')
    group = {"measurement_id": "a", "identity": {"source_cell_ids": ["T1:r0001:c0001"], "value_raw": "120"}}
    pub = {"document_id": data["document_id"], "candidate": [group, {**group, "measurement_id": "b"}]}
    result = build_source_extraction(data, pub)
    assert len(result["observations"]) == 1
    assert result["observations"][0]["claim_ids"] == ["a", "b"]
    assert result["counts"]["claim_count"] == 2


def test_mixed_viscosity_solubility_caption_does_not_relabel_numeric_property():
    data = source('<table><tr><td>Sample</td><td>Viscosity (dL/g)</td><td>DMF</td></tr><tr><td>A</td><td>0.50</td><td>-</td></tr></table>', 'Viscosity and solubility')
    rows = build_source_extraction(data)["observations"]
    assert rows[0]["record_kind"] == "property"
    assert rows[0]["property_name_raw"] == "Viscosity (dL/g)"
    assert rows[1]["record_kind"] == "qualitative_property"


def test_solvent_rows_with_sample_columns_keep_both_axes():
    data = source('<table><tr><td rowspan="2">Solvent</td><td colspan="2">PEI</td></tr><tr><td>3a</td><td>3b</td></tr><tr><td>DMF</td><td>+</td><td>-</td></tr></table>', 'Solubility of PEI')
    rows = build_source_extraction(data)["observations"]
    assert [r["article_sample_label_raw"] for r in rows] == ["PEI | 3a", "PEI | 3b"]
    assert rows[0]["property_header_path"] == ["DMF"]
    assert len(rows) == 2


def test_nested_state_is_context_and_missing_marker_footnote_is_preserved_only_in_inventory():
    data = source('<table><tr><td rowspan="2">Sample</td><td colspan="3">Polymer</td></tr><tr><td>State</td><td>Tg</td><td>Tm</td></tr><tr><td>A</td><td>Ox</td><td>120</td><td>—a</td></tr></table>')
    result = build_source_extraction(data)
    rows = result['observations']
    assert [r['record_kind'] for r in rows] == ['context', 'property']
    assert rows[1]['condition_context_raw'][0]['value_raw'] == 'Ox'
    assert any(c['text'] == '—a' for c in result['tables'][0]['cells'])


def test_shared_sample_axis_does_not_merge_implicit_different_row_states():
    data = source('<table><tr><td>Sample</td><td>Color</td></tr><tr><td rowspan="2">A</td><td>Ox = 47</td></tr><tr><td>Red = 53</td></tr></table>')
    rows = build_source_extraction(data)['observations']
    assert rows[0]['sample_axis_cell_ids'] == rows[1]['sample_axis_cell_ids']
    assert rows[0]['article_sample_key'] != rows[1]['article_sample_key']
