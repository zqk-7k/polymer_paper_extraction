from __future__ import annotations

from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from agents.specialized_attribution import (
    SemanticAttribution,
    SpecializedAttributionResponse,
    build_agent_input,
    run_attribution_agent,
    select_applicable_memory,
    validate_agent_response,
)
from llm_client import LLMJSONResponse, LLMTokenUsage
from schema.polymer_schema import Stage0Document, Stage0Element
from stages.table_grid import parse_table_cells


def _stage0() -> Stage0Document:
    body = (
        "<table><tr><td>Sample</td><td>d-spacing (Å)</td></tr>"
        "<tr><td>PC-1</td><td>5.13</td></tr></table>"
    )
    table = Stage0Element(
        block_id="T_1",
        type="table",
        page=1,
        source_block_index=1,
        caption="XRD results",
        table_body=body,
        table_cells=parse_table_cells(body, "T_1"),
    )
    return Stage0Document.model_validate({
        "schema_version": "1.1",
        "source_document_schema_version": "1.0",
        "document_id": "reference_no_test",
        "paper": {
            "ref_no": "reference_no_test",
            "pdf_filename": "test.pdf",
            "source_pdf_path": "test.pdf",
            "organized_pdf_path": "test.pdf",
            "metadata_status": "failed",
            "metadata_extraction": {},
        },
        "source_files": {},
        "ocr": {},
        "elements": [{
            "block_id": "P_1",
            "type": "text",
            "section": "Results",
            "text": "The XRD results are summarized in Table 1.",
            "page": 1,
            "source_block_index": 0,
        }, table.model_dump(mode="json")],
        "warnings": [],
    })


def _stage3() -> dict:
    return {"samples": [{
        "sample_id": "s001",
        "sample_label_raw": "PC-1",
        "polymer_name": "polycarbonate",
        "refers_to_entity": "pe001",
    }]}


def _vocabulary() -> dict:
    return {
        "crystallographic_data": {
            "semantic_labels": ["d_spacing", "two_theta"],
            "aliases": ["d-spacing"],
            "variants": ["reported"],
            "value_kinds": ["numeric_scalar"],
            "stages": ["stage4t"],
        }
    }


def _valid_response() -> dict:
    return {
        "schema_version": "specialized_attribution_agent_schema.v1",
        "document_id": "reference_no_test",
        "table_id": "T_1",
        "semantic_assignments": [{
            "source_cell_ids": ["T_1:r0000:c0001"],
            "decision": "specialized",
            "source_field": "crystallographic_data",
            "semantic_label": "d_spacing",
            "variant": "reported",
            "external_semantic_label": None,
            "confidence": 0.98,
            "reason": "explicit d-spacing header",
        }],
        "sample_assignments": [{
            "sample_label_raw": "PC-1",
            "source_cell_ids": ["T_1:r0001:c0000"],
            "status": "matched",
            "sample_id": "s001",
            "entity_id": "pe001",
            "candidate_sample_ids": [],
            "confidence": 0.99,
            "reason": "exact Stage 3 label",
        }],
        "requires_human_review": False,
        "warnings": [],
    }


def test_contract_forbids_values_and_requires_controlled_fields() -> None:
    payload = {
        "source_cell_ids": ["T_1:r0000:c0001"],
        "decision": "specialized",
        "source_field": "crystallographic_data",
        "semantic_label": "d_spacing",
        "confidence": 0.9,
        "reason": "header",
        "value_raw": "5.13",
    }
    with pytest.raises(ValidationError):
        SemanticAttribution.model_validate(payload)


def test_agent_input_redacts_values_and_includes_tools_and_memory() -> None:
    request = build_agent_input(
        _stage0(),
        _stage3(),
        table_id="T_1",
        vocabulary=_vocabulary(),
        approved_memory=[{
            "pattern_id": "xrd",
            "guidance": "d is spacing",
            "positive_cues": ["d-spacing"],
        }],
    )
    by_cell = {item["cell_id"]: item for item in request["table"]["cells"]}
    assert by_cell["T_1:r0001:c0001"]["text"] == "<NUMERIC>"
    assert request["stage3_samples"][0]["sample_id"] == "s001"
    assert request["approved_memory"][0]["pattern_id"] == "xrd"
    assert request["memory_retrieval"][0]["matched_cues"] == ["d-spacing"]
    assert "query_stage3_sample_catalog" in request["tool_trace"]


def test_memory_routing_requires_caption_or_header_cue() -> None:
    selected, audit = select_applicable_memory(
        [{
            "pattern_id": "xrd",
            "guidance": "XRD header rule",
            "positive_cues": ["XRD"],
        }],
        table_input={
            "caption": "Surface properties",
            "cells": [{
                "cell_id": "T_1:r0000:c0000",
                "cell_role": "header",
                "text": "Contact angle",
            }],
        },
    )

    assert selected == []
    assert audit == [{
        "pattern_id": "xrd",
        "selected": False,
        "matched_cues": [],
    }]


def test_validation_rejects_unknown_sample_and_invalid_semantic_pair() -> None:
    request = build_agent_input(
        _stage0(), _stage3(), table_id="T_1", vocabulary=_vocabulary()
    )
    payload = _valid_response()
    payload["sample_assignments"][0]["sample_id"] = "s999"
    with pytest.raises(ValueError, match="未知 sample_id"):
        validate_agent_response(payload, request, _vocabulary())

    payload = _valid_response()
    payload["semantic_assignments"][0]["semantic_label"] = "crystallinity"
    with pytest.raises(ValueError, match="不兼容"):
        validate_agent_response(payload, request, _vocabulary())


@dataclass
class FakeClient:
    responses: list[dict]

    def __post_init__(self) -> None:
        self.call_history = []
        self.pricing = None

    def call_json(self, *_args, **_kwargs) -> LLMJSONResponse:
        return LLMJSONResponse(
            data=self.responses.pop(0),
            provider="test",
            model="test",
            usage=LLMTokenUsage(),
        )


def test_agent_repairs_invalid_first_response_without_publishing() -> None:
    invalid = _valid_response()
    invalid["semantic_assignments"][0]["source_cell_ids"] = ["missing"]
    client = FakeClient([invalid, _valid_response()])

    artifact = run_attribution_agent(
        stage0=_stage0(),
        stage3=_stage3(),
        table_id="T_1",
        vocabulary=_vocabulary(),
        vocabulary_sha256="0" * 64,
        client=client,  # type: ignore[arg-type]
    )

    assert artifact["status"] == "succeeded"
    assert artifact["authoritative"] is False
    assert artifact["publication_status"] == "candidate_only"
    assert artifact["repair_attempts_used"] == 1
    assert artifact["response"]["sample_assignments"][0]["sample_id"] == "s001"


def test_response_schema_contains_no_value_fields() -> None:
    schema_text = str(SpecializedAttributionResponse.model_json_schema())
    assert "value_raw" not in schema_text
    assert "value_min" not in schema_text
