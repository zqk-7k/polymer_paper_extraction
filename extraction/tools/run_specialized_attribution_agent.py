"""在现有 Stage 0/3/4T 产物上运行九类性质归属核验 Agent。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal
from pathlib import Path
from typing import Any


EXTRACTION_ROOT = Path(__file__).resolve().parents[1]
if str(EXTRACTION_ROOT) not in sys.path:
    sys.path.insert(0, str(EXTRACTION_ROOT))

from agents.specialized_attribution import (  # noqa: E402
    artifact_cost,
    build_agent_input,
    load_approved_memory,
    load_document_inputs,
    load_specialized_vocabulary,
    run_attribution_agent,
)
from llm_client import DEFAULT_CONFIG_PATH, load_pipeline_config  # noqa: E402


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def _targets(path: Path) -> list[dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    targets = data.get("targets") if isinstance(data, dict) else None
    if not isinstance(targets, list) or not targets:
        raise ValueError("manifest.targets 必须是非空数组")
    result = []
    for item in targets:
        if not isinstance(item, dict) or not item.get("ref_no") or not item.get("table_id"):
            raise ValueError("每个 target 必须包含 ref_no 和 table_id")
        result.append({
            "ref_no": str(item["ref_no"]),
            "table_id": str(item["table_id"]),
            "split": str(item.get("split") or "unspecified"),
        })
    return result


def _run_one(
    target: dict[str, str],
    *,
    batch_root: Path,
    output_root: Path,
    vocabulary: dict[str, dict[str, Any]],
    vocabulary_sha256: str,
    memory: list[dict[str, Any]],
    memory_sha256: str | None,
    config_path: Path,
    reuse_root: Path | None,
) -> dict[str, Any]:
    ref_no = target["ref_no"]
    table_id = target["table_id"]
    stage0, stage3, shadow = load_document_inputs(batch_root / ref_no)
    probe = build_agent_input(
        stage0,
        stage3,
        table_id=table_id,
        vocabulary=vocabulary,
        shadow=shadow,
        approved_memory=memory,
    )
    selected_patterns = [
        item.get("pattern_id") for item in probe.get("approved_memory") or []
    ]
    baseline_path = (
        reuse_root / ref_no / f"{table_id}_attribution_agent.json"
        if reuse_root is not None
        else None
    )
    reused = bool(
        memory
        and not selected_patterns
        and baseline_path is not None
        and baseline_path.is_file()
    )
    if reused:
        artifact = json.loads(baseline_path.read_text(encoding="utf-8"))
        baseline_sha256 = hashlib.sha256(baseline_path.read_bytes()).hexdigest()
        artifact["memory_sha256"] = memory_sha256
        artifact["selected_memory_pattern_ids"] = []
        artifact["evolution_reuse"] = {
            "reused": True,
            "reason": "no_applicable_approved_memory",
            "baseline_artifact_sha256": baseline_sha256,
        }
        artifact["runtime"] = {
            "call_count": 0,
            "usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "billable_input_tokens": 0,
                "total_tokens": 0,
            },
            "cost": {
                "status": "not_applicable",
                "currency": "CNY",
                "input_cost": "0",
                "output_cost": "0",
                "total_cost": "0",
            },
        }
    else:
        artifact = run_attribution_agent(
            stage0=stage0,
            stage3=stage3,
            table_id=table_id,
            vocabulary=vocabulary,
            vocabulary_sha256=vocabulary_sha256,
            shadow=shadow,
            approved_memory=memory,
            memory_sha256=memory_sha256,
            config_path=config_path,
        )
    artifact["split"] = target["split"]
    output_path = output_root / ref_no / f"{table_id}_attribution_agent.json"
    _write_json(output_path, artifact)
    cost = artifact_cost(artifact)
    return {
        "ref_no": ref_no,
        "table_id": table_id,
        "split": target["split"],
        "status": str(artifact.get("status")),
        "requires_human_review": bool(
            ((artifact.get("response") or {}).get("requires_human_review"))
        ),
        "semantic_assignments": len(
            (artifact.get("response") or {}).get("semantic_assignments") or []
        ),
        "sample_assignments": len(
            (artifact.get("response") or {}).get("sample_assignments") or []
        ),
        "call_count": int((artifact.get("runtime") or {}).get("call_count") or 0),
        "reported_cost_cny": str(cost) if cost is not None else None,
        "reused_baseline": reused,
        "selected_memory_pattern_ids": selected_patterns,
        "output": str(output_path),
    }


def run_batch(args: argparse.Namespace) -> Path:
    config = load_pipeline_config(args.config)
    settings = (config.get("stages") or {}).get("specialized_attribution_agent") or {}
    vocabulary_path = EXTRACTION_ROOT / str(
        settings.get("vocabulary_path") or "config/polymer_schema.yaml"
    )
    vocabulary, vocabulary_sha256 = load_specialized_vocabulary(vocabulary_path)
    memory, memory_sha256 = load_approved_memory(args.memory)
    targets = _targets(args.manifest)
    workers = max(1, min(int(args.workers), len(targets)))
    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _run_one,
                target,
                batch_root=args.batch_root,
                output_root=args.output_root,
                vocabulary=vocabulary,
                vocabulary_sha256=vocabulary_sha256,
                memory=memory,
                memory_sha256=memory_sha256,
                config_path=args.config,
                reuse_root=args.reuse_root,
            ): target
            for target in targets
        }
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            print(f"completed {row['ref_no']} {row['table_id']} {row['status']}", flush=True)

    costs = [
        Decimal(row["reported_cost_cny"])
        for row in rows
        if row.get("reported_cost_cny") is not None
    ]
    summary = {
        "schema_version": "specialized_attribution_agent_run.v1",
        "manifest": str(args.manifest),
        "batch_root": str(args.batch_root),
        "memory": str(args.memory) if args.memory else None,
        "memory_sha256": memory_sha256,
        "vocabulary_sha256": vocabulary_sha256,
        "workers": workers,
        "documents": sorted(rows, key=lambda item: (item["ref_no"], item["table_id"])),
        "total_calls": sum(row["call_count"] for row in rows),
        "reported_cost_cny": str(sum(costs, Decimal(0))) if costs else None,
    }
    path = args.output_root / "agent_run_summary.json"
    _write_json(path, summary)
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--memory", type=Path)
    parser.add_argument(
        "--reuse-root",
        type=Path,
        help="无适用记忆时复用该目录中的冻结基线，隔离无关更新影响",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--workers", type=int, default=1)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    args.batch_root = args.batch_root.expanduser().resolve()
    args.manifest = args.manifest.expanduser().resolve()
    args.output_root = args.output_root.expanduser().resolve()
    args.config = args.config.expanduser().resolve()
    if args.memory:
        args.memory = args.memory.expanduser().resolve()
    if args.reuse_root:
        args.reuse_root = args.reuse_root.expanduser().resolve()
    print(run_batch(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
