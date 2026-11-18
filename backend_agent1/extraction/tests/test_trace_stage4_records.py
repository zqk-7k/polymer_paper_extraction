from copy import deepcopy

from tools.trace_stage4_records import trace_records


def fixture():
    source = {"document_id": "test", "elements": [{"block_id": "T1", "type": "table", "page": 0, "source_block_index": 0,
               "table_body": "<table><tr><th>Sample</th><th>Tg</th></tr><tr><td>A</td><td>120</td></tr><tr><td>B</td><td>120</td></tr></table>"}]}
    item = {"property_id": "prop001", "property_name_raw": "$T_{g}$", "sample_id": "s001", "value_raw": "120", "unit_raw": "K",
            "evidence": [{"block_id": "T1", "table_locator": {"row_label": "A", "column_label": "Tg", "cell_value": "120"}}]}
    return source, {"properties": [item]}


def test_equal_values_in_different_rows_do_not_imply_retention():
    source, raw = fixture()
    output = deepcopy(raw)
    output["properties"][0]["evidence"][0]["table_locator"]["row_label"] = "B"
    result = trace_records(raw, output, source)
    assert result["records"][0]["status"] == "destination_not_found_requires_review"


def test_scalar_represented_as_series_point_is_not_reported_lost():
    source, raw = fixture()
    point = deepcopy(raw["properties"][0])
    output = {"property_series": [{"property_name_raw": "Tg", "points": [point]}]}
    result = trace_records(raw, output, source)
    assert result["records"][0]["status"] == "represented_as_series_point"
    assert result["output_record_count"] == 1


def test_identity_changes_are_visible_and_ambiguous_destinations_stay_pending():
    source, raw = fixture()
    output = deepcopy(raw)
    output["properties"][0]["sample_id"] = "s002"
    result = trace_records(raw, output, source)
    assert result["records"][0]["status"] == "same_source_value_fields_changed"
    assert result["records"][0]["changed_fields"][0]["field"] == "sample_id"
    output["properties"].append(deepcopy(output["properties"][0]))
    assert trace_records(raw, output, source)["records"][0]["status"] == "multiple_destinations_requires_review"


def test_quarantine_reason_is_visible_in_record_lineage():
    source, raw = fixture()
    output = {"properties": [], "warnings": [{"code": "preview_objects_quarantined", "objects": [
        {"collection": "properties", "object_id": "prop001", "reason": "aggregate_series_reference_incompatible"}]}]}
    row = trace_records(raw, output, source)["records"][0]
    assert row["status"] == "quarantined_requires_review"
    assert row["quarantine_reasons"] == ["aggregate_series_reference_incompatible"]
