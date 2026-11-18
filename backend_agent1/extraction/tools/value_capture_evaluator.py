"""Evaluate whether a PolyInfo value was captured by Preview.

This evaluator intentionally answers a narrower question than the publication
coverage matcher: does any Preview extraction layer contain a numerically
correct value for the same property in the same document?  Sample binding,
publication status and final-schema acceptance are reported as provenance, but
are not required for the primary value-capture metric.

The default denominator excludes paired PolyInfo rows (for example Td and a
weight-loss threshold), matching the project's review rule that paired,
derived and outside-the-extraction data are not primary extraction targets.
Use ``--include-paired`` when a paired-event side analysis is desired.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from tools.polyinfo_coverage_matcher import (
    CREDIBLE,
    EXCLUDED_DOCS,
    LC_CONTEXT_RE,
    classify_interval,
    classify_pred,
    classify_quantity_kind,
    classify_surface_component,
    extract_evidence_labels,
    extract_tga_threshold,
    load_gt,
    load_gt_points,
    match_doc,
    TIER_ORDER,
)


SOURCE_FILES = (
    ("stage4n", "stage4_properties.json"),
    ("stage4t", "stage4t_shadow.json"),
    ("stage4r", "stage4_properties.unified_preview.json"),
    ("final", "final.json"),
)
SOURCE_ORDER = {
    "stage4n_raw_llm": 0,
    "stage4n": 1,
    "stage4t": 2,
    "stage4r": 3,
    "final": 4,
}
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.S | re.I)


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _json_load(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_gt_exclusions(path: str | os.PathLike[str]) -> dict[tuple[str, str], dict[str, Any]]:
    """读取版本化 GT 排除清单，键为 (doc_id, row_id)。"""
    payload = _json_load(Path(path))
    entries = payload.get("exclusions") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        raise ValueError("GT exclusion manifest 必须包含 exclusions 数组")
    exclusions: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("GT exclusion manifest 条目必须是对象")
        doc_id = entry.get("doc_id")
        row_id = entry.get("row_id")
        reason = entry.get("reason")
        if not all(isinstance(value, str) and value.strip() for value in (doc_id, row_id, reason)):
            raise ValueError("GT exclusion manifest 条目缺少 doc_id、row_id 或 reason")
        key = (doc_id, row_id)
        if key in exclusions:
            raise ValueError(f"GT exclusion manifest 存在重复条目：{key}")
        exclusions[key] = entry
    return exclusions


def _raw_json(value: Any) -> dict[str, Any] | None:
    """Parse a raw LLM content string without accepting arbitrary text."""
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    fenced = _FENCE_RE.match(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        # Some providers prepend a short sentence.  Only attempt the bounded
        # outer-object slice; malformed or non-object content remains ignored.
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(text[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None


def _evidence_labels(obj: dict[str, Any], extra: Iterable[str] = ()) -> list[str]:
    labels: list[str] = []
    labels.extend(str(x) for x in extra if x)
    labels.extend(extract_evidence_labels(obj.get("evidence")))
    locator = obj.get("evidence_locator")
    if isinstance(locator, dict):
        path = locator.get("header_path") or []
        labels.extend(str(x) for x in path if x)
        for key in ("column_label", "row_label"):
            if locator.get(key):
                labels.append(str(locator[key]))
    for key in ("header_context", "header_labels"):
        value = obj.get(key)
        if isinstance(value, (list, tuple)):
            labels.extend(str(x) for x in value if x)
        elif value:
            labels.append(str(value))
    # Keep order stable while avoiding repeated labels from nested evidence.
    return list(dict.fromkeys(labels))


def _value_fields(obj: dict[str, Any]) -> tuple[Any, ...]:
    raw = obj.get("value_raw")
    if raw is None:
        raw = obj.get("value")
    vmin = obj.get("value_min")
    vmax = obj.get("value_max")
    normalized_value = obj.get("normalized_value")
    normalized_min = obj.get("normalized_value_min")
    normalized_max = obj.get("normalized_value_max")
    restored_value = obj.get("restored_value")
    values: list[float] = []
    for value in (normalized_min, normalized_max, normalized_value, restored_value, vmin, vmax):
        number = _float(value)
        if number is not None and number not in values:
            values.append(number)
    if not values:
        from tools.polyinfo_coverage_matcher import parse_values

        values = parse_values(raw)
    return raw, vmin, vmax, normalized_value, normalized_min, normalized_max, restored_value, values


def _candidate(
    doc_id: str,
    source: str,
    container: str,
    obj: dict[str, Any],
    lc_context: bool,
    extra_labels: Iterable[str] = (),
) -> dict[str, Any] | None:
    fields = _value_fields(obj)
    raw, vmin, vmax, normalized_value, normalized_min, normalized_max, restored_value, values = fields
    if not values:
        return None
    labels = _evidence_labels(obj, extra_labels)
    name_parts = [
        obj.get("semantic_label"),
        obj.get("source_field"),
        obj.get("property_name_normalized"),
        obj.get("property_name_raw"),
        obj.get("property_variant"),
        obj.get("variant"),
        *labels,
    ]
    name = " ".join(str(x) for x in name_parts if x).strip()
    unit = obj.get("unit_normalized") or obj.get("normalized_unit") or obj.get("unit_raw") or obj.get("unit")
    interval_kind, interval_min, interval_max, center_value = classify_interval(raw, vmin, vmax)
    if center_value is not None and center_value not in values:
        values.insert(0, center_value)
    pid = (
        obj.get("property_id")
        or obj.get("observation_id")
        or obj.get("specialized_id")
        or obj.get("unresolved_id")
        or obj.get("point_id")
        or obj.get("id")
        or "%s:%s" % (container, len(values))
    )
    measurement_context = obj.get("measurement_context") or obj.get("conditions")
    return {
        "doc_id": doc_id,
        "container": container,
        "source_stage": source,
        "pred_id": str(pid),
        "property_name_raw": name,
        "unit_raw": unit,
        "value_raw": raw,
        "sample_id": obj.get("sample_id") or obj.get("sample_label_raw"),
        "bucket": classify_pred(name, unit, lc_context),
        "values": values,
        "quantity_kind": classify_quantity_kind(name),
        "surface_component": classify_surface_component(name, obj.get("property_variant") or obj.get("variant")),
        "evidence_header_labels": labels,
        "interval_kind": interval_kind,
        "interval_min": interval_min,
        "interval_max": interval_max,
        "center_value": center_value,
        "measurement_context": measurement_context,
        "tga_threshold_percent": extract_tga_threshold(
            name=name,
            variant=obj.get("property_variant") or obj.get("variant"),
            measurement_context=measurement_context,
            evidence=obj.get("evidence") or obj.get("evidence_locator"),
        ),
        "publication_status": obj.get("publication_status")
        or (obj.get("publication_gate") or {}).get("status"),
        "sample_resolution_status": obj.get("sample_resolution_status"),
    }


def _iter_stage4n(payload: dict[str, Any]) -> Iterable[tuple[str, dict[str, Any], list[str]]]:
    for key in (
        "properties",
        "property_observations",
        "unresolved_properties",
        "unresolved_property_observations",
        "specialized_property_observations",
    ):
        for obj in payload.get(key) or []:
            if isinstance(obj, dict):
                yield key, obj, ()
    for series in payload.get("property_series") or []:
        if not isinstance(series, dict):
            continue
        series_labels = [series.get("property_name_raw"), series.get("property_name_normalized")]
        for point in series.get("points") or []:
            if isinstance(point, dict):
                merged = dict(point)
                for key in ("property_name_raw", "property_name_normalized", "unit_raw", "unit_normalized", "variant"):
                    if merged.get(key) is None:
                        merged[key] = series.get(key)
                yield "property_series", merged, series_labels


def _iter_stage4t(payload: dict[str, Any]) -> Iterable[tuple[str, dict[str, Any], list[str]]]:
    for table in payload.get("tables") or []:
        if not isinstance(table, dict):
            continue
        table_labels = [table.get("caption")]
        for key in (
            "observations",
            "shadow_observations",
            "llm_enriched_observations",
            "rule_observations",
            "unresolved",
        ):
            for obj in table.get(key) or []:
                if isinstance(obj, dict):
                    labels = table_labels + list(obj.get("header_context") or [])
                    yield key, obj, labels


def collect_candidates(doc_id: str, doc_dir: Path) -> list[dict[str, Any]]:
    """Load all value-bearing Preview layers for one document."""
    payloads: list[tuple[str, dict[str, Any]]] = []
    for source, filename in SOURCE_FILES:
        path = doc_dir / filename
        if not path.exists():
            continue
        try:
            payload = _json_load(path)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            payloads.append((source, payload))

    names: list[str] = []
    for _, payload in payloads:
        for key in ("properties", "property_observations", "specialized_property_observations"):
            names.extend(str(o.get("property_name_raw") or "") for o in payload.get(key) or [] if isinstance(o, dict))
        for series in payload.get("property_series") or []:
            if isinstance(series, dict):
                names.append(str(series.get("property_name_raw") or ""))
    lc_context = bool(LC_CONTEXT_RE.search(" ".join(names)))
    out: list[dict[str, Any]] = []
    for source, payload in payloads:
        iterator = _iter_stage4t(payload) if source == "stage4t" else _iter_stage4n(payload)
        for container, obj, labels in iterator:
            item = _candidate(doc_id, source, container, obj, lc_context, labels)
            if item:
                out.append(item)

    # Preserve a separate diagnostic layer for values present in raw Stage4N
    # LLM JSON but dropped before materialization.
    raw_path = doc_dir / "stage4_llm_response.json"
    if raw_path.exists():
        try:
            wrapper = _json_load(raw_path)
            raw_payload = _raw_json((wrapper.get("raw_response") or {}).get("content"))
        except (OSError, json.JSONDecodeError, AttributeError):
            raw_payload = None
        if raw_payload:
            for container, obj, labels in _iter_stage4n(raw_payload):
                item = _candidate(doc_id, "stage4n_raw_llm", container, obj, lc_context, labels)
                if item:
                    out.append(item)
    return out


def _bucket_compatible(gt: dict[str, Any], pred: dict[str, Any]) -> bool:
    bucket = gt.get("bucket")
    pred_bucket = pred.get("bucket")
    if bucket is None or pred_bucket is None:
        return False
    if bucket == pred_bucket:
        return True
    from tools.polyinfo_coverage_matcher import RECIPROCAL_PAIRS

    return (pred_bucket, bucket) in RECIPROCAL_PAIRS or (
        bucket == "thermal_mass_fraction" and pred_bucket == "td_wl"
    )


def evaluate(
    root: str | os.PathLike[str],
    batch: str | os.PathLike[str],
    include_paired: bool = False,
    gt_points_path: str | os.PathLike[str] | None = None,
    gt_exclusions_path: str | os.PathLike[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    root_path = Path(root)
    batch_path = Path(batch)
    if not batch_path.is_absolute():
        batch_path = root_path / batch_path
    doc_dirs = [d for d in sorted(batch_path.glob("reference_no_*")) if d.is_dir()]
    doc_ids = {d.name for d in doc_dirs if d.name not in EXCLUDED_DOCS}
    gt_by_doc = (
        load_gt_points(gt_points_path)
        if gt_points_path
        else load_gt(str(root_path), doc_ids)
    )
    gt_exclusions = (
        load_gt_exclusions(gt_exclusions_path)
        if gt_exclusions_path
        else {}
    )
    rows: list[dict[str, Any]] = []
    per_doc: dict[str, dict[str, Any]] = {}
    by_bucket: dict[str, Counter[str]] = defaultdict(Counter)
    source_counts: Counter[str] = Counter()
    conversion_counts: Counter[str] = Counter()

    for doc_dir in doc_dirs:
        doc_id = doc_dir.name
        if doc_id in EXCLUDED_DOCS:
            continue
        candidates = collect_candidates(doc_id, doc_dir)
        gt_rows = gt_by_doc.get(doc_id, [])
        doc_counts = Counter()
        excluded_by_reason: Counter[str] = Counter()
        for index, gt in enumerate(gt_rows):
            exclusion = gt_exclusions.get((doc_id, str(gt.get("row_id") or "")))
            if exclusion is not None:
                reason = str(exclusion["reason"])
                doc_counts["excluded"] += 1
                excluded_by_reason[reason] += 1
                continue
            # Raw PolyInfo GT uses paired_event_id; a reviewed/versioned
            # manifest may instead carry pair_row/migration metadata.
            paired = bool(
                gt.get("paired_event_id")
                or gt.get("pair_row")
                or "td_wl_to_observation" in str(gt.get("migration") or "")
            )
            if paired and not include_paired:
                doc_counts["paired_excluded"] += 1
                continue
            if not gt.get("coverage_eligible", True):
                doc_counts["ineligible"] += 1
                continue
            compatible = [p for p in candidates if _bucket_compatible(gt, p)]
            matching: list[tuple[dict[str, Any], dict[str, Any]]] = []
            for candidate in compatible:
                candidate_result = match_doc([gt], [candidate])[0]
                if candidate_result.get("match_tier") in CREDIBLE:
                    matching.append((candidate, candidate_result))
            best_rank = min(
                (TIER_ORDER.index(result.get("match_tier")) for _, result in matching),
                default=None,
            )
            best_matches = [
                (candidate, result)
                for candidate, result in matching
                if best_rank is not None and TIER_ORDER.index(result.get("match_tier")) == best_rank
            ]
            # Prefer a structured candidate for lineage when the same value is
            # present in both materialized output and raw LLM JSON. Raw-only is
            # reported only when no structured candidate independently matches.
            structured_matches = [
                pair for pair in best_matches if pair[0].get("source_stage") != "stage4n_raw_llm"
            ]
            chosen_candidate, result = min(
                structured_matches or best_matches,
                key=lambda pair: SOURCE_ORDER.get(pair[0].get("source_stage"), 99),
                default=(None, {}),
            )
            tier = TIER_ORDER[best_rank] if best_rank is not None else None
            matched_pred = result.get("pred_id")
            matched_sources = sorted(
                {candidate["source_stage"] for candidate, _ in matching},
                key=lambda s: SOURCE_ORDER.get(s, 99),
            )
            if tier in CREDIBLE:
                status = "captured_correct"
                source = chosen_candidate.get("source_stage") if chosen_candidate else None
                source_counts[source or "unknown"] += 1
                conversion = result.get("match_conversion")
                if isinstance(conversion, dict) and conversion.get("operation"):
                    conversion_counts[str(conversion["operation"])] += 1
                doc_counts["captured_correct"] += 1
                if tier == "exact":
                    doc_counts["exact"] += 1
            elif compatible:
                status = "captured_wrong_value"
                doc_counts["captured_wrong_value"] += 1
                source = None
            else:
                status = "not_captured"
                doc_counts["not_captured"] += 1
                source = None
            record = dict(gt)
            record.update({
                "gt_fact_id": "%s:gt_%04d" % (doc_id, index + 1),
                "capture_status": status,
                "capture_layer": source,
                "match_tier": tier,
                "matched_pred_id": matched_pred,
                "matched_sources": matched_sources,
                "matched_pred_value": result.get("pred_value"),
                "matched_pred_name_raw": result.get("pred_name_raw"),
                "matched_pred_unit_raw": result.get("pred_unit_raw"),
                "match_conversion": result.get("match_conversion"),
                "matched_pred_container": result.get("pred_container"),
                "matched_pred_sample_id": result.get("pred_sample_id"),
                "compatible_candidate_examples": [
                    {
                        "source_stage": p.get("source_stage"),
                        "pred_id": p.get("pred_id"),
                        "property_name_raw": p.get("property_name_raw"),
                        "values": p.get("values", [])[:4],
                        "unit_raw": p.get("unit_raw"),
                    }
                    for p in compatible[:5]
                ],
                "sample_binding_ignored": True,
                "publication_status_ignored": True,
                "candidate_count": len(candidates),
                "compatible_candidate_count": len(compatible),
            })
            rows.append(record)
            by_bucket[gt.get("bucket") or "UNMAPPED"][status] += 1
        per_doc[doc_id] = {
            "gt_total": len(gt_rows),
            # ``exact`` is a subset of ``captured_correct`` and must not be
            # added a second time to the denominator.
            "gt_included": doc_counts["captured_correct"]
            + doc_counts["captured_wrong_value"]
            + doc_counts["not_captured"],
            "paired_excluded": doc_counts["paired_excluded"],
            "ineligible": doc_counts["ineligible"],
            "excluded": dict(excluded_by_reason),
            "candidate_count": len(candidates),
            **{key: doc_counts[key] for key in ("captured_correct", "exact", "captured_wrong_value", "not_captured")},
        }

    totals = Counter(r["capture_status"] for r in rows)
    exact = sum(1 for r in rows if r.get("match_tier") == "exact")
    structured_correct = sum(
        1 for r in rows
        if r.get("capture_status") == "captured_correct"
        and r.get("capture_layer") != "stage4n_raw_llm"
    )
    raw_only_correct = sum(
        1 for r in rows
        if r.get("capture_status") == "captured_correct"
        and r.get("capture_layer") == "stage4n_raw_llm"
    )
    included = len(rows)
    summary = {
        "metric": "value_capture_recall",
        "definition": "同篇文献内，Preview 任一抽取层存在同性质且数值可信的候选即命中；不要求样品绑定或最终发布。",
        "credible_tiers": sorted(CREDIBLE),
        "paired_rows_excluded_by_default": not include_paired,
        "include_paired": include_paired,
        "gt_points_path": str(gt_points_path) if gt_points_path else None,
        "gt_exclusions_path": str(gt_exclusions_path) if gt_exclusions_path else None,
        "documents": len(per_doc),
        "gt_included": included,
        "captured_correct": totals["captured_correct"],
        "structured_correct": structured_correct,
        "raw_only_correct": raw_only_correct,
        "exact": exact,
        "captured_wrong_value": totals["captured_wrong_value"],
        "not_captured": totals["not_captured"],
        "excluded_by_reason": dict(
            Counter(
                reason
                for counts in per_doc.values()
                for reason, count in counts.get("excluded", {}).items()
                for _ in range(count)
            )
        ),
        "value_capture_recall": (totals["captured_correct"] / included if included else 0.0),
        "exact_recall": (exact / included if included else 0.0),
        "source_counts": dict(source_counts),
        "match_conversion_counts": dict(conversion_counts),
        "by_bucket": {bucket: dict(counts) for bucket, counts in sorted(by_bucket.items())},
        "per_doc": per_doc,
    }
    for counts in summary["per_doc"].values():
        doc_included = int(counts.get("gt_included") or 0)
        present = int(counts.get("captured_correct") or 0) + int(
            counts.get("captured_wrong_value") or 0
        )
        counts["candidate_present"] = present
        counts["candidate_presence_recall"] = (
            present / doc_included if doc_included else 0.0
        )
    summary["candidate_present"] = totals["captured_correct"] + totals["captured_wrong_value"]
    summary["candidate_presence_recall"] = (
        summary["candidate_present"] / included if included else 0.0
    )
    return rows, summary


def write_outputs(rows: list[dict[str, Any]], summary: dict[str, Any], out_dir: str | os.PathLike[str]) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "value_capture.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    (out / "value_capture_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    candidate_present = int(
        summary.get("candidate_present")
        if summary.get("candidate_present") is not None
        else int(summary.get("captured_correct") or 0)
        + int(summary.get("captured_wrong_value") or 0)
    )
    included = int(summary.get("gt_included") or 0)
    candidate_presence_recall = float(
        summary.get("candidate_presence_recall")
        if summary.get("candidate_presence_recall") is not None
        else (candidate_present / included if included else 0.0)
    )
    lines = [
        "# Preview 值捕获率评估",
        "",
        f"- 文献数：{summary['documents']}",
        f"- 纳入 GT 值：{summary['gt_included']}",
        f"- 正确捕获：{summary['captured_correct']}（{summary['value_capture_recall']:.1%}）",
        f"  - 已进入结构化候选：{summary['structured_correct']}；仅 raw LLM：{summary['raw_only_correct']}",
        f"- 同性质候选存在：{candidate_present}（{candidate_presence_recall:.1%}；仅表示候选存在，不代表数值正确）",
        f"- 其中 exact：{summary['exact']}（{summary['exact_recall']:.1%}）",
        f"- 明确单位转换命中：{summary.get('match_conversion_counts', {})}",
        f"- 已抽取但值不符：{summary['captured_wrong_value']}",
        f"- 未捕获：{summary['not_captured']}",
        f"- 分母外排除：{sum(summary.get('excluded_by_reason', {}).values())}"
        f"（{summary.get('excluded_by_reason', {})}）",
        "",
        "主指标不要求样品绑定、publication_status 或 final.json 发布；配对 GT 默认排除。",
        "逐条结果见 `value_capture.jsonl`，程序化汇总见 `value_capture_summary.json`。",
        "",
        "## 逐篇统计",
        "",
        "| 文献 | 纳入 GT 值 | 正确捕获 | 值捕获召回率 | 候选存在率 | exact | 值不符 | 未捕获 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for doc_id, counts in sorted(summary.get("per_doc", {}).items()):
        denominator = int(counts.get("gt_included") or 0)
        recall = (
            f"{int(counts.get('captured_correct') or 0) / denominator:.1%}"
            if denominator else "—"
        )
        candidate_present = int(
            counts.get("candidate_present")
            if counts.get("candidate_present") is not None
            else int(counts.get("captured_correct") or 0)
            + int(counts.get("captured_wrong_value") or 0)
        )
        presence = (
            f"{candidate_present / denominator:.1%}"
            if denominator else "—"
        )
        lines.append(
            "| {doc} | {included} | {correct} | {recall} | {presence} | {exact} | {wrong} | {missing} |".format(
                doc=doc_id,
                included=denominator,
                correct=int(counts.get("captured_correct") or 0),
                recall=recall,
                presence=presence,
                exact=int(counts.get("exact") or 0),
                wrong=int(counts.get("captured_wrong_value") or 0),
                missing=int(counts.get("not_captured") or 0),
            )
        )
    (out / "value_capture_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--batch", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--include-paired", action="store_true")
    parser.add_argument(
        "--gt-points",
        default=None,
        help="可选：版本化 GT JSONL；可携带 pair_row/migration 等排除标记",
    )
    parser.add_argument(
        "--gt-exclusions",
        default=None,
        help="可选：版本化 GT 排除清单 JSON；按 doc_id+row_id 排除图读数等记录",
    )
    args = parser.parse_args()
    rows, summary = evaluate(
        args.root,
        args.batch,
        include_paired=args.include_paired,
        gt_points_path=args.gt_points,
        gt_exclusions_path=args.gt_exclusions,
    )
    write_outputs(rows, summary, args.out)
    print(json.dumps({k: summary[k] for k in (
        "documents", "gt_included", "captured_correct", "exact", "captured_wrong_value",
        "not_captured", "value_capture_recall", "exact_recall",
    )}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
