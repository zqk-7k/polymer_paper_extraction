"""生成 Stage 4T precision Shadow 报告，不修改抽取结果。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stages.stage4t_precision_audit import audit_fixture_file, audit_shadow_files


def main() -> int:
    parser = argparse.ArgumentParser(description="审计 Stage 4T fixture 的性质映射冲突")
    parser.add_argument("--fixture", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preview-root", type=Path)
    mode.add_argument("--shadow-report", type=Path)
    parser.add_argument("--binding-fixture", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.shadow_report is not None:
        if args.binding_fixture is None:
            parser.error("--shadow-report 需要同时指定 --binding-fixture")
        report = audit_shadow_files(
            args.fixture,
            args.binding_fixture,
            args.shadow_report,
        )
    else:
        report = audit_fixture_file(args.fixture, args.preview_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 1 if report.get("failures") else 0


if __name__ == "__main__":
    raise SystemExit(main())
