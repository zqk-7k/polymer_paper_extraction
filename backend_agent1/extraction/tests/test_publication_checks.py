from copy import deepcopy

import pytest

from stages.measurement_record import publication_audit_for_final


def source_fixture(header="Tg (°C)"):
    stage0 = {"document_id": "test", "elements": [{
        "block_id": "T1", "type": "table", "page": 0, "source_block_index": 0,
        "table_body": f"<table><tr><th>Sample</th><th>{header}</th></tr><tr><td>A</td><td>120</td></tr><tr><td>B</td><td>100</td></tr></table>",
    }]}
    stage3 = {"document_id": "test", "samples": [
        {"sample_id": "s001", "sample_label_raw": "A", "sample_kind": "synthesis_batch", "refers_to_entity": "pe001"},
        {"sample_id": "s002", "sample_label_raw": "B", "sample_kind": "synthesis_batch", "refers_to_entity": "pe001"},
    ], "process_steps": []}
    payload = {"document_id": "test", "polymer_entities": [{"entity_id": "pe001"}], "evidence": [{
        "evidence_id": "e1", "block_id": "T1", "page": 0, "source_type": "table",
        "source_sentence": "A 120", "table_locator": {"cell_id": "T1:r0001:c0001", "row_index": 1, "column_index": 1},
    }], "property_observations": [{
        "property_id": "prop001", "property_name_raw": "Tg", "property_code": "P3110",
        "sample_id": "s001", "entity_id": "pe001", "value_raw": "120", "unit_raw": "°C", "evidence_ids": ["e1"],
    }]}
    inputs = {"stage0": stage0, "stage3": stage3, "stage4": {"provenance": {"status": "success"}}, "stage5": {"provenance": {"status": "success"}}}
    return payload, inputs


def test_complete_source_path_can_pass_without_mutating_input():
    payload, inputs = source_fixture()
    before = deepcopy((payload, inputs))
    row = publication_audit_for_final(payload, **inputs)["records"][0]
    assert row["publication_status"] == "final", row
    assert row["source_cell_ids"] == ["T1:r0001:c0001"]
    assert row["scale_status"] == "not_present_on_source_path"
    assert (payload, inputs) == before


def test_delta_n_requires_explicit_same_table_real_index_caption():
    payload, inputs = source_fixture("Δn")
    item = payload["property_observations"][0]
    item.update(property_name_raw="Δn", unit_raw=None)
    # A bare symbol does not define a property or its unit.
    assert publication_audit_for_final(payload, **inputs)["records"][0]["publication_status"] != "final"
    table = inputs["stage0"]["elements"][0]
    table["caption"] = "Changes of the real part of the refractive index of polymers during illumination"
    row = publication_audit_for_final(payload, **inputs)["records"][0]
    assert row["publication_status"] == "final", row
    assert row["standard_property_code"] == "STD:real_refractive_index_change"
    assert row["unit_normalized"] == "1"
    assert item["unit_raw"] is None
    assert row["standard_mapping_basis"]["header_cell_id"] == "T1:r0000:c0001"
    for caption in ("Changes in carrier concentration", "Changes of the imaginary part of the refractive index", "Changes of the real part of the refractive index (%)"):
        table["caption"] = caption
        assert publication_audit_for_final(payload, **inputs)["records"][0]["publication_status"] != "final"


def test_delta_n_source_rule_does_not_erase_unit_or_scale_conflicts():
    payload, inputs = source_fixture("Δn")
    item = payload["property_observations"][0]
    item.update(property_name_raw="Δn", unit_raw="MPa")
    inputs["stage0"]["elements"][0]["caption"] = "Changes of the real part of the refractive index"
    row = publication_audit_for_final(payload, **inputs)["records"][0]
    assert row["publication_status"] != "final"
    assert "unit_family_conflict" in row["publication_reasons"]
    item.update(unit_raw=None, display_scale_raw="10^-3")
    row = publication_audit_for_final(payload, **inputs)["records"][0]
    assert "display_scale_unverified" in row["publication_reasons"]


@pytest.mark.parametrize("patch,reason", [
    ({"evidence_ids": ["invented"]}, "evidence_reference_unknown"),
    ({"value_raw": "999"}, "value_not_in_target_cell"),
    ({"sample_id": "s002"}, "sample_axis_conflict"),
    ({"entity_id": "pe999"}, "sample_entity_conflict"),
    ({"unit_raw": "MPa", "unit_status": "confirmed"}, "unit_family_conflict"),
    ({"property_name_raw": "unknown", "standard_status": "standard_exact"}, "standard_field_unresolved"),
    ({"standard_property_code": "STD:melting_temperature"}, "standard_code_conflict"),
    ({"binding_status": "ambiguous"}, "binding_unresolved"),
    ({"display_scale_raw": "10^-3"}, "display_scale_unverified"),
    ({"unit_normalized": "K"}, "unit_conversion_unverified"),
    ({"property_name_raw": "", "property_name_normalized": "glass_transition_temperature"}, "input_incomplete"),
])
def test_claimed_confirmations_do_not_override_source(patch, reason):
    payload, inputs = source_fixture()
    payload["property_observations"][0].update(patch)
    row = publication_audit_for_final(payload, **inputs)["records"][0]
    assert row["publication_status"] != "final"
    assert reason in row["publication_reasons"], row


def test_partial_stage_and_source_scale_block_publication():
    payload, inputs = source_fixture("Tg (°C) ×10^3")
    inputs["stage4"]["provenance"]["status"] = "candidate_partial"
    row = publication_audit_for_final(payload, **inputs)["records"][0]
    assert row["publication_status"] == "not_publishable"
    assert {"input_incomplete", "display_scale_unverified"} <= set(row["publication_reasons"])


def test_source_input_is_required_even_when_path_is_claimed_complete():
    payload, inputs = source_fixture()
    payload["property_observations"][0]["property_path_status"] = "complete"
    inputs["stage0"] = None
    row = publication_audit_for_final(payload, **inputs)["records"][0]
    assert row["publication_status"] != "final"
    assert row["path_status"] == "candidate"


def test_duplicate_ids_preserve_both_records_and_block_publication():
    payload, inputs = source_fixture()
    payload["property_observations"].append(deepcopy(payload["property_observations"][0]))
    rows = publication_audit_for_final(payload, **inputs)["records"]
    assert len(rows) == 2
    assert all(r["publication_status"] == "not_publishable" for r in rows)
    assert all("duplicate_object_id" in r["publication_reasons"] for r in rows)


def test_condition_column_cannot_supply_property_unit():
    payload, inputs = source_fixture()
    inputs["stage0"]["elements"][0]["table_body"] = (
        "<table><tr><th>Sample</th><th>Temperature (°C)</th><th>Tg (K)</th></tr>"
        "<tr><td>A</td><td>25</td><td>120</td></tr></table>"
    )
    payload["evidence"][0]["table_locator"].update(cell_id="T1:r0001:c0002", column_index=2)
    row = publication_audit_for_final(payload, **inputs)["records"][0]
    assert row["publication_status"] == "not_publishable"
    assert "unit_source_conflict" in row["publication_reasons"]


def test_same_label_multiple_batches_stays_unresolved():
    payload, inputs = source_fixture()
    inputs["stage3"]["samples"][1]["sample_label_raw"] = "A"
    row = publication_audit_for_final(payload, **inputs)["records"][0]
    assert row["publication_status"] != "final"
    assert row["binding_status"] != "resolved"


def test_zero_value_remains_a_complete_measurement():
    payload, inputs = source_fixture()
    payload["property_observations"][0]["value_raw"] = "0"
    inputs["stage0"]["elements"][0]["table_body"] = inputs["stage0"]["elements"][0]["table_body"].replace('120', '0')
    assert publication_audit_for_final(payload, **inputs)["records"][0]["publication_status"] == "final"


def test_article_label_without_stage3_sample_can_publish_with_source_proof():
    payload, inputs = source_fixture()
    inputs["stage3"]["samples"] = []
    item = payload["property_observations"][0]
    item.pop("sample_id")
    item.pop("entity_id")
    before = deepcopy(payload)
    row = publication_audit_for_final(payload, **inputs)["records"][0]
    assert row["binding_status"] == "article_alias_confirmed", row
    assert row["publication_status"] == "final"
    assert row["article_sample_label_raw"] == "A"
    assert row["article_sample_key"].startswith("article_sample_")
    assert row["sample_id"] is None
    assert payload == before
    item["article_sample_key"] = row["article_sample_key"]
    assert publication_audit_for_final(payload, **inputs)["records"][0]["article_sample_key"] == row["article_sample_key"]
    item["article_sample_key"] = "invented"
    assert "article_sample_key_conflict" in publication_audit_for_final(payload, **inputs)["records"][0]["publication_reasons"]


def test_repeated_article_label_does_not_merge_different_source_rows():
    payload, inputs = source_fixture()
    inputs["stage3"]["samples"] = []
    inputs["stage0"]["elements"][0]["table_body"] = inputs["stage0"]["elements"][0]["table_body"].replace(">B<", ">A<")
    item = payload["property_observations"][0]
    item.pop("sample_id")
    item.pop("entity_id")
    first = publication_audit_for_final(payload, **inputs)["records"][0]
    item["value_raw"] = "100"
    payload["evidence"][0]["table_locator"].update(cell_id="T1:r0002:c0001", row_index=2)
    second = publication_audit_for_final(payload, **inputs)["records"][0]
    assert first["binding_status"] == second["binding_status"] == "article_alias_confirmed"
    assert first["article_sample_key"] != second["article_sample_key"]


@pytest.mark.parametrize("variant", ["valid", "missing_evidence", "wrong_table", "duplicate_name", "wrong_label"])
def test_entity_only_requires_unique_same_source_entity_proof(variant):
    payload, inputs = source_fixture()
    inputs["stage3"]["samples"] = []
    payload["property_observations"][0].pop("sample_id")
    entity = payload["polymer_entities"][0]
    entity.update(polymer_name="A", source_names=["A"], evidence={"block_id": "T1", "source_sentence": "A"})
    if variant == "missing_evidence": entity.pop("evidence")
    if variant == "wrong_table": entity["evidence"]["block_id"] = "T2"
    if variant == "duplicate_name": payload["polymer_entities"].append({**deepcopy(entity), "entity_id": "pe002"})
    if variant == "wrong_label": entity["evidence"]["source_sentence"] = "AB"
    row = publication_audit_for_final(payload, **inputs)["records"][0]
    if variant == "valid":
        assert row["publication_status"] == "final", row
        assert row["binding_status"] == "entity_only"
        assert row["entity_source_proof"]["label_cell_id"] == "T1:r0001:c0000"
    else:
        assert row["publication_status"] != "final"
        assert "entity_value_relation_unverified" in row["publication_reasons"]


def test_absent_catalog_entity_relation_is_unverified_not_a_conflict():
    payload, inputs = source_fixture()
    inputs["stage3"]["samples"][0].pop("refers_to_entity")
    row = publication_audit_for_final(payload, **inputs)["records"][0]
    assert "sample_entity_relation_unverified" in row["publication_reasons"]
    assert "sample_entity_conflict" not in row["publication_reasons"]
    assert row["publication_status"] == "candidate"
