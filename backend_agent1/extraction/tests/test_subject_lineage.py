import copy

from stages.subject_lineage import build_lineage, subject_chain, inherit_entity_ids, audit_lineage


def inputs():
    stage2 = {"polymer_entities": [{"entity_id": "pe001", "resolved_from_mentions": ["m001"]}, {"entity_id": "pe002"}]}
    stage3 = {"samples": [{"sample_id": "s001"}, {"sample_id": "s002", "refers_to_entity": "pe001"},
                           {"sample_id": "s003", "refers_to_entity": "pe002"}],
              "process_steps": [{"step_id": "ps001", "input_sample_ids": ["s001"], "output_sample_ids": ["s002"]}]}
    return stage2, stage3


def test_chain_uses_ids_and_preserves_raw_material_without_entity():
    lineage = build_lineage(*inputs())
    chain = subject_chain({"sample_id": "s002"}, lineage)
    assert chain["status"] == "linked"
    assert chain["entity_ids"] == ["pe001"]
    assert chain["process_step_ids"] == ["ps001"]
    assert chain["ancestor_sample_ids"] == ["s001"]
    assert chain["mention_ids"] == ["m001"]
    assert subject_chain({"sample_id": "s001"}, lineage)["status"] == "entity_unlinked"
    assert not lineage["reference_errors"]


def test_conflicts_are_reported_not_replaced_with_derived_entity():
    stage2, stage3 = inputs()
    payload = {"properties": [{"sample_id": "s002", "entity_id": "pe002", "value_raw": "120"}]}
    before = copy.deepcopy(payload)
    assert subject_chain(payload["properties"][0], build_lineage(stage2, stage3))["errors"] == ["sample_entity_conflict"]
    assert inherit_entity_ids(payload, stage2, stage3) == before == payload


def test_exact_inheritance_handles_multi_subjects_without_name_matching():
    stage2, stage3 = inputs()
    payload = {"properties": [{"sample_id": "s002"}, {"sample_label_raw": "s002"}, {"sample_ids": ["s002", "s003"]}]}
    result = inherit_entity_ids(payload, stage2, stage3)
    assert result["properties"][0]["entity_id"] == "pe001"
    assert "entity_id" not in result["properties"][1]
    assert result["properties"][2]["entity_ids"] == ["pe001", "pe002"]
    assert "entity_id" not in payload["properties"][0]


def test_dangling_references_and_cycles_are_visible():
    stage2, stage3 = inputs()
    stage3["process_steps"].append({"step_id": "ps002", "input_sample_ids": ["s002", "s999"], "output_sample_ids": ["s001"]})
    lineage = build_lineage(stage2, stage3)
    assert lineage["reference_errors"][0]["code"] == "process_unknown_sample"
    assert "process_cycle" in subject_chain({"sample_id": "s002"}, lineage)["errors"]
    assert subject_chain({"sample_id": "s999"}, lineage)["status"] == "conflict"


def test_series_point_own_subject_does_not_inherit_parent_entity():
    stage2, stage3 = inputs()
    audit = audit_lineage({"stage2_entities.json": stage2, "stage3_process.json": stage3,
                          "stage4_properties.json": {"property_series": [{"sample_id": "s002", "entity_id": "pe001",
                              "points": [{"sample_id": "s003", "value_raw": "120"}]}]}})
    assert audit["rows"][1]["entity_ids"] == ["pe002"]
    assert audit["rows"][1]["status"] == "linked"


def test_default_null_series_point_inherits_existing_series_subject():
    stage2, stage3 = inputs()
    audit = audit_lineage({"stage2_entities.json": stage2, "stage3_process.json": stage3,
                          "stage4_properties.json": {"property_series": [{"sample_id": "s002", "entity_id": "pe001",
                              "points": [{"sample_id": None, "entity_id": None, "value_raw": "120"}]}]}})
    assert audit["rows"][1]["sample_ids"] == ["s002"]
    assert audit["rows"][1]["status"] == "linked"
