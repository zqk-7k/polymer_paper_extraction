from __future__ import annotations

import json

import pytest
import yaml

from tools.build_standard_property_codes import (
    DEFAULT_REGISTRY, DEFAULT_SCHEMA, DEFAULT_STANDARD,
    build, file_hash, load_registry, map_record, read_standard,
)


@pytest.fixture
def mapper():
    _, aliases = load_registry()
    schema = yaml.safe_load(DEFAULT_SCHEMA.read_text(encoding="utf-8"))

    def resolve(raw, reviewed, unit=None, **overrides):
        row = {
            "全局序号": 1, "论文编号": "reference_no_test", "样品ID": "sample1",
            "锚点ID": "reference_no_test:sample1:property:1", "_excel_row": 2,
            "性质名称": raw, "原文复核后规范性质名": reviewed,
            "原文复核后规范单位": unit, "原文复核状态": "原文数值已找到",
            "主评估纳入_v2": "是", "数值最小": 42, "数值最大": 42,
            **overrides,
        }
        return map_record(row, aliases, schema["property_vocabulary"], schema["specialized_property_vocabulary"])

    return resolve


def test_polyinfo_group_codes_do_not_collapse_distinct_properties(mapper):
    temperature = mapper("Thermal decomposition temperature", "thermal decomposition temperature", "c")
    loss = mapper("Thermal decomposition weight loss", "thermal_decomposition_weight_loss", "%")
    assert temperature["polyinfo_group_code"] == loss["polyinfo_group_code"] == "P3170"
    assert temperature["standard_property_code"] != loss["standard_property_code"]


def test_molecular_weight_statistics_and_dispersity_stay_distinct(mapper):
    codes = {
        mapper("Mn", "mn")["standard_property_code"],
        mapper("Mw", "mw")["standard_property_code"],
        mapper("Molecular weight dispersity (Mw/Mn)", "molecular_weight_distribution")["standard_property_code"],
    }
    assert len(codes) == 3 and None not in codes
    assert mapper("MW", "mw")["standard_property_code"] is None
    assert mapper("MW of PAA", "mw of paa")["standard_property_code"] is None
    assert mapper("Mw distribution curve", "molecular_weight_distribution")["standard_property_code"] is None


def test_reviewed_unknown_can_map_without_guessing_mn_or_mw(mapper):
    result = mapper("Unknown", "average_molecular_weight", "g/mol")
    assert result["standard_property_code"] == "STD:average_molecular_weight_unspecified"
    assert result["property_name_raw"] == "Unknown"


def test_blank_reviewed_column_does_not_fallback_to_old_suggestion(mapper):
    result = mapper("Tg", None, "c", **{"建议规范性质名_v2": "glass transition temperature"})
    assert result["standard_property_code"] is None
    assert result["mapping_status"] == "unresolved"


def test_review_unit_conflict_is_not_given_confirmed_code(mapper):
    result = mapper("Td (wt. loss at 800C)", "thermal decomposition temperature", "%")
    assert result["standard_property_code"] is None
    assert result["proposed_standard_property_code"] == "STD:thermal_decomposition_temperature"
    assert "reviewed_property_unit_conflict" in result["review_flags"]


def test_compound_review_splits_dc_conductivity_with_condition(mapper):
    result = mapper("DC conductivity after 2h UV exposure", None, "1/(ohm*cm)", **{"原文复核状态": "原文确认-待拆列"})
    assert result["standard_property_code"] == "STD:electric_conductivity"
    assert result["qualifiers"]["uv_exposure"] == "after_2h"
    assert "compound_column_split_deterministic" in result["review_flags"]


def test_uv_pl_and_surface_components_split_deterministically(mapper):
    uv = mapper("UV-vis and PL(max. in THF)", None, "nm", **{"原文复核状态": "原文确认-待拆列", "数值分量序号": 0})
    pl = mapper("UV-vis and PL(max. in THF)", None, "nm", **{"原文复核状态": "原文确认-待拆列", "数值分量序号": 1})
    polar = mapper("Surface tension (polar and dispersive force)", "surface tension polar and dispersive force", "mN/m", **{"原文复核状态": "原文确认-待分量", "数值分量序号": 0})
    dispersive = mapper("Surface tension (polar and dispersive force)", "surface tension polar and dispersive force", "mN/m", **{"原文复核状态": "原文确认-待分量", "数值分量序号": 1})
    assert uv["standard_property_code"] == "STD:absorption_wavelength"
    assert pl["standard_property_code"] == "STD:emission_wavelength"
    assert polar["standard_property_code"] == "STD:surface_tension_polar"
    assert dispersive["standard_property_code"] == "STD:surface_tension_dispersive"


def test_surface_component_keeps_code_while_retaining_review_flag(mapper):
    result = mapper("Surface tension", "surface tension", "mn/m", **{"性质变体_v2": "total_or_polar_or_dispersive"})
    assert result["standard_property_code"] == "STD:surface_tension"
    assert result["mapping_status"] == "mapped"
    assert "surface_component_unresolved" in result["review_flags"]


def test_process_information_gets_status_and_identity_but_no_property_code(mapper):
    result = mapper("Treatment condition", None, "c", **{"原文复核状态": "原文确认-过程信息"})
    assert result["mapping_status"] == "out_of_scope"
    assert result["standard_record_id"]
    assert result["standard_property_code"] is None


def test_exact_aliases_preserve_specificity_and_qualifiers(mapper):
    at_break = mapper("Tensile strength at break", "tensile strength at break", "mpa")
    stress = mapper("Tensile stress at break", "tensile stress at break", "mpa")
    generic = mapper("Tensile strength", "tensile strength", "mpa")
    assert at_break["standard_property_code"] == stress["standard_property_code"]
    assert generic["standard_property_code"] != stress["standard_property_code"]
    assert mapper("Log tensile strength", "log tensile strength", "mpa")["standard_property_code"] is None
    first = mapper("Tg1", "tg1", "c")
    second = mapper("Tg2", "tg2", "c")
    assert first["standard_property_code"] == second["standard_property_code"]
    assert first["qualifiers"] != second["qualifiers"]
    assert mapper("Dielectric constant AC", "dielectric constant ac")["pipeline_property_name"] is None


def test_registry_rejects_alias_collisions(tmp_path):
    registry = json.loads(DEFAULT_REGISTRY.read_text(encoding="utf-8"))
    registry["entries"][1]["aliases"].append("izod impact")
    path = tmp_path / "bad_registry.json"
    path.write_text(json.dumps(registry), encoding="utf-8")
    with pytest.raises(ValueError, match="Ambiguous alias"):
        load_registry(path)


@pytest.mark.skipif(not DEFAULT_STANDARD.exists(), reason="Local reviewed standard workbook not present")
def test_reviewed_workbook_readonly_reproducible_full_record_export(tmp_path):
    before = file_hash(DEFAULT_STANDARD)
    source, _ = read_standard(DEFAULT_STANDARD)
    summary = build(DEFAULT_STANDARD, DEFAULT_REGISTRY, DEFAULT_SCHEMA, tmp_path)
    content = (tmp_path / "standard_property_codes.jsonl").read_bytes()
    output = [json.loads(line) for line in content.splitlines()]
    assert summary["records"] == len(source) == len(output) == 1542
    assert summary["documents"] == 29
    assert len({r["standard_record_id"] for r in output}) == 1542
    assert sum(summary["mapping_status_counts"].values()) == 1542
    assert all(r["standard_property_code"] is None for r in output if r["mapping_status"] != "mapped")
    assert all(r["standard_property_code"] is not None for r in output if r["mapping_status"] == "mapped")
    source_by_id = {r["全局序号"]: r for r in source}
    for r in output:
        original = source_by_id[r["source_global_id"]]
        assert (r["value_min"], r["value_max"]) == (original["数值最小"], original["数值最大"])
        assert r["evidence_excerpt"] == original["证据摘录"]
    build(DEFAULT_STANDARD, DEFAULT_REGISTRY, DEFAULT_SCHEMA, tmp_path)
    assert content == (tmp_path / "standard_property_codes.jsonl").read_bytes()
    assert file_hash(DEFAULT_STANDARD) == before
