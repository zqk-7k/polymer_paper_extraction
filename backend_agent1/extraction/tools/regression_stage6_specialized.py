"""Step 9 回归：对 output_test 下全部文献重跑 Stage 6，核对 specialized 合并守恒。

Stage 6 是纯离线校验，直接复用已有 stage0-5 产物，不触发 LLM 调用。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

EXTRACTION_ROOT = Path(__file__).resolve().parents[1]
if str(EXTRACTION_ROOT) not in sys.path:
    sys.path.insert(0, str(EXTRACTION_ROOT))

from schema.polymer_schema import (
    Stage0Document,
    Stage1Document,
    Stage2Document,
    Stage3Document,
    Stage4Document,
    Stage5Document,
)
from stages.stage6_validate_merge import validate_and_merge

STAGE_FILES = {
    "stage0": ("stage0_blocks.json", Stage0Document),
    "stage1": ("stage1_mentions.json", Stage1Document),
    "stage2": ("stage2_entities.json", Stage2Document),
    "stage3": ("stage3_process.json", Stage3Document),
    "stage4": ("stage4_properties.json", Stage4Document),
    "stage5": ("stage5_characterizations.json", Stage5Document),
}


def load_stages(doc_dir: Path) -> dict[str, object] | None:
    loaded: dict[str, object] = {}
    for key, (filename, model) in STAGE_FILES.items():
        path = doc_dir / filename
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        try:
            loaded[key] = model.model_validate(payload)
        except ValidationError:
            return None
    return loaded


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="output_test")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()

    root = (EXTRACTION_ROOT / args.root).resolve()
    doc_dirs = sorted(
        path for path in root.glob("reference_no_*") if path.is_dir()
    )
    if args.limit:
        doc_dirs = doc_dirs[: args.limit]

    rows: list[dict[str, object]] = []
    failures: list[str] = []
    skipped: list[str] = []

    for doc_dir in doc_dirs:
        stages = load_stages(doc_dir)
        if stages is None:
            skipped.append(doc_dir.name)
            continue
        stage4 = stages["stage4"]
        stage5 = stages["stage5"]
        expected = (
            len(stage4.specialized_property_observations)
            + len(stage5.specialized_property_observations)
        )
        try:
            final, validation = validate_and_merge(
                stages["stage0"],
                stages["stage1"],
                stages["stage2"],
                stages["stage3"],
                stage4,
                stage5,
                preview=args.preview,
            )
        except Exception as exc:  # noqa: BLE001 - 回归脚本需报告全部异常
            failures.append(f"{doc_dir.name}: {type(exc).__name__}: {exc}")
            continue

        if final is None:
            failures.append(
                f"{doc_dir.name}: validation failed "
                f"({validation.error_count} errors) "
                f"{[item.code for item in validation.errors][:3]}"
            )
            continue

        actual = len(final.specialized_property_observations)
        status_counts: dict[str, int] = {}
        for item in final.specialized_property_observations:
            status_counts[item.publication_status] = (
                status_counts.get(item.publication_status, 0) + 1
            )
        conserved = actual == expected
        if not conserved:
            failures.append(
                f"{doc_dir.name}: specialized 不守恒 "
                f"expected={expected} actual={actual}"
            )
        rows.append({
            "document": doc_dir.name,
            "status": validation.status,
            "stage4_sp": len(stage4.specialized_property_observations),
            "stage5_sp": len(stage5.specialized_property_observations),
            "final_sp": actual,
            "conserved": conserved,
            "by_status": status_counts,
            "properties": len(final.property_observations),
            "warnings": validation.warning_count,
        })

    print(f"{'document':<24}{'status':<22}{'s4':>4}{'s5':>4}{'final':>7}  by_status")
    print("-" * 88)
    for row in rows:
        flag = "" if row["conserved"] else "  <-- MISMATCH"
        print(
            f"{row['document']:<24}{row['status']:<22}"
            f"{row['stage4_sp']:>4}{row['stage5_sp']:>4}{row['final_sp']:>7}"
            f"  {row['by_status'] or '{}'}{flag}"
        )

    total_expected = sum(row["stage4_sp"] + row["stage5_sp"] for row in rows)
    total_actual = sum(row["final_sp"] for row in rows)
    print("-" * 88)
    print(
        f"docs={len(rows)} skipped={len(skipped)} "
        f"specialized_total={total_actual}/{total_expected} "
        f"failures={len(failures)}"
    )
    if skipped:
        print(f"skipped: {', '.join(skipped)}")
    for line in failures:
        print(f"FAIL {line}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
