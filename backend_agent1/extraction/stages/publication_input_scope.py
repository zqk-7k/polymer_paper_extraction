"""Conservative, per-record input completeness using saved Stage5 shard audits."""
from __future__ import annotations

import json


def stage4_input_diagnostics(stage: dict | None, response: dict | None = None) -> dict:
    """Explain a partial stage without treating saved response text as proof."""
    codes = sorted({w.get("code") for w in (stage or {}).get("warnings", []) if w.get("code")})
    categories = []
    for code, category in (
        ("preview_semantic_validation_bypassed", "source_semantics_unverified"),
        ("preview_objects_salvaged", "objects_partially_salvaged"),
        ("preview_objects_quarantined", "invalid_objects_quarantined"),
        ("preview_degraded_empty_shell", "structured_output_unavailable"),
        ("preview_incomplete_response", "response_declared_incomplete"),
        ("series_subject_unresolved", "series_binding_unresolved"),
    ):
        if code in codes:
            categories.append(category)
    status = (stage or {}).get("provenance", {}).get("status", "missing")
    if stage is None:
        categories.append("stage_input_missing")
    elif status not in {"success", "complete_no_evidence"} and not categories:
        categories.append("partial_reason_unspecified")
    raw = (response or {}).get("raw_response") or {}
    structured = False
    try:
        structured = isinstance(json.loads(raw.get("content", "")), dict)
    except (ValueError, TypeError):
        pass
    return {
        "input_status": status, "warning_codes": codes, "diagnostic_categories": categories,
        "saved_response_available": response is not None,
        "response_status": (response or {}).get("status"),
        "finish_reason": raw.get("finish_reason"), "strict_json_object": structured,
        "request_input_link_verified": False,
        "publication_status_changed": False,
        "next_action": "restore_missing_stage_input" if stage is None else (
            "verify_request_input_link_and_record_dependencies" if status not in {"success", "complete_no_evidence"}
            else "continue_record_evidence_audit"),
    }


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _evidence(item: dict, registry: dict) -> list[dict]:
    result = []
    for node in _walk(item):
        if node.get("block_id"):
            result.append(node)
        for eid in _reference_ids(node):
            if eid in registry:
                result.append(registry[eid])
    return result


def _reference_ids(node: dict):
    def leaves(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, list):
            for child in value:
                yield from leaves(child)
        elif isinstance(value, dict):
            for child in value.values():
                yield from leaves(child)
    for key, value in node.items():
        if key.endswith("evidence_ids"):
            yield from leaves(value)


def _signature(item: dict, registry: dict) -> str:
    # IDs of properties/characterizations are renumbered during shard merge.
    evidence = sorted({json.dumps({
        "block_id": e.get("block_id"), "source_sentence": e.get("source_sentence"),
        "cell_id": (e.get("table_locator") or {}).get("cell_id"),
    }, sort_keys=True) for e in _evidence({"evidence": item.get("evidence"), "evidence_ids": item.get("evidence_ids", [])}, registry)})
    fields = ("property_name_raw", "value_raw", "unit_raw", "sample_id", "entity_id", "sample_ids", "entity_ids")
    return json.dumps({**{key: item.get(key) for key in fields}, "evidence": evidence}, sort_keys=True)


def stage4_record_input_scope(item: dict, payload: dict, stage: dict, proof: dict) -> dict:
    """Certify only an unchanged scalar in the traced, validated Stage4 output."""
    from stages.series_input_scope import point_input_scope
    result = {"input_status": stage.get("provenance", {}).get("status"), "input_complete": False,
              "input_scope_basis": proof["basis"], "input_scope_reasons": list(proof["reasons"]), "input_shard_ids": []}
    if not proof["verified"]:
        return result
    registry = {e["evidence_id"]: e for e in payload.get("evidence", []) if e.get("evidence_id")}
    if any(eid not in registry for node in _walk(item) for eid in _reference_ids(node)):
        result["input_scope_reasons"].append("input_scope_reference_unknown")
        return result
    def meaning(value):
        if isinstance(value, dict):
            return {k: meaning(v) for k, v in value.items() if v is not None and k not in {"evidence", "confidence"} and not k.endswith("evidence_ids")}
        if isinstance(value, list):
            return [meaning(v) for v in value]
        return value
    fields = ("measurement_context", "measurement_condition_id", "measurement_condition_ids", "condition_id", "condition_ids",
              "method_raw", "determination_method_raw", "display_scale_raw", "scale_factor_raw", "scale_factor_exponent")
    def conditions(value):
        return meaning({k: value[k] for k in fields if value.get(k) is not None})
    matches = [c for collection in ("properties", "unresolved_properties", "specialized_property_observations")
               for c in stage.get(collection, []) if _signature(c, {}) == _signature(item, registry) and conditions(c) == conditions(item)]
    if len(matches) != 1:
        result["input_scope_reasons"].append("traced_stage4_record_not_unique")
        return result
    scope = point_input_scope({}, matches[0], proof)
    result.update(scope)
    if scope["input_complete"]:
        # Include Stage6's resolved evidence, so an extra condition dependency
        # outside the actual request cannot be hidden by the matched core fields.
        scope = point_input_scope({}, {"evidence": _evidence(item, registry)}, proof, dependencies_only=True)
        result.update(scope)
    return result


def record_input_scope(item: dict, payload: dict, stage: dict | None, shards: dict | None = None) -> dict:
    status = (stage or {}).get("provenance", {}).get("status", "missing")
    result = {"input_status": status, "input_complete": False, "input_scope_basis": "unverified", "input_shard_ids": [], "input_scope_reasons": []}
    reasons = result["input_scope_reasons"]
    if stage is None:
        reasons.append("stage_input_missing")
        return result
    if shards is None:
        if status in {"success", "complete_no_evidence"}:
            result.update(input_complete=True, input_scope_basis="stage_complete")
        else:
            reasons.append("partial_input_scope_unverified")
        return result
    rows = shards.get("shards") or []
    if (shards.get("schema_version") != "stage5_shards.v0.2"
            or shards.get("document_id") != payload.get("document_id")
            or shards.get("status") not in {"success", "candidate_partial"}
            or shards.get("shard_count") != len(rows) or not rows
            or any(s.get("status") not in {"complete", "candidate_partial", "failed"} or not s.get("block_ids") for s in rows)
            or len({s.get("shard_id") for s in rows}) != len(rows)):
        reasons.append("shard_manifest_incomplete")
        return result
    if status not in {"success", "complete_no_evidence", "candidate_partial"}:
        reasons.append("stage_input_incomplete")
        return result
    registry = {e["evidence_id"]: e for e in payload.get("evidence", [])}
    dependencies = [item]
    if item.get("characterization_id"):
        owners = [c for c in stage.get("characterizations", []) if c.get("characterization_id") == item["characterization_id"]]
        if len(owners) != 1:
            reasons.append("characterization_scope_unverified")
            return result
        dependencies.extend(owners)
    if any(eid not in registry for node in _walk(dependencies) for eid in _reference_ids(node)):
        reasons.append("input_scope_reference_unknown")
        return result
    blocks = {e["block_id"] for e in _evidence(dependencies, registry) if e.get("block_id")}
    if not blocks:
        reasons.append("input_scope_evidence_missing")
        return result
    relevant = [s for s in rows if blocks.intersection(s["block_ids"])]
    result["input_shard_ids"] = sorted(s["shard_id"] for s in relevant)
    if blocks.intersection(shards.get("unrouted_block_ids", [])) or blocks - {b for s in relevant for b in s["block_ids"]}:
        reasons.append("input_scope_uncovered")
        return result
    if any(s["status"] != "complete" for s in relevant):
        reasons.append("input_shard_incomplete")
        return result
    # Coverage alone is insufficient: a saved validated result must contain
    # this same record, including value, subject and original evidence.
    signature = _signature(item, registry)
    matches = [s for s in relevant if any(
        _signature(candidate, {}) == signature
        for collection in ("properties", "specialized_property_observations")
        for candidate in (s.get("result") or {}).get(collection, [])
    )]
    if len(matches) != 1:
        reasons.append("shard_record_not_unique")
        return result
    result.update(input_complete=True, input_scope_basis="complete_shard_record")
    return result
