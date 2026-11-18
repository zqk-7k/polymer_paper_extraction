"""Read reviewed, hash-bound reference identities without using property values."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def load_crosswalk(path):
    path = Path(path).resolve()
    snapshots = {path: path.read_bytes()}
    data = json.loads(snapshots[path])
    if data.get("schema_version") != "reference_sample_crosswalk.v1":
        raise ValueError("Unsupported sample crosswalk")
    entries = {}
    for item in data["entries"]:
        key = (item["document_id"], item["reference_sample_id"])
        if key in entries:
            raise ValueError("Duplicate reference sample identity")
        entries[key] = item
        sources = {}
        names = ("reference_source", "article_source") if item["status"] == "reviewed_identity" else ("reference_source",)
        for name in names:
            source = item[name]
            source_path = (path.parent / source["path"]).resolve()
            content = source_path.read_bytes()
            if hashlib.sha256(content).hexdigest() != source["sha256"]:
                raise ValueError("Identity source changed")
            snapshots[source_path] = content
            sources[name] = json.loads(content)
        if sources["reference_source"].get("sample_id") != item["reference_sample_id"]:
            raise ValueError("Identity document mismatch")
        if item["status"] != "reviewed_identity":
            continue
        if not item.get("reviewer") or not item.get("basis"):
            raise ValueError("Identity review is missing")
        reference, article = sources["reference_source"], sources["article_source"]
        if (reference.get("sample_id") != item["reference_sample_id"]
                or article.get("document_id") != item["document_id"]):
            raise ValueError("Identity document mismatch")
        # Reviewed excerpts must be identity/preparation fields, never target values.
        allowed = {"polymer_name", "polymerization_information"}
        if not item.get("identity_excerpts"):
            raise ValueError("Independent identity evidence missing")
        for excerpt in item["identity_excerpts"]:
            keys = excerpt["field_path"]
            if not keys or keys[0] not in allowed:
                raise ValueError("Property values cannot establish sample identity")
            value = reference
            for part in keys:
                value = value[part]
            if value != excerpt["value"]:
                raise ValueError("Identity excerpt mismatch")
        cells = {cell["cell_id"]: cell for block in article["elements"]
                 if block.get("block_id") == item["table_id"] for cell in block.get("table_cells", [])}
        for expected in [item["sample_axis"], *item.get("preparation_axes", [])]:
            cell = cells.get(expected["cell_id"], {})
            if cell.get("text") != expected["value_raw"]:
                raise ValueError("Reviewed source axis changed")
        if not item.get("preparation_axes"):
            raise ValueError("Preparation identity must be explicitly scoped")
    return entries, snapshots


def identity_match(record, entry):
    if entry is None or entry.get("status") != "reviewed_identity":
        return False
    if record.get("binding_status") not in {"resolved", "article_alias_confirmed", "entity_only"}:
        return False
    if entry["sample_axis"]["cell_id"] not in record.get("binding_evidence_ids", []):
        return False
    context = record.get("source_condition_context") or {}
    if context.get("table_id") != entry["table_id"] or context.get("status") != "source_aligned":
        return False
    axes = {axis["cell_id"]: axis for axis in context.get("condition_axes", [])}
    return all(axes.get(expected["cell_id"], {}).get("value_raw") == expected["value_raw"]
               and axes[expected["cell_id"]].get("condition_kind") == "sample_preparation"
               for expected in entry["preparation_axes"])
