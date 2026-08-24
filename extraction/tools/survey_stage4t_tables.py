"""运行 Stage 4T P1-a 表结构调查。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stages.stage4t_table_survey import render_markdown, survey_batch


def main() -> int:
    parser = argparse.ArgumentParser(description="调查 Stage 4T 表格结构")
    parser.add_argument("--batch-root", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args()

    report = survey_batch(args.batch_root)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
