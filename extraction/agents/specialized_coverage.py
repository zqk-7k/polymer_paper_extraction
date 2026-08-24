"""Document-level coverage Agent for nine PoLyInfo specialized fields."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from llm_client import DEFAULT_CONFIG_PATH, LLMClient, load_pipeline_config, summarize_client_calls
from prompt_loader import PromptLoader


AGENT_STAGE = "specialized_coverage_agent"
SCHEMA_VERSION = "specialized_coverage_agent_schema.v1"
PROMPT_ID = "polymer.specialized.coverage"

NUMERIC_ONLY_FIELDS = {
    "average_molecular_weight",
    "solution_viscosity",
    "degree_of_polymerization",
    "crystallographic_data",
}


class CoverageDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_field: str
    decision: Literal["supported", "not_found", "ambiguous"]
    semantic_label: str | None = None
    variant: str | None = None
    observed_text: str | None = Field(default=None, max_length=320)
    evidence_block_ids: list[str] = Field(default_factory=list)
    sample_id: str | None = None
    entity_id: str | None = None
    subject_resolution: Literal["sample", "entity_only", "unresolved"]
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=320)

    @model_validator(mode="after")
    def validate_supported(self) -> "CoverageDecision":
        if self.decision == "supported":
            if not self.semantic_label or not self.observed_text or not self.evidence_block_ids:
                raise ValueError("supported decision requires semantics, verbatim text, and evidence")
            if self.subject_resolution == "sample" and not self.sample_id:
                raise ValueError("sample subject requires sample_id")
            if self.subject_resolution == "entity_only" and not self.entity_id:
                raise ValueError("entity_only subject requires entity_id")
        elif any((self.semantic_label, self.variant, self.observed_text, self.evidence_block_ids, self.sample_id, self.entity_id)):
            raise ValueError("non-supported decision must not carry candidate facts")
        return self


class SpecializedCoverageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["specialized_coverage_agent_schema.v1"] = SCHEMA_VERSION
    document_id: str
    decisions: list[CoverageDecision]
    requires_human_review: bool
    warnings: list[str] = Field(default_factory=list)


def _normalize(value: str) -> str:
    normalized = value.casefold()
    normalized = normalized.replace("\\text", " ").replace("\\mathrm", " ")
    normalized = re.sub(r"[{}_$^\\]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def passes_schema_release_gate(decision: Mapping[str, Any]) -> bool:
    """Reject category-only statements from fields whose contract requires a value."""
    if decision.get("decision") != "supported":
        return False
    if decision.get("source_field") not in NUMERIC_ONLY_FIELDS:
        return True
    return bool(re.search(r"\d", str(decision.get("observed_text") or "")))


def load_vocabulary(path: Path) -> tuple[dict[str, dict[str, Any]], str]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    vocabulary = payload.get("specialized_property_vocabulary") or {}
    if not isinstance(vocabulary, dict) or len(vocabulary) != 9:
        raise ValueError("specialized_property_vocabulary must contain exactly nine fields")
    return {str(key): dict(value) for key, value in vocabulary.items()}, hashlib.sha256(path.read_bytes()).hexdigest()


def load_memory(path: Path | None) -> tuple[dict[str, list[str]], str | None]:
    if path is None:
        return {}, None
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    aliases = payload.get("retrieval_aliases") or {}
    return {
        str(field): [str(value) for value in values or []]
        for field, values in aliases.items()
        if isinstance(values, list)
    }, hashlib.sha256(path.read_bytes()).hexdigest()


def _block_text(block: Mapping[str, Any]) -> str:
    fragments = [
        str(block.get("text") or ""),
        str(block.get("caption") or ""),
        str(block.get("table_body") or ""),
    ]
    for cell in (block.get("table_cells") or block.get("cells") or []):
        if isinstance(cell, Mapping):
            fragments.append(str(cell.get("text") or cell.get("value") or ""))
    return " ".join(fragment for fragment in fragments if fragment).strip()


def _compact_candidate(item: Mapping[str, Any]) -> dict[str, Any]:
    evidence = []
    for anchor in item.get("evidence") or []:
        if not isinstance(anchor, Mapping):
            continue
        locator = anchor.get("table_locator") or {}
        evidence.append({
            "block_id": anchor.get("block_id"),
            "source_sentence": anchor.get("source_sentence"),
            "row_label": locator.get("row_label"),
            "column_label": locator.get("column_label"),
            "cell_value": locator.get("cell_value"),
        })
    return {
        key: item.get(key)
        for key in (
            "specialized_id",
            "source_field",
            "semantic_label",
            "variant",
            "value_kind",
            "value_raw",
            "unit_raw",
            "sample_id",
            "entity_id",
            "publication_status",
            "reason",
        )
    } | {"evidence": evidence[:2]}


def retrieve_evidence(
    stage0: Mapping[str, Any],
    vocabulary: Mapping[str, Mapping[str, Any]],
    memory: Mapping[str, list[str]],
    *,
    max_blocks: int = 72,
    max_chars_per_block: int = 1000,
    include_global_context: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    cue_map: dict[str, list[str]] = {}
    for field, entry in vocabulary.items():
        cue_map[field] = [str(value) for value in entry.get("aliases") or []] + list(memory.get(field) or [])
    ranked: list[tuple[int, int, dict[str, Any], list[str]]] = []
    for index, block in enumerate(stage0.get("elements") or []):
        if not isinstance(block, Mapping) or not block.get("block_id"):
            continue
        text = _block_text(block)
        normalized = _normalize(text)
        matched_fields = []
        score = 0
        for field, cues in cue_map.items():
            matches = [cue for cue in cues if _normalize(cue) and _normalize(cue) in normalized]
            if matches:
                matched_fields.append(field)
                score += 3 + min(4, len(matches))
        if block.get("type") == "table" and matched_fields:
            score += 3
        section = _normalize(str(block.get("section") or ""))
        is_global_context = (
            block.get("type") in {"title", "table"}
            or section in {"documenttitle", "abstract", "conclusion", "conclusions"}
        )
        if matched_fields or (include_global_context and is_global_context):
            if include_global_context and is_global_context:
                score += 2
            ranked.append((-score, index, dict(block), matched_fields))
    ranked.sort(key=lambda item: (item[0], item[1]))
    selected = ranked[:max_blocks]
    evidence = []
    coverage: dict[str, list[str]] = {field: [] for field in vocabulary}
    for _, _, block, fields in selected:
        block_id = str(block["block_id"])
        for field in fields:
            coverage[field].append(block_id)
        evidence.append({
            "block_id": block_id,
            "page": block.get("page"),
            "bbox": block.get("bbox"),
            "type": block.get("type"),
            "section": block.get("section"),
            "text": _block_text(block)[:max_chars_per_block],
            "matched_fields": fields,
            "retrieval_reason": "field_cue" if fields else "global_scientific_context",
        })
    return evidence, coverage


def build_input(
    stage0: Mapping[str, Any],
    stage2: Mapping[str, Any],
    stage3: Mapping[str, Any],
    candidate: Mapping[str, Any],
    vocabulary: Mapping[str, Mapping[str, Any]],
    memory: Mapping[str, list[str]],
    *,
    include_global_context: bool = False,
) -> dict[str, Any]:
    evidence, retrieval_coverage = retrieve_evidence(
        stage0,
        vocabulary,
        memory,
        max_blocks=96 if include_global_context else 72,
        include_global_context=include_global_context,
    )
    evidence_by_id = {str(item["block_id"]): item for item in evidence}
    source_blocks = {
        str(block.get("block_id")): block
        for block in stage0.get("elements") or []
        if isinstance(block, Mapping) and block.get("block_id")
    }
    observations = candidate.get("specialized_property_observations") or []
    # Existing shadow candidates are retrieval leads, not answers. Their source blocks
    # must remain visible even when a formula such as mu_inh does not match text aliases.
    referenced_ids = []
    for item in observations:
        for anchor in item.get("evidence") or []:
            block_id = str(anchor.get("block_id") or "")
            if block_id and block_id not in referenced_ids:
                referenced_ids.append(block_id)
    for block_id in referenced_ids:
        if block_id in evidence_by_id or block_id not in source_blocks or len(evidence) >= 96:
            continue
        block = source_blocks[block_id]
        packed = {
            "block_id": block_id,
            "page": block.get("page"),
            "bbox": block.get("bbox"),
            "type": block.get("type"),
            "section": block.get("section"),
            "text": _block_text(block)[:1000],
            "matched_fields": [],
            "retrieval_reason": "existing_shadow_candidate_evidence",
        }
        evidence.append(packed)
        evidence_by_id[block_id] = packed
    entities = [{key: item.get(key) for key in ("entity_id", "polymer_name", "source_names")} for item in stage2.get("polymer_entities") or stage2.get("entities") or []]
    samples = [{key: item.get(key) for key in ("sample_id", "sample_label_raw", "refers_to_entity", "state_description")} for item in stage3.get("samples") or []]
    current = [_compact_candidate(item) for item in observations if item.get("source_field")]
    unresolved = [
        _compact_candidate(item)
        for item in observations
        if item.get("publication_status") != "published"
        and (item.get("semantic_label") or item.get("evidence"))
    ]
    return {
        "input_schema_version": "specialized_coverage_agent_input.v1",
        "document_id": stage0.get("document_id") or (candidate.get("paper") or {}).get("ref_no"),
        "controlled_vocabulary": vocabulary,
        "retrieved_evidence": evidence,
        "retrieval_coverage": retrieval_coverage,
        "polymer_entities": entities,
        "samples": samples,
        "current_published_or_mapped_candidates": current[:160],
        "current_unresolved_candidates": unresolved[:240],
        "required_source_fields": list(vocabulary),
        "tool_trace": ["retrieve_stage0_evidence", "query_polymer_entities", "query_sample_catalog", "lookup_controlled_vocabulary"],
        "coverage_strategy": "global_context_review" if include_global_context else "cue_retrieval",
    }


def validate_response(data: Mapping[str, Any], request: Mapping[str, Any]) -> SpecializedCoverageResponse:
    normalized_data = json.loads(json.dumps(data))
    vocabulary = request["controlled_vocabulary"]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for decision in normalized_data.get("decisions") or []:
        grouped.setdefault(str(decision.get("source_field")), []).append(decision)
    deduplicated = []
    for field, decisions in grouped.items():
        decisions.sort(
            key=lambda item: (
                item.get("decision") == "supported",
                float(item.get("confidence") or 0),
            ),
            reverse=True,
        )
        deduplicated.append(decisions[0])
    normalized_data["decisions"] = deduplicated
    source_fields = [str(item.get("source_field")) for item in deduplicated]
    unknown_fields = set(source_fields) - set(vocabulary)
    if unknown_fields:
        raise ValueError(f"unknown field decisions: {sorted(unknown_fields)}")
    for missing_field in set(vocabulary) - set(source_fields):
        normalized_data.setdefault("decisions", []).append({
            "source_field": missing_field,
            "decision": "not_found",
            "semantic_label": None,
            "variant": None,
            "observed_text": None,
            "evidence_block_ids": [],
            "sample_id": None,
            "entity_id": None,
            "subject_resolution": "unresolved",
            "confidence": 0,
            "reason": "Agent omitted this field; deterministic not_found fallback.",
        })
    for decision in normalized_data.get("decisions") or []:
        if decision.get("decision") == "supported":
            continue
        for field in ("semantic_label", "variant", "observed_text", "sample_id", "entity_id"):
            decision[field] = None
        decision["evidence_block_ids"] = []
        decision["subject_resolution"] = "unresolved"
    response = SpecializedCoverageResponse.model_validate(normalized_data)
    if response.document_id != request.get("document_id"):
        raise ValueError("document_id mismatch")
    decisions = {item.source_field: item for item in response.decisions}
    if set(decisions) != set(vocabulary) or len(response.decisions) != len(vocabulary):
        raise ValueError("exactly one decision is required for each of the nine fields")
    evidence = {str(item["block_id"]): item for item in request["retrieved_evidence"]}
    samples = {str(item.get("sample_id")): item for item in request["samples"] if item.get("sample_id")}
    entities = {str(item.get("entity_id")) for item in request["polymer_entities"] if item.get("entity_id")}

    def reject_candidate(item: CoverageDecision, reason: str) -> None:
        item.decision = "ambiguous"
        item.semantic_label = None
        item.variant = None
        item.observed_text = None
        item.evidence_block_ids = []
        item.sample_id = None
        item.entity_id = None
        item.subject_resolution = "unresolved"
        item.confidence = 0
        item.reason = f"Deterministic validation rejected candidate: {reason}"
        response.requires_human_review = True
        response.warnings.append(f"{item.source_field}: {reason}")

    for item in response.decisions:
        if item.decision != "supported":
            continue
        entry = vocabulary[item.source_field]
        if item.semantic_label not in set(entry.get("semantic_labels") or []):
            reject_candidate(item, "semantic label outside controlled vocabulary")
            continue
        if item.variant and item.variant not in set(entry.get("variants") or []):
            reject_candidate(item, "variant outside controlled vocabulary")
            continue
        unknown = set(item.evidence_block_ids) - set(evidence)
        if unknown:
            reject_candidate(item, f"unknown evidence reference {sorted(unknown)}")
            continue
        source = " ".join(evidence[block_id]["text"] for block_id in item.evidence_block_ids)
        if _normalize(str(item.observed_text)) not in _normalize(source):
            reject_candidate(item, "observed_text is not verbatim evidence")
            continue
        if item.sample_id:
            sample = samples.get(item.sample_id)
            if not sample:
                reject_candidate(item, "unknown sample_id")
                continue
            expected_entity = sample.get("refers_to_entity")
            if item.entity_id and expected_entity and item.entity_id != expected_entity:
                reject_candidate(item, "sample/entity foreign-key mismatch")
                continue
        if item.entity_id and item.entity_id not in entities:
            reject_candidate(item, "unknown entity_id")
    return response


def run_coverage_agent(
    document_dir: Path,
    *,
    vocabulary_path: Path,
    memory_path: Path | None = None,
    config_path: Path = DEFAULT_CONFIG_PATH,
    client: LLMClient | None = None,
    include_global_context: bool = False,
) -> dict[str, Any]:
    stage0 = json.loads((document_dir / "stage0_blocks.json").read_text(encoding="utf-8"))
    stage2 = json.loads((document_dir / "stage2_entities.json").read_text(encoding="utf-8"))
    stage3 = json.loads((document_dir / "stage3_process.json").read_text(encoding="utf-8"))
    candidate = json.loads((document_dir / "candidate.json").read_text(encoding="utf-8"))
    vocabulary, vocabulary_sha256 = load_vocabulary(vocabulary_path)
    memory, memory_sha256 = load_memory(memory_path)
    request = build_input(
        stage0,
        stage2,
        stage3,
        candidate,
        vocabulary,
        memory,
        include_global_context=include_global_context,
    )
    prompt = PromptLoader().render_stage_prompt(PROMPT_ID, SpecializedCoverageResponse, expected_stage=AGENT_STAGE, expected_output_schema=SCHEMA_VERSION)
    local_client = client or LLMClient.from_pipeline_config(stage=AGENT_STAGE, config_path=config_path)
    start = len(local_client.call_history)
    config = load_pipeline_config(config_path)
    settings = ((config.get("stages") or {}).get(AGENT_STAGE) or {})
    response = local_client.call_json(prompt.text, json.dumps(request, ensure_ascii=False, separators=(",", ":")), max_tokens=int(settings.get("max_tokens") or 8192))
    validated = validate_response(response.data, request)
    usage, cost = summarize_client_calls(local_client, start, call_count=len(local_client.call_history) - start)
    return {
        "schema_version": "specialized_coverage_agent_artifact.v1",
        "status": "succeeded",
        "authoritative": False,
        "publication_status": "candidate_only",
        "document_id": request["document_id"],
        "response": validated.model_dump(mode="json"),
        "retrieval": {"evidence_blocks": len(request["retrieved_evidence"]), "field_block_counts": {key: len(value) for key, value in request["retrieval_coverage"].items()}},
        "tool_trace": request["tool_trace"] + ["validate_evidence_quote", "validate_subject_foreign_keys"],
        "prompt": {"id": prompt.prompt_id, "version": prompt.version, "sha256": prompt.sha256},
        "vocabulary_sha256": vocabulary_sha256,
        "memory_sha256": memory_sha256,
        "coverage_strategy": request["coverage_strategy"],
        "runtime": {"usage": usage, "cost": cost},
    }
