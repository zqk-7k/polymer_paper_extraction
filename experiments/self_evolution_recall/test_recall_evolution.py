from recall_evolution import aggregate, anchor_ready_properties, property_quality


def test_aggregate_penalizes_value_conflicts_on_both_sides() -> None:
    rows = [{
        "baseline": {
            "matched": 8,
            "value_diff": 2,
            "polyinfo_only": 2,
            "extraction_only": 0,
        }
    }]
    metrics = aggregate(rows, "baseline")
    assert metrics["precision"] == 0.8
    assert metrics["recall"] == round(8 / 12, 4)


def test_property_quality_requires_locatable_evidence(tmp_path) -> None:
    (tmp_path / "stage3_process.json").write_text(
        '{"samples":[{"sample_id":"s001"}]}',
        encoding="utf-8",
    )
    properties = [
        {
            "sample_id": "s001",
            "unit_raw": "MPa",
            "evidence": [{"block_id": "P_1", "page": 1, "bbox": [1, 2, 3, 4]}],
        },
        {"sample_id": "missing", "evidence": []},
    ]
    quality = property_quality(tmp_path, properties)
    assert quality["sample_binding_rate"] == 0.5
    assert quality["evidence_location_rate"] == 0.5
    assert quality["unit_completeness"] == 0.5


def test_anchor_normalization_uses_explicit_molecular_weight_type() -> None:
    original = [{
        "property_name_raw": "$M_{\\text{w}}$",
        "property_name_normalized": None,
        "molecular_weight_type": "Mw",
    }]
    normalized = anchor_ready_properties(original)
    assert normalized[0]["property_name_normalized"] == "mw"
    assert original[0]["property_name_normalized"] is None
