import json
from pathlib import Path

from web_api.app import _display_text, _polyinfo_properties, _select_batch_root


def _write_index(root: Path, result_date: str, generated_at: str = "") -> None:
    root.mkdir(parents=True)
    (root / "RESULT_INDEX.json").write_text(
        json.dumps({"result_date": result_date, "generated_at": generated_at}),
        encoding="utf-8",
    )


def test_selects_newest_indexed_collection(tmp_path: Path) -> None:
    _write_index(tmp_path / "older", "2026-08-08")
    _write_index(tmp_path / "newer", "2026-08-09")

    root, index = _select_batch_root(tmp_path)

    assert root.name == "newer"
    assert index["result_date"] == "2026-08-09"


def test_explicit_collection_overrides_newest(tmp_path: Path) -> None:
    _write_index(tmp_path / "pinned", "2026-08-08")
    _write_index(tmp_path / "newer", "2026-08-09")

    root, _ = _select_batch_root(tmp_path, "pinned")

    assert root.name == "pinned"


def test_ignores_invalid_and_unsafe_collection_names(tmp_path: Path) -> None:
    (tmp_path / "invalid").mkdir()
    _write_index(tmp_path / "valid", "2026-08-09")

    root, _ = _select_batch_root(tmp_path, "../invalid")

    assert root.name == "valid"


def test_formats_nested_polyinfo_measurement_conditions_as_text() -> None:
    conditions = [
        {
            "solution_viscosity_measurement_condition": "Solvent",
            "solution_viscosity_measurement_condition_information": "DMF",
        },
        {
            "solution_viscosity_measurement_condition": "Concentration",
            "solution_viscosity_measurement_condition_information": "0.5 g/dL",
        },
    ]

    assert _display_text(conditions) == "Solvent: DMF; Concentration: 0.5 g/dL"


def test_polyinfo_property_api_never_returns_structured_method_or_condition() -> None:
    sample = {
        "sample_id": "sample-1",
        "polymer_id": "P000001",
        "property": [],
        "average_molecular_weight": [],
        "solution_viscosity": {
            "solution_viscosity_kind": "eta inh",
            "solution_viscosity_min": 1.2,
            "solution_viscosity_unit": "dL/g",
            "solution_viscosity_measurement_method": ["Ubbelohde viscometer"],
            "solution_viscosity_measurement_conditions": [
                {
                    "solution_viscosity_measurement_condition": "Temp.",
                    "solution_viscosity_measurement_condition_information": "25 C",
                }
            ],
        },
    }

    [property_record] = _polyinfo_properties([sample])

    assert property_record["method"] == "Ubbelohde viscometer"
    assert property_record["condition"] == "Temp.: 25 C"
