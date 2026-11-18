from types import SimpleNamespace

import pytest

from schema.polymer_schema import NumericValueSemantics, Stage0Element
from stages.numeric_value_semantics import derive_numeric_value
from stages.table_grid import parse_table_cells


def observation(raw, semantics, *, unit="g/mol", evidence=()):
    return SimpleNamespace(value_raw=raw, unit_raw=unit, unit_normalized=None,
                           value_semantics=NumericValueSemantics.model_validate(semantics) if semantics is not None else None,
                           evidence=evidence)


def table(header, body="12"):
    html = f"<table><tr><th>{header}</th></tr><tr><td>{body}</td></tr></table>"
    return Stage0Element(block_id="T_1", type="table", page=1, source_block_index=0,
                         table_body=html, table_cells=parse_table_cells(html, "T_1"))


@pytest.mark.parametrize("header,raw,expected,unit", [
    ("Mw ×10^-3 (g/mol)", "42", 42000, "g/mol"),
    ("ΔCp (cal/g°C) (×10²)", "11.10", 0.111, "cal/g°C×10²"),
])
def test_displayed_property_multiplier_is_inverted_without_changing_raw(header, raw, expected, unit):
    source = table(header)
    item = observation(raw, {"scale": {"expression_raw": header, "source_block_id": "T_1",
                        "relation": "displayed_equals_actual_times_scale"}}, unit=unit)
    result = derive_numeric_value(item, {"T_1": source})
    assert result["status"] == "normalized"
    assert result["actual_values"] == pytest.approx([expected])
    assert result["actual_unit"] in {"g/mol", "cal/g°C"}
    assert item.value_raw == raw and item.unit_raw == unit


def test_unit_prefix_multiplier_uses_the_other_direction():
    source = table("Mw (10^3 g/mol)")
    item = observation("42", {"scale": {"expression_raw": "10^3 g/mol", "source_block_id": "T_1",
                       "relation": "actual_equals_displayed_times_scale"}})
    assert derive_numeric_value(item, {"T_1": source})["actual_values"] == [42000]


def test_multiplier_fragment_uses_verified_header_of_the_value_column():
    source = table("ΔCp (cal/g°C) (×10²)")
    locator = {"table_id": "T_1", "column_index": 0, "row_index": 1}
    item = observation("12", {"scale": {"expression_raw": "×10²", "source_block_id": "T_1",
        "source_cell_id": "T_1:r0000:c0000", "relation": "displayed_equals_actual_times_scale"}},
        evidence=[SimpleNamespace(table_locator=locator)])
    assert derive_numeric_value(item, {"T_1": source})["actual_values"] == pytest.approx([0.12])
    locator["column_index"] = 1
    assert "actual_values" not in derive_numeric_value(item, {"T_1": source})


def test_mixed_resolved_and_unresolved_series_is_retained():
    from copy import deepcopy
    from tests.test_stage4_property import SeriesClient, stage0_document, stage3_document, load_property_vocabulary, DEFAULT_VOCABULARY_PATH
    from schema.polymer_schema import PropertySeriesCandidate
    from stages.stage4_property import _repair_candidate_response_payload
    payload = SeriesClient().call_json("", "").data
    series = payload["property_series"][0]
    series.update(sample_id=None, entity_id=None, sample_resolution_status="unresolved")
    known = series["points"][0]
    known.update(sample_id="s001", entity_id="pe001", sample_resolution_status="resolved")
    second = deepcopy(known)
    second.update(point_id="pt011", sample_id="s002", entity_id="pe002")
    unknown = deepcopy(known)
    unknown.update(point_id="pt012", sample_id=None, entity_id=None, sample_resolution_status="unresolved")
    series["points"] = [known, second, unknown]
    series.pop("coverage", None)
    assert len(PropertySeriesCandidate.model_validate(series).points) == 3
    vocabulary, _ = load_property_vocabulary(DEFAULT_VOCABULARY_PATH)
    repaired, _ = _repair_candidate_response_payload(payload, stage3_document(), stage0_document().elements,
                                                     vocabulary, preview_relaxed=True)
    assert len(repaired["property_series"]) == 1
    assert len(repaired["property_series"][0]["points"]) == 3


def test_wrong_or_unknown_multiplier_direction_does_not_publish_actual_value():
    source = table("Mw ×10^-3 (g/mol)")
    for relation in ("unknown", "actual_equals_displayed_times_scale"):
        item = observation("42", {"scale": {"expression_raw": "Mw ×10^-3 (g/mol)",
                       "source_block_id": "T_1", "relation": relation}})
        result = derive_numeric_value(item, {"T_1": source})
        assert result["status"] == "review_required" and "actual_values" not in result


def test_scale_not_in_source_is_not_applied():
    source = table("Mw (g/mol)")
    item = observation("42", {"scale": {"expression_raw": "Mw ×10^-3", "source_block_id": "T_1",
                       "relation": "displayed_equals_actual_times_scale"}})
    result = derive_numeric_value(item, {"T_1": source})
    assert result["warnings"] == ["scale_source_unverified"]
    assert "actual_values" not in result and "candidate_values" not in result


def test_repeated_exponent_requires_same_column_and_remains_review_candidate():
    source = table("Cp", "1.22×10^-3")
    source.table_body = source.table_body.replace("</table>", "<tr><td>2.41</td></tr></table>")
    source.table_cells = parse_table_cells(source.table_body, "T_1")
    locator = SimpleNamespace(table_id="T_1", column_index=0, row_index=2)
    item = observation("2.41", {"scale": {"expression_raw": "1.22×10^-3", "source_block_id": "T_1",
        "source_cell_id": "T_1:r0001:c0000", "relation": "repeated_cell_exponent"}},
        evidence=[SimpleNamespace(table_locator=locator)])
    result = derive_numeric_value(item, {"T_1": source})
    assert result["status"] == "review_required"
    assert result["candidate_values"] == pytest.approx([0.00241]) and "actual_values" not in result
    # Materialized Evidence uses a dict, while some candidate fixtures use models.
    item.evidence = [SimpleNamespace(table_locator={"table_id": "T_1", "column_index": 0, "row_index": 2})]
    assert derive_numeric_value(item, {"T_1": source})["candidate_values"] == pytest.approx([0.00241])
    item.evidence = [SimpleNamespace(table_locator=locator)]
    locator.column_index = 1
    invalid = derive_numeric_value(item, {"T_1": source})
    assert "candidate_values" not in invalid


def test_approximation_uncertainty_and_role_are_preserved():
    item = observation("about 70 ± 2", {"value_role": "predicted", "qualifiers_raw": ["about"]}, unit="°C")
    result = derive_numeric_value(item, {})
    assert result["actual_values"] == [70] and result["uncertainty"] == 2
    assert item.value_raw == "about 70 ± 2" and item.value_semantics.value_role == "predicted"


def test_footnote_link_is_checked_against_its_own_table():
    source = table("Mw (g/mol)")
    source.table_notes = ["a) GPC peak maximum."]
    item = observation("42", {"footnote_links": [{"block_id": "T_1", "marker_raw": "a)",
                                                   "text_raw": "a) GPC peak maximum."}]})
    assert derive_numeric_value(item, {"T_1": source})["warnings"] == []
    result = derive_numeric_value(item, {})
    assert result["status"] == "review_required" and result["warnings"] == ["footnote_text_not_in_source"]


def test_full_stage4_keeps_unknown_material_and_calls_once():
    from tests.test_stage4_property import (
        UnresolvedClient, stage0_document, stage2_document, stage3_document,
        rendered_prompt, load_property_vocabulary, DEFAULT_VOCABULARY_PATH,
    )
    from stages.stage4_property import extract_properties, select_context_blocks
    class Client(UnresolvedClient):
        def call_json(self, *args, **kwargs):
            response = super().call_json(*args, **kwargs)
            item = response.data["unresolved_properties"][0]
            item.update(entity_id=None, article_sample_key="PB",
                        value_semantics={"value_role": "measured", "qualifiers_raw": []})
            return response
    document = stage0_document()
    for block in document.elements:
        block.section = "Introduction"
    document.elements.append(document.elements[0].model_copy(update={
        "block_id": "P_REF", "section": "References", "source_block_index": 99,
    }))
    entities = stage2_document().model_copy(update={"polymer_entities": []})
    process = stage3_document().model_copy(update={"samples": [], "process_steps": []})
    # Remove references in this fixture to deliberately empty upstream material identity.
    client = Client()
    vocabulary, digest = load_property_vocabulary(DEFAULT_VOCABULARY_PATH)
    result = extract_properties(document, entities, process, client, rendered_prompt(), vocabulary, digest,
                                preview_relaxed=True)
    assert client.calls == 1
    item = result.unresolved_properties[0]
    assert item.entity_id is None and item.article_sample_key == "PB"
    assert item.value_raw == "8.5 to 8.6" and item.value_semantics.value_role == "measured"
    assert item.value_derivation["actual_values"] == [8.5, 8.6]
    selected, _, _ = select_context_blocks(document, entities, process)
    assert {b.block_id for b in selected} == {b.block_id for b in document.elements if b.section != "References"}


def test_stage6_preserves_unresolved_identity_and_numeric_metadata():
    from tests.test_stage6_validate_merge import all_stages
    from schema.polymer_schema import UnresolvedPropertyObservation
    from stages.stage6_validate_merge import validate_and_merge
    stages = list(all_stages())
    prop = stages[4].properties[0]
    unresolved = UnresolvedPropertyObservation(
        unresolved_id="uprop001", entity_id=None, article_sample_key="P-unknown",
        property_name_raw=prop.property_name_raw, value_raw=prop.value_raw,
        unit_raw=prop.unit_raw, reason="sample_not_found", evidence=prop.evidence,
        value_semantics={"value_role": "reference", "qualifiers_raw": ["about"]},
        value_derivation={"status": "review_required", "candidate_values": [12]},
    )
    stages[4].unresolved_properties.append(unresolved)
    final, validation = validate_and_merge(*stages, preview=True)
    assert final is not None
    kept = final.unresolved_property_observations[0]
    assert kept.entity_id is None and kept.article_sample_key == "P-unknown"
    assert kept.value_semantics.value_role == "reference" and kept.value_raw == prop.value_raw
    assert kept.value_derivation["derivation_version"] == "numeric_semantics.v5"
    assert unresolved.value_derivation == {"status": "review_required", "candidate_values": [12]}
    assert any(w.code == "unresolved_material_identity" for w in validation.warnings)


def test_scalar_and_percent_do_not_require_model_semantic_fields():
    item = observation("about 5%", None, unit=None)
    result = derive_numeric_value(item, {})
    assert result["actual_values"] == [5] and result["actual_unit"] == "%"
    assert item.value_semantics is None and item.value_raw == "about 5%"


def test_source_role_conflict_is_annotated_without_overwriting_model():
    block = Stage0Element(block_id="P_1", type="text", page=0, source_block_index=0,
                          text="The relaxation times calculated from this data are 6.7 and 4.9 ms.")
    item = observation("6.7", {"value_role": "measured"}, unit="ms", evidence=[SimpleNamespace(
        block_id="P_1", source_sentence=block.text, table_locator=None)])
    result = derive_numeric_value(item, {"P_1": block})
    semantic = result["source_semantics"]
    assert semantic["source_role"] == "calculated" and semantic["role_status"] == "conflict"
    assert item.value_semantics.value_role == "measured"
    block.text = "The time 6.7 ms was not calculated."
    item.evidence[0].source_sentence = block.text
    assert derive_numeric_value(item, {"P_1": block})["source_semantics"]["source_role"] == "unknown"


def test_only_marked_value_inherits_its_footnote_not_neighboring_values():
    source = table("Transition (°C)", "105<sup>b)</sup>")
    source.table_notes = ["b) Peak broad and flat; difficult to determine."]
    source.table_body = source.table_body.replace("</table>", "<tr><td>120</td></tr></table>")
    source.table_cells = parse_table_cells(source.table_body, "T_1")
    evidence = SimpleNamespace(block_id="T_1", source_sentence="105b)", table_locator={"cell_id":"T_1:r0001:c0000"})
    item = observation("105", None, unit="°C", evidence=[evidence])
    annotations = derive_numeric_value(item, {"T_1":source})["source_semantics"]
    assert annotations["footnote_associations"][0]["status"] == "confirmed"
    assert {q["qualifier_raw"] for q in annotations["qualifiers_from_source"]} >= {"broad", "flat", "difficult to determine"}
    evidence.table_locator = {"cell_id":"T_1:r0002:c0000"}
    assert not derive_numeric_value(observation("120", None, evidence=[evidence]), {"T_1":source})["source_semantics"]["footnote_associations"]


def test_column_header_links_html_footer_and_recovers_explicit_scale():
    source = table("Mw<sup>a)</sup> ×10^-3 (g/mol)", "12")
    source.table_body = source.table_body.replace("</table>", "<tr><td colspan='2'>a) GPC peak maximum.</td></tr></table>")
    source.table_cells = parse_table_cells(source.table_body, "T_1")
    item = observation("12", None, evidence=[SimpleNamespace(block_id="T_1", table_locator={"cell_id":"T_1:r0001:c0000"}, source_sentence="12")])
    result = derive_numeric_value(item, {"T_1":source})
    assert result["actual_values"] == [12000]
    assert result["source_semantics"]["footnote_associations"][0]["text_raw"] == "a) GPC peak maximum."


def test_duplicate_note_definitions_remain_ambiguous():
    source = table("Tg<sup>a)</sup>", "70")
    source.table_notes = ["a) Experimental.", "a) Calculated."]
    item = observation("70", None, evidence=[SimpleNamespace(block_id="T_1", table_locator={"cell_id":"T_1:r0001:c0000"}, source_sentence="70")])
    result = derive_numeric_value(item, {"T_1":source})["source_semantics"]
    assert len(result["footnote_associations"]) == 2
    assert result["source_role"] == "unknown" and "footnote_marker_ambiguous" in result["warnings"]


def test_parameter_body_and_table_frequency_remain_separate():
    from stages.source_context_semantics import derive_parameter_sources
    body = Stage0Element(block_id="P_1", type="text", page=0, source_block_index=0,
                         text="1H NMR (200 MHz, CDCl3).")
    html = "<table><tr><th>Compound</th><th>1H NMR<sup>b)</sup></th></tr>" \
           "<tr><td>A</td><td>4.2</td></tr><tr><td colspan='2'>b) 250 MHz, CDCl3.</td></tr></table>"
    tbl = Stage0Element(block_id="T_1", type="table", page=1, source_block_index=1,
                        table_body=html, table_cells=parse_table_cells(html,"T_1"))
    char = SimpleNamespace(characterization_id="char001", article_sample_key="A",
        parameters={"1H frequency":"200 MHz"}, evidence=[SimpleNamespace(block_id="P_1")])
    result = derive_parameter_sources(char, [], {"P_1":body,"T_1":tbl})["1H frequency"]
    assert {(s["value_raw"],s["scope"]) for s in result} == {("200 MHz","body"),("250 MHz","table_note")}
    assert char.parameters == {"1H frequency":"200 MHz"}
    char.parameters = {"13C frequency":"200 MHz"}
    assert derive_parameter_sources(char, [], {"P_1":body,"T_1":tbl})["13C frequency"][0]["status"] == "unverified"


def test_composite_cell_footnote_attaches_only_to_preceding_value():
    source = table("Thermal transitions", "g 19 sA (155)<sup>b)</sup> i")
    source.table_notes = ["b) Clearing peak broad and flat."]
    evidence = SimpleNamespace(block_id="T_1",table_locator={"cell_id":"T_1:r0001:c0000"},source_sentence="g 19 sA (155)b) i")
    low = derive_numeric_value(observation("19",None,evidence=[evidence]),{"T_1":source})
    high = derive_numeric_value(observation("(155)",None,evidence=[evidence]),{"T_1":source})
    assert not low["source_semantics"]["footnote_associations"]
    assert high["source_semantics"]["footnote_associations"][0]["marker_raw"] == "b"
    assert high["status"] == "review_required" and high["candidate_values"] == [155]
    assert "actual_values" not in high


def test_unit_is_derived_only_from_this_values_column_header():
    source = table("Mw (g/mol)","12")
    evidence = SimpleNamespace(block_id="T_1",table_locator={"cell_id":"T_1:r0001:c0000"},source_sentence="12")
    item = observation("12",None,unit=None,evidence=[evidence])
    result = derive_numeric_value(item,{"T_1":source})
    assert result["actual_unit"] == "g/mol" and item.unit_raw is None


def test_damaged_header_unit_is_not_confirmed_or_guessed():
    source = table("Thermal transitions /\ufffd\ufffdC", "19")
    evidence = SimpleNamespace(block_id="T_1",table_locator={"cell_id":"T_1:r0001:c0000"},source_sentence="19")
    item = observation("19",None,unit=None,evidence=[evidence])
    result = derive_numeric_value(item,{"T_1":source})
    assert result["status"] == "review_required" and result["actual_unit"] is None
    assert "damaged_header_unit" in result["warnings"] and "actual_values" not in result
    assert item.unit_raw is None


def test_multi_nucleus_paragraph_does_not_confirm_wrong_frequency_scope():
    from stages.source_context_semantics import derive_parameter_sources
    body = Stage0Element(block_id="P_1",type="text",page=1,source_block_index=0,
        text="The spectrometer operates at 25.2 MHz 13C resonance frequency and 100.1 MHz proton frequency.")
    char = SimpleNamespace(characterization_id="char001",article_sample_key=None,
        parameters={"13C frequency":"100.1 MHz"},evidence=[SimpleNamespace(block_id="P_1")])
    records = derive_parameter_sources(char,[],{"P_1":body})["13C frequency"]
    assert records[0]["status"] == "candidate"


def test_composite_data_row_is_not_used_as_a_header(monkeypatch):
    import stages.source_context_semantics as semantic
    source = table("Transitions", "g 19 sA (155)<sup>b)</sup> i")
    source.table_body = source.table_body.replace("</table>","<tr><td>g 17 sA 130 i</td></tr></table>")
    source.table_cells = parse_table_cells(source.table_body,"T_1")
    source.table_notes = ["b) Broad peak."]
    monkeypatch.setattr(semantic,"survey_table",lambda _: {"header_rows":[0,1]})
    evidence = SimpleNamespace(block_id="T_1",table_locator={"cell_id":"T_1:r0002:c0000"},source_sentence="g 17 sA 130 i")
    result = derive_numeric_value(observation("130",None,evidence=[evidence]),{"T_1":source})
    assert not result["source_semantics"]["footnote_associations"]


@pytest.mark.parametrize("marker,definition", [
    ("<sup>*1</sup>", "${}^{*1}$ GPC at 100 °C."),
    ("$M_n^{*2}$", "*2 Concentration 0.5 g/dL."),
    ("<sup>a</sup>", "<sup>a</sup> Calculated values."),
    ("$T_g^b$", "$^{b}$ Broad peak."),
])
def test_explicit_superscript_footnotes_without_parentheses(marker,definition):
    source=table("Property " + marker, "12");source.table_notes=[definition]
    evidence=SimpleNamespace(block_id="T_1",table_locator={"cell_id":"T_1:r0001:c0000"},source_sentence="12")
    result=derive_numeric_value(observation("12",None,evidence=[evidence]),{"T_1":source})
    assert len(result["source_semantics"]["footnote_associations"])==1
    assert result["source_semantics"]["footnote_associations"][0]["status"]=="confirmed"


def test_plain_letter_suffix_does_not_become_a_superscript():
    source=table("GPCa", "12");source.table_notes=["a) Calculated values."]
    evidence=SimpleNamespace(block_id="T_1",table_locator={"cell_id":"T_1:r0001:c0000"},source_sentence="12")
    assert not derive_numeric_value(observation("12",None,evidence=[evidence]),{"T_1":source})["source_semantics"]["footnote_associations"]


@pytest.mark.parametrize("header", ["$M_n/10^3$",r"$\frac{M_n}{10^{3}}$"])
def test_explicit_fraction_scale_requires_this_column_header(header):
    source=table(header,"2.9")
    evidence=SimpleNamespace(block_id="T_1",table_locator={"table_id":"T_1","cell_id":"T_1:r0001:c0000","row_index":1,"column_index":0},source_sentence="2.9")
    result=derive_numeric_value(observation("2.9",None,evidence=[evidence]),{"T_1":source})
    assert result["actual_values"]==[2900]
    assert result["scale_relation"]=="actual_equals_displayed_times_scale"
    assert "scale_exponent" not in derive_numeric_value(observation("2.9",None),{"T_1":source}) or derive_numeric_value(observation("2.9",None),{"T_1":source})["scale_exponent"] is None


def test_middle_dot_is_review_candidate_only_for_literal_source():
    source=table("Hv", "9·4")
    evidence=SimpleNamespace(block_id="T_1",table_locator={"cell_id":"T_1:r0001:c0000"},source_sentence="9·4")
    item=observation("9·4",None,evidence=[evidence])
    result=derive_numeric_value(item,{"T_1":source})
    assert result["candidate_values"]==[9.4] and "actual_values" not in result
    assert item.value_raw=="9·4"
    assert derive_numeric_value(item,{})["status"]=="not_numeric"
    assert derive_numeric_value(observation("2·10^3",None,evidence=[evidence]),{"T_1":source})["actual_values"]==[2000]


def test_parameter_terminal_period_latex_and_direct_table_quote():
    from stages.source_context_semantics import derive_parameter_sources
    source=table("Property","12");source.table_notes=[r"*1 Heating rate $3\,\mathrm{K}/\mathrm{min}$. Temperature 293 K."]
    char=SimpleNamespace(characterization_id="char001",article_sample_key=None,
        parameters={"heating rate":"3 K/min"}, evidence=[SimpleNamespace(block_id="T_1",source_sentence=source.table_notes[0])])
    result=derive_parameter_sources(char,[],{"T_1":source})["heating rate"]
    assert result[0]["status"]=="confirmed" and result[0]["scope"]=="table_quote"
    char.parameters={"temperature":"29 K"}
    assert derive_parameter_sources(char,[],{"T_1":source})["temperature"][0]["status"]=="unverified"


def test_literal_aggregate_survives_incompatible_links_without_mutating_raw():
    from copy import deepcopy
    from stages.stage4_property import _repair_candidate_response_payload
    from tests.test_stage4_property import stage3_document
    from schema.polymer_schema import PropertyObservationCandidate
    source=table("Density","1.19 ± 0.01")
    item={"property_id":"prop001","sample_id":"s001","property_name_raw":"Density",
          "value_raw":"1.19 ± 0.01","unit_raw":"g/cm3","observation_role":"aggregate","measurement_condition_id":"mc001",
          "series_ids":["series001","series002"],"confidence":{"score":0.8},
          "evidence":[{"block_id":"T_1","source_sentence":"1.19 ± 0.01","table_locator":{
          "table_id":"T_1","cell_id":"T_1:r0001:c0000","row_index":1,"column_index":0,"column_label":"Density"}}]}
    raw=deepcopy(item)
    payload,repairs=_repair_candidate_response_payload({"properties":[item]},stage3_document(),[source],preview_relaxed=True)
    kept=payload["properties"][0]
    assert kept["value_raw"]==raw["value_raw"] and item==raw
    assert "series_ids" not in kept and repairs["aggregate_relation_downgraded"]==1
    assert kept["aggregate_relation_audit"]["original_series_ids"]==raw["series_ids"]
    assert PropertyObservationCandidate.model_validate(kept).sample_id=="s001"
    # Contradictory coordinates cannot establish literal source support.
    item["evidence"][0]["table_locator"]["row_index"]=2
    payload,_=_repair_candidate_response_payload({"properties":[item]},stage3_document(),[source],preview_relaxed=True)
    assert not payload["properties"]



def test_stage6_retains_detached_aggregate_audit_and_warns():
    from tests.test_stage6_validate_merge import all_stages
    from stages.stage6_validate_merge import validate_and_merge
    from schema.polymer_schema import PropertyObservation
    stages=list(all_stages());raw=stages[4].properties[0].model_dump()
    raw.update(observation_role="aggregate",series_id=None,series_ids=None,
        aggregate_relation_audit={"reason":"aggregate_series_reference_incompatible","source_supported":True,
                                  "original_series_ids":["series777","series778"],"original_sample_id":raw["sample_id"]})
    stages[4].properties[0]=PropertyObservation.model_validate(raw)
    final,validation=validate_and_merge(*stages,preview=True)
    assert final is not None and validation.error_count==0
    kept=next(p for p in final.property_observations if p.property_id==raw["property_id"])
    assert kept.aggregate_relation_audit.original_series_ids==["series777","series778"]
    assert kept.series_id is None and kept.series_ids is None
    assert any(w.code=="aggregate_relation_unverified" for w in validation.warnings)



def test_full_stage4_materialization_retains_verified_aggregate_after_downgrade():
    from tests.test_stage4_property import FakeClient, stage0_document, stage2_document, stage3_document, rendered_prompt
    from stages.stage4_property import extract_properties, load_property_vocabulary, DEFAULT_VOCABULARY_PATH
    class AggregateClient(FakeClient):
        def call_json(self,*args,**kwargs):
            response=super().call_json(*args,**kwargs)
            response.data["properties"][0].update(observation_role="aggregate",series_ids=["series777","series778"])
            return response
    vocabulary,digest=load_property_vocabulary(DEFAULT_VOCABULARY_PATH)
    client=AggregateClient()
    output=extract_properties(stage0_document(),stage2_document(),stage3_document(),client,rendered_prompt(),vocabulary,digest,preview_relaxed=True)
    assert client.calls==1 and len(output.properties)==1
    kept=output.properties[0]
    assert kept.value_raw=="8.5 to 8.6" and kept.observation_role=="aggregate"
    assert kept.aggregate_relation_audit.original_series_ids==["series777","series778"]
    assert kept.value_derivation["actual_values"]==[8.5,8.6]


def test_incomplete_unit_exponent_is_warned_without_guessing():
    item=observation("9.4",None,unit="(cal/cm^3)^+")
    result=derive_numeric_value(item,{})
    assert result["status"]=="review_required" and "damaged_unit_symbol_or_exponent" in result["warnings"]
    assert "actual_values" not in result and item.unit_raw=="(cal/cm^3)^+"



def test_units_and_terminal_c_are_not_footnote_markers():
    source=table("Tg (°C)","12");source.table_notes=[r"$^{*1}$ Measured at $100^{\circ}$ C.","l) Reference values."]
    evidence=SimpleNamespace(block_id="T_1",table_locator={"cell_id":"T_1:r0001:c0000"},source_sentence="12")
    result=derive_numeric_value(observation("12",None,evidence=[evidence]),{"T_1":source})
    assert not result["source_semantics"]["footnote_associations"]
    from stages.source_context_semantics import table_notes
    notes=table_notes(source,{"T_1":source})
    assert next(n for n in notes if n["marker_raw"]=="*1")["text_raw"].endswith("C.")
    source=table("Mw (g/mol)","12");source.table_notes=["l) Calculated values."]
    assert not derive_numeric_value(observation("12",None,evidence=[evidence]),{"T_1":source})["source_semantics"]["footnote_associations"]



def test_column_of_simple_multiplications_is_not_confirmed_as_decimals():
    source=table('Mw g/mol','2·3')
    source.table_body=source.table_body.replace('</table>','<tr><td>2·4</td></tr><tr><td>2·5</td></tr></table>')
    source.table_cells=parse_table_cells(source.table_body,'T_1')
    evidence=SimpleNamespace(block_id='T_1',source_sentence='2·3',table_locator={'cell_id':'T_1:r0001:c0000'})
    result=derive_numeric_value(observation('2·3',None,evidence=[evidence]),{'T_1':source})
    assert result['status']=='review_required' and 'actual_values' not in result


def test_footnote_conditions_are_column_scoped_and_rate_is_not_temperature():
    html='<table><tr><th>Sample</th><th>Tg<sup>a</sup></th><th>Yield</th></tr><tr><td>A</td><td>120</td><td>85</td></tr></table>'
    source=Stage0Element(block_id='T',type='table',page=1,source_block_index=0,table_body=html,
        table_cells=parse_table_cells(html,'T'),table_notes=['<sup>a</sup> Measured by DSC at 20 °C/min, using 0.5 g/dl solution for 22–24 h.'])
    evidence=lambda col:SimpleNamespace(block_id='T',table_locator={'cell_id':f'T:r0001:c{col:04d}'},source_sentence='120' if col==1 else '85')
    first=derive_numeric_value(observation('120',None,evidence=[evidence(1)]),{'T':source})['source_semantics']
    other=derive_numeric_value(observation('85',None,evidence=[evidence(2)]),{'T':source})['source_semantics']
    conditions=first['conditions_from_source']
    assert any(c['parameter']=='heating_rate' for c in conditions)
    assert not any(c['parameter']=='temperature' for c in conditions)
    assert any(c['parameter']=='time' and c['value_raw']=='22–24 h' for c in conditions)
    assert not other['conditions_from_source']



def test_plain_dot_definition_at_note_start_does_not_split_time_unit():
    from stages.source_context_semantics import table_notes
    source=table('Tg<sup>a</sup>','120');source.table_notes=['a. Measured at 25 °C for 2 h. Another sentence.']
    notes=table_notes(source,{'T_1':source})
    assert len(notes)==1 and notes[0]['text_raw'].endswith('Another sentence.')
