"""Audit a Stage 4T Shadow report against the reviewed binding fixture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stages.stage4t_shadow_binding_audit import audit_shadow_files, render_markdown


def main() -> int:
    parser = argparse.ArgumentParser(description="审计 Stage 4T Shadow 性质映射与样品绑定")
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--shadow-report", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args()

    report = audit_shadow_files(args.fixture, args.shadow_report)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
