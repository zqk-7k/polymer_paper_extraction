from tools.preview_polyinfo_row_matcher import (
    build_candidate_index,
    describe_audit_row,
    match_audit_row,
    numbers,
)


def test_identity_alias_is_a_composite_match() -> None:
    final = {
        "polymer_entities": [{
            "polymer_name": "PVC",
            "source_names": ["PVC", "poly(vinyl chloride)"],
        }],
    }
    row = {
        "audit_domain": "聚合物身份",
        "polyinfo_field": "polymer_id/polymer_name/polymer_type",
        "paper_sample": "PVC",
        "paper_value": "poly(vinyl chloride) (PVC)",
    }

    decision = match_audit_row(row, build_candidate_index(final))

    assert decision["match_status"] == "composite_match"
    assert decision["parts"]["name"]["collection"] == "polymer_entities"


def test_name_and_value_objects_combine_through_sample_anchor() -> None:
    final = {
        "samples": [{"sample_id": "s1", "sample_label_raw": "COC/CB3"}],
        "specialized_property_observations": [{
            "specialized_id": "sp1",
            "semantic_label": "electric conductivity",
            "value_raw": "1.0",
            "unit_raw": "S/cm",
            "sample_id": "s1",
        }],
    }
    row = {
        "audit_domain": "样品身份与电学性质",
        "polyinfo_field": "electric conductivity",
        "paper_sample": "COC/CB3",
        "paper_value": "1.0 S/cm",
    }

    decision = match_audit_row(row, build_candidate_index(final))

    assert decision["match_status"] == "composite_match"
    assert decision["match_tier"] == "cross_object"
    assert decision["parts"]["name"]["collection"] == "samples"
    assert decision["parts"]["value"]["collection"] == "specialized_property_observations"
    assert any(anchor["type"] == "sample_id" for anchor in decision["anchors"])


def test_method_and_condition_object_are_joined_via_property_anchor() -> None:
    final = {
        "property_observations": [{
            "property_id": "p1",
            "property_name_raw": "glass transition temperature",
            "value_raw": "100",
            "unit_raw": "°C",
            "measurement_condition_id": "mc1",
            "sample_id": "s1",
        }],
        "characterizations": [{
            "characterization_id": "c1",
            "method_raw": "Differential scanning calorimetry",
            "derived_property_ids": ["p1"],
            "sample_id": "s1",
            "measurement_context": {"temperature": "25 °C"},
        }],
    }
    row = {
        "audit_domain": "性质测量",
        "polyinfo_field": "glass transition temperature",
        "paper_value": "DSC at 25 °C: Tg=100 °C",
    }

    decision = match_audit_row(row, build_candidate_index(final))

    assert decision["match_status"] == "composite_match"
    assert decision["parts"]["method"]["collection"] == "characterizations"


def test_common_evidence_and_table_anchor_joins_name_and_value() -> None:
    final = {
        "samples": [{
            "sample_id": "s1",
            "sample_label_raw": "MET-2/20",
            "evidence": [{
                "evidence_id": "ev7",
                "table_locator": {
                    "table_id": "t1",
                    "row_index": 2,
                    "cell_id": "t1-r2-c3",
                },
            }],
        }],
        "specialized_property_observations": [{
            "specialized_id": "sp1",
            "semantic_label": "tensile strength",
            "value_raw": "50",
            "unit_raw": "MPa",
            "evidence": [{
                "evidence_id": "ev7",
                "table_locator": {
                    "table_id": "t1",
                    "row_index": 2,
                    "cell_id": "t1-r2-c3",
                },
            }],
        }],
    }
    row = {
        "audit_domain": "样品身份与力学性质",
        "polyinfo_field": "tensile strength",
        "paper_sample": "MET-2/20",
        "paper_value": "50 MPa",
    }

    decision = match_audit_row(row, build_candidate_index(final))

    assert decision["match_status"] == "composite_match"
    assert decision["parts"]["name"]["collection"] == "samples"
    assert decision["parts"]["value"]["collection"] == "specialized_property_observations"
    assert any(anchor["type"] == "evidence_id" for anchor in decision["anchors"])
    assert any(anchor["type"] == "table_id" for anchor in decision["anchors"])


def test_same_number_without_shared_anchor_is_not_combined() -> None:
    final = {
        "samples": [{"sample_id": "s1", "sample_label_raw": "NBR43"}],
        "property_observations": [{
            "property_id": "p1",
            "property_name_raw": "tensile strength",
            "value_raw": "50",
            "unit_raw": "MPa",
            "sample_id": "s2",
        }],
    }
    row = {
        "audit_domain": "样品身份和性质",
        "polyinfo_field": "tensile strength",
        "paper_sample": "NBR43",
        "paper_value": "50 MPa",
    }

    decision = match_audit_row(row, build_candidate_index(final))

    assert decision["match_status"] == "unmatched"
    assert decision["reasons"] == ["name_value_without_shared_anchor"]


def test_unlinked_evidence_is_reported_separately() -> None:
    final = {
        "evidence": [{
            "evidence_id": "ev1",
            "block_id": "P_1_35",
            "source_sentence": "uniform film thickness of 400–800 μm",
        }],
    }
    row = {
        "audit_domain": "样品状态/加工",
        "polyinfo_field": "processing_information",
        "paper_value": "uniform film thickness of 400–800 μm",
    }

    decision = match_audit_row(row, build_candidate_index(final))

    assert decision["match_status"] == "evidence_only"
    assert decision["match_tier"] == "evidence_only"
    assert decision["parts"]["evidence"]["collection"] == "evidence"


def test_primary_value_keeps_decimals_and_excludes_standard_numbers() -> None:
    row = {
        "polyinfo_field": "oxygen_index",
        "polyinfo_value": '{"oxygen_index": 26, "standard": "ASTM D2863-77"}',
        "paper_value": "LOI=26; ASTM D-2863-77",
    }

    assert numbers("0.77 dL/g") == [0.77]
    assert describe_audit_row(row).primary_numbers == (26.0,)
