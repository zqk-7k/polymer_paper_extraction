"""Preview-only Stage 4R：合并正文 Stage 4N 与表格 Stage 4T 候选。

已绑定的正式性质写入 `properties`；未绑定或未映射候选保留在现有
`specialized_property_observations`/审计通道中，不阻断后续 Stage 5/6。
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
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping, Sequence

EXTRACTION_ROOT = Path(__file__).resolve().parents[1]
if str(EXTRACTION_ROOT) not in sys.path:
    sys.path.insert(0, str(EXTRACTION_ROOT))

from schema.polymer_schema import Stage0Document, Stage4Document, FinalSpecializedPropertyObservation
from stages.source_context_semantics import literal_value_supported, table_evidence_context
from stages.numeric_value_semantics import derive_numeric_value
from stages.table_value_inventory import composite_candidates
from stages.sample_catalog import family_members, normalize_label
from stages.final_unit_conversion import parse_numeric
from stages.specialized_vocabulary import (
    LabelResolution,
    SpecializedVocabulary,
    get_specialized_vocabulary,
)


STAGE_ID = "stage4r_unified_preview"
IMPLEMENTATION_VERSION = "0.2.0"
OUTPUT_NAME = "stage4_properties.unified_preview.json"
AUDIT_NAME = "stage4r_unified_audit.json"
CANDIDATE_CONTRACT_VERSION = "stage4r_candidate_input.v0.1"
_PROPERTY_ID_RE = re.compile(r"^prop(\d+)$")
_CONDITION_ID_RE = re.compile(r"^mc(\d+)$")
# 方案 §8：official 与 specialized 的唯一交集。精确匹配，不做前缀/模糊。
_REROUTED_OFFICIAL_PROPERTY = "intrinsic_viscosity"


def _norm(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").casefold())


_SAMPLE_INDEX_LABEL_RE = re.compile(
    r"^(?P<prefix>.+?)[\s_\-‐‑‒–—]+(?P<number>\d+)$"
)
_SAMPLE_RANGE_RE = re.compile(
    r"(?P<prefix>[A-Za-z\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff]*)"
    r"[\s_\-‐‑‒–—]*(?P<start>\d+)\s*"
    r"(?:to|至|[-‐‑‒–—])\s*"
    r"(?:[A-Za-z\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff]*"
    r"[\s_\-‐‑‒–—]*)?"
    r"(?P<end>\d+)",
    re.IGNORECASE,
)
_SAMPLE_NUMBER_RE = re.compile(r"^\s*(?P<number>\d+)\s*$")


def _sample_label_aliases(value: Any) -> set[str]:
    """Family members are separate samples, never aliases of a group."""

    raw = str(value or "").strip()
    if not raw:
        return set()
    return {raw}


def _sample_label_parts(value: Any) -> tuple[str, int] | None:
    match = _SAMPLE_INDEX_LABEL_RE.fullmatch(str(value or "").strip())
    if not match:
        return None
    return _norm(match.group("prefix")), int(match.group("number"))


def _context_text(candidate: Mapping[str, Any]) -> str:
    values = [
        candidate.get("table_caption"),
        candidate.get("table_context_text"),
        candidate.get("property_name_raw"),
    ]
    locator = candidate.get("evidence_locator")
    if isinstance(locator, Mapping):
        values.extend(locator.get("header_path") or [])
        values.append(locator.get("column_label"))
    return " | ".join(str(value) for value in values if value)


def _sample_context_score(
    candidate: Mapping[str, Any],
    sample: Mapping[str, Any],
) -> tuple[int, list[str]]:
    """只利用可追溯的文本锚点，不依靠外部知识猜测样品。"""

    context = _norm(_context_text(candidate))
    if not context:
        return 0, []
    score = 0
    anchors: list[str] = []
    label = sample.get("sample_label_raw")
    if label and len(_norm(label)) >= 3 and _norm(label) in context:
        score += 30
        anchors.append("context_sample_label")
    polymer_name = str(sample.get("polymer_name") or "").strip()
    normalized_polymer = _norm(polymer_name)
    if len(normalized_polymer) >= 6 and normalized_polymer in context:
        score += 20
        anchors.append("context_polymer_name")
    source_block_ids = set(str(value) for value in candidate.get(
        "context_source_block_ids", []
    ) if value)
    evidence = sample.get("evidence")
    if isinstance(evidence, Mapping) and str(evidence.get("block_id") or "") in source_block_ids:
        score += 10
        anchors.append("shared_evidence_block")
    return score, anchors


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        return None


def _next_number(
    items: Sequence[Mapping[str, Any]],
    key: str,
    pattern: re.Pattern[str],
) -> int:
    numbers = []
    for item in items:
        match = pattern.fullmatch(str(item.get(key) or ""))
        if match:
            numbers.append(int(match.group(1)))
    return max(numbers, default=0) + 1


def _cell_ids(item: Mapping[str, Any]) -> set[str]:
    result: set[str] = set()
    for evidence in item.get("evidence") or []:
        locator = evidence.get("table_locator") if isinstance(evidence, Mapping) else None
        if isinstance(locator, Mapping) and locator.get("cell_id"):
            result.add(str(locator["cell_id"]))
    return result


def _semantic(item: Mapping[str, Any]) -> str:
    return _norm(
        item.get("property_name_normalized")
        or item.get("semantic_label")
        or item.get("property_name_raw")
    )


def _candidate_semantic(candidate: Mapping[str, Any]) -> str:
    return _norm(
        candidate.get("property_name_normalized")
        or candidate.get("semantic_label")
        or candidate.get("property_name_raw")
    )


def _flatten_candidates(sidecar: Mapping[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for table in sidecar.get("tables") or []:
        if not isinstance(table, Mapping):
            continue
        table_context_payload = table.get("context")
        table_context_payload = (
            table_context_payload
            if isinstance(table_context_payload, Mapping)
            else {}
        )
        table_context = {
            "table_caption": table.get("caption"),
            "table_direction": table.get("direction"),
            "table_sample_axis": table.get("sample_axis"),
            "table_sample_series": table.get("sample_series"),
            "table_axis_role": table.get("axis_role"),
            "table_header_rows": table.get("header_rows"),
            "context_source_block_ids": list(
                table_context_payload.get("source_block_ids") or []
            ),
            "table_context_text": " | ".join(
                str(item.get("text") or "")
                for section in ("preceding_text", "following_text", "footnotes")
                for item in table_context_payload.get(section) or []
                if isinstance(item, Mapping) and item.get("text")
            ),
        }
        for item in table.get("observations") or []:
            if not isinstance(item, Mapping):
                continue
            candidate = dict(item)
            # 表级上下文只作为延迟绑定和审计信息，不参与标题模糊匹配。
            for key, value in table_context.items():
                if value is not None:
                    candidate.setdefault(key, value)
            candidates.append(candidate)
    return candidates


def _candidate_contract_error(candidate: Mapping[str, Any]) -> str | None:
    required = ("observation_id", "table_id", "cell_id", "value_raw")
    missing = [key for key in required if not str(candidate.get(key) or "").strip()]
    if missing:
        return "missing_required_fields:" + ",".join(missing)
    return None


def _sample_index(
    stage2: Mapping[str, Any],
    stage3: Mapping[str, Any],
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    samples = [
        dict(item)
        for item in stage3.get("samples") or []
        if isinstance(item, Mapping) and item.get("sample_id")
    ]
    aliases_by_entity: dict[str, set[str]] = defaultdict(set)
    for entity in stage2.get("polymer_entities") or []:
        if not isinstance(entity, Mapping) or not entity.get("entity_id"):
            continue
        entity_id = str(entity["entity_id"])
        for key in ("polymer_name", "canonical_name", "normalized_name", "display_name"):
            if entity.get(key):
                aliases_by_entity[entity_id].add(str(entity[key]))
        aliases_by_entity[entity_id].update(
            str(value) for value in entity.get("source_names") or [] if value
        )

    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        if family_members(str(sample.get("sample_label_raw") or sample.get("polymer_name") or "")) or sample.get("sample_level") == "sample_family":
            continue
        labels = {sample.get("sample_label_raw"), sample.get("polymer_name")}
        labels.update(sample.get("sample_label_aliases") or [])
        # Entity 的 source_names 是文档级别别名，不能扩散到已经有自身
        # 标签/聚合物名的多个样品，否则会把同实体的无标签样品伪造成
        # ``PI-1`` 等逐项样品并制造歧义。仅对完全无名称的样品使用兜底。
        if not any(str(label or "").strip() for label in labels):
            labels.update(aliases_by_entity.get(str(sample.get("refers_to_entity") or ""), set()))
        for label in labels:
            for alias in _sample_label_aliases(label):
                normalized = normalize_label(alias)
                if normalized and sample not in index[normalized]:
                    index[normalized].append(sample)
    return index, samples


def _resolve_sample_legacy(
    candidate: Mapping[str, Any],
    sample_index: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    label_sources: list[tuple[str, str]] = []
    for key, basis in (
        ("sample_label_raw", "sample_or_entity_alias"),
        ("row_label", "explicit_row_label"),
        ("column_header", "explicit_column_header"),
    ):
        value = candidate.get(key)
        if value:
            label_sources.append((str(value).strip(), basis))
    locator = candidate.get("evidence_locator")
    if isinstance(locator, Mapping) and locator.get("row_label"):
        label_sources.append((str(locator["row_label"]).strip(), "evidence_row_label"))
    explicit = candidate.get("sample_label_candidates")
    if isinstance(explicit, Sequence) and not isinstance(explicit, (str, bytes)):
        label_sources.extend(
            (str(value).strip(), "explicit_candidate_label")
            for value in explicit
            if value
        )

    seen: set[tuple[str, str]] = set()
    ambiguous_matches: list[Mapping[str, Any]] = []
    matched_labels: dict[str, tuple[str, str]] = {}
    for label, basis in label_sources:
        key = (normalize_label(label), basis)
        if not key[0] or key in seen:
            continue
        seen.add(key)
        matches = list(sample_index.get(key[0], ()))
        ambiguous_matches.extend(matches)
        for sample in matches:
            matched_labels[str(sample["sample_id"])] = (label, basis)

    unique_direct = {str(s["sample_id"]): s for s in ambiguous_matches}
    if len(unique_direct) == 1:
        sid, sample = next(iter(unique_direct.items()))
        label, basis = matched_labels[sid]
        return {"status": "matched", "label": label, "sample_id": sid,
                "entity_id": sample.get("refers_to_entity"), "basis": f"normalized_{basis}",
                "matches": [sid], "confidence": 1.0, "anchors": [basis]}
    if len(unique_direct) > 1:
        return {"status": "ambiguous_sample", "label": label_sources[0][0],
                "matches": sorted(unique_direct), "confidence": 0.0, "anchors": ["multiple_sample_candidates"]}

    # 数字行标签只有在表格明确提供了样品系列锚点时才展开，例如
    # “PC-1–PC-6” + 行标签 “1”。单独的数字不会触发该规则。
    number_match = _SAMPLE_NUMBER_RE.fullmatch(
        str(candidate.get("sample_label_raw") or candidate.get("row_label") or "")
    )
    if number_match and candidate.get("table_sample_axis") in {"row", "column"}:
        number = int(number_match.group("number"))
        # 数字标签只有在表题或 Stage4T 明确提供的表级系列字段中出现系列
        # 前缀时才可映射；邻近正文可能同时描述多张表，不能作为唯一依据。
        context = " | ".join(
            str(value)
            for value in (
                candidate.get("table_caption"),
                candidate.get("table_sample_series"),
            )
            if value
        )
        prefix_candidates: set[str] = set()
        for match in re.finditer(
            r"(?P<prefix>[A-Za-z][A-Za-z0-9]*)\s*[-‐‑‒–—]\s*(?P<number>\d+)",
            context,
        ):
            if int(match.group("number")) == number:
                prefix_candidates.add(match.group("prefix"))
        series_matches: list[Mapping[str, Any]] = []
        for prefix in prefix_candidates:
            series_matches.extend(sample_index.get(normalize_label(f"{prefix}-{number}"), ()))
        unique_series_matches = list({
            str(item.get("sample_id")): item for item in series_matches
        }.values())
        if len(unique_series_matches) == 1:
            sample = unique_series_matches[0]
            return {
                "status": "matched",
                "label": str(number),
                "sample_id": sample["sample_id"],
                "entity_id": sample.get("refers_to_entity"),
                "basis": "table_sample_series_index",
                "matches": [sample["sample_id"]],
                "confidence": 0.9,
                "anchors": ["numeric_row_label", "sample_series_context"],
            }
        if len(unique_series_matches) > 1:
            ambiguous_matches.extend(unique_series_matches)

    # 复杂表没有显式样品标签时，只有上下文中唯一出现一个已知样品名才绑定。
    context_matches: list[tuple[int, Mapping[str, Any], list[str]]] = []
    # 数字轴的上下文经常是 ``PC-1–PC-6`` 这类范围；在没有表级系列字段
    # 时，不能把范围中的第一个标签误当成当前行对应样品。
    axis_role = str(
        candidate.get("table_axis_role")
        or (locator.get("axis_role") if isinstance(locator, Mapping) else "")
        or ""
    ).casefold()
    allow_context_sample_anchor = not (
        number_match and candidate.get("table_sample_axis") in {"row", "column"}
    ) and not (
        candidate.get("table_sample_axis") == "implicit"
        or axis_role in {"condition", "condition_series"}
    ) and not ambiguous_matches and not label_sources
    if allow_context_sample_anchor:
        for sample_list in sample_index.values():
            for sample in sample_list:
                score, anchors = _sample_context_score(candidate, sample)
                if score:
                    context_matches.append((score, sample, anchors))
    best_score = max((item[0] for item in context_matches), default=0)
    best = [item for item in context_matches if item[0] == best_score]
    best_by_id = {str(item[1].get("sample_id")): item for item in best}
    if best_score >= 30 and len(best_by_id) == 1:
        score, sample, anchors = next(iter(best_by_id.values()))
        return {
            "status": "matched",
            "label": sample.get("sample_label_raw") or sample.get("polymer_name"),
            "sample_id": sample["sample_id"],
            "entity_id": sample.get("refers_to_entity"),
            "basis": "shared_context_anchor",
            "matches": [sample["sample_id"]],
            "confidence": min(0.85, 0.5 + score / 100),
            "anchors": anchors,
        }

    if ambiguous_matches:
        unique_matches = {
            str(item.get("sample_id")): item for item in ambiguous_matches
        }
        return {
            "status": "ambiguous_sample",
            "label": label_sources[0][0] if label_sources else None,
            "matches": sorted(unique_matches),
            "confidence": 0.0,
            "anchors": ["multiple_sample_candidates"],
        }
    return {
        "status": "unmatched_sample",
        "label": label_sources[0][0] if label_sources else None,
        "matches": [],
        "confidence": 0.0,
        "anchors": [],
    }


def resolve_sample(candidate, sample_index, subject_catalog=None):
    from stages.stage4t_subject_context import resolve_subject, state_conflict
    samples = {s['sample_id']: s for group in sample_index.values() for s in group}
    catalog = subject_catalog or {'samples': list(samples.values()), 'entities': []}
    scoped = resolve_subject(candidate, catalog)
    if scoped is not None:
        return scoped
    result = _resolve_sample_legacy(candidate, sample_index)
    if result.get('status') == 'matched' and state_conflict(candidate, samples.get(result['sample_id'], {})):
        return {'status': 'unmatched_sample', 'label': result.get('label'), 'matches': [],
                'confidence': 0.0, 'anchors': ['sample_state_conflict'], 'entity_id': result.get('entity_id')}
    return result


def _sample_binding_context(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """保留未绑定候选的最小上下文，供后续样品解析重试。"""
    locator = candidate.get("evidence_locator")
    locator = locator if isinstance(locator, Mapping) else {}
    labels = []
    for value in (
        candidate.get("sample_label_raw"),
        candidate.get("row_label"),
        candidate.get("column_header"),
        locator.get("row_label"),
    ):
        if value and str(value).strip() not in labels:
            labels.append(str(value).strip())
    explicit = candidate.get("sample_label_candidates")
    if isinstance(explicit, Sequence) and not isinstance(explicit, (str, bytes)):
        labels.extend(
            str(value).strip()
            for value in explicit
            if value and str(value).strip() not in labels
        )
    return {
        "table_id": candidate.get("table_id"),
        "caption": candidate.get("table_caption"),
        "direction": candidate.get("table_direction") or locator.get("axis_role"),
        "sample_axis": candidate.get("table_sample_axis"),
        "sample_series": candidate.get("table_sample_series"),
        "axis_role": candidate.get("table_axis_role"),
        "header_rows": candidate.get("table_header_rows"),
        "context_source_block_ids": list(
            candidate.get("context_source_block_ids") or []
        ),
        "context_text": str(candidate.get("table_context_text") or "")[:1000],
        "row_index": candidate.get("row_index"),
        "column_index": candidate.get("column_index"),
        "cell_id": candidate.get("cell_id"),
        "label_candidates": labels,
        "subject_relations": copy.deepcopy(candidate.get("subject_relations") or []),
        "subject_resolution": copy.deepcopy(candidate.get("subject_resolution")),
    }


def _table_elements(stage0: Stage0Document) -> dict[str, Any]:
    return {
        item.block_id: item
        for item in stage0.elements
        if item.type == "table"
    }


def _evidence(candidate: Mapping[str, Any], tables: Mapping[str, Any]) -> dict[str, Any]:
    table_id = str(candidate.get("table_id") or "")
    table = tables.get(table_id)
    locator = candidate.get("evidence_locator") or candidate.get("evidence") or {}
    header_path = [str(value) for value in locator.get("header_path") or [] if value]
    value_raw = str(candidate.get("value_raw") or "").strip()
    row_label = candidate.get("source_row_label") or candidate.get("sample_label_raw") or candidate.get("row_label")
    if not row_label and isinstance(locator, Mapping):
        row_label = locator.get("row_label")
    stable_coordinates = all(
        candidate.get(key) is not None
        for key in ("cell_id", "row_index", "column_index")
    )
    if candidate.get("alignment_status") == "inferred_right_shift":
        locator_status = "inferred_column_shift"
    elif stable_coordinates and row_label and header_path:
        locator_status = "stable_cell"
    elif stable_coordinates:
        locator_status = "stable_coordinates_label_missing"
    elif row_label or header_path:
        locator_status = "surface_only"
    else:
        locator_status = "locator_missing"
    return {
        "block_id": table_id,
        "page": int(getattr(table, "page", 0) or 0),
        "bbox": list(table.bbox) if table is not None and table.bbox is not None else None,
        "source_type": "table",
        "source_sentence": value_raw,
        "table_locator": {
            "table_id": table_id,
            "cell_id": candidate.get("cell_id"),
            "row_index": candidate.get("row_index"),
            "column_index": candidate.get("column_index"),
            "row_label": row_label,
            "column_label": candidate.get("source_column_label") or " / ".join(header_path) or candidate.get("property_name_raw"),
            "cell_value": value_raw,
            "locator_status": locator_status,
            "axis_role": candidate.get("table_axis_role") or locator.get("axis_role"),
            "header_path": header_path,
            "raw_row_label": candidate.get("row_label") or row_label,
            "raw_column_header": candidate.get("column_header")
            or (header_path[-1] if header_path else None),
        },
    }


def _condition_context(conditions: Mapping[str, Any]) -> dict[str, Any]:
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
    for key, value in conditions.items():
        if value is None:
            continue
        if key in known:
            field, unit = known[key]
            context[field] = {"raw": f"{value} {unit}", "value": float(value), "unit": unit}
        else:
            context["other_conditions"][str(key)] = str(value)
    if any(
        context[field] is not None
        for field in ("temperature", "frequency", "wavelength")
    ) or context["other_conditions"]:
        context["condition_status"] = "reported"
    return context


def _condition(
    condition_id: str,
    context: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "condition_id": condition_id,
        "temperature": context.get("temperature"),
        "frequency": context.get("frequency"),
        "humidity": context.get("humidity"),
        "pressure": context.get("pressure"),
        "wavelength": context.get("wavelength"),
        "other_conditions": context.get("other_conditions") or {},
        "other_condition_evidence": {},
        "condition_status": context["condition_status"],
        "evidence": dict(evidence),
        "confidence": None,
    }


def _context_signature(context: Mapping[str, Any]) -> str:
    selected = {
        "temperature": context.get("temperature"),
        "frequency": context.get("frequency"),
        "humidity": context.get("humidity"),
        "pressure": context.get("pressure"),
        "wavelength": context.get("wavelength"),
        "other_conditions": context.get("other_conditions") or {},
        "condition_status": context.get("condition_status") or "not_reported",
    }
    return json.dumps(selected, ensure_ascii=False, sort_keys=True)


def _value_equal(left: Any, right: Any) -> bool:
    left_number = _decimal(left)
    right_number = _decimal(right)
    if left_number is not None and right_number is not None:
        return left_number == right_number
    return str(left).strip() == str(right).strip()


def _rounded_equal(left: Any, right: Any) -> bool:
    left_text, right_text = str(left).strip(), str(right).strip()
    left_number, right_number = _decimal(left_text), _decimal(right_text)
    if left_number is None or right_number is None or left_number == right_number:
        return False
    for coarse_text, coarse, precise in (
        (left_text, left_number, right_number),
        (right_text, right_number, left_number),
    ):
        decimals = len(coarse_text.partition(".")[2]) if "." in coarse_text else 0
        quantum = Decimal(1).scaleb(-decimals)
        if precise.quantize(quantum) == coarse:
            return True
    return False


def _units_compatible(left: Any, right: Any) -> bool:
    return not left or not right or _norm(left) == _norm(right)


def _append_unique_evidence(item: dict[str, Any], evidence: dict[str, Any]) -> None:
    cell_id = (evidence.get("table_locator") or {}).get("cell_id")
    if cell_id and cell_id in _cell_ids(item):
        return
    item.setdefault("evidence", []).append(evidence)


# 4T 产出 6 种 value_kind，specialized 模型只收 4 种。区间/不确定度/带状态量
# 统一折成 numeric_scalar，区间端点仍写入 value_min/value_max，不丢信息。
_SPECIALIZED_VALUE_KIND = {
    "numeric_scalar": "numeric_scalar",
    "numeric_multiple": "numeric_multiple",
    "categorical": "categorical",
    "numeric_range": "numeric_scalar",
    "numeric_with_uncertainty": "numeric_scalar",
    "state_qualified_numeric": "numeric_scalar",
}
_NUMBER_RE = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:\s*[eE][+-]?\d+)?")
_SPECIALIZED_ID_RE = re.compile(r"^sp(\d+)$")


# '10-20' 里的 '-' 是区间分隔符，不是负号；先按分隔符切再取数，
# 否则 min/max 会得到 (-20, 10)。'±' 后面的是容差，同样不能当边界。
_RANGE_SPLIT_RE = re.compile(r"\s*(?:~|–|—|to\b|-)\s*", re.IGNORECASE)
_UNCERTAINTY_SPLIT_RE = re.compile(r"\s*(?:±|\+/-|\+-)\s*")


def _first_number(text: str) -> float | None:
    match = _NUMBER_RE.search(str(text or "").replace(",", ""))
    if match is None:
        return None
    try:
        return float(match.group(0).replace(" ", ""))
    except ValueError:
        return None


def _all_numbers(text: str) -> list[float]:
    numbers: list[float] = []
    for match in _NUMBER_RE.finditer(str(text or "").replace(",", "")):
        try:
            numbers.append(float(match.group(0).replace(" ", "")))
        except ValueError:
            continue
    return numbers


def _specialized_bounds(
    value_raw: str,
    raw_kind: str | None = None,
) -> tuple[float | None, float | None]:
    """按 4T 原始 value_kind 取数值区间；单值时 min==max，取不到返回 (None, None)。

    分 kind 处理而非一律 min/max：区间的 '-' 与负号同形、容差不是边界，
    统一 min/max 会在这两种写法上给出错误的 value_min。
    """
    parsed = parse_numeric(value_raw, raw_kind or "")
    if parsed is None:
        return None, None
    return float(min(parsed["values"])), float(max(parsed["values"]))


def _unit_status(candidate: Mapping[str, Any]) -> str:
    if candidate.get("unit_normalized"):
        return "normalized"
    if candidate.get("unit_raw"):
        return "raw_only"
    return "missing"


def _candidate_bounds(candidate: Mapping[str, Any]) -> tuple[float | None, float | None]:
    if candidate.get("normalized_values"):
        return min(candidate["normalized_values"]), max(candidate["normalized_values"])
    if candidate.get("normalized_value_min") is not None:
        return (
            candidate.get("normalized_value_min"),
            candidate.get("normalized_value_max"),
        )
    if candidate.get("normalized_value") is not None:
        value = candidate.get("normalized_value")
        return value, value
    if candidate.get("value_min") is not None or candidate.get("value_max") is not None:
        return candidate.get("value_min"), candidate.get("value_max")
    return _specialized_bounds(
        str(candidate.get("value_raw") or ""),
        str(candidate.get("value_kind") or ""),
    )


def _specialized_record(
    candidate: Mapping[str, Any],
    *,
    specialized_id: str,
    label: str | None,
    resolution: Mapping[str, Any],
    evidence: Mapping[str, Any],
    vocabulary: SpecializedVocabulary,
    variant_fallback: str | None = None,
) -> dict[str, Any]:
    """把候选投影为 specialized 记录；发布资格由词表裁决，不在此硬编码。

    方案 §6.3：原始候选层不强制受控，发布分流才校验。未映射、value_kind 不被
    词表接受、样品未绑定的候选都留在同一数组标 unresolved，守恒式才成立。
    """
    # 改道来的 label 本身就是 vocabulary_key（不在 legacy 登记表内），故先查词表；
    # 查不到再走登记表解析，两条入口共用同一份发布裁决。
    if label and vocabulary.get(label) is not None:
        verdict = LabelResolution(
            label=label,
            vocabulary_key=label,
            publishable=True,
            reason=None,
            registered=True,
        )
    else:
        verdict = vocabulary.resolve_label(label)
    value_raw = str(candidate.get("value_raw") or "").strip()
    raw_kind = str(candidate.get("value_kind") or "")
    value_kind = _SPECIALIZED_VALUE_KIND.get(raw_kind)
    entry = vocabulary.get(verdict.vocabulary_key)

    reason: str | None = verdict.reason
    if verdict.publishable and value_kind is None:
        reason = "unsupported_value_kind"
    elif verdict.publishable and entry is not None and value_kind not in entry.value_kinds:
        reason = "value_kind_not_allowed"

    matched_sample = resolution.get("status") == "matched"
    if reason is None and not matched_sample:
        reason = "sample_binding_unresolved"

    publishable = reason is None
    record: dict[str, Any] = {
        "specialized_id": specialized_id,
        "property_name_raw": (
            str(candidate.get("property_name_raw") or "").strip()
            or str(candidate.get("semantic_label") or "").strip()
            or str(candidate.get("property_name_normalized") or "").strip()
            or "unmapped_specialized_property"
        ),
        "source_field": entry.source_field if publishable else None,
        "semantic_label": verdict.vocabulary_key if publishable else label,
        "variant": candidate.get("property_variant") or variant_fallback,
        # 无法归一的 kind 仍需落一个合法值；此时必为 unresolved，不会被当成数值用。
        "value_kind": value_kind or "text",
        "value_raw": value_raw or "(empty)",
        "value_min": None,
        "value_max": None,
        "categorical_value": None,
        "text_value": None,
        "unit_raw": candidate.get("unit_raw"),
        "unit_normalized": candidate.get("normalized_unit") or candidate.get("unit_normalized"),
        "unit_status": _unit_status(candidate),
        "method_raw": candidate.get("determination_method_raw"),
        "sample_id": resolution.get("sample_id") if matched_sample else None,
        "sample_resolution_status": "resolved" if matched_sample else "unresolved",
        "source_stage": "stage4t",
        "evidence": [dict(evidence)],
        "evidence_ids": [],
        "publication_status": "published" if publishable else "unresolved",
        "reason": reason,
    }
    if record["value_kind"] in {"numeric_scalar", "numeric_multiple"}:
        record["value_min"], record["value_max"] = _specialized_bounds(
            value_raw, raw_kind
        )
    elif record["value_kind"] == "categorical":
        record["categorical_value"] = value_raw or None
    else:
        record["text_value"] = value_raw or None
    if candidate.get("normalization_status") == "normalized":
        if candidate.get("normalized_values"):
            record["numeric_values"] = list(candidate["normalized_values"])
            record["value_min"] = min(candidate["normalized_values"])
            record["value_max"] = max(candidate["normalized_values"])
        elif candidate.get("normalized_value_min") is not None:
            record["value_min"] = candidate["normalized_value_min"]
            record["value_max"] = candidate.get("normalized_value_max")
        elif candidate.get("normalized_value") is not None:
            record["value_min"] = candidate["normalized_value"]
            record["value_max"] = candidate["normalized_value"]
    return record


def unify_documents(
    stage0: Stage0Document,
    stage2: Mapping[str, Any],
    stage3: Mapping[str, Any],
    stage4: Mapping[str, Any],
    sidecar: Mapping[str, Any],
) -> tuple[Stage4Document, dict[str, Any]]:
    payload = copy.deepcopy(dict(stage4))
    legacy_empty_specialized_names = []
    for item in payload.get("specialized_property_observations") or []:
        if not str(item.get("property_name_raw") or "").strip():
            legacy_empty_specialized_names.append(item.get("specialized_id"))
            item["property_name_raw"] = (
                item.get("semantic_label")
                or item.get("source_field")
                or "unmapped_specialized_property"
            )
    if legacy_empty_specialized_names:
        payload.setdefault("warnings", []).append({
            "stage": STAGE_ID,
            "code": "legacy_empty_specialized_name_repaired",
            "message": "历史 specialized 记录缺少原始性质名；保留其语义标签作为兼容显示名，原批次不改写",
            "specialized_ids": legacy_empty_specialized_names,
        })
    candidates = _flatten_candidates(sidecar)
    sample_index, _ = _sample_index(stage2, stage3)
    from stages.stage4t_subject_context import subject_summary, evidence_sources
    from stages.stage4t_table_property import build_table_interpretation_context
    subject_catalog = subject_summary(stage2, stage3)
    table_lookup = _table_elements(stage0)
    from stages.stage4t_structure_expand import replay_visual_sources, structure_audit_valid
    table_structure_audits = {t.get('table_id'): t.get('structure_audit')
                              for t in sidecar.get('tables', []) if isinstance(t, Mapping)}
    table_contexts = {tid: {**build_table_interpretation_context(stage0, table), 'subject_catalog': subject_catalog}
                      for tid, table in table_lookup.items()}
    valid_structure_tables = {tid for tid, audit in table_structure_audits.items()
                              if tid in table_lookup and structure_audit_valid(audit, table_lookup[tid], context=table_contexts[tid])}
    table_visual_sources = {tid: replay_visual_sources(table_structure_audits[tid], table_lookup[tid])
                            for tid in valid_structure_tables}
    table_sources = {tid: {s['source_id']: s['text'] for s in [
        *evidence_sources(table, table_contexts[tid]),
        *table_visual_sources.get(tid, [])]} for tid, table in table_lookup.items()}
    for candidate in candidates:
        table = table_lookup.get(candidate.get('table_id'))
        if table is None:
            candidate.pop('subject_relations', None)
            continue
        sources = table_sources[table.block_id]
        visual_sources = table_visual_sources.get(table.block_id, [])
        if candidate.get('structure_trace') and table.block_id not in valid_structure_tables:
            candidate['normalization_status'] = 'warning'
            candidate['normalization_warning'] = 'structure_audit_rejected'
            candidate['sample_label_raw'] = None
            candidate['conditions'] = {}
            for key in ('normalized_value', 'normalized_values', 'restored_value', 'restored_values'):
                candidate.pop(key, None)
        if visual_sources:
            candidate['visual_evidence'] = copy.deepcopy(visual_sources)
        for field in ('subject_relations', 'scoped_relations'):
            accepted = []
            for relation in candidate.get(field, []):
                refs = relation.get('source_refs') or []
                quote = relation.get('source_quote')
                if (refs and quote and candidate.get('cell_id') in relation.get('target_cell_ids', [])
                        and all(ref in sources for ref in refs) and any(quote in sources[ref] for ref in refs)):
                    accepted.append(relation)
                else:
                    candidate.setdefault('warnings', []).append('scoped_relation_source_rejected')
            candidate[field] = accepted
        candidate['subject_resolution'] = resolve_sample(candidate, sample_index, subject_catalog)
    tables = _table_elements(stage0)
    records: list[dict[str, Any]] = []

    existing = [dict(item) for item in payload.get("properties") or []]
    by_cell: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in existing:
        for cell_id in _cell_ids(item):
            by_cell[cell_id].append(item)

    # 同一来源格子的已映射语义不一致时，Preview 保留 Stage4N 原值，
    # 并把 Stage4T 候选转入现有 specialized 容器标记 unresolved；
    # 不再删除已抽取的 Stage4N property。
    conflict_records: dict[str, dict[str, Any]] = {}
    conflicted_stage4_property_ids: set[str] = set()
    for candidate in candidates:
        cell_id = str(candidate.get("cell_id") or "")
        candidate_semantic = _candidate_semantic(candidate)
        if not cell_id or not candidate_semantic:
            continue
        for item in by_cell.get(cell_id, []):
            if _semantic(item) and _semantic(item) != candidate_semantic:
                resolution = resolve_sample(candidate, sample_index, subject_catalog)
                conflicted_stage4_property_ids.add(str(item["property_id"]))
                candidate_id = str(candidate.get("observation_id") or "")
                if not candidate_id or candidate_id in conflict_records:
                    continue
                record = {
                    "candidate_id": candidate.get("observation_id"),
                    "stage4_property_id": item["property_id"],
                    "cell_id": cell_id,
                    "status": "source_conflict",
                    "reason": "same_cell_semantic_conflict",
                    "stage4_semantic": _semantic(item),
                    "stage4t_semantic": candidate_semantic,
                    "sample_resolution_status": resolution["status"],
                    "sample_label_raw": resolution["label"],
                    "sample_matches": resolution["matches"],
                    "sample_binding_context": _sample_binding_context(candidate),
                }
                if resolution["status"] == "matched":
                    record.update({
                        "sample_id": resolution["sample_id"],
                        "entity_id": resolution.get("entity_id"),
                        "sample_resolution_basis": resolution["basis"],
                        "sample_binding_confidence": resolution.get("confidence"),
                        "sample_binding_anchors": resolution.get("anchors", []),
                    })
                records.append(record)
                conflict_records[candidate_id] = record

    next_property = _next_number(payload.get("properties") or [], "property_id", _PROPERTY_ID_RE)
    next_condition = _next_number(
        payload.get("measurement_conditions") or [], "condition_id", _CONDITION_ID_RE
    )
    next_specialized = _next_number(
        payload.get("specialized_property_observations") or [],
        "specialized_id",
        _SPECIALIZED_ID_RE,
    )
    vocabulary = get_specialized_vocabulary()

    def retain_review(candidate, reason):
        """Keep source-backed values in the unresolved channel, never publish by guess."""
        nonlocal next_specialized
        evidence = _evidence(candidate, tables)
        if (not literal_value_supported({"value_raw":candidate.get("value_raw"),"evidence":[evidence]}, tables)
                or candidate.get("candidate_class") in {"condition_observation", "coordinate_observation"}):
            return []
        contexts,_ = table_evidence_context(evidence,tables[candidate["table_id"]],tables)
        headers = [c["text_raw"] for c in contexts if c["scope"] == "table_header"]
        name = str(candidate.get("property_name_raw") or "")
        if not re.search(r"[A-Za-zα-ωΑ-Ω]", name) or not headers:
            return []
        source_raw = next(c["text_raw"] for c in contexts if c["scope"]=="table_cell")
        composite = composite_candidates(source_raw, headers)
        if composite["status"] == "label_or_formula_not_split":
            return []
        # Without a role definition, A(B) could be uncertainty notation; retain
        # the whole cell and diagnostic parts instead of two independent facts.
        parts = (composite["candidates"] if any(p.get("role_basis") for p in composite["candidates"])
                 else [{"value_raw":source_raw,"position":None}])
        ids = []
        for part in parts:
            key = str(candidate["observation_id"]) + "/" + str(part["position"] or "whole")
            existing = next((i for i in payload.get("specialized_property_observations", [])
                             if (i.get("candidate_trace") or {}).get("candidate_key") == key), None)
            if existing is not None:
                ids.append(existing["specialized_id"]);continue
            data = _specialized_record(candidate,specialized_id=f"sp{next_specialized:03d}",label=candidate.get("semantic_label"),
                resolution={"status":"unresolved"},evidence=evidence,vocabulary=vocabulary)
            next_specialized += 1
            data.update(source_field=None, publication_status="unresolved",
                        reason="composite_part_requires_review" if part["position"] else reason,
                        value_raw=part["value_raw"],value_min=None,value_max=None,numeric_values=[],
                        value_kind="numeric_scalar" if parse_numeric(part["value_raw"]) else "text",
                        text_value=None if parse_numeric(part["value_raw"]) else part["value_raw"],
                        article_sample_key=candidate.get("sample_label_raw"),value_semantics=None,
                        candidate_trace={"candidate_key":key,"candidate_id":candidate["observation_id"],
                            "source_cell_raw":source_raw,"source_candidate_value_raw":candidate["value_raw"],
                            "part_position":part["position"],
                            "source_span":[part["source_start"],part["source_end"]] if part.get("source_start") is not None else None,
                            "composite_status":composite["status"],"original_unit_raw":candidate.get("unit_raw"),
                            "diagnostic_parts":composite["candidates"],
                            "original_candidate_role":candidate.get("candidate_role"),
                            "original_measurement_role":candidate.get("measurement_role"),
                            "original_scale_status":candidate.get("scale_factor_status"),
                            "binding_status":"unresolved", "semantic_status":candidate.get("semantic_status"),
                            "normalization_warning":candidate.get("normalization_warning")})
            observation = FinalSpecializedPropertyObservation.model_validate(data)
            derivation = derive_numeric_value(observation,{b.block_id:b for b in stage0.elements})
            update = {"value_derivation":derivation}
            if derivation.get("status") == "normalized" and derivation.get("actual_values"):
                values = derivation["actual_values"]
                update.update(value_kind="numeric_scalar" if len(values)==1 else "numeric_multiple",
                              numeric_values=values,value_min=min(values),value_max=max(values),
                              reason="property_or_binding_requires_review")
            observation = observation.model_copy(update=update)
            payload.setdefault("specialized_property_observations", []).append(observation.model_dump(mode="json"))
            ids.append(observation.specialized_id)
        return ids

    for candidate in candidates:
        candidate_id = candidate.get("observation_id")
        cell_id = str(candidate.get("cell_id") or "")
        contract_error = _candidate_contract_error(candidate)
        if contract_error:
            records.append({
                "candidate_id": candidate_id,
                "cell_id": cell_id or None,
                "status": "invalid_candidate",
                "reason": contract_error,
                "sample_resolution_status": "not_attempted",
            })
            continue
        conflict_record = conflict_records.get(str(candidate_id) or "")
        if (candidate.get("scale_factor_status") == "ambiguous_display_scale"
                or candidate.get("normalization_status") == "warning"):
            reason = candidate.get("normalization_warning") or "scale_direction_requires_review"
            review_ids = retain_review(candidate,reason)
            records.append({
                "candidate_id": candidate_id, "cell_id": cell_id,
                "status": "retained_candidate",
                "reason": candidate.get("normalization_warning") or "scale_direction_requires_review",
                "sample_resolution_status": "not_attempted",
                "raw_candidate": copy.deepcopy(candidate),
                "specialized_id":review_ids[0] if review_ids else None,
                "specialized_ids":review_ids, "specialized_publication_status":"unresolved" if review_ids else None,
            })
            continue
        if conflict_record is not None:
            resolution = resolve_sample(candidate, sample_index, subject_catalog)
            fallback_label = (
                candidate.get("semantic_label")
                or candidate.get("property_name_normalized")
                or candidate.get("property_name_raw")
            )
            specialized_record = _specialized_record(
                candidate,
                specialized_id=f"sp{next_specialized:03d}",
                label=fallback_label,
                resolution=resolution,
                evidence=_evidence(candidate, tables),
                vocabulary=vocabulary,
            )
            next_specialized += 1
            specialized_record["source_field"] = None
            specialized_record["publication_status"] = "unresolved"
            specialized_record["reason"] = "same_cell_semantic_conflict"
            payload.setdefault("specialized_property_observations", []).append(
                specialized_record
            )
            conflict_record.update({
                "specialized_id": specialized_record["specialized_id"],
                "specialized_publication_status": "unresolved",
                "specialized_reason": "same_cell_semantic_conflict",
            })
            continue
        resolution = resolve_sample(candidate, sample_index, subject_catalog)
        resolution_fields = {
            "sample_resolution_status": resolution["status"],
            "sample_label_raw": resolution["label"],
            "sample_matches": resolution["matches"],
            "sample_binding_context": _sample_binding_context(candidate),
            "source_layer": candidate.get("source_layer"),
            "interpretation_status": candidate.get("interpretation_status"),
            "interpretation_confidence": candidate.get(
                "interpretation_confidence"
            ),
            "confidence_source": candidate.get("confidence_source"),
        }
        if resolution["status"] == "matched":
            resolution_fields.update({
                "sample_id": resolution["sample_id"],
                "entity_id": resolution.get("entity_id"),
                "sample_resolution_basis": resolution["basis"],
                "sample_binding_confidence": resolution.get("confidence"),
                "sample_binding_anchors": resolution.get("anchors", []),
            })
        if candidate.get("candidate_class") != "official_property":
            # 方案 Step 4：非 official 候选不再统一暂扣，改按词表分流。mapped 进
            # specialized 数组；未映射/未绑定同样进该数组标 unresolved 并保留
            # evidence，故守恒式 总候选 = published + unresolved + rejected 成立。
            specialized_record = _specialized_record(
                candidate,
                specialized_id=f"sp{next_specialized:03d}",
                label=candidate.get("semantic_label"),
                resolution=resolution,
                evidence=_evidence(candidate, tables),
                vocabulary=vocabulary,
            )
            next_specialized += 1
            payload.setdefault("specialized_property_observations", []).append(
                specialized_record
            )
            records.append({
                "candidate_id": candidate_id,
                "cell_id": cell_id,
                "status": (
                    "integrated_specialized"
                    if specialized_record["publication_status"] == "published"
                    else "retained_specialized"
                ),
                "reason": specialized_record["reason"] or str(
                    candidate.get("candidate_class") or "unknown_candidate_class"
                ),
                "specialized_id": specialized_record["specialized_id"],
                "specialized_publication_status": specialized_record[
                    "publication_status"
                ],
                "vocabulary_key": specialized_record["semantic_label"],
                **resolution_fields,
            })
            continue
        if not candidate.get("property_name_normalized"):
            review_ids = retain_review(candidate,"property_not_normalized")
            records.append({
                "candidate_id": candidate_id,
                "cell_id": cell_id,
                "status": "retained_candidate",
                "reason": "property_not_normalized",
                "specialized_id":review_ids[0] if review_ids else None,"specialized_ids":review_ids,
                "specialized_publication_status":"unresolved" if review_ids else None,
                **resolution_fields,
            })
            continue
        # 方案 §8 唯一交集：intrinsic_viscosity 改道 specialized。必须**精确**
        # 匹配——melt_viscosity / dynamic_viscosity 属 PolyInfo property[]，不改道，
        # 按 'viscos' 模糊匹配会连带搬走它们，official 侧数字就不止少 34 条。
        if candidate.get("property_name_normalized") == _REROUTED_OFFICIAL_PROPERTY:
            specialized_record = _specialized_record(
                candidate,
                specialized_id=f"sp{next_specialized:03d}",
                label="solution_viscosity",
                resolution=resolution,
                evidence=_evidence(candidate, tables),
                vocabulary=vocabulary,
                variant_fallback="intrinsic",
            )
            next_specialized += 1
            payload.setdefault("specialized_property_observations", []).append(
                specialized_record
            )
            records.append({
                "candidate_id": candidate_id,
                "cell_id": cell_id,
                "status": (
                    "integrated_specialized"
                    if specialized_record["publication_status"] == "published"
                    else "retained_specialized"
                ),
                "reason": specialized_record["reason"] or "rerouted_to_specialized",
                "specialized_id": specialized_record["specialized_id"],
                "specialized_publication_status": specialized_record[
                    "publication_status"
                ],
                "vocabulary_key": specialized_record["semantic_label"],
                "rerouted_from_official": _REROUTED_OFFICIAL_PROPERTY,
                **resolution_fields,
            })
            continue
        if candidate.get("value_kind") not in {
            "numeric_scalar",
            "numeric_range",
            "numeric_with_uncertainty",
            "numeric_multiple",
        }:
            review_ids = retain_review(candidate,"unsupported_value_kind")
            records.append({
                "candidate_id": candidate_id,
                "cell_id": cell_id,
                "status": "retained_candidate",
                "reason": "unsupported_value_kind",
                "specialized_id":review_ids[0] if review_ids else None,"specialized_ids":review_ids,
                "specialized_publication_status":"unresolved" if review_ids else None,
                **resolution_fields,
            })
            continue

        if resolution["status"] != "matched":
            # 正式 PropertyObservation 的 schema 要求 sample_id；配对不是候选
            # 存在的前置条件，因此未绑定的 official 候选转入已有 specialized
            # 容器，保留原始值、单位和 evidence，并以 unresolved 标记待重绑。
            fallback_label = (
                candidate.get("semantic_label")
                or candidate.get("property_name_normalized")
                or candidate.get("property_name_raw")
            )
            specialized_record = _specialized_record(
                candidate,
                specialized_id=f"sp{next_specialized:03d}",
                label=fallback_label,
                resolution=resolution,
                evidence=_evidence(candidate, tables),
                vocabulary=vocabulary,
            )
            next_specialized += 1
            payload.setdefault("specialized_property_observations", []).append(
                specialized_record
            )
            records.append({
                "candidate_id": candidate_id,
                "cell_id": cell_id,
                "status": "retained_specialized",
                "reason": resolution["status"],
                "specialized_id": specialized_record["specialized_id"],
                "specialized_publication_status": specialized_record[
                    "publication_status"
                ],
                **resolution_fields,
            })
            continue

        evidence = _evidence(candidate, tables)
        semantic = _candidate_semantic(candidate)
        candidate_context = _condition_context(candidate.get("conditions") or {})
        same_cell = [
            item for item in payload.get("properties") or [] if cell_id in _cell_ids(item)
        ]
        duplicate = next(
            (
                item for item in same_cell
                if _semantic(item) == semantic
                and _value_equal(item.get("value_raw"), candidate.get("value_raw"))
            ),
            None,
        )
        if duplicate is not None:
            _append_unique_evidence(duplicate, evidence)
            records.append({
                "candidate_id": candidate_id,
                "cell_id": cell_id,
                "status": "duplicate_merged",
                "relationship": "exact_same_cell",
                "property_id": duplicate["property_id"],
                "sample_id": resolution["sample_id"],
                "sample_resolution_status": "matched",
            })
            continue

        cross_source = [
            item for item in payload.get("properties") or []
            if item.get("sample_id") == resolution["sample_id"]
            and _semantic(item) == semantic
            and item.get("source_type") != "table"
            and _units_compatible(item.get("unit_raw"), candidate.get("unit_raw"))
            and _context_signature(item.get("measurement_context") or {})
            == _context_signature(candidate_context)
            and not item.get("determination_method_raw")
        ]
        exact = next(
            (item for item in cross_source if _value_equal(item.get("value_raw"), candidate.get("value_raw"))),
            None,
        )
        rounded = next(
            (item for item in cross_source if _rounded_equal(item.get("value_raw"), candidate.get("value_raw"))),
            None,
        )
        matched = exact or rounded
        if matched is not None:
            _append_unique_evidence(matched, evidence)
            records.append({
                "candidate_id": candidate_id,
                "cell_id": cell_id,
                "status": "duplicate_merged",
                "relationship": "exact" if exact is not None else "rounded",
                "property_id": matched["property_id"],
                "sample_id": resolution["sample_id"],
                "sample_resolution_status": "matched",
            })
            continue

        property_id = f"prop{next_property:03d}"
        condition_id = f"mc{next_condition:03d}"
        next_property += 1
        next_condition += 1
        context = candidate_context
        payload.setdefault("measurement_conditions", []).append(
            _condition(condition_id, context, evidence)
        )
        payload.setdefault("properties", []).append({
            "property_id": property_id,
            "sample_id": resolution["sample_id"],
            "property_name_raw": str(candidate.get("property_name_raw") or candidate["property_name_normalized"]),
            "property_name_normalized": candidate["property_name_normalized"],
            "property_code": None,
            "property_category": None,
            "molecular_weight_type": None,
            "determination_method_raw": None,
            "observation_group_id": None,
            "observation_role": "single",
            "series_id": None,
            "series_ids": None,
            "value_raw": str(candidate.get("value_raw") or "").strip(),
            "value_min": _candidate_bounds(candidate)[0],
            "value_max": _candidate_bounds(candidate)[1],
            "unit_raw": candidate.get("unit_raw"),
            "unit_normalized": candidate.get("normalized_unit") or candidate.get("unit_normalized"),
            "measurement_condition_id": condition_id,
            "measurement_context": context,
            "source_type": "table",
            "evidence": [evidence],
            "confidence": None,
        })
        records.append({
            "candidate_id": candidate_id,
            "cell_id": cell_id,
            "status": "integrated_preview",
            "relationship": "independent",
            "property_id": property_id,
            "sample_id": resolution["sample_id"],
            "sample_resolution_status": "matched",
            "sample_resolution_basis": resolution["basis"],
            "sample_binding_confidence": resolution.get("confidence"),
            "sample_binding_anchors": resolution.get("anchors", []),
        })

    warnings = payload.setdefault("warnings", [])
    if not any(
        isinstance(item, Mapping)
        and item.get("code") == "stage4r_unified_preview"
        for item in warnings
    ):
        warnings.append({
            "code": "stage4r_unified_preview",
            "message": "Stage 4T 仅按 Preview 门控合并；未发布候选见 stage4r_unified_audit.json",
        })
    # Carry the checked T relations through existing extensible trace fields.
    candidate_by_id = {c.get('observation_id'): c for c in candidates}
    for audit_record in records:
        candidate = candidate_by_id.get(audit_record.get('candidate_id'))
        if not candidate:
            continue
        for collection, id_key in (('properties', 'property_id'), ('specialized_property_observations', 'specialized_id')):
            oid = audit_record.get(id_key)
            if not oid:
                continue
            item = next((x for x in payload.get(collection, []) if x.get(id_key) == oid), None)
            if item is not None:
                trace = item.get('candidate_trace') or {}
                item['candidate_trace'] = trace
                bundle = {key: copy.deepcopy(candidate.get(key)) for key in (
                    'scoped_relations', 'subject_resolution', 'property_source_relations', 'metadata_conflicts',
                    'visual_evidence', 'structure_trace', 'value_projection', 'unresolved_metadata_fields',
                    'condition_axes') if candidate.get(key)}
                previous = trace.get('stage4t_relations')
                if previous is None:
                    trace['stage4t_relations'] = bundle
                elif {k:v for k,v in previous.items() if k != 'alternative_candidates'} != bundle:
                    alternatives = previous.setdefault('alternative_candidates', [])
                    if bundle not in alternatives:
                        alternatives.append(bundle)
    from stages.subject_lineage import inherit_entity_ids
    payload = inherit_entity_ids(payload, dict(stage2), dict(stage3))
    merged = Stage4Document.model_validate(payload)
    status_counts = Counter(str(item.get("status")) for item in records)
    audit = {
        "schema_version": "stage4r_unified_audit.v0.1",
        "candidate_contract_version": CANDIDATE_CONTRACT_VERSION,
        "stage": STAGE_ID,
        "implementation_version": IMPLEMENTATION_VERSION,
        "document_id": merged.document_id,
        "authoritative": False,
        "inputs": {"stage4n": "stage4_properties.json", "stage4t": "stage4t_shadow.json"},
        "summary": {
            "candidate_count": len(candidates),
            "candidate_conservation": {
                "input_candidate_count": len(candidates),
                "accounted_candidate_count": len(records),
                "unaccounted_candidate_count": len(candidates) - len(records),
                "balanced": len(candidates) == len(records),
            },
            "integrated_count": status_counts["integrated_preview"],
            "duplicate_merged_count": status_counts["duplicate_merged"],
            "unmatched_sample_count": sum(
                item.get("sample_resolution_status") == "unmatched_sample"
                for item in records
            ),
            "ambiguous_sample_count": sum(
                item.get("sample_resolution_status") == "ambiguous_sample"
                for item in records
            ),
            "source_conflict_count": status_counts["source_conflict"],
            "retained_candidate_count": status_counts["retained_candidate"],
            "review_observation_count":sum(len(i.get("specialized_ids") or []) for i in records),
            "invalid_candidate_count": status_counts["invalid_candidate"],
            "quarantined_stage4_property_count": 0,
            "conflict_stage4_property_count": len(conflicted_stage4_property_ids),
            "specialized_published_count": status_counts["integrated_specialized"],
            "specialized_unresolved_count": sum(
                bool(item.get("specialized_id"))
                and item.get("specialized_publication_status") != "published"
                for item in records
            ),
            "specialized_reason_counts": dict(sorted(Counter(
                str(item.get("reason"))
                for item in records
                if item.get("specialized_id")
                and item.get("specialized_publication_status") != "published"
            ).items())),
            "specialized_vocabulary_sha256": vocabulary.sha256,
            "status_counts": dict(sorted(status_counts.items())),
            "sample_resolution_status_counts": dict(sorted(Counter(
                str(item.get("sample_resolution_status") or "not_recorded")
                for item in records
            ).items())),
        },
        "candidate_outcomes": records,
    }
    from stages.request_trace import content_hash
    audit["input_content_hashes"] = {k: content_hash(v) for k, v in {
        "stage0": stage0.model_dump(mode="json"), "stage2": stage2, "stage3": stage3,
        "stage4n": stage4, "stage4t": sidecar}.items()}
    audit["output_content_sha256"] = content_hash(merged.model_dump(mode="json"))
    return merged, audit


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--ref-no", required=True)
    parser.add_argument("--config", type=Path, help="兼容批处理器；本阶段不读取模型配置")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    input_root = args.input_root.expanduser().resolve()
    output_root = (args.output_root or input_root).expanduser().resolve()
    ref_no = args.ref_no if args.ref_no.startswith("reference_no_") else f"reference_no_{args.ref_no}"
    source = input_root / ref_no
    target = output_root / ref_no
    target.mkdir(parents=True, exist_ok=True)
    output_path = target / OUTPUT_NAME
    audit_path = target / AUDIT_NAME
    source_paths = {
        "stage0_blocks.json": source / "stage0_blocks.json",
        "stage2_entities.json": source / "stage2_entities.json",
        "stage3_process.json": source / "stage3_process.json",
        "stage4_properties.json": source / "stage4_properties.json",
        "stage4t_shadow.json": source / "stage4t_shadow.json",
    }
    input_hashes = {name: _sha256_file(path) for name, path in source_paths.items()}
    if output_path.is_file() and audit_path.is_file() and not args.force:
        cached = json.loads(audit_path.read_text(encoding="utf-8"))
        if (
            cached.get("implementation_version") == IMPLEMENTATION_VERSION
            and cached.get("input_hashes") == input_hashes
        ):
            if args.apply:
                _write_json(target / "stage4_properties.json", json.loads(output_path.read_text(encoding="utf-8")))
            print(f"[cached] {ref_no}: unified Stage 4R Preview 已存在")
            return 0

    stage0 = Stage0Document.model_validate_json(source_paths["stage0_blocks.json"].read_text(encoding="utf-8"))
    stage2 = json.loads(source_paths["stage2_entities.json"].read_text(encoding="utf-8"))
    stage3 = json.loads(source_paths["stage3_process.json"].read_text(encoding="utf-8"))
    stage4 = json.loads(source_paths["stage4_properties.json"].read_text(encoding="utf-8"))
    sidecar = json.loads(source_paths["stage4t_shadow.json"].read_text(encoding="utf-8"))
    merged, audit = unify_documents(stage0, stage2, stage3, stage4, sidecar)
    audit["input_hashes"] = input_hashes
    audit["output_sha256"] = hashlib.sha256(
        merged.model_dump_json().encode("utf-8")
    ).hexdigest()
    _write_json(output_path, merged.model_dump(mode="json"))
    _write_json(audit_path, audit)
    if args.apply:
        destination = target / "stage4_properties.json"
        backup = target / "stage4_properties.pre_unified.json"
        if destination.is_file() and not backup.is_file():
            shutil.copy2(destination, backup)
        _write_json(destination, merged.model_dump(mode="json"))
    print(json.dumps({
        "document_id": merged.document_id,
        **audit["summary"],
        "preview_path": str(output_path),
        "applied": bool(args.apply),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
