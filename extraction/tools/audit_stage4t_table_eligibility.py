"""生成 Stage 4T 表格 eligibility 人工复核报告。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stages.stage4t_table_eligibility import audit_files, render_markdown


def main() -> int:
    parser = argparse.ArgumentParser(description="审计 Stage 4T 表格 eligibility fixture")
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--survey", type=Path, required=True)
    parser.add_argument("--shadow-report", type=Path, required=True)
    parser.add_argument("--binding-fixture", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args()

    report = audit_files(
        args.fixture,
        args.survey,
        args.shadow_report,
        args.binding_fixture,
    )
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
