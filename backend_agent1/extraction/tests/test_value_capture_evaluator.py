import json
from pathlib import Path

from tools.value_capture_evaluator import collect_candidates, evaluate, load_gt_exclusions, write_outputs


def _write_doc(root: Path, payload: dict, *, shadow: dict | None = None, final: dict | None = None) -> Path:
    doc = root / "reference_no_test"
    doc.mkdir()
    (doc / "stage4_properties.json").write_text(json.dumps(payload), encoding="utf-8")
    if shadow is not None:
        (doc / "stage4t_shadow.json").write_text(json.dumps(shadow), encoding="utf-8")
    if final is not None:
        (doc / "final.json").write_text(json.dumps(final), encoding="utf-8")
    return doc


def test_collect_candidates_includes_stage4n_and_stage4t_without_sample_binding(tmp_path, monkeypatch) -> None:
    doc = tmp_path / "reference_no_test"
    doc.mkdir()
    (doc / "stage4_properties.json").write_text(json.dumps({
        "properties": [{
            "property_id": "p1",
            "property_name_raw": "glass transition temperature",
            "value_raw": "80",
            "value_min": 80,
            "value_max": 80,
            "unit_raw": "°C",
        }],
    }), encoding="utf-8")
    (doc / "stage4t_shadow.json").write_text(json.dumps({
        "tables": [{
            "observations": [{
                "observation_id": "t1",
                "property_name_raw": "melting temperature",
                "value_raw": "120",
                "unit_raw": "°C",
                "sample_label_raw": "Table-A",
                "evidence_locator": {"header_path": ["Tm (°C)"]},
            }],
        }],
    }), encoding="utf-8")

    candidates = collect_candidates("reference_no_test", doc)

    assert {candidate["source_stage"] for candidate in candidates} == {"stage4n", "stage4t"}
    assert any(candidate["bucket"] == "tg" for candidate in candidates)
    assert any(candidate["bucket"] == "tm" for candidate in candidates)


def test_evaluate_counts_correct_value_even_when_sample_is_unresolved(tmp_path, monkeypatch) -> None:
    # Patch the GT loader so this unit test does not depend on the PolyInfo tree.
    from tools import value_capture_evaluator as evaluator

    monkeypatch.setattr(evaluator, "load_gt", lambda root, doc_ids: {
        "reference_no_test": [{
            "doc_id": "reference_no_test",
            "property_name": "glass transition temperature",
            "bucket": "tg",
            "value_min": 80.0,
            "value_max": 80.0,
            "paired_event_id": None,
            "coverage_eligible": True,
        }]
    })
    doc = tmp_path / "reference_no_test"
    doc.mkdir()
    (doc / "stage4t_shadow.json").write_text(json.dumps({
        "tables": [{"observations": [{
            "observation_id": "t1",
            "property_name_raw": "Tg",
            "value_raw": "80",
            "unit_raw": "°C",
            "publication_gate": {"status": "candidate_only"},
            "sample_label_raw": "unresolved-sample",
        }]}],
    }), encoding="utf-8")

    rows, summary = evaluate(tmp_path, tmp_path)

    assert rows[0]["capture_status"] == "captured_correct"
    assert rows[0]["capture_layer"] == "stage4t"
    assert summary["gt_included"] == 1
    assert summary["value_capture_recall"] == 1.0


def test_evaluate_converts_explicit_kelvin_to_celsius_for_temperature(tmp_path, monkeypatch) -> None:
    from tools import value_capture_evaluator as evaluator

    monkeypatch.setattr(evaluator, "load_gt", lambda root, doc_ids: {
        "reference_no_test": [{
            "doc_id": "reference_no_test",
            "property_name": "glass transition temperature",
            "bucket": "tg",
            "unit": "C",
            "value_min": 160.0,
            "value_max": 160.0,
            "coverage_eligible": True,
        }]
    })
    doc = tmp_path / "reference_no_test"
    doc.mkdir()
    (doc / "stage4_properties.json").write_text(json.dumps({"properties": [{
        "property_name_raw": "glass transition temperature",
        "value_raw": "433",
        "unit_raw": "K",
    }]}), encoding="utf-8")

    rows, summary = evaluate(tmp_path, tmp_path)

    assert rows[0]["capture_status"] == "captured_correct"
    assert rows[0]["match_tier"] == "exact"
    assert rows[0]["match_conversion"]["operation"] == "K_to_C"
    assert summary["value_capture_recall"] == 1.0


def test_evaluate_converts_explicit_joule_per_gram_to_kcal_per_gram(tmp_path, monkeypatch) -> None:
    from tools import value_capture_evaluator as evaluator

    monkeypatch.setattr(evaluator, "load_gt", lambda root, doc_ids: {
        "reference_no_test": [{
            "doc_id": "reference_no_test",
            "property_name": "heat of fusion",
            "bucket": "heat_fusion",
            "unit": "kcal/g",
            "value_min": 0.0086,
            "value_max": 0.0086,
            "coverage_eligible": True,
        }]
    })
    doc = tmp_path / "reference_no_test"
    doc.mkdir()
    (doc / "stage4_properties.json").write_text(json.dumps({"properties": [{
        "property_name_raw": "heat of fusion",
        "value_raw": "36",
        "unit_raw": "J/g",
    }]}), encoding="utf-8")

    rows, summary = evaluate(tmp_path, tmp_path)

    assert rows[0]["capture_status"] == "captured_correct"
    assert rows[0]["match_tier"] == "exact"
    assert rows[0]["match_conversion"]["operation"] == "energy_per_g_unit_conversion"
    assert abs(rows[0]["matched_pred_value"] - 0.0086) < 0.0001
    assert summary["value_capture_recall"] == 1.0


def test_paired_rows_are_excluded_from_default_denominator(tmp_path, monkeypatch) -> None:
    from tools import value_capture_evaluator as evaluator

    monkeypatch.setattr(evaluator, "load_gt", lambda root, doc_ids: {
        "reference_no_test": [
            {"doc_id": "reference_no_test", "bucket": "tg", "value_min": 80, "value_max": 80, "coverage_eligible": True},
            {"doc_id": "reference_no_test", "bucket": "td", "value_min": 400, "value_max": 400, "paired_event_id": "e1", "coverage_eligible": True},
        ]
    })
    doc = tmp_path / "reference_no_test"
    doc.mkdir()
    (doc / "stage4_properties.json").write_text(json.dumps({"properties": [{
        "property_name_raw": "Tg", "value_raw": "80", "unit_raw": "°C"
    }]}), encoding="utf-8")

    _, summary = evaluate(tmp_path, tmp_path)

    assert summary["gt_included"] == 1
    assert summary["paired_rows_excluded_by_default"] is True


def test_collect_candidates_keeps_raw_llm_value_as_separate_layer(tmp_path) -> None:
    doc = tmp_path / "reference_no_test"
    doc.mkdir()
    (doc / "stage4_llm_response.json").write_text(json.dumps({
        "raw_response": {
            "content": json.dumps({"properties": [{
                "property_id": "raw-p1",
                "property_name_raw": "glass transition temperature",
                "value_raw": "80",
                "value_min": 80,
                "value_max": 80,
                "unit_raw": "°C",
            }]})
        }
    }), encoding="utf-8")

    candidates = collect_candidates("reference_no_test", doc)

    assert len(candidates) == 1
    assert candidates[0]["source_stage"] == "stage4n_raw_llm"
    assert candidates[0]["bucket"] == "tg"


def test_versioned_gt_pair_row_is_excluded(tmp_path, monkeypatch) -> None:
    from tools import value_capture_evaluator as evaluator

    monkeypatch.setattr(evaluator, "load_gt_points", lambda path: {
        "reference_no_test": [
            {"doc_id": "reference_no_test", "bucket": "tg", "value_min": 80, "value_max": 80, "coverage_eligible": True},
            {"doc_id": "reference_no_test", "bucket": "td", "value_min": 400, "value_max": 400, "pair_row": "1", "coverage_eligible": True},
        ]
    })
    doc = tmp_path / "reference_no_test"
    doc.mkdir()
    (doc / "stage4_properties.json").write_text(json.dumps({"properties": [{
        "property_name_raw": "Tg", "value_raw": "80", "unit_raw": "°C"
    }]}), encoding="utf-8")

    _, summary = evaluator.evaluate(tmp_path, tmp_path, gt_points_path="manifest.jsonl")

    assert summary["gt_included"] == 1
    assert summary["paired_rows_excluded_by_default"] is True


def test_gt_exclusion_manifest_removes_rows_from_denominator(tmp_path, monkeypatch) -> None:
    from tools import value_capture_evaluator as evaluator

    monkeypatch.setattr(evaluator, "load_gt_points", lambda path: {
        "reference_no_test": [
            {"doc_id": "reference_no_test", "row_id": "1", "bucket": "tg", "value_min": 80, "value_max": 80, "coverage_eligible": True},
            {"doc_id": "reference_no_test", "row_id": "2", "bucket": "water_abs", "value_min": 5, "value_max": 5, "coverage_eligible": True},
        ]
    })
    doc = tmp_path / "reference_no_test"
    doc.mkdir()
    (doc / "stage4_properties.json").write_text(json.dumps({"properties": [{
        "property_name_raw": "Tg", "value_raw": "80", "unit_raw": "°C"
    }]}), encoding="utf-8")
    exclusions = tmp_path / "exclusions.json"
    exclusions.write_text(json.dumps({"exclusions": [{
        "doc_id": "reference_no_test", "row_id": "2",
        "reason": "image_reading", "source_locator": "Figure 3"
    }]}), encoding="utf-8")

    rows, summary = evaluate(
        tmp_path,
        tmp_path,
        gt_points_path="manifest.jsonl",
        gt_exclusions_path=exclusions,
    )

    assert len(rows) == 1
    assert summary["gt_included"] == 1
    assert summary["excluded_by_reason"] == {"image_reading": 1}
    assert summary["per_doc"]["reference_no_test"]["excluded"] == {
        "image_reading": 1
    }


def test_gt_exclusion_manifest_rejects_duplicate_key(tmp_path) -> None:
    path = tmp_path / "exclusions.json"
    path.write_text(json.dumps({"exclusions": [
        {"doc_id": "d", "row_id": "1", "reason": "image_reading"},
        {"doc_id": "d", "row_id": "1", "reason": "derived_value"},
    ]}), encoding="utf-8")

    try:
        load_gt_exclusions(path)
    except ValueError as exc:
        assert "重复" in str(exc)
    else:
        raise AssertionError("expected duplicate exclusion key to fail")


def test_write_outputs_includes_per_doc_recall_table(tmp_path) -> None:
    write_outputs([], {
        "documents": 1,
        "gt_included": 2,
        "captured_correct": 1,
        "structured_correct": 1,
        "raw_only_correct": 0,
        "exact": 1,
        "captured_wrong_value": 1,
        "not_captured": 0,
        "candidate_present": 2,
        "candidate_presence_recall": 1.0,
        "value_capture_recall": 0.5,
        "exact_recall": 0.5,
        "excluded_by_reason": {},
        "per_doc": {
            "reference_no_test": {
                "gt_included": 2,
                "captured_correct": 1,
                "exact": 1,
                "captured_wrong_value": 1,
                "not_captured": 0,
            },
        },
    }, tmp_path)
    report = (tmp_path / "value_capture_report.md").read_text(encoding="utf-8")
    assert "## 逐篇统计" in report
    assert "| reference_no_test | 2 | 1 | 50.0% | 100.0% | 1 | 1 | 0 |" in report
