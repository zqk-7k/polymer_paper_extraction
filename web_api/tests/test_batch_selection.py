import json
from pathlib import Path

from web_api.app import _select_batch_root


def _write_index(root: Path, result_date: str, generated_at: str = "") -> None:
    root.mkdir(parents=True)
    (root / "RESULT_INDEX.json").write_text(
        json.dumps({"result_date": result_date, "generated_at": generated_at}),
        encoding="utf-8",
    )


def test_selects_newest_indexed_collection(tmp_path: Path) -> None:
    _write_index(tmp_path / "older", "2026-08-08")
    _write_index(tmp_path / "newer", "2026-08-09")

    root, index = _select_batch_root(tmp_path)

    assert root.name == "newer"
    assert index["result_date"] == "2026-08-09"


def test_explicit_collection_overrides_newest(tmp_path: Path) -> None:
    _write_index(tmp_path / "pinned", "2026-08-08")
    _write_index(tmp_path / "newer", "2026-08-09")

    root, _ = _select_batch_root(tmp_path, "pinned")

    assert root.name == "pinned"


def test_ignores_invalid_and_unsafe_collection_names(tmp_path: Path) -> None:
    (tmp_path / "invalid").mkdir()
    _write_index(tmp_path / "valid", "2026-08-09")

    root, _ = _select_batch_root(tmp_path, "../invalid")

    assert root.name == "valid"
