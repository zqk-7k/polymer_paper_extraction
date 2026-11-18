"""Freeze verified live Stage4 requests for identical-input model comparisons."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from stages.request_trace import content_hash
from stages.stage4_property import load_stage0_document, load_stage2_document, load_stage3_document
from tools.audit_stage4_request_trace import audit_trace


def freeze(cases, output_root):
    output_root = Path(output_root).resolve()
    if output_root.exists():
        raise ValueError("Output already exists")
    snapshots, packets, ids = {}, [], set()

    def read(path):
        path = Path(path).resolve()
        snapshots[path] = path.read_bytes()
        return json.loads(snapshots[path])

    for input_dir, stage4_dir in cases:
        input_dir, stage4_dir = Path(input_dir).resolve(), Path(stage4_dir).resolve()
        if any(root == output_root or root in output_root.parents or output_root in root.parents
               for root in (input_dir, stage4_dir)):
            raise ValueError("Output must be separate from inputs")
        inputs = {}
        for key, filename, loader in (("stage0", "stage0_blocks.json", load_stage0_document),
                                      ("stage2", "stage2_entities.json", load_stage2_document),
                                      ("stage3", "stage3_process.json", load_stage3_document)):
            read(input_dir / filename)
            inputs[key] = loader(input_dir / filename).model_dump(mode="json")
        trace = read(stage4_dir / "stage4_request_trace.json")
        output = read(stage4_dir / "stage4_properties.json")
        result = audit_trace(trace, inputs, output)
        if not result["historical_live_request_verified"] or not result["model_output_complete"]:
            raise ValueError("A/B baseline needs a verified complete live response")
        doc = trace["document_id"]
        if doc in ids:
            raise ValueError("Duplicate document")
        ids.add(doc)
        attempt = trace["attempts"][-1]
        # Whitelist application request fields; never copy client configuration.
        request = {key: attempt["request"][key] for key in ("system_prompt", "user_message", "max_tokens")}
        packets.append({"document_id": doc, "request": request, "request_sha256": content_hash(request),
                        "baseline": {"raw_response": attempt["raw_response"], "parsed_response": attempt["parsed_response"],
                                     "provenance": {key: output.get("provenance", {}).get(key)
                                                    for key in ("provider", "model", "usage", "cost", "status")}},
                        "trace_audit": result})
    if not packets or any(path.read_bytes() != content for path, content in snapshots.items()):
        raise ValueError("Empty dataset or changed input")
    output_root.mkdir(parents=True)
    files = []
    for index, packet in enumerate(packets, 1):
        path = output_root / f"case_{index:03d}.json"
        content = json.dumps(packet, ensure_ascii=False, indent=2).encode()
        path.write_bytes(content)
        files.append({"path": path.name, "document_id": packet["document_id"],
                      "sha256": hashlib.sha256(content).hexdigest(), "request_sha256": packet["request_sha256"]})
    manifest = {"schema_version": "stage4_ab_dataset.v1", "status": "awaiting_candidate_model", "cases": files,
                "input_hashes": {str(path): hashlib.sha256(content).hexdigest() for path, content in snapshots.items()},
                "api_requests": 0, "original_inputs_unchanged": True,
                "evaluation_contract": {"identical_request_required": True, "ground_truth_in_prompt": False,
                    "candidate_model": None, "required_metrics": ["deterministic_validation_pass_rate", "independent_sample_binding_accuracy",
                    "conflicting_binding_false_acceptance", "cost", "timeout_rate"],
                    "promotion_requires": "Independent reviewed labels, improved accuracy, no conflict-rate increase; small diagnostic dataset alone cannot authorize production replacement."}}
    (output_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", nargs=2, action="append", required=True, metavar=("INPUT_DIR", "STAGE4_DIR"))
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps({"cases": len(freeze(args.case, args.output_root)["cases"]), "api_requests": 0}))


if __name__ == "__main__":
    main()
