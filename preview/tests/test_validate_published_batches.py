import hashlib
import json
from pathlib import Path

from preview.validate_published_batches import validate_collection


def _write_valid_collection(root: Path) -> Path:
    collection = root / "preview_smoke_20260810"
    result_dir = collection / "reference_no_0000001"
    result_dir.mkdir(parents=True)
    candidate = {
        "document_id": "reference_no_0000001",
        "paper": {},
        "polymer_entities": [],
        "samples": [],
        "process_steps": [],
        "property_observations": [],
        "evidence": [],
        "publication": {"status": "complete"},
    }
    artifacts = {
        "candidate.json": json.dumps(candidate),
        "report_candidate.html": "<html>report</html>",
    }
    files = []
    for name, content in artifacts.items():
        payload = content.encode()
        (result_dir / name).write_bytes(payload)
        files.append({"name": name, "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
    index = {
        "schema_version": "polymerlit-batch/2.0",
        "generated_at": "2026-08-10T10:00:00+08:00",
        "result_date": "2026-08-10",
        "result_mode": "preview",
        "pipeline": {
            "mode": "preview",
            "git_commit": "a" * 40,
            "config_sha256": "b" * 64,
            "stages": [
                "stage0_document",
                "stage1_material_mention",
                "stage2_polymer_entity",
                "stage3_sample_process",
                "stage4_property",
                "stage4r_table_recovery",
                "stage5_characterization",
                "candidate_publish",
            ],
        },
        "documents": [{"reference_no": "reference_no_0000001", "result_dir": "reference_no_0000001", "files": files}],
    }
    (collection / "RESULT_INDEX.json").write_text(json.dumps(index), encoding="utf-8")
    return collection


def test_valid_v2_collection_passes(tmp_path: Path) -> None:
    collection = _write_valid_collection(tmp_path)
    errors, warnings = validate_collection(collection)
    assert errors == []
    assert warnings == []


def test_missing_stage4r_provenance_fails(tmp_path: Path) -> None:
    collection = _write_valid_collection(tmp_path)
    index_path = collection / "RESULT_INDEX.json"
    index = json.loads(index_path.read_text())
    index["pipeline"]["stages"].remove("stage4r_table_recovery")
    index_path.write_text(json.dumps(index))
    errors, _ = validate_collection(collection)
    assert any("stage4r_table_recovery" in error for error in errors)


def test_candidate_hash_mismatch_fails(tmp_path: Path) -> None:
    collection = _write_valid_collection(tmp_path)
    (collection / "reference_no_0000001" / "candidate.json").write_text("{}")
    errors, _ = validate_collection(collection)
    assert any("SHA-256 mismatch" in error for error in errors)


def test_legacy_hash_is_not_enforced_across_platform_line_endings(tmp_path: Path) -> None:
    collection = _write_valid_collection(tmp_path)
    index_path = collection / "RESULT_INDEX.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["schema_version"] = "polymerlit-batch/1.0"
    index.pop("pipeline")
    index["documents"][0]["files"][0]["sha256"] = "0" * 64
    index_path.write_text(json.dumps(index), encoding="utf-8")

    errors, warnings = validate_collection(collection)

    assert errors == []
    assert any("legacy index" in warning for warning in warnings)


def test_v2_text_hash_uses_canonical_lf_line_endings(tmp_path: Path) -> None:
    collection = _write_valid_collection(tmp_path)
    candidate_path = collection / "reference_no_0000001" / "candidate.json"
    original = candidate_path.read_bytes()
    candidate_path.write_bytes(original.replace(b", ", b", \r\n"))
    normalized = candidate_path.read_bytes().replace(b"\r\n", b"\n")
    index_path = collection / "RESULT_INDEX.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    record = index["documents"][0]["files"][0]
    record["size_bytes"] = len(normalized)
    record["sha256"] = hashlib.sha256(normalized).hexdigest()
    index_path.write_text(json.dumps(index), encoding="utf-8")

    errors, _ = validate_collection(collection)

    assert errors == []
