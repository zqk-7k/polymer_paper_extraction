from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from prompt_loader import PromptLoader
from schema.polymer_schema import Stage0Document, Stage0Element
from stages.stage4t_table_interpretation import (
    Stage4TTableInterpretation,
    build_interpretation_input,
    interpretation_route_reasons,
    normalize_interpretation_response,
    render_interpretation_prompt,
    validate_interpretation,
)
from stages.stage4t_table_property import shadow_extract_table
from stages.stage4t_table_survey import survey_table
from stages.table_grid import parse_table_cells


TEST_ROOT = Path(__file__).parent
PROJECT_ROOT = TEST_ROOT.parents[1]
BATCH_ROOT = PROJECT_ROOT / "batch_results" / "demo20_preview_final_20260812"


def _table(table_id: str, body: str, *, caption: str | None = None) -> Stage0Element:
    return Stage0Element(
        block_id=table_id,
        type="table",
        page=1,
        source_block_index=0,
        caption=caption,
        table_body=body,
        table_cells=parse_table_cells(body, table_id),
    )


def _valid_interpretation(table_id: str, cell_id: str) -> dict:
    return {
        "schema_version": "stage4t_table_interpretation_schema.v1",
        "table_id": table_id,
        "direction": "row_samples",
        "axis_role": "named_sample",
        "sample_binding_strategy": "direct_row",
        "header_assignments": [{
            "source_cell_ids": [cell_id],
            "role": "official_property",
            "normalized_name": "glass_transition_temperature",
            "semantic_label": None,
            "measurement_role": None,
            "confidence": 0.95,
            "reason": "Tg header",
        }],
        "requires_human_review": False,
        "warnings": [],
    }


def test_interpretation_output_schema_forbids_value_fields() -> None:
    payload = _valid_interpretation("T_1", "T_1:r0000:c0001")
    payload["value_raw"] = "120"

    with pytest.raises(ValidationError):
        Stage4TTableInterpretation.model_validate(payload)

    schema = Stage4TTableInterpretation.model_json_schema()
    assert "value_raw" not in schema["properties"]
    assert "value" not in schema["properties"]


def test_interpretation_output_rejects_raw_header_as_canonical_name() -> None:
    payload = _valid_interpretation("T_1", "T_1:r0000:c0001")
    payload["header_assignments"][0]["normalized_name"] = "Glass Transition"

    with pytest.raises(ValidationError, match="canonical snake_case"):
        Stage4TTableInterpretation.model_validate(payload)


def test_interpretation_output_requires_named_condition_axis() -> None:
    payload = _valid_interpretation("T_1", "T_1:r0000:c0001")
    payload["header_assignments"][0].update({
        "role": "condition_axis",
        "normalized_name": None,
    })

    with pytest.raises(ValidationError, match="condition_axis 必须给出"):
        Stage4TTableInterpretation.model_validate(payload)


def test_interpretation_response_normalizes_identical_mirrored_semantics() -> None:
    payload = _valid_interpretation("T_1", "T_1:r0000:c0001")
    payload["header_assignments"][0]["semantic_label"] = (
        "glass_transition_temperature"
    )

    normalized = normalize_interpretation_response(payload)
    interpretation = Stage4TTableInterpretation.model_validate(normalized)

    assert interpretation.header_assignments[0].semantic_label is None


def test_interpretation_input_redacts_data_values_but_keeps_structure() -> None:
    table = _table(
        "T_1",
        "<table><tr><td>Sample</td><td>Tg (°C)</td></tr>"
        "<tr><td>P-1</td><td>120 ± 2</td></tr></table>",
    )

    payload = build_interpretation_input(table)
    by_cell = {cell["cell_id"]: cell for cell in payload["cells"]}

    assert by_cell["T_1:r0000:c0001"]["text"] == "Tg (°C)"
    assert by_cell["T_1:r0001:c0000"]["text"] == "P-1"
    assert by_cell["T_1:r0001:c0001"]["text"] == "<NUMERIC_WITH_UNCERTAINTY>"


def test_interpretation_input_keeps_semantic_labels_with_conditions() -> None:
    table = _table(
        "T_1",
        "<table><tr><td>Sample</td><td>HT</td></tr>"
        "<tr><td>E' (GPa) @ 25°C</td><td>0.66</td></tr></table>",
    )

    payload = build_interpretation_input(table)
    by_cell = {cell["cell_id"]: cell for cell in payload["cells"]}

    assert by_cell["T_1:r0001:c0000"]["text"] == "E' (GPa) @ 25°C"
    assert by_cell["T_1:r0001:c0001"]["text"] == "<NUMERIC>"


def test_interpretation_input_redacts_footnoted_numeric_values() -> None:
    table = _table(
        "T_1",
        "<table><tr><td>Sample</td><td>Angle</td></tr>"
        "<tr><td>P-1</td><td>$13^{°b)}$</td></tr></table>",
    )

    payload = build_interpretation_input(table, survey={"header_rows": [0]})
    by_cell = {cell["cell_id"]: cell for cell in payload["cells"]}

    assert by_cell["T_1:r0001:c0001"]["text"] == "<NUMERIC>"


def test_interpretation_input_keeps_spanned_subheaders() -> None:
    table = _table(
        "T_1",
        "<table><tr><td rowspan='2'>Polymer</td>"
        "<td colspan='2'>2 theta</td></tr>"
        "<tr><td>(100)</td><td>(200)</td></tr>"
        "<tr><td>P-1</td><td>4.5</td><td>6.6</td></tr></table>",
    )

    payload = build_interpretation_input(table)
    by_cell = {cell["cell_id"]: cell for cell in payload["cells"]}

    assert by_cell["T_1:r0001:c0001"]["cell_role"] == "header"
    assert by_cell["T_1:r0001:c0001"]["text"] == "(100)"


def test_interpretation_validation_rejects_unknown_cell_reference() -> None:
    table = _table(
        "T_1",
        "<table><tr><td>Sample</td><td>Tg (°C)</td></tr>"
        "<tr><td>P-1</td><td>120</td></tr></table>",
    )
    request = build_interpretation_input(table)
    response = _valid_interpretation("T_1", "T_1:r9999:c9999")

    with pytest.raises(ValueError, match="未知 cell_id"):
        validate_interpretation(response, request)


def test_simple_high_confidence_table_does_not_route_to_llm() -> None:
    table = _table(
        "T_simple",
        "<table><tr><td>Sample</td><td>Tg (°C)</td></tr>"
        "<tr><td>P-1</td><td>120</td></tr></table>",
    )
    survey = survey_table(table)
    shadow = shadow_extract_table(table)

    assert interpretation_route_reasons(survey, shadow, eligible=True) == []


def test_current_semantic_zero_tables_route_to_llm_interpretation() -> None:
    targets = {
        ("reference_no_0021296", "T_8_91"),
        ("reference_no_0038527", "T_5_69"),
        ("reference_no_0039705", "T_6_84"),
        ("reference_no_0043541", "T_4_49"),
        ("reference_no_0043590", "T_1_19"),
    }
    documents: dict[str, Stage0Document] = {}

    for doc_id, table_id in targets:
        if doc_id not in documents:
            documents[doc_id] = Stage0Document.model_validate(json.loads(
                (BATCH_ROOT / doc_id / "stage0_blocks.json").read_text(
                    encoding="utf-8"
                )
            ))
        table = next(
            element
            for element in documents[doc_id].elements
            if element.block_id == table_id
        )
        survey = survey_table(table)
        shadow = shadow_extract_table(table)
        reasons = interpretation_route_reasons(survey, shadow, eligible=True)

        assert "only_unmapped_candidates" in reasons, (doc_id, table_id, reasons)


def test_interpretation_prompt_uses_registered_schema() -> None:
    rendered = render_interpretation_prompt(PromptLoader())

    assert rendered.stage == "stage4t_table_interpretation"
    assert rendered.output_schema_version == "stage4t_table_interpretation_schema.v1"
    assert "只解释结构" in rendered.text
    assert "thermal_decomposition_temperature" in rendered.text
    assert "canonical snake_case" in rendered.text
    assert "所有模式 cell 都必须覆盖" in rendered.text
