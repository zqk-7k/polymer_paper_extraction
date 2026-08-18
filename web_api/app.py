from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = ROOT / "web_runtime" / "tasks"
BATCH_PARENT = ROOT / "batch_results"


def _read_batch_index_file(root: Path) -> dict[str, Any]:
    try:
        payload = json.loads((root / "RESULT_INDEX.json").read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _select_batch_root(parent: Path, requested: str = "") -> tuple[Path, dict[str, Any]]:
    """Select an explicit collection or the newest indexed batch result."""
    requested = requested.strip()
    if requested and Path(requested).name == requested:
        requested_root = parent / requested
        requested_index = _read_batch_index_file(requested_root)
        if requested_root.is_dir() and requested_index:
            return requested_root, requested_index

    candidates: list[tuple[tuple[str, str, str], Path, dict[str, Any]]] = []
    if parent.is_dir():
        for child in parent.iterdir():
            if not child.is_dir():
                continue
            index = _read_batch_index_file(child)
            if not index:
                continue
            key = (
                str(index.get("result_date") or ""),
                str(index.get("generated_at") or ""),
                child.name,
            )
            candidates.append((key, child, index))

    if candidates:
        _, selected_root, selected_index = max(candidates, key=lambda item: item[0])
        return selected_root, selected_index

    fallback = parent / "demo20_preview_20260809"
    return fallback, {}


BATCH_ROOT, BATCH_INDEX = _select_batch_root(
    BATCH_PARENT,
    os.environ.get("BATCH_RESULTS_COLLECTION", ""),
)
SOURCE_PDF_ROOT = ROOT / "source_pdfs"
EVIDENCE_PREVIEW_ROOT = ROOT / "web_runtime" / "evidence_pages"
POLYINFO_DATA_ROOT = Path(os.environ.get("POLYINFO_DATA_ROOT", str(ROOT.parent / "整理结果" / "polyinfo数据")))
POLYINFO_GROUPS = ("有doi", "无doi")
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", 50 * 1024 * 1024))
REQUIRE_HTTPS_FOR_KEYS = os.environ.get("REQUIRE_HTTPS_FOR_KEYS", "true").lower() not in {"0", "false", "no"}
TASK_ID_RE = re.compile(r"^[a-f0-9]{12}$")
REF_NO_RE = re.compile(r"^reference_no_\d+$")

STAGES = (
    ("stage0", "stage0_blocks.json"),
    ("stage1", "stage1_mentions.json"),
    ("stage2", "stage2_entities.json"),
    ("stage3", "stage3_process.json"),
    ("stage4", "stage4_properties.json"),
    ("stage5", "stage5_characterizations.json"),
    ("result", "candidate.json"),
)

FAILURE_FILES = {
    "stage1": "stage1_failure.json",
    "stage2": "stage2_failure.json",
    "stage3": "stage3_failure.json",
    "stage4": "stage4_failure.json",
    "stage5": "stage5_failure.json",
}

app = FastAPI(title="PolymerLit Extractor API", version="0.3.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
EVIDENCE_PREVIEW_ROOT.mkdir(parents=True, exist_ok=True)
_processes: dict[str, subprocess.Popen[str]] = {}
_process_lock = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _task_root(task_id: str) -> Path:
    if not TASK_ID_RE.fullmatch(task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    root = RUNTIME_ROOT / task_id
    if not root.is_dir():
        raise HTTPException(status_code=404, detail="Task not found")
    return root


def _record_path(root: Path) -> Path:
    return root / "task.json"


def _read_record(root: Path) -> dict[str, Any]:
    try:
        return json.loads(_record_path(root).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="Task metadata is unavailable") from exc


def _write_record(root: Path, record: dict[str, Any]) -> None:
    record["updated_at"] = _utc_now()
    temp = _record_path(root).with_suffix(".tmp")
    temp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(_record_path(root))


def _render_pdf_page(pdf_path: Path, cache_root: Path, page: int) -> Path:
    if page < 0 or page > 5000:
        raise HTTPException(status_code=400, detail="Invalid PDF page")
    if not pdf_path.is_file():
        raise HTTPException(status_code=404, detail="Source PDF not found")

    cache_root.mkdir(parents=True, exist_ok=True)
    output_prefix = cache_root / f"page_{page + 1:04d}"
    output_path = output_prefix.with_suffix(".png")
    if output_path.is_file() and output_path.stat().st_size > 0:
        return output_path

    converter = shutil.which("pdftocairo")
    if not converter:
        raise HTTPException(status_code=503, detail="PDF page renderer is unavailable")
    command = [
        converter,
        "-png",
        "-singlefile",
        "-f",
        str(page + 1),
        "-l",
        str(page + 1),
        "-r",
        "144",
        str(pdf_path),
        str(output_prefix),
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(status_code=503, detail="PDF page rendering failed") from exc
    if completed.returncode != 0 or not output_path.is_file():
        raise HTTPException(status_code=422, detail="Requested PDF page could not be rendered")
    return output_path


def _page_response(path: Path) -> FileResponse:
    return FileResponse(
        path,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


def _load_pipeline_environment() -> dict[str, str]:
    env = os.environ.copy()
    env_path = ROOT / ".env"
    if env_path.is_file():
        for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip("\"'")
            if key and key not in env:
                env[key] = value
    return env


def _result_dir(root: Path, ref_no: str) -> Path:
    return root / "output" / ref_no


def _read_json(path: Path, unavailable_message: str) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=unavailable_message) from exc


def _candidate_overview(candidate: dict[str, Any]) -> dict[str, Any]:
    publication = candidate.get("publication") or {}
    return {
        "paper": candidate.get("paper") or {},
        "stats": {
            "polymer_count": len(candidate.get("polymer_entities") or []),
            "sample_count": len(candidate.get("samples") or []),
            "property_count": len(candidate.get("property_observations") or []),
            "process_count": len(candidate.get("process_steps") or []),
            "characterization_count": len(candidate.get("characterizations") or []),
            "evidence_count": len(candidate.get("evidence") or []),
        },
        "validation_status": publication.get("validation_status"),
    }


def _stage_payload(root: Path, record: dict[str, Any]) -> list[dict[str, Any]]:
    result_dir = _result_dir(root, record["ref_no"])
    running = record.get("status") in {"queued", "running"}
    stages: list[dict[str, Any]] = []
    first_missing_seen = False

    for stage_id, output_name in STAGES:
        output_path = result_dir / output_name
        failure_name = FAILURE_FILES.get(stage_id)
        failure_path = result_dir / failure_name if failure_name else None
        if output_path.is_file():
            status = "complete"
        elif failure_path and failure_path.is_file():
            status = "failed"
        elif running and not first_missing_seen:
            status = "running"
            first_missing_seen = True
        else:
            status = "pending"
            first_missing_seen = True
        stages.append({"id": stage_id, "status": status, "artifact": output_name if output_path.is_file() else None})
    return stages


def _public_task(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    stages = _stage_payload(root, record)
    completed = sum(1 for item in stages if item["status"] == "complete")
    current = next((item["id"] for item in stages if item["status"] == "running"), None)
    payload = dict(record)
    payload["stages"] = stages
    payload["current_stage"] = current
    payload["progress"] = round(completed / len(stages) * 100)
    payload["result_ready"] = stages[-1]["status"] == "complete"
    payload["pdf_url"] = f"/api/tasks/{record['task_id']}/pdf"
    payload["result_url"] = f"/api/tasks/{record['task_id']}/result" if payload["result_ready"] else None
    payload["source_kind"] = "web"
    if payload["result_ready"]:
        candidate_path = _result_dir(root, record["ref_no"]) / "candidate.json"
        try:
            payload.update(_candidate_overview(_read_json(candidate_path, "Extraction result is invalid")))
        except HTTPException:
            payload["result_ready"] = False
            payload["result_url"] = None
    return payload


def _load_candidate(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    result_path = _result_dir(root, record["ref_no"]) / "candidate.json"
    if not result_path.is_file():
        raise HTTPException(status_code=409, detail="Extraction result is not ready")
    return _read_json(result_path, "Extraction result is invalid")


def _batch_result_dir(ref_no: str) -> Path:
    if not REF_NO_RE.fullmatch(ref_no):
        raise HTTPException(status_code=404, detail="Batch result not found")
    result_dir = BATCH_ROOT / ref_no
    if not result_dir.is_dir():
        raise HTTPException(status_code=404, detail="Batch result not found")
    return result_dir


def _load_batch_candidate(ref_no: str) -> dict[str, Any]:
    candidate_path = _batch_result_dir(ref_no) / "candidate.json"
    if not candidate_path.is_file():
        raise HTTPException(status_code=404, detail="Batch candidate not found")
    return _read_json(candidate_path, "Batch candidate is invalid")


def _batch_source_map() -> dict[str, str]:
    index = BATCH_INDEX or _read_batch_index_file(BATCH_ROOT)
    if not index:
        return {}
    mapping: dict[str, str] = {}
    for source_batch, refs in (index.get("batch_membership") or {}).items():
        for ref_no in refs or []:
            mapping[str(ref_no)] = str(source_batch)
    if not mapping:
        source_label = str(index.get("result_mode") or BATCH_ROOT.name)
        for document in index.get("documents") or []:
            if isinstance(document, dict) and document.get("reference_no"):
                mapping[str(document["reference_no"])] = source_label
    return mapping


def _polyinfo_result_dir(ref_no: str) -> tuple[Path, str]:
    if not REF_NO_RE.fullmatch(ref_no):
        raise HTTPException(status_code=404, detail="PoLyInfo result not found")
    for group in POLYINFO_GROUPS:
        result_dir = POLYINFO_DATA_ROOT / group / ref_no
        if result_dir.is_dir():
            return result_dir, group
    raise HTTPException(status_code=404, detail="PoLyInfo result not found")


def _read_polyinfo_samples(result_dir: Path, include_structures: bool) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for path in sorted(result_dir.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(record, dict) or not record.get("sample_id") or not record.get("polymer_id"):
            continue
        record["source_file"] = path.name
        record["_has_structure"] = bool(record.get("cu_chemical_structure"))
        if not include_structures:
            record.pop("cu_chemical_structure", None)
        samples.append(record)
    return samples


def _value_display(value: dict[str, Any]) -> str:
    minimum = value.get("property_value_min")
    maximum = value.get("property_value_max")
    if minimum is None and maximum is None:
        return "-"
    raw_prefix = str(value.get("property_value_inequality") or "")
    prefix = {"ca": "ca. ", "lt": "<", "gt": ">", "le": "≤", "ge": "≥"}.get(raw_prefix.lower(), raw_prefix)
    if minimum is not None and maximum is not None and minimum != maximum:
        return f"{prefix}{minimum}–{maximum}"
    return f"{prefix}{minimum if minimum is not None else maximum}"


def _display_text(value: Any) -> str | None:
    """Convert heterogeneous PoLyInfo fields into stable, readable API text."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        text = str(value).strip()
        return text or None
    if isinstance(value, list):
        parts = [_display_text(item) for item in value]
        return "; ".join(part for part in parts if part) or None
    if isinstance(value, dict):
        condition_name = value.get("solution_viscosity_measurement_condition")
        condition_value = value.get("solution_viscosity_measurement_condition_information")
        if condition_name is not None or condition_value is not None:
            name_text = _display_text(condition_name)
            value_text = _display_text(condition_value)
            if name_text and value_text:
                return f"{name_text}: {value_text}"
            return name_text or value_text
        parts: list[str] = []
        for key, child in value.items():
            child_text = _display_text(child)
            if child_text:
                parts.append(f"{str(key).replace('_', ' ')}: {child_text}")
        return "; ".join(parts) or None
    return str(value)


def _polyinfo_properties(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    properties: list[dict[str, Any]] = []
    for sample in samples:
        sample_id = str(sample.get("sample_id") or "")
        polymer_id = str(sample.get("polymer_id") or "")
        for group_index, group in enumerate(sample.get("property") or []):
            title = str(group.get("property_title") or "Property")
            for item_index, item in enumerate(group.get("property_item") or []):
                method = _display_text(item.get("measurement_method"))
                condition = _display_text(item.get("measurement_condition"))
                for value_index, value in enumerate(item.get("property_values") or []):
                    properties.append({
                        "id": f"{sample_id}:p:{group_index}:{item_index}:{value_index}",
                        "sample_id": sample_id,
                        "polymer_id": polymer_id,
                        "category": title,
                        "name": value.get("property_name") or title,
                        "value": _value_display(value),
                        "value_min": value.get("property_value_min"),
                        "value_max": value.get("property_value_max"),
                        "unit": value.get("property_unit"),
                        "method": method,
                        "condition": condition,
                        "remark": item.get("remark"),
                        "source": "PoLyInfo property",
                    })

        for index, item in enumerate(sample.get("average_molecular_weight") or []):
            kind = str(item.get("average_molecular_weight_kind") or "Molecular weight")
            minimum = item.get("average_molecular_weight_min")
            maximum = item.get("average_molecular_weight_max")
            properties.append({
                "id": f"{sample_id}:mw:{index}",
                "sample_id": sample_id,
                "polymer_id": polymer_id,
                "category": "Average molecular weight",
                "name": kind,
                "value": str(minimum if minimum is not None else maximum if maximum is not None else "-"),
                "value_min": minimum,
                "value_max": maximum,
                "unit": item.get("average_molecular_weight_unit"),
                "method": _display_text(item.get("average_molecular_weight_measurement_method")),
                "condition": _display_text(item.get("average_molecular_weight_measurement_condition")),
                "source": "PoLyInfo molecular weight",
            })

        viscosity = sample.get("solution_viscosity")
        if isinstance(viscosity, dict) and viscosity.get("solution_viscosity_min") is not None:
            kind = str(viscosity.get("solution_viscosity_kind") or "Solution viscosity")
            properties.append({
                "id": f"{sample_id}:solution-viscosity",
                "sample_id": sample_id,
                "polymer_id": polymer_id,
                "category": "Solution viscosity",
                "name": kind,
                "value": str(viscosity.get("solution_viscosity_min")),
                "value_min": viscosity.get("solution_viscosity_min"),
                "value_max": viscosity.get("solution_viscosity_max") or viscosity.get("solution_viscosity_min"),
                "unit": viscosity.get("solution_viscosity_unit"),
                "method": _display_text(viscosity.get("solution_viscosity_measurement_method")),
                "condition": _display_text(viscosity.get("solution_viscosity_measurement_conditions")),
                "source": "PoLyInfo solution viscosity",
            })
    return properties


def _polyinfo_processes(samples: list[dict[str, Any]]) -> list[dict[str, str]]:
    processes: list[dict[str, str]] = []
    for sample in samples:
        sample_id = str(sample.get("sample_id") or "")
        polymerization = sample.get("polymerization_information")
        if isinstance(polymerization, dict):
            for kind, values in (("Polymerization type", polymerization.get("type")), ("Polymerization style", polymerization.get("style"))):
                for value in values or []:
                    processes.append({"sample_id": sample_id, "kind": kind, "value": _display_text(value) or "-"})
            condition = polymerization.get("polymer_reaction_condition")
            if condition:
                processes.append({"sample_id": sample_id, "kind": "Reaction condition", "value": _display_text(condition) or "-"})
        processing = sample.get("processing_information")
        if isinstance(processing, dict):
            for value in processing.get("molding_method") or []:
                processes.append({"sample_id": sample_id, "kind": "Molding method", "value": _display_text(value) or "-"})
            for value in processing.get("molding_sample_shape") or []:
                processes.append({"sample_id": sample_id, "kind": "Sample shape", "value": _display_text(value) or "-"})
        blending = sample.get("mixing_blending_method")
        if isinstance(blending, list):
            for value in blending:
                processes.append({"sample_id": sample_id, "kind": "Mixing/blending", "value": _display_text(value) or "-"})
        elif blending:
            processes.append({"sample_id": sample_id, "kind": "Mixing/blending", "value": _display_text(blending) or "-"})
    return processes


def _polyinfo_stats(samples: list[dict[str, Any]], properties: list[dict[str, Any]], processes: list[dict[str, str]]) -> dict[str, int]:
    methods = {str(item.get("method")) for item in properties if item.get("method")}
    conditions = sum(1 for item in properties if item.get("condition"))
    structures = sum(1 for item in samples if item.get("cu_chemical_structure") or item.get("_has_structure"))
    return {
        "polymer_count": len({str(item.get("polymer_id")) for item in samples if item.get("polymer_id")}),
        "sample_count": len(samples),
        "property_count": len(properties),
        "property_type_count": len({str(item.get("name")) for item in properties if item.get("name")}),
        "process_count": len(processes),
        "characterization_count": len(methods),
        "measurement_condition_count": conditions,
        "structure_count": structures,
        "evidence_count": 0,
    }


def _polyinfo_summary(result_dir: Path, group: str) -> dict[str, Any] | None:
    samples = _read_polyinfo_samples(result_dir, include_structures=False)
    if not samples:
        return None
    properties = _polyinfo_properties(samples)
    processes = _polyinfo_processes(samples)
    reference = samples[0].get("reference") or {}
    polymer_names = sorted({str(name) for item in samples for name in (item.get("polymer_name") or []) if name})
    return {
        "source_kind": "polyinfo",
        "collection_id": "local_polyinfo_export",
        "group": group,
        "ref_no": result_dir.name,
        "reference": reference,
        "polymer_names": polymer_names[:6],
        "polymer_name_count": len(polymer_names),
        "stats": _polyinfo_stats(samples, properties, processes),
        "has_pdf": any(result_dir.glob("*.pdf")),
        "has_batch_result": (BATCH_ROOT / result_dir.name / "candidate.json").is_file(),
        "detail_url": f"/api/polyinfo-results/{result_dir.name}",
        "comparison_url": f"/api/polyinfo-results/{result_dir.name}/comparison",
    }


@lru_cache(maxsize=1)
def _polyinfo_summaries() -> tuple[dict[str, Any], ...]:
    results: list[dict[str, Any]] = []
    for group in POLYINFO_GROUPS:
        group_root = POLYINFO_DATA_ROOT / group
        if not group_root.is_dir():
            continue
        for result_dir in sorted(group_root.iterdir()):
            if not result_dir.is_dir() or not REF_NO_RE.fullmatch(result_dir.name):
                continue
            summary = _polyinfo_summary(result_dir, group)
            if summary:
                results.append(summary)
    return tuple(results)


@lru_cache(maxsize=24)
def _polyinfo_detail(ref_no: str) -> dict[str, Any]:
    result_dir, group = _polyinfo_result_dir(ref_no)
    samples = _read_polyinfo_samples(result_dir, include_structures=True)
    if not samples:
        raise HTTPException(status_code=404, detail="PoLyInfo sample records not found")
    properties = _polyinfo_properties(samples)
    processes = _polyinfo_processes(samples)
    polymer_map: dict[str, dict[str, Any]] = {}
    for sample in samples:
        polymer_id = str(sample.get("polymer_id") or "unresolved")
        polymer = polymer_map.setdefault(polymer_id, {
            "polymer_id": polymer_id,
            "polymer_names": sample.get("polymer_name") or [],
            "polymer_type": sample.get("polymer_type"),
            "cu_formula": sample.get("cu_formula"),
            "structure_image": (sample.get("cu_chemical_structure") or [None])[0],
            "sample_ids": [],
        })
        polymer["sample_ids"].append(sample.get("sample_id"))
    compact_samples = []
    for sample in samples:
        compact_samples.append({
            "sample_id": sample.get("sample_id"),
            "polymer_id": sample.get("polymer_id"),
            "polymer_name": sample.get("polymer_name") or [],
            "polymer_type": sample.get("polymer_type"),
            "polymer_class": sample.get("polymer_class") or [],
            "material_type": sample.get("material_type") or [],
            "cu_formula": sample.get("cu_formula"),
            "characteristics_of_material": sample.get("characteristics_of_material") or {},
            "property_count": sum(1 for item in properties if item.get("sample_id") == sample.get("sample_id")),
            "process_count": sum(1 for item in processes if item.get("sample_id") == sample.get("sample_id")),
            "source_file": sample.get("source_file"),
        })
    return {
        "source_kind": "polyinfo",
        "group": group,
        "ref_no": ref_no,
        "reference": samples[0].get("reference") or {},
        "polymers": list(polymer_map.values()),
        "samples": compact_samples,
        "properties": properties,
        "processes": processes,
        "stats": _polyinfo_stats(samples, properties, processes),
        "pdf_url": f"/api/polyinfo-results/{ref_no}/pdf" if any(result_dir.glob("*.pdf")) else None,
    }


def _canonical_property_name(item: dict[str, Any], source: str) -> str:
    if source == "extraction":
        raw = str(item.get("property_name_normalized") or item.get("property_name_raw") or "")
    else:
        raw = str(item.get("name") or "")
    normalized = re.sub(r"[^a-z0-9]+", " ", raw.lower()).strip()
    aliases = {
        "intrinsic viscosity": "intrinsic viscosity",
        "intrinsic viscosity eta": "intrinsic viscosity",
        "eta mathrm inh": "intrinsic viscosity",
        "eta inh": "intrinsic viscosity",
        "intrinsic viscosity eta inh": "intrinsic viscosity",
        "intrinsic viscosity": "intrinsic viscosity",
        "tensile strength": "tensile stress strength at break",
        "tensile stress at break": "tensile stress strength at break",
        "tensile stress strength at break": "tensile stress strength at break",
        "glass transition temperature": "glass transition temperature",
        "elongation at break": "elongation at break",
    }
    underscore_name = raw.lower().strip()
    if underscore_name == "intrinsic_viscosity":
        return "intrinsic viscosity"
    if underscore_name == "tensile_stress_at_break":
        return "tensile stress strength at break"
    return aliases.get(normalized, normalized)


def _normalized_value(item: dict[str, Any], source: str) -> tuple[float | None, float | None, str]:
    if source == "extraction":
        minimum = item.get("value_min")
        maximum = item.get("value_max")
        unit = item.get("unit_normalized") or item.get("unit_raw") or ""
        if minimum is None:
            match = re.search(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", str(item.get("value_raw") or ""))
            minimum = float(match.group()) if match else None
        if maximum is None:
            maximum = minimum
    else:
        minimum = item.get("value_min")
        maximum = item.get("value_max")
        unit = item.get("unit") or ""
    try:
        min_value = float(minimum) if minimum is not None else None
        max_value = float(maximum) if maximum is not None else min_value
    except (TypeError, ValueError):
        min_value, max_value = None, None
    normalized_unit = str(unit).strip().lower().replace("°", "").replace("deg", "")
    if normalized_unit == "gpa" and min_value is not None:
        min_value *= 1000
        max_value = max_value * 1000 if max_value is not None else min_value
        normalized_unit = "mpa"
    if normalized_unit in {"c", "celsius"}:
        normalized_unit = "c"
    return min_value, max_value, normalized_unit


def _values_match(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_min, left_max, left_unit = _normalized_value(left, "polyinfo")
    right_min, right_max, right_unit = _normalized_value(right, "extraction")
    if left_min is None or right_min is None or (left_unit and right_unit and left_unit != right_unit):
        return False
    left_max = left_max if left_max is not None else left_min
    right_max = right_max if right_max is not None else right_min
    tolerance = max(1e-6, abs(left_min) * 0.01, abs(right_min) * 0.01)
    return not (left_max + tolerance < right_min or right_max + tolerance < left_min)


def _matching_batch_candidate(ref_no: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    candidate_path = BATCH_ROOT / ref_no / "candidate.json"
    if not candidate_path.is_file():
        return None
    try:
        candidate = _read_json(candidate_path, "Batch candidate is invalid")
    except HTTPException:
        return None
    record = {
        "source_kind": "batch",
        "collection_id": BATCH_ROOT.name,
        "created_at": "2026-08-09",
        "file_name": f"{ref_no}.pdf",
    }
    return record, candidate


def _comparison_payload(ref_no: str) -> dict[str, Any]:
    polyinfo = _polyinfo_detail(ref_no)
    match = _matching_batch_candidate(ref_no)
    if not match:
        return {"ref_no": ref_no, "polyinfo": polyinfo, "extraction": None, "metrics": [], "property_alignment": [], "message": "最新批处理没有该 reference_no 的抽取结果"}
    record, candidate = match
    extraction_stats = _candidate_overview(candidate)["stats"]
    extraction_stats["property_type_count"] = len({_canonical_property_name(item, "extraction") for item in candidate.get("property_observations") or []})
    extraction_stats["measurement_condition_count"] = sum(1 for item in candidate.get("measurement_conditions") or [] if item.get("condition_status") == "reported" or item.get("other_conditions"))
    extraction_stats["structure_count"] = sum(1 for item in candidate.get("polymer_entities") or [] if item.get("structure") or item.get("psmiles"))

    pi_props = polyinfo["properties"]
    web_props = list(candidate.get("property_observations") or [])
    remaining = set(range(len(web_props)))
    alignment: list[dict[str, Any]] = []
    for prop in pi_props:
        canonical = _canonical_property_name(prop, "polyinfo")
        candidates = [index for index in remaining if _canonical_property_name(web_props[index], "extraction") == canonical]
        exact = next((index for index in candidates if _values_match(prop, web_props[index])), None)
        selected = exact if exact is not None else (candidates[0] if candidates else None)
        if selected is None:
            alignment.append({"status": "polyinfo_only", "canonical_name": canonical, "polyinfo": prop, "extraction": None})
            continue
        remaining.discard(selected)
        alignment.append({"status": "matched" if exact is not None else "value_diff", "canonical_name": canonical, "polyinfo": prop, "extraction": web_props[selected]})
    for index in sorted(remaining):
        item = web_props[index]
        alignment.append({"status": "extraction_only", "canonical_name": _canonical_property_name(item, "extraction"), "polyinfo": None, "extraction": item})

    metrics = [
        {"key": "polymer_count", "label": "聚合物实体", "polyinfo": polyinfo["stats"]["polymer_count"], "extraction": extraction_stats["polymer_count"], "interpretation": "身份层级定义可能不同"},
        {"key": "sample_count", "label": "样品/状态", "polyinfo": polyinfo["stats"]["sample_count"], "extraction": extraction_stats["sample_count"], "interpretation": "检查样品切分与状态链"},
        {"key": "property_count", "label": "性质观测", "polyinfo": polyinfo["stats"]["property_count"], "extraction": extraction_stats["property_count"], "interpretation": "逐值比较见下表"},
        {"key": "process_count", "label": "工艺描述", "polyinfo": polyinfo["stats"]["process_count"], "extraction": extraction_stats["process_count"], "interpretation": "PoLyInfo 为字段，批处理结果为过程事件"},
        {"key": "measurement_condition_count", "label": "测量条件", "polyinfo": polyinfo["stats"]["measurement_condition_count"], "extraction": extraction_stats["measurement_condition_count"], "interpretation": "统计有明确条件的记录"},
        {"key": "evidence_count", "label": "可定位原文证据", "polyinfo": 0, "extraction": extraction_stats["evidence_count"], "interpretation": "本地 PoLyInfo JSON 未提供页码、BBox 或原文片段"},
    ]
    status_counts = {status: sum(1 for item in alignment if item["status"] == status) for status in ("matched", "value_diff", "polyinfo_only", "extraction_only")}
    return {
        "ref_no": ref_no,
        "polyinfo": polyinfo,
        "extraction": {
            "source_kind": record.get("source_kind"),
            "collection_id": record.get("collection_id"),
            "created_at": record.get("created_at"),
            "file_name": record.get("file_name"),
            "paper": candidate.get("paper") or {},
            "stats": extraction_stats,
            "polymer_entities": candidate.get("polymer_entities") or [],
            "samples": candidate.get("samples") or [],
        },
        "metrics": metrics,
        "property_alignment": alignment,
        "alignment_stats": status_counts,
        "message": "数量差异只用于定位问题，性质一致性按名称、单位换算和数值逐条判定",
    }


def _candidate_hierarchy(candidate: dict[str, Any]) -> dict[str, Any]:
    samples = candidate.get("samples", [])
    properties = candidate.get("property_observations", [])
    characterizations = candidate.get("characterizations", [])
    processes = candidate.get("process_steps", [])

    sample_children: dict[str, dict[str, Any]] = {}
    for sample in samples:
        sample_id = sample.get("sample_id")
        sample_children[sample_id] = {
            **sample,
            "properties": [item for item in properties if item.get("sample_id") == sample_id],
            "characterizations": [item for item in characterizations if sample_id in item.get("sample_ids", [])],
            "incoming_processes": [item for item in processes if sample_id in item.get("output_sample_ids", [])],
            "outgoing_processes": [item for item in processes if sample_id in item.get("input_sample_ids", [])],
        }

    polymers = []
    linked_sample_ids: set[str] = set()
    for entity in candidate.get("polymer_entities", []):
        entity_samples = [
            sample_children[item.get("sample_id")]
            for item in samples
            if item.get("refers_to_entity") == entity.get("entity_id")
        ]
        linked_sample_ids.update(item.get("sample_id") for item in entity_samples)
        polymers.append({**entity, "samples": entity_samples})

    return {
        "paper": candidate.get("paper", {}),
        "polymers": polymers,
        "unlinked_samples": [item for key, item in sample_children.items() if key not in linked_sample_ids],
        "process_steps": processes,
        "stats": {
            "polymer_count": len(polymers),
            "linked_polymer_count": sum(1 for item in polymers if item["samples"]),
            "sample_count": len(samples),
            "property_count": len(properties),
            "process_count": len(processes),
            "characterization_count": len(characterizations),
        },
    }


def _candidate_graph(candidate: dict[str, Any]) -> dict[str, Any]:
    paper = candidate.get("paper", {})
    paper_id = f"paper:{paper.get('ref_no', 'current')}"
    nodes: list[dict[str, Any]] = [{
        "id": paper_id,
        "type": "paper",
        "label": paper.get("title") or paper.get("ref_no") or "Paper",
        "data": paper,
    }]
    edges: list[dict[str, Any]] = []

    for entity in candidate.get("polymer_entities", []):
        entity_id = entity.get("entity_id")
        nodes.append({"id": entity_id, "type": "polymer", "label": entity.get("polymer_name") or entity_id, "data": entity})
        edges.append({"id": f"{paper_id}:contains:{entity_id}", "source": paper_id, "target": entity_id, "type": "contains_polymer", "label": "识别"})

    for sample in candidate.get("samples", []):
        sample_id = sample.get("sample_id")
        sample_label = sample.get("sample_label_raw") or sample.get("polymer_name") or sample_id
        nodes.append({"id": sample_id, "type": "sample", "label": sample_label, "data": sample})
        entity_id = sample.get("refers_to_entity")
        if entity_id:
            edges.append({"id": f"{entity_id}:sample:{sample_id}", "source": entity_id, "target": sample_id, "type": "has_sample", "label": "对应样品"})

    for step in candidate.get("process_steps", []):
        step_id = step.get("step_id")
        nodes.append({"id": step_id, "type": "process", "label": step.get("process_type") or step_id, "data": step})
        for sample_id in step.get("input_sample_ids", []):
            edges.append({"id": f"{sample_id}:input:{step_id}", "source": sample_id, "target": step_id, "type": "process_input", "label": "输入"})
        for sample_id in step.get("output_sample_ids", []):
            edges.append({"id": f"{step_id}:output:{sample_id}", "source": step_id, "target": sample_id, "type": "process_output", "label": "生成"})

    for prop in candidate.get("property_observations", []):
        prop_id = prop.get("property_id")
        label = f"{prop.get('property_name_raw', prop_id)}: {prop.get('value_raw', '')} {prop.get('unit_normalized') or prop.get('unit_raw') or ''}".strip()
        nodes.append({"id": prop_id, "type": "property", "label": label, "data": prop})
        sample_id = prop.get("sample_id")
        if sample_id:
            edges.append({"id": f"{sample_id}:property:{prop_id}", "source": sample_id, "target": prop_id, "type": "has_property", "label": "测得"})

    for characterization in candidate.get("characterizations", []):
        char_id = characterization.get("characterization_id")
        nodes.append({
            "id": char_id,
            "type": "characterization",
            "label": characterization.get("method_normalized") or characterization.get("method_raw") or char_id,
            "data": characterization,
        })
        for sample_id in characterization.get("sample_ids", []):
            edges.append({"id": f"{sample_id}:characterization:{char_id}", "source": sample_id, "target": char_id, "type": "characterized_by", "label": "表征"})

    node_counts: dict[str, int] = {}
    for node in nodes:
        node_counts[node["type"]] = node_counts.get(node["type"], 0) + 1
    return {"nodes": nodes, "edges": edges, "stats": {"node_counts": node_counts, "edge_count": len(edges)}}


def _run_pipeline(task_id: str, task_secrets: dict[str, str]) -> None:
    root = RUNTIME_ROOT / task_id
    record = _read_record(root)
    record["status"] = "running"
    record["started_at"] = _utc_now()
    _write_record(root, record)

    command = [
        str(PYTHON if PYTHON.is_file() else "python"),
        str(ROOT / "pipeline_runner.py"),
        "--input-dir", str(root / "source_pdfs"),
        "--mineru-output", str(root / "work" / "mineru"),
        "--organized-root", str(root / "work" / "organized"),
        "--processed-output", str(root / "work" / "processed"),
        "--output-dir", str(root / "output"),
        "--config", str(ROOT / "extraction" / "config" / "pipeline.yaml"),
        "--env-file", str(ROOT / ".env"),
        "--ref-no", record["ref_no"],
        "--workers", "1",
        "--llm-workers", "1",
        "--preview",
    ]

    log_path = root / "pipeline.log"
    try:
        with log_path.open("w", encoding="utf-8", errors="replace") as log_file:
            pipeline_env = _load_pipeline_environment()
            pipeline_env.update(task_secrets)
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                env=pipeline_env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
            )
            with _process_lock:
                _processes[task_id] = process
            return_code = process.wait()

        record = _read_record(root)
        candidate_path = _result_dir(root, record["ref_no"]) / "candidate.json"
        if return_code == 0 and candidate_path.is_file():
            record["status"] = "complete"
        elif record.get("status") != "cancelled":
            record["status"] = "failed"
            record["error"] = f"Pipeline exited with code {return_code}. See pipeline.log."
        record["finished_at"] = _utc_now()
        _write_record(root, record)
    except Exception as exc:  # noqa: BLE001 - retain the task error for the UI
        record = _read_record(root)
        record["status"] = "failed"
        record["error"] = str(exc)
        record["finished_at"] = _utc_now()
        _write_record(root, record)
    finally:
        task_secrets.clear()
        with _process_lock:
            _processes.pop(task_id, None)


def _is_secure_request(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
    return (
        request.url.scheme == "https"
        or forwarded_proto == "https"
        or request.url.hostname in {"localhost", "127.0.0.1", "::1"}
    )


@app.get("/api/health")
def health(request: Request) -> dict[str, Any]:
    env = _load_pipeline_environment()
    return {
        "status": "ok",
        "pipeline_root": str(ROOT),
        "python_ready": PYTHON.is_file() or shutil.which("python") is not None,
        "accepts_user_keys": True,
        "requires_https_for_keys": REQUIRE_HTTPS_FOR_KEYS,
        "key_submission_allowed": not REQUIRE_HTTPS_FOR_KEYS or _is_secure_request(request),
        "max_upload_bytes": MAX_UPLOAD_BYTES,
        "mineru_key_ready": bool(env.get("MINERU_API_KEY")),
        "llm_key_ready": bool(env.get("DMX_API_KEY") or env.get("LLM_API_KEY")),
        "batch_collection": BATCH_ROOT.name,
        "batch_result_date": BATCH_INDEX.get("result_date"),
    }


@app.post("/api/tasks", status_code=202)
async def create_task(
    request: Request,
    file: UploadFile = File(...),
    dmx_api_key: str = Form(...),
    mineru_api_key: str = Form(...),
) -> dict[str, Any]:
    if REQUIRE_HTTPS_FOR_KEYS and not _is_secure_request(request):
        raise HTTPException(status_code=426, detail="HTTPS is required before API credentials can be submitted")
    dmx_api_key = dmx_api_key.strip()
    mineru_api_key = mineru_api_key.strip()
    for label, value in (("DMX API key", dmx_api_key), ("MinerU API key", mineru_api_key)):
        if not 8 <= len(value) <= 512 or "\n" in value or "\r" in value:
            raise HTTPException(status_code=422, detail=f"{label} is invalid")
    if file.content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Only PDF files are supported")

    original_name = Path(file.filename or "paper.pdf").name
    source_ref_match = re.fullmatch(r"(reference_no_\d+)\.pdf", original_name, flags=re.IGNORECASE)
    task_id = uuid.uuid4().hex[:12]
    ref_no = f"reference_no_{int(time.time() * 1000)}"
    root = RUNTIME_ROOT / task_id
    source_dir = root / "source_pdfs"
    source_dir.mkdir(parents=True)
    pdf_path = source_dir / f"{ref_no}.pdf"

    size = 0
    first_chunk = True
    with pdf_path.open("wb") as target:
        while chunk := await file.read(1024 * 1024):
            if first_chunk and not chunk.startswith(b"%PDF"):
                target.close()
                pdf_path.unlink(missing_ok=True)
                raise HTTPException(status_code=400, detail="The uploaded file is not a valid PDF")
            first_chunk = False
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                target.close()
                pdf_path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail=f"PDF exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit")
            target.write(chunk)
    await file.close()

    record = {
        "task_id": task_id,
        "ref_no": ref_no,
        "source_reference_no": source_ref_match.group(1).lower() if source_ref_match else None,
        "file_name": original_name,
        "file_size": size,
        "status": "queued",
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "error": None,
    }
    _write_record(root, record)
    task_secrets = {"DMX_API_KEY": dmx_api_key, "MINERU_API_KEY": mineru_api_key}
    threading.Thread(target=_run_pipeline, args=(task_id, task_secrets), daemon=True).start()
    return _public_task(root, record)


@app.get("/api/tasks")
def list_tasks(limit: int = 20) -> list[dict[str, Any]]:
    safe_limit = min(max(limit, 1), 100)
    tasks: list[dict[str, Any]] = []
    for root in RUNTIME_ROOT.iterdir():
        if not root.is_dir() or not TASK_ID_RE.fullmatch(root.name):
            continue
        try:
            tasks.append(_public_task(root, _read_record(root)))
        except HTTPException:
            continue
    tasks.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return tasks[:safe_limit]


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str) -> dict[str, Any]:
    root = _task_root(task_id)
    return _public_task(root, _read_record(root))


@app.get("/api/tasks/{task_id}/result")
def get_result(task_id: str) -> JSONResponse:
    root = _task_root(task_id)
    record = _read_record(root)
    return JSONResponse(_load_candidate(root, record))


@app.get("/api/tasks/{task_id}/hierarchy")
def get_hierarchy(task_id: str) -> JSONResponse:
    root = _task_root(task_id)
    record = _read_record(root)
    return JSONResponse(_candidate_hierarchy(_load_candidate(root, record)))


@app.get("/api/tasks/{task_id}/graph")
def get_graph(task_id: str) -> JSONResponse:
    root = _task_root(task_id)
    record = _read_record(root)
    return JSONResponse(_candidate_graph(_load_candidate(root, record)))


@app.get("/api/tasks/{task_id}/pdf")
def get_pdf(task_id: str) -> FileResponse:
    root = _task_root(task_id)
    record = _read_record(root)
    pdf_path = root / "source_pdfs" / f"{record['ref_no']}.pdf"
    return FileResponse(pdf_path, media_type="application/pdf", filename=record["file_name"])


@app.get("/api/tasks/{task_id}/pdf/pages/{page}")
def get_pdf_page(task_id: str, page: int) -> FileResponse:
    root = _task_root(task_id)
    record = _read_record(root)
    pdf_path = root / "source_pdfs" / f"{record['ref_no']}.pdf"
    return _page_response(_render_pdf_page(pdf_path, root / "page_previews", page))


@app.get("/api/batch-results")
def list_batch_results() -> list[dict[str, Any]]:
    if not BATCH_ROOT.is_dir():
        return []
    source_map = _batch_source_map()
    result_date = str(BATCH_INDEX.get("result_date") or BATCH_INDEX.get("generated_at") or "")
    result_mode = str(BATCH_INDEX.get("result_mode") or BATCH_ROOT.name)
    results: list[dict[str, Any]] = []
    for result_dir in sorted(BATCH_ROOT.iterdir()):
        if not result_dir.is_dir() or not REF_NO_RE.fullmatch(result_dir.name):
            continue
        candidate_path = result_dir / "candidate.json"
        if not candidate_path.is_file():
            continue
        try:
            candidate = _read_json(candidate_path, "Batch candidate is invalid")
        except HTTPException:
            continue
        ref_no = result_dir.name
        results.append({
            "source_kind": "batch",
            "collection_id": BATCH_ROOT.name,
            "result_date": result_date,
            "result_mode": result_mode,
            "ref_no": ref_no,
            "source_batch": source_map.get(ref_no),
            "result_url": f"/api/batch-results/{ref_no}/result",
            "graph_url": f"/api/batch-results/{ref_no}/graph",
            "pdf_url": f"/api/batch-results/{ref_no}/pdf" if (SOURCE_PDF_ROOT / f"{ref_no}.pdf").is_file() else None,
            **_candidate_overview(candidate),
        })
    return results


@app.get("/api/batch-results/{ref_no}/result")
def get_batch_result(ref_no: str) -> JSONResponse:
    return JSONResponse(_load_batch_candidate(ref_no))


@app.get("/api/batch-results/{ref_no}/hierarchy")
def get_batch_hierarchy(ref_no: str) -> JSONResponse:
    return JSONResponse(_candidate_hierarchy(_load_batch_candidate(ref_no)))


@app.get("/api/batch-results/{ref_no}/graph")
def get_batch_graph(ref_no: str) -> JSONResponse:
    return JSONResponse(_candidate_graph(_load_batch_candidate(ref_no)))


@app.get("/api/batch-results/{ref_no}/pdf")
def get_batch_pdf(ref_no: str) -> FileResponse:
    _batch_result_dir(ref_no)
    pdf_path = SOURCE_PDF_ROOT / f"{ref_no}.pdf"
    if not pdf_path.is_file():
        raise HTTPException(status_code=404, detail="Source PDF not found")
    return FileResponse(pdf_path, media_type="application/pdf", filename=pdf_path.name)


@app.get("/api/batch-results/{ref_no}/pdf/pages/{page}")
def get_batch_pdf_page(ref_no: str, page: int) -> FileResponse:
    _batch_result_dir(ref_no)
    pdf_path = SOURCE_PDF_ROOT / f"{ref_no}.pdf"
    return _page_response(_render_pdf_page(pdf_path, EVIDENCE_PREVIEW_ROOT / "batch" / ref_no, page))


@app.get("/api/polyinfo-results")
def list_polyinfo_results() -> list[dict[str, Any]]:
    batch_refs = {
        root.name.lower()
        for root in BATCH_ROOT.iterdir()
        if root.is_dir() and REF_NO_RE.fullmatch(root.name) and (root / "candidate.json").is_file()
    } if BATCH_ROOT.is_dir() else set()
    return [{**item, "has_batch_result": item["ref_no"].lower() in batch_refs} for item in _polyinfo_summaries()]


@app.get("/api/polyinfo-results/{ref_no}")
def get_polyinfo_result(ref_no: str) -> JSONResponse:
    return JSONResponse(_polyinfo_detail(ref_no))


@app.get("/api/polyinfo-results/{ref_no}/comparison")
def get_polyinfo_comparison(ref_no: str) -> JSONResponse:
    return JSONResponse(_comparison_payload(ref_no))


@app.get("/api/polyinfo-results/{ref_no}/pdf")
def get_polyinfo_pdf(ref_no: str) -> FileResponse:
    result_dir, _ = _polyinfo_result_dir(ref_no)
    pdf_path = next(result_dir.glob("*.pdf"), None)
    if not pdf_path or not pdf_path.is_file():
        raise HTTPException(status_code=404, detail="PoLyInfo source PDF not found")
    return FileResponse(pdf_path, media_type="application/pdf", filename=pdf_path.name)


@app.get("/api/polyinfo-results/{ref_no}/pdf/pages/{page}")
def get_polyinfo_pdf_page(ref_no: str, page: int) -> FileResponse:
    result_dir, _ = _polyinfo_result_dir(ref_no)
    pdf_path = next(result_dir.glob("*.pdf"), None)
    if not pdf_path:
        raise HTTPException(status_code=404, detail="PoLyInfo source PDF not found")
    return _page_response(_render_pdf_page(pdf_path, EVIDENCE_PREVIEW_ROOT / "polyinfo" / ref_no, page))


@app.get("/api/source-pdfs/{ref_no}/pdf")
def get_source_pdf(ref_no: str) -> FileResponse:
    if not REF_NO_RE.fullmatch(ref_no):
        raise HTTPException(status_code=404, detail="Source PDF not found")
    pdf_path = SOURCE_PDF_ROOT / f"{ref_no}.pdf"
    if not pdf_path.is_file():
        raise HTTPException(status_code=404, detail="Source PDF not found")
    return FileResponse(pdf_path, media_type="application/pdf", filename=pdf_path.name)


@app.get("/api/source-pdfs/{ref_no}/pdf/pages/{page}")
def get_source_pdf_page(ref_no: str, page: int) -> FileResponse:
    if not REF_NO_RE.fullmatch(ref_no):
        raise HTTPException(status_code=404, detail="Source PDF not found")
    pdf_path = SOURCE_PDF_ROOT / f"{ref_no}.pdf"
    return _page_response(_render_pdf_page(pdf_path, EVIDENCE_PREVIEW_ROOT / "source" / ref_no, page))


@app.post("/api/tasks/{task_id}/cancel")
def cancel_task(task_id: str) -> dict[str, Any]:
    root = _task_root(task_id)
    record = _read_record(root)
    with _process_lock:
        process = _processes.get(task_id)
        if process and process.poll() is None:
            process.terminate()
    record["status"] = "cancelled"
    record["finished_at"] = _utc_now()
    _write_record(root, record)
    return _public_task(root, record)
