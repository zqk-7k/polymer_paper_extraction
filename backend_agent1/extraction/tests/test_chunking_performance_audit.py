from tools.chunking_performance_audit import _collect_block_ids, _iter_evidence_objects


def test_collect_block_ids_and_nested_evidence_objects() -> None:
    payload = {
        "material_mentions": [{
            "evidence": {"block_id": "P1"},
            "nested": {"evidence": [{"block_id": "P2"}]},
        }],
        "warnings": [{"block_id": "ignored_for_object_scope"}],
    }

    objects = list(_iter_evidence_objects(payload))

    assert len(objects) == 2
    assert _collect_block_ids(objects[0]["evidence"]) == {"P1"}
    assert _collect_block_ids(objects[0]["nested"]["evidence"]) == {"P2"}
