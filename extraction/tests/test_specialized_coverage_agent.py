from __future__ import annotations

import pytest

from agents.specialized_coverage import (
    CoverageDecision,
    SpecializedCoverageResponse,
    _block_text,
    passes_schema_release_gate,
    retrieve_evidence,
    validate_response,
)


VOCABULARY = {
    "solution_viscosity": {
        "semantic_labels": ["solution_viscosity"],
        "aliases": ["intrinsic viscosity"],
        "variants": ["intrinsic"],
    },
    "degree_of_polymerization": {
        "semantic_labels": ["degree_of_polymerization"],
        "aliases": ["degree of polymerization"],
        "variants": ["reported"],
    },
}


def test_table_cells_are_visible_to_retriever() -> None:
    block = {
        "block_id": "T_1",
        "type": "table",
        "caption": "Reported properties",
        "table_body": "<table><tr><td>Intrinsic viscosity</td><td>0.12</td></tr></table>",
        "table_cells": [{"text": "Intrinsic viscosity"}, {"text": "0.12"}],
    }
    evidence, coverage = retrieve_evidence({"elements": [block]}, VOCABULARY, {})
    assert evidence[0]["block_id"] == "T_1"
    assert coverage["solution_viscosity"] == ["T_1"]
    assert "Intrinsic viscosity" in _block_text(block)


def test_evolved_retriever_includes_global_scientific_context() -> None:
    block = {
        "block_id": "P_1",
        "type": "text",
        "section": "Abstract",
        "text": "A new material family was synthesized.",
    }
    base, _ = retrieve_evidence({"elements": [block]}, VOCABULARY, {})
    evolved, _ = retrieve_evidence(
        {"elements": [block]},
        VOCABULARY,
        {},
        include_global_context=True,
    )
    assert base == []
    assert evolved[0]["retrieval_reason"] == "global_scientific_context"


def _request() -> dict:
    return {
        "document_id": "reference_no_test",
        "controlled_vocabulary": VOCABULARY,
        "retrieved_evidence": [{"block_id": "T_1", "text": "Intrinsic viscosity 0.12"}],
        "samples": [{"sample_id": "s001", "refers_to_entity": "pe001"}],
        "polymer_entities": [{"entity_id": "pe001"}],
    }


def _response() -> dict:
    return SpecializedCoverageResponse(
        document_id="reference_no_test",
        decisions=[
            CoverageDecision(
                source_field="solution_viscosity",
                decision="supported",
                semantic_label="solution_viscosity",
                variant="intrinsic",
                observed_text="Intrinsic viscosity 0.12",
                evidence_block_ids=["T_1"],
                sample_id="s001",
                entity_id="pe001",
                subject_resolution="sample",
                confidence=0.95,
                reason="Table row and sample column are explicit.",
            ),
            CoverageDecision(
                source_field="degree_of_polymerization",
                decision="not_found",
                subject_resolution="unresolved",
                confidence=0.9,
                reason="No supporting evidence.",
            ),
        ],
        requires_human_review=False,
    ).model_dump(mode="json")


def test_validator_accepts_evidence_bound_candidate() -> None:
    response = validate_response(_response(), _request())
    assert response.decisions[0].sample_id == "s001"


def test_validator_downgrades_unknown_evidence() -> None:
    response = _response()
    response["decisions"][0]["evidence_block_ids"] = ["T_missing"]
    validated = validate_response(response, _request())
    assert validated.decisions[0].decision == "ambiguous"
    assert validated.requires_human_review


def test_validator_downgrades_nonverbatim_quote() -> None:
    response = _response()
    response["decisions"][0]["observed_text"] = "Intrinsic viscosity 0.99"
    validated = validate_response(response, _request())
    assert validated.decisions[0].decision == "ambiguous"
    assert "verbatim" in validated.decisions[0].reason


def test_validator_fills_omitted_field_as_not_found() -> None:
    response = _response()
    response["decisions"].pop()
    validated = validate_response(response, _request())
    assert len(validated.decisions) == 2
    fallback = next(item for item in validated.decisions if item.source_field == "degree_of_polymerization")
    assert fallback.decision == "not_found"
    assert fallback.confidence == 0


def test_validator_drops_non_supported_candidate_payload() -> None:
    response = _response()
    response["decisions"][1]["semantic_label"] = "degree_of_polymerization"
    validated = validate_response(response, _request())
    assert validated.decisions[1].semantic_label is None
    assert validated.decisions[1].subject_resolution == "unresolved"


def test_numeric_release_gate_rejects_qualitative_molecular_weight() -> None:
    assert not passes_schema_release_gate({
        "decision": "supported",
        "source_field": "average_molecular_weight",
        "observed_text": "high molecular weight polymer",
    })
    assert passes_schema_release_gate({
        "decision": "supported",
        "source_field": "average_molecular_weight",
        "observed_text": "Mw = 42,000 g mol-1",
    })


def test_validator_deduplicates_document_level_field_decisions() -> None:
    response = _response()
    duplicate = dict(response["decisions"][1])
    duplicate["confidence"] = 0.1
    response["decisions"].append(duplicate)
    validated = validate_response(response, _request())
    assert len(validated.decisions) == 2
