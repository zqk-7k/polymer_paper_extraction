"""Deterministic value/unit enrichment before Candidate and Final value exports.

Never uses a reference value to manufacture an observation. Original fields
remain intact. CLI: python -m stages.final_unit_conversion --input rows.jsonl
--output enriched.jsonl [--target-unit GPa]. No LLM or external service.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
from typing import Any


D = Decimal
NUM = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
SCI = re.compile(rf"({NUM})\s*(?:×|x|\\times|·)\s*10\s*(?:\^|(?=[+-]))\s*\{{?\s*([+-]?\d+)\s*\}}?", re.I)
POWER = re.compile(r"(?<![\w.])10\s*\^\s*\{?\s*([+-]?\d+)\s*\}?")
SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻", "0123456789+-")


def decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = D(str(value))
        return result if result.is_finite() else None
    except InvalidOperation:
        return None


def parse_numeric(value: Any, kind: str = "") -> dict | None:
    """Parse complete numeric text, never a stray digit in a label or method."""
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        v = decimal(value)
        return {"values": [v], "kind": "scalar", "uncertainty": None} if v is not None else None
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip().replace("−", "-").replace("$", "").replace(r"\pm", "±").replace(r"\sim", "~").replace("+/-", "±")
    if kind == "numeric_multiple":
        s = s.replace("/", ";")
    # Explicit table annotations are retained in value_raw. Only these complete
    # suffixes are stripped; inequalities and arbitrary prose remain unparsed.
    s = re.sub(r"\s*\(peaks?\)\s*$", "", s, flags=re.I)
    s = re.sub(r"(?:\^\s*\{\s*\\circ\s*\}|°)\s*(?:C)?\s*$", "", s)
    # OCR can space decimal digits in equations (1. 3 2). Do not join lists or
    # whitespace-separated integers, whose grouping is ambiguous.
    if re.fullmatch(r"[+-]?\d+\s*\.\s*\d(?:\s*\d)*", s.strip()):
        s = re.sub(r"\s", "", s)
    s = re.sub(r"10([⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻]+)", lambda m: "10^{" + m[1].translate(SUPERSCRIPTS) + "}", s)
    s = SCI.sub(lambda m: str(D(m[1]) * (D(10) ** int(m[2]))), s)
    s = POWER.sub(lambda m: str(D(10) ** int(m[1])), s)
    # Thousands separated by spaces occur in molecular-weight tables.
    s = re.sub(r"(?<![\d.])\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?!\d)", lambda m: re.sub(r"\s", "", m[0]), s)
    # Commas are vectors when the table declares them so; otherwise only a
    # complete thousands-group expression is treated as one number.
    if kind != "numeric_multiple" and re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", s):
        s = s.replace(",", "")
    elif kind != "numeric_multiple" and re.search(r"[~～–—]|\s-\s|\bto\b|±", s):
        s = re.sub(r"(?<![\d.])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\d.])", lambda m: m[0].replace(",", ""), s)
    s = re.sub(r"\^\{[a-z*, ]+\}$", "", s).strip()
    scalar = re.fullmatch(NUM, s)
    if scalar:
        return {"values": [D(s)], "kind": "scalar", "uncertainty": None}
    unc = re.fullmatch(rf"\(?\s*({NUM})\s*±\s*({NUM})\s*\)?", s)
    if unc:
        return {"values": [D(unc[1])], "kind": "uncertainty", "uncertainty": abs(D(unc[2]))}
    interval = re.fullmatch(rf"({NUM})\s*(?:–|—|-|~|～|to)\s*({NUM})", s)
    if interval:
        return {"values": sorted([D(interval[1]), D(interval[2])]), "kind": "range", "uncertainty": None}
    if re.fullmatch(rf"{NUM}(?:\s*[,;]\s*{NUM})+", s):
        return {"values": [D(x.strip()) for x in re.split(r"[,;]", s)], "kind": "multiple", "uncertainty": None}
    return None


def canonical_unit(value: Any, property_code: str = "") -> str:
    s = str(value or "").strip().replace("−", "-").replace("⁻¹", "^-1")
    s = re.sub(r"\\(?:text|mathrm|rm)\s*\{([^{}]*)\}", r"\1", s)
    s = s.replace("$", "").replace(r"\circ", "°").replace("{", "").replace("}", "")
    s = re.sub(r"\s+", "", s).casefold()
    aliases = {"°c": "c", "degc": "c", "celsius": "c", "centigrade": "c",
               "kelvin": "k", "scm^-1": "s/cm", "scm-1": "s/cm", "1/(ohm*cm)": "s/cm",
               "1/(ω*cm)": "s/cm", "degree": "degree", "degrees": "degree", "deg": "degree",
               "j/m²": "j/m2", "kj/m²": "kj/m2", "mj/m²": "mj/m2", "å": "angstrom",
               "dlg^-1": "dl/g", "dlg-1": "dl/g"}
    s = aliases.get(s, s)
    if s == "°":
        return "degree" if "angle" in property_code else "c" if "temperature" in property_code else s
    return s


# (dimension, factor to base unit, additive offset to base unit).
UNITS = {
    "pa": ("stress", D(1), D(0)), "kpa": ("stress", D(1000), D(0)),
    "mpa": ("stress", D("1e6"), D(0)), "gpa": ("stress", D("1e9"), D(0)),
    "c": ("temperature", D(1), D(0)), "k": ("temperature", D(1), D("-273.15")),
    "j/m": ("impact_length", D(1), D(0)), "kj/m": ("impact_length", D(1000), D(0)),
    "j/m2": ("impact_area", D(1), D(0)), "kj/m2": ("impact_area", D(1000), D(0)),
    "j/g": ("energy_mass", D(1), D(0)), "kj/g": ("energy_mass", D(1000), D(0)),
    "cal/g": ("energy_mass", D("4.184"), D(0)), "kcal/g": ("energy_mass", D(4184), D(0)),
    "j/mol": ("energy_mole", D(1), D(0)), "kj/mol": ("energy_mole", D(1000), D(0)),
    "s/cm": ("conductivity", D(1), D(0)), "s/m": ("conductivity", D(".01"), D(0)),
    "mn/m": ("surface", D(1), D(0)), "n/m": ("surface", D(1000), D(0)),
    "dyn/cm": ("surface", D(1), D(0)), "mj/m2": ("surface", D(1), D(0)),
    "g/mol": ("molecular_weight", D(1), D(0)), "kg/mol": ("molecular_weight", D(1000), D(0)),
    "degree": ("angle", D(1), D(0)), "%": ("percentage", D(1), D(0)),
    "dl/g": ("specific_volume", D(1), D(0)), "ml/g": ("specific_volume", D(".01"), D(0)),
    "angstrom": ("length", D(1), D(0)), "nm": ("length", D(10), D(0)),
    "1": ("dimensionless", D(1), D(0)),
}


def _serialize(values: list[Decimal]) -> float | list[float]:
    return float(values[0]) if len(values) == 1 else [float(v) for v in values]


def attach_table_scale(observation: dict, tables: dict) -> dict:
    """Recover an explicit molecular-weight multiplier from the first header rows.

    This uses the source grid, never the reference number or an inferred ratio.
    """
    if observation.get("source_stage") != "stage4t" or observation.get("semantic_label") != "molecular_weight":
        return observation
    table = tables.get(observation.get("table_id"), {})
    column, row = observation.get("column_index"), observation.get("row_index")
    if column is None or row is None:
        return observation
    headers = []
    for cell in table.get("table_cells", []):
        text = str(cell.get("text") or "").replace("$", "").strip()
        match = re.fullmatch(r"10\s*\^\s*\{?([+-]?\d+)\}?", text)
        if cell.get("column_index") == column and cell.get("row_index", 99) <= 1 and match:
            headers.append((cell, int(match[1])))
    if len(headers) != 1:
        return observation
    cell, exponent = headers[0]
    out = dict(observation)
    if row == cell["row_index"]:
        out["value_role"] = "scale_header"
    elif row > cell["row_index"] and observation.get("scale_factor_exponent") is None:
        out.update(scale_factor_exponent=exponent, scale_factor_raw=cell["text"],
                   scale_factor_location="header", scale_factor_evidence=dict(cell))
    return out


def enrich_observation(observation: dict, target_unit: Any = None, property_code: str = "") -> dict:
    """Return an enriched copy; always recompute from original fields (idempotent)."""
    out = deepcopy(observation)
    for key in ("standard_numeric_values", "source_numeric_values", "original_value_kind",
                "original_uncertainty", "applied_header_scale", "converted_source_rounding_half_width"):
        out.pop(key, None)
    raw = observation.get("value_raw")
    kind = observation.get("value_kind", "")
    parsed = parse_numeric(raw, kind)
    if observation.get("value_role") == "scale_header":
        parsed = None
    source_unit = observation.get("unit_raw") or observation.get("unit_normalized") or observation.get("unit")
    # Permit a numeric text with a known trailing source unit.
    if parsed is None and isinstance(raw, str) and source_unit and raw.strip().endswith(str(source_unit)):
        parsed = parse_numeric(raw.strip()[:-len(str(source_unit))].strip(), kind)
    basis = "value_raw"
    warnings = []
    if parsed is None and observation.get("value_role") != "scale_header":
        lo, hi = decimal(observation.get("value_min")), decimal(observation.get("value_max"))
        if lo is None:
            lo = decimal(observation.get("value"))
        if lo is not None or hi is not None:
            lo = hi if lo is None else lo
            hi = lo if hi is None else hi
            parsed = {"values": [lo] if lo == hi else sorted([lo, hi]),
                      "kind": "scalar" if lo == hi else "range", "uncertainty": None}
            basis = "value_min_max"
            if raw not in (None, ""):
                warnings.append("raw_text_not_fully_parsed")
    out.update(standard_value=None, standard_value_min=None, standard_value_max=None,
               standard_unit=None, original_value=None, original_unit=source_unit,
               unit_conversion_status="unit_review_required", conversion_operation=None,
               conversion_factor=None, conversion_offset=None, standard_uncertainty=None,
               target_unit=target_unit, numeric_present=parsed is not None, value_parse_basis=basis,
               conversion_warnings=warnings, conversion_schema_version="final_unit_conversion.v1")
    if parsed is None:
        warnings.append("numeric_value_missing")
        return out
    values, unc = parsed["values"], parsed["uncertainty"]
    out.update(original_value=_serialize(values), original_value_kind=parsed["kind"],
               original_uncertainty=float(unc) if unc is not None else None)
    source_half_width = (D(10) ** values[0].as_tuple().exponent)/2 if basis == "value_raw" and parsed["kind"] == "scalar" else D(0)
    structured = decimal(observation.get("value_min"))
    if basis == "value_raw" and structured is not None and abs(structured-values[0]) > max(abs(values[0])*D("1e-9"), D("1e-15")):
        warnings.append("raw_structured_value_conflict")
    scale = decimal(observation.get("scale_factor_exponent"))
    scale_pending = False
    if scale is not None:
        # A multiplier may have been copied from an already exponent-bearing
        # cell; require explicit scope rather than applying it twice.
        if isinstance(raw, str) and (SCI.search(raw) or POWER.search(raw) or re.search(r"10[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻]+|\d[eE][+-]?\d", raw)):
            warnings.append("scale_provenance_requires_review")
            scale_pending = True
        elif scale != scale.to_integral_value() or abs(scale) > 30:
            warnings.append("invalid_header_scale")
            scale_pending = True
        else:
            multiplier = D(10) ** int(scale)
            values = [v*multiplier for v in values]
            source_half_width *= multiplier
            unc = unc*multiplier if unc is not None else None
            out["applied_header_scale"] = float(multiplier)
    out["source_numeric_values"] = [float(v) for v in values]
    src, dst = canonical_unit(source_unit, property_code), canonical_unit(target_unit, property_code)
    if not dst:
        status, factor, offset, unit = "unit_source_only", D(1), D(0), source_unit
    elif src not in UNITS or dst not in UNITS:
        warnings.append("unit_unknown_or_missing")
        return out
    elif UNITS[src][0] != UNITS[dst][0]:
        out["unit_conversion_status"] = "unit_conflict"
        warnings.append("incompatible_unit_dimensions")
        return out
    else:
        _, a, b = UNITS[src]
        _, c, d = UNITS[dst]
        factor, offset = a/c, (b-d)/c
        status = "unit_equivalent" if factor == 1 and offset == 0 else "unit_converted_exact"
        unit = target_unit
    if scale_pending:
        return out
    converted = [v*factor+offset for v in values]
    out.update(standard_value=_serialize(converted), standard_value_min=float(min(converted)),
               standard_value_max=float(max(converted)), standard_unit=unit,
               standard_numeric_values=[float(v) for v in converted], unit_conversion_status=status,
               conversion_operation="source_unit_retained" if not dst else f"{src}_to_{dst}",
               conversion_factor=float(factor), conversion_offset=float(offset),
               converted_source_rounding_half_width=float(source_half_width*abs(factor)),
               standard_uncertainty=float(unc*abs(factor)) if unc is not None else None)
    return out


def match_reference(expected: dict, observation: dict) -> str | None:
    """Value-only comparison; unknown units are review hits, never converted hits."""
    ref = parse_numeric(expected.get("value_min") if expected.get("value_min") is not None else expected.get("value_raw"))
    high = parse_numeric(expected.get("value_max"))
    if ref is None or not observation.get("numeric_present"):
        return None
    lo = ref["values"][0]
    hi = high["values"][0] if high else lo
    standard = observation.get("standard_numeric_values")
    values = standard or observation.get("source_numeric_values") or []
    if not values:
        return None
    def close(a: Decimal, b: Decimal) -> bool:
        return abs(a-b) <= max(abs(b)*D("1e-6"), D("1e-12"))
    candidate_values = [D(str(x)) for x in values]
    kind = observation.get("original_value_kind")
    if kind == "multiple" and lo == hi:
        exact = any(close(v, lo) for v in candidate_values)
    else:
        exact = close(min(candidate_values), lo) and close(max(candidate_values), hi)
    if exact:
        return "numeric_match" if standard else "raw_value_unit_unverified"
    # Reference cells often round converted energy/temperature values. Accept
    # at most half the final stated decimal place, only after a known conversion.
    if observation.get("unit_conversion_status") == "unit_converted_exact":
        def rounded(v: Decimal, target: Decimal) -> bool:
            # Both the source and reference may have rounded their last digit.
            # Bound combined rounding at 1%; report this separately from equality.
            quantum = D(10) ** target.as_tuple().exponent
            source_width = D(str(observation.get("converted_source_rounding_half_width") or 0))
            width = abs(quantum)/2 + source_width
            return width <= abs(target)*D(".01") and abs(v-target) <= width
        if rounded(min(candidate_values), lo) and rounded(max(candidate_values), hi):
            return "converted_matches_reference_rounding"
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-unit")
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error("Use a separate output; original input must be preserved")
    rows = [json.loads(s) for s in args.input.read_text(encoding="utf-8").splitlines() if s.strip()]
    enriched = [enrich_observation(r, args.target_unit or r.get("target_unit") or r.get("reviewed_unit"), r.get("standard_property_code", "")) for r in rows]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(r, ensure_ascii=False, allow_nan=False)+"\n" for r in enriched), encoding="utf-8")
    print(json.dumps({"rows": len(rows), "numeric_present": sum(r["numeric_present"] for r in enriched)}))


if __name__ == "__main__":
    main()
