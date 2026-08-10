"""Validate batch result collections before they can be published."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Sequence


COLLECTION_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*_(\d{8})$")
REF_RE = re.compile(r"^reference_no_\d+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
PROHIBITED_NAMES = {".env", ".env.local"}
PROHIBITED_SUFFIXES = {".db", ".key", ".log", ".pem", ".sqlite", ".sqlite3"}
REQUIRED_CANDIDATE_FIELDS = {
    "document_id",
    "paper",
    "polymer_entities",
    "samples",
    "process_steps",
    "property_observations",
    "evidence",
    "publication",
}
V2_REQUIRED_STAGES = {
    "stage0_document",
    "stage1_material_mention",
    "stage2_polymer_entity",
    "stage3_sample_process",
    "stage4_property",
    "stage4r_table_recovery",
    "stage5_characterization",
    "candidate_publish",
}


def _read_object(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        errors.append(f"cannot read {path}: {exc}")
        return {}
    except json.JSONDecodeError as exc:
        errors.append(f"invalid JSON {path}: {exc}")
        return {}
    if not isinstance(payload, dict):
        errors.append(f"JSON root must be an object: {path}")
        return {}
    return payload


def _validate_v2_metadata(index: dict[str, Any], label: str, errors: list[str]) -> None:
    pipeline = index.get("pipeline")
    if not isinstance(pipeline, dict):
        errors.append(f"{label}: schema v2 requires pipeline metadata")
        return
    if pipeline.get("mode") != "preview":
        errors.append(f"{label}: pipeline.mode must be preview")
    if not GIT_SHA_RE.fullmatch(str(pipeline.get("git_commit") or "")):
        errors.append(f"{label}: pipeline.git_commit must be a full 40-character Git SHA")
    stages = set(pipeline.get("stages") or [])
    missing = sorted(V2_REQUIRED_STAGES - stages)
    if missing:
        errors.append(f"{label}: pipeline.stages is missing {', '.join(missing)}")
    if not SHA256_RE.fullmatch(str(pipeline.get("config_sha256") or "")):
        errors.append(f"{label}: pipeline.config_sha256 must be a SHA-256 digest")


def validate_collection(root: Path, *, verify_hashes: bool = True) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    label = root.name

    name_match = COLLECTION_RE.fullmatch(label)
    if not name_match:
        errors.append(f"{label}: collection name must end in _YYYYMMDD")

    index_path = root / "RESULT_INDEX.json"
    if not index_path.is_file():
        return [f"{label}: missing RESULT_INDEX.json"], warnings
    index = _read_object(index_path, errors)
    if not index:
        return errors, warnings

    for field in ("schema_version", "generated_at", "result_date", "result_mode", "documents"):
        if field not in index:
            errors.append(f"{label}: RESULT_INDEX.json is missing {field}")

    result_date = str(index.get("result_date") or "")
    try:
        parsed_date = date.fromisoformat(result_date)
    except ValueError:
        errors.append(f"{label}: result_date must use YYYY-MM-DD")
        parsed_date = None
    if name_match and parsed_date and name_match.group(1) != parsed_date.strftime("%Y%m%d"):
        errors.append(f"{label}: directory date and result_date do not match")
    if not str(index.get("generated_at") or "").strip():
        errors.append(f"{label}: generated_at cannot be empty")
    if not str(index.get("result_mode") or "").strip():
        errors.append(f"{label}: result_mode cannot be empty")

    schema_version = str(index.get("schema_version") or "")
    if schema_version.startswith("polymerlit-batch/2"):
        _validate_v2_metadata(index, label, errors)
    else:
        warnings.append(f"{label}: legacy index has no enforceable pipeline provenance")

    documents = index.get("documents")
    if not isinstance(documents, list) or not documents:
        errors.append(f"{label}: documents must be a non-empty list")
        return errors, warnings

    indexed_refs: list[str] = []
    for position, document in enumerate(documents):
        if not isinstance(document, dict):
            errors.append(f"{label}: documents[{position}] must be an object")
            continue
        ref_no = str(document.get("reference_no") or "")
        if not REF_RE.fullmatch(ref_no):
            errors.append(f"{label}: invalid reference_no at documents[{position}]: {ref_no}")
            continue
        indexed_refs.append(ref_no)
        if document.get("result_dir") not in (None, ref_no):
            errors.append(f"{label}/{ref_no}: result_dir must equal reference_no")

        result_dir = root / ref_no
        candidate_path = result_dir / "candidate.json"
        report_path = result_dir / "report_candidate.html"
        if not result_dir.is_dir():
            errors.append(f"{label}/{ref_no}: result directory is missing")
            continue
        if not candidate_path.is_file():
            errors.append(f"{label}/{ref_no}: candidate.json is missing")
            continue
        if not report_path.is_file() or report_path.stat().st_size == 0:
            errors.append(f"{label}/{ref_no}: report_candidate.html is missing or empty")

        candidate = _read_object(candidate_path, errors)
        if candidate:
            if candidate.get("document_id") != ref_no:
                errors.append(f"{label}/{ref_no}: candidate.document_id does not match directory")
            missing_fields = sorted(REQUIRED_CANDIDATE_FIELDS - candidate.keys())
            if missing_fields:
                errors.append(f"{label}/{ref_no}: candidate is missing {', '.join(missing_fields)}")
            publication = candidate.get("publication")
            if not isinstance(publication, dict) or publication.get("status") != "complete":
                errors.append(f"{label}/{ref_no}: candidate publication status must be complete")

        files = document.get("files")
        if not isinstance(files, list) or not files:
            errors.append(f"{label}/{ref_no}: index must contain a non-empty files manifest")
            continue
        for file_record in files:
            if not isinstance(file_record, dict):
                errors.append(f"{label}/{ref_no}: files entries must be objects")
                continue
            file_name = str(file_record.get("name") or "")
            if Path(file_name).name != file_name:
                errors.append(f"{label}/{ref_no}: files manifest contains unsafe path {file_name}")
                continue
            artifact = result_dir / file_name
            if not artifact.is_file():
                errors.append(f"{label}/{ref_no}: indexed file is missing: {file_name}")
                continue
            expected_size = file_record.get("size_bytes")
            if expected_size is not None and artifact.stat().st_size != expected_size:
                errors.append(f"{label}/{ref_no}: size mismatch for {file_name}")
            expected_hash = str(file_record.get("sha256") or "")
            if not SHA256_RE.fullmatch(expected_hash):
                errors.append(f"{label}/{ref_no}: invalid SHA-256 for {file_name}")
            elif verify_hashes:
                actual_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
                if actual_hash != expected_hash:
                    errors.append(f"{label}/{ref_no}: SHA-256 mismatch for {file_name}")

    if len(indexed_refs) != len(set(indexed_refs)):
        errors.append(f"{label}: duplicate reference_no values in documents")
    actual_refs = {
        item.name
        for item in root.iterdir()
        if item.is_dir() and REF_RE.fullmatch(item.name)
    }
    if actual_refs != set(indexed_refs):
        errors.append(
            f"{label}: index/directory mismatch; only in index={sorted(set(indexed_refs) - actual_refs)}, "
            f"only on disk={sorted(actual_refs - set(indexed_refs))}"
        )

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.name in PROHIBITED_NAMES or path.suffix.lower() in PROHIBITED_SUFFIXES:
            errors.append(f"{label}: prohibited file in published data: {path.relative_to(root)}")
        if path.stat().st_size >= 95 * 1024 * 1024:
            errors.append(f"{label}: file is too large for normal GitHub publication: {path.relative_to(root)}")

    return errors, warnings


def validate_root(root: Path, *, verify_hashes: bool = True) -> tuple[list[str], list[str]]:
    if not root.is_dir():
        return [f"batch root does not exist: {root}"], []
    collections = sorted(item for item in root.iterdir() if item.is_dir())
    if not collections:
        return [f"no batch result collections found under {root}"], []
    errors: list[str] = []
    warnings: list[str] = []
    for collection in collections:
        collection_errors, collection_warnings = validate_collection(
            collection,
            verify_hashes=verify_hashes,
        )
        errors.extend(collection_errors)
        warnings.extend(collection_warnings)
    return errors, warnings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path("batch_results"))
    parser.add_argument("--skip-hashes", action="store_true", help="skip artifact digest calculation")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    errors, warnings = validate_root(args.root, verify_hashes=not args.skip_hashes)
    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if errors:
        print(f"batch publication validation failed with {len(errors)} error(s)", file=sys.stderr)
        return 1
    print(f"batch publication validation passed for {args.root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
