"""Run one named model against hash-locked Stage4 requests, without changing production."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import re
import time

import requests

from llm_client import LLMClient, load_pipeline_config, resolve_llm_config, resolve_pricing_config
from prompt_loader import RenderedPrompt
from stages.request_trace import content_hash
from stages.stage4_property import (run_stage4, load_property_vocabulary, DEFAULT_VOCABULARY_PATH,
                                   STAGE_ID, OUTPUT_SCHEMA_VERSION)
from stages.measurement_publication import build_measurement_publication


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def load_dataset(root):
    root = Path(root).resolve()
    manifest_path = root / "manifest.json"
    manifest = read(manifest_path)
    if manifest.get("schema_version") != "stage4_ab_dataset.v1":
        raise ValueError("Unsupported frozen dataset")
    hashes = {Path(p).resolve(): h for p, h in manifest["input_hashes"].items()}
    if any(not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != h for p, h in hashes.items()):
        raise ValueError("Frozen source changed")
    hashes[manifest_path] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    cases = []
    for entry in manifest["cases"]:
        path = (root / entry["path"]).resolve()
        if path.parent != root or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError("Frozen case changed or path is outside dataset")
        packet = read(path)
        if (packet["document_id"] != entry["document_id"] or packet["request_sha256"] != entry["request_sha256"]
                or content_hash(packet["request"]) != entry["request_sha256"]):
            raise ValueError("Frozen request changed")
        if not re.fullmatch(r"reference_no_\d+", packet["document_id"]):
            raise ValueError("Invalid document directory")
        hashes[path] = entry["sha256"]
        inputs = {}
        for name in ("stage0_blocks.json", "stage2_entities.json", "stage3_process.json"):
            matches = [p for p in hashes if p.name == name and read(p).get("document_id") == packet["document_id"]]
            if len(matches) != 1:
                raise ValueError("Frozen input path is not unique")
            inputs[name] = matches[0]
        cases.append((packet, inputs))
    if not cases or len({p[0]["document_id"] for p in cases}) != len(cases):
        raise ValueError("Empty or duplicate dataset")
    if any(not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != h for p, h in hashes.items()):
        raise ValueError("Frozen source changed")
    return cases, hashes


class FrozenClient(LLMClient):
    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, **kwargs)
        self.frozen_request = request
        self.request_count = 0
        self.elapsed_seconds = 0.0

    def call_json(self, system_prompt, user_message, *, max_tokens=4096):
        actual = dict(system_prompt=system_prompt, user_message=user_message, max_tokens=max_tokens)
        if content_hash(actual) != content_hash(self.frozen_request) or self.request_count:
            raise ValueError("Request must exactly match frozen input; no validation retries")
        self.request_count += 1
        started = time.monotonic()
        try:
            return super().call_json(system_prompt, user_message, max_tokens=max_tokens)
        finally:
            self.elapsed_seconds = time.monotonic() - started


def evaluate(directory, inputs):
    stage0, stage2, stage3 = [read(inputs[name]) for name in ("stage0_blocks.json", "stage2_entities.json", "stage3_process.json")]
    stage4, trace = read(directory / "stage4_properties.json"), read(directory / "stage4_request_trace.json")
    payload = {"document_id": stage4["document_id"], "polymer_entities": stage2.get("polymer_entities", []), "evidence": [],
               "samples": stage3.get("samples", []),
               "property_observations": stage4.get("properties", []), "unresolved_property_observations": stage4.get("unresolved_properties", []),
               "specialized_property_observations": stage4.get("specialized_property_observations", [])}
    publication = build_measurement_publication(payload, stage0=stage0, stage2=stage2, stage3=stage3,
                                               stage4=stage4, trace=trace)
    write(directory / "measurement_publication.json", publication)
    reasons = Counter(reason for status in ("candidate", "not_publishable") for group in publication[status]
                      for reason in group["publication_reasons"])
    binding = Counter((group.get("record") or {}).get("binding_status", "unavailable")
                      for status in ("final", "candidate", "not_publishable") for group in publication[status])
    return {"counts": publication["counts"], "binding_counts": dict(binding), "reason_counts": dict(reasons),
            "object_semantic_audit": {k: v for k, v in publication["series_input_proof"].get("object_semantic_audit", {}).items() if k != "rejected" and k != "accepted_object_hashes"},
            "input_proof_verified": publication["series_input_proof"]["verified"],
            "evaluation_scope": "Stage4 scalar and series claims only; no Stage5, no production replacement"}


def run(dataset, output_root, model, arm):
    cases, hashes = load_dataset(dataset)
    output_root = Path(output_root).resolve()
    if output_root.exists():
        raise ValueError("Output already exists")
    if any(output_root == p or output_root in p.parents or p.parent in output_root.parents for p in hashes):
        raise ValueError("Output must be separate from frozen inputs")
    config = load_pipeline_config()
    base = resolve_llm_config(config, STAGE_ID)
    resolved = replace(base, model=model, requested_model=model, max_retries=0)
    pricing = resolve_pricing_config(config, model) if model in config.get("pricing", {}).get("models", {}) else None
    vocabulary, vocabulary_hash = load_property_vocabulary(DEFAULT_VOCABULARY_PATH)
    code_root = Path(__file__).resolve().parents[1]
    rules = list((code_root / "stages").glob("*.py")) + list((code_root / "config").glob("*.v1.json")) + [Path(__file__).resolve()]
    rule_hashes = {str(p.relative_to(code_root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in rules}
    output_root.mkdir(parents=True)
    result = {"schema_version": "stage4_ab_run.v1", "arm": arm, "requested_model": model, "status": "running",
              "transport": {k: getattr(resolved, k) for k in ("api_format", "timeout_seconds", "max_retries", "stream", "thinking_effort")},
              "pricing_status": "configured" if pricing else "unknown", "input_hashes": {str(p): h for p, h in hashes.items()},
              "cases": [], "production_config_changed": False, "rule_hashes": rule_hashes}
    write(output_root / "summary.json", result)
    for packet, inputs in cases:
        directory = output_root / packet["document_id"]
        directory.mkdir()
        request = packet["request"]
        client = FrozenClient(resolved, pricing=pricing, request=request)
        prompt = RenderedPrompt("polymer.stage4.property", "frozen-ab", STAGE_ID, OUTPUT_SCHEMA_VERSION,
                                request["system_prompt"], hashlib.sha256(request["system_prompt"].encode()).hexdigest())
        row = {"document_id": packet["document_id"], "request_sha256": packet["request_sha256"], "status": "running"}
        result["cases"].append(row)
        write(output_root / "summary.json", result)
        print(json.dumps({"arm": arm, "document_id": packet["document_id"], "status": "started"}), flush=True)
        try:
            run_stage4(*(inputs[name] for name in ("stage0_blocks.json", "stage2_entities.json", "stage3_process.json")),
                       directory / "stage4_properties.json", client, prompt, vocabulary, vocabulary_hash,
                       max_tokens=request["max_tokens"], max_validation_retries=0, preview_relaxed=True)
            row.update(status="completed", evaluation=evaluate(directory, inputs))
        except Exception as exc:
            causes, current = [], exc
            while current is not None and len(causes) < 8:
                causes.append(current)
                current = current.__cause__
            row.update(status="failed", error_type=type(exc).__name__,
                       timeout=any(isinstance(e, requests.Timeout) for e in causes))
            match = re.search(r"HTTP (\d{3})", str(exc))
            if match:
                row["http_status"] = int(match.group(1))
        row.update(api_requests=client.request_count, elapsed_seconds=round(client.elapsed_seconds, 3))
        if client.last_raw_response is not None:
            raw = client.last_raw_response
            row.update(actual_model=raw.model, finish_reason=raw.finish_reason, usage=asdict(raw.usage),
                       cost=asdict(raw.cost) if raw.cost else None)
            write(directory / "raw_response.json", asdict(raw))
        write(directory / "case_result.json", row)
        write(output_root / "summary.json", result)
        print(json.dumps({"arm": arm, **{k: row[k] for k in ("document_id", "status", "error_type", "http_status") if k in row}}), flush=True)
    result.update(status="completed", api_requests=sum(r["api_requests"] for r in result["cases"]),
                  original_inputs_unchanged=all(hashlib.sha256(p.read_bytes()).hexdigest() == h for p, h in hashes.items()))
    result["rules_unchanged"] = rule_hashes == {str(p.relative_to(code_root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in rules}
    write(output_root / "summary.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--arm", choices=("A", "B"), required=True)
    run(**vars(parser.parse_args()))


if __name__ == "__main__":
    main()
