"""Compare explicitly named radiation doses without filling missing conditions."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, DecimalException, localcontext
import re


DOSE_NAMES = {"dose", "irradiation dose", "radiation dose", "absorbed dose", "剂量", "辐照剂量"}
NUMBER = r"[+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d{1,2})?"
QUANTITY = re.compile(rf"({NUMBER})\s*(Gy|kGy)?")
HEADER = re.compile(r"(.+?)\s*(?:/\s*(Gy|kGy)|\((Gy|kGy)\)|\[(Gy|kGy)\])")
FACTORS = {"Gy": Decimal(1), "kGy": Decimal(1000)}


def _name(value):
    return " ".join(str(value).replace("_", " ").casefold().split())


def _header(value):
    text = str(value or "").strip()
    match = HEADER.fullmatch(text)
    if match and _name(match[1]) in DOSE_NAMES:
        return _name(match[1]), next(u for u in match.groups()[1:] if u)
    if _name(text) in DOSE_NAMES:
        return _name(text), None
    return None, text if text in FACTORS else None


def _quantity(value, unit=None):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return None
    text = str(value).strip()
    match = QUANTITY.fullmatch(text) if len(text) <= 100 else None
    if not match or unit not in (None, "", *FACTORS):
        return None
    inline = match[2]
    if inline and unit and inline != unit:
        return None
    source_unit = inline or unit
    if source_unit not in FACTORS:
        return None
    try:
        with localcontext() as context:
            context.prec = max(28, len(text) + 4)
            number = Decimal(match[1]) * FACTORS[source_unit]
        return {"value_gy": str(number), "unit_raw": source_unit,
                "factor_to_gy": str(FACTORS[source_unit])}
    except DecimalException:
        return None


def _declaration(value):
    if not isinstance(value, dict):
        return _quantity(value)
    # Preserve both raw and structured representations; neither can hide a
    # conflicting number or an unsupported qualifier in the other.
    if set(value) - {"raw", "value", "unit", "evidence", "evidence_ids"}:
        return None
    present = [value[k] for k in ("raw", "value") if value.get(k) not in (None, "")]
    parsed = [_quantity(v, value.get("unit")) for v in present]
    if not parsed or any(p is None for p in parsed):
        return None
    return parsed[0] if len({Decimal(p["value_gy"]) for p in parsed}) == 1 else None


def _declared_doses(candidate):
    declarations, unstructured = [], False
    for field in ("measurement_context", "conditions"):
        context = candidate.get(field)
        if context in (None, ""):
            continue
        if not isinstance(context, dict):
            unstructured = True
            continue
        containers = [(field, context)]
        other = context.get("other_conditions")
        if other not in (None, ""):
            if isinstance(other, dict):
                containers.append((field + ".other_conditions", other))
            else:
                unstructured = True
        for pointer, fields in containers:
            for name, value in fields.items():
                if _name(name) in DOSE_NAMES and value not in (None, ""):
                    declarations.append({"field_path": pointer + "." + name,
                                         "raw": deepcopy(value), "normalized": _declaration(value)})
    return declarations, unstructured


def compare_source_conditions(source_context, candidate):
    """Source association and numeric agreement are separate review outcomes.

    This compares named dose fields only, not prose, process steps, or evidence
    quotes. A missing declaration never authorizes copying a source value.
    """
    declarations, unstructured = _declared_doses(candidate)
    axes = source_context.get("condition_axes", [])
    dose_axes = [a for a in axes if _header(a.get("name"))[0] is not None]
    rows = []
    for axis in [*axes, *source_context.get("composition_axes", [])]:
        row = {"cell_id": axis["cell_id"], "header_cell_ids": deepcopy(axis["header_cell_ids"]),
               "status": "needs_review", "numeric_comparison": "not_available", "reasons": [],
               "source_normalized": None, "declarations": deepcopy(declarations)}
        rows.append(row)
        if _header(axis.get("name"))[0] is None:
            row["reasons"].append("condition_type_not_supported")
            continue
        headers = axis.get("header_path") or [axis.get("name")]
        parts = [_header(h) for h in headers]
        units = {u for _, u in parts if u}
        if (len(units) != 1 or any(n is None and u is None for n, u in parts)
                or not axis.get("header_cell_ids")):
            row["reasons"].append("source_dose_unit_unverified")
            continue
        row["source_normalized"] = _quantity(axis.get("value_raw"), next(iter(units)))
        if row["source_normalized"] is None:
            row["reasons"].append("source_dose_not_scalar_with_explicit_unit")
            continue
        if axis.get("association_status") not in {"source_aligned", "candidate"} or len(dose_axes) != 1:
            row["reasons"].append("source_dose_association_ambiguous")
            continue
        if axis.get("association_status") != "source_aligned":
            row["reasons"].append("source_dose_association_requires_review")
        if unstructured:
            row["reasons"].append("unstructured_conditions_not_compared")
        if not declarations:
            row["status"] = "needs_review" if unstructured else "declaration_missing"
            row["reasons"].append("named_dose_declaration_missing")
            continue
        if any(d["normalized"] is None for d in declarations):
            row["reasons"].append("declared_dose_unit_value_or_representation_unresolved")
            continue
        values = {Decimal(d["normalized"]["value_gy"]) for d in declarations}
        source = Decimal(row["source_normalized"]["value_gy"])
        row["numeric_comparison"] = "equal" if values == {source} else "different"
        if len(values) > 1:
            row["reasons"].append("declared_doses_disagree")
        if axis.get("association_status") == "source_aligned" and not unstructured:
            row["status"] = "matched" if values == {source} else "conflict"
        if values != {source}:
            row["reasons"].append("dose_numeric_difference")
    statuses = {r["status"] for r in rows}
    status = next((s for s in ("conflict", "needs_review", "declaration_missing", "matched") if s in statuses), "not_applicable")
    return {"schema_version": "source_condition_comparison.v1", "scope": "explicit_named_radiation_dose_only",
            "status": status, "axes": rows, "updates_model_context": False, "changes_publication_status": False}
