"""Stage 4T 宽松候选到权威层的确定性门控。"""

from __future__ import annotations

from typing import Any, Mapping


def semantic_classification(
    property_name: str | None,
    semantic_label: str | None,
) -> tuple[str, str, str | None]:
    if property_name:
        return "normalized", "official_property", "property_observation"
    if semantic_label:
        return (
            "mapped_characteristic",
            "material_characteristic",
            "material_characteristic_observation",
        )
    return "unmapped", "unknown_observation", None


def assess_publication_candidate(
    candidate: Mapping[str, Any],
    *,
    resolved_sample_id: str | None = None,
    condition_binding_validated: bool = False,
    value_validated: bool = False,
) -> dict[str, Any]:
    """给出发布资格；本函数不发布或改写候选。"""
    semantic_status, _, target = semantic_classification(
        candidate.get("property_name_normalized"),
        candidate.get("semantic_label"),
    )
    blockers: list[str] = []
    if semantic_status == "unmapped":
        blockers.append("semantic_unmapped")
    if not resolved_sample_id:
        blockers.append(
            "subject_not_resolved"
            if candidate.get("direction") == "condition_series"
            else "sample_not_resolved"
        )
    if candidate.get("conditions") and not condition_binding_validated:
        blockers.append("condition_binding_not_validated")
    if candidate.get("measurement_role") == "calculated":
        blockers.append("calculated_property_policy_not_resolved")
    if candidate.get("value_kind") in {
        "numeric_range",
        "numeric_multiple",
        "numeric_with_uncertainty",
        "state_qualified_numeric",
    } and not value_validated:
        blockers.append("value_structure_not_validated")
    if candidate.get("value_has_footnote") and not value_validated:
        blockers.append("footnote_not_resolved")

    blockers = list(dict.fromkeys(blockers))
    return {
        "status": "eligible" if not blockers and target else "candidate_only",
        "target": target,
        "blockers": blockers,
        "checks": {
            "semantic_bound": semantic_status != "unmapped",
            "sample_bound": bool(resolved_sample_id),
            "conditions_validated": bool(condition_binding_validated),
            "value_validated": bool(value_validated),
            "evidence_bound": bool(
                candidate.get("cell_id") and candidate.get("table_id")
            ),
        },
    }
