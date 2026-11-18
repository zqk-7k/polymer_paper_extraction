from copy import deepcopy

import pytest

from stages.measurement_publication import build_measurement_publication
from stages.raw_measurement_candidates import build_raw_candidate_ledger
from tests.test_measurement_publication import fixture


def shadow():
    raw = {"observation_id": "o1", "table_id": "T1", "cell_id": "T1:r0001:c0001",
           "row_index": 1, "column_index": 1, "property_name_raw": "Tg", "unit_raw": "°C",
           "value_raw": "120", "binding_status": "bound", "sample_label_raw": "A"}
    return {"document_id": "test", "tables": [{"table_id": "T1", "shadow_observations": [raw], "observations": [deepcopy(raw)]}]}


def test_same_expression_in_multiple_views_is_losslessly_deduplicated():
    _, inputs = fixture()
    source = shadow()
    before = deepcopy(source)
    result = build_raw_candidate_ledger(inputs["stage0"], inputs["stage2"], inputs["stage3"], stage4t=source)
    assert result["counts"]["expression_count"] == 1
    assert result["counts"]["occurrence_count"] == 2
    assert result["counts"]["duplicate_view_count"] == 1
    row = result["records"][0]
    assert row["source_cell_ids"] == ["T1:r0001:c0001"]
    assert row["record"]["source_stage"] == "stage4t"
    assert row["publication_status"] == "not_publishable"
    assert row["original_record"]["binding_status"] == "bound"
    assert source == before


def test_preview_claims_link_to_primary_without_claiming_publication_authority():
    payload, inputs = fixture()
    scalar = deepcopy(payload["property_observations"][0])
    scalar["evidence"] = [{k: v for k, v in payload["evidence"][0].items() if k != "evidence_id"}]
    scalar.pop("evidence_ids")
    stage4r = {"document_id": "test", "properties": [scalar]}
    result = build_measurement_publication(payload, **inputs, stage4t=shadow(), stage4r=stage4r)
    assert result["counts"]["final"] == 1
    assert len(result["raw_candidate_ledger"]["records"]) == 2
    assert all(r["publication_status"] != "final" for r in result["raw_candidate_ledger"]["records"])
    assert len(result["source_cell_groups"]) == 1
    group = result["source_cell_groups"][0]
    assert len(group["publication_measurement_ids"]) == 1 and len(group["raw_measurement_ids"]) == 2


def test_different_claims_are_not_merged_and_wrong_values_remain_rejected():
    _, inputs = fixture()
    source = shadow()
    source["tables"][0]["observations"][0]["value_raw"] = "999"
    result = build_raw_candidate_ledger(inputs["stage0"], inputs["stage2"], inputs["stage3"], stage4t=source)
    assert result["counts"]["expression_count"] == 2
    bad = next(r for r in result["records"] if r["original_record"]["value_raw"] == "999")
    assert "value_not_in_target_cell" in bad["publication_reasons"]


def test_non_scalar_and_mixed_documents_do_not_disappear():
    _, inputs = fixture()
    source = shadow()
    source["tables"][0]["unresolved"] = [{"reason": "missing_column"}]
    result = build_raw_candidate_ledger(inputs["stage0"], inputs["stage2"], inputs["stage3"], stage4t=source)
    assert result["counts"]["auxiliary_count"] == 1
    assert result["auxiliary_records"][0]["original_record"] == {"reason": "missing_column"}
    source["document_id"] = "another_document"
    with pytest.raises(ValueError, match="document mismatch"):
        build_raw_candidate_ledger(inputs["stage0"], inputs["stage2"], inputs["stage3"], stage4t=source)


def test_missing_stage3_keeps_table_candidates_without_inventing_a_catalog():
    _, inputs = fixture()
    result = build_raw_candidate_ledger(inputs["stage0"], inputs["stage2"], None, stage4t=shadow())
    assert result["counts"]["expression_count"] == 1
    row = result["records"][0]
    assert row["publication_status"] == "not_publishable"
    assert "sample_catalog_missing" in row["publication_reasons"]
    assert row["record"]["sample_id"] is None


def test_dose_is_routed_to_context_review_without_losing_claims_or_releasing_values():
    _, inputs = fixture()
    table = inputs["stage0"]["elements"][0]
    table["table_body"] = table["table_body"].replace("Tg (°C)", "Dose/kGy").replace("th>", "td>")
    source = shadow()
    for name in ("observations", "shadow_observations"):
        source["tables"][0][name][0].update(property_name_raw="Dose/kGy", unit_raw="mol/L")
    before = deepcopy((source, inputs))
    result = build_raw_candidate_ledger(inputs["stage0"], inputs["stage2"], inputs["stage3"], stage4t=source)
    row = result["records"][0]
    assert row["review_route"] == "context_review"
    assert row["source_roles"][0]["cell_role"] == "condition"
    assert row["original_record"]["unit_raw"] == "mol/L"
    assert row["publication_status"] != "final"
    assert "unit_source_unverified" in row["publication_reasons"]
    assert len(row["source_occurrences"]) == 2
    assert result["counts"]["review_route_counts"] == {"context_review": 1}
    assert (source, inputs) == before
    for name in ("observations", "shadow_observations"):
        source["tables"][0][name][0]["value_raw"] = "999"
    wrong = build_raw_candidate_ledger(inputs["stage0"], inputs["stage2"], inputs["stage3"], stage4t=source)
    assert wrong["records"][0]["review_route"] == "source_review"


def condition_fixture():
    _, inputs = fixture()
    inputs["stage0"]["elements"][0]["table_body"] = (
        "<table><tr><td>Sample</td><td>Tg (°C)</td><td>Dose/kGy</td></tr>"
        "<tr><td>A</td><td>120</td><td>8.1</td></tr>"
        "<tr><td>B</td><td>100</td><td>50</td></tr></table>")
    return inputs, shadow()


def test_source_context_preserves_empty_or_conflicting_model_conditions_without_overwrite():
    inputs, source = condition_fixture()
    source["tables"][0]["observations"][0]["conditions"] = {"dose": "999 kGy"}
    before = deepcopy((inputs, source))
    ledger = build_raw_candidate_ledger(inputs["stage0"], inputs["stage2"], inputs["stage3"], stage4t=source)
    assert len(ledger["records"]) == 2
    for row in ledger["records"]:
        link = row["source_context"]
        assert link["status"] == "candidate"  # td header inference is still explicit
        assert link["table_id"] == "T1" and link["target_cell_id"] == "T1:r0001:c0001"
        assert link["condition_axes"][0]["value_raw"] == "8.1"
        assert link["condition_axes"][0]["header_path"] == ["Dose/kGy"]
        has_claim = bool(row["original_record"].get("conditions"))
        assert link["declared_context_comparison"] == ("needs_review" if has_claim else "declaration_missing")
        if has_claim:
            assert link["declared_context_audit"]["axes"][0]["numeric_comparison"] == "different"
        assert link["evidence_cell_ids"] == ["T1:r0001:c0001", "T1:r0001:c0002", "T1:r0000:c0002"]
        assert row["effective_candidate"]["measurement_context"] == row["original_record"].get("conditions", {})
        assert row["publication_status"] != "final"
    assert ledger["counts"]["source_context_expression_count"] == 2
    assert ledger["counts"]["source_context_status_counts"] == {"candidate": 2}
    assert (inputs, source) == before


def test_wrong_value_or_property_does_not_gain_a_verified_context_link():
    inputs, source = condition_fixture()
    source["tables"][0]["observations"][0]["value_raw"] = "999"
    source["tables"][0]["shadow_observations"][0]["property_name_raw"] = "wrong_property"
    ledger = build_raw_candidate_ledger(inputs["stage0"], inputs["stage2"], inputs["stage3"], stage4t=source)
    assert all(r["source_context"] is None for r in ledger["records"])
    assert ledger["counts"]["source_context_expression_count"] == 0


def test_stage4r_source_context_is_retained_alongside_original_context():
    inputs, source = condition_fixture()
    raw = source["tables"][0]["observations"][0]
    raw["evidence"] = [{"block_id": "T1", "table_locator": {
        "cell_id": raw["cell_id"], "row_index": 1, "column_index": 1, "cell_value": "120"}}]
    raw["measurement_context"] = {"other_conditions": {"dose": "8.1 kGy"}}
    ledger = build_raw_candidate_ledger(inputs["stage0"], inputs["stage2"], inputs["stage3"],
        stage4r={"document_id": "test", "specialized_property_observations": [raw]})
    row = ledger["records"][0]
    assert row["source_context"]["condition_axes"][0]["value_raw"] == "8.1"
    assert row["effective_candidate"]["measurement_context"] == raw["measurement_context"]
    assert row["source_context"]["declared_context_comparison"] == "needs_review"
    assert row["source_context"]["declared_context_audit"]["axes"][0]["numeric_comparison"] == "equal"
