"""Explicit article-local entity/sample/process references; never infer identity by name."""
from __future__ import annotations

import copy
from collections import Counter, defaultdict

LINEAGE_VERSION = "subject_lineage.v1"
COLLECTIONS = ("properties", "unresolved_properties", "property_observations",
               "unresolved_property_observations", "specialized_property_observations", "characterizations")


def observations(payload: dict):
    for collection in COLLECTIONS:
        for index, item in enumerate(payload.get(collection) or []):
            yield f"{collection}[{index}]", item
    for index, series in enumerate(payload.get("property_series") or []):
        yield f"property_series[{index}]", series
        for n, point in enumerate(series.get("points") or []):
            # A point-level subject replaces the series-level subject as a unit.
            subject = {} if any(point.get(k) for k in ("sample_id", "entity_id", "sample_ids", "entity_ids")) or point.get("sample_resolution_status") == "unresolved" else {
                k: series.get(k) for k in ("sample_id", "entity_id", "sample_ids", "entity_ids")}
            yield f"property_series[{index}].points[{n}]", {**point, **subject}


def build_lineage(stage2: dict | None, stage3: dict, stage1: dict | None = None) -> dict:
    entities = {x["entity_id"]: copy.deepcopy(x) for x in (stage2 or {}).get("polymer_entities", [])}
    samples = {x["sample_id"]: copy.deepcopy(x) for x in stage3.get("samples", [])}
    steps = {x["step_id"]: copy.deepcopy(x) for x in stage3.get("process_steps", [])}
    producers, errors = defaultdict(list), []
    for step_id, step in steps.items():
        for sid in step.get("output_sample_ids", []):
            producers[sid].append(step_id)
        for sid in set(step.get("input_sample_ids", []) + step.get("output_sample_ids", [])) - samples.keys():
            errors.append({"code": "process_unknown_sample", "step_id": step_id, "sample_id": sid})
    for sid, sample in samples.items():
        eid = sample.get("refers_to_entity")
        if eid and stage2 is not None and eid not in entities:
            errors.append({"code": "sample_unknown_entity", "sample_id": sid, "entity_id": eid})
    mentions = {x["mention_id"] for x in (stage1 or {}).get("material_mentions", [])}
    for eid, entity in entities.items():
        if entity.get("variant_of") and entity["variant_of"] not in entities:
            errors.append({"code": "variant_unknown_entity", "entity_id": eid})
        if stage1 is not None:
            for mid in set(entity.get("resolved_from_mentions", [])) - mentions:
                errors.append({"code": "entity_unknown_mention", "entity_id": eid, "mention_id": mid})
    return {"schema_version": LINEAGE_VERSION, "stage2_available": stage2 is not None,
            "entities": entities, "samples": samples, "process_steps": steps,
            "producers": dict(producers), "reference_errors": errors}


def subject_chain(item: dict, lineage: dict) -> dict:
    samples, entities = lineage["samples"], lineage["entities"]
    sids = sorted(set(item.get("sample_ids") or []) | ({item["sample_id"]} if item.get("sample_id") else set()))
    explicit_eids = set(item.get("entity_ids") or []) | ({item["entity_id"]} if item.get("entity_id") else set())
    derived = {samples[s].get("refers_to_entity") for s in sids if s in samples} - {None}
    errors = []
    if set(sids) - samples.keys():
        errors.append("unknown_sample_id")
    if lineage["stage2_available"] and (derived | explicit_eids) - entities.keys():
        errors.append("unknown_entity_id")
    if derived and explicit_eids and derived != explicit_eids:
        errors.append("sample_entity_conflict")
    eids = sorted(derived | explicit_eids)
    visited, active, step_ids = set(), set(), set()

    def visit(sid):
        if sid in active:
            errors.append("process_cycle")
            return
        if sid in visited:
            return
        active.add(sid)
        for step_id in lineage["producers"].get(sid, []):
            step_ids.add(step_id)
            for parent in lineage["process_steps"][step_id].get("input_sample_ids", []):
                if parent not in samples:
                    errors.append("process_unknown_sample")
                visit(parent)
        active.remove(sid)
        visited.add(sid)

    for sid in sids:
        visit(sid)
    if errors:
        status = "conflict"
    elif not lineage["stage2_available"]:
        status = "stage2_unavailable"
    elif not sids:
        status = "entity_only" if eids else "subject_unlinked"
    elif any(not samples[s].get("refers_to_entity") for s in sids):
        status = "entity_unlinked"
    else:
        status = "linked"
    return {"status": status, "sample_ids": sids, "entity_ids": eids,
            "entity_id_basis": "explicit" if explicit_eids else "stage3_sample_reference" if derived else "missing",
            "process_step_ids": sorted(step_ids), "ancestor_sample_ids": sorted(visited - set(sids)),
            "mention_ids": sorted({mid for eid in eids for mid in entities.get(eid, {}).get("resolved_from_mentions", [])}),
            "errors": sorted(set(errors))}


def inherit_entity_ids(payload: dict, stage2: dict, stage3: dict) -> dict:
    """Enrich only exact existing sample references; leave missing or conflicting subjects intact."""
    result = copy.deepcopy(payload)
    lineage = build_lineage(stage2, stage3)
    rows = [item for key in COLLECTIONS for item in result.get(key, [])]
    for series in result.get("property_series", []):
        rows.append(series)
        rows.extend(series.get("points", []))
    for item in rows:
        chain = subject_chain(item, lineage)
        if chain["errors"]:
            continue
        if item.get("sample_id") and not item.get("entity_id") and len(chain["entity_ids"]) == 1:
            item["entity_id"] = chain["entity_ids"][0]
        elif item.get("sample_ids") and not item.get("entity_ids") and chain["status"] == "linked":
            item["entity_ids"] = chain["entity_ids"]
    return result


def audit_lineage(files: dict) -> dict:
    lineage = build_lineage(files.get("stage2_entities.json"), files["stage3_process.json"], files.get("stage1_mentions.json"))
    rows = []
    for filename, payload in files.items():
        if filename.startswith(("stage0", "stage1", "stage2", "stage3")):
            continue
        for path, item in observations(payload):
            rows.append({"source_file": filename, "path": path,
                         "object_id": next((item[k] for k in ("property_id", "point_id", "series_id", "characterization_id", "specialized_id", "unresolved_id") if item.get(k)), None),
                         **subject_chain(item, lineage)})
    return {"schema_version": LINEAGE_VERSION, "document_id": files["stage3_process.json"].get("document_id"),
            "reference_errors": lineage["reference_errors"],
            "sample_chains": [{"sample_id": sid, **subject_chain({"sample_id": sid}, lineage)} for sid in lineage["samples"]],
            "observation_status_counts": dict(Counter(r["status"] for r in rows)),
            "rows": rows, "metrics_scope": "source objects including versions; entity_unlinked may include non-polymer process inputs"}
