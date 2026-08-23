"""Preview-only Stage 4R：合并正文 Stage 4N 与表格 Stage 4T 候选。

只有已规范化的正式性质且能唯一绑定 Stage 3 Sample 时才写入
Stage4Document。其余候选保留在审计文件中，不阻断后续 Stage 5/6。
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

from schema.polymer_schema import Stage0Document, Stage4Document


STAGE_ID = "stage4r_unified_preview"
IMPLEMENTATION_VERSION = "0.1.0"
OUTPUT_NAME = "stage4_properties.unified_preview.json"
AUDIT_NAME = "stage4r_unified_audit.json"
CANDIDATE_CONTRACT_VERSION = "stage4r_candidate_input.v0.1"
_PROPERTY_ID_RE = re.compile(r"^prop(\d+)$")
_CONDITION_ID_RE = re.compile(r"^mc(\d+)$")


def _norm(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").casefold())


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
    return [
        dict(item)
        for table in sidecar.get("tables") or []
        if isinstance(table, Mapping)
        for item in table.get("observations") or []
        if isinstance(item, Mapping)
    ]


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
        for key in ("canonical_name", "normalized_name", "display_name"):
            if entity.get(key):
                aliases_by_entity[entity_id].add(str(entity[key]))
        aliases_by_entity[entity_id].update(
            str(value) for value in entity.get("source_names") or [] if value
        )

    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        labels = {sample.get("sample_label_raw"), sample.get("polymer_name")}
        labels.update(aliases_by_entity.get(str(sample.get("refers_to_entity") or ""), set()))
        for label in labels:
            normalized = _norm(label)
            if normalized and sample not in index[normalized]:
                index[normalized].append(sample)
    return index, samples


def resolve_sample(
    candidate: Mapping[str, Any],
    sample_index: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    label = str(candidate.get("sample_label_raw") or "").strip()
    if not label:
        return {"status": "unmatched_sample", "label": None, "matches": []}
    matches = list(sample_index.get(_norm(label), ()))
    if len(matches) == 1:
        sample = matches[0]
        return {
            "status": "matched",
            "label": label,
            "sample_id": sample["sample_id"],
            "entity_id": sample.get("refers_to_entity"),
            "basis": "normalized_sample_or_entity_alias",
            "matches": [sample["sample_id"]],
        }
    return {
        "status": "ambiguous_sample" if matches else "unmatched_sample",
        "label": label,
        "matches": [item["sample_id"] for item in matches],
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
            "row_label": candidate.get("sample_label_raw"),
            "column_label": " / ".join(header_path) or candidate.get("property_name_raw"),
            "cell_value": value_raw,
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


def unify_documents(
    stage0: Stage0Document,
    stage2: Mapping[str, Any],
    stage3: Mapping[str, Any],
    stage4: Mapping[str, Any],
    sidecar: Mapping[str, Any],
) -> tuple[Stage4Document, dict[str, Any]]:
    payload = copy.deepcopy(dict(stage4))
    candidates = _flatten_candidates(sidecar)
    sample_index, _ = _sample_index(stage2, stage3)
    tables = _table_elements(stage0)
    records: list[dict[str, Any]] = []

    existing = [dict(item) for item in payload.get("properties") or []]
    by_cell: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in existing:
        for cell_id in _cell_ids(item):
            by_cell[cell_id].append(item)

    # 同一来源格子的已映射语义不一致时，Preview 不选择任一结果，先隔离。
    quarantined_ids: set[str] = set()
    for candidate in candidates:
        cell_id = str(candidate.get("cell_id") or "")
        candidate_semantic = _candidate_semantic(candidate)
        if not cell_id or not candidate_semantic:
            continue
        for item in by_cell.get(cell_id, []):
            if _semantic(item) and _semantic(item) != candidate_semantic:
                resolution = resolve_sample(candidate, sample_index)
                quarantined_ids.add(str(item["property_id"]))
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
                }
                if resolution["status"] == "matched":
                    record.update({
                        "sample_id": resolution["sample_id"],
                        "entity_id": resolution.get("entity_id"),
                        "sample_resolution_basis": resolution["basis"],
                    })
                records.append(record)
    if quarantined_ids:
        payload["properties"] = [
            item for item in existing if str(item.get("property_id")) not in quarantined_ids
        ]
        used_conditions = {
            str(item.get("measurement_condition_id"))
            for item in payload["properties"]
            if item.get("measurement_condition_id")
        }
        payload["measurement_conditions"] = [
            item for item in payload.get("measurement_conditions") or []
            if str(item.get("condition_id")) in used_conditions
        ]

    next_property = _next_number(payload.get("properties") or [], "property_id", _PROPERTY_ID_RE)
    next_condition = _next_number(
        payload.get("measurement_conditions") or [], "condition_id", _CONDITION_ID_RE
    )

    for candidate in candidates:
        candidate_id = candidate.get("observation_id")
        cell_id = str(candidate.get("cell_id") or "")
        if any(
            record.get("candidate_id") == candidate_id
            and record.get("status") == "source_conflict"
            for record in records
        ):
            continue
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
        resolution = resolve_sample(candidate, sample_index)
        resolution_fields = {
            "sample_resolution_status": resolution["status"],
            "sample_label_raw": resolution["label"],
            "sample_matches": resolution["matches"],
        }
        if resolution["status"] == "matched":
            resolution_fields.update({
                "sample_id": resolution["sample_id"],
                "entity_id": resolution.get("entity_id"),
                "sample_resolution_basis": resolution["basis"],
            })
        if candidate.get("candidate_class") != "official_property":
            records.append({
                "candidate_id": candidate_id,
                "cell_id": cell_id,
                "status": "retained_candidate",
                "reason": str(candidate.get("candidate_class") or "unknown_candidate_class"),
                **resolution_fields,
            })
            continue
        if not candidate.get("property_name_normalized"):
            records.append({
                "candidate_id": candidate_id,
                "cell_id": cell_id,
                "status": "retained_candidate",
                "reason": "property_not_normalized",
                **resolution_fields,
            })
            continue
        if candidate.get("value_kind") not in {"numeric_scalar", "numeric_range"}:
            records.append({
                "candidate_id": candidate_id,
                "cell_id": cell_id,
                "status": "retained_candidate",
                "reason": "unsupported_value_kind",
                **resolution_fields,
            })
            continue

        if resolution["status"] != "matched":
            records.append({
                "candidate_id": candidate_id,
                "cell_id": cell_id,
                "status": resolution["status"],
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
            "value_min": candidate.get("value_min"),
            "value_max": candidate.get("value_max"),
            "unit_raw": candidate.get("unit_raw"),
            "unit_normalized": candidate.get("unit_normalized"),
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
            "integrated_count": status_counts["integrated_preview"],
            "duplicate_merged_count": status_counts["duplicate_merged"],
            "unmatched_sample_count": status_counts["unmatched_sample"],
            "ambiguous_sample_count": status_counts["ambiguous_sample"],
            "source_conflict_count": status_counts["source_conflict"],
            "retained_candidate_count": status_counts["retained_candidate"],
            "invalid_candidate_count": status_counts["invalid_candidate"],
            "quarantined_stage4_property_count": len(quarantined_ids),
            "status_counts": dict(sorted(status_counts.items())),
            "sample_resolution_status_counts": dict(sorted(Counter(
                str(item.get("sample_resolution_status") or "not_recorded")
                for item in records
            ).items())),
        },
        "candidate_outcomes": records,
    }
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
