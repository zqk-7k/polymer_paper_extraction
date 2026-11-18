from __future__ import annotations

from stages.stage4t_candidate_gate import assess_publication_candidate


def test_gate_requires_semantics_and_resolved_sample() -> None:
    candidate = {
        "table_id": "T_1",
        "cell_id": "T_1:r0001:c0001",
        "direction": "row_samples",
        "property_name_normalized": "glass_transition_temperature",
        "semantic_label": None,
        "conditions": {},
        "measurement_role": "experimental",
        "value_kind": "numeric_scalar",
        "value_has_footnote": False,
    }

    blocked = assess_publication_candidate(candidate)
    eligible = assess_publication_candidate(
        candidate,
        resolved_sample_id="s001",
        condition_binding_validated=True,
        value_validated=True,
    )

    assert blocked["status"] == "candidate_only"
    assert blocked["blockers"] == ["sample_not_resolved"]
    assert eligible["status"] == "eligible"
    assert eligible["target"] == "property_observation"


def test_gate_holds_unmapped_and_calculated_candidates() -> None:
    candidate = {
        "table_id": "T_1",
        "cell_id": "T_1:r0001:c0001",
        "direction": "row_samples",
        "property_name_normalized": None,
        "semantic_label": None,
        "conditions": {},
        "measurement_role": "calculated",
        "value_kind": "numeric_scalar",
        "value_has_footnote": False,
    }

    result = assess_publication_candidate(
        candidate,
        resolved_sample_id="s001",
        condition_binding_validated=True,
        value_validated=True,
    )

    assert result["status"] == "candidate_only"
    assert result["target"] is None
    assert result["blockers"] == [
        "semantic_unmapped",
        "calculated_property_policy_not_resolved",
    ]
