"""Verify complete response/input provenance and per-point source dependencies."""
from __future__ import annotations

import json
import hashlib
import re

from schema.polymer_schema import Stage0Document, Stage2Document, Stage3Document, compact_confidence_payload
from stages.request_trace import content_hash
from stages.stage4_property import _element_source_text


def _complete_response_object(content):
    text = content.strip()
    response_format = "json"
    if text.startswith("```"):
        match = re.fullmatch(r"```(?:json)?[ \t]*\r?\n([\s\S]*)\r?\n```", text, re.I)
        if not match:
            raise ValueError("Incomplete or unsupported JSON wrapper")
        text = match[1]
        response_format = "single_json_code_fence"
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("Response must be a JSON object")
    return parsed, response_format


def _request_blocks(message: str) -> list:
    name = "FULL ARTICLE BLOCKS" if "--- BEGIN UNTRUSTED FULL ARTICLE BLOCKS ---\n" in message else "METHODS AND RESULTS BLOCKS"
    marker = f"--- BEGIN UNTRUSTED {name} ---\n"
    start = message.index(marker) + len(marker)
    blocks, end = json.JSONDecoder().raw_decode(message[start:])
    if not isinstance(blocks, list) or not message[start + end:].startswith(f"\n--- END UNTRUSTED {name} ---"):
        raise ValueError("Invalid source section")
    return blocks


def verify_series_input_trace(stage0, stage2, stage3, stage4, trace, origin_trace=None,
                              *, stage4n=None, stage4t=None, stage4r_audit=None,
                              lineage_file_hashes=None):
    if stage4n is not None and content_hash(stage4n) != content_hash(stage4):
        proof = verify_series_input_trace(stage0, stage2, stage3, stage4n, trace, origin_trace)
        chain = verify_stage4r_lineage(stage0, stage2, stage3, stage4n, stage4t,
                                      stage4, stage4r_audit, lineage_file_hashes)
        proof["stage4r_lineage"] = chain
        if not chain["verified"]:
            proof.update(verified=False, basis="unverified")
            proof["reasons"].append("stage4r_lineage_unverified")
        elif proof["verified"]:
            # R-derived records never borrow N's model/input certificate.
            proof["traced_object_hashes"] = traced_object_hashes(stage4n)
            if proof.get("semantic_scope") == "per_object":
                proof["accepted_traced_object_hashes"] = traced_object_hashes(
                    stage4n, proof["object_semantic_audit"]["accepted_object_hashes"])
        return proof
    result = {"verified": False, "basis": "unverified", "selected_block_ids": [], "reasons": []}
    reasons = result["reasons"]
    if trace is None:
        reasons.append("request_trace_missing")
        return result
    try:
        models = [cls.model_validate(compact_confidence_payload(data)[0]) for cls, data in
                  ((Stage0Document, stage0), (Stage2Document, stage2), (Stage3Document, stage3))]
        inputs = {name: model.model_dump(mode="json") for name, model in zip(("stage0", "stage2", "stage3"), models)}
        if any(data["document_id"] != stage4["document_id"] for data in inputs.values()):
            raise ValueError("Mixed documents")
        for value in [trace] + ([origin_trace] if origin_trace is not None else []):
            # 原 live 请求可以在完整响应后因本地物化失败；不改写其失败状态。
            # 下方仍验证响应完整、哈希及回放与原请求完全一致。
            allowed_statuses = {"completed", "failed"} if value is origin_trace else {"completed"}
            if (value.get("schema_version") != "stage4_request_trace.v1" or value.get("status") not in allowed_statuses
                    or value.get("document_id") != stage4["document_id"]):
                raise ValueError("Incomplete trace")
            if any(value.get("input_model_hashes", {}).get(name) != content_hash(data) for name, data in inputs.items()):
                raise ValueError("Inputs changed")
            attempts = value.get("attempts") or []
            if not attempts:
                raise ValueError("No request")
            for index, attempt in enumerate(attempts, 1):
                if attempt.get("attempt") != index or attempt.get("request_sha256") != content_hash(attempt.get("request")):
                    raise ValueError("Request changed")
            last = attempts[-1]
            if last.get("status") != "response_received" or "parsed_response" not in last or last.get("parsed_response_sha256") != content_hash(last["parsed_response"]):
                raise ValueError("Response incomplete")
        if trace.get("output_sha256") != content_hash(stage4):
            raise ValueError("Stage4 output changed")
        current = trace["attempts"][-1]
        if trace.get("mode") == "live":
            live = current
        elif trace.get("mode") == "offline_replay" and origin_trace and origin_trace.get("mode") == "live":
            live = origin_trace["attempts"][-1]
            if (current["request_sha256"] != live["request_sha256"]
                    or current["parsed_response_sha256"] != live["parsed_response_sha256"]):
                raise ValueError("Replay does not match actual request/response")
        else:
            raise ValueError("Actual request provenance missing")
        raw = live.get("raw_response") or {}
        if not raw or live.get("raw_response_sha256") != content_hash(raw) or raw.get("finish_reason") not in {"end_turn", "stop"}:
            raise ValueError("Raw response incomplete")
        # A repaired or partial JSON parse cannot certify complete input here.
        parsed, response_format = _complete_response_object(raw["content"])
        if content_hash(parsed) != current["parsed_response_sha256"]:
            raise ValueError("Raw and parsed response mismatch")
        result["response_format"] = response_format
        blocks = _request_blocks(current["request"]["user_message"])
        block_map = {block.block_id: block for block in models[0].elements}
        ids = [b["block_id"] for b in blocks]
        if len(ids) != len(set(ids)) or any(b["block_id"] not in block_map or b.get("source_text") != _element_source_text(block_map[b["block_id"]]) for b in blocks):
            raise ValueError("Request source blocks differ")
        result["selected_block_ids"] = sorted(ids)
    except (KeyError, ValueError, TypeError, AttributeError):
        reasons.append("request_response_input_link_unverified")
        return result
    blocked_codes = {"preview_degraded_empty_shell", "preview_incomplete_response"}
    object_codes = {"preview_semantic_validation_bypassed", "preview_objects_salvaged"}
    safe_blocking = {"preview_objects_quarantined", "series_subject_unresolved"}
    if any(w.get("code") in blocked_codes or (w.get("blocking") and w.get("code") not in safe_blocking) for w in stage4.get("warnings", [])):
        reasons.append("stage4_semantic_or_structural_validation_incomplete")
        return result
    if stage4.get("provenance", {}).get("status") not in {"success", "candidate_partial"}:
        reasons.append("stage4_status_incomplete")
        return result
    object_review = any(w.get("code") in object_codes for w in stage4.get("warnings", []))
    if object_review:
        from stages.stage4_object_validation import validate_objects
        selected_source = models[0].model_copy(update={"elements": [b for b in models[0].elements if b.block_id in ids]})
        audit = validate_objects(stage4, selected_source, models[1], models[2])
        result["object_semantic_audit"] = audit
        if not audit["accepted_count"]:
            reasons.append("stage4_semantic_or_structural_validation_incomplete")
            return result
        result["semantic_scope"] = "per_object"
    if stage4.get("provenance", {}).get("status") == "candidate_partial" and not any(
        w.get("code") in safe_blocking for w in stage4.get("warnings", [])
    ) and not object_review:
        reasons.append("partial_stage_cause_unverified")
        return result
    result.update(verified=True, basis="verified_live_trace" if trace["mode"] == "live" else "verified_replay_of_live_response")
    return result


def _object_hash(series, point):
    # R materializes optional null fields. Ignore only absence versus null;
    # retain all non-null values, empty containers, evidence and conditions.
    def without_nulls(value):
        if isinstance(value, dict):
            return {k: without_nulls(v) for k, v in value.items() if v is not None}
        if isinstance(value, list):
            return [without_nulls(v) for v in value]
        return value
    return content_hash(without_nulls({"series": {k: v for k, v in series.items() if k != "points"}, "point": point}))


def traced_object_hashes(stage, accepted_semantic_keys=None):
    from stages.stage4_object_validation import object_key
    objects = [({}, item) for key in ("properties", "unresolved_properties", "specialized_property_observations")
               for item in stage.get(key, [])]
    objects.extend((series, point) for series in stage.get("property_series", []) for point in series.get("points", []))
    values = [_object_hash(series, point) for series, point in objects
              if accepted_semantic_keys is None or object_key(series, point) in accepted_semantic_keys]
    return sorted(set(values))


def verify_stage4r_lineage(stage0, stage2, stage3, stage4n, stage4t, merged, audit, file_hashes=None):
    result = {"verified": False, "basis": "unverified"}
    inputs = {"stage0": stage0, "stage2": stage2, "stage3": stage3, "stage4n": stage4n, "stage4t": stage4t}
    try:
        doc = stage0["document_id"]
        if not doc or any(x.get("document_id") != doc for x in [*inputs.values(), merged, audit]):
            return result
        if audit.get("stage") != "stage4r_unified_preview" or not audit.get("implementation_version"):
            return result
        if "input_content_hashes" in audit:
            if audit["input_content_hashes"] != {k: content_hash(v) for k, v in inputs.items()}:
                return result
            if audit.get("output_content_sha256") != content_hash(merged):
                return result
            basis = "canonical_content_chain"
        else:
            # Older R audits stored byte hashes and Pydantic's output serialization.
            names = {"stage0_blocks.json", "stage2_entities.json", "stage3_process.json", "stage4_properties.json", "stage4t_shadow.json"}
            if not file_hashes or set(audit.get("input_hashes", {})) != names:
                return result
            if any(audit["input_hashes"][k] != file_hashes.get(k) for k in names):
                return result
            from schema.polymer_schema import Stage4Document
            serialized = Stage4Document.model_validate(merged).model_dump_json()
            if audit.get("output_sha256") != hashlib.sha256(serialized.encode()).hexdigest():
                return result
            basis = "legacy_saved_file_chain"
        result.update(verified=True, basis=basis, implementation_version=audit["implementation_version"])
    except (KeyError, ValueError, TypeError, AttributeError):
        pass
    return result


def point_input_scope(series: dict, point: dict, proof: dict, *, dependencies_only=False):
    result = {"input_complete": False, "input_scope_basis": proof["basis"], "input_scope_reasons": list(proof["reasons"])}
    if not proof["verified"]:
        return result
    if not dependencies_only and "traced_object_hashes" in proof and _object_hash(series, point) not in proof["traced_object_hashes"]:
        result["input_scope_reasons"].append("record_not_in_traced_stage4n_output")
        return result
    if proof.get("semantic_scope") == "per_object" and not dependencies_only:
        from stages.stage4_object_validation import object_key
        accepted = (_object_hash(series, point) in proof["accepted_traced_object_hashes"]
                    if "accepted_traced_object_hashes" in proof
                    else object_key(series, point) in proof["object_semantic_audit"]["accepted_object_hashes"])
        if not accepted:
            result["input_scope_reasons"].append("stage4_object_semantic_validation_failed")
            return result
    blocks, unsupported_refs = set(), []
    def visit(value):
        if isinstance(value, dict):
            if value.get("block_id"):
                blocks.add(value["block_id"])
            for key, child in value.items():
                if key.endswith("evidence_ids") and child:
                    unsupported_refs.append(key)
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    # Sibling points are independent; series-level evidence and context are not.
    visit({k: v for k, v in series.items() if k != "points"})
    visit(point)
    result["input_dependency_block_ids"] = sorted(blocks)
    if unsupported_refs or not blocks or blocks - set(proof["selected_block_ids"]):
        result["input_scope_reasons"].append("point_input_dependencies_unverified")
        return result
    result["input_complete"] = True
    return result
