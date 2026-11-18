"""Build article-local catalogs, source packets and resumable binding review sidecars.

Default is dry-run (no LLM). --execute enables bounded model calls. Original
batch files and the standard spreadsheet are never rewritten.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

EXTRACTION_ROOT = Path(__file__).resolve().parents[1]
if str(EXTRACTION_ROOT) not in sys.path:
    sys.path.insert(0, str(EXTRACTION_ROOT))

from llm_client import DEFAULT_CONFIG_PATH, LLMClient, LLMConfigurationError, load_pipeline_config
from stages.sample_catalog import build_catalog, digest, source_index
from stages.subject_lineage import audit_lineage, build_lineage, subject_chain
from stages.sample_binding import (BINDING_VERSION, BindingReview, STAGE4_FILES, build_packet, collect_candidates, deterministic_review, validate_review)

PROMPT_VERSION = "sample_binding_review.v3"
INPUT_FILES = ("stage0_blocks.json", "stage1_mentions.json", "stage2_entities.json", "stage3_process.json", *STAGE4_FILES, "stage4t_shadow.json", "stage5_characterizations.json", "candidate.json", "final.json")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str), encoding="utf-8")
    temp.replace(path)


def write_jsonl(path: Path, values: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text("".join(json.dumps(x, ensure_ascii=False, sort_keys=True, default=str) + "\n" for x in values), encoding="utf-8")
    temp.replace(path)


def load_document(source: Path) -> tuple[dict, dict, list[dict]]:
    files = {name: read_json(source / name) for name in INPUT_FILES if (source / name).is_file()}
    for required in ("stage0_blocks.json", "stage3_process.json"):
        if required not in files:
            raise ValueError(f"Missing input: {source / required}")
    doc_ids = {v.get("document_id") for v in files.values() if isinstance(v, dict) and v.get("document_id")}
    if len(doc_ids) > 1:
        raise ValueError("Cross-document inputs cannot share entity or sample identifiers")
    catalog = build_catalog(files["stage0_blocks.json"], files["stage3_process.json"])
    candidates = collect_candidates(files, catalog["document_id"])
    indexes = source_index(files["stage0_blocks.json"])
    source_hash = digest(files["stage0_blocks.json"])
    packets = [build_packet(c, files["stage0_blocks.json"], catalog, indexes=indexes, source_hash=source_hash) for c in candidates]
    lineage = build_lineage(files.get("stage2_entities.json"), files["stage3_process.json"])
    for packet in packets:
        packet["stage2_entities"] = list(lineage["entities"].values())
        packet["stage2_available"] = lineage["stage2_available"]
        packet["stage2_sha256"] = digest(files.get("stage2_entities.json"))
        packet["subject_chain"] = subject_chain(packet["candidate"], lineage)
        packet["sample_chains"] = {sample["sample_id"]: subject_chain({"sample_ids": sample["legacy_sample_ids"]}, lineage) for sample in catalog["samples"]}
        packet["process_steps"] = list(lineage["process_steps"].values())
        packet["failure_reasons"] = sorted(set(packet["failure_reasons"] + packet["subject_chain"]["errors"]))
        packet.pop("input_sha256")
        packet["input_sha256"] = digest(packet)
    return files, catalog, packets


def render_prompt() -> str:
    text = (EXTRACTION_ROOT / "prompts/sample_binding_review.md").read_text(encoding="utf-8")
    return text.split("---", 2)[-1].strip().replace("{{OUTPUT_SCHEMA}}", json.dumps(BindingReview.model_json_schema(), ensure_ascii=False))


def api_failure_details(exc: Exception) -> dict:
    """Expose transport categories without logging URLs, payloads or credentials."""
    seen, current = set(), exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, requests.RequestException):
            return {"api_failure": True, "api_error_category": type(current).__name__}
        status = re.search(r"\bHTTP\s+(\d{3})\b", str(current))
        if status:
            return {"api_failure": True, "api_error_category": "http_error",
                    "http_status": int(status[1])}
        current = current.__cause__ or current.__context__
    return {"api_failure": False}


def review_packet(packet: dict, *, client: Any = None, execute: bool = False, cache_dir: Path,
                  config_hash: str, prompt: str, max_tokens: int = 4096, force_llm: bool = False,
                  request_allowed: bool = True) -> dict:
    baseline = validate_review(deterministic_review(packet), packet, allow_inherited=False)
    required = baseline["reasoning_status"] != "accepted" or "candidate_sample_conflict" in packet["failure_reasons"]
    key = digest({"input": packet["input_sha256"], "prompt": digest(prompt), "config": config_hash, "version": BINDING_VERSION})
    metadata = {"review_id": packet["review_id"], "property_id": packet["property_id"], "input_sha256": packet["input_sha256"],
                "catalog_sha256": packet["catalog_sha256"], "prompt_version": PROMPT_VERSION, "prompt_sha256": digest(prompt),
                "config_hash": config_hash, "cache_key": key, "review_required": required,
                "request_count": 0, "cache_hit_count": 0, "usage": {}, "cost": None, "review_model": None}
    if not required and not force_llm:
        return {**metadata, "review_method": "deterministic", "source_reasoning_status": "not_reviewed", "raw_review": deterministic_review(packet), "validated_review": baseline}
    if not execute:
        return {**metadata, "review_method": "not_reviewed", "source_reasoning_status": "not_reviewed", "raw_review": None,
                "validated_review": {"reasoning_status": "not_verifiable", "selected_sample_id": None, "validation_passed": False, "validation_errors": ["review_required"], "binding_status": "unresolved"}}
    cache_path = cache_dir / (key + ".json")
    if cache_path.is_file():
        cached = read_json(cache_path)
        if cached.get("cache_key") == key and cached.get("input_sha256") == packet["input_sha256"]:
            checked = validate_review(cached.get("raw_review"), packet)
            if checked["validation_passed"]:
                return {**cached, "validated_review": checked, "request_count": 0, "cache_hit_count": 1, "usage": {}, "cost": None}
    if not request_allowed:
        return {**metadata, "review_method": "not_reviewed", "source_reasoning_status": "not_reviewed", "raw_review": None,
                "validated_review": {"reasoning_status": "not_verifiable", "selected_sample_id": None,
                                     "validation_passed": False, "validation_errors": ["request_budget_exhausted"], "binding_status": "unresolved"}}
    result = {**metadata, "review_method": "llm", "request_count": 1, "raw_review": None}
    try:
        model_input = {k: v for k, v in packet.items() if k not in {"original_candidate", "candidate", "source_file", "source_collection"}}
        response = client.call_json(prompt, json.dumps(model_input, ensure_ascii=False), max_tokens=max_tokens)
        result.update(review_model=response.model, usage=asdict(response.usage), cost=asdict(response.cost) if response.cost else None)
        parsed = response.parsed_json
        raw = getattr(client, "last_raw_response", None)
        result["raw_response"] = getattr(raw, "content", None)
        if parsed and (parsed.prefix_text.strip() or parsed.trailing_text.strip() or parsed.parse_source not in {"direct", "raw"}):
            raise ValueError("extra_text_or_markdown")
        if raw and raw.finish_reason in {"length", "max_tokens"}:
            raise ValueError("truncated_output")
        if raw and raw.content is not None:
            # Do not accept a permissive parser's repair of malformed model JSON.
            if json.loads(raw.content) != response.data:
                raise ValueError("raw_json_mismatch")
        result["raw_review"] = response.data
        result["validated_review"] = validate_review(response.data, packet)
    except Exception as exc:
        # Record a category only; API errors may contain transport credentials/URLs.
        result["error_type"] = type(exc).__name__
        result.update(api_failure_details(exc))
        result["validated_review"] = {"reasoning_status": "not_verifiable", "selected_sample_id": None, "validation_passed": False, "validation_errors": ["llm_or_schema_failure"], "binding_status": "unresolved"}
    result["source_reasoning_status"] = result["validated_review"]["reasoning_status"]
    if result["validated_review"]["validation_passed"]:
        write_json(cache_path, result)
    return result


def process_document(source: Path, output: Path, *, execute: bool = False, client: Any = None,
                     config_hash: str = "offline", max_requests: int = 20, positive_samples: int = 0,
                     max_tokens: int = 4096) -> dict:
    source, output = source.resolve(), output.resolve()
    if output == source or source in output.parents:
        raise ValueError("Review output must be outside the original document directory")
    files, catalog, packets = load_document(source)
    chain_audit = audit_lineage(files)
    write_json(output / "subject_lineage_audit.json", chain_audit)
    write_json(output / "stage3_sample_catalog.json", catalog)
    write_jsonl(output / "sample_binding_evidence_packets.jsonl", packets)
    prompt = render_prompt()
    results, requests = [], 0
    api_blocked = False
    def priority(packet):
        status = packet["deterministic_binding"]["sample_binding_status"]
        if status == "ambiguous":
            rank = 0
        elif status in {"unresolved", "group_only"} and packet["source_evidence"]:
            rank = 1
        elif "candidate_sample_conflict" in packet["failure_reasons"]:
            rank = 2
        elif status == "resolved":
            rank = 3
        else:
            rank = 4
        return rank, packet["review_id"]
    positive_ids = set()
    for packet in sorted(packets, key=lambda p: p["review_id"]):
        if len(positive_ids) >= positive_samples:
            break
        if validate_review(deterministic_review(packet), packet, allow_inherited=False)["reasoning_status"] == "accepted":
            positive_ids.add(packet["review_id"])
    for packet in sorted(packets, key=lambda p: (p["review_id"] not in positive_ids, priority(p))):
        positive = packet["review_id"] in positive_ids
        result = review_packet(packet, client=client, execute=execute, cache_dir=output / "cache",
                               config_hash=config_hash, prompt=prompt, max_tokens=max_tokens, force_llm=positive,
                               request_allowed=requests < max_requests and not api_blocked)
        if api_blocked and result["review_method"] == "not_reviewed":
            result["validated_review"]["validation_errors"] = ["api_circuit_open"]
        api_blocked = api_blocked or bool(result.get("api_failure"))
        result["positive_control"] = positive
        requests += result["request_count"]
        results.append(result)
        # Checkpoint every completed review, including failures and dry-run queue entries.
        if result["request_count"]:
            write_jsonl(output / "source_reasoning_review.jsonl", results)
    write_jsonl(output / "source_reasoning_review.jsonl", results)
    counts = Counter(x["validated_review"]["reasoning_status"] for x in results)
    summary = {"schema_version": BINDING_VERSION, "batch_id": source.parent.name, "document_id": catalog["document_id"],
               "source_dir": str(source), "run_mode": "execute" if execute else "dry_run", "created_at": datetime.now(timezone.utc).isoformat(),
               "input_sha256": digest({k: digest(v) for k, v in files.items()}), "input_file_hashes": {k: digest(v) for k, v in files.items()},
               "catalog_sha256": catalog["catalog_sha256"], "prompt_version": PROMPT_VERSION, "prompt_sha256": digest(prompt), "config_hash": config_hash,
               "sample_count": len(catalog["samples"]), "candidate_count": len(packets), "value_retained_count": len(results),
               "subject_chain_status_counts": chain_audit["observation_status_counts"],
               "lineage_reference_error_count": len(chain_audit["reference_errors"]),
               "request_count": requests, "api_blocked": api_blocked,
               "api_failure_count": sum(bool(x.get("api_failure")) for x in results),
               "success_count": sum(x["request_count"] and x["validated_review"]["validation_passed"] for x in results),
               "failure_count": sum(x["request_count"] and not x["validated_review"]["validation_passed"] for x in results),
               "cache_hit_count": sum(x["cache_hit_count"] for x in results), "review_status_counts": dict(counts),
               "deterministic_binding_counts": dict(Counter(p["deterministic_binding"]["sample_binding_status"] for p in packets)),
               "sample_unique_binding_rate": sum(x["validated_review"]["reasoning_status"] == "accepted" for x in results) / len(results) if results else None,
               "source_reasoning_accepted_rate": sum(x["review_method"] == "llm" and x["validated_review"]["reasoning_status"] == "accepted" for x in results) / sum(x["review_method"] == "llm" for x in results) if any(x["review_method"] == "llm" for x in results) else None,
               "failure_reason_counts": dict(Counter(r for p in packets for r in p["failure_reasons"])),
               "models": sorted({x["review_model"] for x in results if x["review_model"]}),
               "token_usage": {k: sum(x["usage"].get(k, 0) for x in results) for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")},
               "estimated_cost": str(sum(float((x.get("cost") or {}).get("total_cost", 0)) for x in results)),
               "metrics_scope": "process candidates, not standard records; no standard-set denominator"}
    write_json(output / "source_reasoning_manifest.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--ref-no", action="append")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--max-requests", type=int, default=20, help="Total request budget across selected documents")
    parser.add_argument("--max-requests-per-document", type=int, default=None,
                        help="Optional request budget applied independently to each document")
    parser.add_argument("--positive-samples", type=int, default=0)
    parser.add_argument("--document-workers", type=int, default=1,
                        help="文献级并发数；每篇仍使用独立预算和独立缓存")
    args = parser.parse_args()
    if args.max_requests < 0 or args.positive_samples < 0 or args.document_workers < 1 or (args.max_requests_per_document is not None and args.max_requests_per_document < 0):
        parser.error("Request/sample budgets must be nonnegative")
    config = load_pipeline_config(args.config)
    settings = config.get("stages", {}).get("sample_binding_review", {})
    # Config contains no secrets (credentials are environment variables); only its hash is persisted.
    config_hash = digest(config)
    refs = [r if r.startswith("reference_no_") else "reference_no_" + r for r in args.ref_no or []]
    dirs = [args.batch_dir / r for r in refs] if refs else sorted(p.parent for p in args.batch_dir.glob("reference_no_*/stage3_process.json"))
    if not dirs:
        parser.error("No document directories found")
    allocations, budget = [], args.max_requests
    for index, source in enumerate(dirs):
        fair_share = (budget + len(dirs) - index - 1) // (len(dirs) - index)
        document_budget = fair_share if args.max_requests_per_document is None else min(fair_share, args.max_requests_per_document)
        allocations.append(document_budget)
        budget -= document_budget

    def run_one(index: int):
        source, document_budget = dirs[index], allocations[index]
        try:
            client = LLMClient.from_pipeline_config(stage="sample_binding_review", config_path=args.config) if args.execute else None
            summary = process_document(source, args.output_dir / source.name, execute=args.execute, client=client, config_hash=config_hash,
                                       max_requests=document_budget, positive_samples=args.positive_samples, max_tokens=int(settings.get("max_tokens", 4096)))
            return index, summary, None
        except Exception as exc:
            return index, None, {"document_id": source.name, "error_type": type(exc).__name__}

    summaries_by_index, failures = {}, []
    if args.document_workers == 1:
        results = []
        for index in range(len(dirs)):
            result = run_one(index)
            results.append(result)
            if result[1] and result[1].get("api_blocked"):
                break
    else:
        with ThreadPoolExecutor(max_workers=min(args.document_workers, len(dirs))) as pool:
            futures = [pool.submit(run_one, index) for index in range(len(dirs))]
            results = [future.result() for future in as_completed(futures)]
    for index, summary, failure in sorted(results, key=lambda item: item[0]):
        if failure:
            failures.append(failure)
            print(f"[failed] {dirs[index].name}: {failure['error_type']}", file=sys.stderr)
            continue
        summaries_by_index[index] = summary
        print(json.dumps({k: summary[k] for k in ("document_id", "candidate_count", "request_count", "review_status_counts")}, ensure_ascii=False))
        if summary.get("api_blocked"):
            failures.append({"document_id": dirs[index].name, "error_type": "api_circuit_open"})
    summaries = [summaries_by_index[index] for index in sorted(summaries_by_index)]
    not_started = []
    for index in range(len(dirs)):
        if index not in summaries_by_index and not any(f["document_id"] == dirs[index].name for f in failures):
            not_started.append(dirs[index].name)
    write_json(args.output_dir / "sample_binding_reasoning_summary.json", {"documents": summaries, "failures": failures,
               "not_started_documents": not_started,
               "total_request_budget": args.max_requests, "max_requests_per_document": args.max_requests_per_document,
               "document_workers": args.document_workers,
               "request_count": sum(x["request_count"] for x in summaries), "value_retained_count": sum(x["value_retained_count"] for x in summaries)})
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
