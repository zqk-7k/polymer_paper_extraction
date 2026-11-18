import json

from tools.batch_stability_audit import compare_batches


def test_compare_batches_ignores_volatile_keys(tmp_path):
    left = tmp_path / "left" / "reference_no_1"
    right = tmp_path / "right" / "reference_no_1"
    left.mkdir(parents=True)
    right.mkdir(parents=True)
    for base, run_id in ((left, "a"), (right, "b")):
        (base / "candidate.json").write_text(
            json.dumps({"run_id": run_id, "properties": [{"value": 1}]}), encoding="utf-8"
        )
        for name in (
            "stage4_properties.json",
            "stage4_properties.unified_preview.json",
            "stage4t_shadow.json",
            "stage5_characterizations.json",
            "final.json",
            "stage6_validation.json",
        ):
            (base / name).write_text(json.dumps({"value": 1}), encoding="utf-8")

    result = compare_batches(left.parent, right.parent, tmp_path / "out")

    assert result["status"] == "stable"
    assert result["stable_documents"] == 1
    assert result["changed_documents"] == 0
