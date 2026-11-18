from copy import deepcopy

from stages.sample_catalog import build_catalog, sample_review_hash, digest
from stages.source_measurement_context import table_review_hash
from stages.publication_checks import audit_context, check_publication_source
from tests.test_publication_checks import source_fixture


def fixture():
    payload, inputs = source_fixture()
    source, process = inputs["stage0"], inputs["stage3"]
    source["elements"][0]["table_body"] = '<table><tr><th>Sample</th><th>Dose/kGy</th><th>Tg (°C)</th></tr><tr><td>A</td><td>8.1</td><td>120</td></tr><tr><td>B</td><td>9.0</td><td>100</td></tr></table>'
    text = "The A gel was prepared at a dose of 8.1 kGy."
    source["elements"].append({"block_id": "P1", "type": "text", "text": text})
    process["samples"][0]["sample_label_raw"] = "A gel"
    review = {"document_id": "test", "legacy_sample_id": "s001", "sample_sha256": sample_review_hash(process["samples"][0]),
              "article_alias": "A", "table_id": "T1", "table_sha256": table_review_hash(source["elements"][0]),
              "sample_axis_cell_id": "T1:r0001:c0000", "preparation_cell_id": "T1:r0001:c0001", "preparation_value_raw": "8.1",
              "definition_evidence": {"block_id": "P1", "quote": text, "text_sha256": digest(text)}, "reviewer": "test", "basis": "explicit source identity"}
    payload["evidence"][0]["table_locator"].update(cell_id="T1:r0001:c0002", column_index=2)
    return payload, inputs, {"reviews": [review]}


def check(payload, inputs, reviews):
    context = audit_context(payload, inputs["stage0"], inputs["stage3"])
    context["catalog"] = build_catalog(inputs["stage0"], inputs["stage3"], alias_reviews=reviews)
    return check_publication_source(payload["property_observations"][0], context)


def test_reviewed_alias_resolves_only_its_source_row_without_mutation():
    payload, inputs, reviews = fixture()
    before = deepcopy((payload, inputs, reviews))
    assert check(payload, inputs, {"reviews": []})["binding_status"] == "conflict"
    result = check(payload, inputs, reviews)
    assert result["binding_status"] == "resolved", result
    assert result["source_alias_reviews"] == reviews["reviews"]
    assert (payload, inputs, reviews) == before
    payload["evidence"][0]["table_locator"].update(cell_id="T1:r0002:c0002", row_index=2)
    payload["property_observations"][0]["value_raw"] = "100"
    assert check(payload, inputs, reviews)["binding_status"] == "conflict"


def test_stale_review_and_competing_batch_never_merge():
    for change in ("source", "sample", "definition", "competing"):
        payload, inputs, reviews = fixture()
        if change == "source":
            inputs["stage0"]["elements"][0]["table_body"] = inputs["stage0"]["elements"][0]["table_body"].replace('8.1', '50.8')
        elif change == "sample":
            inputs["stage3"]["samples"][0]["state_description"] = "another treatment"
        elif change == "definition":
            inputs["stage0"]["elements"][1]["text"] = "A different gel"
        else:
            inputs["stage3"]["samples"].append({"sample_id": "s003", "sample_label_raw": "A", "sample_kind": "synthesis_batch"})
        assert check(payload, inputs, reviews)["binding_status"] != "resolved", change


def test_optional_null_evidence_metadata_does_not_invalidate_identity():
    sample = {"sample_id": "s001", "sample_label_raw": "A gel", "evidence": {"block_id": "P1", "source_sentence": "A gel"}}
    normalized = deepcopy(sample)
    normalized["evidence"]["table_locator"] = None
    assert sample_review_hash(sample) == sample_review_hash(normalized)
