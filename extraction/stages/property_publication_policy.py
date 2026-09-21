"""Deterministic safety policy for Stage 4 publication recovery.

The policy deliberately knows nothing about PoLyInfo or evaluation gold data.
It only decides whether an already extracted table candidate has sufficiently
direct evidence and internally compatible property, value, and unit fields.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Mapping


POLICY_VERSION = "stage4p-direct-table-policy/1.2.0"
DISPLAY_MULTIPLIER_INTERPRETATION = (
    "display_value_equals_physical_value_times_10^n"
)

PROPERTY_FAMILIES = frozenset({
    "contact_angle",
    "crystallinity",
    "crystallization_temperature",
    "degree_of_polymerization",
    "dielectric_constant",
    "electric_conductivity",
    "elongation_at_break",
    "glass_transition_temperature",
    "heat_of_fusion",
    "impact_strength",
    "inherent_viscosity",
    "intrinsic_viscosity",
    "reduced_viscosity",
    "specific_viscosity",
    "izod_impact",
    "lattice_spacing",
    "liquid_crystal_transition_temperature",
    "loss_tangent",
    "melting_temperature",
    "mn",
    "molar_mass",
    "mw",
    "optical_spectral_maximum",
    "oxygen_index",
    "photoluminescence_maximum",
    "polydispersity_index",
    "refractive_index",
    "solution_viscosity",
    "softening_temperature",
    "storage_modulus",
    "surface_energy",
    "tensile_modulus",
    "tensile_strength",
    "thermal_decomposition_temperature",
    "thermal_decomposition_weight_loss",
    "uv_vis_absorption_maximum",
    "vicat_softening_temperature",
    "water_absorption",
})

DIMENSIONLESS_FAMILIES = frozenset({
    "degree_of_polymerization",
    "dielectric_constant",
    "loss_tangent",
    "polydispersity_index",
    "refractive_index",
})
TEMPERATURE_FAMILIES = frozenset({
    "crystallization_temperature",
    "glass_transition_temperature",
    "liquid_crystal_transition_temperature",
    "melting_temperature",
    "softening_temperature",
    "thermal_decomposition_temperature",
    "vicat_softening_temperature",
})
PERCENT_FAMILIES = frozenset({
    "crystallinity",
    "elongation_at_break",
    "oxygen_index",
    "thermal_decomposition_weight_loss",
    "water_absorption",
})


@dataclass(frozen=True)
class QuantityDecision:
    accepted: bool
    reason: str
    property_name: str
    value_min: float | None = None
    value_max: float | None = None
    unit_raw: str | None = None
    unit_normalized: str | None = None
    molecular_weight_type: str | None = None


def compact(value: Any) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"\\(?:mathrm|text|operatorname)\s*\{([^{}]*)\}", r" \1 ", text)
    return re.sub(r"[^a-z0-9%\u4e00-\u9fff]+", " ", text).strip()


def canonical_property(candidate: Mapping[str, Any]) -> str:
    """Map an extracted semantic label to a conservative property family."""

    normalized = str(candidate.get("property_name_normalized") or "").strip()
    if normalized in PROPERTY_FAMILIES:
        return normalized

    semantic = str(candidate.get("semantic_label") or "").strip().casefold()
    variant = str(candidate.get("property_variant") or "").strip().casefold()
    if semantic == "molecular_weight":
        if variant == "number_average":
            return "mn"
        if variant == "weight_average":
            return "mw"
        return "molar_mass"
    if semantic in {"molecular_weight_distribution", "dispersity"}:
        return "polydispersity_index"
    if semantic == "degree_of_polymerization":
        return "degree_of_polymerization"
    if semantic == "crystallinity":
        return "crystallinity"
    if semantic in {"d_spacing", "interplanar_spacing"}:
        return "lattice_spacing"
    if semantic == "solution_viscosity":
        if variant == "inherent":
            return "inherent_viscosity"
        if variant == "intrinsic":
            return "intrinsic_viscosity"
        if variant == "reduced":
            return "reduced_viscosity"
        if variant == "specific":
            return "specific_viscosity"
        return "solution_viscosity"

    raw = " ".join(str(candidate.get(key) or "") for key in (
        "property_name_raw", "semantic_label", "property_variant",
    ))
    text = compact(raw)
    aliases = (
        (r"(?:^| )pdi(?: |$)|polydispersity|dispersity|m w m n", "polydispersity_index"),
        (r"number average molecular weight|(?:^| )m n(?: |$)", "mn"),
        (r"weight average molecular weight|(?:^| )m w(?: |$)", "mw"),
        (r"degree of polymerization|(?:^| )dpn?(?: |$)", "degree_of_polymerization"),
        (r"glass transition|(?:^| )t g(?: |$)", "glass_transition_temperature"),
        (r"melting (?:temperature|point)|(?:^| )t m(?: |$)", "melting_temperature"),
        (r"crystalli[sz]ation temperature|(?:^| )t c(?: |$)", "crystallization_temperature"),
        (r"thermal decomposition|decomposition temperature|(?:^| )t d(?: |$)", "thermal_decomposition_temperature"),
        (r"degree of crystallinity|(?:^| )crystallinity(?: |$)", "crystallinity"),
        (r"d spacing|lattice spacing|interplanar spacing", "lattice_spacing"),
        (r"surface free energy|surface energy|surface tension", "surface_energy"),
        (r"contact angle", "contact_angle"),
        (r"tensile modulus|young s modulus", "tensile_modulus"),
        (r"tensile (?:strength|stress)", "tensile_strength"),
        (r"elongation at break", "elongation_at_break"),
        (r"storage modulus", "storage_modulus"),
        (r"inherent viscosity", "inherent_viscosity"),
        (r"intrinsic viscosity", "intrinsic_viscosity"),
        (r"reduced viscosity", "reduced_viscosity"),
        (r"specific viscosity", "specific_viscosity"),
        (r"solution viscosity", "solution_viscosity"),
        (r"absorption maximum|lambda max|uv vis", "uv_vis_absorption_maximum"),
        (r"emission maximum|lambda em|photoluminescence", "photoluminescence_maximum"),
        (r"water absorption|water uptake", "water_absorption"),
        (r"electric conductivity|electrical conductivity", "electric_conductivity"),
        (r"dielectric constant", "dielectric_constant"),
        (r"oxygen index", "oxygen_index"),
    )
    for pattern, family in aliases:
        if re.search(pattern, text):
            return family
    return ""


def looks_like_property_or_condition_label(label: Any, property_name: str = "") -> bool:
    text = compact(label)
    if not text:
        return False
    if text == compact(property_name).replace("_", " "):
        return True
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?(?: c| k| hz| mpa| gpa| %)?", text):
        return True
    return bool(re.search(
        r"(?:^| )(?:tg|tm|tc|td|t g|t m|t c|t d|temperature|frequency|pressure|humidity|"
        r"modulus|strength|elongation|contact angle|surface energy|weight loss|"
        r"viscosity|conductivity|crystallinity|annealed|treated|as processed)(?: |$)",
        text,
    ))


def looks_like_material_label(label: Any) -> bool:
    text = compact(label)
    if not text or not re.search(r"[a-z\u4e00-\u9fff]", text):
        return False
    if looks_like_property_or_condition_label(label):
        return False
    return not bool(re.fullmatch(r"c|k|hz|mpa|gpa|%|nm|cm|w|j g", text))


def _replace_scientific(match: re.Match[str]) -> str:
    return str(float(match.group(1)) * (10 ** int(match.group(2))))


def numeric_values(surface: Any) -> list[float]:
    raw = str(surface or "")
    raw = re.sub(
        r"([-+]?\d+(?:\.\d+)?)\s*(?:\\times|×|x|\*)\s*10\s*\^?\s*\{?\s*([-+]?\d+)\s*\}?",
        _replace_scientific,
        raw,
        flags=re.I,
    )
    raw = re.sub(
        r"(?<![\d.])(\d{1,3}(?:[ ]\d{3})+)(?!\d)",
        lambda match: match.group(1).replace(" ", ""),
        raw,
    )
    raw = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", raw)
    result: list[float] = []
    for token in re.findall(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", raw):
        try:
            number = float(token)
        except ValueError:
            continue
        if math.isfinite(number):
            result.append(number)
    return result


def is_qualified_or_multivalue(surface: Any) -> bool:
    raw = str(surface or "").strip()
    if not raw:
        return True
    if re.search(r"(?:^|\s)(?:<=|>=|<|>|≈|~|≤|≥)", raw):
        return True
    if "±" in raw or "+/-" in raw:
        return True
    if re.search(r"\d\s*(?:–|—|~|至)\s*[-+]?\d", raw):
        return True
    if re.search(r"\d\s*[-]\s*\d", raw):
        return True
    without_thousands = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", raw)
    if "," in without_thousands and len(numeric_values(without_thousands)) > 1:
        return True
    if re.search(r"\d\s*/\s*\d", raw):
        return True
    if re.search(r"\d\s*(?:\*|†|‡)\s*$", raw):
        return True
    return False


def number_close(left: float, right: float) -> bool:
    return abs(left - right) <= max(1e-8, abs(left) * 0.005, abs(right) * 0.005)


def _unit_surface(candidate: Mapping[str, Any], header: str) -> str:
    return " ".join(str(candidate.get(key) or "") for key in (
        "unit_normalized", "unit_raw", "property_name_raw",
    )) + " " + str(header or "")


def _crystallinity_percent_is_supported(
    candidate: Mapping[str, Any],
    property_header: str,
) -> bool:
    """Require a traceable source for a crystallinity percent unit."""

    if "%" in str(property_header or ""):
        return True
    if "%" in str(candidate.get("property_name_raw") or ""):
        return True
    unit = str(candidate.get("unit_normalized") or candidate.get("unit_raw") or "")
    location = str(candidate.get("unit_location") or "")
    if location == "caption":
        return "%" in unit
    return (
        location == "inferred_property_convention"
        and candidate.get("unit_inference_basis")
        == "degree_crystallinity_column_0_100"
        and "%" in unit
    )


def _temperature_unit(surface: str) -> str | None:
    lowered = surface.casefold()
    if "℃" in surface or re.search(r"(?:°|º|�|掳)\s*c", lowered):
        return "°C"
    text = compact(surface)
    if text in {"c", "degc", "deg c", "degree c", "degrees c", "celsius"}:
        return "°C"
    if re.search(r"(?:^| )(?:deg(?:ree)? c|celsius)(?: |$)", text):
        return "°C"
    if re.search(r"(?:^| )k(?: |$)", text):
        return "K"
    return None


def _explicit_unit(family: str, surface: str) -> str | None:
    text = compact(surface)
    raw = surface.casefold()
    if family in TEMPERATURE_FAMILIES:
        return _temperature_unit(surface)
    if family in PERCENT_FAMILIES:
        return "%" if "%" in surface else None
    if family in {"mn", "mw", "molar_mass"}:
        return "g/mol" if re.search(r"g\s*/?\s*mol", raw) else None
    if family in {
        "inherent_viscosity", "intrinsic_viscosity", "reduced_viscosity",
        "specific_viscosity", "solution_viscosity",
    }:
        return "dL/g" if re.search(r"d\s*l\s*/\s*g", raw) else None
    if family == "contact_angle":
        return "degree" if re.search(r"degree|deg|°|º|�|掳", raw) else None
    if family == "lattice_spacing":
        if "angstrom" in text or "å" in raw or "Å" in surface:
            return "angstrom"
        return "nm" if re.search(r"(?:^| )nm(?: |$)", text) else None
    if family in {"tensile_modulus", "tensile_strength", "storage_modulus"}:
        if re.search(r"(?:^| )gpa(?: |$)", text):
            return "GPa"
        return "MPa" if re.search(r"(?:^| )mpa(?: |$)", text) else None
    if family == "surface_energy":
        if re.search(r"mj\s*/\s*m\s*(?:\^?2|²)", raw):
            return "mJ/m²"
        return "mN/m" if re.search(r"mn\s*/\s*m", raw) else None
    if family == "heat_of_fusion":
        if re.search(r"kj\s*/\s*mol", raw):
            return "kJ/mol"
        return "J/g" if re.search(r"j\s*/\s*g", raw) else None
    if family in {"impact_strength", "izod_impact"}:
        return "kJ/m²" if re.search(r"kj\s*/\s*m\s*(?:\^?2|²)", raw) else None
    if family == "electric_conductivity":
        return "S/cm" if re.search(r"s\s*/\s*cm", raw) else None
    if family in {
        "optical_spectral_maximum", "photoluminescence_maximum",
        "uv_vis_absorption_maximum",
    }:
        return "nm" if re.search(r"(?:^| )nm(?: |$)", text) else None
    return None


def _scale_exponent(surface: str) -> int | None:
    match = re.search(r"10\s*\^?\s*\{?\s*([-+]?\d+)\s*\}?", surface)
    if not match:
        return None
    exponent = int(match.group(1))
    return exponent if -9 <= exponent <= 9 and exponent != 0 else None


def _flat_unit_surface(value: Any) -> str:
    text = str(value or "")
    for _ in range(3):
        text = re.sub(
            r"\\(?:text|mathrm|operatorname)\s*\{([^{}]*)\}",
            r"\1",
            text,
        )
    text = text.replace("\\Omega", "ohm").replace("Ω", "ohm")
    text = text.replace("−", "-").replace("–", "-")
    return re.sub(r"[\s${}]", "", text).casefold()


def _has_reciprocal_ohm_cm(value: Any) -> bool:
    return bool(re.search(
        r"ohm(?:\^)?-1(?:[*/·]?)cm(?:\^)?-1",
        _flat_unit_surface(value),
    ))


def _explicit_display_scale(
    candidate: Mapping[str, Any],
    *,
    family: str,
    unit_surface: str,
) -> tuple[float, str | None]:
    """Validate an upstream display-multiplier contract.

    Generic ``10^n`` text is deliberately insufficient: exponent direction
    differs across scientific table conventions.  At present inverse scaling
    is accepted only for an electric-conductivity column with a reciprocal
    ohm-centimetre unit and the complete Stage 4T metadata triplet.
    """

    fields = (
        candidate.get("display_multiplier_exponent"),
        candidate.get("value_scale_factor"),
        candidate.get("scale_interpretation"),
    )
    if all(value is None for value in fields):
        return 1.0, None
    exponent, factor, interpretation = fields
    if family != "electric_conductivity":
        return 1.0, "display_scale_property_not_supported"
    if interpretation != DISPLAY_MULTIPLIER_INTERPRETATION:
        return 1.0, "display_scale_interpretation_invalid"
    if (
        not isinstance(exponent, int)
        or isinstance(exponent, bool)
        or not 1 <= exponent <= 18
    ):
        return 1.0, "display_scale_exponent_invalid"
    if (
        not isinstance(factor, (int, float))
        or isinstance(factor, bool)
        or not math.isfinite(float(factor))
    ):
        return 1.0, "display_scale_factor_invalid"
    expected = 10.0 ** (-exponent)
    if not math.isclose(float(factor), expected, rel_tol=1e-12, abs_tol=0.0):
        return 1.0, "display_scale_factor_inconsistent"
    if not _has_reciprocal_ohm_cm(unit_surface):
        return 1.0, "display_scale_reciprocal_unit_missing"
    return expected, None


def decide_quantity(
    candidate: Mapping[str, Any],
    *,
    cell_text: str,
    header: str = "",
) -> QuantityDecision:
    """Validate and normalize one direct table scalar."""

    family = canonical_property(candidate)
    if not family:
        return QuantityDecision(False, "property_family_unresolved", "")
    if family not in PROPERTY_FAMILIES:
        return QuantityDecision(False, "property_family_not_registered", family)
    if candidate.get("measurement_role") == "calculated":
        return QuantityDecision(False, "calculated_value_not_released", family)
    if candidate.get("value_has_footnote") is True:
        return QuantityDecision(False, "value_footnote_unresolved", family)
    value_kind = str(candidate.get("value_kind") or "numeric_scalar")
    if value_kind != "numeric_scalar":
        return QuantityDecision(False, "non_scalar_value_not_released", family)
    if is_qualified_or_multivalue(cell_text):
        return QuantityDecision(False, "qualified_or_multivalue_cell", family)

    candidate_min = candidate.get("value_min")
    candidate_max = candidate.get("value_max")
    parsed = numeric_values(candidate.get("value_raw"))
    if candidate_min is None:
        candidate_min = parsed[0] if len(parsed) == 1 else None
    if candidate_max is None:
        candidate_max = candidate_min
    if not isinstance(candidate_min, (int, float)) or isinstance(candidate_min, bool):
        return QuantityDecision(False, "numeric_value_missing", family)
    if not isinstance(candidate_max, (int, float)) or isinstance(candidate_max, bool):
        return QuantityDecision(False, "numeric_value_missing", family)
    value_min = float(candidate_min)
    value_max = float(candidate_max)
    if not math.isfinite(value_min) or not math.isfinite(value_max):
        return QuantityDecision(False, "numeric_value_non_finite", family)
    if not number_close(value_min, value_max):
        return QuantityDecision(False, "numeric_range_not_released", family)

    cell_numbers = numeric_values(cell_text)
    if len(cell_numbers) != 1:
        return QuantityDecision(False, "direct_cell_not_single_numeric", family)
    cell_value = cell_numbers[0]
    unit_surface = _unit_surface(candidate, header)
    provided_unit = str(
        candidate.get("unit_normalized") or candidate.get("unit_raw") or ""
    ).strip()
    # A valid unit in the header must not conceal an incompatible unit already
    # attached to the extracted object.  Such disagreement is a semantic
    # conflict, not a harmless missing-unit repair.
    if family in TEMPERATURE_FAMILIES and provided_unit:
        if _temperature_unit(provided_unit) is None:
            return QuantityDecision(False, "required_unit_missing_or_invalid", family)
    if family in PERCENT_FAMILIES and provided_unit and "%" not in provided_unit:
        return QuantityDecision(False, "required_unit_missing_or_invalid", family)
    if family == "crystallinity" and not _crystallinity_percent_is_supported(
        candidate,
        header,
    ):
        return QuantityDecision(False, "crystallinity_percent_source_unverified", family)
    display_scale, display_scale_error = _explicit_display_scale(
        candidate,
        family=family,
        unit_surface=unit_surface,
    )
    if display_scale_error:
        return QuantityDecision(False, display_scale_error, family)
    exponent = _scale_exponent(unit_surface) if family in {"mn", "mw", "molar_mass"} else None
    scale = 10.0 ** exponent if exponent is not None else display_scale
    supported = number_close(value_min, cell_value) or number_close(value_min, cell_value * scale)
    if not supported:
        return QuantityDecision(False, "value_not_supported_by_cell", family)

    molecular_weight_type = None
    if family in {"mn", "mw", "molar_mass"}:
        explicit = _explicit_unit(family, unit_surface)
        if explicit is None and exponent is None:
            return QuantityDecision(False, "molecular_weight_unit_or_scale_missing", family)
        normalized_value = cell_value * scale if exponent is not None else value_min
        molecular_weight_type = "Mn" if family == "mn" else "Mw" if family == "mw" else "unspecified"
        return QuantityDecision(
            True, "accepted_direct_scalar", family,
            normalized_value, normalized_value, "g/mol", "g/mol", molecular_weight_type,
        )

    if family in DIMENSIONLESS_FAMILIES:
        unit_text = compact(candidate.get("unit_normalized") or candidate.get("unit_raw"))
        harmless = {"", "w", "mw mn", "m w m n"}
        if unit_text not in harmless:
            return QuantityDecision(False, "dimensionless_property_has_unit", family)
        return QuantityDecision(
            True, "accepted_direct_scalar", family,
            value_min, value_min, None, None, None,
        )

    explicit = _explicit_unit(family, unit_surface)
    if explicit is None:
        return QuantityDecision(False, "required_unit_missing_or_invalid", family)
    if family == "thermal_decomposition_temperature" and not 100 <= value_min <= 1500:
        return QuantityDecision(False, "implausible_decomposition_temperature", family)
    normalized_value = cell_value * display_scale if display_scale != 1.0 else value_min
    return QuantityDecision(
        True,
        "accepted_direct_scaled_scalar" if display_scale != 1.0 else "accepted_direct_scalar",
        family,
        normalized_value,
        normalized_value,
        explicit,
        explicit,
        None,
    )
