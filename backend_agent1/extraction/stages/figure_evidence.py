"""Index caption/body evidence and image links. Never inspect image pixels."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

FIGURE_CONTEXT_VERSION = "figure_context.v1"
_REFERENCE = re.compile(r"\b(?:fig(?:ure)?s?\.?)[ \t]*(\d+)(?:[a-z])?\b|图\s*(\d+)", re.I)
_CAPTION = re.compile(r"^\s*(?:fig(?:ure)?\.?\s*|图\s*)(\d+)\b", re.I)


def build_figure_index(stage0: dict, *, asset_root: Path | None = None) -> dict[str, Any]:
    figures = []
    for block in stage0.get("elements", []):
        if block.get("type") != "image":
            continue
        caption = str(block.get("caption") or "")
        match = _CAPTION.search(caption)
        path = block.get("image_path")
        record = {"block_id": block["block_id"], "page": block.get("page"),
            "figure_id": f"Fig.{int(match[1])}" if match else None,
            "caption_raw": caption, "caption_source_type": "figure_caption",
            "image_path": path, "image_sha256": None,
            "image_link_status": "unchecked" if path else "missing_link",
            "body_references": [], "image_value_extraction": "disabled"}
        if path and asset_root is not None:
            candidate = Path(path)
            candidate = candidate if candidate.is_absolute() else asset_root / candidate
            if candidate.is_file():
                record.update(image_link_status="available", resolved_image_path=str(candidate.resolve()),
                    image_sha256=hashlib.sha256(candidate.read_bytes()).hexdigest())
            else:
                record["image_link_status"] = "file_missing"
        figures.append(record)
    by_id = {}
    for figure in figures:
        if figure["figure_id"]:
            by_id.setdefault(figure["figure_id"], []).append(figure)
    unresolved = []
    for block in stage0.get("elements", []):
        if block.get("type") not in {"text", "footnote"}:
            continue
        text = str(block.get("text") or "")
        for match in _REFERENCE.finditer(text):
            fid = f"Fig.{int(match[1] or match[2])}"
            reference = {"block_id": block["block_id"], "page": block.get("page"),
                "reference_raw": match[0], "reference_start": match.start(),
                "body_text_raw": text, "source_type": "figure_body_reference"}
            matches = by_id.get(fid, [])
            if len(matches) == 1:
                matches[0]["body_references"].append(reference)
            else:
                unresolved.append({**reference, "figure_id": fid,
                    "reason": "duplicate_figure_id" if matches else "caption_not_found"})
    return {"schema_version": FIGURE_CONTEXT_VERSION, "document_id": stage0.get("document_id"),
        "figures": figures, "unresolved_references": unresolved,
        "scope": "caption_and_body_text_only", "image_value_extraction": "disabled"}


def related_figures(stage0: dict, block_ids: set[str]) -> list[dict]:
    return [f for f in build_figure_index(stage0)["figures"]
        if f["block_id"] in block_ids or any(r["block_id"] in block_ids for r in f["body_references"])]
