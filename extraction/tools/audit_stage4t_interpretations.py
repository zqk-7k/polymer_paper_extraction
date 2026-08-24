from __future__ import annotations

import argparse
import json
from pathlib import Path

from stages.stage4t_interpretation_audit import (
    audit_interpretations,
    render_audit_markdown,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="离线审计 Stage 4T LLM 表结构解释"
    )
    parser.add_argument("--batch-root", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()

    report = audit_interpretations(
        batch_root=args.batch_root,
        fixture_path=args.fixture,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    args.output_md.write_text(
        render_audit_markdown(report),
        encoding="utf-8",
    )
    return 0 if report["summary"]["failed_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
