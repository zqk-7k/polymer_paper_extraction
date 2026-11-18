from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from llm_client import LLMJSONResponse, LLMTokenUsage, ParsedJSON
from stages.sample_catalog import build_catalog, digest, normalize_label, resolve_labels
from stages.sample_binding import BindingReview, build_packet, collect_candidates, deterministic_review, validate_review
from tools.review_sample_binding_llm import process_document, review_packet, render_prompt


def fixture(body=None, labels=("A", "B"), value="120", row=1, col=1):
    body = body or "<table><tr><th>Sample</th><th>Tg (°C)</th></tr><tr><td>A</td><td>120</td></tr><tr><td>B</td><td>120</td></tr></table>"
    stage0 = {"document_id": "reference_no_test", "elements": [{"block_id": "T1", "type": "table", "table_body": body, "source_block_index": 0, "page": 0}]}
    stage3 = {"document_id": "reference_no_test", "samples": [{"sample_id": f"s{i:03}", "sample_kind": "synthesis_batch", "polymer_name": label, "sample_label_raw": label} for i, label in enumerate(labels, 1)], "process_steps": []}
    candidate = {"observation_id": "o1", "table_id": "T1", "cell_id": f"T1:r{row:04}:c{col:04}", "row_index": row, "column_index": col,
                 "value_raw": value, "unit_raw": "°C", "property_name_raw": "Tg (°C)", "property_name_normalized": "glass_transition_temperature"}
    files = {"stage0_blocks.json": stage0, "stage3_process.json": stage3, "stage4t_shadow.json": {"tables": [{"table_id": "T1", "observations": [candidate]}]}}
    return files


def packet_for(files):
    catalog = build_catalog(files["stage0_blocks.json"], files["stage3_process.json"])
    record = collect_candidates(files, "reference_no_test")[0]
    return build_packet(record, files["stage0_blocks.json"], catalog)


class FakeClient:
    def __init__(self, mutate=None, parsed=None):
        self.calls = 0
        self.mutate = mutate
        self.parsed = parsed

    def call_json(self, prompt, user_message, **kwargs):
        self.calls += 1
        packet = json.loads(user_message)
        review = deterministic_review(packet)
        if self.mutate:
            review = self.mutate(review)
        return LLMJSONResponse(review, "fake", "fake-model", usage=LLMTokenUsage(10, 5), parsed_json=self.parsed)


def test_identity_independent_of_sample_order_and_legacy_ids():
    files = fixture()
    original = build_catalog(files["stage0_blocks.json"], files["stage3_process.json"])
    changed = copy.deepcopy(files["stage3_process.json"])
    changed["samples"].reverse()
    for i, s in enumerate(changed["samples"], 10):
        s["sample_id"] = f"s{i:03}"
    rebuilt = build_catalog(files["stage0_blocks.json"], changed)
    assert original["catalog_sha256"] == rebuilt["catalog_sha256"]
    assert original["legacy_mapping"] != rebuilt["legacy_mapping"]
    assert normalize_label("A/B") != normalize_label("AB")


def test_family_members_have_distinct_id_and_family_is_not_concrete():
    files = fixture(labels=("PI-1 to PI-7",), body="<table><tr><th>Sample</th><th>Tg</th></tr><tr><td>PI-1</td><td>120</td></tr><tr><td>PI-2</td><td>121</td></tr></table>")
    catalog = build_catalog(files["stage0_blocks.json"], files["stage3_process.json"])
    first, second = [resolve_labels([s], catalog) for s in ("PI-1", "PI-2")]
    assert first["sample_id"] != second["sample_id"]
    assert resolve_labels(["PI-1 to PI-7"], catalog)["sample_binding_status"] == "group_only"
    assert resolve_labels(["PI-3"], catalog)["sample_binding_status"] == "unresolved"


def test_catalog_exposes_auditable_binding_status_without_breaking_legacy_status():
    files = fixture(labels=("PI-1", "PI-2"), body="<table><tr><th>Sample</th><th>Tg</th></tr><tr><td>PI-1</td><td>120</td></tr><tr><td>PI-2</td><td>121</td></tr></table>")
    catalog = build_catalog(files["stage0_blocks.json"], files["stage3_process.json"])

    resolved = resolve_labels(["PI-1"], catalog)
    unresolved = resolve_labels(["PI-3"], catalog)

    assert resolved["binding_status"] == "resolved"
    assert resolved["binding_basis"] == "exact_or_alias_label"
    assert unresolved["binding_status"] == "unbound"
    assert unresolved["binding_basis"] == "no_unique_label_evidence"


def test_same_label_different_sources_entities_or_batches_are_not_merged():
    files = fixture(labels=("A", "A"))
    samples = files["stage3_process.json"]["samples"]
    for s, entity in zip(samples, ("pe001", "pe002")):
        s["refers_to_entity"] = entity
    catalog = build_catalog(files["stage0_blocks.json"], files["stage3_process.json"])
    resolution = resolve_labels(["A"], catalog)
    assert resolution["binding_status"] == "ambiguous"
    assert resolution["entity_id"] is None
    assert len(resolution["sample_candidate_ids"]) == 2
    samples[1]["refers_to_entity"] = "pe001"
    samples[1]["evidence"] = {"block_id": "T1", "source_sentence": "separate batch A"}
    resolution = resolve_labels(["A"], build_catalog(files["stage0_blocks.json"], files["stage3_process.json"]))
    assert resolution["binding_status"] == "entity_confirmed_sample_ambiguous"
    assert resolution["entity_id"] == "pe001"
    assert resolution["sample_id"] is None
    assert resolution["sample_binding_status"] == "ambiguous"


def test_indistinguishable_stage3_samples_keep_distinct_ids_and_require_review():
    files = fixture(labels=("A", "A", "A"))
    catalog = build_catalog(files["stage0_blocks.json"], files["stage3_process.json"])
    resolution = resolve_labels(["A"], catalog)
    assert len(resolution["sample_candidate_ids"]) == 3
    assert resolution["sample_id"] is None
    assert all(len(v) == 1 for v in catalog["legacy_mapping"].values())
    files["stage3_process.json"]["samples"].reverse()
    reversed_catalog = build_catalog(files["stage0_blocks.json"], files["stage3_process.json"])
    assert catalog["catalog_sha256"] == reversed_catalog["catalog_sha256"]


@pytest.mark.parametrize("body,row,col", [
    (None, 1, 1),
    ("<table><tr><th>Property</th><th>A</th><th>B</th></tr><tr><td>Tg (°C)</td><td>120</td><td>120</td></tr></table>", 1, 1),
    ("<table><tr><th>Sample</th><th>Tg (°C)</th></tr><tr><td rowspan='2'>A</td><td>121</td></tr><tr><td>120</td></tr></table>", 2, 1),
])
def test_row_column_and_rowspan_axes(body, row, col):
    packet = packet_for(fixture(body=body, row=row, col=col))
    checked = validate_review(deterministic_review(packet), packet)
    assert checked["reasoning_status"] == "accepted", checked
    assert checked["sample_label_observed"] == "A"


def test_full_width_group_row_propagates_to_numeric_rows():
    body = "<table><tr><th>Dose</th><th>Tg (°C)</th></tr><tr><td colspan='2'>Polymer A</td></tr><tr><td>2</td><td>120</td></tr></table>"
    files = fixture(body=body, labels=("Polymer A",), value="120", row=2, col=1)
    packet = packet_for(files)
    path = packet["evidence_paths"][0]
    assert path["group_row_cell_ids"] == ["T1:r0001:c0000"]
    assert path["group_row_cell_ids"][0] in path["axis_cell_ids"]
    assert packet["deterministic_binding"]["sample_binding_status"] == "resolved"
    checked = validate_review(deterministic_review(packet), packet)
    assert checked["reasoning_status"] == "accepted", checked
    assert checked["selected_sample_id"] == packet["deterministic_binding"]["sample_id"]


def test_same_value_for_multiple_samples_does_not_bind_by_value_order():
    files = fixture()
    item = files["stage4t_shadow.json"]["tables"][0]["observations"][0]
    for key in ("cell_id", "row_index", "column_index"):
        del item[key]
    packet = packet_for(files)
    assert packet["deterministic_binding"]["sample_id"] is None
    assert "value_location_ambiguous" in packet["failure_reasons"]


def test_multiple_axis_labels_remain_ambiguous_even_if_model_selects_one():
    files = fixture(body="<table><tr><th>Sample</th><th>Other sample</th><th>Tg</th></tr><tr><td>A</td><td>B</td><td>120</td></tr></table>", col=2)
    packet = packet_for(files)
    review = deterministic_review(packet)
    review.update(reasoning_status="accepted", selected_sample_id=packet["stage3_samples"][0]["sample_id"], sample_label_observed="A", source_quote="A")
    assert validate_review(review, packet)["reasoning_status"] == "not_verifiable"


@pytest.mark.parametrize("patch,error", [
    ({"source_quote": "A ... 120"}, "source_quote_not_verbatim"),
    ({"evidence_ids": ["missing"]}, "evidence_id_missing"),
    ({"selected_sample_id": "sample_invented"}, "unknown_sample_id"),
    ({"reasoning_status": "certain"}, "invalid_review_schema"),
    ({"value_raw": "999"}, "invalid_review_schema"),
    ({"property_id": "another"}, "review_identity_mismatch"),
])
def test_invalid_review_never_accepted(patch, error):
    packet = packet_for(fixture())
    result = validate_review({**deterministic_review(packet), **patch}, packet)
    assert result["reasoning_status"] == "not_verifiable"
    assert error in result["validation_errors"]


@pytest.mark.parametrize("header,context,code", [("Tg DC", {"method": "AC"}, "ac_dc_conflict"), ("Tg wet", {"state": "dry"}, "dry_wet_conflict"), ("Tg at 50 °C", {"temperature": "25 °C"}, "temperature_conflict"), ("Tg at 1 Hz", {"frequency": "2 Hz"}, "frequency_conflict")])
def test_condition_conflicts(header, context, code):
    files = fixture(body=f"<table><tr><th>Sample</th><th>{header}</th></tr><tr><td>A</td><td>120</td></tr></table>")
    files["stage4t_shadow.json"]["tables"][0]["observations"][0]["measurement_context"] = context
    packet = packet_for(files)
    checked = validate_review(deterministic_review(packet), packet)
    assert code in checked["validation_errors"]


def test_image_only_cannot_confirm_binding():
    files = fixture()
    files["stage0_blocks.json"]["elements"] = [{"block_id": "T1", "type": "image", "caption": "A Tg 120", "source_block_index": 0, "page": 0}]
    packet = packet_for(files)
    checked = validate_review(deterministic_review(packet), packet)
    assert checked["reasoning_status"] == "not_verifiable"


def test_fake_llm_cache_and_invalidation(tmp_path):
    packet = packet_for(fixture())
    client = FakeClient()
    kwargs = dict(client=client, execute=True, cache_dir=tmp_path, config_hash="config1", prompt=render_prompt(), force_llm=True)
    first = review_packet(packet, **kwargs)
    second = review_packet(packet, **kwargs)
    assert first["source_reasoning_status"] == "accepted"
    assert second["cache_hit_count"] == 1 and client.calls == 1
    changed = copy.deepcopy(packet)
    changed["input_sha256"] = "changed"
    review_packet(changed, **kwargs)
    assert client.calls == 2
    review_packet(packet, **{**kwargs, "config_hash": "config2"})
    assert client.calls == 3


def test_markdown_response_is_rejected(tmp_path):
    packet = packet_for(fixture())
    client = FakeClient(parsed=ParsedJSON({}, parse_source="fence[0]"))
    result = review_packet(packet, client=client, execute=True, cache_dir=tmp_path, config_hash="c", prompt="p", force_llm=True)
    assert result["source_reasoning_status"] == "not_verifiable"
    assert not list(tmp_path.glob("*.json"))


def test_dry_run_retains_shadow_values_and_original_files(tmp_path):
    source, output = tmp_path / "batch/reference_no_test", tmp_path / "reviews/reference_no_test"
    source.mkdir(parents=True)
    files = fixture()
    for name, data in files.items():
        (source / name).write_text(json.dumps(data), encoding="utf-8")
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    summary = process_document(source, output)
    assert summary["candidate_count"] == summary["value_retained_count"] == 1
    assert summary["request_count"] == 0
    assert before == {p.name: p.read_bytes() for p in source.iterdir()}
    with pytest.raises(ValueError):
        process_document(source, source)


def test_candidate_reorder_preserves_packets_and_verdicts():
    files = fixture()
    observations = files["stage4t_shadow.json"]["tables"][0]["observations"]
    observations.append({**observations[0], "observation_id": "o2", "row_index": 2, "cell_id": "T1:r0002:c0001"})
    first = collect_candidates(files, "reference_no_test")
    by_id = {item["property_id"]: item for item in first}
    assert by_id["o1"]["measurement_record"]["source_cell_ids"] == ["T1:r0001:c0001"]
    assert by_id["o2"]["measurement_record"]["source_cell_ids"] == ["T1:r0002:c0001"]
    assert all(item["measurement_record"]["source_stage"] == "stage4t" for item in first)
    observations.reverse()
    assert first == collect_candidates(files, "reference_no_test")


def test_deterministic_review_conforms_to_response_schema():
    packet = packet_for(fixture())
    response = deterministic_review(packet)
    BindingReview.model_validate(response)
    assert "binding_status" not in response
    assert validate_review(response, packet)["binding_status"] == "resolved"


def test_subnumber_and_wrong_property_cannot_confirm():
    packet = packet_for(fixture(value="1"))
    assert "value_not_in_target_cell" in packet["failure_reasons"]
    files = fixture()
    item = files["stage4t_shadow.json"]["tables"][0]["observations"][0]
    item.update(property_name_raw="Tm", property_name_normalized="melting_temperature")
    packet = packet_for(files)
    assert "property_evidence_path_missing" in validate_review(deterministic_review(packet), packet)["validation_errors"]


def test_blank_row_requires_semantic_review_not_automatic_fill():
    packet = packet_for(fixture(body="<table><tr><th>Sample</th><th>Tg</th></tr><tr><td>A</td><td>121</td></tr><tr><td></td><td>120</td></tr></table>", row=2))
    assert packet["deterministic_binding"]["sample_binding_status"] == "unresolved"
    sample = next(s for s in packet["stage3_samples"] if s["sample_label_primary"] == "A")
    response = {**deterministic_review(packet), "reasoning_status": "accepted", "selected_sample_id": sample["sample_id"], "sample_label_observed": "A", "source_quote": "A",
                "evidence_ids": ["T1:r0001:c0000", "T1:r0002:c0001", "T1:r0000:c0001"]}
    assert validate_review(response, packet)["reasoning_status"] == "accepted"
    assert validate_review(response, packet, allow_inherited=False)["reasoning_status"] == "not_verifiable"


def test_composite_rows_do_not_collapse_distinct_blends_into_parent():
    files = fixture(body="<table><tr><th colspan='2'>Sample</th><th>Tg</th></tr><tr><td rowspan='2'>50/50 Blend</td><td>A/B</td><td>120</td></tr><tr><td>A/C</td><td>120</td></tr></table>", labels=(), col=2)
    first = packet_for(files)
    obs = files["stage4t_shadow.json"]["tables"][0]["observations"][0]
    obs.update(row_index=2, cell_id="T1:r0002:c0002")
    second = packet_for(files)
    assert first["deterministic_binding"]["sample_id"] != second["deterministic_binding"]["sample_id"]
    assert first["deterministic_binding"]["observed_labels"] == ["50/50 Blend | A/B"]
    assert validate_review(deterministic_review(first), first)["reasoning_status"] == "accepted"
    assert next(s for s in first["stage3_samples"] if s["sample_label_primary"] == "50/50 Blend")["sample_level"] == "sample_family"


def test_caption_only_binding_requires_unique_cited_table_context():
    files = fixture(labels=("A", "B"), body="<table><tr><th>Temperature</th><th>Tg</th></tr><tr><td>25</td><td>120</td></tr></table>")
    files["stage0_blocks.json"]["elements"][0]["caption"] = "Measured properties of A"
    packet = packet_for(files)
    sid = next(s["sample_id"] for s in packet["stage3_samples"] if s["sample_label_primary"] == "A")
    response = {**deterministic_review(packet), "reasoning_status": "accepted", "selected_sample_id": sid,
                "sample_label_observed": "A", "source_quote": "Measured properties of A"}
    response["evidence_ids"].append("T1__caption_0")
    assert validate_review(response, packet)["reasoning_status"] == "accepted"
    assert validate_review(response, packet, allow_inherited=False)["reasoning_status"] == "not_verifiable"
    files["stage0_blocks.json"]["elements"][0]["table_notes"] = ["B was also measured"]
    assert validate_review(response, packet_for(files))["reasoning_status"] == "not_verifiable"


def test_caption_cannot_override_explicit_axis():
    files = fixture()
    files["stage0_blocks.json"]["elements"][0]["caption"] = "Properties of A and B"
    packet = packet_for(files)
    assert validate_review(deterministic_review(packet), packet)["reasoning_status"] == "accepted"
    response = deterministic_review(packet)
    response.update(selected_sample_id=next(s["sample_id"] for s in packet["stage3_samples"] if s["sample_label_primary"] == "B"), sample_label_observed="B", source_quote="Properties of A and B")
    response["evidence_ids"].append("T1__caption_0")
    assert validate_review(response, packet)["reasoning_status"] == "not_verifiable"


def test_note_is_separately_citable_and_cache_survives_zero_request_budget(tmp_path):
    files = fixture()
    files["stage0_blocks.json"]["elements"][0]["content"] = {"table_footnote": ["Measured dry at 25 °C"]}
    packet = packet_for(files)
    assert packet["source_evidence"]["T1__table_footnote_0"]["text"] == "Measured dry at 25 °C"
    client = FakeClient()
    options = dict(client=client, execute=True, force_llm=True, cache_dir=tmp_path, config_hash="test", prompt=render_prompt())
    assert review_packet(packet, **options)["request_count"] == 1
    assert review_packet(packet, request_allowed=False, **options)["cache_hit_count"] == 1
    assert client.calls == 1


def test_stage2_hash_and_lineage_are_part_of_review_input(tmp_path):
    from tools.review_sample_binding_llm import load_document
    files = fixture()
    files["stage2_entities.json"] = {"document_id": "reference_no_test", "polymer_entities": [{"entity_id": "pe001"}]}
    files["stage3_process.json"]["samples"][0]["refers_to_entity"] = "pe001"
    for name, value in files.items():
        (tmp_path / name).write_text(json.dumps(value), encoding="utf-8")
    packet = load_document(tmp_path)[2][0]
    assert packet["stage2_entities"][0]["entity_id"] == "pe001"
    sample_id = next(s["sample_id"] for s in packet["stage3_samples"] if s["sample_label_primary"] == "A")
    assert packet["sample_chains"][sample_id]["entity_ids"] == ["pe001"]
    files["stage2_entities.json"]["polymer_entities"][0]["polymer_name"] = "changed"
    (tmp_path / "stage2_entities.json").write_text(json.dumps(files["stage2_entities.json"]), encoding="utf-8")
    assert load_document(tmp_path)[2][0]["input_sha256"] != packet["input_sha256"]


def test_same_entity_different_irradiation_batch_cannot_be_accepted():
    files = fixture(body="<table><tr><th>Sample</th><th>Dose (kGy)</th><th>Tg</th></tr><tr><td>A</td><td>8.0</td><td>120</td></tr></table>", col=2)
    files["stage3_process.json"]["process_steps"] = [{"step_id": "ps001", "input_sample_ids": [], "output_sample_ids": ["s001"], "parameters": {"dose": "8.5 kGy"}}]
    packet = packet_for(files)
    assert "process_dose_conflict" in validate_review(deterministic_review(packet), packet)["validation_errors"]


def test_stage0_keeps_table_notes_for_downstream_context():
    from schema.polymer_schema import SourceElement, Stage0Element
    from stages.stage0_load_document import _element_payload
    from stages.stage3_sample_process import _element_source_text
    source = SourceElement(block_id="T1", element_type="table", page_id=0, block_index=0,
                           table_body="<table><tr><td>120</td></tr></table>", caption="Properties of A", table_footnote=["A was dried"])
    element = Stage0Element.model_validate(_element_payload(source, element_type="table", section="Results"))
    assert element.table_notes == ["A was dried"]
    assert "Properties of A" in _element_source_text(element)
    assert "A was dried" in _element_source_text(element)


def test_total_budget_is_reserved_across_documents(monkeypatch, tmp_path):
    import sys
    from tools import review_sample_binding_llm as tool
    budgets = []
    def fake_process(source, output, **kwargs):
        budgets.append(kwargs["max_requests"])
        return {"document_id": source.name, "candidate_count": 100, "value_retained_count": 100,
                "request_count": kwargs["max_requests"], "review_status_counts": {}}
    monkeypatch.setattr(tool, "process_document", fake_process)
    monkeypatch.setattr(tool, "load_pipeline_config", lambda path: {})
    monkeypatch.setattr(tool.LLMClient, "from_pipeline_config", lambda **kwargs: FakeClient())
    monkeypatch.setattr(sys, "argv", ["review", "--batch-dir", str(tmp_path / "batch"), "--output-dir", str(tmp_path / "out"),
                                    "--execute", "--max-requests", "12", "--ref-no", "1", "--ref-no", "2", "--ref-no", "3", "--ref-no", "4"])
    assert tool.main() == 0
    assert budgets == [3, 3, 3, 3]


def test_transport_failure_stops_further_requests_but_retains_all_candidates(tmp_path):
    import requests
    from llm_client import LLMRequestError
    class BrokenClient:
        calls = 0
        def call_json(self, *args, **kwargs):
            self.calls += 1
            try:
                raise requests.exceptions.SSLError("secret transport details")
            except requests.exceptions.SSLError as exc:
                raise LLMRequestError("request failed") from exc
    files = fixture()
    observations = files["stage4t_shadow.json"]["tables"][0]["observations"]
    observations.append({**observations[0], "observation_id": "o2", "row_index": 2, "cell_id": "T1:r0002:c0001"})
    source = tmp_path / "source"
    source.mkdir()
    for name, value in files.items():
        (source / name).write_text(json.dumps(value), encoding="utf8")
    client = BrokenClient()
    result = process_document(source, tmp_path / "review", execute=True, client=client, positive_samples=2)
    assert client.calls == result["request_count"] == result["api_failure_count"] == 1
    assert result["api_blocked"]
    assert result["value_retained_count"] == 2
    rows = [json.loads(line) for line in (tmp_path / "review/source_reasoning_review.jsonl").read_text().splitlines()]
    assert rows[0]["api_error_category"] == "SSLError"
    assert rows[1]["validated_review"]["validation_errors"] == ["api_circuit_open"]
    assert "secret transport" not in json.dumps(rows)


def test_semantic_failure_is_not_an_api_failure():
    from tools.review_sample_binding_llm import api_failure_details
    assert api_failure_details(ValueError("sample binding mismatch")) == {"api_failure": False}


def test_api_failure_returns_nonzero_and_does_not_start_other_documents(monkeypatch, tmp_path):
    import sys
    from tools import review_sample_binding_llm as tool
    started = []
    def fake_process(source, output, **kwargs):
        started.append(source.name)
        return {"document_id": source.name, "candidate_count": 100, "value_retained_count": 100,
                "request_count": 1, "review_status_counts": {}, "api_blocked": True}
    monkeypatch.setattr(tool, "process_document", fake_process)
    monkeypatch.setattr(tool, "load_pipeline_config", lambda path: {})
    monkeypatch.setattr(tool.LLMClient, "from_pipeline_config", lambda **kwargs: FakeClient())
    monkeypatch.setattr(sys, "argv", ["review", "--batch-dir", str(tmp_path / "batch"), "--output-dir", str(tmp_path / "out"),
                                    "--execute", "--ref-no", "1", "--ref-no", "2"])
    assert tool.main() == 1
    assert started == ["reference_no_1"]
    summary = json.loads((tmp_path / "out/sample_binding_reasoning_summary.json").read_text())
    assert summary["not_started_documents"] == ["reference_no_2"]
def test_article_alias_does_not_match_polymer_prefix_or_longer_code():
    from stages.sample_binding import _label_in_text
    assert not _label_in_text("IZO-3", "PIZO-3 homopolymer")
    assert not _label_in_text("IZO-3", "IZO-30")
    assert _label_in_text("IZO-3", "Monomer IZO-3 (Table 1)")
    assert _label_in_text("IZO-3", "IZO–3")


@pytest.mark.parametrize("source_label", ["PIZO-3", "IZO-30"])
def test_review_rejects_monomer_alias_on_a_different_material_axis(source_label):
    files = fixture(body=f"<table><tr><th>Sample</th><th>Tg (°C)</th></tr><tr><td>{source_label}</td><td>120</td></tr></table>", labels=())
    packet = packet_for(files)
    response = deterministic_review(packet)
    response.update(selected_sample_id=None, article_sample_key="proposed-key",
                    sample_label_observed_exact="IZO-3", source_quote="120", reasoning_status="accepted")
    result = validate_review(response, packet)
    assert not result["validation_passed"]
    assert "article_sample_evidence_path_missing" in result["validation_errors"]
