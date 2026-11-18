from stages.standard_mapping import resolve_standard_property
import pytest


@pytest.mark.parametrize("name,unit,code", [
    (r"$T_{g} (K)$", "K", "glass_transition_temperature"),
    (r"$\overline{M}_{w}$", "g/mol", "weight_average_molecular_weight"),
    (r"$T_g (^{\circ}C)$", "°C", "glass_transition_temperature"),
])
def test_formula_presentation_preserves_registered_meaning(name, unit, code):
    result = resolve_standard_property(name, unit)
    assert result["standard_status"] == "standard_alias", result
    assert result["standard_property_code"] == f"STD:{code}"


@pytest.mark.parametrize("name", [r"$T_{g,1}$", r"$T_{g}$ onset", r"$\gamma_s^p$", r"$M_w \times 10^3$"])
def test_formula_qualifiers_and_scales_are_not_erased(name):
    assert resolve_standard_property(name, "g/mol")["standard_status"] == "standard_unmapped"


def test_registered_canonical_name_with_compatible_unit_is_exact():
    result = resolve_standard_property("glass_transition_temperature", "°C")
    assert result["standard_status"] == "standard_exact"
    assert result["standard_property_code"] == "STD:glass_transition_temperature"
    assert result["unit_status"] == "confirmed"


def test_registered_display_alias_is_alias_mapping():
    result = resolve_standard_property("Tg", "C")
    assert result["standard_status"] == "standard_alias"
    assert result["standard_property_code"] == "STD:glass_transition_temperature"

    annotated = resolve_standard_property("Tg (°C)", "C")
    assert annotated["standard_status"] == "standard_alias"
    assert "unit_annotation_in_property_name" in annotated["mapping_reasons"]


def test_missing_or_conflicting_units_stay_candidates():
    missing = resolve_standard_property("Tg")
    conflict = resolve_standard_property("Tg", "MPa")
    assert missing["standard_status"] == "standard_candidate"
    assert "unit_missing" in missing["mapping_reasons"]
    assert conflict["standard_status"] == "standard_candidate"
    assert "unit_family_conflict" in conflict["mapping_reasons"]


def test_unknown_name_is_unmapped_without_guessing():
    result = resolve_standard_property("thermal mystery property", "°C")
    assert result["standard_status"] == "standard_unmapped"
    assert result["standard_property_code"] is None


def test_annotation_conflict_and_registry_review_flags_are_not_confirmed():
    assert resolve_standard_property("Tg (MPa)", "C")["standard_status"] == "standard_candidate"
    assert resolve_standard_property("Tg (K)", "C")["unit_status"] == "unit_conflict"
    assert resolve_standard_property("tensile strength", "MPa")["standard_status"] == "standard_candidate"
    assert resolve_standard_property("MW", "g/mol")["standard_status"] == "standard_candidate"
    assert resolve_standard_property("MW (g/mol)", "g/mol")["standard_status"] == "standard_candidate"
    assert resolve_standard_property("Mw", "g/mol")["standard_status"] == "standard_alias"
    assert resolve_standard_property("degree of polymerization")["unit_status"] == "unit_unresolved"


@pytest.mark.parametrize("name,unit,code", [(r"$T_g/°C$", "°C", "glass_transition_temperature"),
    ("Tm/°C", "°C", "melting_temperature"), ("Mw/g/mol", "g/mol", "weight_average_molecular_weight"),
    ("Mw/(g/mol)", "g/mol", "weight_average_molecular_weight")])
def test_registered_property_slash_unit_is_preserved_and_source_discoverable(name, unit, code):
    from stages.standard_mapping import units_in_text
    result = resolve_standard_property(name, unit)
    assert result["standard_property_code"] == "STD:" + code
    assert result["unit_status"] == "confirmed"
    assert result["standard_status"] == "standard_alias"
    assert unit in units_in_text(name)


@pytest.mark.parametrize("name", ["Tg/°C^a", "Tg/°C ×10^3", "Tg onset/°C", "unknown/°C"])
def test_slash_mapping_does_not_erase_qualifiers(name):
    assert resolve_standard_property(name, "°C")["standard_status"] == "standard_unmapped"


def test_slash_annotation_mismatch_and_statistic_ambiguity_are_not_accepted():
    assert resolve_standard_property("Tg/K", "°C")["unit_status"] == "unit_conflict"
    assert resolve_standard_property("MW/g/mol", "g/mol")["standard_status"] == "standard_candidate"
