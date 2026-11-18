"""Deterministic article-local binding identities and status classification."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any, Literal


BindingStatus = Literal[
    "resolved",
    "article_alias_confirmed",
    "entity_only",
    "ambiguous",
    "unresolved",
    "conflict",
]


def normalize_article_label(value: Any) -> str:
    """Normalize a label for identity generation while preserving its meaning."""
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    return re.sub(r"\s+", " ", text)


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, str):
        return normalize_article_label(value)
    return value


def build_article_sample_key(
    document_id: str,
    scope_id: str,
    label: str,
    *,
    variant_context: Any = None,
    entity_id: str | None = None,
) -> str:
    """Build a stable identity local to one article and evidence scope.

    The scope and variant context intentionally participate in the key so that
    different table-local batches, doses, or treatments are not merged merely
    because their displayed labels are similar.
    """
    payload = {
        "document_id": normalize_article_label(document_id),
        "scope_id": normalize_article_label(scope_id),
        "label": normalize_article_label(label),
        "variant_context": _canonical(variant_context),
        "entity_id": normalize_article_label(entity_id),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "article_sample_" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


_CONFLICT_ERRORS = {
    "candidate_entity_conflict",
    "candidate_sample_conflict",
    "locator_conflict",
    "process_dose_conflict",
    "sample_entity_conflict",
}


def classify_binding_status(
    *,
    selected_sample_id: str | None,
    selected_entity_id: str | None,
    article_sample_key: str | None,
    reasoning_status: str,
    validation_passed: bool,
    validation_errors: list[str] | tuple[str, ...] = (),
) -> BindingStatus:
    """Separate binding identity from the model's review vocabulary."""
    errors = set(validation_errors)
    if not validation_passed:
        return "conflict" if errors & _CONFLICT_ERRORS else "unresolved"
    if reasoning_status == "ambiguous":
        return "ambiguous"
    if reasoning_status == "rejected":
        return "conflict" if errors & _CONFLICT_ERRORS else "unresolved"
    if reasoning_status != "accepted":
        return "unresolved"
    if selected_sample_id:
        return "resolved"
    if article_sample_key:
        return "article_alias_confirmed"
    if selected_entity_id:
        return "entity_only"
    return "unresolved"
