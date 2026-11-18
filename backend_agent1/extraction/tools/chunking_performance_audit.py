# -*- coding: utf-8 -*-
"""Audit Stage1 chunk boundaries, evidence spans, and recorded parallelism."""
from __future__ import annotations

import argparse
import json
import os
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from stages.stage1_material_mention import (
    DEFAULT_FALLBACK_SECTIONS,
    DEFAULT_PRIMARY_SECTIONS,
    chunk_blocks,
    load_stage0_document,
    select_input_blocks,
)


def _collect_block_ids(value: Any) -> set[str]:
    ids: set[str] = set()

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            block_id = item.get("block_id")
            if isinstance(block_id, str) and block_id:
                ids.add(block_id)
            for child in item.values():
                if isinstance(child, (dict, list)):
                    walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)
    return ids


def _iter_evidence_objects(payload: dict[str, Any]):
    """Yield list objects that carry evidence, including nested series points."""
    def walk(value: Any):
        if isinstance(value, dict):
            if "evidence" in value or "evidence_ids" in value:
                yield value
            for child in value.values():
                if isinstance(child, (dict, list)):
                    yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)

    yield from walk(payload)


def _stage1_chunk_audit(doc_dir: Path, max_chunk_chars: int) -> dict[str, Any]:
    stage0_path = doc_dir / "stage0_blocks.json"
    stage1_path = doc_dir / "stage1_mentions.json"
    document = load_stage0_document(stage0_path)
    blocks, selection_warnings = select_input_blocks(
        document, DEFAULT_PRIMARY_SECTIONS, DEFAULT_FALLBACK_SECTIONS
    )
    chunks = chunk_blocks(blocks, max_chunk_chars)
    block_chunks = {
        block.block_id: index
        for index, chunk in enumerate(chunks, start=1)
        for block in chunk
    }
    chunk_sizes = [sum(len(block.text or "") + 160 for block in chunk) for chunk in chunks]
    edge_pairs = [
        f"{left[-1].type}->{right[0].type}"
        for left, right in zip(chunks, chunks[1:])
    ]
    table_edge_count = sum(
        1
        for chunk in chunks
        if chunk and (chunk[0].type == "table" or chunk[-1].type == "table")
    )
    title_edge_count = sum(
        1
        for chunk in chunks
        if chunk and (chunk[0].type == "title" or chunk[-1].type == "title")
    )

    evidence_objects = 0
    cross_chunk_objects = 0
    evidence_spans: list[int] = []
    if stage1_path.is_file():
        payload = json.loads(stage1_path.read_text(encoding="utf-8-sig"))
        for obj in _iter_evidence_objects(payload):
            object_chunks = {
                block_chunks[block_id]
                for block_id in _collect_block_ids(obj.get("evidence"))
                if block_id in block_chunks
            }
            if not object_chunks:
                continue
            evidence_objects += 1
            span = len(object_chunks)
            evidence_spans.append(span)
            if span > 1:
                cross_chunk_objects += 1

    stage4t = {}
    stage4t_path = doc_dir / "stage4t_shadow.json"
    if stage4t_path.is_file():
        stage4t = json.loads(stage4t_path.read_text(encoding="utf-8-sig"))
    interpretation = stage4t.get("interpretation_summary") or {}

    stage1 = {}
    stage1_path = doc_dir / "stage1_mentions.json"
    if stage1_path.is_file():
        stage1 = json.loads(stage1_path.read_text(encoding="utf-8-sig"))
    stage1_usage = (stage1.get("provenance") or {}).get("usage") or {}

    stage5 = {}
    stage5_path = doc_dir / "stage5_shards.json"
    if stage5_path.is_file():
        stage5 = json.loads(stage5_path.read_text(encoding="utf-8-sig"))
    shards = [shard for shard in stage5.get("shards") or [] if shard.get("duration_seconds") is not None]
    durations = [float(shard["duration_seconds"]) for shard in shards]
    intervals = [
        (float(shard["started_at"]), float(shard.get("ended_at") or shard["started_at"]))
        for shard in shards
        if shard.get("started_at") is not None
    ]
    wall_seconds = None
    if intervals:
        wall_seconds = max(end for _, end in intervals) - min(start for start, _ in intervals)

    return {
        "document_id": document.document_id,
        "block_count": len(blocks),
        "chunk_count": len(chunks),
        "chunk_sizes": chunk_sizes,
        "chunk_size_min": min(chunk_sizes) if chunk_sizes else 0,
        "chunk_size_max": max(chunk_sizes) if chunk_sizes else 0,
        "edge_pairs": dict(Counter(edge_pairs)),
        "table_edge_chunk_count": table_edge_count,
        "title_edge_chunk_count": title_edge_count,
        "selection_warning_count": len(selection_warnings),
        "stage1_input_tokens": stage1_usage.get("input_tokens", 0),
        "stage1_output_tokens": stage1_usage.get("output_tokens", 0),
        "stage1_total_tokens": stage1_usage.get("total_tokens", 0),
        "evidence_object_count": evidence_objects,
        "cross_chunk_evidence_object_count": cross_chunk_objects,
        "cross_chunk_evidence_rate": (
            cross_chunk_objects / evidence_objects if evidence_objects else 0.0
        ),
        "evidence_span_max": max(evidence_spans) if evidence_spans else 0,
        "stage4t_table_workers": (stage4t.get("table_workers") or 1),
        "stage4t_routed_table_count": interpretation.get("routed_table_count", 0),
        "stage4t_fallback_count": interpretation.get("fallback_count", 0),
        "stage4t_interpretation_seconds": interpretation.get("interpretation_duration_seconds", 0.0),
        "stage5_shard_count": len(stage5.get("shards") or []),
        "stage5_shard_workers": (stage5.get("parallelism") or {}).get("effective_workers", 1),
        "stage5_shard_duration_sum_seconds": sum(durations),
        "stage5_shard_wall_seconds": wall_seconds,
        "stage5_parallelism_ratio": (
            sum(durations) / wall_seconds if wall_seconds and wall_seconds > 0 else 1.0
        ),
    }


def audit_batch(batch_dir: str | Path, max_chunk_chars: int = 8000) -> list[dict[str, Any]]:
    root = Path(batch_dir)
    rows = []
    for doc_dir in sorted(root.glob("reference_no_*")):
        if not doc_dir.is_dir() or not (doc_dir / "stage0_blocks.json").is_file():
            continue
        rows.append(_stage1_chunk_audit(doc_dir, max_chunk_chars))
    return rows


def build_summary(rows: list[dict[str, Any]], max_chunk_chars: int) -> dict[str, Any]:
    chunk_sizes = [size for row in rows for size in row["chunk_sizes"]]
    evidence_objects = sum(row["evidence_object_count"] for row in rows)
    cross_chunk = sum(row["cross_chunk_evidence_object_count"] for row in rows)
    return {
        "schema_version": "chunking_performance_audit.v1",
        "max_chunk_chars": max_chunk_chars,
        "documents": len(rows),
        "total_blocks": sum(row["block_count"] for row in rows),
        "total_chunks": sum(row["chunk_count"] for row in rows),
        "chunk_count_distribution": dict(sorted(Counter(row["chunk_count"] for row in rows).items())),
        "chunk_size_min": min(chunk_sizes) if chunk_sizes else 0,
        "chunk_size_max": max(chunk_sizes) if chunk_sizes else 0,
        "chunk_size_median": statistics.median(chunk_sizes) if chunk_sizes else 0,
        "chunk_size_p95": (
            statistics.quantiles(chunk_sizes, n=20)[18]
            if len(chunk_sizes) >= 2 else (chunk_sizes[0] if chunk_sizes else 0)
        ),
        "table_edge_chunk_count": sum(row["table_edge_chunk_count"] for row in rows),
        "title_edge_chunk_count": sum(row["title_edge_chunk_count"] for row in rows),
        "evidence_object_count": evidence_objects,
        "cross_chunk_evidence_object_count": cross_chunk,
        "cross_chunk_evidence_rate": cross_chunk / evidence_objects if evidence_objects else 0.0,
        "stage4t_routed_table_count": sum(row["stage4t_routed_table_count"] for row in rows),
        "stage4t_fallback_count": sum(row["stage4t_fallback_count"] for row in rows),
        "stage4t_interpretation_seconds": sum(row["stage4t_interpretation_seconds"] for row in rows),
        "stage1_input_tokens": sum(row["stage1_input_tokens"] for row in rows),
        "stage1_output_tokens": sum(row["stage1_output_tokens"] for row in rows),
        "stage1_total_tokens": sum(row["stage1_total_tokens"] for row in rows),
        "stage5_shard_duration_sum_seconds": sum(row["stage5_shard_duration_sum_seconds"] for row in rows),
        "stage5_parallelism_ratio_mean": (
            statistics.mean(row["stage5_parallelism_ratio"] for row in rows) if rows else 1.0
        ),
        "per_document": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-chunk-chars", type=int, default=8000)
    args = parser.parse_args()
    rows = audit_batch(args.batch, args.max_chunk_chars)
    summary = build_summary(rows, args.max_chunk_chars)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "chunking_performance.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out / "chunking_performance.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
