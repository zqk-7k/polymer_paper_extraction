"""Shared source packets and conservative, order-independent binding validation."""
from __future__ import annotations

import copy
import re
from decimal import Decimal
from functools import lru_cache
from collections import defaultdict
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from stages.sample_catalog import SAMPLE_HEADER, digest, normalize_label, resolve_axis, resolve_labels, source_index
from stages.table_recall_audit import _load_property_patterns, _normalized_text, _property_match
from stages.figure_evidence import related_figures
from stages.binding_identity import build_article_sample_key, classify_binding_status
from stages.measurement_record import measurement_record_from_candidate

BINDING_VERSION = "sample_binding.v6"
STAGE4_FILES = ("stage4_properties.unified_preview.json", "stage4_properties.json", "stage4_properties.recovery_preview.json")


class BindingReview(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    review_id: str
    property_id: str
    selected_sample_id: str | None
    selected_entity_id: str | None = None
    article_sample_key: str | None = None
    sample_label_observed: str
    sample_label_observed_exact: str | None = None
    binding_basis: Literal["row_label", "column_label", "caption", "footnote", "text"] | None = None
    reasoning_status: Literal["accepted", "ambiguous", "rejected", "not_verifiable"]
    reasoning: str
    source_quote: str
    evidence_ids: list[str]
    confidence: float = Field(ge=0, le=1)


def evidence_objects(item: Any) -> list[dict]:
    result = []
    if isinstance(item, dict):
        if any(item.get(k) for k in ("block_id", "table_id", "cell_id")):
            result.append(item)
        for key, child in item.items():
            if key not in {"original_candidate", "stage3_samples"}:
                result.extend(evidence_objects(child))
    elif isinstance(item, list):
        for child in item:
            result.extend(evidence_objects(child))
    return result


def collect_candidates(files: dict, document_id: str) -> list[dict]:
    result = {}

    def source_stage(filename: str) -> str:
        if filename == "stage5_characterizations.json":
            return "stage5"
        if filename == "stage4t_shadow.json":
            return "stage4t"
        if "recovery" in filename:
            return "stage4r"
        if filename == "candidate.json":
            return "candidate"
        if filename == "final.json":
            return "final"
        return "stage4"

    def add(item: dict, filename: str, collection: str, parent: dict | None = None):
        original = copy.deepcopy(item)
        inherited = dict(parent or {})
        if any(original.get(k) for k in ("sample_id", "entity_id", "sample_ids", "entity_ids")) or original.get("sample_resolution_status") == "unresolved":
            for key in ("sample_id", "entity_id", "sample_ids", "entity_ids"):
                inherited.pop(key, None)
        row = {**inherited, **original}
        if not any(original.get(k) for k in ("sample_id", "entity_id", "sample_ids", "entity_ids")) and original.get("sample_resolution_status") != "unresolved":
            row.update({key: inherited[key] for key in ("sample_id", "entity_id", "sample_ids", "entity_ids") if key in inherited})
        if row.get("value_raw") is None or str(row.get("value_raw")).strip() == "":
            return
        row.pop("points", None)
        evidence_registry = {e.get("evidence_id"): e for e in files[filename].get("evidence", []) if isinstance(e, dict)}
        if not row.get("evidence") and row.get("evidence_ids"):
            row["evidence"] = [evidence_registry[e] for e in row["evidence_ids"] if e in evidence_registry]
        if not row.get("measurement_context"):
            conditions = {c.get("condition_id"): c for c in files[filename].get("measurement_conditions", [])}
            if row.get("measurement_condition_id") in conditions:
                row["measurement_context"] = conditions[row["measurement_condition_id"]]
        measurement_record = measurement_record_from_candidate(
            row, document_id=document_id, source_stage=source_stage(filename),
        )
        property_id = str(row.get("property_id") or row.get("specialized_id") or row.get("unresolved_id") or row.get("point_id") or row.get("observation_id") or "")
        identity = {"document_id": document_id, "source_file": filename, "collection": collection,
                    "property": row.get("property_name_raw") or row.get("semantic_label") or row.get("property_name_normalized"),
                    "value_raw": row["value_raw"], "unit_raw": row.get("unit_raw"),
                    "property_id": property_id, "sample_id_candidate": row.get("sample_id"),
                    "evidence": sorted(evidence_objects(row), key=digest), "conditions": row.get("measurement_context") or row.get("conditions")}
        rid = "binding_" + digest(identity)[:24]
        # Preserve exact source objects; no standard-set record participates in the key.
        record = {"review_id": rid, "property_id": property_id or rid, "document_id": document_id,
                  "source_file": filename, "source_collection": collection, "candidate": row, "original_candidate": original}
        if measurement_record is not None:
            record["measurement_record"] = measurement_record.model_dump(mode="json")
        if rid in result and result[rid]["candidate"] != row:
            raise ValueError("Conflicting candidate identity")
        result[rid] = record

    for filename in (*STAGE4_FILES, "stage5_characterizations.json", "candidate.json", "final.json"):
        payload = files.get(filename)
        if not isinstance(payload, dict):
            continue
        for key in ("properties", "unresolved_properties", "specialized_property_observations", "property_observations", "unresolved_property_observations"):
            for item in payload.get(key, []):
                add(item, filename, key)
        for series in payload.get("property_series", []):
            for point in series.get("points", []):
                add(point, filename, "property_series.points", series)
    shadow = files.get("stage4t_shadow.json", {})
    for table in shadow.get("tables", []):
        for key in ("observations", "shadow_observations", "llm_enriched_observations", "property_candidates"):
            for item in table.get(key, []):
                add(item, "stage4t_shadow.json", "tables." + key, {"table_id": table.get("table_id"), "table_direction": table.get("direction"), "table_sample_axis": table.get("sample_axis")})
    return sorted(result.values(), key=lambda x: x["review_id"])


def _covers(cell: dict, target: dict, axis: str) -> bool:
    return cell[axis + "_index"] <= target[axis + "_index"] < cell[axis + "_index"] + cell[axis + "_span"]


def value_in_source(value: str, source: str) -> bool:
    value, source = normalize_label(value), normalize_label(source)
    if not value:
        return False
    if value == source:
        return True
    return bool(re.search(r"(?<![0-9.e+\-])" + re.escape(value) + r"(?![0-9.e+\-])", source))


def _preceding_group_row(table_cells: list[dict], target: dict, catalog: dict) -> dict | None:
    """Return the nearest explicit full-width sample group row, if it resolves.

    Many source tables put a polymer name in a merged row and list only doses in
    the following rows.  The group row is table-owned evidence, so it may be
    used when the target's row/column axes do not already identify a sample.
    Requiring a merged row that spans the complete table and a catalog match
    prevents ordinary numeric or property rows from becoming bindings.
    """
    if not table_cells:
        return None
    table_width = max((c["column_index"] + c["column_span"] for c in table_cells), default=0)
    if table_width < 2:
        return None
    rows = sorted({c["row_index"] for c in table_cells if c["row_index"] < target["row_index"]}, reverse=True)
    for row_index in rows:
        candidates = [c for c in table_cells if c["row_index"] == row_index and c["text"].strip()
                      and c["column_index"] == 0 and c["column_span"] >= table_width]
        if not candidates:
            continue
        # A row can contain only one full-width cell in a valid table.  Keep
        # ambiguity visible if malformed input contains multiple candidates.
        resolutions = [resolve_labels([c["text"]], catalog) for c in candidates]
        valid = [(c, r) for c, r in zip(candidates, resolutions)
                 if r["sample_binding_status"] in {"resolved", "ambiguous", "group_only"}]
        if len(valid) == 1:
            return valid[0][0]
        if len(valid) > 1:
            return None
    return None


def table_context(block: dict) -> list[dict]:
    """Cite original table-owned captions/notes, preserving their individual text."""
    result = []
    values = [("caption", block.get("caption")), ("table_notes", block.get("table_notes"))]
    content = block.get("content")
    if isinstance(content, dict):
        values.extend((key, content.get(key)) for key in ("table_caption", "table_footnote", "footnotes", "notes"))
    for key, value in values:
        for index, text in enumerate(value if isinstance(value, list) else [value]):
            if not isinstance(text, str) or not text.strip():
                continue
            evidence_id = f"{block['block_id']}__{key}_{index}"
            result.append({"evidence_id": evidence_id, "text": text, "table_id": block["block_id"],
                           "page": block.get("page"), "source_type": "table_caption" if "caption" in key else "table_note"})
    return result


def labels_in_text(text: str, catalog: dict) -> list[str]:
    return sorted({label for sample in catalog["samples"]
                   for label in [sample["sample_label_primary"], *sample.get("sample_label_aliases", [])]
                   if label and re.search(r"(?<![\w-])" + re.escape(label) + r"(?![\w-])", text, re.I)})


def build_packet(record: dict, stage0: dict, catalog: dict, *, indexes=None, source_hash=None) -> dict:
    blocks, cells = indexes if indexes is not None else source_index(stage0)
    candidate = record["candidate"]
    locators = evidence_objects(candidate)
    target_ids, requested_blocks, locator_errors = set(), set(), []
    for loc in locators:
        cid = loc.get("cell_id")
        bid = loc.get("table_id") or loc.get("block_id")
        if bid in blocks:
            requested_blocks.add(bid)
        if cid:
            if cid not in cells:
                locator_errors.append("evidence_id_missing")
                continue
            cell = cells[cid]
            if any(loc.get(k) is not None and loc[k] != cell[k] for k in ("table_id", "row_index", "column_index")):
                locator_errors.append("locator_conflict")
                continue
            target_ids.add(cid)
        elif bid in blocks and isinstance(loc.get("row_index"), int) and isinstance(loc.get("column_index"), int):
            matches = [c for c in cells.values() if c["table_id"] == bid and c["row_index"] <= loc["row_index"] < c["row_index"] + c["row_span"] and c["column_index"] <= loc["column_index"] < c["column_index"] + c["column_span"]]
            if len(matches) == 1:
                target_ids.add(matches[0]["cell_id"])
            else:
                locator_errors.append("locator_not_unique")
    # Evidence may contain a condition/label cell as well as the value cell.
    raw_value = str(candidate["value_raw"])
    value_norm = normalize_label(raw_value)
    targets = [cells[x] for x in sorted(target_ids) if value_in_source(raw_value, cells[x]["text"])]
    if target_ids and not targets:
        locator_errors.append("value_not_in_target_cell")
    if not target_ids:
        # Exact value recovery is permitted only inside an explicitly referenced table,
        # and only if the location is unique. Never bind by candidate/value order.
        recovered = [c for c in cells.values() if c["table_id"] in requested_blocks and normalize_label(c["text"]) == value_norm]
        if len(recovered) == 1:
            targets = recovered
        elif len(recovered) > 1:
            locator_errors.append("value_location_ambiguous")
    registry, paths = {}, []
    for target in targets:
        table_cells = [c for c in cells.values() if c["table_id"] == target["table_id"]]
        row = [c for c in table_cells if _covers(c, target, "row")]
        headers = [c for c in table_cells if _covers(c, target, "column") and c["row_index"] < target["row_index"]]
        left = [c for c in row if c["column_index"] < target["column_index"]]
        # Only header rows are column labels; preceding numeric body cells are never labels.
        above = [c for c in headers if c["is_header"] or c["row_index"] == 0]
        axes = {c["cell_id"]: c for c in [*left, *above]}
        group_row = None
        initial_resolution = resolve_axis(list(axes.values()), catalog)
        if initial_resolution["sample_binding_status"] == "unresolved":
            group_row = _preceding_group_row(table_cells, target, catalog)
            if group_row is not None:
                # A full-width, catalog-resolved row is explicit table
                # evidence.  Add it to the axis so deterministic review and
                # the LLM receive the same binding basis.
                axes[group_row["cell_id"]] = group_row
        inherited = []
        for blank in left:
            if blank["text"].strip():
                continue
            if not any(c["column_index"] == blank["column_index"] and c["row_index"] == 0 and SAMPLE_HEADER.fullmatch(c["text"].strip()) for c in table_cells):
                continue
            # Explicit rowspan is already handled by _covers. An unmarked blank is
            # context for semantic review and cannot silently establish a binding.
            prior = [c for c in table_cells if c["column_index"] == blank["column_index"] and c["row_index"] < target["row_index"] and c["text"].strip()]
            if prior:
                inherited.append(max(prior, key=lambda x: x["row_index"]))
        neighbors = [c for c in table_cells if abs(c["row_index"] - target["row_index"]) <= 1]
        # Include all table header cells, including multirow headers.
        full_headers = [c for c in table_cells if c["is_header"] or c["row_index"] == 0]
        for c in [target, *row, *headers, *neighbors, *full_headers, *inherited]:
            registry[c["cell_id"]] = {"evidence_id": c["cell_id"], "text": c["text"], "source_type": "table", **c}
        context = table_context(blocks[target["table_id"]])
        for evidence in context:
            registry[evidence["evidence_id"]] = evidence
        caption = str(blocks[target["table_id"]].get("caption") or "")
        paths.append({"target_cell_id": target["cell_id"], "table_id": target["table_id"],
                      "row_index": target["row_index"], "column_index": target["column_index"],
                      "axis_cell_ids": sorted(axes), "inherited_cell_ids": sorted(c["cell_id"] for c in inherited),
                      "group_row_cell_ids": [group_row["cell_id"]] if group_row else [],
                      "header_cell_ids": sorted(c["cell_id"] for c in full_headers),
                      "caption": caption, "context_evidence_ids": [e["evidence_id"] for e in context],
                      "sample_resolution": resolve_axis(list(axes.values()), catalog),
                      "context_resolution": resolve_axis([*axes.values(), *inherited], catalog)})
        requested_blocks.add(target["table_id"])
    ordered = sorted(blocks.values(), key=lambda x: x.get("source_block_index", 0))
    source_blocks = set(requested_blocks)
    for i, block in enumerate(ordered):
        if block["block_id"] in requested_blocks:
            source_blocks.update(x["block_id"] for x in ordered[max(0, i-1):i+2] if x.get("type") in {"text", "footnote", "title"})
    for bid in sorted(source_blocks):
        block = blocks[bid]
        registry[bid] = {"evidence_id": bid, "text": block.get("text") or block.get("table_body") or block.get("caption") or "", "source_type": "figure_caption" if block.get("type") == "image" else block.get("type"), "page": block.get("page")}
        if block.get("type") == "image":
            registry[bid]["image_path"] = block.get("image_path")
    observed = sorted({label for path in paths for label in path["sample_resolution"]["observed_labels"]})
    resolution = resolve_labels(observed, catalog)
    if not paths:
        resolution = resolve_labels([], catalog)
    reasons = list(locator_errors)
    if not candidate.get("sample_id"):
        reasons.append("candidate_sample_id_missing")
    if resolution["sample_binding_status"] == "group_only":
        reasons.append("sample_granularity_mismatch")
    elif resolution["sample_binding_status"] == "ambiguous":
        reasons.append("article_label_ambiguous")
    elif resolution["sample_binding_status"] == "unresolved":
        reasons.append("stage3_alias_missing" if paths else "row_label_not_propagated")
    candidate_uid = catalog["legacy_mapping"].get(candidate.get("sample_id"), [])
    if len(candidate_uid) == 1 and resolution["sample_id"] and candidate_uid[0] != resolution["sample_id"]:
        reasons.append("candidate_sample_conflict")
    packet = {**record, "schema_version": BINDING_VERSION, "catalog_sha256": catalog["catalog_sha256"],
              "stage3_sha256": catalog["stage3_sha256"], "source_sha256": source_hash or digest(stage0),
              "value_raw": raw_value, "unit_raw": candidate.get("unit_raw"),
              "property_name": candidate.get("property_name_raw") or candidate.get("property_name_normalized") or candidate.get("semantic_label"),
              "sample_id_candidate": candidate_uid[0] if len(candidate_uid) == 1 else None,
              "stage3_samples": [{k: v for k, v in s.items() if k != "legacy_sample"} for s in catalog["samples"]],
              "source_evidence": registry, "evidence_paths": paths, "source_block_ids": sorted(requested_blocks),
              "measurement_context": {**(candidate.get("measurement_context") or candidate.get("conditions") or {}),
                                      "determination_method_raw": candidate.get("determination_method_raw") or candidate.get("method_raw")},
              "deterministic_binding": resolution, "failure_reasons": sorted(set(reasons)), "locator_errors": sorted(set(locator_errors))}
    packet["figure_context"] = related_figures(stage0, source_blocks)
    packet["input_sha256"] = digest(packet)
    return packet


def _contains_quote(quote: str, source: str) -> bool:
    # Representation-only normalization, never punctuation stripping or ellipsis joining.
    return bool(quote.strip()) and re.sub(r"\s+", " ", quote).strip() in re.sub(r"\s+", " ", source).strip()


def condition_conflicts(packet: dict, path: dict | None) -> list[str]:
    registry = packet["source_evidence"]
    ids = ([path["target_cell_id"], *path["axis_cell_ids"]] if path else packet["source_block_ids"])
    source = " ".join(registry[x]["text"] for x in ids if x in registry)
    if path:
        source += " " + str(path.get("caption") or "")
    expected = str(packet["measurement_context"])
    conflicts = []
    for first, second, code in ((r"\bac\b", r"\bdc\b", "ac_dc_conflict"), (r"\bdry\b", r"\bwet\b", "dry_wet_conflict")):
        es = (bool(re.search(first, expected, re.I)), bool(re.search(second, expected, re.I)))
        ss = (bool(re.search(first, source, re.I)), bool(re.search(second, source, re.I)))
        if (es == (True, False) and ss[1]) or (es == (False, True) and ss[0]):
            conflicts.append(code)
    for pattern, code in ((r"([-+]?\d+(?:\.\d+)?)\s*(?:°\s*C|℃)\b?", "temperature_conflict"), (r"(\d+(?:\.\d+)?)\s*(kHz|MHz|Hz)\b", "frequency_conflict")):
        # Strip the optional boundary after a non-word temperature sign.
        pattern = pattern.replace("\\b?", "")
        expected_values = set(re.findall(pattern, expected, re.I))
        source_values = set(re.findall(pattern, source, re.I))
        if expected_values and source_values and expected_values.isdisjoint(source_values):
            conflicts.append(code)
    methods = r"\b(?:DSC|DMA|TGA|GPC|SEC|DTA)\b"
    expected_methods = {x.casefold() for x in re.findall(methods, expected, re.I)}
    source_methods = {x.casefold() for x in re.findall(methods, source, re.I)}
    if expected_methods and source_methods and expected_methods.isdisjoint(source_methods):
        conflicts.append("measurement_method_conflict")
    volts = r"(?<![A-Za-z])(\d+(?:\.\d+)?)\s*(mV|kV|V)\b"
    expected_volts, source_volts = set(re.findall(volts, expected)), set(re.findall(volts, source))
    if expected_volts and source_volts and expected_volts.isdisjoint(source_volts):
        conflicts.append("voltage_conflict")
    return conflicts


@lru_cache(maxsize=1)
def _patterns():
    return _load_property_patterns()


def property_on_path(packet: dict, path: dict) -> bool:
    source = " | ".join(packet["source_evidence"][x]["text"] for x in path["axis_cell_ids"])
    raw = packet.get("property_name") or ""
    if normalize_label(raw) and normalize_label(raw) in normalize_label(source):
        return True
    expected = packet["candidate"].get("property_name_normalized") or _property_match(_normalized_text(raw), _patterns())
    observed = {_property_match(_normalized_text(packet["source_evidence"][x]["text"]), _patterns()) for x in path["axis_cell_ids"]}
    return bool(expected and expected in observed)


def process_condition_conflicts(packet: dict, selected: str, path: dict | None, ids: set[str]) -> list[str]:
    """Compare explicit irradiation doses, never treat every process number as a dose."""
    registry = packet["source_evidence"]
    sample = next((s for s in packet["stage3_samples"] if s["sample_id"] == selected), {})
    expected = " ".join(str(value) for step in sample.get("process_context", [])
                        for key, value in step.get("parameters", {}).items() if re.search(r"dose|剂量", key, re.I))
    source = " ".join(registry[x]["text"] for x in ids if x in registry and registry[x].get("source_type") != "table")
    if path:
        source += " " + " ".join(registry[x]["text"] for x in path["axis_cell_ids"])
        # Recover the unit of a numeric dose cell from its own column header.
        for cell_id in path["axis_cell_ids"]:
            cell = registry[cell_id]
            if not re.fullmatch(r"\d+(?:\.\d+)?", cell["text"].strip()):
                continue
            for header_id in path["header_cell_ids"]:
                header = registry[header_id]
                if _covers(header, cell, "column") and re.search(r"dose|剂量", header["text"], re.I) and re.search(r"kGy", header["text"], re.I):
                    source += " " + cell["text"] + " kGy"
    doses = lambda text: {Decimal(value) for value in re.findall(r"(?<![\d.])(\d+(?:\.\d+)?)\s*kGy\b", text, re.I)}
    first, second = doses(expected), doses(source)
    return ["process_dose_conflict"] if first and second and first.isdisjoint(second) else []


def _review_label(review: dict) -> str:
    """Prefer the exact source label over a model's explanatory row summary."""
    return str(review.get("sample_label_observed_exact") or review.get("sample_label_observed") or "").strip()


def _label_in_text(label: str, text: str) -> bool:
    if not label or not text:
        return False
    if re.search(r"(?<![\w-])" + re.escape(label) + r"(?![\w-])", text, re.I):
        return True
    normalized = normalize_label(label)
    return bool(normalized and re.search(
        r"(?<![\w-])" + re.escape(normalized) + r"(?![\w-])", normalize_label(text), re.I
    ))


def _selected_axis_labels(packet: dict, selected: str, ids: set[str], *, allow_inherited: bool) -> list[str]:
    registry = packet["source_evidence"]
    labels = []
    for path in packet["evidence_paths"]:
        axis_ids = path["axis_cell_ids"] + (path["inherited_cell_ids"] if allow_inherited else [])
        axis = resolve_axis([registry[x] for x in axis_ids if x in ids and x in registry], {"samples": packet["stage3_samples"]})
        if axis.get("sample_binding_status") == "resolved" and axis.get("sample_id") == selected:
            labels.extend(axis.get("observed_labels", []))
    return sorted(set(labels))


def _article_alias_paths(packet: dict, label: str, ids: set[str]) -> list[dict]:
    """Find a unique table path for an article-local label absent from Stage3."""
    registry = packet["source_evidence"]
    paths = []
    for path in packet["evidence_paths"]:
        if path["target_cell_id"] not in ids:
            continue
        axis_ids = [x for x in path["axis_cell_ids"] if x in ids and x in registry]
        if not any(_label_in_text(label, registry[x]["text"]) for x in axis_ids):
            continue
        if not property_on_path(packet, {**path, "axis_cell_ids": axis_ids}):
            continue
        paths.append(path)
    return paths


def validate_review(response: dict, packet: dict, *, allow_inherited: bool = True) -> dict:
    """Validate a model response against a freshly rebuilt Stage0 packet."""
    reasons = list(packet.get("locator_errors", []))
    try:
        review = BindingReview.model_validate(response).model_dump()
    except (ValueError, TypeError):
        return {"reasoning_status": "not_verifiable", "validation_passed": False,
                "validation_errors": ["invalid_review_schema"], "selected_sample_id": None,
                "binding_status": "unresolved"}
    if review["review_id"] != packet["review_id"] or review["property_id"] != packet["property_id"]:
        reasons.append("review_identity_mismatch")
    registry = packet["source_evidence"]
    ids = set(review["evidence_ids"])
    if not ids or not ids.issubset(registry):
        reasons.append("evidence_id_missing")
    if review["source_quote"] and not any(_contains_quote(review["source_quote"], registry[x]["text"]) for x in ids if x in registry):
        reasons.append("source_quote_not_verbatim")
    selected = review["selected_sample_id"]
    observed_label = _review_label(review)
    samples = {s["sample_id"]: s for s in packet["stage3_samples"]}
    if selected is not None and selected not in samples:
        reasons.append("unknown_sample_id")
    if review["reasoning_status"] == "accepted":
        if selected is None:
            # An article-local label can be valid even when Stage3 has no sample
            # record (for example, a monomer table). Keep the alias auditable and
            # require a unique table path before accepting it.
            selected_entity = review.get("selected_entity_id")
            known_entities = {item.get("entity_id") for item in packet.get("stage2_entities", [])}
            if selected_entity and known_entities and selected_entity not in known_entities:
                reasons.append("unknown_entity_id")
            if not review.get("article_sample_key") and not selected_entity:
                reasons.append("sample_or_entity_binding_missing")
            alias_paths = _article_alias_paths(packet, observed_label, ids)
            if review.get("article_sample_key") and len(alias_paths) != 1:
                reasons.append("article_sample_evidence_path_missing")
            elif len(alias_paths) == 1:
                alias_path = alias_paths[0]
                review["article_sample_key"] = build_article_sample_key(
                    packet["document_id"], alias_path["table_id"], observed_label,
                    variant_context=packet.get("measurement_context"),
                    entity_id=selected_entity,
                )
                reasons.extend(condition_conflicts(packet, alias_path))
                reasons.extend(process_condition_conflicts(packet, selected, alias_path, ids))
            checked_status = "not_verifiable" if reasons else review["reasoning_status"]
            return {**review, "reasoning_status": checked_status,
                    "validation_passed": not reasons, "validation_errors": sorted(set(reasons)),
                    "binding_status": classify_binding_status(
                        selected_sample_id=selected,
                        selected_entity_id=review.get("selected_entity_id"),
                        article_sample_key=review.get("article_sample_key"),
                        reasoning_status=checked_status,
                        validation_passed=not reasons,
                        validation_errors=sorted(set(reasons)),
                    )}
        chain = packet.get("sample_chains", {}).get(selected, {})
        reasons.extend(chain.get("errors", []))
        # An explicit entity on the candidate must agree with the chosen sample.
        claimed_entity = packet.get("candidate", {}).get("entity_id")
        if claimed_entity and chain.get("entity_ids") and claimed_entity not in chain["entity_ids"]:
            reasons.append("candidate_entity_conflict")
        if not review["source_quote"]:
            reasons.append("source_quote_missing")
        resolved = resolve_labels([observed_label], {"samples": packet["stage3_samples"]})
        selected_axis_labels = _selected_axis_labels(packet, selected, ids, allow_inherited=allow_inherited)
        if ((resolved["sample_binding_status"] != "resolved" or resolved["sample_id"] != selected)
                and selected not in {resolve_labels([label], {"samples": packet["stage3_samples"]}).get("sample_id") for label in selected_axis_labels}):
            reasons.append("sample_mapping_not_unique")
        paths = []
        for path in packet["evidence_paths"]:
            axis_ids = path["axis_cell_ids"] + (path["inherited_cell_ids"] if allow_inherited else [])
            whole_resolution = path["context_resolution"] if allow_inherited else path["sample_resolution"]
            axis_resolution = resolve_axis([registry[x] for x in axis_ids if x in ids], {"samples": packet["stage3_samples"]})
            # Table-wide context can supply a missing label, never override an
            # explicit or ambiguous axis. All table-owned notes participate.
            contextual_labels = []
            if allow_inherited and whole_resolution["sample_binding_status"] == "unresolved":
                context_ids = path.get("context_evidence_ids", [])
                contextual_labels = labels_in_text(" ".join(registry[x]["text"] for x in context_ids if x in ids), {"samples": packet["stage3_samples"]})
                all_labels = labels_in_text(" ".join(registry[x]["text"] for x in context_ids), {"samples": packet["stage3_samples"]})
                whole_resolution = resolve_labels(all_labels, {"samples": packet["stage3_samples"]})
            combined_resolution = resolve_labels(axis_resolution["observed_labels"] + contextual_labels, {"samples": packet["stage3_samples"]})
            # All plausible axis samples participate, not just those selected by the model.
            if path["target_cell_id"] in ids and whole_resolution["sample_binding_status"] == "resolved" and combined_resolution["sample_id"] == selected and whole_resolution["sample_id"] == selected:
                if any(normalize_label(observed_label) == normalize_label(x) for x in (axis_resolution["observed_labels"] + contextual_labels)) or selected in {resolve_labels([label], {"samples": packet["stage3_samples"]}).get("sample_id") for label in selected_axis_labels}:
                    paths.append(path)
        if paths:
            for path in paths:
                reasons.extend(condition_conflicts(packet, path))
                reasons.extend(process_condition_conflicts(packet, selected, path, ids))
                if not property_on_path(packet, {**path, "axis_cell_ids": [x for x in path["axis_cell_ids"] if x in ids]}):
                    reasons.append("property_evidence_path_missing")
            if len({p["target_cell_id"] for p in paths}) != 1:
                reasons.append("evidence_path_not_unique")
        else:
            # Text review requires the observed label, property and value in the same
            # original text block. Neighbor paragraphs alone cannot confirm a value.
            supported = [registry[x] for x in ids if x in packet["source_block_ids"] and x in registry and registry[x]["source_type"] in {"text", "footnote"}
                         and _contains_quote(review["source_quote"], registry[x]["text"])
                         and normalize_label(observed_label) in normalize_label(registry[x]["text"])
                         and value_in_source(packet["value_raw"], registry[x]["text"])
                         and normalize_label(packet.get("property_name")) in normalize_label(registry[x]["text"])]
            if len(supported) != 1:
                reasons.append("sample_value_evidence_path_missing")
            else:
                text_labels = [s["sample_label_primary"] for s in samples.values() if re.search(r"(?<![\w-])" + re.escape(s["sample_label_primary"]) + r"(?![\w-])", supported[0]["text"], re.I)]
                if resolve_labels(text_labels, {"samples": packet["stage3_samples"]})["sample_binding_status"] != "resolved":
                    reasons.append("article_label_ambiguous")
                reasons.extend(condition_conflicts(packet, None))
                reasons.extend(process_condition_conflicts(packet, selected, None, ids))
        if any(registry[x]["source_type"] == "image" for x in ids if x in registry):
            reasons.append("image_requires_visual_review")
    checked_status = "not_verifiable" if reasons else review["reasoning_status"]
    return {**review, "reasoning_status": checked_status,
            "validation_passed": not reasons, "validation_errors": sorted(set(reasons)),
            "binding_status": classify_binding_status(
                selected_sample_id=selected,
                selected_entity_id=review.get("selected_entity_id"),
                article_sample_key=review.get("article_sample_key"),
                reasoning_status=checked_status,
                validation_passed=not reasons,
                validation_errors=sorted(set(reasons)),
            )}


def deterministic_review(packet: dict) -> dict:
    binding = packet["deterministic_binding"]
    status = binding["sample_binding_status"]
    selected = binding["sample_id"]
    labels = binding["observed_labels"]
    quote = labels[0] if labels else ""
    ids = sorted({i for p in packet["evidence_paths"] for i in [p["target_cell_id"], *p["axis_cell_ids"]]})
    selected_entry = next((s for s in packet["stage3_samples"] if s["sample_id"] == selected), {})
    source_quote = quote
    if selected_entry.get("label_segment_paths"):
        segment_id = next((x for path in selected_entry["label_segment_paths"] for x in path if x in ids), None)
        if segment_id:
            source_quote = packet["source_evidence"][segment_id]["text"]
    reasoning_status = "accepted" if status == "resolved" else "ambiguous" if status == "ambiguous" else "not_verifiable"
    return {"review_id": packet["review_id"], "property_id": packet["property_id"], "selected_sample_id": selected,
            "sample_label_observed": quote, "reasoning_status": reasoning_status,
            "reasoning": "Unique source axis label" if selected else "No unique source axis label", "source_quote": source_quote,
            "evidence_ids": ids, "confidence": 1.0 if selected else 0.0}
