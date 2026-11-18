import json
import pytest
from tools.production_export import build_export
from tools.source_index_diagnostics import FAILURE_CLASSES


def row(i, sample="unresolved", source="MPa", target="GPa", value=80):
    return {"standard_record_id": f"GT:{i}", "reference_no": "reference_no_1",
            "standard_property_code": "STD:tensile_stress_at_break", "status": "sample_unresolved",
            "value_captured": True, "reviewed_unit": target, "value_min": .08,
            "sample_binding_status": sample, "evidence_binding_status": "conflict",
            "matched_observations": [{"value_raw": str(value), "unit_raw": source,
                                      "sample_id": None, "source_file": "stage4t_shadow.json"}]}


def run(tmp_path, rows):
    alignment = tmp_path / "alignment"
    output = tmp_path / "export"
    alignment.mkdir(exist_ok=True)
    (alignment / "properties_alignment.jsonl").write_text("".join(json.dumps(r)+"\n" for r in rows), encoding="utf-8")
    return build_export(alignment, output), output


def test_samples_and_unit_review_never_block_value_export(tmp_path):
    missing = row(4)
    missing.update(value_captured=False, matched_observations=[])
    result, output = run(tmp_path, [row(1), row(2, "ambiguous"), row(3, source="unknown"), missing])
    assert result["counts"]["candidate_value_only"] == 3
    assert result["counts"]["final_value_only"] == 3
    assert result["counts"]["not_captured"] == 1
    assert result["counts"]["unit_conversion_review"] == 1
    assert not (output / "dataset.jsonl").exists()
    items = [json.loads(s) for s in (output / "final_value_only.jsonl").read_text(encoding="utf-8").splitlines()]
    assert items[0]["standard_value"] == .08
    assert items[0]["original_value"] == 80
    assert items[0]["reference_value_min"] == .08
    assert "value_min" not in items[0]
    assert items[2]["standard_value"] is None
    assert items[2]["original_value"] == 80
    assert items[2]["unit_review_required"] is True


def test_multiple_values_retained_and_export_is_deterministic(tmp_path):
    a = row(1)
    a["matched_observations"].append({"value_raw": "81", "unit_raw": "MPa", "sample_id": "s002"})
    _, output = run(tmp_path, [a])
    before = (output / "final_value_only.jsonl").read_bytes()
    _, output = run(tmp_path, [a])
    assert before == (output / "final_value_only.jsonl").read_bytes()
    item = json.loads(before)
    assert item["observation_count"] == 2
    assert item["standard_value"] is None
    assert "multiple_value_representations" in item["value_parse_warnings"]


def test_legacy_audit_cannot_publish_reference_values_as_observations(tmp_path):
    r = row(1)
    del r["matched_observations"]
    with pytest.raises(ValueError, match="lacks source observations"):
        run(tmp_path, [r])


@pytest.mark.parametrize('failure_class', sorted(FAILURE_CLASSES))
def test_diagnostics_preserve_all_failure_classes_without_backfilling_values(tmp_path, failure_class):
    missing = row(1)
    missing.update(value_captured=False, matched_observations=[])
    _, output = run(tmp_path, [missing])
    diagnostic = tmp_path / 'diagnostics.jsonl'
    diagnostic.write_text(json.dumps({
        'standard_record_id': 'GT:1', 'current_value_captured': False,
        'index_failure_class': failure_class, 'index_failure_reason': 'specific_source_failure',
        # Untrusted extra fields must never replace observations or predictions.
        'matched_observations': [{'value_raw': '80', 'unit_raw': 'MPa'}],
        'standard_value': .08, 'value_captured': True,
    })+'\n', encoding='utf-8')
    manifest = build_export(tmp_path / 'alignment', output, diagnostic)
    assert manifest['counts']['final_value_only'] == 0
    out = json.loads((output / 'not_captured.jsonl').read_text(encoding='utf-8'))
    assert out['failure_reason'] == 'specific_source_failure'
    assert out['index_failure_class'] == failure_class
    assert out['standard_value'] is None and out['observations'] == []


def test_stale_diagnostics_are_rejected(tmp_path):
    _, output = run(tmp_path, [row(1)])
    diagnostic = tmp_path / 'diagnostics.jsonl'
    diagnostic.write_text(json.dumps({'standard_record_id': 'GT:1', 'current_value_captured': False,
                                     'index_failure_class': 'needs_original_review'})+'\n', encoding='utf-8')
    with pytest.raises(ValueError, match='do not match'):
        build_export(tmp_path / 'alignment', output, diagnostic)
