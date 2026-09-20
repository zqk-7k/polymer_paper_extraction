"""Stage 4P: schema-aware recovery of already extracted table properties.

Stage 4P is deterministic.  It never reads evaluation gold data, never invents
samples, and never publishes a source conflict.  It writes a preview and a
complete decision audit; ``--apply`` atomically replaces Stage 4 after keeping
the pre-Stage-4P document as a backup.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

EXTRACTION_ROOT = Path(__file__).resolve().parents[1]
if str(EXTRACTION_ROOT) not in sys.path:
    sys.path.insert(0, str(EXTRACTION_ROOT))

from schema.polymer_schema import (  # noqa: E402
    MeasurementCondition,
    MeasurementContext,
    PropertyObservation,
    Stage0Document,
    Stage4Document,
)
from stages.property_publication_policy import (  # noqa: E402
    POLICY_VERSION,
    canonical_property,
    compact,
    decide_quantity,
    looks_like_material_label,
    looks_like_property_or_condition_label,
    number_close,
    numeric_values,
)


STAGE_ID = "stage4p_publication_recovery"
IMPLEMENTATION_VERSION = "1.5.0"
OUTPUT_NAME = "stage4_properties.p2_preview.json"
AUDIT_NAME = "stage4p_publication_audit.json"
BACKUP_NAME = "stage4_properties.pre_p2.json"

_PROPERTY_ID_RE = re.compile(r"^prop(\d+)$")
_CONDITION_ID_RE = re.compile(r"^mc(\d+)$")
_SAFE_PRE_UNIFIED_STATUSES = frozenset({
    "pre_unified_release_eligible",
    "stage4_property_preserved",
    "retained_stage4_property",
    "stage4t_axis_semantic_conflict_ignored",
})
_FATAL_AUDIT_STATUSES = frozenset({"source_conflict"})
_PERMITTED_SHADOW_BLOCKERS = frozenset({
    "sample_not_resolved",
    "subject_not_resolved",
})
_JOINED_SAMPLE_LABEL_RE = re.compile(r"\s+\|\s+")
_MIXTURE_LABEL_RE = re.compile(
    r"\b(?:blend|mixture|composite|compound|copolymer)\b|"
    r"共混|混合|复合",
    re.IGNORECASE,
)
_ENTRY_LABEL_RE = re.compile(r"(?:\d+[a-z]?|[a-z])", re.IGNORECASE)
_CONTINUATION_LABEL_RE = re.compile(r"[b-z]", re.IGNORECASE)
_POLYMERIZATION_METHOD_RE = re.compile(
    r"^\s*(HTS|LTS)(?:[a-z])?\s*$",
    re.IGNORECASE,
)
_TRAILING_ACRONYM_RE = re.compile(r"\s*\(([A-Z]{2,8})\)\s*$")
_NUMBER_TOKEN = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
_RATIO_FULL_RE = re.compile(
    rf"\s*({_NUMBER_TOKEN})\s*%?\s*([:/])\s*({_NUMBER_TOKEN})\s*%?\s*"
)
_RATIO_SEARCH_RE = re.compile(
    rf"(?<![\w.])({_NUMBER_TOKEN})\s*%?\s*([:/])\s*"
    rf"({_NUMBER_TOKEN})\s*%?(?![\w.])"
)


class Stage4PError(RuntimeError):
    """Stage 4P input, policy, or output contract error."""


def _payload(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        return dict(dumped)
    if isinstance(value, Mapping):
        return copy.deepcopy(dict(value))
    raise TypeError(f"Expected model or mapping, got {type(value).__name__}")


def _read_json(path: Path, *, required: bool = True) -> dict[str, Any]:
    if not path.is_file():
        if required:
            raise Stage4PError(f"Missing Stage 4P input: {path}")
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage4PError(f"Invalid JSON input: {path}") from exc
    if not isinstance(value, dict):
        raise Stage4PError(f"Stage 4P input must be a JSON object: {path}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _copy_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    shutil.copy2(source, temporary)
    temporary.replace(destination)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _archive_path(backup_path: Path, digest: str) -> Path:
    """Return a content-addressed path for a superseded pre-P2 baseline."""

    return backup_path.with_name(f"{backup_path.stem}.{digest}{backup_path.suffix}")


def _sync_pre_p2_backup(base_stage4: Path, backup_path: Path) -> dict[str, Any]:
    """Make the canonical backup equal this run's audited base without data loss.

    Repeated P2 runs may follow a fresh upstream Stage 4 run in the same folder.
    In that case the old canonical backup is no longer this run's input. Preserve
    it under a content-addressed name, then replace the canonical backup with the
    exact base whose hash is recorded in the audit.
    """

    base_hash = _sha256(base_stage4)
    result: dict[str, Any] = {
        "path": str(backup_path),
        "sha256": base_hash,
        "archived_previous_path": None,
        "archived_previous_sha256": None,
    }
    if backup_path.is_file():
        backup_hash = _sha256(backup_path)
        if backup_hash == base_hash:
            return result
        archive_path = _archive_path(backup_path, backup_hash)
        if archive_path.is_file():
            if _sha256(archive_path) != backup_hash:
                raise Stage4PError(
                    "Pre-P2 history archive hash collision: "
                    f"{archive_path}"
                )
        else:
            _copy_atomic(backup_path, archive_path)
        result["archived_previous_path"] = str(archive_path)
        result["archived_previous_sha256"] = backup_hash

    if base_stage4.resolve() != backup_path.resolve():
        _copy_atomic(base_stage4, backup_path)
    if not backup_path.is_file() or _sha256(backup_path) != base_hash:
        raise Stage4PError(
            "Canonical pre-P2 backup does not match this run's audited base"
        )
    return result


def _optional_hash(path: Path) -> str | None:
    return _sha256(path) if path.is_file() else None


def _next_id(items: Sequence[Mapping[str, Any]], field: str, pattern: re.Pattern[str]) -> int:
    values = []
    for item in items:
        match = pattern.fullmatch(str(item.get(field) or ""))
        if match:
            values.append(int(match.group(1)))
    return max(values, default=0) + 1


def _table_index(stage0: Stage0Document) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    tables: dict[str, dict[str, Any]] = {}
    cells: dict[str, dict[str, Any]] = {}
    for element in stage0.elements:
        if element.type != "table":
            continue
        table = element.model_dump(mode="json")
        tables[element.block_id] = table
        for cell in table.get("table_cells") or []:
            if isinstance(cell, Mapping) and cell.get("cell_id"):
                cells[str(cell["cell_id"])] = dict(cell)
    return tables, cells


def _series_response_evidence(
    point: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str]:
    evidence = point.get("evidence")
    if not isinstance(evidence, list) or len(evidence) != 1:
        return None, "property_series_response_evidence_not_unique"
    item = evidence[0]
    if not isinstance(item, Mapping):
        return None, "property_series_response_evidence_invalid"
    return dict(item), ""


def _exact_coordinate_cell(
    coordinate: Mapping[str, Any],
    *,
    table: Mapping[str, Any],
    table_id: str,
    response_row: int,
    response_column: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str]:
    """Return one exact same-row coordinate cell and its canonical locator.

    The recovery deliberately does not infer a coordinate from a nearby value.
    Its column header must occur at exactly one column before the response row,
    and the cell covering that column on the response row must equal the
    coordinate's reported surface text.
    """

    evidence = coordinate.get("evidence")
    if not isinstance(evidence, Mapping):
        return None, None, "property_series_coordinate_evidence_missing"
    locator = evidence.get("table_locator")
    if not isinstance(locator, Mapping):
        return None, None, "property_series_coordinate_locator_missing"
    if str(evidence.get("block_id") or "") != table_id:
        return None, None, "property_series_coordinate_table_mismatch"
    if str(locator.get("table_id") or "") != table_id:
        return None, None, "property_series_coordinate_table_mismatch"
    source_sentence = str(evidence.get("source_sentence") or "").strip()
    value_raw = str(coordinate.get("value_raw") or "").strip()
    if not value_raw or source_sentence != value_raw:
        return None, None, "property_series_coordinate_surface_mismatch"
    column_label = str(locator.get("column_label") or "").strip()
    if not column_label or column_label != str(coordinate.get("name_raw") or "").strip():
        return None, None, "property_series_coordinate_header_mismatch"

    table_cells = [
        dict(cell)
        for cell in table.get("table_cells") or []
        if isinstance(cell, Mapping)
    ]
    header_columns: set[int] = set()
    header_text_by_column: dict[int, str] = {}
    for cell in table_cells:
        text = str(cell.get("text") or "").strip()
        row = cell.get("row_index")
        column = cell.get("column_index")
        if (
            text != column_label
            or not isinstance(row, int)
            or not isinstance(column, int)
            or row >= response_row
        ):
            continue
        span = _cell_span(cell, "column_span")
        for covered_column in range(column, column + span):
            if covered_column < response_column:
                header_columns.add(covered_column)
                header_text_by_column[covered_column] = text
    if len(header_columns) != 1:
        return None, None, "property_series_coordinate_header_not_unique"
    coordinate_column = next(iter(header_columns))
    cell = _covering_cell(table_cells, response_row, coordinate_column)
    if cell is None or not cell.get("cell_id"):
        return None, None, "property_series_coordinate_cell_not_found"
    cell_text = str(cell.get("text") or "").strip()
    if cell_text != value_raw:
        return None, None, "property_series_coordinate_cell_value_mismatch"

    row_cells = [
        item
        for column in range(response_column)
        if (item := _covering_cell(table_cells, response_row, column)) is not None
        and str(item.get("text") or "").strip()
    ]
    if not row_cells:
        return None, None, "property_series_coordinate_row_label_missing"
    row_label = str(row_cells[0].get("text") or "").strip()
    canonical = {
        **dict(locator),
        "table_id": table_id,
        "row_label": row_label,
        "column_label": header_text_by_column[coordinate_column],
        "cell_value": cell_text,
        "cell_id": str(cell["cell_id"]),
        "row_index": response_row,
        "column_index": coordinate_column,
    }
    return dict(cell), canonical, ""


def _repair_property_series_scalar_locators(
    output: dict[str, Any],
    *,
    tables: Mapping[str, Mapping[str, Any]],
    cells: Mapping[str, Mapping[str, Any]],
    stage2: Mapping[str, Any],
    sample_by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """Repair only exact coordinate locators on existing scalar series points.

    A coordinate cell can be repeated verbatim by several property series.  We
    make one conservative decision per physical coordinate cell, then apply an
    accepted canonical locator to every identical occurrence.  The first
    occurrence is the audited source object.  If that occurrence is a range or
    multi-value point, the physical coordinate is fail-closed and later scalar
    duplicates cannot silently override that decision.
    """

    entity_ids = {
        str(item.get("entity_id"))
        for item in stage2.get("polymer_entities") or []
        if isinstance(item, Mapping) and item.get("entity_id")
    }
    decisions: dict[str, tuple[str, dict[str, Any] | None]] = {}
    repairs: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    repaired_occurrences = 0

    for series in output.get("property_series") or []:
        if not isinstance(series, dict):
            continue
        series_id = str(series.get("series_id") or "")
        normalized_property = str(series.get("property_name_normalized") or "").strip()
        normalized_unit = str(series.get("unit_normalized") or "").strip()
        family = canonical_property(series)
        for point in series.get("points") or []:
            if not isinstance(point, dict):
                continue
            point_value = str(point.get("value_raw") or "").strip()
            if (
                point.get("coverage_status") != "covered"
                or not point_value
                or not numeric_values(point_value)
            ):
                continue
            coordinates = point.get("coordinates")
            if not isinstance(coordinates, list) or not coordinates:
                continue

            response_evidence, response_reason = _series_response_evidence(point)
            response_locator = (
                response_evidence.get("table_locator")
                if isinstance(response_evidence, Mapping) else None
            )
            response_cell_id = str(
                (
                    response_locator.get("cell_id")
                    if isinstance(response_locator, Mapping) else ""
                ) or ""
            )
            response_cell = cells.get(response_cell_id)
            table_id = str(
                (
                    response_locator.get("table_id")
                    if isinstance(response_locator, Mapping) else ""
                ) or ""
            )
            table = tables.get(table_id)
            response_row = (
                response_cell.get("row_index")
                if isinstance(response_cell, Mapping) else None
            )
            response_column = (
                response_cell.get("column_index")
                if isinstance(response_cell, Mapping) else None
            )

            coordinate_plans: list[tuple[dict[str, Any], str, dict[str, Any]]] = []
            plan_reason = ""
            if (
                response_reason
                or not isinstance(response_locator, Mapping)
                or not isinstance(response_cell, Mapping)
                or table is None
                or not isinstance(response_row, int)
                or not isinstance(response_column, int)
            ):
                plan_reason = response_reason or "property_series_response_cell_not_found"
            elif str(response_evidence.get("block_id") or "") != table_id:
                plan_reason = "property_series_response_table_mismatch"
            elif str(response_cell.get("text") or "").strip() != str(point.get("value_raw") or "").strip():
                plan_reason = "property_series_response_cell_value_mismatch"
            elif str(response_evidence.get("source_sentence") or "").strip() != str(point.get("value_raw") or "").strip():
                plan_reason = "property_series_response_surface_mismatch"
            else:
                for coordinate in coordinates:
                    if not isinstance(coordinate, dict):
                        plan_reason = "property_series_coordinate_invalid"
                        break
                    cell, canonical, reason = _exact_coordinate_cell(
                        coordinate,
                        table=table,
                        table_id=table_id,
                        response_row=response_row,
                        response_column=response_column,
                    )
                    if cell is None or canonical is None:
                        plan_reason = reason
                        break
                    evidence = coordinate.get("evidence")
                    current = (
                        evidence.get("table_locator")
                        if isinstance(evidence, Mapping) else None
                    )
                    if not isinstance(current, Mapping) or any(
                        current.get(key) != canonical.get(key)
                        for key in (
                            "table_id", "row_label", "column_label", "cell_value",
                            "cell_id", "row_index", "column_index",
                        )
                    ):
                        coordinate_plans.append(
                            (coordinate, str(cell["cell_id"]), canonical)
                        )
            if not coordinate_plans and not plan_reason:
                continue

            new_coordinate_ids = [
                cell_id for _coordinate, cell_id, _canonical in coordinate_plans
                if cell_id not in decisions
            ]
            if not new_coordinate_ids and any(
                decisions.get(cell_id, ("", None))[0] == "blocked"
                for _coordinate, cell_id, _canonical in coordinate_plans
            ):
                continue

            point_id = str(point.get("point_id") or "")
            base_outcome = {
                "source_stage": "stage4_property_series",
                "source_id": point_id or None,
                "series_id": series_id or None,
                "response_cell_id": response_cell_id or None,
            }
            values = numeric_values(point_value)
            value_min = point.get("value_min")
            value_max = point.get("value_max")
            sample_id = str(point.get("sample_id") or "")
            entity_id = str(point.get("entity_id") or "")
            sample = sample_by_id.get(sample_id)

            rejection_reason = plan_reason
            if not rejection_reason and (
                not normalized_property or not family or not normalized_unit
            ):
                rejection_reason = "property_series_semantic_or_unit_missing"
            elif not rejection_reason and (
                point.get("sample_resolution_status") != "resolved"
                or sample is None
                or entity_id not in entity_ids
                or str(sample.get("refers_to_entity") or "") != entity_id
            ):
                rejection_reason = "property_series_sample_entity_not_exact"
            elif not rejection_reason and (
                len(values) != 1
                or not isinstance(value_min, (int, float))
                or isinstance(value_min, bool)
                or not isinstance(value_max, (int, float))
                or isinstance(value_max, bool)
                or not number_close(float(value_min), float(value_max))
                or not number_close(float(value_min), values[0])
            ):
                rejection_reason = "property_series_non_scalar_not_repaired"
            elif not rejection_reason and any(
                decisions.get(cell_id, ("", None))[0] == "blocked"
                for _coordinate, cell_id, _canonical in coordinate_plans
            ):
                rejection_reason = "property_series_coordinate_previously_blocked"

            if rejection_reason:
                for cell_id in new_coordinate_ids:
                    decisions[cell_id] = ("blocked", None)
                if new_coordinate_ids or plan_reason:
                    rejections.append({
                        **base_outcome,
                        "status": "rejected",
                        "reason": rejection_reason,
                        "coordinate_cell_ids": new_coordinate_ids,
                    })
                continue

            for _coordinate, cell_id, canonical in coordinate_plans:
                if cell_id not in decisions:
                    decisions[cell_id] = ("repair", copy.deepcopy(canonical))
            repaired_in_point: list[str] = []
            for coordinate, cell_id, _canonical in coordinate_plans:
                decision, decided_locator = decisions[cell_id]
                if decision != "repair" or decided_locator is None:
                    continue
                evidence = coordinate["evidence"]
                evidence["table_locator"] = copy.deepcopy(decided_locator)
                repaired_in_point.append(cell_id)
                repaired_occurrences += 1
            if new_coordinate_ids:
                repairs.append({
                    **base_outcome,
                    "status": "locator_repaired",
                    "reason": "exact_same_row_coordinate_locator",
                    "property_name": family,
                    "unit": normalized_unit,
                    "sample_id": sample_id,
                    "entity_id": entity_id,
                    "coordinate_cell_ids": repaired_in_point,
                })

    if repairs:
        output.setdefault("warnings", []).append({
            "stage": STAGE_ID,
            "code": "property_series_coordinate_locator_repaired",
            "message": (
                f"已按响应 cell 的同一表格行修复 {len(repairs)} 个标量 "
                f"PropertySeries 源对象，共 {repaired_occurrences} 个坐标 locator；"
                "未修改性质、数值、单位、样品或实体。"
            ),
        })
    return repairs, rejections, repaired_occurrences


def _entity_aliases(stage2: Mapping[str, Any]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for entity in stage2.get("polymer_entities") or []:
        if not isinstance(entity, Mapping) or not entity.get("entity_id"):
            continue
        entity_id = str(entity["entity_id"])
        for field in (
            "polymer_name", "canonical_name", "normalized_name", "display_name",
        ):
            if entity.get(field):
                result[entity_id].add(str(entity[field]))
        result[entity_id].update(
            str(value) for value in entity.get("source_names") or [] if value
        )
    return result


def _sample_indexes(
    stage2: Mapping[str, Any],
    stage3: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]], dict[str, set[str]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_label: dict[str, list[str]] = defaultdict(list)
    aliases_by_sample: dict[str, set[str]] = defaultdict(set)
    entity_names = _entity_aliases(stage2)
    for source in stage3.get("samples") or []:
        if not isinstance(source, Mapping) or not source.get("sample_id"):
            continue
        sample = dict(source)
        sample_id = str(sample["sample_id"])
        if not re.fullmatch(r"s\d{3,}", sample_id):
            continue
        by_id[sample_id] = sample
        labels = {
            str(sample.get(field) or "").strip()
            for field in ("sample_label_raw", "polymer_name", "state_description")
            if str(sample.get(field) or "").strip()
        }
        labels.update(entity_names.get(str(sample.get("refers_to_entity") or ""), set()))
        for label in labels:
            normalized = compact(label)
            if normalized:
                aliases_by_sample[sample_id].add(normalized)
                if sample_id not in by_label[normalized]:
                    by_label[normalized].append(sample_id)
    return by_id, dict(by_label), dict(aliases_by_sample)


def _sample_surfaces(sample: Mapping[str, Any]) -> list[str]:
    """Return only text that Stage 3 preserved as direct sample evidence."""

    values = [
        sample.get("sample_label_raw"),
        sample.get("polymer_name"),
        sample.get("state_description"),
    ]
    evidence = sample.get("evidence")
    if isinstance(evidence, Mapping):
        values.append(evidence.get("source_sentence"))
    return [str(value) for value in values if str(value or "").strip()]


def _decimal_key(value: str) -> str | None:
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    if not number.is_finite():
        return None
    return format(number.normalize(), "f")


def _ratio_signature(value: Any, *, full: bool) -> tuple[str, str, str] | None:
    text = str(value or "")
    match = _RATIO_FULL_RE.fullmatch(text) if full else _RATIO_SEARCH_RE.search(text)
    if match is None:
        return None
    left = _decimal_key(match.group(1))
    right = _decimal_key(match.group(3))
    if left is None or right is None:
        return None
    return left, match.group(2), right


def _sample_ratio_signatures(sample: Mapping[str, Any]) -> set[tuple[str, str, str]]:
    signatures: set[tuple[str, str, str]] = set()
    for surface in _sample_surfaces(sample):
        for match in _RATIO_SEARCH_RE.finditer(surface):
            left = _decimal_key(match.group(1))
            right = _decimal_key(match.group(3))
            if left is not None and right is not None:
                signatures.add((left, match.group(2), right))
    return signatures


def _ratio_sample_matches(
    value: str,
    by_id: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """Match an explicit ratio only when one Stage 3 sample owns that ratio."""

    signature = _ratio_signature(value, full=True)
    if signature is None:
        return []
    return sorted(
        sample_id
        for sample_id, sample in by_id.items()
        if signature in _sample_ratio_signatures(sample)
    )


def _joined_label_matches(
    label: str,
    by_id: Mapping[str, Mapping[str, Any]],
    by_label: Mapping[str, Sequence[str]],
) -> tuple[list[str], str | None]:
    """Resolve safe Stage 4T ``A | B`` labels without selecting a component.

    Stage 4T joins multiple sample-axis cells with `` | ``.  A segment may be
    used only when every other segment is demonstrably an entry identifier or
    a numeric composition ratio.  Mixture-bearing labels require a full Stage
    3 label match and are never reduced to one material component.
    """

    parts = [part.strip() for part in _JOINED_SAMPLE_LABEL_RE.split(label) if part.strip()]
    if len(parts) < 2 or _MIXTURE_LABEL_RE.search(label):
        return [], None
    owners: set[str] = set()
    matched = False
    for part in parts:
        exact = list(by_label.get(compact(part), ()))
        ratio = _ratio_sample_matches(part, by_id)
        part_owners = set(exact) | set(ratio)
        if part_owners:
            owners.update(part_owners)
            matched = True
            continue
        if _ENTRY_LABEL_RE.fullmatch(part) or _ratio_signature(part, full=True):
            continue
        return [], None
    if not matched:
        return [], None
    return sorted(owners), "unique_joined_stage3_alias"


def _cell_span(cell: Mapping[str, Any], field: str) -> int:
    value = cell.get(field)
    return int(value) if isinstance(value, int) and value > 0 else 1


def _covering_cell(
    table_cells: Sequence[Mapping[str, Any]],
    row: int,
    column: int,
) -> Mapping[str, Any] | None:
    return next((
        cell
        for cell in table_cells
        if int(cell.get("row_index", -1)) <= row
        < int(cell.get("row_index", -1)) + _cell_span(cell, "row_span")
        and int(cell.get("column_index", -1)) <= column
        < int(cell.get("column_index", -1)) + _cell_span(cell, "column_span")
    ), None)


def _unique_exact_owner(
    values: Sequence[str],
    by_label: Mapping[str, Sequence[str]],
) -> tuple[str | None, str | None, bool]:
    matches: dict[str, str] = {}
    ambiguous = False
    for value in values:
        owners = list(by_label.get(compact(value), ()))
        if len(owners) > 1:
            ambiguous = True
        for owner in owners:
            matches.setdefault(owner, value)
    if ambiguous or len(matches) > 1:
        return None, None, True
    if len(matches) == 1:
        owner = next(iter(matches))
        return owner, matches[owner], False
    return None, None, False


def _table_parent_sample(
    candidate: Mapping[str, Any],
    tables: Mapping[str, Mapping[str, Any]],
    by_label: Mapping[str, Sequence[str]],
) -> dict[str, Any] | None:
    """Resolve an explicit rowspan or a structurally marked blank continuation.

    The fallback never uses property values, never borrows from a later row,
    and stops at the first preceding non-continuation entry.  Parent labels are
    accepted only by a globally unique exact Stage 3 alias.
    """

    locator = _locator(candidate)
    table = tables.get(str(locator.get("table_id") or candidate.get("table_id") or ""))
    row = locator.get("row_index", candidate.get("row_index"))
    column = locator.get("column_index", candidate.get("column_index"))
    if table is None or not isinstance(row, int) or not isinstance(column, int):
        return None
    table_cells = [
        cell for cell in table.get("table_cells") or [] if isinstance(cell, Mapping)
    ]

    spanning = [
        cell
        for cell in table_cells
        if int(cell.get("column_index", -1)) < column
        and int(cell.get("row_index", -1)) < row
        and int(cell.get("row_index", -1)) + _cell_span(cell, "row_span") > row
        and str(cell.get("text") or "").strip()
    ]
    owner, parent_label, ambiguous = _unique_exact_owner(
        [str(cell.get("text") or "").strip() for cell in spanning], by_label,
    )
    if ambiguous:
        return {
            "status": "ambiguous_sample",
            "reason": "stage3_label_ambiguous",
            "label": str(candidate.get("sample_label_raw") or "").strip(),
            "matches": [],
        }
    if owner is not None:
        return {
            "status": "matched",
            "reason": "table_rowspan_parent_exact_alias",
            "sample_id": owner,
            "label": parent_label,
            "matches": [owner],
        }

    label = str(candidate.get("sample_label_raw") or "").strip()
    if not _CONTINUATION_LABEL_RE.fullmatch(label):
        return None
    marker_cells = [
        cell
        for cell in table_cells
        if int(cell.get("row_index", -1)) == row
        and int(cell.get("column_index", -1)) < column
        and str(cell.get("text") or "").strip().casefold() == label.casefold()
    ]
    if len(marker_cells) != 1:
        return None
    marker_column = int(marker_cells[0].get("column_index", -1))
    for prior_row in range(row - 1, -1, -1):
        marker = _covering_cell(table_cells, prior_row, marker_column)
        marker_text = str(marker.get("text") or "").strip() if marker else ""
        if not marker_text or _CONTINUATION_LABEL_RE.fullmatch(marker_text):
            continue

        parent_cells = [
            cell
            for cell in table_cells
            if int(cell.get("row_index", -1)) <= prior_row
            < int(cell.get("row_index", -1)) + _cell_span(cell, "row_span")
            and marker_column < int(cell.get("column_index", -1)) < column
            and str(cell.get("text") or "").strip()
        ]
        parent_owner, parent_label, parent_ambiguous = _unique_exact_owner(
            [str(cell.get("text") or "").strip() for cell in parent_cells], by_label,
        )
        if parent_ambiguous:
            return {
                "status": "ambiguous_sample",
                "reason": "stage3_label_ambiguous",
                "label": label,
                "matches": [],
            }
        if parent_owner is None:
            return None
        parent_column = next(
            int(cell.get("column_index", -1))
            for cell in parent_cells
            if compact(cell.get("text")) == compact(parent_label)
        )
        current_parent_cell = _covering_cell(table_cells, row, parent_column)
        if current_parent_cell is not None and str(current_parent_cell.get("text") or "").strip():
            return None
        return {
            "status": "matched",
            "reason": "table_blank_continuation_parent_exact_alias",
            "sample_id": parent_owner,
            "label": parent_label,
            "matches": [parent_owner],
        }
    return None


def _paired_shift_process_binding(
    candidate: Mapping[str, Any],
    sample_id: str,
    tables: Mapping[str, Mapping[str, Any]],
    stage3: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate a shifted property cell against the row's synthesis method.

    A missing colspan can shift a PMT value into the neighbouring viscosity
    column.  Recovering the number is safe, but a blank polymer-code cell can
    still make several independently prepared table rows collapse onto one
    Stage 3 sample.  For this inferred alignment, publication therefore
    requires an explicit HTS/LTS token in the source row and the same token on
    a Stage 3 process that produces the resolved sample.  The value remains in
    the non-authoritative Stage 4T candidate layer when this check fails.
    """

    if str(candidate.get("alignment_status") or "") != "paired_right_shift":
        return {"accepted": True, "basis": None}

    locator = _locator(candidate)
    table_id = str(locator.get("table_id") or candidate.get("table_id") or "")
    row = locator.get("row_index", candidate.get("row_index"))
    table = tables.get(table_id)
    if table is None or not isinstance(row, int):
        return {
            "accepted": False,
            "reason": "paired_shift_process_binding_unverified",
            "row_methods": [],
            "sample_process_methods": [],
        }

    row_methods: set[str] = set()
    for cell in table.get("table_cells") or []:
        if not isinstance(cell, Mapping) or int(cell.get("row_index", -1)) != row:
            continue
        match = _POLYMERIZATION_METHOD_RE.fullmatch(str(cell.get("text") or ""))
        if match:
            row_methods.add(match.group(1).upper())

    sample_methods: set[str] = set()
    for step in stage3.get("process_steps") or []:
        if not isinstance(step, Mapping) or sample_id not in {
            str(value) for value in step.get("output_sample_ids") or []
        }:
            continue
        surfaces: list[str] = [str(step.get("process_type") or "")]
        parameters = step.get("parameters")
        if isinstance(parameters, Mapping):
            surfaces.extend(str(value) for value in parameters.values())
        evidence = step.get("evidence")
        if isinstance(evidence, Mapping):
            surfaces.append(str(evidence.get("source_sentence") or ""))
        for surface in surfaces:
            sample_methods.update(
                match.group(1).upper()
                for match in re.finditer(r"(?<![A-Za-z])(HTS|LTS)(?![A-Za-z])", surface, re.IGNORECASE)
            )

    if not row_methods or not sample_methods:
        return {
            "accepted": False,
            "reason": "paired_shift_process_binding_unverified",
            "row_methods": sorted(row_methods),
            "sample_process_methods": sorted(sample_methods),
        }
    if row_methods.isdisjoint(sample_methods):
        return {
            "accepted": False,
            "reason": "paired_shift_process_binding_conflict",
            "row_methods": sorted(row_methods),
            "sample_process_methods": sorted(sample_methods),
        }
    return {
        "accepted": True,
        "basis": "paired_shift_row_method_matches_stage3_producer",
        "row_methods": sorted(row_methods),
        "sample_process_methods": sorted(sample_methods),
    }


def _locator(candidate: Mapping[str, Any]) -> dict[str, Any]:
    locator_hint = candidate.get("evidence_locator")
    result = dict(locator_hint) if isinstance(locator_hint, Mapping) else {}
    for evidence in candidate.get("evidence") or []:
        if isinstance(evidence, Mapping):
            locator = evidence.get("table_locator")
            if isinstance(locator, Mapping):
                return {**result, **dict(locator)}
    evidence = candidate.get("evidence")
    if isinstance(evidence, Mapping):
        locator = evidence.get("table_locator")
        if isinstance(locator, Mapping):
            return {**result, **dict(locator)}
        for key in ("table_id", "cell_id", "row_index", "column_index"):
            if evidence.get(key) is not None:
                result.setdefault(key, evidence.get(key))
    for key in ("table_id", "cell_id", "row_index", "column_index"):
        if candidate.get(key) is not None:
            result.setdefault(key, candidate.get(key))
    return result


def _cell_ids(candidate: Mapping[str, Any]) -> set[str]:
    result: set[str] = set()
    locator = _locator(candidate)
    if locator.get("cell_id"):
        result.add(str(locator["cell_id"]))
    for evidence in candidate.get("evidence") or []:
        if not isinstance(evidence, Mapping):
            continue
        nested = evidence.get("table_locator")
        if isinstance(nested, Mapping) and nested.get("cell_id"):
            result.add(str(nested["cell_id"]))
    return result


def _axis_labels(candidate: Mapping[str, Any]) -> tuple[str, str]:
    locator = _locator(candidate)
    row_label = str(
        locator.get("row_label") or candidate.get("sample_label_raw") or ""
    ).strip()
    column_label = str(locator.get("column_label") or "").strip()
    if not column_label:
        header_path = locator.get("header_path")
        if isinstance(header_path, list) and header_path:
            column_label = str(header_path[-1]).strip()
    if not column_label:
        column_label = str(candidate.get("property_name_raw") or "").strip()
    return row_label, column_label


def _property_axis_header(candidate: Mapping[str, Any]) -> str:
    """Return only evidence belonging to the property axis.

    Sample labels may legitimately contain percentages (for example
    ``100% Amylopectin``).  They must never be joined into the surface used to
    prove a response unit.
    """

    raw = str(candidate.get("property_name_raw") or "").strip()
    if raw:
        return raw
    locator = _locator(candidate)
    header_path = locator.get("header_path")
    if isinstance(header_path, list):
        clean = [str(value).strip() for value in header_path if str(value).strip()]
        if clean:
            return " | ".join(clean)
    direction = str(candidate.get("direction") or "")
    if direction == "row_samples":
        return str(locator.get("column_label") or "").strip()
    if direction == "column_samples":
        return str(locator.get("row_label") or "").strip()
    return ""


def _resolve_sample(
    candidate: Mapping[str, Any],
    family: str,
    by_id: Mapping[str, Mapping[str, Any]],
    by_label: Mapping[str, Sequence[str]],
    aliases_by_sample: Mapping[str, set[str]],
    tables: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    row_label, column_label = _axis_labels(candidate)
    label = str(candidate.get("sample_label_raw") or row_label).strip()
    repaired = False
    if label and looks_like_property_or_condition_label(label, family):
        if looks_like_material_label(column_label):
            label = column_label
            repaired = True
        else:
            return {
                "status": "unmatched_sample",
                "reason": "sample_axis_is_property_or_condition",
                "label": label,
                "matches": [],
            }

    source_id = str(candidate.get("sample_id") or "")
    normalized_label = compact(label)
    if source_id:
        if source_id not in by_id:
            return {
                "status": "unmatched_sample",
                "reason": "source_sample_id_not_in_stage3",
                "label": label,
                "matches": [],
            }
        if normalized_label and normalized_label not in aliases_by_sample.get(source_id, set()):
            return {
                "status": "sample_conflict",
                "reason": "source_sample_id_label_conflict",
                "label": label,
                "matches": [source_id],
            }
        return {
            "status": "matched",
            "reason": "existing_stage3_sample_id",
            "sample_id": source_id,
            "label": label,
            "matches": [source_id],
            "axis_repaired": repaired,
        }

    matches = list(by_label.get(normalized_label, ())) if normalized_label else []
    if len(matches) == 1:
        return {
            "status": "matched",
            "reason": "exact_normalized_stage3_label",
            "sample_id": matches[0],
            "label": label,
            "matches": matches,
            "axis_repaired": repaired,
        }
    if len(matches) > 1:
        return {
            "status": "ambiguous_sample",
            "reason": "stage3_label_ambiguous",
            "label": label,
            "matches": matches,
        }

    acronym = _TRAILING_ACRONYM_RE.search(label)
    if acronym:
        base = label[:acronym.start()].strip()
        acronym_matches = list(by_label.get(compact(base), ())) if base else []
        if len(acronym_matches) == 1:
            return {
                "status": "matched",
                "reason": "unique_trailing_acronym_stage3_alias",
                "sample_id": acronym_matches[0],
                "label": label,
                "matches": acronym_matches,
                "axis_repaired": repaired,
            }
        if len(acronym_matches) > 1:
            return {
                "status": "ambiguous_sample",
                "reason": "ambiguous_trailing_acronym_alias",
                "label": label,
                "matches": acronym_matches,
            }

    if not _MIXTURE_LABEL_RE.search(label):
        ratio_matches = _ratio_sample_matches(label, by_id)
        if len(ratio_matches) == 1:
            return {
                "status": "matched",
                "reason": "unique_composition_ratio_stage3_alias",
                "sample_id": ratio_matches[0],
                "label": label,
                "matches": ratio_matches,
                "axis_repaired": repaired,
            }
        if len(ratio_matches) > 1:
            return {
                "status": "ambiguous_sample",
                "reason": "stage3_label_ambiguous",
                "label": label,
                "matches": ratio_matches,
            }

        joined_matches, joined_basis = _joined_label_matches(label, by_id, by_label)
        if len(joined_matches) == 1:
            return {
                "status": "matched",
                "reason": joined_basis,
                "sample_id": joined_matches[0],
                "label": label,
                "matches": joined_matches,
                "axis_repaired": repaired,
            }
        if len(joined_matches) > 1:
            return {
                "status": "ambiguous_sample",
                "reason": "stage3_label_ambiguous",
                "label": label,
                "matches": joined_matches,
            }

    parent = _table_parent_sample(candidate, tables, by_label)
    if parent is not None:
        parent.setdefault("axis_repaired", repaired)
        return parent
    return {
        "status": "unmatched_sample",
        "reason": "stage3_label_not_found",
        "label": label,
        "matches": [],
    }


def _shadow_candidates(shadow: Mapping[str, Any]) -> list[dict[str, Any]]:
    result = [
        dict(item) for item in shadow.get("observations") or []
        if isinstance(item, Mapping)
    ]
    for table in shadow.get("tables") or []:
        if not isinstance(table, Mapping):
            continue
        for source in table.get("observations") or []:
            if not isinstance(source, Mapping):
                continue
            item = dict(source)
            item.setdefault("table_id", table.get("table_id"))
            result.append(item)
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in result:
        key = (
            str(item.get("observation_id") or ""),
            str(item.get("cell_id") or _locator(item).get("cell_id") or ""),
            str(item.get("property_name_normalized") or item.get("property_name_raw") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _audit_outcomes_by_candidate(audit: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in audit.get("candidate_outcomes") or []:
        if not isinstance(row, Mapping):
            continue
        item = dict(row)
        for key in (
            "candidate_id", "cell_id", "stage4_property_id", "property_id",
        ):
            if item.get(key):
                result[str(item[key])].append(item)
    return dict(result)


def _pre_unified_allowlist(audit: Mapping[str, Any]) -> tuple[set[str], set[str]]:
    property_ids: set[str] = set()
    cell_ids: set[str] = set()
    for value in audit.get("pre_unified_release_allowlist") or []:
        if isinstance(value, str):
            if value.startswith("prop"):
                property_ids.add(value)
            else:
                cell_ids.add(value)
        elif isinstance(value, Mapping):
            if value.get("property_id") or value.get("stage4_property_id"):
                property_ids.add(str(value.get("property_id") or value.get("stage4_property_id")))
            if value.get("cell_id"):
                cell_ids.add(str(value["cell_id"]))
    for row in audit.get("candidate_outcomes") or []:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("status") or "") not in _SAFE_PRE_UNIFIED_STATUSES:
            continue
        if row.get("stage4_property_id") or row.get("property_id"):
            property_ids.add(str(row.get("stage4_property_id") or row.get("property_id")))
        if row.get("cell_id"):
            cell_ids.add(str(row["cell_id"]))
    return property_ids, cell_ids


def _pre_unified_candidates(
    pre_unified: Mapping[str, Any],
    audit: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    allowed_properties, allowed_cells = _pre_unified_allowlist(audit)
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    conditions = {
        str(item.get("condition_id")): dict(item)
        for item in pre_unified.get("measurement_conditions") or []
        if isinstance(item, Mapping) and item.get("condition_id")
    }
    for source in pre_unified.get("properties") or []:
        if not isinstance(source, Mapping):
            continue
        item = dict(source)
        cells = _cell_ids(item)
        allowed = (
            str(item.get("property_id") or "") in allowed_properties
            or bool(cells & allowed_cells)
        )
        if allowed:
            candidates.append(item)
        else:
            rejected.append({
                "source_stage": "stage4_pre_unified",
                "source_id": item.get("property_id"),
                "cell_id": sorted(cells)[0] if cells else None,
                "status": "rejected",
                "reason": "pre_unified_not_allowed_by_audit",
            })
    return candidates, rejected, conditions


def _complete_evidence(
    candidate: Mapping[str, Any],
    family: str,
    sample_label: str,
    tables: Mapping[str, Mapping[str, Any]],
    cells: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any] | None, str]:
    locator = _locator(candidate)
    cell_id = str(locator.get("cell_id") or candidate.get("cell_id") or "")
    cell = cells.get(cell_id)
    if cell is None:
        return None, "table_cell_not_found"
    table_id = str(
        locator.get("table_id") or candidate.get("table_id")
        or cell_id.split(":r", 1)[0]
    )
    table = tables.get(table_id)
    if table is None:
        return None, "table_block_not_found"
    row_label, column_label = _axis_labels(candidate)
    row_label = row_label or sample_label
    column_label = column_label or str(candidate.get("property_name_raw") or family)
    if not row_label or not column_label:
        return None, "table_axis_label_missing"
    cell_text = str(cell.get("text") or "").strip()
    if not cell_text:
        return None, "table_cell_empty"
    return {
        "block_id": table_id,
        "page": int(table.get("page") or 0),
        "bbox": table.get("bbox"),
        "source_type": "table",
        "source_sentence": cell_text,
        "table_locator": {
            "table_id": table_id,
            "cell_id": cell_id,
            "row_index": int(cell.get("row_index", locator.get("row_index", 0))),
            "column_index": int(cell.get("column_index", locator.get("column_index", 0))),
            "row_label": row_label,
            "column_label": column_label,
            "cell_value": cell_text,
        },
    }, "direct_table_cell"


def _condition_context_from_shadow(conditions: Any) -> dict[str, Any]:
    raw = dict(conditions) if isinstance(conditions, Mapping) else {}
    context: dict[str, Any] = {
        "temperature": None,
        "frequency": None,
        "humidity": None,
        "pressure": None,
        "wavelength": None,
        "other_conditions": {},
        "other_condition_evidence": {},
        "other_condition_evidence_ids": {},
        "condition_status": "not_reported",
    }
    known = {
        "temperature_celsius": ("temperature", "°C"),
        "frequency_hz": ("frequency", "Hz"),
        "wavelength_nm": ("wavelength", "nm"),
    }
    for key, value in raw.items():
        if value is None or value == "":
            continue
        if key in known and isinstance(value, (int, float)) and not isinstance(value, bool):
            field, unit = known[key]
            context[field] = {"raw": f"{value} {unit}", "value": float(value), "unit": unit}
        elif isinstance(value, (str, int, float, bool)):
            context["other_conditions"][str(key)] = str(value)
    if any(context[key] is not None for key in (
        "temperature", "frequency", "humidity", "pressure", "wavelength",
    )) or context["other_conditions"]:
        context["condition_status"] = "reported"
    return MeasurementContext.model_validate(context).model_dump(mode="json")


def _condition_context(
    candidate: Mapping[str, Any],
    pre_conditions: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    context = candidate.get("measurement_context")
    if isinstance(context, Mapping):
        try:
            return MeasurementContext.model_validate(context).model_dump(mode="json")
        except Exception:
            pass
    old_id = str(candidate.get("measurement_condition_id") or "")
    source = pre_conditions.get(old_id)
    if source is not None:
        value = {
            key: copy.deepcopy(source.get(key))
            for key in (
                "temperature", "frequency", "humidity", "pressure", "wavelength",
                "other_conditions", "other_condition_evidence",
            )
        }
        value["other_condition_evidence_ids"] = {}
        value["condition_status"] = source.get("condition_status") or "not_reported"
        try:
            return MeasurementContext.model_validate(value).model_dump(mode="json")
        except Exception:
            pass
    return _condition_context_from_shadow(candidate.get("conditions"))


def _new_condition(
    condition_id: str,
    context: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    payload = {
        "condition_id": condition_id,
        "temperature": copy.deepcopy(context.get("temperature")),
        "frequency": copy.deepcopy(context.get("frequency")),
        "humidity": copy.deepcopy(context.get("humidity")),
        "pressure": copy.deepcopy(context.get("pressure")),
        "wavelength": copy.deepcopy(context.get("wavelength")),
        "other_conditions": copy.deepcopy(context.get("other_conditions") or {}),
        "other_condition_evidence": copy.deepcopy(context.get("other_condition_evidence") or {}),
        "condition_status": context.get("condition_status") or "not_reported",
        "evidence": copy.deepcopy(dict(evidence)),
        "confidence": None,
    }
    return MeasurementCondition.model_validate(payload).model_dump(mode="json")


def _existing_numeric(item: Mapping[str, Any]) -> float | None:
    value = item.get("value_min")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    values = numeric_values(item.get("value_raw"))
    return values[0] if len(values) == 1 else None


def _unit_key(value: Any) -> str:
    text = compact(value)
    aliases = {
        "c": "degc", "deg c": "degc", "degree c": "degc",
        "g mol": "g/mol", "dl g": "dl/g", "mn m": "mn/m",
    }
    return aliases.get(text, text)


def _scaled_placeholder_unit_is_repairable(
    current_unit: str,
    expected_unit: str,
    *,
    family: str,
) -> bool:
    """Accept only an empty, exact, or unmistakably truncated unit token.

    A table extractor can reduce ``ohm^-1 cm^-1`` to the final token ``cm``.
    That fragment is not a conductivity unit by itself.  When Stage 4T has
    already validated the complete reciprocal-unit and display-multiplier
    contract for the *same cell*, replacing this fragment is a repair rather
    than a competing interpretation.  Other non-empty unit disagreements
    remain conflicts.
    """

    if current_unit in {"", expected_unit}:
        return True
    return bool(
        family == "electric_conductivity"
        and expected_unit == _unit_key("S/cm")
        and current_unit in {"cm", "ohm", "omega"}
    )


def _equivalent_existing(
    item: Mapping[str, Any],
    *,
    family: str,
    sample_id: str,
    value: float,
    unit: Any,
) -> bool:
    existing_value = _existing_numeric(item)
    return bool(
        canonical_property(item) == family
        and str(item.get("sample_id") or "") == sample_id
        and existing_value is not None
        and number_close(existing_value, value)
        and _unit_key(item.get("unit_normalized") or item.get("unit_raw")) == _unit_key(unit)
    )


def _repair_spaced_thousands_specialized(
    output: dict[str, Any],
) -> list[dict[str, Any]]:
    """Repair directly evidenced molecular weights such as ``19 800``.

    Some table parsers treated the thousands separator as a value separator
    and stored the same scalar as the interval 19--800.  This repair is limited
    to published molecular-weight observations in g/mol whose exact table cell
    equals a conventional grouped-integer surface.
    """

    repairs: list[dict[str, Any]] = []
    pattern = re.compile(r"^\d{1,3}(?:[ \u00a0\u202f]\d{3})+$")
    for item in output.get("specialized_property_observations") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("publication_status") or "") != "published":
            continue
        semantic = compact(
            item.get("semantic_label") or item.get("source_field") or ""
        )
        if semantic not in {"molecular weight", "average molecular weight"}:
            continue
        if _unit_key(item.get("unit_normalized") or item.get("unit_raw")) != "g/mol":
            continue
        raw = str(item.get("value_raw") or "").strip()
        if pattern.fullmatch(raw) is None:
            continue
        cell_ids: list[str] = []
        evidence_matches = False
        for evidence in item.get("evidence") or []:
            if not isinstance(evidence, Mapping):
                continue
            locator = evidence.get("table_locator")
            if not isinstance(locator, Mapping):
                continue
            if str(locator.get("cell_value") or "").strip() == raw:
                evidence_matches = True
                if locator.get("cell_id"):
                    cell_ids.append(str(locator["cell_id"]))
        if not evidence_matches:
            continue
        value = float(re.sub(r"[ \u00a0\u202f]", "", raw))
        old_min = item.get("value_min")
        old_max = item.get("value_max")
        if number_close(old_min, value) and number_close(old_max, value):
            continue
        item["value_kind"] = "numeric_scalar"
        item["value_min"] = value
        item["value_max"] = value
        repairs.append({
            "specialized_id": item.get("specialized_id"),
            "cell_ids": sorted(set(cell_ids)),
            "value_raw": raw,
            "old_value_min": old_min,
            "old_value_max": old_max,
            "new_value": value,
            "basis": "exact_table_cell_grouped_integer",
        })
    return repairs


def _equivalent_specialized(
    item: Mapping[str, Any],
    *,
    family: str,
    sample_id: str,
    value: float,
    unit: Any,
) -> bool:
    if str(item.get("publication_status") or "") != "published":
        return False
    semantic = compact(item.get("semantic_label") or item.get("source_field") or "")
    variant = compact(item.get("variant") or "")
    if semantic in {"molecular weight", "average molecular weight"}:
        specialized_family = {
            "number average": "mn",
            "weight average": "mw",
        }.get(variant, "molar_mass")
    else:
        specialized_family = semantic.replace(" ", "_")
    return bool(
        specialized_family == family
        and str(item.get("sample_id") or "") == sample_id
        and _existing_numeric(item) is not None
        and number_close(_existing_numeric(item), value)
        and _unit_key(item.get("unit_normalized") or item.get("unit_raw"))
        == _unit_key(unit)
    )


def recover_stage4_document(
    stage0: Stage0Document | Mapping[str, Any],
    stage2: Mapping[str, Any],
    stage3: Mapping[str, Any],
    stage4: Stage4Document | Mapping[str, Any],
    shadow: Mapping[str, Any] | None,
    unified_audit: Mapping[str, Any] | None,
    pre_unified: Mapping[str, Any] | None = None,
) -> tuple[Stage4Document, dict[str, Any]]:
    """Return a schema-valid recovered Stage 4 document and decision audit."""

    stage0_model = (
        stage0 if isinstance(stage0, Stage0Document)
        else Stage0Document.model_validate(stage0)
    )
    stage4_model = (
        stage4 if isinstance(stage4, Stage4Document)
        else Stage4Document.model_validate(stage4)
    )
    stage2_payload = _payload(stage2)
    stage3_payload = _payload(stage3)
    shadow_payload = _payload(shadow or {})
    audit_payload = _payload(unified_audit or {})
    pre_payload = _payload(pre_unified or {})

    if stage0_model.document_id != stage4_model.document_id:
        raise Stage4PError("Stage 0 and Stage 4 document_id mismatch")
    if stage2_payload.get("document_id") not in {None, stage0_model.document_id}:
        raise Stage4PError("Stage 2 document_id mismatch")
    if stage3_payload.get("document_id") not in {None, stage0_model.document_id}:
        raise Stage4PError("Stage 3 document_id mismatch")
    for label, payload in (("shadow", shadow_payload), ("audit", audit_payload), ("pre_unified", pre_payload)):
        if payload.get("document_id") not in {None, stage0_model.document_id}:
            raise Stage4PError(f"{label} document_id mismatch")

    output = stage4_model.model_dump(mode="json")
    specialized_repairs = _repair_spaced_thousands_specialized(output)
    tables, cells = _table_index(stage0_model)
    sample_by_id, samples_by_label, aliases_by_sample = _sample_indexes(
        stage2_payload, stage3_payload,
    )
    series_locator_repairs, series_locator_rejections, repaired_coordinate_occurrences = (
        _repair_property_series_scalar_locators(
            output,
            tables=tables,
            cells=cells,
            stage2=stage2_payload,
            sample_by_id=sample_by_id,
        )
    )
    audit_by_candidate = _audit_outcomes_by_candidate(audit_payload)
    pre_candidates, pre_rejections, pre_conditions = _pre_unified_candidates(
        pre_payload, audit_payload,
    )
    outcomes: list[dict[str, Any]] = [
        *series_locator_repairs,
        *series_locator_rejections,
        *pre_rejections,
    ]

    candidates: list[tuple[str, dict[str, Any]]] = [
        ("stage4t_shadow", item) for item in _shadow_candidates(shadow_payload)
    ] + [
        ("stage4_pre_unified", item) for item in pre_candidates
    ]
    next_property = _next_id(output.get("properties") or [], "property_id", _PROPERTY_ID_RE)
    next_condition = _next_id(
        output.get("measurement_conditions") or [], "condition_id", _CONDITION_ID_RE,
    )

    existing_by_cell: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in output.get("properties") or []:
        for cell_id in _cell_ids(item):
            existing_by_cell[cell_id].append(item)
    specialized_by_cell: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in output.get("specialized_property_observations") or []:
        if not isinstance(item, dict):
            continue
        for cell_id in _cell_ids(item):
            specialized_by_cell[cell_id].append(item)

    for source_stage, candidate in candidates:
        source_id = str(
            candidate.get("observation_id") or candidate.get("property_id") or ""
        )
        locator = _locator(candidate)
        cell_id = str(locator.get("cell_id") or candidate.get("cell_id") or "")
        base_outcome = {
            "source_stage": source_stage,
            "source_id": source_id or None,
            "cell_id": cell_id or None,
        }

        related_audit = [
            *audit_by_candidate.get(source_id, []),
            *audit_by_candidate.get(cell_id, []),
        ]
        if any(str(row.get("status") or "") in _FATAL_AUDIT_STATUSES for row in related_audit):
            outcomes.append({
                **base_outcome, "status": "rejected", "reason": "upstream_source_conflict",
            })
            continue

        if source_stage == "stage4t_shadow":
            candidate_class = str(candidate.get("candidate_class") or "")
            if candidate_class not in {"official_property", "material_characteristic"}:
                outcomes.append({
                    **base_outcome, "status": "rejected", "reason": "candidate_class_not_publishable",
                })
                continue
            gate = candidate.get("publication_gate")
            blockers = set(gate.get("blockers") or []) if isinstance(gate, Mapping) else set()
            fatal_blockers = sorted(blockers - _PERMITTED_SHADOW_BLOCKERS)
            if fatal_blockers:
                outcomes.append({
                    **base_outcome,
                    "status": "rejected",
                    "reason": "upstream_publication_blocker",
                    "blockers": fatal_blockers,
                })
                continue

        cell = cells.get(cell_id)
        if cell is None:
            outcomes.append({
                **base_outcome, "status": "rejected", "reason": "table_cell_not_found",
            })
            continue
        header = _property_axis_header(candidate)
        quantity = decide_quantity(
            candidate,
            cell_text=str(cell.get("text") or ""),
            header=header,
        )
        if not quantity.accepted or quantity.value_min is None:
            outcomes.append({
                **base_outcome,
                "status": "rejected",
                "reason": quantity.reason,
                "property_name": quantity.property_name or None,
            })
            continue

        resolution = _resolve_sample(
            candidate,
            quantity.property_name,
            sample_by_id,
            samples_by_label,
            aliases_by_sample,
            tables,
        )
        if resolution["status"] != "matched":
            outcomes.append({
                **base_outcome,
                "status": "rejected",
                "reason": resolution["reason"],
                "sample_resolution_status": resolution["status"],
                "sample_label": resolution.get("label"),
                "sample_matches": resolution.get("matches") or [],
                "sample_resolution_basis": resolution.get("reason"),
            })
            continue
        sample_id = str(resolution["sample_id"])

        # A lettered blank row is evidence for a distinct table entry, not an
        # exact identity assertion about the preceding parent sample.  Keep the
        # numeric candidate for all-stage recall, but do not publish an inferred
        # parent binding as if it were a verified sample relation.
        if resolution.get("reason") == "table_blank_continuation_parent_exact_alias":
            outcomes.append({
                **base_outcome,
                "status": "rejected",
                "reason": "continuation_sample_binding_not_exact",
                "sample_resolution_status": "inferred_parent_only",
                "sample_label": resolution.get("label"),
                "sample_matches": resolution.get("matches") or [],
                "sample_resolution_basis": resolution.get("reason"),
            })
            continue

        process_binding = _paired_shift_process_binding(
            candidate,
            sample_id,
            tables,
            stage3_payload,
        )
        if not process_binding["accepted"]:
            outcomes.append({
                **base_outcome,
                "status": "rejected",
                "reason": process_binding["reason"],
                "sample_resolution_status": "process_unverified",
                "sample_label": resolution.get("label"),
                "sample_matches": resolution.get("matches") or [],
                "sample_resolution_basis": resolution.get("reason"),
                "row_methods": process_binding.get("row_methods") or [],
                "sample_process_methods": (
                    process_binding.get("sample_process_methods") or []
                ),
            })
            continue

        evidence, evidence_reason = _complete_evidence(
            candidate,
            quantity.property_name,
            str(resolution.get("label") or sample_by_id[sample_id].get("sample_label_raw") or sample_id),
            tables,
            cells,
        )
        if evidence is None:
            outcomes.append({
                **base_outcome, "status": "rejected", "reason": evidence_reason,
            })
            continue

        equivalent_specialized = next((
            item for item in specialized_by_cell.get(cell_id, [])
            if _equivalent_specialized(
                item,
                family=quantity.property_name,
                sample_id=sample_id,
                value=quantity.value_min,
                unit=quantity.unit_normalized,
            )
        ), None)
        if equivalent_specialized is not None:
            outcomes.append({
                **base_outcome,
                "status": "duplicate_existing_specialized",
                "reason": "same_cell_same_specialized_fact",
                "specialized_id": equivalent_specialized.get("specialized_id"),
                "sample_id": sample_id,
                "sample_resolution_basis": resolution.get("reason"),
                "process_binding_basis": process_binding.get("basis"),
            })
            continue

        same_cell = existing_by_cell.get(cell_id, [])
        equivalent = next((
            item for item in same_cell
            if _equivalent_existing(
                item,
                family=quantity.property_name,
                sample_id=sample_id,
                value=quantity.value_min,
                unit=quantity.unit_normalized,
            )
        ), None)
        if equivalent is not None:
            if cell_id not in _cell_ids(equivalent):
                equivalent.setdefault("evidence", []).append(evidence)
            outcomes.append({
                **base_outcome,
                "status": "duplicate_existing",
                "reason": "same_cell_same_fact",
                "property_id": equivalent.get("property_id"),
                "sample_id": sample_id,
                "sample_resolution_basis": resolution.get("reason"),
                "process_binding_basis": process_binding.get("basis"),
            })
            continue
        # Stage 4 may already contain a schema-valid table placeholder whose
        # numeric value is still the displayed cell value.  A narrow example
        # is ``sigma (10^12 ohm^-1 cm^-1)``: Stage 4T carries a fully validated
        # inverse display multiplier, while the older Stage 4 object retains
        # ``4.76`` instead of the physical ``4.76e-12 S/cm``.  Treating that
        # compatible placeholder as a semantic conflict prevents P2 from
        # completing an otherwise direct, evidenced extraction.
        #
        # Repair is deliberately limited to the already validated scaled-
        # scalar branch, the same cell/family/sample, and a displayed value
        # that agrees with the source cell.  A different property, sample,
        # unit, or more than one possible placeholder remains a conflict.
        if quantity.reason == "accepted_direct_scaled_scalar" and same_cell:
            cell_values = numeric_values(cell.get("text"))
            display_value = cell_values[0] if len(cell_values) == 1 else None
            expected_unit = _unit_key(quantity.unit_normalized)
            repairable = []
            for item in same_cell:
                current_value = _existing_numeric(item)
                current_unit = _unit_key(
                    item.get("unit_normalized") or item.get("unit_raw")
                )
                if (
                    canonical_property(item) == quantity.property_name
                    and str(item.get("sample_id") or "") == sample_id
                    and display_value is not None
                    and current_value is not None
                    and number_close(current_value, display_value)
                    and _scaled_placeholder_unit_is_repairable(
                        current_unit,
                        expected_unit,
                        family=quantity.property_name,
                    )
                ):
                    repairable.append(item)
            if len(repairable) == 1:
                repaired = repairable[0]
                repaired["value_min"] = quantity.value_min
                repaired["value_max"] = quantity.value_max
                repaired["unit_raw"] = quantity.unit_raw
                repaired["unit_normalized"] = quantity.unit_normalized
                repaired["property_name_normalized"] = quantity.property_name
                if cell_id not in _cell_ids(repaired):
                    repaired.setdefault("evidence", []).append(evidence)
                outcomes.append({
                    **base_outcome,
                    "status": "published",
                    "reason": "same_cell_display_value_scaled",
                    "property_id": repaired.get("property_id"),
                    "property_name": quantity.property_name,
                    "value_min": quantity.value_min,
                    "unit": quantity.unit_normalized,
                    "sample_id": sample_id,
                    "sample_label": resolution.get("label"),
                    "sample_resolution_basis": resolution.get("reason"),
                    "process_binding_basis": process_binding.get("basis"),
                    "repaired_existing": True,
                })
                continue
        if same_cell:
            outcomes.append({
                **base_outcome,
                "status": "rejected",
                "reason": "current_stage4_cell_conflict",
                "conflicting_property_ids": [item.get("property_id") for item in same_cell],
            })
            continue

        equivalent_elsewhere = next((
            item for item in output.get("properties") or []
            if _equivalent_existing(
                item,
                family=quantity.property_name,
                sample_id=sample_id,
                value=quantity.value_min,
                unit=quantity.unit_normalized,
            )
        ), None)
        if equivalent_elsewhere is not None:
            equivalent_elsewhere.setdefault("evidence", []).append(evidence)
            existing_by_cell[cell_id].append(equivalent_elsewhere)
            outcomes.append({
                **base_outcome,
                "status": "evidence_merged",
                "reason": "same_sample_property_value_unit",
                "property_id": equivalent_elsewhere.get("property_id"),
                "sample_id": sample_id,
                "sample_resolution_basis": resolution.get("reason"),
                "process_binding_basis": process_binding.get("basis"),
            })
            continue

        context = _condition_context(candidate, pre_conditions)
        condition_id = f"mc{next_condition:03d}"
        property_id = f"prop{next_property:03d}"
        next_condition += 1
        next_property += 1
        condition = _new_condition(condition_id, context, evidence)
        raw_name = str(candidate.get("property_name_raw") or quantity.property_name).strip()
        property_payload = {
            "property_id": property_id,
            "sample_id": sample_id,
            "property_name_raw": raw_name,
            "property_name_normalized": quantity.property_name,
            "property_code": None,
            "property_category": None,
            "molecular_weight_type": quantity.molecular_weight_type,
            "determination_method_raw": (
                str(candidate.get("determination_method_raw")).strip()
                if candidate.get("determination_method_raw") else None
            ),
            "observation_group_id": None,
            "observation_role": "single",
            "series_id": None,
            "series_ids": None,
            "value_raw": str(cell.get("text") or "").strip(),
            "value_min": quantity.value_min,
            "value_max": quantity.value_max,
            "unit_raw": quantity.unit_raw,
            "unit_normalized": quantity.unit_normalized,
            "measurement_condition_id": condition_id,
            "measurement_context": context,
            "source_type": "table",
            "evidence": [evidence],
            "confidence": None,
        }
        property_item = PropertyObservation.model_validate(property_payload).model_dump(mode="json")
        output.setdefault("measurement_conditions", []).append(condition)
        output.setdefault("properties", []).append(property_item)
        existing_by_cell[cell_id].append(property_item)
        outcomes.append({
            **base_outcome,
            "status": "published",
            "reason": "direct_table_scalar_with_exact_stage3_sample",
            "property_id": property_id,
            "condition_id": condition_id,
            "property_name": quantity.property_name,
            "value_min": quantity.value_min,
            "unit": quantity.unit_normalized,
            "sample_id": sample_id,
            "sample_label": resolution.get("label"),
            "sample_resolution_basis": resolution.get("reason"),
            "process_binding_basis": process_binding.get("basis"),
            "axis_orientation_repaired": bool(resolution.get("axis_repaired")),
        })

    # The entire document is the publication boundary.  No partially valid
    # object is returned if any generated reference or schema field is wrong.
    merged = Stage4Document.model_validate(output)
    status_counts = Counter(str(row.get("status") or "unknown") for row in outcomes)
    reason_counts = Counter(str(row.get("reason") or "unknown") for row in outcomes)
    audit = {
        "schema_version": "stage4p_publication_audit.v1",
        "stage": STAGE_ID,
        "implementation_version": IMPLEMENTATION_VERSION,
        "policy_version": POLICY_VERSION,
        "document_id": merged.document_id,
        "authoritative": False,
        "gold_visible_at_runtime": False,
        "sources": [
            "existing_stage4_property_series",
            "stage4t_shadow.json",
            "audit_allowed_stage4_properties.pre_unified.json",
        ],
        "summary": {
            # Includes pre-unified objects rejected before the publication
            # loop because the upstream audit did not explicitly allow them.
            "candidate_count": len(outcomes),
            "published_count": status_counts["published"],
            "evidence_merged_count": status_counts["evidence_merged"],
            "duplicate_existing_count": status_counts["duplicate_existing"],
            "duplicate_existing_specialized_count": status_counts[
                "duplicate_existing_specialized"
            ],
            "specialized_spaced_thousands_repaired_count": len(
                specialized_repairs
            ),
            "property_series_locator_repaired_count": len(
                series_locator_repairs
            ),
            "property_series_coordinate_occurrence_repaired_count": (
                repaired_coordinate_occurrences
            ),
            "property_series_locator_rejected_count": len(
                series_locator_rejections
            ),
            "rejected_count": status_counts["rejected"],
            "status_counts": dict(sorted(status_counts.items())),
            "reason_counts": dict(sorted(reason_counts.items())),
        },
        "specialized_repairs": specialized_repairs,
        "property_series_locator_repairs": series_locator_repairs,
        "property_series_locator_rejections": series_locator_rejections,
        "candidate_outcomes": outcomes,
    }
    return merged, audit


def _select_base_stage4(
    source_stage4: Path,
    destination_stage4: Path,
    backup_path: Path,
    audit_path: Path,
) -> Path:
    """Reuse the backup only when destination is the prior audited output."""

    if destination_stage4.is_file() and backup_path.is_file() and audit_path.is_file():
        try:
            previous = _read_json(audit_path)
            previous_output = str(previous.get("output_sha256") or "")
            previous_base = str((previous.get("input_hashes") or {}).get("base_stage4") or "")
            if (
                previous_output
                and _sha256(destination_stage4) == previous_output
                and previous_base
                and _sha256(backup_path) == previous_base
            ):
                return backup_path
        except (OSError, Stage4PError):
            pass
    return source_stage4


def run_stage4p(
    ref_no: str,
    *,
    input_root: Path,
    output_root: Path,
    apply: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    source = input_root / ref_no
    target = output_root / ref_no
    target.mkdir(parents=True, exist_ok=True)
    output_path = target / OUTPUT_NAME
    audit_path = target / AUDIT_NAME
    destination_stage4 = target / "stage4_properties.json"
    backup_path = target / BACKUP_NAME
    source_stage4 = source / "stage4_properties.json"
    base_stage4 = _select_base_stage4(
        source_stage4, destination_stage4, backup_path, audit_path,
    )
    paths = {
        "stage0": source / "stage0_blocks.json",
        "stage2": source / "stage2_entities.json",
        "stage3": source / "stage3_process.json",
        "base_stage4": base_stage4,
        "stage4t_shadow": source / "stage4t_shadow.json",
        "stage4r_unified_audit": source / "stage4r_unified_audit.json",
        "stage4_pre_unified": source / "stage4_properties.pre_unified.json",
    }
    for key in ("stage0", "stage2", "stage3", "base_stage4"):
        if not paths[key].is_file():
            raise Stage4PError(f"Missing required {key}: {paths[key]}")
    input_hashes = {key: _optional_hash(path) for key, path in paths.items()}
    policy_hash = hashlib.sha256(
        Path(__file__).with_name("property_publication_policy.py").read_bytes()
    ).hexdigest()

    if output_path.is_file() and audit_path.is_file() and not force:
        cached = _read_json(audit_path)
        if (
            cached.get("implementation_version") == IMPLEMENTATION_VERSION
            and cached.get("policy_version") == POLICY_VERSION
            and cached.get("policy_sha256") == policy_hash
            and cached.get("input_hashes") == input_hashes
            and cached.get("output_sha256") == _sha256(output_path)
        ):
            if apply and (
                not destination_stage4.is_file()
                or _sha256(destination_stage4) != _sha256(output_path)
            ):
                backup_record = _sync_pre_p2_backup(base_stage4, backup_path)
                cached["pre_p2_backup"] = backup_record
                cached["applied"] = True
                _write_json(audit_path, cached)
                _copy_atomic(output_path, destination_stage4)
            return {
                "status": "cached",
                "preview_path": output_path,
                "audit_path": audit_path,
                "applied": apply,
                "summary": cached.get("summary") or {},
            }

    stage0 = _read_json(paths["stage0"])
    stage2 = _read_json(paths["stage2"])
    stage3 = _read_json(paths["stage3"])
    stage4 = _read_json(paths["base_stage4"])
    shadow = _read_json(paths["stage4t_shadow"], required=False)
    unified_audit = _read_json(paths["stage4r_unified_audit"], required=False)
    pre_unified = _read_json(paths["stage4_pre_unified"], required=False)
    merged, audit = recover_stage4_document(
        stage0, stage2, stage3, stage4, shadow, unified_audit, pre_unified,
    )
    _write_json(output_path, merged.model_dump(mode="json"))
    audit.update({
        "input_paths": {key: str(path) for key, path in paths.items()},
        "input_hashes": input_hashes,
        "policy_sha256": policy_hash,
        "output_sha256": _sha256(output_path),
        "applied": bool(apply),
    })
    if apply:
        audit["pre_p2_backup"] = _sync_pre_p2_backup(base_stage4, backup_path)
        if audit["pre_p2_backup"]["sha256"] != input_hashes["base_stage4"]:
            raise Stage4PError(
                "Pre-P2 backup hash differs from the audited Stage 4 input"
            )
    _write_json(audit_path, audit)
    if apply:
        _copy_atomic(output_path, destination_stage4)
    return {
        "status": "executed",
        "preview_path": output_path,
        "audit_path": audit_path,
        "applied": apply,
        "summary": audit["summary"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref-no", required=True)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--config", type=Path, help="Batch-runner compatibility; unused")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ref_no = args.ref_no if args.ref_no.startswith("reference_no_") else f"reference_no_{args.ref_no}"
    input_root = args.input_root.expanduser().resolve()
    output_root = (args.output_root or input_root).expanduser().resolve()
    result = run_stage4p(
        ref_no,
        input_root=input_root,
        output_root=output_root,
        apply=bool(args.apply),
        force=bool(args.force),
    )
    print(json.dumps({
        "reference_no": ref_no,
        "status": result["status"],
        "applied": result["applied"],
        "summary": result["summary"],
        "preview_path": str(result["preview_path"]),
        "audit_path": str(result["audit_path"]),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Stage 4P failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
