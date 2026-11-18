"""Verify a captured Stage4 request against loaded inputs, without model calls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from stages.request_trace import content_hash
from stages.stage4_property import load_stage0_document, load_stage2_document, load_stage3_document, _element_source_text


def _section(message: str, name: str):
    marker = f"--- BEGIN UNTRUSTED {name} ---\n"
    start = message.index(marker) + len(marker)
    value, end = json.JSONDecoder().raw_decode(message[start:])
    if not message[start + end:].startswith(f"\n--- END UNTRUSTED {name} ---"):
        raise ValueError("Invalid request section boundary")
    return value


def audit_trace(trace: dict | None, inputs: dict, output: dict | None = None) -> dict:
    result = {"schema_version": "stage4_request_trace_audit.v1", "integrity_verified": False,
              "historical_live_request_verified": False, "model_output_complete": False, "publication_status_changed": False,
              "reasons": [], "attempts": []}
    reasons = result["reasons"]
    if trace is None:
        reasons.append("request_trace_missing")
        return result
    result.update(document_id=trace.get("document_id"), mode=trace.get("mode"), trace_id=trace.get("trace_id"))
    if trace.get("schema_version") != "stage4_request_trace.v1":
        reasons.append("trace_schema_unknown")
    for name, value in inputs.items():
        if trace.get("input_model_hashes", {}).get(name) != content_hash(value):
            reasons.append(f"{name}_input_hash_mismatch")
        if value.get("document_id") != trace.get("document_id"):
            reasons.append(f"{name}_document_mismatch")
    if set(inputs) != {"stage0", "stage2", "stage3"}:
        reasons.append("required_inputs_missing")
    if output is None:
        reasons.append("stage4_output_missing")
    elif trace.get("output_sha256") != content_hash(output):
        reasons.append("stage4_output_hash_mismatch")
    if trace.get("status") != "completed":
        reasons.append("trace_not_completed")
    attempts = trace.get("attempts") or []
    if not attempts:
        reasons.append("trace_has_no_requests")
    for index, attempt in enumerate(attempts, 1):
        if attempt.get("attempt") != index:
            reasons.append("attempt_sequence_invalid")
        if attempt.get("request_sha256") != content_hash(attempt.get("request")):
            reasons.append(f"attempt_{index}_request_hash_mismatch")
        for field in ("parsed_response", "raw_response"):
            if field in attempt and attempt.get(field + "_sha256") != content_hash(attempt[field]):
                reasons.append(f"attempt_{index}_{field}_hash_mismatch")
    if reasons:
        return result
    result["integrity_verified"] = True
    # Receiving a truncated response still proves which request produced it.
    # Request linkage and output completeness are separate facts.
    result["historical_live_request_verified"] = trace.get("mode") == "live" and all(
        a.get("raw_response") for a in attempts)
    result["model_output_complete"] = (
        attempts[-1].get("status") == "response_received" and "parsed_response" in attempts[-1]
        and (attempts[-1].get("raw_response") or {}).get("finish_reason") not in {"max_tokens", "length"}
    )
    source = inputs["stage0"]
    from schema.polymer_schema import Stage0Element
    expected_blocks = {b["block_id"]: b for b in source.get("elements", [])}
    for attempt in attempts:
        row = {"attempt": attempt["attempt"], "status": attempt["status"],
               "error_type": attempt.get("error_type"), "finish_reason": (attempt.get("raw_response") or {}).get("finish_reason"),
               "omitted_blocks": [], "altered_blocks": [], "missing_sample_fields": [], "missing_process_fields": []}
        try:
            message = attempt["request"]["user_message"]
            name = "FULL ARTICLE BLOCKS" if "--- BEGIN UNTRUSTED FULL ARTICLE BLOCKS ---\n" in message else "METHODS AND RESULTS BLOCKS"
            blocks = _section(message, name)
            process = _section(message, "SAMPLES AND PROCESS")
            actual = {b["block_id"]: b for b in blocks}
            row["duplicate_block_ids"] = len(actual) != len(blocks)
            row["unknown_block_ids"] = sorted(set(actual) - set(expected_blocks))
            for bid, block in expected_blocks.items():
                if bid not in actual:
                    row["omitted_blocks"].append({"block_id": bid, "type": block["type"], "section": block.get("section")})
                elif actual[bid].get("source_text") != _element_source_text(Stage0Element.model_validate(block)):
                    row["altered_blocks"].append(bid)
            row["omitted_table_ids"] = [b["block_id"] for b in row["omitted_blocks"] if b["type"] == "table"]
            for collection, id_field, fields, report_field in (
                ("samples", "sample_id", ("sample_label_raw", "state_description", "evidence"), "missing_sample_fields"),
                ("process_steps", "step_id", ("parameters", "evidence"), "missing_process_fields"),
            ):
                actual_items = {item[id_field]: item for item in process.get(collection, [])}
                for item in inputs["stage3"].get(collection, []):
                    for field in fields:
                        expected = item.get(field)
                        if field == "evidence" and isinstance(expected, dict):
                            expected = {k: v for k, v in expected.items() if v is not None}
                        if expected is not None and actual_items.get(item[id_field], {}).get(field) != expected:
                            row[report_field].append({id_field: item[id_field], "field": field})
        except (ValueError, KeyError, TypeError):
            row["request_format_unrecognized"] = True
        result["attempts"].append(row)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--stage4-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Report already exists")
    inputs = {name: loader(args.input_dir / filename).model_dump(mode="json") for name, loader, filename in (
        ("stage0", load_stage0_document, "stage0_blocks.json"),
        ("stage2", load_stage2_document, "stage2_entities.json"),
        ("stage3", load_stage3_document, "stage3_process.json"),
    )}
    trace_path = args.stage4_dir / "stage4_request_trace.json"
    output_path = args.stage4_dir / "stage4_properties.json"
    read = lambda path: json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    result = audit_trace(read(trace_path), inputs, read(output_path))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("integrity_verified", "historical_live_request_verified", "reasons")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
