"""Deterministic property-name and unit mapping for unified measurements."""
from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

from stages.final_unit_conversion import canonical_unit


DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "standard_property_codes.v1.json"
)

UNIT_FAMILIES: dict[str, set[str]] = {
    "temperature": {"c", "°c", "k", "degc"},
    "stress": {"pa", "kpa", "mpa", "gpa"},
    "fraction": {"%", "wt%", "1", "dimensionless"},
    "dimensionless": {"1", "dimensionless"},
    "impact": {"j/m", "kj/m", "j/m2", "kj/m2", "j/m²", "kj/m²"},
    "specific_energy": {"j/g", "kj/g", "cal/g", "kcal/g"},
    "molecular_weight": {"g/mol", "kg/mol", "da", "kda"},
    "viscosity": {"dl/g", "ml/g", "cm3/g", "cm³/g", "1", "dimensionless"},
    "angle": {"degree", "degrees", "°", "deg"},
    "length": {"nm", "angstrom", "å", "m", "µm"},
    "surface": {"mn/m", "n/m", "dyn/cm", "mj/m2", "mj/m²"},
    "conductivity": {"1/(ohm*cm)", "s/cm", "s/m"},
}


def normalize_source_notation(value: Any) -> str:
    """Remove supported presentation markup, preserving qualifiers and scales."""
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = text.replace("$", "").replace(r"\(", "").replace(r"\)", "")
    text = re.sub(r"\\(?:mathrm|text|operatorname)\s*\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\(?:overline|bar)\s*\{\s*M\s*\}", "M", text)
    text = re.sub(r"\b([TM])\s*_\s*\{\s*([gmnw](?:[12])?)\s*\}", r"\1\2", text)
    text = re.sub(r"\b([TM])_([gmnw](?:[12])?)\b", r"\1\2", text)
    text = re.sub(r"\^\s*\{\s*\\circ\s*\}", "°", text)
    text = text.replace(r"\circ", "°")
    return " ".join(text.split())


def normalize_mapping_text(value: Any) -> str:
    text = normalize_source_notation(value).casefold()
    return " ".join(text.replace("_", " ").split())


def normalize_unit(value: Any) -> str:
    text = normalize_source_notation(value).casefold()
    text = text.replace("²", "2").replace("³", "3")
    return re.sub(r"\s+", "", text)


@lru_cache(maxsize=4)
def load_standard_mapping(path: Path = DEFAULT_REGISTRY_PATH) -> dict[str, Any]:
    registry = json.loads(path.read_text(encoding="utf-8"))
    if (
        registry.get("schema_version") != "standard_property_code_registry.v1"
        or registry.get("namespace") != "STD:"
    ):
        raise ValueError("Unsupported property code registry")
    aliases: dict[str, dict[str, Any]] = {}
    for entry in registry.get("entries", []):
        key = str(entry["key"])
        for surface in [key, *entry.get("aliases", [])]:
            normalized = normalize_mapping_text(surface)
            previous = aliases.get(normalized)
            if previous and previous["key"] != key:
                raise ValueError(f"Ambiguous alias: {surface}")
            aliases[normalized] = entry
    return {"registry": registry, "aliases": aliases}


def _unit_status(unit_raw: Any, family: str) -> str:
    if not normalize_unit(unit_raw):
        return "unit_unresolved"
    unit = normalize_unit(unit_raw)
    allowed = {normalize_unit(x) for x in UNIT_FAMILIES.get(family, set())}
    if unit in allowed:
        return "confirmed"
    known = {normalize_unit(x) for x in set().union(*UNIT_FAMILIES.values())}
    return "unit_conflict" if unit in known else "unit_unrecognized"


def _split_unit_annotation(text: str) -> tuple[str, str | None]:
    allowed = {normalize_unit(u) for values in UNIT_FAMILIES.values() for u in values}
    match = re.search(r"\s*\(([^()]*)\)$", text)
    if match and normalize_unit(match[1]) in allowed:
        base = text[:match.start()].strip()
        return base.rstrip("/").strip(), match[1].strip()
    for index, char in enumerate(text):
        if char == "/" and normalize_unit(text[index + 1:]) in allowed:
            return text[:index].strip(), text[index + 1:].strip()
    return text, None


def units_in_text(text: Any) -> list[str]:
    """Extract bounded, registered unit tokens; never match C inside a label."""
    normalized = normalize_source_notation(text)
    tokens = {unicodedata.normalize("NFKC", x) for x in set().union(*UNIT_FAMILIES.values())}
    # Bare 1 is also a measurement value, so cannot prove dimensionlessness.
    tokens.discard("1")
    pattern = r"(?<![\w/])(?:" + "|".join(re.escape(x) for x in sorted(tokens, key=lambda x: (-len(x), x))) + r")(?![\w/])"
    found = set(re.findall(pattern, normalized, re.I))
    base, unit = _split_unit_annotation(normalized)
    if unit and normalize_mapping_text(base) in load_standard_mapping()["aliases"]:
        found.add(unit)
    return sorted(found)


def resolve_standard_property(
    property_name_raw: Any,
    unit_raw: Any = None,
    *,
    registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve only registered names; never use fuzzy or substring matching."""
    mapping = registry or load_standard_mapping()
    normalized = normalize_mapping_text(property_name_raw)
    name_without_unit = normalized
    entry = mapping["aliases"].get(normalized)
    stripped_unit_annotation = False
    annotation_unit = None
    if entry is None:
        base_name, parsed_unit = _split_unit_annotation(normalized)
        if parsed_unit:
            name_without_unit = base_name
            entry = mapping["aliases"].get(base_name)
            stripped_unit_annotation = entry is not None
            annotation_unit = parsed_unit
    if entry is None:
        return {
            "standard_status": "standard_unmapped",
            "standard_property_code": None,
            "unit_status": "unit_unresolved" if unit_raw in (None, "") else "unit_unchecked",
            "mapping_reasons": ["property_alias_not_registered"],
        }

    unit_status = _unit_status(unit_raw or annotation_unit, entry["unit_family"])
    reasons: list[str] = []
    if stripped_unit_annotation:
        reasons.append("unit_annotation_in_property_name")
    if unit_status == "unit_unresolved":
        reasons.append("unit_missing")
    elif unit_status == "unit_conflict":
        reasons.append("unit_family_conflict")
    elif unit_status == "unit_unrecognized":
        reasons.append("unit_not_registered")
    if annotation_unit and unit_raw and canonical_unit(annotation_unit) != canonical_unit(unit_raw):
        unit_status = "unit_conflict"
        reasons.append("unit_annotation_conflict")
    reasons.extend(entry.get("review_flags", []))
    raw_name = normalize_source_notation(property_name_raw)
    raw_without_unit = _split_unit_annotation(raw_name)[0]
    if name_without_unit == "mw" and raw_without_unit != "Mw":
        reasons.append("molecular_weight_statistic_unresolved")
    if normalized == "molecular weight distribution":
        reasons.append("distribution_not_confirmed_as_dispersity")
    canonical = normalize_mapping_text(entry["key"]) == normalized
    blockers = [reason for reason in reasons if reason != "unit_annotation_in_property_name"]
    status = "standard_candidate" if blockers else "standard_exact" if canonical else "standard_alias"
    return {
        "standard_status": status,
        "standard_property_code": f"STD:{entry['key']}",
        "unit_status": unit_status,
        "mapping_reasons": reasons,
        "registry_key": entry["key"],
    }
