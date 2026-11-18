import json

from tools.stage4t_table_completeness_audit import audit_document, build_summary


def test_table_completeness_distinguishes_dropped_and_present_columns(tmp_path) -> None:
    doc = tmp_path / "reference_no_test"
    doc.mkdir()
    (doc / "stage4t_shadow.json").write_text(json.dumps({
        "document_id": "reference_no_test",
        "tables": [{
            "table_id": "T1",
            "property_candidates": [
                {"column_index": 1, "property_name_raw": "Tg",
                 "property_name_normalized": "glass_transition_temperature",
                 "unit_normalized": "°C"},
                {"column_index": 2, "property_name_raw": "Td",
                 "property_name_normalized": "thermal_decomposition_temperature",
                 "unit_normalized": "°C"},
                {"column_index": 3, "property_name_raw": "NMR shift",
                 "property_name_normalized": None, "unit_normalized": "ppm"},
            ],
            "shadow_observations": [
                {"column_index": 1, "value_raw": "120"},
                {"column_index": 2, "value_raw": "350"},
                {"column_index": 3, "value_raw": "7.2"},
            ],
        }],
    }), encoding="utf-8")
    (doc / "final.json").write_text(json.dumps({
        "properties": [{
            "property_name_normalized": "glass_transition_temperature",
            "value_raw": "120",
            "publication_status": "published",
            "evidence": [{"table_locator": {
                "table_id": "T1", "column_index": 1,
            }}],
        }],
    }), encoding="utf-8")

    rows = audit_document(str(doc))
    statuses = {(row["column_index"], row["status"]) for row in rows}

    assert (1, "candidate_present") in statuses
    assert (2, "table_column_dropped") in statuses
    assert (3, "out_of_scope") in statuses
    assert build_summary(rows)["table_column_dropped"] == 1


def test_table_completeness_uses_header_evidence_for_components(tmp_path) -> None:
    doc = tmp_path / "reference_no_test"
    doc.mkdir()
    header = r"${\gamma}_{s}^{p}$ (mJ/m2)"
    (doc / "stage4t_shadow.json").write_text(json.dumps({
        "document_id": "reference_no_test",
        "tables": [{
            "table_id": "T1",
            "property_candidates": [{
                "column_index": 1, "property_name_raw": header,
                "property_name_normalized": None, "unit_normalized": "mJ/m²",
            }],
            "shadow_observations": [{"column_index": 1, "value_raw": "1.2"}],
        }],
    }), encoding="utf-8")
    (doc / "final.json").write_text(json.dumps({
        "specialized_property_observations": [{
            "value_raw": "1.2", "publication_status": "unresolved",
            "evidence": [{"table_locator": {
                "table_id": "T1", "column_index": 1,
                "column_label": header,
            }}],
        }],
    }), encoding="utf-8")

    row = audit_document(str(doc))[0]

    assert row["bucket"] == "surface_tension"
    assert row["surface_component"] == "polar"
    assert row["status"] == "candidate_unresolved"


def test_table_header_precedes_variant_metadata() -> None:
    from tools.stage4t_table_completeness_audit import _object_bucket

    obj = {
        "semantic_label": "thermal_decomposition_temperature",
        "variant": "mass_loss_threshold",
        "evidence": [{"table_locator": {
            "column_label": r"$T_d^{10\%}$ (°C)",
        }}],
    }
    assert _object_bucket(obj)[0] == "td"


def test_top_level_evidence_ids_and_property_observations_are_audited(tmp_path) -> None:
    doc = tmp_path / "reference_no_test"
    doc.mkdir()
    header = r"$T_d$ (°C)"
    (doc / "stage4t_shadow.json").write_text(json.dumps({
        "document_id": "reference_no_test",
        "tables": [{
            "table_id": "T1",
            "property_candidates": [{
                "column_index": 1,
                "property_name_raw": header,
                "property_name_normalized": "thermal_decomposition_temperature",
                "unit_normalized": "°C",
            }],
            "shadow_observations": [{"column_index": 1, "value_raw": "350"}],
        }],
    }), encoding="utf-8")
    (doc / "final.json").write_text(json.dumps({
        "property_observations": [{
            "property_name_normalized": "thermal_decomposition_temperature",
            "value_raw": "350",
            "publication_status": "published",
            "evidence_ids": ["ev1"],
        }],
        "evidence": [{
            "evidence_id": "ev1",
            "table_locator": {"table_id": "T1", "column_index": 1,
                               "column_label": header},
        }],
    }), encoding="utf-8")

    row = audit_document(str(doc))[0]

    assert row["status"] == "candidate_present"
