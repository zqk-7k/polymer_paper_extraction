"""审计 Preview Stage4R 的样品绑定与候选守恒。

该工具只读取批次结果，不修改任何 Stage4/Stage6 文件。输出按文档和绑定
方式拆分，便于比较绑定器改造前后的 unmatched/ambiguous/resolved 变化。
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping


def _load(path: Path) -> Mapping[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise ValueError(f"JSON 根对象必须是 object：{path}")
    return payload


def _document_dirs(batch_root: Path) -> list[Path]:
    return sorted(
        path for path in batch_root.iterdir()
        if path.is_dir()
        and path.name.startswith("reference_no_")
        and (path / "stage4r_unified_audit.json").is_file()
    )


def audit_batch(batch_root: Path) -> dict[str, Any]:
    documents: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    basis_counts: Counter[str] = Counter()
    conservation_failures: list[str] = []
    examples: dict[str, list[dict[str, Any]]] = {
        "unmatched_sample": [],
        "ambiguous_sample": [],
        "matched": [],
    }

    for document_dir in _document_dirs(batch_root):
        payload = _load(document_dir / "stage4r_unified_audit.json")
        summary = payload.get("summary") or {}
        outcomes = [
            item for item in payload.get("candidate_outcomes") or []
            if isinstance(item, Mapping)
        ]
        doc_status = Counter(
            str(item.get("sample_resolution_status") or "not_recorded")
            for item in outcomes
        )
        doc_basis = Counter(
            str(item.get("sample_resolution_basis") or "not_recorded")
            for item in outcomes
            if item.get("sample_resolution_status") == "matched"
        )
        status_counts.update(doc_status)
        basis_counts.update(doc_basis)
        conservation = summary.get("candidate_conservation") or {}
        if int(conservation.get("unaccounted_candidate_count") or 0) != 0:
            conservation_failures.append(document_dir.name)
        for status in examples:
            for item in outcomes:
                if item.get("sample_resolution_status") != status:
                    continue
                if len(examples[status]) >= 12:
                    break
                examples[status].append({
                    "document_id": document_dir.name,
                    "candidate_id": item.get("candidate_id"),
                    "sample_label_raw": item.get("sample_label_raw"),
                    "sample_matches": item.get("sample_matches") or [],
                    "table_id": item.get("sample_binding_context", {}).get("table_id")
                    if isinstance(item.get("sample_binding_context"), Mapping)
                    else None,
                    "reason": item.get("reason"),
                    "basis": item.get("sample_resolution_basis"),
                    "anchors": item.get("sample_binding_anchors") or [],
                })
        documents.append({
            "document_id": document_dir.name,
            "candidate_count": int(summary.get("candidate_count") or 0),
            "integrated_count": int(summary.get("integrated_count") or 0),
            "unmatched_sample_count": int(summary.get("unmatched_sample_count") or 0),
            "ambiguous_sample_count": int(summary.get("ambiguous_sample_count") or 0),
            "invalid_candidate_count": int(summary.get("invalid_candidate_count") or 0),
            "unaccounted_candidate_count": int(
                conservation.get("unaccounted_candidate_count") or 0
            ),
            "sample_resolution_status_counts": dict(sorted(doc_status.items())),
            "sample_resolution_basis_counts": dict(sorted(doc_basis.items())),
        })

    return {
        "audit_schema_version": "preview_binding_audit.v0.1",
        "batch_root": str(batch_root.resolve()),
        "document_count": len(documents),
        "summary": {
            "sample_resolution_status_counts": dict(sorted(status_counts.items())),
            "sample_resolution_basis_counts": dict(sorted(basis_counts.items())),
            "conservation_failure_documents": conservation_failures,
            "conservation_balanced": not conservation_failures,
        },
        "examples": examples,
        "documents": documents,
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Preview 样品绑定审计",
        "",
        f"- 文档数：{report.get('document_count', 0)}",
        f"- 绑定状态：`{summary.get('sample_resolution_status_counts', {})}`",
        f"- 绑定方式：`{summary.get('sample_resolution_basis_counts', {})}`",
        f"- 守恒通过：`{summary.get('conservation_balanced', False)}`",
        "",
        "## 文档明细",
        "",
        "| 文档 | 候选 | 已整合 | 未匹配 | 歧义 | 硬错误 | 未解释 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in report.get("documents") or []:
        lines.append(
            "| {document_id} | {candidate_count} | {integrated_count} | "
            "{unmatched_sample_count} | {ambiguous_sample_count} | "
            "{invalid_candidate_count} | {unaccounted_candidate_count} |".format(**item)
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="审计 Preview Stage4R 样品绑定")
    parser.add_argument("--batch-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()
    report = audit_batch(args.batch_root.expanduser().resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render_markdown(report), encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
