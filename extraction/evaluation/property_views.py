"""Build comparable numeric-property views from all released candidate stores.

The extraction schema intentionally keeps scalar observations, property series,
and PoLyInfo-specialized observations separate. Evaluation must unite those
stores before measuring numeric recall, while preserving each record's origin.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any, Callable


NUMERIC_PATTERN = re.compile(r"[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?")
ATOMIC_NUMERIC_PATTERN = re.compile(
    r"[-+]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE](?:[-+]?\d+|\([-+]?\d+\)))?"
)


def _condition_name(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip().casefold()
    return text or "unnamed"


def _quantity_payload(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    payload: dict[str, Any] = {}
    numeric = value.get("value")
    if isinstance(numeric, (int, float)) and not isinstance(numeric, bool):
        payload["value"] = numeric
    else:
        raw = str(value.get("raw") or "").strip()
        if raw:
            payload["raw"] = raw
    unit = str(value.get("unit") or "").strip()
    if unit:
        payload["unit"] = unit
    return payload or None


def _context_conditions(
    context: Any,
    *,
    prefix: str = "measurement",
) -> dict[str, Any]:
    if not isinstance(context, Mapping):
        return {}
    result: dict[str, Any] = {}
    for name in ("temperature", "frequency", "humidity", "pressure", "wavelength"):
        payload = _quantity_payload(context.get(name))
        if payload is not None:
            result[f"{prefix}.{name}"] = payload
    other = context.get("other_conditions")
    if isinstance(other, Mapping):
        for name, value in sorted(other.items(), key=lambda item: str(item[0])):
            result[f"{prefix}.other.{_condition_name(name)}"] = str(value).strip()
    return result


def _coordinate_conditions(coordinates: Any) -> dict[str, Any]:
    if not isinstance(coordinates, list):
        return {}
    result: dict[str, Any] = {}
    for index, coordinate in enumerate(coordinates):
        if not isinstance(coordinate, Mapping):
            continue
        raw = str(coordinate.get("value_raw") or "").strip()
        numeric_match = NUMERIC_PATTERN.search(raw)
        value: Any = raw
        if numeric_match:
            try:
                value = float(numeric_match.group().replace(",", "."))
            except ValueError:
                value = raw
        payload: dict[str, Any] = {"value": value}
        unit = str(coordinate.get("unit_raw") or "").strip()
        if unit:
            payload["unit"] = unit
        name = _condition_name(coordinate.get("name_raw"))
        result[f"series_coordinate.{index:03d}.{name}"] = payload
    return result


def _measurement_condition_map(candidate: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for row in candidate.get("measurement_conditions") or []:
        if not isinstance(row, Mapping):
            continue
        condition_id = str(row.get("condition_id") or "")
        if condition_id:
            result[condition_id] = row
    return result


def _record_conditions(
    item: Mapping[str, Any],
    *,
    inherited_context: Any = None,
    condition_map: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    raw_conditions = item.get("conditions")
    if isinstance(raw_conditions, Mapping):
        result.update({str(key): value for key, value in raw_conditions.items()})
    result.update(_context_conditions(inherited_context, prefix="series_measurement"))
    result.update(_context_conditions(item.get("measurement_context")))
    condition_id = str(item.get("measurement_condition_id") or "")
    if condition_id and condition_map and condition_id in condition_map:
        result.update(_context_conditions(condition_map[condition_id]))
    result.update(_coordinate_conditions(item.get("coordinates")))
    return result


def canonical_conditions(value: Any) -> str:
    """Return a deterministic semantic condition key for matching/deduplication."""

    if not isinstance(value, Mapping) or not value:
        return "{}"
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _has_numeric_value(item: Mapping[str, Any]) -> bool:
    if item.get("value_min") is not None:
        return True
    return bool(NUMERIC_PATTERN.search(str(item.get("value_raw") or "")))


def _specialized_property_name(item: Mapping[str, Any]) -> str:
    source_field = str(item.get("source_field") or "")
    variant = str(item.get("variant") or "").casefold()
    if source_field == "average_molecular_weight":
        return {
            "number_average": "Mn",
            "weight_average": "Mw",
            "z_average": "Mz",
            "viscosity_average": "Mv",
        }.get(variant, str(item.get("semantic_label") or "molecular_weight"))
    if source_field == "solution_viscosity":
        return {
            "inherent": "inherent_viscosity",
            "intrinsic": "intrinsic_viscosity",
            "reduced": "reduced_viscosity",
            "specific": "specific_viscosity",
            "": "solution_viscosity",
        }.get(variant, str(item.get("semantic_label") or source_field))
    return str(item.get("semantic_label") or source_field)


def _atomic_numeric_values(value: Any) -> list[float]:
    """Parse a reported numeric list as discrete values, never as a range."""

    text = str(value or "")
    # Preserve decimal-list commas while removing unambiguous thousands
    # separators such as ``14,200``.
    text = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", text)
    result: list[float] = []
    for match in ATOMIC_NUMERIC_PATTERN.finditer(text):
        token = match.group()
        token = re.sub(r"[eE]\(([+-]?\d+)\)$", r"e\1", token)
        try:
            result.append(float(token))
        except ValueError:
            continue
    return result


def ordinary_numeric_records(candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
    records = []
    condition_map = _measurement_condition_map(candidate)
    for item in candidate.get("property_observations") or []:
        if not isinstance(item, Mapping) or not _has_numeric_value(item):
            continue
        records.append(dict(item) | {
            "conditions": _record_conditions(item, condition_map=condition_map),
            "diagnostic_source": "ordinary_property",
        })
    return records


def property_series_numeric_records(candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Materialize one comparable record per numeric PropertySeries point."""
    records: list[dict[str, Any]] = []
    for series in candidate.get("property_series") or []:
        if not isinstance(series, Mapping):
            continue
        for point in series.get("points") or []:
            if not isinstance(point, Mapping) or not _has_numeric_value(point):
                continue
            records.append(dict(point) | {
                "property_name_raw": series.get("property_name_raw"),
                "property_name_normalized": series.get("property_name_normalized"),
                "property_code": series.get("property_code"),
                "property_category": series.get("property_category"),
                "unit_raw": point.get("unit_raw") or series.get("unit_raw"),
                "unit_normalized": point.get("unit_normalized") or series.get("unit_normalized"),
                "sample_id": point.get("sample_id") or series.get("sample_id"),
                "entity_id": point.get("entity_id") or series.get("entity_id"),
                "conditions": _record_conditions(
                    point,
                    inherited_context=series.get("measurement_context"),
                ),
                "diagnostic_source": "property_series_point",
                "source_series_id": series.get("series_id"),
            })
    return records


def published_specialized_numeric_records(
    candidate: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Materialize numeric records from the released specialized-property table."""
    records: list[dict[str, Any]] = []
    for item in candidate.get("specialized_property_observations") or []:
        if (
            not isinstance(item, Mapping)
            or item.get("publication_status") != "published"
            or not _has_numeric_value(item)
        ):
            continue
        property_name = _specialized_property_name(item)
        base = dict(item) | {
            "property_name_raw": property_name,
            "property_name_normalized": property_name,
            "conditions": _record_conditions(item),
            "diagnostic_source": "published_specialized_property",
        }
        if item.get("value_kind") == "numeric_multiple":
            values = _atomic_numeric_values(item.get("value_raw"))
            for index, value in enumerate(values):
                records.append(base | {
                    "property_id": f"{item.get('specialized_id') or 'specialized'}:value:{index}",
                    "value_min": value,
                    "value_max": value,
                    "specialized_component_index": index,
                })
            continue
        records.append(base)
    return records


def deduplicate_numeric_records(
    records: list[dict[str, Any]],
    *,
    canonical_name: Callable[[dict[str, Any]], str],
    normalized_value: Callable[[dict[str, Any]], tuple[float | None, float | None, str]],
) -> list[dict[str, Any]]:
    """Remove duplicate candidate facts without collapsing different samples."""
    unique: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for item in records:
        minimum, maximum, unit = normalized_value(item)
        if minimum is None:
            value_key: tuple[Any, ...] = (str(item.get("value_raw") or ""),)
        else:
            value_key = (
                format(float(minimum), ".12g"),
                format(float(maximum if maximum is not None else minimum), ".12g"),
            )
        key = (
            canonical_name(item),
            *value_key,
            unit,
            item.get("sample_id"),
            canonical_conditions(item.get("conditions")),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def unified_numeric_records(
    candidate: Mapping[str, Any],
    *,
    canonical_name: Callable[[dict[str, Any]], str] | None = None,
    normalized_value: Callable[[dict[str, Any]], tuple[float | None, float | None, str]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Return ordinary + series-point + released-specialized numeric facts.

    If canonicalization callbacks are provided, exact duplicate facts are removed.
    Both raw inventory and the deduplicated evaluation count are reported.
    """
    ordinary = ordinary_numeric_records(candidate)
    series = property_series_numeric_records(candidate)
    specialized = published_specialized_numeric_records(candidate)
    raw_records = ordinary + series + specialized
    records = raw_records
    if canonical_name is not None and normalized_value is not None:
        records = deduplicate_numeric_records(
            raw_records,
            canonical_name=canonical_name,
            normalized_value=normalized_value,
        )
    inventory = {
        "ordinary_numeric_records": len(ordinary),
        "property_series": len(candidate.get("property_series") or []),
        "property_series_points": sum(
            len(item.get("points") or [])
            for item in candidate.get("property_series") or []
            if isinstance(item, Mapping)
        ),
        "numeric_property_series_points": len(series),
        "published_specialized_records": sum(
            item.get("publication_status") == "published"
            for item in candidate.get("specialized_property_observations") or []
            if isinstance(item, Mapping)
        ),
        "published_specialized_numeric_records": len(specialized),
        "raw_unified_numeric_records": len(raw_records),
        "deduplicated_unified_numeric_records": len(records),
    }
    return records, inventory
