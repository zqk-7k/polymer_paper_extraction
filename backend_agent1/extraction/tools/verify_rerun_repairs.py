"""Offline repair verification from saved source/response files; makes no API calls."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llm_client import extract_json_object, load_pipeline_config, DEFAULT_CONFIG_PATH
from prompt_loader import PromptLoader
from schema.polymer_schema import (Stage0Document, Stage2Document, Stage3Document,
    Stage4Document, CharacterizationStageResponse)
from stages.stage4t_preview_sidecar import run_sidecar, _summary
from stages.stage4t_interpretation_apply import apply_table_interpretation
from stages.stage4t_table_property import build_table_interpretation_context
from stages.stage5_characterization import (select_context_blocks, plan_shards,
    load_characterization_vocabulary, DEFAULT_VOCABULARY_PATH,
    _materialize_specialized, _materialize_shard_with_salvage,
    extract_characterizations, _failure_replay_client)
from stages.specialized_vocabulary import get_specialized_vocabulary
from tools.review_sample_binding_llm import process_document
from stages.figure_evidence import build_figure_index
from stages.stage0_load_document import SECTION_ROUTING_VERSION, rebuild_sections
from stages.stage4r_unified_preview import unify_documents
from stages.subject_lineage import audit_lineage


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stage5_failure_class(failure: dict) -> tuple[str, bool]:
    """Classify a saved Stage5 stop without treating every gap as an API retry."""
    error_type = str(failure.get("error_type") or "").casefold()
    error_text = str(failure.get("error") or "").casefold()
    api_markers = (
        "timeout", "connection", "rate", "429", "502", "503", "504",
        "api", "provider", "unavailable", "network", "http",
    )
    if any(marker in error_type or marker in error_text for marker in api_markers):
        return "api_failure", True
    if error_type in {"keyerror", "valueerror", "validationerror", "typeerror"}:
        return "deterministic_or_sample_reference_failure", False
    if not error_type and not error_text:
        return "unknown_failure", False
    return "non_api_failure", False


def _dependency_rebuild_plan(
    *,
    routing_changes: list[dict],
    changed_tables: list[dict],
    unified_status: str,
    stage5_replay: dict | None,
) -> list[dict]:
    """Produce a conservative, stage-aware rebuild plan from offline evidence."""
    plan: list[dict] = []

    def add(stage: str, reason: str, *, api_required: bool = False) -> None:
        item = {"stage": stage, "reason": reason, "api_required": api_required}
        if item not in plan:
            plan.append(item)

    if routing_changes:
        add("stage1", "Stage0 section routing changed; downstream mention context may differ")
        add("stage2", "Stage0 section routing changed; entity evidence may differ")
        add("stage3", "Stage0 section routing changed; sample/process evidence may differ")
        add("stage4", "Stage0 section routing changed; property evidence may differ")
        add("stage5", "Stage0 section routing changed; characterization context may differ")
        add("stage6", "Upstream routing changed; validation/merge must be rerun")
    if any(
        item.get("added_cell_ids") or item.get("removed_cell_ids")
        or item.get("changed_numeric_cell_ids")
        for item in changed_tables
    ):
        add("stage4t", "Table source-cell inventory or normalized numeric projection changed")
        add("stage4r", "Stage4T table candidates changed")
        add("stage5", "Stage4T/Stage4R input changed; reuse only matching shard cache")
        add("stage6", "Property inputs changed; validation/merge must be rerun")
    if unified_status != "generated":
        add("stage4r", "Stage4R preview could not be generated from available inputs")
        add("stage5", "Stage4R dependency is incomplete", api_required=False)
    if stage5_replay:
        missing = stage5_replay.get("shards_without_saved_or_failure_response") or []
        recovered = stage5_replay.get("shards_recovered_from_failure_response") or []
        if recovered:
            add("stage5", "Saved failure response was recovered with current salvage validation")
        if missing:
            api_eligible = bool(
                stage5_replay.get("original_failure", {}).get("api_retry_eligible")
            )
            add(
                "stage5",
                f"{len(missing)} shard(s) have no saved response; dependency/semantic review required",
                api_required=api_eligible,
            )
        add("stage6", "Stage5 replay or missing shards changed characterization completeness")
    return plan


def verify_stage5(source):
    failure_path = source / "stage5_failure.json"
    if not failure_path.exists():
        return None
    needed = ("stage0_blocks.json", "stage2_entities.json", "stage3_process.json", "stage4_properties.json")
    if not all((source / name).exists() for name in needed):
        return {"status": "upstream_missing"}
    doc, entities, process, stage4 = [cls.model_validate(read(source / name)) for cls, name in zip(
        (Stage0Document, Stage2Document, Stage3Document, Stage4Document), needed)]
    methods, vocabulary, vocabulary_hash = load_characterization_vocabulary(DEFAULT_VOCABULARY_PATH)
    blocks, _, _ = select_context_blocks(doc, entities, process, stage4, allow_oversize=True)
    shards, unrouted = plan_shards(blocks, methods)
    saved = read(source / "stage5_shards.json") if (source / "stage5_shards.json").exists() else {}
    saved_ids = {s["shard_id"] for s in saved.get("shards", [])}
    failure = read(failure_path)
    failure_class, api_retry_eligible = _stage5_failure_class(failure)
    result = {"scope": "saved_failure_materialization_not_full_stage5_run",
        "planned_shard_ids": [s.shard_id for s in shards],
        "saved_shard_ids": sorted(saved_ids),
        "shards_without_saved_result": [s.shard_id for s in shards if s.shard_id not in saved_ids],
        "unrouted_block_ids": unrouted, "replays": [],
        "original_failure": {
            "error_type": failure.get("error_type"),
            "error": failure.get("error"),
            "failure_class": failure_class,
            "api_retry_eligible": api_retry_eligible,
        },
        "retry_policy": "api_failures_only",
    }
    raw = extract_json_object(failure["raw_response"]["content"])
    parsed = CharacterizationStageResponse.model_validate(raw)
    response_methods = {c.method_normalized for c in parsed.characterizations}
    vocab = get_specialized_vocabulary()
    for shard in shards:
        if shard.method_normalized not in response_methods:
            continue
        before_error = None
        try:
            _materialize_specialized(parsed.specialized_property_observations,
                {b.block_id: b for b in shard.blocks}, vocab)
        except (KeyError, ValueError) as exc:
            before_error = f"{type(exc).__name__}: {exc}"
        chars, props, specialized, rejected = _materialize_shard_with_salvage(parsed, list(shard.blocks), vocab)
        result["replays"].append({"shard_id": shard.shard_id, "block_ids": [b.block_id for b in shard.blocks],
            "original_error": failure.get("error"), "reproduced_error": before_error,
            "status": "candidate_partial" if rejected else "materialized_requires_semantic_validation",
            "characterizations": [x.model_dump(mode="json") for x in chars],
            "properties": [x.model_dump(mode="json") for x in props],
            "specialized_property_observations": [x.model_dump(mode="json") for x in specialized],
            "rejected_objects": rejected})
    missing_ids = set(result["shards_without_saved_result"])
    replayed_ids = {item["shard_id"] for item in result["replays"]}
    result["shards_recovered_from_failure_response"] = sorted(missing_ids & replayed_ids)
    result["shards_without_saved_or_failure_response"] = sorted(missing_ids - replayed_ids)
    # Exercise the complete current validation/merge path, including every
    # planned shard. A missing saved response stays explicitly unexecuted.
    cache = {s["shard_id"]: s for s in saved.get("shards", [])}
    for replay in result["replays"]:
        if replay["shard_id"] not in cache:
            shard = next(s for s in shards if s.shard_id == replay["shard_id"])
            cache[shard.shard_id] = {"shard_id": shard.shard_id,
                "method_normalized": shard.method_normalized, "block_ids": replay["block_ids"],
                "attempts": [{"raw_response": failure["raw_response"]}]}
    client = _failure_replay_client(failure_path, load_pipeline_config(DEFAULT_CONFIG_PATH))
    def forbid_call(*args, **kwargs):
        raise AssertionError("Offline verification attempted an unsaved model call")
    client.call_json = forbid_call
    prompt = PromptLoader().render_stage_prompt("polymer.stage5.characterization", CharacterizationStageResponse,
        expected_stage="stage5_characterization", expected_output_schema="characterization_schema.v4")
    audit = {}
    rebuilt = extract_characterizations(doc, entities, process, stage4, client, prompt,
        methods, vocabulary, vocabulary_hash, preview_relaxed=True, sharded=True,
        max_validation_retries=0, shard_cache=cache, replay_shard_responses=True, diagnostic_sink=audit)
    result["validated_document"] = rebuilt.model_dump(mode="json")
    result["validated_shard_audit"] = audit
    result["api_calls"] = 0
    return result


def verify_document(source, output_root, recovery_root):
    ref = source.name
    derived = output_root / "table_rebuild" / ref
    derived.mkdir(parents=True, exist_ok=True)
    input_files = {}
    # Construct a dependency-isolated input snapshot. A repaired Stage 0 or
    # recovered Stage 3 is used only here; the original batch remains intact.
    for name in ("stage1_mentions.json", "stage2_entities.json", "stage3_process.json",
                 "stage4_properties.json"):
        path = source / name
        if name == "stage3_process.json" and recovery_root and (recovery_root / ref / name).exists():
            path = recovery_root / ref / name
        if path.exists():
            shutil.copyfile(path, derived / name)
            input_files[name] = {"path": str(path), "sha256": sha(path)}
    source_doc = Stage0Document.model_validate(read(source / "stage0_blocks.json"))
    repaired_doc, routing_changes = rebuild_sections(source_doc)
    write(derived / "stage0_blocks.json", repaired_doc.model_dump(mode="json"))
    input_files["stage0_blocks.json"] = {"path": str(source / "stage0_blocks.json"),
        "sha256": sha(source / "stage0_blocks.json"), "routing_changes": len(routing_changes)}
    path, _ = run_sidecar(input_root=derived.parent, output_root=derived.parent,
        ref_no=ref, force=True, enable_llm_interpretation=False)
    report = read(path)
    write(output_root / ref / "section_routing_audit.json", {"changes": routing_changes,
        "section_routing_version": SECTION_ROUTING_VERSION,
        "status": "requires_downstream_rebuild" if routing_changes else "unchanged"})
    if routing_changes:
        write(output_root / ref / "stage0_blocks.section_repaired.json", repaired_doc.model_dump(mode="json"))
    write(output_root / ref / "figure_context.json", build_figure_index(
        repaired_doc.model_dump(mode="json"), asset_root=Path(__file__).resolve().parents[3]))
    tables = {t.block_id: t for t in repaired_doc.elements if t.type == "table"}
    original = read(source / "stage4t_shadow.json") if (source / "stage4t_shadow.json").exists() else {}
    provenance_matches = (not routing_changes
        and original.get("provenance", {}).get("stage0_sha256") == sha(derived / "stage0_blocks.json"))
    old_interpretations = {r["table_id"]: r for r in original.get("interpretations", [])}
    replay_status = []
    for index, table_report in enumerate(report["tables"]):
        tid = table_report["table_id"]
        previous = old_interpretations.get(tid, {})
        if previous.get("status") != "succeeded" or not previous.get("interpretation"):
            continue
        entry = {"table_id": tid, "api_call": False}
        if not provenance_matches:
            entry["status"] = "source_hash_mismatch_or_missing"
        else:
            try:
                updated, application = apply_table_interpretation(tables[tid], table_report,
                    previous["interpretation"], context=build_table_interpretation_context(repaired_doc, tables[tid]))
                updated["rule_observations"] = table_report["observations"]
                report["tables"][index] = updated
                entry.update(status="replayed", application=application)
            except (TypeError, ValueError) as exc:
                entry.update(status="raw_retained_interpretation_failed", error=str(exc))
        replay_status.append(entry)
    report["saved_interpretation_replay"] = replay_status
    report["summary"] = _summary(report)
    report["offline_validation_only"] = True
    write(path, report)
    # Stage 4R is deterministic: merge the current table sidecar with the
    # saved Stage 4N result and emit a separate preview for review.
    unified_path = derived / "stage4_properties.unified_preview.json"
    unified_audit_path = derived / "stage4r_unified_audit.json"
    unified_status = "not_run"
    if all((derived / name).exists() for name in ("stage2_entities.json", "stage3_process.json", "stage4_properties.json")):
        stage2 = read(derived / "stage2_entities.json")
        stage3 = read(derived / "stage3_process.json")
        stage4 = read(derived / "stage4_properties.json")
        merged, unified_audit = unify_documents(repaired_doc, stage2, stage3, stage4, report)
        unified_audit["offline_rebuild"] = True
        unified_audit["routing_change_count"] = len(routing_changes)
        write(unified_path, merged.model_dump(mode="json"))
        write(unified_audit_path, unified_audit)
        unified_status = "generated"
    write(derived / "copied_input_manifest.json", input_files)
    lineage_files = {}
    for name in (
        "stage1_mentions.json", "stage2_entities.json", "stage3_process.json",
        "stage4t_shadow.json", "stage4_properties.json",
        "stage4_properties.unified_preview.json", "stage5_characterizations.json",
    ):
        candidate_path = derived / name
        if candidate_path.exists():
            lineage_files[name] = read(candidate_path)
    lineage_audit = audit_lineage(lineage_files)
    write(output_root / ref / "lineage_audit.json", lineage_audit)
    review = None
    if (derived / "stage3_process.json").exists():
        review = process_document(derived, output_root / "table_binding_review" / ref,
            execute=False, max_requests=20, positive_samples=1)
    replay = verify_stage5(source)
    if replay:
        write(output_root / ref / "stage5_failure_replay.json", replay)
    changed = []
    old_tables = {t["table_id"]: t for t in original.get("tables", [])}
    for table in report["tables"]:
        before = {o["cell_id"]: o for o in old_tables.get(table["table_id"], {}).get("observations", [])}
        after = {o["cell_id"]: o for o in table["observations"]}
        changed.append({"table_id": table["table_id"], "before": len(before), "after": len(after),
            "added_cell_ids": sorted(after.keys() - before.keys()),
            "removed_cell_ids": sorted(before.keys() - after.keys()),
            "changed_numeric_cell_ids": sorted(k for k in before.keys() & after.keys()
                if before[k].get("normalized_value") != after[k].get("normalized_value")),
            "coverage": table["input_capture_coverage"]})
    rebuild_plan = _dependency_rebuild_plan(
        routing_changes=routing_changes,
        changed_tables=changed,
        unified_status=unified_status,
        stage5_replay=replay,
    )
    result = {"document_id": ref, "api_calls": 0, "table_count": len(report["tables"]),
        "stage4r_status": unified_status, "routing_change_count": len(routing_changes),
        "tables": changed, "summary": report["summary"],
        "dependency_rebuild_plan": rebuild_plan,
        "lineage_reference_error_count": len(lineage_audit.get("reference_errors") or []),
        "binding_review": review, "stage5_replay_available": bool(replay)}
    write(output_root / ref / "verification.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--recovery-root", type=Path)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    source, target = args.input_root.resolve(), args.output_root.resolve()
    if source == target or source in target.parents or target in source.parents:
        raise ValueError("Output must be separate from the original batch")
    if args.workers < 1:
        raise ValueError("workers must be positive")
    files = sorted(source.glob("reference_no_*/*.json"))
    hashes = {str(p.relative_to(source)): sha(p) for p in files}
    write(target / "original_input_hashes.json", hashes)
    documents = sorted(p.parent for p in source.glob("reference_no_*/stage0_blocks.json"))
    results, errors = [], []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [(p, pool.submit(verify_document, p, target, args.recovery_root)) for p in documents]
        for path, future in futures:
            try:
                results.append(future.result())
                print(f"done {path.name}", flush=True)
            except Exception as exc:
                errors.append({"document_id": path.name, "error": f"{type(exc).__name__}: {exc}"})
                print(f"failed {path.name}: {type(exc).__name__}: {exc}", flush=True)
    changed = [str(p.relative_to(source)) for p in files if sha(p) != hashes[str(p.relative_to(source))]]
    write(target / "verification_summary.json", {"scope": "offline_table_rebuild_and_failure_replay",
        "document_count": len(documents), "completed": len(results), "errors": errors,
        "api_calls": 0, "original_files_changed": changed, "documents": results})
    if errors or changed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
