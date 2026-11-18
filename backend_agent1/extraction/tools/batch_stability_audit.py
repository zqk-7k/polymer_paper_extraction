"""Compare two production batch directories for deterministic stability."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any


COMPARE_FILES = (
    "stage4_properties.json",
    "stage4_properties.unified_preview.json",
    "stage4t_shadow.json",
    "stage5_characterizations.json",
    "candidate.json",
    "final.json",
    "stage6_validation.json",
)
VOLATILE_KEYS = {"generated_at", "timestamp", "run_id", "batch_id", "input_hash"}


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in sorted(value.items()) if k not in VOLATILE_KEYS}
    if isinstance(value, list):
        return [_canonical(v) for v in value]
    return value


def _signature(path: Path) -> str:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        payload = json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = path.read_bytes()
    return hashlib.sha256(payload).hexdigest()


def compare_batches(left: Path, right: Path, output: Path) -> dict[str, Any]:
    left, right, output = left.resolve(), right.resolve(), output.resolve()
    left_docs = {p.name: p for p in left.glob("reference_no_*") if p.is_dir()}
    right_docs = {p.name: p for p in right.glob("reference_no_*") if p.is_dir()}
    documents = []
    for ref in sorted(set(left_docs) | set(right_docs)):
        lp, rp = left_docs.get(ref), right_docs.get(ref)
        file_diffs = []
        for name in COMPARE_FILES:
            lf, rf = (lp / name if lp else None), (rp / name if rp else None)
            if lf is None or not lf.exists():
                file_diffs.append({"file": name, "status": "missing_left"})
            elif rf is None or not rf.exists():
                file_diffs.append({"file": name, "status": "missing_right"})
            else:
                ls, rs = _signature(lf), _signature(rf)
                if ls != rs:
                    file_diffs.append({"file": name, "status": "changed", "left_sha256": ls, "right_sha256": rs})
        if file_diffs:
            documents.append({"reference_no": ref, "status": "changed", "file_diffs": file_diffs})
        else:
            documents.append({"reference_no": ref, "status": "stable", "file_diffs": []})

    changed = [d for d in documents if d["status"] == "changed"]
    result = {
        "schema_version": "batch_stability_audit.v1",
        "generated_at": date.today().isoformat(),
        "left_batch": str(left),
        "right_batch": str(right),
        "compare_files": list(COMPARE_FILES),
        "documents": len(documents),
        "stable_documents": len(documents) - len(changed),
        "changed_documents": len(changed),
        "status": "stable" if not changed else "changed",
        "document_diffs": documents,
        "notes": [
            "JSON 文件按排序后的规范化内容计算签名，并忽略 generated_at/timestamp/run_id/batch_id/input_hash。",
            "两批次若存在有意代码或输入变更，changed 是回归差异，不自动判定为并发不稳定。",
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "stability_report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# 批次稳定性审计", "", f"左批次：`{left}`", f"右批次：`{right}`", "",
        f"文献：{len(documents)}；稳定：{result['stable_documents']}；有差异：{result['changed_documents']}",
        "", "| 文献 | 状态 | 差异文件 |", "|---|---|---|",
    ]
    for doc in documents:
        names = ", ".join(d["file"] for d in doc["file_diffs"]) or "-"
        lines.append(f"| {doc['reference_no']} | {doc['status']} | {names} |")
    (output / "stability_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--left", type=Path, required=True)
    parser.add_argument("--right", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare_batches(args.left, args.right, args.output)
    print(json.dumps({k: result[k] for k in ("documents", "stable_documents", "changed_documents", "status")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
