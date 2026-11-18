"""Stratified human review packets and evaluation with explicit, adjudicated labels."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
import json

from tools.review_sample_binding_llm import read_json, write_json, write_jsonl
from stages.sample_binding import deterministic_review, validate_review
from stages.sample_catalog import digest


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def evaluate_gold(labels: list[dict], reviews: list[dict]) -> dict:
    predictions = {r["review_id"]: r for r in reviews}
    completed = [label for label in labels if label.get("adjudicated") is True and label.get("annotator") and label.get("expected_status") in {"accepted", "rejected", "ambiguous", "not_verifiable"}]
    if len({label["review_id"] for label in completed}) != len(completed):
        raise ValueError("Duplicate adjudicated review_id")
    tp = fp = fn = correct = evaluated = 0
    for label in completed:
        row = predictions.get(label["review_id"])
        if row is None or row.get("input_sha256") != label.get("input_sha256"):
            raise ValueError("Human labels refer to missing or changed evidence")
        predicted = row["validated_review"]
        if label["expected_status"] == "accepted" and not label.get("expected_sample_id"):
            raise ValueError("Accepted gold label requires a sample ID")
        accepted = predicted["reasoning_status"] == "accepted"
        positive = label["expected_status"] == "accepted"
        match = accepted and positive and predicted.get("selected_sample_id") == label["expected_sample_id"]
        tp += match
        fp += accepted and not match
        fn += positive and not match
        correct += predicted["reasoning_status"] == label["expected_status"] and (not positive or match)
        evaluated += 1
    return {"label_count": len(labels), "adjudicated_count": evaluated, "pending_count": len(labels) - evaluated,
            "precision": tp / (tp + fp) if tp + fp else None, "recall": tp / (tp + fn) if tp + fn else None,
            "status_accuracy": correct / evaluated if evaluated else None, "false_accept_count": fp if evaluated else None,
            "metrics_status": "human_adjudicated_subset" if evaluated else "awaiting_human_labels"}


def verify_inputs(summaries: list[dict]) -> dict:
    checked, mismatches = 0, []
    for doc in summaries:
        source = Path(doc["source_dir"])
        groups = [(source, doc["input_file_hashes"])]
        manifest_path = source / "lineage_enrichment_manifest.json"
        if manifest_path.is_file():
            manifest = read_json(manifest_path)
            groups.append((Path(manifest["source_dir"]), manifest["original_hashes"]))
        for directory, hashes in groups:
            for name, expected in hashes.items():
                path = directory / name
                checked += 1
                if not path.is_file() or digest(read_json(path)) != expected:
                    mismatches.append(str(path))
    return {"checked_file_count": checked, "mismatches": mismatches}


def build_report(review_dir: Path, output: Path, *, per_stratum: int = 3, gold: Path | None = None):
    output.mkdir(parents=True, exist_ok=True)
    summaries = read_json(review_dir / "sample_binding_reasoning_summary.json")
    annotation, all_reviews, report = [], [], []
    for doc in summaries["documents"]:
        directory = review_dir / doc["document_id"]
        packets = {row["review_id"]: row for row in read_jsonl(directory / "sample_binding_evidence_packets.jsonl")}
        reviews = read_jsonl(directory / "source_reasoning_review.jsonl")
        all_reviews.extend(reviews)
        strata = defaultdict(list)
        for row in reviews:
            p = packets[row["review_id"]]
            if row["review_method"] == "llm":
                kind = "llm_" + row["validated_review"]["reasoning_status"]
            elif p.get("subject_chain", {}).get("status") in {"conflict", "entity_unlinked"}:
                kind = "incomplete_entity_chain"
            else:
                kind = "deterministic_" + row["validated_review"]["reasoning_status"]
            strata[kind].append(row)
        for kind, rows in sorted(strata.items()):
            # One source location per stratum, avoiding repeated Candidate/Final copies.
            seen = set()
            for row in sorted(rows, key=lambda r: r["review_id"]):
                packet = packets[row["review_id"]]
                source_key = json.dumps([packet["value_raw"], packet["property_name"], packet["evidence_paths"], packet["source_block_ids"]], sort_keys=True)
                if source_key in seen:
                    continue
                seen.add(source_key)
                annotation.append({"document_id": doc["document_id"], "review_id": row["review_id"], "input_sha256": packet["input_sha256"],
                    "stratum": kind, "property_name": packet["property_name"], "value_raw": packet["value_raw"],
                    "evidence_paths": packet["evidence_paths"], "source_evidence": packet["source_evidence"],
                    "stage2_entities": packet.get("stage2_entities", []), "stage3_samples": packet["stage3_samples"],
                    "process_steps": packet.get("process_steps", []), "expected_status": None, "expected_sample_id": None,
                    "annotator": None, "adjudicated": False, "notes": ""})
                if len(seen) >= per_stratum:
                    break
        llm = [r for r in reviews if r["review_method"] == "llm"]
        newly_accepted = [r["review_id"] for r in llm if r["validated_review"]["reasoning_status"] == "accepted"
                          and validate_review(deterministic_review(packets[r["review_id"]]), packets[r["review_id"]], allow_inherited=False)["reasoning_status"] != "accepted"]
        report.append({"document_id": doc["document_id"], "candidate_count": len(reviews),
                       "request_count": doc["request_count"], "cache_hits": doc["cache_hit_count"],
                       "statuses": doc["review_status_counts"],
                       "llm_statuses": dict(Counter(r["validated_review"]["reasoning_status"] for r in llm)),
                       "positive_control_count": sum(bool(r.get("positive_control")) for r in llm),
                       "llm_newly_accepted_review_ids": newly_accepted,
                       "validation_errors": dict(Counter(error for r in llm for error in r["validated_review"].get("validation_errors", []))),
                       "chain_counts": doc.get("subject_chain_status_counts", {}),
                       "reference_error_count": doc.get("lineage_reference_error_count", 0)})
    queue_path = output / "human_review_queue.jsonl"
    labels = read_jsonl(gold) if gold else read_jsonl(queue_path) if queue_path.exists() else annotation
    # Human work is never overwritten when regenerating an evaluation report.
    if not queue_path.exists():
        write_jsonl(queue_path, annotation)
    metrics = evaluate_gold(labels, all_reviews)
    write_json(output / "evaluation.json", {"documents": report, "human_metrics": metrics,
        "input_integrity": verify_inputs(summaries["documents"]),
        "source_dir": str(review_dir.resolve()), "scope": "stratified source candidates; not a population accuracy estimate"})
    return report, metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--gold", type=Path)
    args = parser.parse_args()
    _, metrics = build_report(args.review_dir, args.output_dir, gold=args.gold)
    print(json.dumps(metrics, ensure_ascii=False))


if __name__ == "__main__":
    main()
