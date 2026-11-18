from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import threading
import time
import pytest
from pathlib import Path

from schema.polymer_schema import Stage0Document, Stage0Element
from stages.stage4t_preview_sidecar import (
    _align_interpretation_with_shadow,
    _llm_billing,
    _reusable_interpretation,
    _table_interpretation_context,
    SHADOW_VERSION,
    run_sidecar,
)
from stages.stage4t_llm_interpreter import INTERPRETER_VERSION
from stages.stage4t_table_interpretation import interpretation_contract_hash
from stages.stage4t_interpretation_apply import APPLICATION_VERSION
from stages.table_grid import parse_table_cells


def test_interrupted_table_run_reuses_completed_and_does_not_auto_repeat_unknown(tmp_path, monkeypatch):
    document = _complex_document().model_copy(deep=True)
    first = document.elements[0]
    second = first.model_copy(update={"block_id":"T_2", "source_block_index":1,
        "table_cells":parse_table_cells(first.table_body,"T_2")})
    document.elements = [first,second]
    base = tmp_path / "reference_no_test"
    base.mkdir()
    (base/"stage0_blocks.json").write_text(document.model_dump_json(),encoding="utf-8")
    calls = []
    def response(table):
        return {"status":"succeeded", "llm_call_attempted":True, "authoritative":False,
                "interpretation":{"table_id":table.block_id, "direction":"unknown", "axis_role":"unknown",
                    "sample_binding_strategy":"unknown", "requires_human_review":True, "header_assignments":[]}}
    def interrupted(table, **kwargs):
        calls.append(table.block_id)
        if table.block_id == "T_2":
            raise RuntimeError("simulated process interruption")
        return response(table)
    monkeypatch.setattr("stages.stage4t_preview_sidecar.interpret_table_with_llm", interrupted)
    with pytest.raises(RuntimeError,match="interruption"):
        run_sidecar(input_root=tmp_path,output_root=tmp_path,ref_no="reference_no_test",enable_llm_interpretation=True)
    def resumed(table, **kwargs):
        calls.append(table.block_id)
        return response(table)
    monkeypatch.setattr("stages.stage4t_preview_sidecar.interpret_table_with_llm", resumed)
    path,_ = run_sidecar(input_root=tmp_path,output_root=tmp_path,ref_no="reference_no_test",enable_llm_interpretation=True)
    assert calls == ["T_1","T_2"]
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["interpretation_summary"]["llm_attempt_count"] == 0
    assert saved["interpretations"][1]["reason"] == "request_interrupted_or_unknown"
    path,_ = run_sidecar(input_root=tmp_path,output_root=tmp_path,ref_no="reference_no_test",
                        enable_llm_interpretation=True,retry_failed_tables=True)
    assert calls == ["T_1","T_2","T_2"]
    assert json.loads(path.read_text(encoding="utf-8"))["interpretation_summary"]["llm_attempt_count"] == 1


def test_sidecar_script_imports_from_external_working_directory(
    tmp_path: Path,
) -> None:
    script = Path(__file__).resolve().parents[1] / "stages" / (
        "stage4t_preview_sidecar.py"
    )
    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def _document() -> Stage0Document:
    body = (
        "<table><tr><td>Sample</td><td>Tg (°C)</td></tr>"
        "<tr><td>Sample-A</td><td>120</td></tr></table>"
    )
    table = Stage0Element(
        block_id="T_1",
        type="table",
        page=1,
        source_block_index=0,
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
        "elements": [table.model_dump(mode="json")],
        "warnings": [],
    })


def _complex_document() -> Stage0Document:
    document = _document().model_copy(deep=True)
    body = (
        "<table><tr><td>Properties</td><td>Sample-A</td></tr>"
        "<tr><td>Unknown metric</td><td>120</td></tr></table>"
    )
    table = document.elements[0]
    table.table_body = body
    table.table_cells = parse_table_cells(body, "T_1")
    return document


def test_table_context_collects_adjacent_text_and_footnotes() -> None:
    document = _document().model_copy(deep=True)
    table = document.elements[0]
    document.elements = [
        Stage0Element(
            block_id="P_before",
            type="text",
            page=1,
            source_block_index=0,
            text="The samples were measured by DSC.",
        ),
        table.model_copy(update={"source_block_index": 1}),
        Stage0Element(
            block_id="F_after",
            type="footnote",
            page=1,
            source_block_index=2,
            text="a) Heating rate was 10 K/min.",
        ),
    ]

    context = _table_interpretation_context(document, document.elements[1])

    assert context["preceding_text"][0]["block_id"] == "P_before"
    assert context["footnotes"][0]["block_id"] == "F_after"
    assert context["source_block_ids"] == ["P_before", "F_after"]


def test_sidecar_writes_non_authoritative_document_shadow_and_reuses_cache(
    tmp_path: Path,
) -> None:
    document_dir = tmp_path / "reference_no_test"
    document_dir.mkdir()
    source_path = document_dir / "stage0_blocks.json"
    source_path.write_text(
        _document().model_dump_json(indent=2),
        encoding="utf-8",
    )

    output_path, cached = run_sidecar(
        input_root=tmp_path,
        output_root=tmp_path,
        ref_no="reference_no_test",
    )
    report = json.loads(output_path.read_text(encoding="utf-8"))

    assert cached is False
    assert report["authoritative"] is False
    assert report["candidate_layer"] == "broad"
    assert report["summary"]["observation_count"] == 1
    assert report["summary"]["candidate_class_counts"] == {
        "official_property": 1
    }
    assert report["summary"]["publication_status_counts"] == {
        "candidate_only": 1
    }
    assert report["tables"][0]["context"]["source_block_ids"] == []
    assert report["tables"][0]["shadow_observations"]
    assert report["tables"][0]["llm_enriched_observations"] == []
    assert report["tables"][0]["observations"][0]["sample_label_raw"] == "Sample-A"
    assert report["interpretation_summary"]["routed_table_count"] == 0
    assert report["interpretation_summary"]["candidate_conservation"] == {
        "input_observation_count": 0,
        "output_observation_count": 0,
        "enriched_observation_count": 0,
        "shadow_retained_count": 0,
        "excluded_header_count": 0,
        "unaccounted_count": 0,
        "balanced": True,
    }
    assert report["provenance"]["timing"]["shadow_duration_seconds"] >= 0

    second_path, second_cached = run_sidecar(
        input_root=tmp_path,
        output_root=tmp_path,
        ref_no="reference_no_test",
    )
    assert second_path == output_path
    assert second_cached is True


def test_sidecar_records_disabled_interpretation_for_routed_table(
    tmp_path: Path,
) -> None:
    document_dir = tmp_path / "reference_no_test"
    document_dir.mkdir()
    (document_dir / "stage0_blocks.json").write_text(
        _complex_document().model_dump_json(indent=2),
        encoding="utf-8",
    )

    output_path, _ = run_sidecar(
        input_root=tmp_path,
        output_root=tmp_path,
        ref_no="reference_no_test",
    )
    report = json.loads(output_path.read_text(encoding="utf-8"))

    assert report["llm_interpretation_enabled"] is False
    assert report["interpretations"][0]["status"] == "disabled"
    assert report["interpretations"][0]["publication_status"] == (
        "candidate_only"
    )
    assert report["interpretation_summary"]["routed_table_count"] == 1
    assert report["interpretation_summary"]["status_counts"] == {"disabled": 1}
    assert report["interpretation_summary"]["candidate_conservation"][
        "balanced"
    ] is True
    assert report["interpretations"][0]["duration_seconds"] >= 0


def test_sidecar_passes_shared_context_to_llm_route_and_audit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    document = _complex_document().model_copy(deep=True)
    table = document.elements[0]
    document.elements = [
        Stage0Element(
            block_id="P_before",
            type="text",
            page=1,
            source_block_index=0,
            text="The table reports thermal properties measured by DSC.",
        ),
        table.model_copy(update={"source_block_index": 1}),
    ]
    document_dir = tmp_path / "reference_no_test"
    document_dir.mkdir()
    (document_dir / "stage0_blocks.json").write_text(
        document.model_dump_json(indent=2),
        encoding="utf-8",
    )

    captured: dict[str, object] = {}

    def fake_interpret(table, *, context, **_kwargs):
        captured["table_id"] = table.block_id
        captured["context"] = context
        return {
            "status": "fallback_candidate_only",
            "authoritative": False,
            "publication_status": "candidate_only",
            "llm_call_attempted": True,
            "reason": "test_fallback",
        }

    monkeypatch.setattr(
        "stages.stage4t_preview_sidecar.interpret_table_with_llm",
        fake_interpret,
    )
    output_path, _ = run_sidecar(
        input_root=tmp_path,
        output_root=tmp_path,
        ref_no="reference_no_test",
        enable_llm_interpretation=True,
    )
    report = json.loads(output_path.read_text(encoding="utf-8"))

    assert captured["table_id"] == "T_1"
    assert captured["context"]["source_block_ids"] == ["P_before"]
    assert report["interpretations"][0]["context_source_block_ids"] == [
        "P_before"
    ]


def test_sidecar_table_workers_parallelize_routes_but_keep_output_order(
    tmp_path: Path,
    monkeypatch,
) -> None:
    document = _complex_document().model_copy(deep=True)
    first = document.elements[0].model_copy(update={"source_block_index": 0})
    second = first.model_copy(update={
        "block_id": "T_2",
        "source_block_index": 1,
        "table_cells": parse_table_cells(first.table_body or "", "T_2"),
    })
    document.elements = [first, second]
    document_dir = tmp_path / "reference_no_test"
    document_dir.mkdir()
    (document_dir / "stage0_blocks.json").write_text(
        document.model_dump_json(indent=2),
        encoding="utf-8",
    )

    lock = threading.Lock()
    active = 0
    max_active = 0

    def fake_interpret(table, **_kwargs):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return {
            "status": "fallback_candidate_only",
            "authoritative": False,
            "publication_status": "candidate_only",
            "llm_call_attempted": True,
            "reason": "test_fallback",
        }

    monkeypatch.setattr(
        "stages.stage4t_preview_sidecar.interpret_table_with_llm",
        fake_interpret,
    )
    output_path, _ = run_sidecar(
        input_root=tmp_path,
        output_root=tmp_path,
        ref_no="reference_no_test",
        enable_llm_interpretation=True,
        table_workers=2,
    )
    report = json.loads(output_path.read_text(encoding="utf-8"))

    assert max_active == 2
    assert [
        item["table_id"] for item in report["interpretations"]
    ] == ["T_1", "T_2"]
    assert report["table_workers"] == 2


def test_sidecar_explicit_llm_switch_invalidates_disabled_cache(
    tmp_path: Path,
    monkeypatch,
) -> None:
    document_dir = tmp_path / "reference_no_test"
    document_dir.mkdir()
    (document_dir / "stage0_blocks.json").write_text(
        _complex_document().model_dump_json(indent=2),
        encoding="utf-8",
    )
    first_path, first_cached = run_sidecar(
        input_root=tmp_path,
        output_root=tmp_path,
        ref_no="reference_no_test",
    )
    assert first_cached is False

    calls: list[str] = []

    def fake_interpret(table, **_kwargs):
        calls.append(table.block_id)
        return {
            "status": "succeeded",
            "authoritative": False,
            "publication_status": "candidate_only",
            "llm_call_attempted": True,
            "interpretation": {"table_id": table.block_id},
            "cost": {
                "provider": "test",
                "model": "test-model",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
                "cost": {
                    "currency": "CNY",
                    "input_per_million": "1",
                    "output_per_million": "2",
                    "input_cost": "0.0001",
                    "output_cost": "0.00004",
                    "total_cost": "0.00014",
                },
            },
        }

    monkeypatch.setattr(
        "stages.stage4t_preview_sidecar.interpret_table_with_llm",
        fake_interpret,
    )
    second_path, second_cached = run_sidecar(
        input_root=tmp_path,
        output_root=tmp_path,
        ref_no="reference_no_test",
        enable_llm_interpretation=True,
    )
    report = json.loads(second_path.read_text(encoding="utf-8"))

    assert first_path == second_path
    assert second_cached is False
    assert calls == ["T_1"]
    assert report["llm_interpretation_enabled"] is True
    assert report["llm_interpretation_scope"] == "routed_complex_tables"
    assert report["interpretations"][0]["status"] == "succeeded"
    assert report["provenance"]["call_count"] == 1
    assert report["provenance"]["usage"]["total_tokens"] == 120
    assert report["provenance"]["cost"]["status"] == "calculated"
    assert report["provenance"]["cost"]["total_cost"] == "0.00014"
    assert report["interpretations"][0]["application"]["status"] == "failed_candidate_only"
    assert report["tables"][0]["observations"][0]["value_raw"] == "120"
    assert report["tables"][0]["input_capture_coverage"]["captured"] == 1
    assert any(c["value_raw"] == "120" for c in report["tables"][0]["input_cell_inventory"])


def test_llm_billing_marks_attempt_without_usage_as_unavailable() -> None:
    billing = _llm_billing(
        [{
            "status": "fallback_candidate_only",
            "llm_call_attempted": True,
            "cost": None,
        }],
        enabled=True,
    )

    assert billing["call_count"] == 1
    assert billing["cost"]["status"] == "unavailable"


def test_sidecar_reuses_v03_successful_interpretation_without_llm_call(
    tmp_path: Path,
    monkeypatch,
) -> None:
    document_dir = tmp_path / "reference_no_test"
    document_dir.mkdir()
    source_path = document_dir / "stage0_blocks.json"
    source_path.write_text(
        _complex_document().model_dump_json(indent=2),
        encoding="utf-8",
    )
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text("{}\n", encoding="utf-8")
    interpretation = {
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
                "reason": "Sample-A is the column subject.",
            },
            {
                "source_cell_ids": ["T_1:r0001:c0000"],
                "role": "material_characteristic",
                "normalized_name": None,
                "semantic_label": "unknown_metric",
                "measurement_role": None,
                "confidence": 0.95,
                "reason": "The row names the measured characteristic.",
            },
        ],
        "requires_human_review": False,
        "warnings": [],
    }
    old_sidecar = {
        "sidecar_schema_version": "stage4t_preview_sidecar.v0.3",
        "shadow_version": SHADOW_VERSION,
        "llm_interpretation_enabled": True,
        "llm_interpreter_version": INTERPRETER_VERSION,
        "interpretation_contract_sha256": interpretation_contract_hash(),
        "interpretations": [{
            "table_id": "T_1",
            "status": "succeeded",
            "llm_call_attempted": True,
            "interpretation": interpretation,
            "publication_status": "candidate_only",
        }],
        "provenance": {
            "subject_input_hashes": {"stage2_entities.json": None, "stage3_process.json": None},
            "stage0_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        },
    }
    (document_dir / "stage4t_shadow.json").write_text(
        json.dumps(old_sidecar),
        encoding="utf-8",
    )

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("旧成功 interpretation 不应触发远程模型")

    monkeypatch.setattr(
        "stages.stage4t_preview_sidecar.interpret_table_with_llm",
        fail_if_called,
    )
    output_path, cached = run_sidecar(
        input_root=tmp_path,
        output_root=tmp_path,
        ref_no="reference_no_test",
        enable_llm_interpretation=True,
        config_path=config_path,
    )
    report = json.loads(output_path.read_text(encoding="utf-8"))

    assert cached is False
    assert report["sidecar_schema_version"] == "stage4t_preview_sidecar.v0.6"
    assert report["interpretation_application_version"] == APPLICATION_VERSION
    assert report["interpretations"][0]["reused_from_sidecar"] is True
    assert report["provenance"]["call_count"] == 0
    candidate = report["tables"][0]["observations"][0]
    assert candidate["semantic_label"] == "unknown_metric"
    assert candidate["sample_label_raw"] == "Sample-A"
    assert candidate["publication_gate"]["status"] == "candidate_only"
    assert len(report["tables"][0]["rule_observations"]) == 1


def test_sidecar_does_not_reuse_interpretation_from_other_shadow_version() -> None:
    cached = {
        "shadow_version": "0.5.0",
        "llm_interpretation_enabled": True,
        "llm_interpreter_version": INTERPRETER_VERSION,
        "interpretation_contract_sha256": interpretation_contract_hash(),
        "provenance": {"stage0_sha256": "source", "config_sha256": "config"},
        "interpretations": [{
            "table_id": "T_1",
            "status": "succeeded",
            "interpretation": {},
        }],
    }

    assert _reusable_interpretation(
        cached,
        table_id="T_1",
        shadow_version=SHADOW_VERSION,
        source_sha256="source",
        config_sha256="config",
    ) is None


def test_minor_shadow_metadata_upgrade_reuses_same_source_interpretation() -> None:
    cached = {
        "shadow_version": "0.6.0",
        "llm_interpretation_enabled": True,
        "llm_interpreter_version": INTERPRETER_VERSION,
        "interpretation_contract_sha256": interpretation_contract_hash(),
        "provenance": {"stage0_sha256": "source", "config_sha256": "config"},
        "interpretations": [{
            "table_id": "T_1",
            "status": "succeeded",
            "interpretation": {"table_id": "T_1"},
        }],
    }

    reused = _reusable_interpretation(
        cached,
        table_id="T_1",
        shadow_version="0.6.5",
        source_sha256="source",
        config_sha256="config",
    )

    assert reused is not None
    assert reused["reused_from_sidecar"] is True
    assert reused["llm_call_attempted"] is False


def test_cached_interpretation_aligns_with_grouped_shadow_axis() -> None:
    result = {
        "status": "succeeded",
        "interpretation": {
            "table_id": "T_1",
            "direction": "column_samples",
            "axis_role": "named_sample",
            "sample_binding_strategy": "grouped_columns",
            "header_assignments": [],
            "requires_human_review": True,
            "warnings": [],
        },
    }

    aligned = _align_interpretation_with_shadow(
        result,
        {"direction": "column_samples", "axis_role": "grouped_sample"},
    )

    assert aligned["interpretation"]["axis_role"] == "grouped_sample"
    assert aligned["interpretation"]["sample_binding_strategy"] == "grouped_columns"
    assert aligned["rule_adjustments"][0]["code"] == (
        "shadow_grouped_sample_alignment"
    )


def test_sidecar_rejects_old_semantic_contract():
    cached = {"shadow_version": SHADOW_VERSION, "llm_interpretation_enabled": True,
              "llm_interpreter_version": INTERPRETER_VERSION,
              "interpretation_contract_sha256": "old_prompt_or_catalog",
              "provenance": {"stage0_sha256": "source", "config_sha256": "config"},
              "interpretations": [{"table_id": "T", "status": "succeeded", "interpretation": {}}]}
    assert _reusable_interpretation(cached, table_id="T", shadow_version=SHADOW_VERSION,
                                    source_sha256="source", config_sha256="config") is None
