"""Deterministic numeric projection; raw evidence is never overwritten."""
from __future__ import annotations

import math
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from stages.final_unit_conversion import SCI, parse_numeric

NORMALIZATION_VERSION = "value_normalization.v3"
_KINDS = {"scalar": "numeric_scalar", "range": "numeric_range",
          "multiple": "numeric_multiple", "uncertainty": "numeric_with_uncertainty"}
_KNOWN_UNIT_KEYS = {
    "", "%", "wt%", "vol%", "mol%", "g", "mg", "kg", "m", "cm", "mm",
    "um", "μm", "nm", "å", "pa", "kpa", "mpa", "gpa", "j/m", "kj/m",
    "j/m2", "kj/m2", "j/g", "kj/g", "cal/g", "kcal/g", "j/mol", "kj/mol",
    "g/mol", "kg/mol", "hz", "khz", "mhz", "s", "min", "h", "°c", "degc",
    "c", "k", "deg", "degree", "degree;degree", "s/cm", "s/m", "1/(ohm*cm)",
    "ohm*cm", "ohm*m", "ω·cm", "ω·m", "dl/g", "ml/g", "g/cm3", "mj/m2",
    "mn/m", "dyn/cm", "mj/m²", "m²/g", "cm⁻¹", "cm-1",
}
_DERIVED_FIELDS = (
    "restored_value", "restored_values", "normalized_value", "normalized_values",
    "normalized_value_min", "normalized_value_max", "normalized_value_secondary",
    "normalized_uncertainty", "normalized_unit", "normalization_warning", "parsed_value_kind",
)


def _unit_key(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\\(?:mathrm|text|mathit|rm)\s*\{([^{}]*)\}", r"\1", text)
    return re.sub(r"\s+", "", text.replace("$", "").replace("\\circ", "°")).casefold()


def normalize_observation(observation: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute from raw fields; retain the original engineering unit."""
    result = dict(observation)
    for key in _DERIVED_FIELDS:
        result.pop(key, None)
    result["normalization_version"] = NORMALIZATION_VERSION
    kind = str(result.get("value_kind") or "")
    if kind and kind not in {*_KINDS.values(), "state_qualified_numeric"}:
        result["normalization_status"] = "skipped_non_numeric"
        return result
    raw = result.get("value_raw")
    numeric_input = raw
    projection = result.get('value_projection')
    if projection is not None:
        # A projection must still point to the unchanged OCR substring. Invalid
        # annotations cannot supply a model-generated numeric replacement.
        try:
            start, end = projection['source_start'], projection['source_end']
            if type(start) is not int or type(end) is not int or not isinstance(raw, str) or not 0 <= start < end <= len(raw):
                raise ValueError('invalid substring bounds')
            numeric_input = raw[start:end]
            if numeric_input != projection['source_text']:
                raise ValueError('projection text differs from OCR')
            style = projection['decimal_style']
            if style not in {'dot', 'middle_dot'}:
                raise ValueError('unknown decimal style')
            if style == 'middle_dot':
                numeric_input = re.sub(r'(?<=\d)·(?=\d)', '.', numeric_input)
            if numeric_input != projection['numeric_text']:
                raise ValueError('numeric projection is not a permitted transformation')
        except (KeyError, TypeError, ValueError):
            result.update(normalization_status='warning', normalization_warning='invalid_ocr_projection')
            return result
    if set(result.get('unresolved_metadata_fields', [])) & {'unit', 'scale_factor', 'content'}:
        result.update(normalization_status='warning', normalization_warning='metadata_conflict_requires_review')
        return result
    parsed = parse_numeric(numeric_input, kind)
    # Strip only an explicitly supplied unit, never arbitrary trailing prose.
    if parsed is None and isinstance(raw, str):
        for unit in (result.get("unit_raw"), result.get("unit_normalized")):
            if unit and _unit_key(unit) in _KNOWN_UNIT_KEYS and raw.strip().endswith(str(unit)):
                parsed = parse_numeric(raw.strip()[:-len(str(unit))].strip(), kind)
                if parsed:
                    break
    if parsed is None:
        result["normalization_status"] = "warning" if kind else "skipped_non_numeric"
        if kind:
            result["normalization_warning"] = "value_missing" if raw is None or raw == "" else "value_not_numeric"
        return result
    result["parsed_value_kind"] = _KINDS[parsed["kind"]]
    if kind in _KINDS.values() and kind != result["parsed_value_kind"]:
        result.update(normalization_status="warning", normalization_warning="value_kind_mismatch")
        return result
    exponent = result.get("scale_factor_exponent")
    if result.get("scale_factor_status") == "ambiguous_display_scale":
        result.update(normalization_status="warning", normalization_warning="scale_direction_requires_review")
        return result
    try:
        exp = Decimal(str(exponent)) if exponent is not None else Decimal(0)
        if not exp.is_finite() or exp != exp.to_integral_value() or abs(exp) > 30:
            raise ValueError("invalid scale")
        scale = Decimal(10) ** int(exp)
    except (TypeError, ValueError, InvalidOperation):
        result.update(normalization_status="warning", normalization_warning="invalid_header_scale")
        return result
    if exponent is not None and isinstance(raw, str) and (SCI.search(raw) or re.search(r"\d[eE][+-]?\d|10\s*(?:\^|[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻])", raw)):
        result.update(normalization_status="warning", normalization_warning="scale_provenance_requires_review")
        return result
    values = [float(v * scale) for v in parsed["values"]]
    unc = float(parsed["uncertainty"] * scale) if parsed["uncertainty"] is not None else None
    if not all(math.isfinite(v) for v in values) or (unc is not None and not math.isfinite(unc)):
        result.update(normalization_status="warning", normalization_warning="numeric_overflow")
        return result
    result.update(restored_value=values[0], restored_values=values)
    unit = result.get("unit_normalized") or result.get("unit_raw")
    if _unit_key(unit) not in _KNOWN_UNIT_KEYS:
        result.update(normalization_status="warning", normalization_warning="unit_unrecognized")
        return result
    result.update(normalized_value=values[0], normalized_values=values,
                  normalized_unit=unit, normalization_status="normalized")
    if parsed["kind"] == "range":
        result.update(normalized_value_min=values[0], normalized_value_max=values[1])
    if parsed["kind"] == "multiple" and len(values) > 1:
        result["normalized_value_secondary"] = values[1]
    if unc is not None:
        result["normalized_uncertainty"] = unc
    return result
