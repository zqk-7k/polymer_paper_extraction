"""Repair historical specialized evidence registration on a copy, with source checks."""
from __future__ import annotations

from copy import deepcopy
import json
import re

from pydantic import ValidationError

from schema.polymer_schema import Evidence, Stage0Element


def _key(evidence: dict) -> str:
    content = {k: v for k, v in evidence.items() if k not in {"evidence_id", "source_stage", "object_id"}}
    return json.dumps(Evidence.model_validate(content).model_dump(mode="json"), sort_keys=True, ensure_ascii=False)


def _reserved_ids(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "evidence_id":
                yield child
            elif key == "evidence_ids" and isinstance(child, list):
                yield from child
            else:
                yield from _reserved_ids(child)
    elif isinstance(value, list):
        for child in value:
            yield from _reserved_ids(child)


def repair_specialized_evidence(payload: dict, stage0: dict) -> tuple[dict, list[dict]]:
    from stages.stage6_validate_merge import EvidenceRegistry

    if payload.get("document_id") != stage0.get("document_id"):
        raise ValueError("Evidence repair requires the same source document")
    out = deepcopy(payload)
    if not out.get("specialized_property_observations"):
        return out, []
    pool = out.setdefault("evidence", [])
    if len({e["evidence_id"] for e in pool}) != len(pool):
        raise ValueError("Ambiguous existing evidence registry")
    block_map = {e["block_id"]: Stage0Element.model_validate(e) for e in stage0.get("elements", [])}
    if len(block_map) != len(stage0.get("elements", [])):
        raise ValueError("Duplicate or missing source block IDs")
    known = {_key(e): e["evidence_id"] for e in pool}
    numbers = [int(str(e)[2:]) for e in _reserved_ids(out) if re.fullmatch(r"ev\d+", str(e))]
    next_id = max(numbers, default=0) + 1
    changes = []
    for index, item in enumerate(out.get("specialized_property_observations", [])):
        before = list(item.get("evidence_ids") or [])
        inline = item.get("evidence") or []
        if not inline:
            continue
        errors, warnings = [], []
        registry = EvidenceRegistry(block_map, errors, warnings, preview=True)
        try:
            registry.add_many(
                [Evidence.model_validate(e) for e in inline],
                stage="stage5_characterization" if item.get("source_stage") == "stage5" else "stage4_property",
                object_id=item["specialized_id"],
            )
        except (ValueError, ValidationError):
            changes.append({"object_id": item["specialized_id"], "index": index, "status": "not_repaired", "reasons": ["invalid_inline_evidence"]})
            continue
        if errors:
            changes.append({"object_id": item["specialized_id"], "index": index, "status": "not_repaired", "reasons": sorted({e.code for e in errors})})
            continue
        after = []
        for evidence in registry.items:
            content = evidence.model_dump(mode="json")
            key = _key(content)
            if key not in known:
                eid = f"ev{next_id:03d}"
                next_id += 1
                known[key] = eid
                pool.append({**content, "evidence_id": eid})
            after.append(known[key])
        item["evidence_ids"] = after
        if before != after:
            changes.append({
                "object_id": item["specialized_id"], "index": index, "status": "registered",
                "before_evidence_ids": before, "after_evidence_ids": after,
                "validation_warnings": sorted({w.code for w in warnings}),
            })
    return out, changes
