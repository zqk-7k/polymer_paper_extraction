from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from llm_client import (
    LLMCallCost,
    LLMCallRecord,
    LLMJSONResponse,
    LLMRawResponse,
    LLMRequestError,
    LLMTokenUsage,
    ParsedJSON,
)
from stages.stage4t_llm_interpreter import (
    approved_interpretation_tables,
    interpret_table_with_llm,
)
from stages.stage4t_table_survey import survey_table
from stages.table_grid import parse_table_cells
from schema.polymer_schema import Stage0Element


def _table() -> Stage0Element:
    body = (
        "<table><tr><td>Properties</td><td>P-1</td></tr>"
        "<tr><td>Tg (°C)</td><td>120</td></tr></table>"
    )
    return Stage0Element(
        block_id="T_1",
        type="table",
        page=1,
        source_block_index=0,
        table_body=body,
        table_cells=parse_table_cells(body, "T_1"),
    )


def _data() -> dict:
    return {
        "schema_version": "stage4t_table_interpretation_schema.v1",
        "table_id": "T_1",
        "direction": "column_samples",
        "axis_role": "named_sample",
        "sample_binding_strategy": "direct_column",
        "header_assignments": [
            {
                "source_cell_ids": ["T_1:r0000:c0001"],
                "role": "sample_axis",
                "normalized_name": "polymer_sample",
                "semantic_label": None,
                "measurement_role": None,
                "confidence": 0.99,
                "reason": "sample column",
            },
            {
                "source_cell_ids": ["T_1:r0001:c0000"],
                "role": "official_property",
                "normalized_name": "glass_transition_temperature",
                "semantic_label": None,
                "measurement_role": None,
                "confidence": 0.99,
                "reason": "Tg row",
            },
        ],
        "requires_human_review": False,
        "warnings": [],
    }


def _cost() -> LLMCallCost:
    return LLMCallCost(
        currency="CNY",
        input_per_million=Decimal("1"),
        output_per_million=Decimal("2"),
        input_cost=Decimal("0.001"),
        output_cost=Decimal("0.002"),
        total_cost=Decimal("0.003"),
    )


@dataclass
class FakeClient:
    response: LLMJSONResponse | None = None
    error: Exception | None = None

    def __post_init__(self) -> None:
        usage = LLMTokenUsage(input_tokens=1000, output_tokens=100)
        self.call_history = [LLMCallRecord(
            provider="test",
            model="test-model",
            usage=usage,
            cost=_cost(),
        )]
        self.pricing = None
        self.last_raw_response = LLMRawResponse(
            provider="test",
            model="test-model",
            finish_reason="stop",
            content=None,
            usage=usage,
            cost=_cost(),
        )

    def call_json(self, *_args, **_kwargs) -> LLMJSONResponse:
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def _response(*, trailing_text: str = "", data: dict | None = None) -> LLMJSONResponse:
    usage = LLMTokenUsage(input_tokens=1000, output_tokens=100)
    return LLMJSONResponse(
        data=data or _data(),
        provider="test",
        model="test-model",
        usage=usage,
        cost=_cost(),
        parsed_json=ParsedJSON(
            data=data or _data(),
            trailing_text=trailing_text,
            parse_source="raw_decode" if trailing_text else "direct",
        ),
    )


def _run(client: FakeClient) -> dict:
    table = _table()
    return interpret_table_with_llm(
        table,
        survey=survey_table(table),
        shadow={"observations": []},
        client=client,  # type: ignore[arg-type]
    )


def test_interpreter_returns_validated_candidate_only_with_cost() -> None:
    result = _run(FakeClient(response=_response()))

    assert result["status"] == "succeeded"
    assert result["authoritative"] is False
    assert result["publication_status"] == "candidate_only"
    assert result["interpretation"]["table_id"] == "T_1"
    assert result["cost"]["usage"]["input_tokens"] == 1000
    assert result["cost"]["cost"]["total_cost"] == "0.003"


def test_interpreter_falls_back_on_incomplete_trailing_marker() -> None:
    result = _run(FakeClient(response=_response(
        trailing_text="仅保留示例，完整输出需补全。"
    )))

    assert result["status"] == "fallback_candidate_only"
    assert "incomplete_marker" in result["reason"]
    assert "interpretation" not in result


def test_interpreter_does_not_scan_json_data_for_incomplete_markers() -> None:
    data = _data()
    data["warnings"] = ["论文写明完整输出需补全"]

    result = _run(FakeClient(response=_response(data=data)))

    assert result["status"] == "succeeded"


def test_interpreter_falls_back_on_schema_failure() -> None:
    data = _data()
    data["value_raw"] = "120"

    result = _run(FakeClient(response=_response(data=data)))

    assert result["status"] == "fallback_candidate_only"
    assert result["reason"] == "llm_or_schema_failure"
    assert result["error_type"] == "ValidationError"


def test_interpreter_falls_back_on_valid_but_empty_structure() -> None:
    data = _data()
    data["header_assignments"] = []
    data["requires_human_review"] = True
    data["warnings"] = ["unable to interpret"]

    result = _run(FakeClient(response=_response(data=data)))

    assert result["status"] == "fallback_candidate_only"
    assert result["reason"] == "missing_header_assignments"


def test_interpreter_falls_back_on_request_failure_without_raw_content() -> None:
    result = _run(FakeClient(error=LLMRequestError("request failed")))

    assert result["status"] == "fallback_candidate_only"
    assert result["reason"] == "llm_or_schema_failure"
    assert result["raw_response"]["finish_reason"] == "stop"
    assert "content" not in result["raw_response"]


def test_approved_table_allowlist_matches_manual_fixture_scope() -> None:
    assert approved_interpretation_tables() == {
        ("reference_no_0021296", "T_8_91"),
        ("reference_no_0038527", "T_5_69"),
        ("reference_no_0039705", "T_6_84"),
        ("reference_no_0043541", "T_4_49"),
        ("reference_no_0043590", "T_1_19"),
    }
