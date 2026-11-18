from copy import deepcopy

from stages.publication_evidence import repair_specialized_evidence


def source():
    return {"document_id": "test", "elements": [{
        "block_id": "P1", "type": "text", "page": 0, "source_block_index": 0,
        "text": "The sample was linear.",
    }]}


def payload():
    return {"document_id": "test", "evidence": [], "specialized_property_observations": [{
        "specialized_id": "sp001", "evidence_ids": ["ev999"], "evidence": [{
            "block_id": "P1", "page": 0, "source_type": "text", "source_sentence": "The sample was linear.",
        }],
    }]}


def test_repair_validates_source_preserves_input_and_is_idempotent():
    original = payload()
    snapshot = deepcopy(original)
    repaired, log = repair_specialized_evidence(original, source())
    assert original == snapshot
    assert log[0]["status"] == "registered"
    assert repaired["specialized_property_observations"][0]["evidence_ids"] == ["ev1000"]
    assert repaired["evidence"][0]["evidence_id"] == "ev1000"
    repeated, log = repair_specialized_evidence(repaired, source())
    assert repeated == repaired
    assert log == []


def test_invalid_inline_evidence_is_not_registered():
    original = payload()
    original["specialized_property_observations"][0]["evidence"][0]["block_id"] = "missing"
    repaired, log = repair_specialized_evidence(original, source())
    assert repaired == original
    assert log[0]["status"] == "not_repaired"
    assert repaired["evidence"] == []


def test_same_old_id_on_different_evidence_does_not_merge_records():
    original = payload()
    stage0 = source()
    stage0["elements"].append({**stage0["elements"][0], "block_id": "P2", "source_block_index": 1})
    other = deepcopy(original["specialized_property_observations"][0])
    other["specialized_id"] = "sp002"
    other["evidence"][0]["block_id"] = "P2"
    original["specialized_property_observations"].append(other)
    repaired, _ = repair_specialized_evidence(original, stage0)
    assert len(repaired["evidence"]) == 2
    assert repaired["specialized_property_observations"][0]["evidence_ids"] != repaired["specialized_property_observations"][1]["evidence_ids"]


def test_legacy_tracking_metadata_is_preserved_but_not_part_of_evidence_identity():
    original = payload()
    original["evidence"] = [{
        **original["specialized_property_observations"][0]["evidence"][0],
        "evidence_id": "ev002", "source_stage": "stage4_property", "object_id": "sp001",
    }]
    repaired, _ = repair_specialized_evidence(original, source())
    assert repaired["evidence"] == original["evidence"]
    assert repaired["specialized_property_observations"][0]["evidence_ids"] == ["ev002"]


def test_no_specialized_records_does_not_rewrite_unrelated_legacy_evidence():
    original = {"document_id": "test", "evidence": [{"evidence_id": "ev001", "block_id": "P1"}]}
    assert repair_specialized_evidence(original, source()) == (original, [])
