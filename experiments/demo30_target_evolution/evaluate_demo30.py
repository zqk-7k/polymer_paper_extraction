"""Evaluate a review collection against local PoLyInfo anchors.

PoLyInfo is treated as a reference anchor, not complete full-text gold. The report
therefore separates exact value recall, semantic property recall, process-family
coverage, and nine-field specialized coverage.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


MODULE_DIR = Path(__file__).resolve().parent
REPO_ROOT = MODULE_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from web_api.app import (  # noqa: E402
    _align_property_records,
    _alignment_metrics,
    _candidate_completeness,
    _completeness_quality,
    _polyinfo_processes,
    _polyinfo_properties,
    _read_polyinfo_samples,
)


SPECIALIZED_FIELDS = (
    "average_molecular_weight",
    "solution_viscosity",
    "crystallinity",
    "degree_of_polymerization",
    "crystallographic_data",
    "primary_structure_informations",
    "morphology",
    "stereoregularity",
    "characteristics_of_material",
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def discover_polyinfo(root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    preferred: list[Path] = []
    other: list[Path] = []
    for path in root.rglob("reference_no_*"):
        if not path.is_dir() or not any(path.glob("*.json")):
            continue
        (preferred if path.parent.name in {"有doi", "无doi"} else other).append(path)
    for path in sorted(preferred) + sorted(other):
        result.setdefault(path.name, path)
    return result


def counts_for_alignment(alignment: Iterable[dict[str, Any]]) -> Counter[str]:
    return Counter(str(item["status"]) for item in alignment)


def metric_payload(counts: Counter[str]) -> dict[str, Any]:
    return _alignment_metrics({
        key: counts[key]
        for key in ("matched", "value_diff", "polyinfo_only", "extraction_only")
    })


def semantic_metrics(counts: Counter[str]) -> dict[str, Any]:
    recovered = counts["matched"] + counts["value_diff"]
    anchored = recovered + counts["polyinfo_only"]
    predicted = recovered + counts["extraction_only"]
    precision = recovered / predicted if predicted else 0.0
    recall = recovered / anchored if anchored else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "recovered_name_records": recovered,
        "anchored_records": anchored,
        "predicted_records": predicted,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def candidate_specialized_fields(candidate: dict[str, Any]) -> set[str]:
    return {
        str(item.get("source_field"))
        for item in candidate.get("specialized_property_observations") or []
        if item.get("publication_status") == "published"
        and item.get("source_field") in SPECIALIZED_FIELDS
    }


def polyinfo_specialized_fields(samples: list[dict[str, Any]]) -> set[str]:
    return {
        field
        for field in SPECIALIZED_FIELDS
        if any(sample.get(field) not in (None, "", [], {}) for sample in samples)
    }


def _process_family(text: str) -> str | None:
    value = text.casefold()
    if any(token in value for token in ("polymer", "condens", "reaction condition", "synthesi")):
        return "polymerization"
    if any(token in value for token in ("mix", "blend", "compound", "knead")):
        return "mixing_blending"
    if any(token in value for token in ("mold", "press", "cast", "extrud", "spin", "draw")):
        return "forming"
    if any(token in value for token in ("anneal", "dry", "quench", "cure", "heat", "treat")):
        return "post_treatment"
    if "sample shape" in value:
        return "sample_shape"
    return None


def polyinfo_process_families(processes: list[dict[str, str]]) -> set[str]:
    return {
        family
        for item in processes
        if (family := _process_family(f"{item.get('kind', '')} {item.get('value', '')}"))
    }


def candidate_process_families(candidate: dict[str, Any]) -> set[str]:
    return {
        family
        for item in candidate.get("process_steps") or []
        if (family := _process_family(str(item.get("process_type") or "")))
    }


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def evaluate(batch_root: Path, polyinfo_root: Path) -> dict[str, Any]:
    index_path = batch_root / "REVIEW_INDEX.json"
    if not index_path.is_file():
        index_path = batch_root / "RESULT_INDEX.json"
    index = read_json(index_path)
    polyinfo_dirs = discover_polyinfo(polyinfo_root)
    overall = Counter()
    completeness = Counter()
    property_breakdown: dict[str, Counter[str]] = defaultdict(Counter)
    process_anchor = Counter()
    process_predicted = Counter()
    process_hit = Counter()
    specialized_anchor = Counter()
    specialized_predicted = Counter()
    specialized_hit = Counter()
    documents: list[dict[str, Any]] = []

    for document in index.get("documents") or []:
        ref_no = str(document.get("reference_no"))
        candidate_path = batch_root / ref_no / "candidate.json"
        if not candidate_path.is_file():
            continue
        candidate = read_json(candidate_path)
        polyinfo_dir = polyinfo_dirs.get(ref_no)
        if polyinfo_dir is None:
            documents.append({"ref_no": ref_no, "paired": False})
            continue
        samples = _read_polyinfo_samples(polyinfo_dir, include_structures=False)
        properties = _polyinfo_properties(samples)
        processes = _polyinfo_processes(samples)
        alignment = _align_property_records(
            properties,
            list(candidate.get("property_observations") or []),
        )
        status = counts_for_alignment(alignment)
        overall.update(status)
        for item in alignment:
            property_breakdown[str(item.get("canonical_name") or "unknown")][str(item["status"])] += 1
        completeness.update(_candidate_completeness(candidate))

        pi_process = polyinfo_process_families(processes)
        extraction_process = candidate_process_families(candidate)
        for family in pi_process:
            process_anchor[family] += 1
        for family in extraction_process:
            process_predicted[family] += 1
        for family in pi_process & extraction_process:
            process_hit[family] += 1

        pi_specialized = polyinfo_specialized_fields(samples)
        extraction_specialized = candidate_specialized_fields(candidate)
        for field in pi_specialized:
            specialized_anchor[field] += 1
        for field in extraction_specialized:
            specialized_predicted[field] += 1
        for field in pi_specialized & extraction_specialized:
            specialized_hit[field] += 1

        failure_stages = sorted(path.stem.replace("_failure", "") for path in (batch_root / ref_no).glob("stage*_failure.json"))
        documents.append({
            "ref_no": ref_no,
            "paired": True,
            "publication_status": (candidate.get("publication") or {}).get("status"),
            "extraction_properties": len(candidate.get("property_observations") or []),
            "polyinfo_properties": len(properties),
            "exact_matched": status["matched"],
            "value_diff": status["value_diff"],
            "polyinfo_only": status["polyinfo_only"],
            "extraction_only": status["extraction_only"],
            "polyinfo_process_families": sorted(pi_process),
            "extraction_process_families": sorted(extraction_process),
            "missing_process_families": sorted(pi_process - extraction_process),
            "polyinfo_specialized_fields": sorted(pi_specialized),
            "extraction_specialized_fields": sorted(extraction_specialized),
            "missing_specialized_fields": sorted(pi_specialized - extraction_specialized),
            "failure_stages": failure_stages,
        })

    property_rows = []
    for name, status in property_breakdown.items():
        exact = metric_payload(status)
        semantic = semantic_metrics(status)
        property_rows.append({
            "property": name,
            **exact,
            "semantic_recall": semantic["recall"],
        })
    property_rows.sort(key=lambda item: (-int(item["polyinfo_only"]), str(item["property"])))

    process_rows = [{
        "family": family,
        "anchor_documents": process_anchor[family],
        "predicted_documents": process_predicted[family],
        "matched_documents": process_hit[family],
        "recall": _ratio(process_hit[family], process_anchor[family]),
        "precision": _ratio(process_hit[family], process_predicted[family]),
    } for family in sorted(set(process_anchor) | set(process_predicted))]

    specialized_rows = [{
        "source_field": field,
        "anchor_documents": specialized_anchor[field],
        "predicted_documents": specialized_predicted[field],
        "matched_documents": specialized_hit[field],
        "recall": _ratio(specialized_hit[field], specialized_anchor[field]),
        "precision": _ratio(specialized_hit[field], specialized_predicted[field]),
    } for field in SPECIALIZED_FIELDS]

    process_totals = {
        "anchor_document_fields": sum(process_anchor.values()),
        "predicted_document_fields": sum(process_predicted.values()),
        "matched_document_fields": sum(process_hit.values()),
    }
    process_totals.update({
        "recall": _ratio(process_totals["matched_document_fields"], process_totals["anchor_document_fields"]),
        "precision": _ratio(process_totals["matched_document_fields"], process_totals["predicted_document_fields"]),
    })
    specialized_totals = {
        "anchor_document_fields": sum(specialized_anchor.values()),
        "predicted_document_fields": sum(specialized_predicted.values()),
        "matched_document_fields": sum(specialized_hit.values()),
    }
    specialized_totals.update({
        "recall": _ratio(specialized_totals["matched_document_fields"], specialized_totals["anchor_document_fields"]),
        "precision": _ratio(specialized_totals["matched_document_fields"], specialized_totals["predicted_document_fields"]),
    })

    return {
        "schema_version": "demo30-polyinfo-audit/1.0",
        "collection_id": batch_root.name,
        "metric_scope": {
            "reference": "PoLyInfo anchor; not full-text gold",
            "exact_property_recall": "one-to-one property name, compatible unit, value within 1% tolerance",
            "semantic_property_recall": "property name recovered; value may differ",
            "process_recall": "document-level broad process-family coverage",
            "specialized_recall": "document-level coverage of nine PoLyInfo source fields",
        },
        "document_count": len(documents),
        "paired_documents": sum(bool(item.get("paired")) for item in documents),
        "exact_property_alignment": metric_payload(overall),
        "semantic_property_alignment": semantic_metrics(overall),
        "candidate_quality": _completeness_quality(completeness),
        "process_alignment": process_totals,
        "specialized_alignment": specialized_totals,
        "property_breakdown": property_rows,
        "process_breakdown": process_rows,
        "specialized_breakdown": specialized_rows,
        "documents": documents,
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value for key, value in row.items()})


def render_html(report: dict[str, Any]) -> str:
    exact = report["exact_property_alignment"]
    semantic = report["semantic_property_alignment"]
    quality = report["candidate_quality"]
    specialized = report["specialized_alignment"]
    process = report["process_alignment"]
    top_gaps = report["property_breakdown"][:12]

    def pct(value: float) -> str:
        return f"{value * 100:.1f}%"

    def bars(rows: list[dict[str, Any]], key: str, label: str) -> str:
        chunks = []
        for row in rows:
            value = float(row.get("recall") or 0)
            chunks.append(
                f'<div class="bar-row"><span>{html.escape(str(row[key]))}</span>'
                f'<div><i style="width:{value * 100:.1f}%"></i></div><b>{pct(value)}</b>'
                f'<small>{row.get("matched_documents", row.get("matched", 0))}/'
                f'{row.get("anchor_documents", row.get("matched", 0) + row.get("value_diff", 0) + row.get("polyinfo_only", 0))}</small></div>'
            )
        return f'<section class="panel"><h2>{html.escape(label)}</h2>{"".join(chunks)}</section>'

    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>demo30 × PoLyInfo 基线审计</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f2f5f8;color:#14202b;font:15px/1.55 Inter,"Microsoft YaHei",sans-serif}}main{{max-width:1480px;margin:auto;padding:48px 34px 80px}}header{{background:#0c2431;color:#fff;padding:38px 42px;border-radius:8px}}header p{{color:#bcd2dc;max-width:900px}}.eyebrow{{color:#49c5b6;font-weight:700;letter-spacing:.08em}}h1{{font:700 36px/1.2 Georgia,serif;margin:8px 0}}h2{{font:700 20px Georgia,serif;margin:0 0 18px}}.metrics{{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin:18px 0}}.metric,.panel{{background:#fff;border:1px solid #dce5ea;border-radius:7px;box-shadow:0 8px 28px rgba(16,42,56,.06)}}.metric{{padding:18px}}.metric span{{display:block;color:#61727c;font-size:13px}}.metric b{{font:700 27px Georgia,serif}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}.panel{{padding:24px;margin-top:16px}}.bar-row{{display:grid;grid-template-columns:minmax(180px,1.5fr) 2fr 70px 55px;gap:12px;align-items:center;margin:11px 0}}.bar-row>div{{height:8px;background:#e8eef1}}.bar-row i{{display:block;height:100%;background:#0b8d83}}.bar-row b,.bar-row small{{text-align:right}}table{{width:100%;border-collapse:collapse}}th,td{{padding:10px 8px;border-bottom:1px solid #e2e9ed;text-align:left}}th{{color:#53656f;font-size:12px;text-transform:uppercase}}.note{{border-left:4px solid #e4a11b;background:#fff8e8;padding:14px 18px;margin:18px 0}}@media(max-width:900px){{.metrics{{grid-template-columns:repeat(2,1fr)}}.grid{{grid-template-columns:1fr}}}}
</style></head><body><main><header><div class="eyebrow">REFERENCE-ALIGNED BASELINE · {html.escape(report['collection_id'])}</div><h1>demo30 与 PoLyInfo 的全量差异</h1><p>同一 reference_no 下逐条比较性质名称、数值和单位，并分别审计工艺族、九类专用字段、证据和样品绑定。PoLyInfo 在这里是参考锚点，不是完整全文 gold。</p></header>
<div class="metrics"><div class="metric"><span>配对文献</span><b>{report['paired_documents']}/{report['document_count']}</b></div><div class="metric"><span>数值完全一致 Recall</span><b>{pct(exact['recall'])}</b></div><div class="metric"><span>性质语义 Recall</span><b>{pct(semantic['recall'])}</b></div><div class="metric"><span>九类字段 Recall</span><b>{pct(specialized['recall'])}</b></div><div class="metric"><span>工艺族 Recall</span><b>{pct(process['recall'])}</b></div><div class="metric"><span>证据绑定</span><b>{pct(quality['evidence_coverage'])}</b></div></div>
<div class="note"><b>口径纪律：</b>“仅 PoLyInfo”表示当前候选没有与锚点对齐，不自动等于全文漏抽；“仅抽取”也可能是 PoLyInfo 未收录的有效补充。两类都需要原文裁决。</div>
<div class="grid">{bars(report['specialized_breakdown'],'source_field','九类专用字段：文献级 Recall')}{bars(report['process_breakdown'],'family','工艺族：文献级 Recall')}</div>
<section class="panel"><h2>缺失最多的性质锚点</h2><table><thead><tr><th>性质</th><th>完全一致</th><th>同名值不同</th><th>仅 PoLyInfo</th><th>仅抽取</th><th>数值 Recall</th><th>语义 Recall</th></tr></thead><tbody>{''.join(f"<tr><td>{html.escape(str(row['property']))}</td><td>{row['matched']}</td><td>{row['value_diff']}</td><td>{row['polyinfo_only']}</td><td>{row['extraction_only']}</td><td>{pct(row['recall'])}</td><td>{pct(row['semantic_recall'])}</td></tr>" for row in top_gaps)}</tbody></table></section>
</main></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-root", type=Path, default=REPO_ROOT / "batch_results" / "demo30_preview_20260824")
    parser.add_argument("--polyinfo-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=MODULE_DIR / "runs" / "baseline")
    args = parser.parse_args()
    report = evaluate(args.batch_root.resolve(), args.polyinfo_root.resolve())
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "baseline_audit.json", report)
    write_csv(output / "per_document.csv", report["documents"])
    write_csv(output / "property_gaps.csv", report["property_breakdown"])
    write_csv(output / "process_gaps.csv", report["process_breakdown"])
    write_csv(output / "specialized_gaps.csv", report["specialized_breakdown"])
    (output / "baseline_report.html").write_text(render_html(report), encoding="utf-8")
    print(output / "baseline_audit.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
