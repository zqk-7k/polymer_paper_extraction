from __future__ import annotations

import json
from pathlib import Path

from schema.polymer_schema import Stage0Element
from stages.stage4t_table_survey import (
    render_markdown,
    survey_batch,
    survey_table,
)
from stages.table_grid import parse_table_cells


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


def test_survey_detects_row_sample_axis_and_header_units() -> None:
    report = survey_table(_table(
        "T_test_1",
        "<table><tr><td>Polymer</td><td>Tg (°C)</td><td>Yield (%)</td></tr>"
        "<tr><td>PC-1</td><td>120</td><td>87.2</td></tr>"
        "<tr><td>PC-2</td><td>130</td><td>86.5</td></tr></table>",
    ))

    assert report["direction"] == "row_samples"
    assert report["sample_axis"] == "row"
    assert report["unit_location"] == "header"
    assert report["header_level_count"] == 1
    assert report["numeric_cell_count"] == 4
    assert report["property_column_candidates"]


def test_survey_detects_multilevel_header_and_variable_spans() -> None:
    report = survey_table(_table(
        "T_test_2",
        "<table><tr><td rowspan='2'>Polymer</td><td colspan='2'>Thermal</td></tr>"
        "<tr><td>Td10% (°C)</td><td>RM (%)</td></tr>"
        "<tr><td>PC-1</td><td>403</td><td>37.8</td></tr></table>",
    ))

    assert report["header_level_count"] == 2
    assert report["direction"] == "row_samples"
    assert report["unit_location"] == "header"
    assert report["property_column_candidates"]


def test_survey_detects_column_sample_pairs() -> None:
    report = survey_table(_table(
        "T_test_column",
        "<table><tr><td></td><td>HS</td><td>HI</td><td>HT</td></tr>"
        "<tr><td>Tm (°C)</td><td>103</td><td>—</td><td>156</td></tr>"
        "<tr><td>ΔHm (J/g)</td><td>36.0</td><td>—</td><td>12.0</td></tr></table>",
    ))

    assert report["direction"] == "column_samples"
    assert report["sample_axis"] == "column"


def test_empty_corner_column_header_overrides_weak_row_guess() -> None:
    report = survey_table(_table(
        "T_test_column_weak_row",
        "<table><tr><td></td><td>HS</td><td>HI</td><td>HT</td></tr>"
        "<tr><td>$T_{exo}$ (°C)</td><td>165</td><td>145</td><td>155</td></tr>"
        "<tr><td>$\\Delta H_{exo}$ (J/g)</td><td>450</td><td>210</td><td>—</td></tr></table>",
    ))

    assert report["direction"] == "column_samples"
    assert report["sample_axis"] == "column"


def test_survey_detects_repeated_sample_property_groups_as_mixed() -> None:
    report = survey_table(_table(
        "T_test_mixed",
        "<table><tr><th>Polymer</th><th>λmax (nm)</th><th>Polymer</th><th>λmax (nm)</th></tr>"
        "<tr><td>P-1</td><td>401</td><td>P-2</td><td>384</td></tr></table>",
    ))

    assert report["direction"] == "mixed"
    assert report["sample_axis"] == "both"


def test_survey_flags_numeric_table_without_property_or_sample_axis() -> None:
    report = survey_table(_table(
        "T_test_3",
        "<table><tr><td>A</td><td>B</td></tr>"
        "<tr><td>1</td><td>2</td></tr></table>",
    ))

    assert report["direction"] == "unknown"
    assert "numeric_table_without_property_columns" in report["warnings"]
    assert "numeric_table_without_sample_axis" in report["warnings"]


def test_survey_batch_and_markdown_are_stable(tmp_path: Path) -> None:
    document = {
        "schema_version": "1.1",
        "source_document_schema_version": "test",
        "document_id": "reference_no_0000001",
        "paper": {
            "ref_no": "reference_no_0000001",
            "pdf_filename": "reference_no_0000001.pdf",
            "source_pdf_path": "source/reference_no_0000001.pdf",
            "organized_pdf_path": "organized/reference_no_0000001.pdf",
            "title": None,
            "doi": None,
            "metadata_status": "partial",
            "metadata_extraction": {},
        },
        "source_files": {},
        "ocr": {},
        "elements": [{
            "block_id": "T_1_1",
            "type": "table",
            "page": 1,
            "source_block_index": 0,
            "table_body": "<table><tr><td>Sample</td><td>Tg (°C)</td></tr>"
            "<tr><td>A-1</td><td>100</td></tr></table>",
        }],
        "warnings": [],
    }
    doc_dir = tmp_path / "reference_no_0000001"
    doc_dir.mkdir()
    (doc_dir / "stage0_blocks.json").write_text(
        json.dumps(document), encoding="utf-8"
    )

    report = survey_batch(tmp_path)
    markdown = render_markdown(report)

    assert report["document_count"] == 1
    assert report["table_count"] == 1
    assert "T_1_1" in markdown
    assert "row_samples" in markdown
