"""Unified measurement records and conservative publication decisions."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from stages.binding_identity import BindingStatus
from stages.standard_mapping import resolve_standard_property
from stages.binding_publication import binding_publication_options


MeasurementStage = Literal["stage4", "stage4t", "stage4r", "stage5", "candidate", "final"]
PublicationStatus = Literal["candidate", "final", "not_publishable"]
StandardStatus = Literal[
    "standard_exact", "standard_alias", "standard_candidate", "standard_unmapped"
]


class MeasurementRecord(BaseModel):
    """Intermediate record shared by extraction and publication audits."""

    model_config = ConfigDict(extra="forbid")

    measurement_id: str = Field(min_length=1)
    source_stage: MeasurementStage
    source_cell_ids: list[str] = Field(default_factory=list)
    source_block_ids: list[str] = Field(default_factory=list)
    property_name_raw: str = Field(min_length=1)
    property_code: str | None = None
    standard_property_code: str | None = None
    standard_status: StandardStatus = "standard_unmapped"
    standard_mapping_reasons: list[str] = Field(default_factory=list)
    value_raw: str = Field(min_length=1)
    value_normalized: str | None = None
    unit_raw: str | None = None
    unit_normalized: str | None = None
    condition_context: dict[str, Any] = Field(default_factory=dict)
    source_condition_context: dict[str, Any] = Field(default_factory=dict)
    composition_context: dict[str, Any] = Field(default_factory=dict)
    sample_id: str | None = None
    article_sample_label_raw: str | None = None
    article_sample_key: str | None = None
    entity_id: str | None = None
    binding_status: BindingStatus
    binding_basis: str | None = None
    binding_evidence_ids: list[str] = Field(default_factory=list)
    publication_status: PublicationStatus = "candidate"
    publication_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_binding_identity(self) -> "MeasurementRecord":
        if not self.source_cell_ids and not self.source_block_ids:
            raise ValueError("measurement 至少需要 source_cell_ids 或 source_block_ids")
        if self.binding_status == "resolved" and not self.sample_id:
            raise ValueError("resolved measurement 必须包含 sample_id")
        if self.binding_status == "article_alias_confirmed":
            if not self.article_sample_key or self.sample_id:
                raise ValueError("article_alias_confirmed 必须只有 article_sample_key")
        if self.binding_status == "entity_only":
            if not self.entity_id or self.sample_id or self.article_sample_key:
                raise ValueError("entity_only 必须只有 entity_id")
        if self.binding_status in {"ambiguous", "unresolved", "conflict"} and self.sample_id:
            raise ValueError(f"{self.binding_status} 不得包含 sample_id")
        if self.publication_status == "final" and self.publication_reasons:
            raise ValueError("final measurement 不得保留 publication_reasons")
        return self


def build_measurement_id(
    document_id: str,
    source_cell_ids: list[str],
    property_code: str | None,
    value_raw: str,
    unit_raw: str | None,
    condition_context: dict[str, Any] | None = None,
) -> str:
    """Build an identity that is independent of model output ordering."""
    payload = {
        "document_id": document_id,
        "source_cell_ids": sorted(set(source_cell_ids)),
        "property_code": property_code,
        "value_raw": value_raw.strip(),
        "unit_raw": unit_raw,
        "condition_context": condition_context or {},
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return "measurement_" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def measurement_record_from_candidate(
    candidate: dict[str, Any],
    *,
    document_id: str,
    source_stage: MeasurementStage,
) -> MeasurementRecord | None:
    """Materialize a record only when the candidate has real source location."""
    evidence = list(_walk_dicts(candidate.get("evidence") or candidate.get("source_evidence") or candidate))
    cell_ids = sorted({str(item["cell_id"]) for item in evidence if item.get("cell_id")})
    block_ids = sorted({str(item.get("block_id") or item.get("table_id")) for item in evidence if item.get("block_id") or item.get("table_id")})
    if not cell_ids and not block_ids:
        return None
    sample_id = candidate.get("sample_id")
    article_key = candidate.get("article_sample_key")
    entity_id = candidate.get("entity_id")
    if sample_id:
        binding_status: BindingStatus = "resolved"
    elif article_key:
        binding_status = "article_alias_confirmed"
    elif entity_id:
        binding_status = "entity_only"
    else:
        binding_status = "unresolved"
    property_name = str(
        candidate.get("property_name_raw")
        or candidate.get("property_name_normalized")
        or candidate.get("semantic_label")
        or "unknown property"
    )
    value_raw = str(candidate.get("value_raw") or "").strip()
    if not value_raw:
        return None
    condition_context = candidate.get("measurement_context") or candidate.get("conditions") or {}
    mapping = resolve_standard_property(
        property_name,
        candidate.get("unit_raw"),
    )
    standard_status = mapping["standard_status"]
    standard_property_code = mapping.get("standard_property_code")
    mapping_reasons = list(mapping.get("mapping_reasons") or [])
    if candidate.get("standard_property_code") and candidate["standard_property_code"] != standard_property_code:
        standard_status = "standard_candidate" if standard_property_code else "standard_unmapped"
        mapping_reasons.append("standard_code_conflict")
    measurement_id = build_measurement_id(
        document_id, cell_ids or block_ids, candidate.get("property_code"), value_raw,
        candidate.get("unit_raw"), condition_context,
    )
    return MeasurementRecord(
        measurement_id=measurement_id,
        source_stage=source_stage,
        source_cell_ids=cell_ids,
        source_block_ids=block_ids,
        property_name_raw=property_name,
        property_code=candidate.get("property_code"),
        standard_property_code=standard_property_code,
        standard_status=standard_status,
        standard_mapping_reasons=mapping_reasons,
        value_raw=value_raw,
        value_normalized=candidate.get("value_normalized"),
        unit_raw=candidate.get("unit_raw"),
        unit_normalized=candidate.get("unit_normalized"),
        condition_context=condition_context if isinstance(condition_context, dict) else {"raw": condition_context},
        sample_id=sample_id,
        article_sample_label_raw=candidate.get("sample_label_observed_exact") or candidate.get("sample_label_observed"),
        article_sample_key=article_key,
        entity_id=entity_id,
        binding_status=binding_status,
        binding_basis=candidate.get("binding_basis"),
        binding_evidence_ids=sorted({str(item.get("evidence_id") or item.get("cell_id")) for item in evidence if item.get("evidence_id") or item.get("cell_id")}),
        publication_status="candidate",
        publication_reasons=[],
    )


def publication_decision(
    *,
    path_status: str,
    standard_status: str,
    unit_status: str,
    binding_status: BindingStatus,
    evidence_ids: list[str],
    input_complete: bool = True,
    allow_article_alias: bool = False,
    allow_entity_only: bool = False,
    conflicts: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    """Apply the publication gate without mutating the source record."""
    reasons: list[str] = []
    if not evidence_ids:
        reasons.append("evidence_missing")
    if not input_complete:
        reasons.append("input_incomplete")
    if path_status not in {"complete", "confirmed"}:
        reasons.append("property_path_incomplete")
    if standard_status not in {"standard_exact", "standard_alias"}:
        reasons.append("standard_field_unresolved")
    if unit_status not in {"confirmed", "unit_equivalent", "unit_converted_exact"}:
        reasons.append("unit_unresolved")
    if binding_status == "article_alias_confirmed" and not allow_article_alias:
        reasons.append("article_alias_policy_block")
    elif binding_status == "entity_only" and not allow_entity_only:
        reasons.append("entity_only_policy_block")
    elif binding_status in {"ambiguous", "unresolved"}:
        reasons.append("binding_unresolved")
    elif binding_status == "conflict":
        reasons.append("binding_conflict")
    reasons.extend(str(item) for item in conflicts if str(item))
    reasons = list(dict.fromkeys(reasons))
    hard = {
        "evidence_missing", "input_incomplete", "binding_conflict",
        "evidence_reference_unknown", "evidence_reference_ambiguous",
        "source_block_unknown", "sample_reference_unknown", "entity_reference_unknown",
        "value_not_in_target_cell",
        "duplicate_object_id",
    }
    hard.update(reason for reason in reasons if reason.endswith("_conflict"))
    status: PublicationStatus = "final" if not reasons else "not_publishable" if hard.intersection(reasons) else "candidate"
    return {"publication_status": status, "publication_reasons": reasons}


def publication_audit_for_final(
    payload: dict[str, Any], *, stage0: dict | None = None,
    stage3: dict | None = None, stage4: dict | None = None,
    stage5: dict | None = None,
    stage5_shards: dict | None = None,
    stage4_input_proof: dict | None = None,
) -> dict[str, Any]:
    """Return a read-only publication audit for Stage 6 output collections."""

    from stages.publication_checks import audit_context, check_publication_source
    from stages.publication_input_scope import record_input_scope, stage4_record_input_scope

    context = audit_context(payload, stage0, stage3)
    stage_status = {
        "stage4": (stage4 or {}).get("provenance", {}).get("status", "missing"),
        "stage5": (stage5 or {}).get("provenance", {}).get("status", "missing"),
    }
    records: list[dict[str, Any]] = []
    collections = (
        ("property_observations", payload.get("property_observations") or []),
        ("unresolved_property_observations", payload.get("unresolved_property_observations") or []),
        ("property_series", payload.get("property_series") or []),
        ("specialized_property_observations", payload.get("specialized_property_observations") or []),
    )
    allowed_statuses = {
        "resolved", "article_alias_confirmed", "entity_only",
        "ambiguous", "unresolved", "conflict",
    }

    for collection, items in collections:
        object_counts = Counter(
            item.get("property_id") or item.get("unresolved_id") or item.get("series_id") or item.get("specialized_id")
            for item in items if isinstance(item, dict)
        )
        for item in items:
            if not isinstance(item, dict):
                continue
            object_id = (
                item.get("property_id") or item.get("unresolved_id")
                or item.get("series_id") or item.get("specialized_id")
            )
            if not object_id:
                continue
            evidence_ids = sorted({
                str(value) for value in (item.get("evidence_ids") or []) if value
            })
            sample_id = item.get("sample_id")
            entity_id = item.get("entity_id")
            article_sample_key = item.get("article_sample_key")
            property_name = (
                item.get("property_name_raw")
                or item.get("semantic_label")
            )
            value_raw = item.get("value_raw")
            check = check_publication_source(item, context)
            if object_counts[object_id] > 1:
                check["check_reasons"].append("duplicate_object_id")
            source_stage = "stage5" if item.get("source_stage") == "stage5" or item.get("characterization_id") else "stage4"
            input_scope = record_input_scope(
                item, payload, stage5 if source_stage == "stage5" else stage4,
                stage5_shards if source_stage == "stage5" else None,
            )
            if source_stage == "stage4" and stage4_input_proof is not None and collection != "property_series":
                input_scope = stage4_record_input_scope(item, payload, stage4 or {}, stage4_input_proof)
            check["check_reasons"].extend(input_scope["input_scope_reasons"])
            has_value = value_raw is not None and bool(str(value_raw).strip())
            decision = publication_decision(
                path_status=check["path_status"],
                standard_status=check["standard_status"],
                unit_status=check["unit_status"],
                binding_status=check["binding_status"],
                evidence_ids=evidence_ids or check["path_evidence_ids"],
                input_complete=input_scope["input_complete"] and bool(property_name) and (has_value or bool(item.get("points"))),
                conflicts=check["check_reasons"],
                **binding_publication_options(check),
            )
            records.append({
                "measurement_id": item.get("measurement_id") or str(object_id),
                "object_id": str(object_id),
                "collection": collection,
                "property_name_raw": property_name,
                "value_raw": value_raw,
                "sample_id": sample_id,
                "article_sample_key": article_sample_key,
                "entity_id": entity_id,
                "evidence_ids": evidence_ids,
                "source_stage": source_stage,
                **input_scope,
                **check,
                **decision,
            })

    status_counts = {status: 0 for status in ("final", "candidate", "not_publishable")}
    binding_counts = {status: 0 for status in sorted(allowed_statuses)}
    for record in records:
        status_counts[record["publication_status"]] += 1
        binding_counts[record["binding_status"]] += 1
    return {
        "schema_version": "measurement_publication_audit.v3",
        "input_scope_counts": dict(Counter(row["input_scope_basis"] for row in records)),
        "stage_input_status": stage_status,
        "records": records,
        "counts": {
            "publication_status": status_counts,
            "binding_status": binding_counts,
        },
        "definition": "旁路审计结果，不改变 FinalDocument 的发布对象或 Stage 6 通过条件。",
    }
