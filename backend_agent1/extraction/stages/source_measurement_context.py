"""Source condition evidence shared by primary records and historical candidates."""
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from stages.property_path_resolver import resolve_property_paths
from stages.table_cell_roles import classify_table_cells
from stages.source_condition_comparison import compare_source_conditions


REVIEWS = Path(__file__).resolve().parents[1] / "config/source_table_reviews.v1.json"


def table_review_hash(block):
    content = {k: block.get(k) for k in ("block_id", "table_body", "table_cells", "caption", "table_notes")}
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def build_source_context_index(stage0, indexes, reviews=None):
    blocks, source_cells = indexes
    if reviews is None:
        reviews = json.loads(REVIEWS.read_text(encoding="utf-8")) if REVIEWS.is_file() else {"reviews": []}
    table_cells = defaultdict(list)
    for cell in source_cells.values():
        table_cells[cell["table_id"]].append(cell)
    roles, paths = {}, {}
    for bid, cells in table_cells.items():
        annotations = classify_table_cells(cells)
        roles.update({r["cell_id"]: r for r in annotations})
        for path in resolve_property_paths(cells, annotations):
            for axis in path["condition_axes"] + path["composition_axes"]:
                axis["condition_kind"] = "unspecified"
                for review in reviews.get("reviews", []):
                    if (review.get("document_id") != stage0["document_id"] or review.get("table_id") != bid
                            or review.get("table_sha256") != table_review_hash(blocks[bid])
                            or axis["header_cell_ids"] != review.get("header_cell_ids")
                            or axis["header_path"] != review.get("header_path")):
                        continue
                    axis["source_review"] = deepcopy(review)
                    axis["condition_kind"] = review["condition_kind"]
                    if (axis["association_status"] == "candidate"
                            and axis["association_reasons"] == ["context_role_requires_review"]):
                        axis.update(association_status="source_aligned", association_reasons=[], role_confidence="confirmed")
            paths[path["target_cell_id"]] = path
    return {"roles": roles, "paths": paths, "cells": source_cells}


def source_context_for(candidate, audit, index):
    ids = audit.get("source_cell_ids", [])
    if (len(ids) != 1 or audit.get("evidence_status") != "source_cell_verified"
            or "value_not_in_target_cell" in audit.get("check_reasons", [])):
        return None
    path = index["paths"].get(ids[0])
    if not path or not (path["condition_axes"] or path["composition_axes"]):
        return None
    axes = path["condition_axes"] + path["composition_axes"]
    statuses = {a["association_status"] for a in axes}
    context = {
        "authority": "source_table_condition_evidence", "table_id": index["cells"][ids[0]]["table_id"],
        "target_cell_id": ids[0],
        "status": "ambiguous" if "ambiguous" in statuses else "candidate" if "candidate" in statuses else "source_aligned",
        "condition_axes": deepcopy(path["condition_axes"]), "composition_axes": deepcopy(path["composition_axes"]),
        "evidence_cell_ids": list(dict.fromkeys([ids[0], *(cid for axis in axes for cid in [axis["cell_id"], *axis["header_cell_ids"]])])),
    }
    comparison = compare_source_conditions(context, candidate)
    context.update(declared_context_comparison=comparison["status"], declared_context_audit=comparison)
    return context


def source_context_blockers(context):
    if not context:
        return []
    if context["declared_context_comparison"] == "conflict":
        return ["source_condition_conflict"]
    if context["status"] != "source_aligned" or context["declared_context_comparison"] == "needs_review":
        return ["source_condition_requires_review"]
    # An explicit source condition can supply a missing model field, in its own
    # provenance-bearing namespace, without claiming the model stated it.
    return []
