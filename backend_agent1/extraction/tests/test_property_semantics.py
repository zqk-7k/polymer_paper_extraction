from __future__ import annotations

from stages.property_semantics import (
    default_official_vocabulary,
    resolve_property_surface,
)
from stages.specialized_vocabulary import get_specialized_vocabulary


def _resolve(name: str, *, context: str = "", value: str = ""):
    return resolve_property_surface(
        name,
        context=context,
        value_text=value,
        official_vocabulary=default_official_vocabulary(),
        specialized_vocabulary=get_specialized_vocabulary(),
        stage="stage4t",
    )


def test_formula_molecular_weight_uses_specialized_route() -> None:
    result = _resolve(r"M̄_n", context="GPC")
    assert result.status == "specialized"
    assert result.specialized_property_key == "molecular_weight"


def test_pdi_is_not_promoted_to_average_molecular_weight() -> None:
    result = _resolve("Mw/Mn", context="GPC")
    assert result.status == "outside_vocab"
    assert result.reason == "molecular_weight_distribution_not_publishable"


def test_weight_loss_requires_thermal_context() -> None:
    assert _resolve("weight loss", value="19%").status == "ambiguous"
    result = _resolve("weight loss", context="TGA thermal decomposition", value="10%")
    assert result.status == "official"
    assert result.official_property == "thermal_decomposition_weight_loss"


def test_yield_remains_ambiguous_without_measurement_context() -> None:
    result = _resolve("Yield", value="87%")
    assert result.status == "ambiguous"


def test_generic_eta_is_not_assumed_to_be_intrinsic_viscosity() -> None:
    result = _resolve("η", context="viscosity", value="1.2")
    assert result.status == "ambiguous"


def test_yield_variant_requires_mechanical_context() -> None:
    assert _resolve("yield strength", value="42 MPa").status == "ambiguous"
    result = _resolve("yield strength", context="tensile test", value="42 MPa")
    assert result.status == "official"
    assert result.official_property == "tensile_stress_at_yield"


def test_specific_gravity_uses_density_context_when_available() -> None:
    assert _resolve("specific gravity", value="1.05").status == "ambiguous"
    assert _resolve("specific gravity", context="Specific gravity").status == "ambiguous"
    result = _resolve("specific gravity", context="density measured by ASTM D792")
    assert result.status == "official"
    assert result.official_property == "density"


def test_dsc_generic_enthalpy_requires_event_context() -> None:
    assert _resolve("ΔH", context="DSC", value="25 J/g").status == "ambiguous"
    fusion = _resolve("ΔH", context="DSC melting endotherm", value="25 J/g")
    assert fusion.status == "official"
    assert fusion.official_property == "heat_of_fusion"
    crystallization = _resolve(
        "exo enthalpy",
        context="DSC cooling crystallization",
        value="25 J/g",
    )
    assert crystallization.status == "official"
    assert crystallization.official_property == "heat_of_crystallization"


def test_dynamic_and_melt_viscosity_are_explicit_official_variants() -> None:
    dynamic = _resolve("dynamic viscosity", value="2 Pa s")
    assert dynamic.status == "official"
    assert dynamic.official_property == "dynamic_viscosity"
    melt = _resolve("melt viscosity", value="120 Pa s")
    assert melt.status == "official"
    assert melt.official_property == "melt_viscosity"
