"""Read-only projection of post-seal human-result comparisons for the reader."""

import json
from pathlib import Path

from .storage import APP, data_root, read
from .name_package import package


def _safe_row(row: dict) -> dict:
    keys = (
        "manual_object", "extraction_object", "source_alias_or_name", "manual_name",
        "manual_name_field", "manual_iupac", "manual_iupac_status", "extraction_iupac_candidate",
        "result", "score", "flags", "note", "comparison_detail", "extraction_identity_package",
    )
    return {k: row[k] for k in keys if k in row}


def _assessments() -> list[dict]:
    found = []
    for run in (APP / "runs").glob("IDENTITY-SIMPLE-NAME-COMPARISON-*"):
        if not run.is_dir():
            continue
        for path in run.glob("papers/*/assessment.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not data.get("model_evaluation_only") or not data.get("extraction_job_id"):
                continue
            data["_path"] = path
            found.append(data)
    return found


def for_job(job_id: str) -> dict:
    matches = [x for x in _assessments() if x.get("extraction_job_id") == job_id]
    if not matches:
        return {"available": False, "job_id": job_id, "rows": [], "by_material_id": {}}
    data = max(matches, key=lambda x: x["_path"].stat().st_mtime_ns)
    candidate = read(data_root() / "jobs" / job_id / "current.json", {}) or {}
    materials = candidate.get("materials", {})
    graphs = candidate.get("graphs", {})
    rows = []
    for source in data.get("rows", []):
        if not isinstance(source, dict):
            continue
        row = dict(source)
        material_id = row.get("extraction_object")
        material = materials.get(material_id) if isinstance(material_id, str) else None
        if material:
            row["extraction_identity_package"] = package(material, graphs)
        rows.append(_safe_row(row))
    by_material_id = {}
    for row in rows:
        key = row.get("extraction_object")
        if isinstance(key, str) and key:
            by_material_id[key] = row
    return {
        "available": True,
        "job_id": job_id,
        "run_id": data["_path"].parents[2].name,
        "paper_id": data.get("paper_id"),
        "manual_kind": data.get("manual_kind", "json"),
        "counts": data.get("counts", {}),
        "source_checks": data.get("source_checks", []),
        "conclusion": data.get("conclusion", ""),
        "rows": rows,
        "by_material_id": by_material_id,
    }
