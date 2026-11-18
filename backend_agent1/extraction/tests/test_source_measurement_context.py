from copy import deepcopy

from stages.measurement_publication import build_measurement_publication
from stages.sample_catalog import source_index
from stages.source_measurement_context import build_source_context_index, table_review_hash
from tests.test_measurement_publication import fixture


def with_dose(claim=None):
    payload, inputs = fixture()
    table = inputs["stage0"]["elements"][0]
    table["table_body"] = table["table_body"].replace("</th></tr>", "</th><th>Dose/kGy</th></tr>").replace("120</td>", "120</td><td>8.1</td>").replace("100</td>", "100</td><td>9</td>")
    if claim is not None:
        payload["property_observations"][0]["measurement_context"] = {"dose": claim}
    return payload, inputs


def test_source_condition_enters_primary_record_without_overwriting_model_context():
    payload, inputs = with_dose()
    before = deepcopy((payload, inputs))
    result = build_measurement_publication(payload, **inputs)
    record = result["final"][0]["record"]
    condition = record["source_condition_context"]
    assert condition["condition_axes"][0]["value_raw"] == "8.1"
    assert condition["declared_context_comparison"] == "declaration_missing"
    assert "dose" not in record["condition_context"]["measurement_context"]
    assert (payload, inputs) == before


def test_conflict_blocks_primary_and_exact_converted_agreement_passes():
    payload, inputs = with_dose("9 kGy")
    bad = build_measurement_publication(payload, **inputs)
    assert not bad["final"]
    assert "source_condition_conflict" in bad["not_publishable"][0]["publication_reasons"]
    payload["property_observations"][0]["measurement_context"]["dose"] = "8100 Gy"
    good = build_measurement_publication(payload, **inputs)
    assert good["final"][0]["record"]["source_condition_context"]["declared_context_comparison"] == "matched"


def test_source_review_is_bound_to_exact_table_and_preserves_condition_kind():
    _, inputs = with_dose()
    stage0 = inputs["stage0"]
    block = stage0["elements"][0]
    block["table_body"] = block["table_body"].replace("th>", "td>")
    review = {"document_id": "test", "table_id": "T1", "table_sha256": table_review_hash(block),
              "header_cell_ids": ["T1:r0000:c0002"], "header_path": ["Dose/kGy"], "condition_kind": "sample_preparation"}
    def axis():
        index = build_source_context_index(stage0, source_index(stage0), {"reviews": [review]})
        return index["paths"]["T1:r0001:c0001"]["condition_axes"][0]
    assert axis()["association_status"] == "source_aligned"
    assert axis()["condition_kind"] == "sample_preparation"
    block["table_body"] = block["table_body"].replace("8.1", "8.2")
    assert axis()["association_status"] == "candidate"
    assert axis()["condition_kind"] == "unspecified"
