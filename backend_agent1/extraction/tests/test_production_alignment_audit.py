from __future__ import annotations

import json

import pytest

from tools.production_alignment_audit import (
    DEFAULT_BATCH, DEFAULT_REGISTRY, DEFAULT_SCHEMA, DEFAULT_STANDARD,
    audit_record, build_audit, candidate_code, load_registry, unit_match, value_match,
)


def test_value_match_supports_exact_ranges_without_llm():
    expected = {"value_min": 10, "value_max": 12}
    assert value_match(expected, {"value_min": 10.0, "value_max": 12.0})
    assert not value_match(expected, {"value_min": 10, "value_max": 13})


def test_unit_match_canonicalizes_degree_symbols_and_aliases():
    assert unit_match({"reviewed_unit": "c"}, {"unit_raw": "°C"})
    assert unit_match({"reviewed_unit": "degree"}, {"unit_raw": "celsius"})
    assert not unit_match({"reviewed_unit": "%"}, {"unit_raw": "c"})


def test_candidate_code_uses_exact_aliases_only():
    _, aliases = load_registry()
    assert candidate_code({"property_name_normalized": "glass_transition_temperature"}, aliases) == "STD:glass_transition_temperature"
    assert candidate_code({"property_name_normalized": "glass_transition_temperature_extra"}, aliases) is None
    assert candidate_code({"semantic_label": "d_spacing", "property_name_raw": "d-Spacing (Å)"}, aliases) == "STD:lattice_spacing"
    assert candidate_code({"semantic_label": "molecular_weight", "property_name_raw": r"$M_{\\text{w}}$"}, aliases) == "STD:weight_average_molecular_weight"
    assert candidate_code({"semantic_label": "molecular_weight", "property_name_raw": r"$M_{\\text{n}}$"}, aliases) == "STD:number_average_molecular_weight"


def test_standard_sample_sequence_never_resolves_to_stage3_id():
    _, aliases = load_registry()
    expected = {
        "reference_no": "reference_no_test", "standard_record_id": "GT:test:1",
        "article_sample_id": "test-001-001-001", "standard_property_code": "STD:glass_transition_temperature",
        "value_min": 120, "value_max": 120, "reviewed_unit": "c", "mapping_status": "mapped",
    }
    doc = {
        "objects": [{"property_name_normalized": "glass_transition_temperature", "value_min": 120,
                     "value_max": 120, "unit_raw": "C", "sample_id": "s001", "property_id": "p1"}],
        "publication": {"final.json": {"property_observations": [{"property_name_normalized": "glass_transition_temperature", "value_min": 120, "value_max": 120}]},
                         "candidate.json": {}},
        "stage3": {"samples": [{"sample_id": "s001"}]},
    }
    prop, sample = audit_record(expected, doc, aliases)
    assert prop["status"] == "sample_unresolved"
    assert prop["expected_process_sample_id"] is None
    assert prop["sample_exact_match"] is None
    assert sample["resolution_status"] == "unresolved"


@pytest.mark.skipif(not (DEFAULT_STANDARD.exists() and DEFAULT_BATCH.exists()), reason="local project batch not present")
def test_full_audit_is_deterministic_and_complete(tmp_path):
    summary = build_audit(DEFAULT_STANDARD, DEFAULT_BATCH, DEFAULT_REGISTRY, DEFAULT_SCHEMA, tmp_path)
    assert summary["standard_records"] == 1542
    assert summary["standard_documents"] == 29
    assert summary["batch_document_dirs"] == 31
    assert sum(summary["alignment_status_counts"].values()) == 1542
    assert summary["documents_with_missing_required_files"] == 0
    rows = [json.loads(line) for line in (tmp_path / "properties_alignment.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1542
    first = (tmp_path / "properties_alignment.jsonl").read_bytes()
    build_audit(DEFAULT_STANDARD, DEFAULT_BATCH, DEFAULT_REGISTRY, DEFAULT_SCHEMA, tmp_path)
    assert first == (tmp_path / "properties_alignment.jsonl").read_bytes()
