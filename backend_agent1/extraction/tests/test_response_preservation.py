"""Regression cases for response boundaries, independent of article identities."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from schema.polymer_schema import PropertyStageResponse, ValueFootnoteLink
from stages.stage4_property import _preview_salvage_raw_payload, _repair_candidate_response_payload
from stages.stage5_characterization import extract_characterizations, load_characterization_vocabulary, DEFAULT_VOCABULARY_PATH
from stages.stage4t_table_property import _unit_info
from stages.source_context_semantics import derive_context_conditions, derive_source_semantics
from stages.numeric_value_semantics import derive_numeric_value
from tests.test_numeric_value_semantics import observation, table
from tests import test_stage4_property as n
from tests import test_stage5_characterization as s5
from unittest.mock import patch


def test_optional_footnote_quote_preserved_but_unknown_fields_still_fail():
    raw = {"block_id": "T_1", "text_raw": "Measured at room temperature", "source_sentence": "a) Measured at room temperature"}
    assert ValueFootnoteLink.model_validate(raw).source_sentence == raw["source_sentence"]
    with pytest.raises(ValidationError):
        ValueFootnoteLink.model_validate({**raw, "invented": 1})


def test_extra_entity_declaration_is_auditable_and_not_used_to_guess_binding():
    raw = n.FakeClient().call_json('', '').data
    raw['properties'][0]['entity_id'] = 'pe999'
    before = deepcopy(raw)
    vocab, _ = n.load_property_vocabulary(n.DEFAULT_VOCABULARY_PATH)
    fixed, repairs = _repair_candidate_response_payload(raw,n.stage3_document(),n.stage0_document().elements,vocab,preview_relaxed=True)
    assert raw == before
    item = fixed['properties'][0]
    assert item['sample_id'] == raw['properties'][0]['sample_id']
    assert item['candidate_trace']['model_entity_declaration'] == {'entity_id':'pe999','status':'unverified'}
    assert repairs['property_entity_declarations_preserved'] == 1


def test_bad_point_does_not_discard_neighbors_or_change_input():
    raw = n.SeriesClient().call_json("", "").data
    series = raw["property_series"][0]
    good = series["points"][0]
    good["confidence"] = {"score": .8}
    bad = deepcopy(good)
    bad.update(point_id="pt011", value_raw=None)
    series["points"].append(bad)
    original = deepcopy(raw)
    kept, audit = _preview_salvage_raw_payload(raw)
    parsed = PropertyStageResponse.model_validate(kept)
    assert len(parsed.property_series[0].points) == 1
    assert audit["dropped_raw_points"][0]["raw_object"] == bad
    assert raw == original


def test_warning_for_reclassified_property_keeps_original_reference():
    from stages import stage4_property as module
    original = module._validate_response
    def validate(*a, **kw):
        result = list(original(*a, **kw))
        result[6] = [*result[6], ("prop999", "P_2_0")]
        return tuple(result)
    vocab, digest = n.load_property_vocabulary(n.DEFAULT_VOCABULARY_PATH)
    with patch.object(module, "_validate_response", side_effect=validate):
        result = module.extract_properties(n.stage0_document(), n.stage2_document(), n.stage3_document(),
            n.FakeClient(), n.rendered_prompt(), vocab, digest, preview_relaxed=True)
    warning = next(w for w in result.warnings if w['code'] == 'supplemented_property_evidence')
    assert {'candidate_property_id':'prop999', 'property_id':None, 'block_id':'P_2_0'} in warning['items']


def test_found_row_label_does_not_leak_to_calculated_row():
    from stages.table_grid import parse_table_cells
    source = table("C %", "59.14")
    source.table_body = '<table><tr><th>Analysis</th><th>C %</th></tr><tr><td>Found</td><td>59.14</td></tr><tr><td>Calcd</td><td>59.46</td></tr></table>'
    source.table_cells = parse_table_cells(source.table_body, 'T_1')
    for row, raw, role in [(1,'59.14','measured'), (2,'59.46','calculated')]:
        item = observation(raw,None,evidence=[{'block_id':'T_1','table_locator':{'table_id':'T_1','row_index':row,'column_index':1}}])
        assert derive_source_semantics(item,{'T_1':source})['source_role'] == role


def test_missing_value_requires_unique_actual_source_cell():
    raw = n.SeriesClient().call_json("", "").data
    point = raw["property_series"][0]["points"][0]
    original_value = point.pop("value_raw")
    vocab, _ = n.load_property_vocabulary(n.DEFAULT_VOCABULARY_PATH)
    fixed, _ = _repair_candidate_response_payload(raw, n.stage3_document(), n.stage0_document().elements, vocab, preview_relaxed=True)
    recovered = fixed["property_series"][0]["points"][0]
    assert recovered["value_raw"] == original_value
    assert recovered["candidate_trace"]["value_recovery"]["source_cell_id"]
    assert "value_raw" not in point
    fixed, _ = _repair_candidate_response_payload(raw, n.stage3_document(), (), vocab, preview_relaxed=True)
    assert not fixed["property_series"][0]["points"][0].get("value_raw")


def run_stage5(client):
    methods, vocab, digest = load_characterization_vocabulary(DEFAULT_VOCABULARY_PATH)
    return extract_characterizations(s5.stage0_document(), s5.stage2_document(), s5.stage3_document(),
        s5.stage4_document(), client, s5.rendered_prompt(), methods, vocab, digest,
        max_validation_retries=0, preview_relaxed=True)


def test_missing_binding_and_bad_specialized_object_preserve_neighbors():
    class Client(s5.FakeClient):
        def call_json(self, *args, **kwargs):
            response = super().call_json(*args, **kwargs)
            good = {"specialized_id": "sp_cand001", "sample_resolution_status": "resolved",
                "property_name_raw": "structure assignment", "value_raw": "C=C stretching",
                "confidence": {"score": .7}, "evidence": [{"block_id": "P_2_0", "source_sentence": s5.FTIR_SENTENCE}]}
            response.data["specialized_property_observations"] = [good, {**good, "specialized_id": "sp_cand002", "value_raw": ""}]
            self.raw = deepcopy(response.data)
            return response
    client = Client()
    result = run_stage5(client)
    assert len(result.characterizations) == 2 and len(result.properties) == 1
    assert len(result.specialized_property_observations) == 1
    assert result.specialized_property_observations[0].sample_id is None
    assert client.raw["specialized_property_observations"][0]["sample_resolution_status"] == "resolved"
    assert result.provenance.call_count == 1 and result.provenance.status == "candidate_partial"
    assert any(w.get("blocking") for w in result.warnings)


def test_empty_after_local_salvage_blocks_success():
    class Client(s5.FakeClient):
        def call_json(self, *args, **kwargs):
            response = super().call_json(*args, **kwargs)
            for item in response.data["characterizations"]:
                item.pop("method_raw")
            return response
    result = run_stage5(Client())
    assert not result.characterizations and not result.properties
    assert result.provenance.status == "candidate_partial"
    assert any(w["code"] == "preview_degraded_empty_shell" and w["blocking"] for w in result.warnings)


@pytest.mark.parametrize("headers,caption,unit", [
    (["Wg"], "Measured at 30 °C", None),
    (["tan δ"], r"Summary of $T_{g}$ and tan δ", None),
    (["d/Å"], "Measured at 25 °C", "Å"),
    ([r"\frac{d}{Å}"], "", "Å"),
    ([r"IR (cm^{-1})"], "", "cm-1"),
    (["C"], "Elemental analysis at 30 °C", None),
    (["Strength"], "All values are reported in MPa", "MPa"),
    (["Strength (MPa)"], "at 25 °C", "MPa"),
])
def test_units_are_column_scoped(headers, caption, unit):
    result = _unit_info(headers, caption)
    assert result["unit_normalized"] == unit
    if unit is None:
        assert result["unit_raw"] is None


@pytest.mark.parametrize('header,raw', [('Amount Used, g','g'), ('mol/L','mol/L'), (r'$T_d/°C^b$','°C')])
def test_explicit_raw_unit_survives_missing_normalization(header, raw):
    result = _unit_info([header], 'at 30 °C')
    assert result['unit_raw'] == raw and result['unit_location'] == 'header'


def test_parameter_number_boundary_and_latex_spacing():
    quote = r"Measured in 0·1 g/dL at $20^{\circ}$ C/min for 1 min."
    result = derive_context_conditions([{"scope": "table_note", "block_id": "T_1", "text_raw": quote}])
    assert [(r["parameter"], r["value_raw"]) for r in result] == [
        ("heating_rate", "20°C/min"), ("concentration", "0·1 g/dL"), ("time", "1 min")]
    assert all(r["quote"] == quote for r in result)


@pytest.mark.parametrize("raw,bounds", [("0,32", .32), ("30,5", 30.5), ("138,154", None)])
def test_comma_is_not_silently_published_as_vector_or_decimal(raw, bounds):
    source = table("Value", raw)
    item = observation(raw, None, evidence=[{"block_id": "T_1", "table_locator": {
        "table_id": "T_1", "row_index": 1, "column_index": 0, "cell_id": "T_1:r0001:c0000", "cell_value": raw}}])
    item.value_min = item.value_max = bounds
    result = derive_numeric_value(item, {"T_1": source})
    assert result["status"] == "review_required" and "actual_values" not in result
    assert item.value_raw == raw


@pytest.mark.parametrize("label,role", [("Found", "measured"), ("Calcd", "calculated"), ("We found", "unknown")])
def test_found_requires_explicit_result_label(label, role):
    source = table(label, "59.14")
    item = observation("59.14", None, evidence=[{"block_id": "T_1", "table_locator": {
        "table_id": "T_1", "row_index": 1, "column_index": 0}}])
    assert derive_source_semantics(item, {"T_1": source})["source_role"] == role
