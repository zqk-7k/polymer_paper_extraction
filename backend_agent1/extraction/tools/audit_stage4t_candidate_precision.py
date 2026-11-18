"""生成 Stage 4T 候选逐格 fixture 和只读审计报告。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stages.stage4t_candidate_precision import (
    audit_candidate_fixture,
    build_fixture_from_sidecars,
    build_expected_cell_fixture_from_sidecars,
    build_extended_fixture_from_sidecars,
    render_audit_markdown,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sidecar-root", type=Path, required=True)
    parser.add_argument("--fixture-output", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument("--ref-no", action="append", required=True)
    parser.add_argument(
        "--include-known-gap-cells",
        action="store_true",
        help="将已定位的 3 个 T_4_49 漏格纳入 v0.2 expected-cell fixture",
    )
    parser.add_argument(
        "--include-solubility-tables",
        action="store_true",
        help="在 v0.2 数值底稿上加入 2 张定性溶解性表，生成 v0.3",
    )
    args = parser.parse_args()

    if args.include_solubility_tables:
        fixture = build_extended_fixture_from_sidecars(args.sidecar_root, args.ref_no)
    elif args.include_known_gap_cells:
        fixture = build_expected_cell_fixture_from_sidecars(args.sidecar_root, args.ref_no)
    else:
        fixture = build_fixture_from_sidecars(args.sidecar_root, args.ref_no)
    report = audit_candidate_fixture(fixture, args.sidecar_root)
    for path, payload in ((args.fixture_output, fixture), (args.json_output, report)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.write_text(render_audit_markdown(report), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 1 if report["failure_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
