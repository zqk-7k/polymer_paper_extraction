from controlled_evolution import aggregate, score_case


def _case() -> dict:
    return {
        "case_id": "c1",
        "split": "frozen_test",
        "ref_no": "reference_no_test",
        "table_id": "T_1",
        "expected_semantics": [{
            "anchor_cell_id": "T_1:r0000:c0001",
            "decision": "specialized",
            "source_field": "crystallographic_data",
            "semantic_label": "d_spacing",
        }],
        "expected_samples": [{
            "sample_label_raw": "PC-1",
            "status": "matched",
            "sample_id": "s001",
        }],
        "expected_out_of_scope_min": 0,
    }


def _artifact() -> dict:
    return {
        "status": "succeeded",
        "response": {
            "semantic_assignments": [{
                "source_cell_ids": ["T_1:r0000:c0001"],
                "decision": "specialized",
                "source_field": "crystallographic_data",
                "semantic_label": "d_spacing",
            }],
            "sample_assignments": [{
                "sample_label_raw": "PC-1",
                "status": "matched",
                "sample_id": "s001",
            }],
        },
    }


def test_score_case_matches_semantic_and_sample() -> None:
    row = score_case(_case(), _artifact())
    assert row["semantic_tp"] == 1
    assert row["semantic_fp"] == 0
    assert row["semantic_fn"] == 0
    assert row["sample_correct"] == 1
    assert row["out_of_scope_expected"] is False


def test_aggregate_penalizes_extra_specialized_assignment() -> None:
    artifact = _artifact()
    artifact["response"]["semantic_assignments"].append({
        "source_cell_ids": ["T_1:r0000:c0002"],
        "decision": "specialized",
        "source_field": "morphology",
        "semantic_label": "fiber_length",
    })
    metrics = aggregate([score_case(_case(), artifact)])
    assert metrics["semantic_precision"] == 0.5
    assert metrics["semantic_recall"] == 1.0
    assert metrics["out_of_scope_cases"] == 0


def test_aggregate_counts_only_preregistered_out_of_scope_cases() -> None:
    case = _case()
    case["expected_out_of_scope_min"] = 1
    artifact = _artifact()
    artifact["response"]["semantic_assignments"].append({
        "source_cell_ids": ["T_1:r0000:c0002"],
        "decision": "not_in_specialized_scope",
        "source_field": None,
        "semantic_label": None,
    })

    metrics = aggregate([score_case(case, artifact)])

    assert metrics["out_of_scope_cases"] == 1
    assert metrics["out_of_scope_cases_passed"] == 1
