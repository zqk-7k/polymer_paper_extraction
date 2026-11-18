"""Article-local sample identities. This sidecar never renumbers Stage3 processes."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from typing import Any
from pathlib import Path

from schema.polymer_schema import Stage0Element
from stages.table_grid import table_cells_for

CATALOG_VERSION = "sample_catalog.v3"
ALIAS_REVIEWS = Path(__file__).resolve().parents[1] / "config/source_sample_alias_reviews.v1.json"
RANGE = re.compile(r"^([A-Za-z][A-Za-z0-9]*)\s*[-–—]\s*(\d+)\s*(?:to|至|[-–—])\s*(?:\1\s*[-–—]\s*)?(\d+)$", re.I)
SAMPLE_HEADER = re.compile(r"^(?:samples?|polymers?|specimens?|materials?|codes?|sample\s+(?:code|id|name)|样品|材料|试样)(?:\s*\([^)]*\))?$", re.I)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def normalize_label(value: Any) -> str:
    # Keep punctuation and numbers: A/B, AB, PI-1 and PI-10 are different labels.
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"[‐‑‒–—−]", "-", text)
    text = re.sub(r"\\(?:mathrm|text|operatorname)\{([^{}]*)\}", r"\1", text)
    text = text.replace("$", "").replace("{", "").replace("}", "")
    return re.sub(r"\s+", "", text).casefold()


def family_members(label: str) -> list[str]:
    match = RANGE.fullmatch(label.strip())
    if not match:
        return []
    prefix, start, end = match.groups()
    if not 0 <= int(end) - int(start) <= 100:
        return []
    return [f"{prefix}-{n}" for n in range(int(start), int(end) + 1)]


def source_index(stage0: dict) -> tuple[dict, dict]:
    blocks, cells = {}, {}
    for raw in stage0.get("elements", []):
        block_id = raw.get("block_id")
        if not block_id:
            continue
        if block_id in blocks:
            raise ValueError(f"duplicate Stage0 block: {block_id}")
        blocks[block_id] = raw
        if raw.get("type") == "table":
            for cell in table_cells_for(Stage0Element.model_validate(raw)):
                if cell.cell_id in cells:
                    raise ValueError(f"duplicate Stage0 cell: {cell.cell_id}")
                cells[cell.cell_id] = {**cell.model_dump(), "table_id": block_id}
    return blocks, cells


def _evidence_list(value: Any) -> list[dict]:
    return [value] if isinstance(value, dict) else [x for x in value or [] if isinstance(x, dict)]


def _label_evidence(label: str, blocks: dict, cells: dict) -> list[dict]:
    result = []
    key = normalize_label(label)
    if not key:
        return result
    for cell in cells.values():
        if normalize_label(cell["text"]) == key:
            result.append({"block_id": cell["table_id"], "cell_id": cell["cell_id"], "source_quote": cell["text"], "source_type": "table"})
    # Boundaries prevent PI-1 from being inferred from PI-10 or a family range.
    pattern = re.compile(r"(?<![\w-])" + re.escape(label) + r"(?![\w-])", re.I)
    for block in blocks.values():
        text = block.get("text") or ""
        if block.get("type") != "table" and pattern.search(text):
            result.append({"block_id": block["block_id"], "source_quote": label, "source_type": block.get("type", "text")})
        if block.get("type") == "table":
            parts = [block.get("caption"), *(block.get("table_notes") or [])]
            content = block.get("content")
            if isinstance(content, dict):
                for key in ("table_caption", "table_footnote", "footnotes", "notes"):
                    value = content.get(key)
                    parts.extend(value if isinstance(value, list) else [value])
            for part in parts:
                if isinstance(part, str) and pattern.search(part):
                    result.append({"block_id": block["block_id"], "source_quote": part, "source_type": "table"})
    return result


def sample_review_hash(sample):
    def evidence_content(value):
        if isinstance(value, dict):
            return {k: evidence_content(v) for k, v in value.items() if v is not None}
        if isinstance(value, list):
            return [evidence_content(v) for v in value]
        return value
    identity = {k: sample.get(k) for k in ("sample_id", "sample_label_raw", "polymer_name", "refers_to_entity", "state_description", "evidence")}
    identity["evidence"] = evidence_content(identity["evidence"])
    return digest(identity)


def _reviewed_aliases(stage0, stage3, blocks, cells, reviews):
    from stages.source_measurement_context import table_review_hash
    if reviews is None:
        reviews = json.loads(ALIAS_REVIEWS.read_text(encoding="utf-8")) if ALIAS_REVIEWS.is_file() else {"reviews": []}
    accepted = []
    for review in reviews.get("reviews", []):
        samples = [s for s in stage3.get("samples", []) if s.get("sample_id") == review.get("legacy_sample_id")]
        block = blocks.get(review.get("table_id"))
        if (review.get("document_id") != stage0.get("document_id") or len(samples) != 1 or not block
                or not review.get("reviewer") or not review.get("basis")
                or sample_review_hash(samples[0]) != review.get("sample_sha256")
                or table_review_hash(block) != review.get("table_sha256")):
            continue
        excerpt = review["definition_evidence"]
        text = blocks.get(excerpt["block_id"], {}).get("text") or ""
        if not excerpt.get("quote") or excerpt["quote"] not in text or digest(text) != excerpt.get("text_sha256"):
            continue
        axis, condition = (cells.get(review[k], {}) for k in ("sample_axis_cell_id", "preparation_cell_id"))
        if (axis.get("table_id") != review["table_id"] or axis.get("text") != review["article_alias"]
                or condition.get("table_id") != review["table_id"] or condition.get("text") != review["preparation_value_raw"]
                or axis.get("row_index") != condition.get("row_index") or axis.get("row_span") != 1):
            continue
        accepted.append(copy.deepcopy(review))
    return accepted


def catalog_for_source_cells(catalog, source_cells, cells):
    """Apply reviewed aliases only to a single, reviewed source row."""
    targets = [cells[cid] for cid in source_cells if cid in cells]
    rows = {(c["table_id"], c["row_index"]) for c in targets}
    if len(rows) != 1:
        return catalog
    reviews = [r for r in catalog.get("reviewed_source_aliases", [])
               if r["sample_axis_cell_id"] in cells and (r["table_id"], cells[r["sample_axis_cell_id"]]["row_index"]) in rows]
    if not reviews:
        return catalog
    scoped = copy.deepcopy(catalog)
    for review in reviews:
        ids = scoped["legacy_mapping"].get(review["legacy_sample_id"], [])
        if len(ids) != 1:
            continue
        target = next(s for s in scoped["samples"] if s["sample_id"] == ids[0])
        alias = review["article_alias"]
        # Never erase a distinct Stage3 batch that already claims this label.
        others = [s for s in scoped["samples"] if s["sample_id"] != ids[0]
                  and normalize_label(alias) in {normalize_label(x) for x in [s["sample_label_primary"], *s["sample_label_aliases"]]}]
        if any(s["legacy_sample_ids"] for s in others):
            continue
        scoped["samples"] = [s for s in scoped["samples"] if s not in others]
        target["sample_label_aliases"] = sorted(set(target["sample_label_aliases"] + [alias]))
        target["source_evidence"].append({"block_id": review["table_id"], "cell_id": review["sample_axis_cell_id"],
                                          "source_quote": alias, "source_type": "table"})
        target.setdefault("source_alias_reviews", []).append(review)
    scoped["catalog_sha256"] = digest(scoped["samples"])
    return scoped


def build_catalog(stage0: dict, stage3: dict, *, alias_reviews=None) -> dict:
    blocks, cells = source_index(stage0)
    document_id = stage0.get("document_id") or stage3.get("document_id")
    if not document_id or (stage3.get("document_id") and stage3["document_id"] != document_id):
        raise ValueError("Stage0/Stage3 document_id mismatch or missing")
    entries: dict[str, dict] = {}
    ambiguous_identities: set[str] = set()
    legacy: dict[str, list[str]] = defaultdict(list)
    family_keys: dict[str, list[str]] = defaultdict(list)
    producers: dict[str, list[dict]] = defaultdict(list)
    for step in stage3.get("process_steps", []):
        for sid in step.get("output_sample_ids", []):
            producers[sid].append(step)

    for sample in stage3.get("samples", []):
        label = str(sample.get("sample_label_primary") or sample.get("sample_label_raw") or sample.get("polymer_name") or "").strip()
        aliases = sorted({str(x).strip() for x in sample.get("sample_label_aliases", []) if str(x).strip()})
        evidence = _label_evidence(label, blocks, cells)
        # A polymer name is an alias only when backed by source text, never by the standard set.
        name = str(sample.get("polymer_name") or "")
        if name and normalize_label(name) != normalize_label(label) and _label_evidence(name, blocks, cells):
            aliases.append(name)
        aliases = sorted({x for x in aliases if _label_evidence(x, blocks, cells)})
        members = family_members(label)
        level = "sample_family" if members else str(sample.get("sample_level") or sample.get("sample_kind") or "material")
        process_context = sorted([{"process_type": x.get("process_type"), "parameters": x.get("parameters", {}), "evidence": x.get("evidence", {})} for x in producers.get(sample.get("sample_id"), [])], key=digest)
        identity = {"document_id": document_id, "label": normalize_label(label), "level": level,
                    "polymer_name": normalize_label(sample.get("polymer_name")),
                    "state": normalize_label(sample.get("state_description")), "composition": sample.get("composition"),
                    "treatment": sample.get("treatment"), "process_context": process_context,
                    "refers_to_entity": sample.get("refers_to_entity"),
                    "source_anchor": sample.get("evidence", {}),
                    "batch_id": sample.get("batch_id")}
        uid = "sample_" + digest(identity)[:24]
        base_uid = uid
        if uid in entries or uid in ambiguous_identities:
            # Identical descriptions are not proof of identical batches. If
            # source evidence cannot distinguish them, keep the legacy identity
            # and expose ambiguous resolution instead of silently merging.
            prior = entries.pop(uid, None)
            previous_ids = prior["legacy_sample_ids"] if prior else []
            if previous_ids:
                previous_uid = "sample_" + digest({**identity, "legacy_identity": previous_ids[0]})[:24]
                prior["sample_id"] = previous_uid
                prior["identity_requires_review"] = True
                entries[previous_uid] = prior
                for sid in previous_ids:
                    legacy[sid] = [previous_uid if x == uid else x for x in legacy[sid]]
                for key in family_keys:
                    family_keys[key] = [previous_uid if x == uid else x for x in family_keys[key]]
            uid = "sample_" + digest({**identity, "legacy_identity": sample.get("sample_id")})[:24]
            ambiguous_identities.add(base_uid)
        entry = entries.setdefault(uid, {
            "sample_id": uid, "sample_label_primary": label, "sample_label_aliases": [],
            "sample_level": level, "parent_sample_ids": [], "member_sample_ids": [],
            "legacy_sample_ids": [], "composition": copy.deepcopy(sample.get("composition")),
            "treatment": copy.deepcopy(sample.get("treatment")), "process_context": process_context,
            "source_evidence": evidence, "label_status": "group_only" if members else ("explicit" if evidence else "unresolved"),
            "refers_to_entity": sample.get("refers_to_entity"), "legacy_sample": copy.deepcopy(sample),
        })
        entry["sample_label_aliases"] = sorted(set(entry["sample_label_aliases"] + aliases))
        if base_uid in ambiguous_identities:
            entry["identity_requires_review"] = True
        if sample.get("sample_id"):
            legacy[sample["sample_id"]].append(uid)
            entry["legacy_sample_ids"] = sorted(set(entry["legacy_sample_ids"] + [sample["sample_id"]]))
        for member in members:
            family_keys[normalize_label(member)].append(uid)

    label_map: dict[str, list[str]] = defaultdict(list)
    for entry in entries.values():
        if entry["sample_level"] != "sample_family":
            for label in [entry["sample_label_primary"], *entry["sample_label_aliases"]]:
                label_map[normalize_label(label)].append(entry["sample_id"])

    # Only create new concrete entries for observed family members or an explicit sample axis.
    # Arbitrary leftmost words/numbers are retained as context, not invented samples.
    sample_columns: dict[str, set[int]] = defaultdict(set)
    sample_rows: dict[str, set[int]] = defaultdict(set)
    for cell in cells.values():
        if SAMPLE_HEADER.fullmatch(cell["text"].strip()):
            if cell["row_index"] == 0:
                sample_columns[cell["table_id"]].update(range(cell["column_index"], cell["column_index"] + cell["column_span"]))
            elif cell["column_index"] == 0:
                sample_rows[cell["table_id"]].add(cell["row_index"])
    composite_rows, component_cells, group_cells = [], set(), set()
    for tid, columns in sample_columns.items():
        table_cells = [c for c in cells.values() if c["table_id"] == tid]
        for row in sorted({c["row_index"] for c in table_cells if c["row_index"] > 0}):
            segments = sorted([c for c in table_cells if c["column_index"] in columns and c["row_index"] <= row < c["row_index"] + c["row_span"] and c["text"].strip()], key=lambda c: c["column_index"])
            if len(segments) > 1:
                composite_rows.append(segments)
                component_cells.update(c["cell_id"] for c in segments)
                group_cells.update(c["cell_id"] for c in segments if c["row_span"] > 1)
    for cell in sorted(cells.values(), key=lambda x: x["cell_id"]):
        label = cell["text"].strip()
        key = normalize_label(label)
        explicit_axis = (cell["column_index"] in sample_columns[cell["table_id"]] and cell["row_index"] > 0) or (cell["row_index"] in sample_rows[cell["table_id"]] and cell["column_index"] > 0)
        if not label or len(label) > 160 or SAMPLE_HEADER.fullmatch(label) or family_members(label):
            continue
        if re.fullmatch(r"total|average|mean|minimum|maximum|合计|平均", label, re.I):
            continue
        if key not in family_keys and not explicit_axis:
            continue
        if cell["cell_id"] in component_cells and cell["cell_id"] not in group_cells:
            continue
        if re.fullmatch(r"[-–—./\s]+", label):
            continue
        matched = label_map.get(key, [])
        if not matched:
            level = "sample_family" if cell["cell_id"] in group_cells else "material"
            uid = "sample_" + digest({"document_id": document_id, "label": key, "level": level})[:24]
            entries[uid] = {
                "sample_id": uid, "sample_label_primary": label, "sample_label_aliases": [],
                "sample_level": level, "parent_sample_ids": [], "member_sample_ids": [],
                "legacy_sample_ids": [], "composition": None, "treatment": None, "process_context": [],
                "source_evidence": _label_evidence(label, blocks, cells), "label_status": "group_only" if level == "sample_family" else "explicit",
                "refers_to_entity": None, "legacy_sample": None,
            }
            label_map[key].append(uid)
            matched = [uid]
        for uid in matched:
            for parent in family_keys.get(key, []):
                entries[parent]["member_sample_ids"].append(uid)
                # Family membership differs from material/process ancestry.
                entries[uid].setdefault("family_sample_ids", []).append(parent)

    for segments in composite_rows:
        label = " | ".join(c["text"].strip() for c in segments)
        uid = "sample_" + digest({"document_id": document_id, "segments": [normalize_label(c["text"]) for c in segments], "level": "material"})[:24]
        entry = entries.setdefault(uid, {"sample_id": uid, "sample_label_primary": label, "sample_label_aliases": [],
            "sample_level": "material", "parent_sample_ids": [], "member_sample_ids": [], "legacy_sample_ids": [],
            "composition": None, "treatment": None, "process_context": [], "source_evidence": [], "label_status": "explicit",
            "refers_to_entity": None, "legacy_sample": None, "label_segment_paths": []})
        entry["label_segment_paths"].append([c["cell_id"] for c in segments])
        entry["source_evidence"].extend({"block_id": c["table_id"], "cell_id": c["cell_id"], "source_quote": c["text"], "source_type": "table"} for c in segments)
        for c in segments:
            if c["cell_id"] in group_cells:
                for parent in label_map.get(normalize_label(c["text"]), []):
                    entries[parent]["sample_level"] = "sample_family"
                    entries[parent]["label_status"] = "group_only"
                    entries[parent]["member_sample_ids"].append(uid)
                    entry.setdefault("family_sample_ids", []).append(parent)

    for sample in stage3.get("samples", []):
        for uid in legacy.get(sample.get("sample_id"), []):
            parents = {parent for step in producers.get(sample.get("sample_id"), []) for sid in step.get("input_sample_ids", []) for parent in legacy.get(sid, []) if parent != uid}
            entries[uid]["parent_sample_ids"] = sorted(parents)
    samples = sorted(entries.values(), key=lambda x: x["sample_id"])
    for sample in samples:
        for key in ("member_sample_ids", "family_sample_ids"):
            if key in sample:
                sample[key] = sorted(set(sample[key]))
    # IDs are order-independent except when source-identical Stage3 records
    # cannot be distinguished without their legacy identity (kept ambiguous).
    stable_samples = [{k: v for k, v in s.items() if k not in {"legacy_sample_ids", "legacy_sample"}} for s in samples]
    reviewed = _reviewed_aliases(stage0, stage3, blocks, cells, alias_reviews)
    return {"schema_version": CATALOG_VERSION, "document_id": document_id, "samples": samples,
            "reviewed_source_aliases": reviewed,
            "catalog_sha256": digest(stable_samples), "legacy_mapping": {k: sorted(set(v)) for k, v in sorted(legacy.items())},
            "source_sha256": digest(stage0), "stage3_sha256": digest(stage3)}


def resolve_labels(labels: list[str], catalog: dict) -> dict:
    matches, groups, observed = set(), set(), []
    matched_aliases: dict[str, list[str]] = defaultdict(list)
    for label in labels:
        key = normalize_label(label)
        if not key:
            continue
        for sample in catalog["samples"]:
            names = [sample["sample_label_primary"], *sample["sample_label_aliases"]]
            if sample["label_status"] != "unresolved" and key in {normalize_label(x) for x in names}:
                (groups if sample["sample_level"] == "sample_family" else matches).add(sample["sample_id"])
                observed.append(label)
                matched_aliases[sample["sample_id"]].append(label)
    status = "resolved" if len(matches) == 1 else "ambiguous" if len(matches) > 1 else "group_only" if groups else "unresolved"
    binding_status = {
        "resolved": "resolved",
        "ambiguous": "ambiguous",
        "group_only": "ambiguous",
        "unresolved": "unbound",
    }[status]
    matched_entries = [s for s in catalog["samples"] if s["sample_id"] in matches]
    entity_ids = sorted({s["refers_to_entity"] for s in matched_entries if s.get("refers_to_entity")})
    entity_id = entity_ids[0] if len(entity_ids) == 1 and all(s.get("refers_to_entity") for s in matched_entries) else None
    if status == "ambiguous" and entity_id:
        binding_status = "entity_confirmed_sample_ambiguous"
    basis = "exact_or_alias_label" if matches or groups else "no_unique_label_evidence"
    return {
        # Keep the legacy field for existing review reports. The canonical
        # status is exposed separately so downstream code can distinguish a
        # family/group hit from a concrete sample resolution.
        "sample_binding_status": status,
        "binding_status": binding_status,
        "binding_basis": basis,
        "entity_id": entity_id,
        "entity_candidate_ids": entity_ids,
        "entity_binding_basis": "explicit_stage3_relation" if entity_id else None,
        "sample_id": next(iter(matches)) if len(matches) == 1 else None,
        "sample_candidate_ids": sorted(matches),
        "sample_group_ids": sorted(groups),
        "observed_labels": sorted(set(observed)),
        "matched_label_map": {
            sample_id: sorted(set(values))
            for sample_id, values in sorted(matched_aliases.items())
        },
    }


def resolve_axis(axis_cells: list[dict], catalog: dict) -> dict:
    ids = {c["cell_id"] for c in axis_cells}
    composites = [s["sample_label_primary"] for s in catalog["samples"] if any(set(p).issubset(ids) for p in s.get("label_segment_paths", []))]
    result = resolve_labels(composites or [c["text"] for c in axis_cells], catalog)
    result["binding_basis"] = "table_axis_label"
    result["evidence_cell_ids"] = [c["cell_id"] for c in axis_cells if c.get("cell_id")]
    return result


def materialize_stage3(stage3: dict, catalog: dict, stage0: dict) -> tuple[dict, dict[str, str]]:
    """Build a separate compatible Stage3 snapshot for a reviewed publication run."""
    result = copy.deepcopy(stage3)
    blocks, cells = source_index(stage0)
    mapping = {}
    used = {s["sample_id"] for s in result["samples"]}
    for sample in catalog["samples"]:
        if sample["sample_level"] == "sample_family" or sample["label_status"] == "unresolved":
            continue
        if len(sample["legacy_sample_ids"]) == 1:
            mapping[sample["sample_id"]] = sample["legacy_sample_ids"][0]
            continue
        sid = "s" + str(int(sample["sample_id"].split("_")[1], 16))
        if sid in used:
            raise ValueError("sample compatibility ID collision")
        ev = next((e for e in sample["source_evidence"] if e.get("cell_id") in cells), None)
        if ev is None:
            continue
        cell, block = cells[ev["cell_id"]], blocks[ev["block_id"]]
        evidence = {"block_id": block["block_id"], "page": block["page"], "bbox": block.get("bbox"), "source_type": "table", "source_sentence": cell["text"],
                    "table_locator": {"table_id": block["block_id"], "cell_id": cell["cell_id"], "row_index": cell["row_index"], "column_index": cell["column_index"], "cell_value": cell["text"],
                                      "row_label": cell["text"], "column_label": next((c["text"] for c in cells.values() if c["table_id"] == cell["table_id"] and c["column_index"] == cell["column_index"] and c["row_index"] == 0), cell["text"])}}
        result["samples"].append({"sample_id": sid, "sample_kind": "unspecified", "polymer_name": sample["sample_label_primary"],
                                  "sample_label_raw": sample["sample_label_primary"], "evidence": evidence})
        mapping[sample["sample_id"]] = sid
        used.add(sid)
    return result, mapping
