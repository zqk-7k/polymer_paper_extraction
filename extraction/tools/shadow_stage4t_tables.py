"""生成 Stage 4T 表级性质 Shadow 报告，不修改现有抽取结果。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stages.stage4t_table_property import render_shadow_markdown, shadow_extract_batch


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 Stage 4T 表级性质 Shadow 报告")
    parser.add_argument("--batch-root", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args()

    report = shadow_extract_batch(args.batch_root)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    args.markdown_output.write_text(
        render_shadow_markdown(report),
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
