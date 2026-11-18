"""Compare frozen-input runs, keeping source-check rates separate from accuracy."""
from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from schema.polymer_schema import PropertyStageResponse
from tools.audit_measurement_reference_alignment import compare_reference
from tools.reference_sample_crosswalk import load_crosswalk
from tools.score_source_binding_labels import load_labels, score


def compare(arm_a, arm_b, output_root, *, reference_rows, sample_crosswalk, binding_labels=None):
    output_root = Path(output_root).resolve()
    if output_root.exists():
        raise ValueError("Output already exists")
    snapshots = {}

    def read(path):
        path = Path(path).resolve()
        snapshots[path] = path.read_bytes()
        return json.loads(snapshots[path])

    roots = [Path(arm_a).resolve(), Path(arm_b).resolve()]
    if any(output_root == root or root in output_root.parents or output_root in root.parents for root in roots):
        raise ValueError("Comparison must be separate from run outputs")
    runs = [read(root / "summary.json") for root in roots]
    if any(run.get("status") != "completed" or not run.get("original_inputs_unchanged") or not run.get("rules_unchanged") for run in runs):
        raise ValueError("Runs must be complete with unchanged inputs and rules")
    requests = [{c["document_id"]: c["request_sha256"] for c in run["cases"]} for run in runs]
    if requests[0] != requests[1] or runs[0]["rule_hashes"] != runs[1]["rule_hashes"] or runs[0]["transport"] != runs[1]["transport"]:
        raise ValueError("A/B evidence, rules or transport settings differ")
    paired = set.intersection(*({c["document_id"] for c in run["cases"] if c["status"] == "completed"} for run in runs))
    crosswalk, sources = load_crosswalk(sample_crosswalk)
    snapshots.update(sources)
    labels = []
    if binding_labels:
        labels, label_sources = load_labels(binding_labels)
        snapshots.update(label_sources)
    reference_rows = Path(reference_rows).resolve()
    snapshots[reference_rows] = reference_rows.read_bytes()
    references = [json.loads(line) for line in snapshots[reference_rows].decode("utf-8-sig").splitlines() if line.strip()]
    references = [r for r in references if r["reference_no"] in requests[0]]
    metrics, alignments = [], {}
    for root, run in zip(roots, runs):
        counts, binding, reasons, publications = Counter(), Counter(), Counter(), {}
        strict_json = schema_valid = complete_responses = conflict_claims = 0
        costs, currencies = [], set()
        attempts = []
        paired_counts = Counter()
        for case in run["cases"]:
            directory = root / case["document_id"]
            result_path = directory / "case_result.json"
            if read(result_path) != case:
                raise ValueError("Case result does not match run summary")
            raw_path = directory / "raw_response.json"
            if raw_path.is_file():
                raw = read(raw_path)
                complete_responses += raw.get("finish_reason") in {"stop", "end_turn"}
                try:
                    data = json.loads(raw["content"])
                    strict_json += isinstance(data, dict)
                    PropertyStageResponse.model_validate(data)
                except (ValueError, TypeError, KeyError):
                    pass
                else:
                    schema_valid += 1
            path = directory / "measurement_publication.json"
            if case["status"] == "completed":
                publication = read(path)
                if publication["counts"] != case["evaluation"]["counts"]:
                    raise ValueError("Evaluation artifact changed")
                publications[case["document_id"]] = publication
                counts.update(publication["counts"])
                if case["document_id"] in paired:
                    paired_counts.update(publication["counts"])
                binding.update(case["evaluation"]["binding_counts"])
                reasons.update(case["evaluation"]["reason_counts"])
                conflict_claims += sum(any(reason in {"binding_conflict", "sample_axis_conflict", "sample_entity_conflict"}
                                           for reason in g["publication_reasons"])
                                       for status in ("final", "candidate", "not_publishable") for g in publication[status])
            history = case.get("attempt_history") or [case]
            attempts.extend(history)
            for attempt in history:
                if attempt.get("cost"):
                    costs.append(Decimal(attempt["cost"]["total_cost"]))
                    currencies.add(attempt["cost"]["currency"])
        if len(currencies) > 1:
            raise ValueError("Cannot sum costs in different currencies")
        aligned = [compare_reference(row, publications.get(row["reference_no"]), crosswalk) for row in references]
        alignments[run["arm"]] = aligned
        submitted = sum(c["api_requests"] for c in run["cases"])
        metrics.append({"arm": run["arm"], "requested_model": run["requested_model"],
                        "actual_models": sorted({c["actual_model"] for c in run["cases"] if c.get("actual_model")}),
                        "cases": len(run["cases"]), "submitted_requests": submitted,
                        "completed_cases": sum(c["status"] == "completed" for c in run["cases"]),
                        "initial_failed_cases": sum(c.get("initial_status", c["status"]) == "failed" for c in run["cases"]),
                        "transport_recovery_cases": sum(bool(c.get("recovery_used")) for c in run["cases"]),
                        "complete_responses": complete_responses, "strict_json_responses": strict_json, "raw_schema_valid_responses": schema_valid,
                        "timeout_rate": sum(bool(c.get("timeout")) for c in attempts) / submitted if submitted else None,
                        "failed_request_rate": sum(c.get("status") == "failed" for c in attempts) / submitted if submitted else None,
                        "transport_interruption_requests": sum(c.get("error_type") == "ChunkedEncodingError" for c in attempts),
                        "elapsed_seconds": round(sum(c["elapsed_seconds"] for c in run["cases"]), 3),
                        "known_cost": str(sum(costs)), "cost_currency": next(iter(currencies), None),
                        "cost_status": "known" if len(costs) == submitted and submitted else "unknown_or_partial",
                        "costed_requests": len(costs), "counts": dict(counts), "binding_counts": dict(binding), "reason_counts": dict(reasons),
                        "paired_completed_counts": dict(paired_counts),
                        "deterministic_publication_pass_rate": counts["final"] / counts["measurement_group_count"] if counts["measurement_group_count"] else None,
                        "detected_binding_conflict_claims": conflict_claims,
                        "independent_identity_reference_rows": sum(r["reference_sample_status"] == "reviewed_identity" for r in aligned),
                        "published_identity_value_match_rows": sum(any(m["publication_status"] == "final" for m in r["identity_verified_value_matches"]) for r in aligned),
                        "independent_sample_binding_accuracy": None, "conflicting_binding_false_acceptance_rate": None,
                        "accuracy_status": "insufficient_independent_labels_no_full_accuracy_claim"})
        if labels:
            metrics[-1]["source_binding_label_score"] = score(labels, publications)
    result = {"schema_version": "stage4_ab_comparison.v1", "same_requests_rules_and_transport": True, "metrics": metrics,
              "paired_completed_document_ids": sorted(paired),
              "reference_rows_in_scope": len(references), "production_model_replaced": False,
              "decision": "diagnostic_comparison_only_insufficient_independent_labels_for_replacement",
              "original_inputs_unchanged": all(p.read_bytes() == content for p, content in snapshots.items()),
              "input_hashes": {str(p): hashlib.sha256(content).hexdigest() for p, content in snapshots.items()}}
    if not result["original_inputs_unchanged"]:
        raise ValueError("Comparison inputs changed")
    output_root.mkdir(parents=True)
    (output_root / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    for arm, rows in alignments.items():
        (output_root / f"{arm}_reference_alignment.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    a, b = metrics
    lines = ["# Stage4 冻结输入 A/B 对比", "", "两个模型使用相同的三篇诊断输入、提示词、输出上限和校验规则。结果仅覆盖 Stage4，不等于全流程准确率。", "",
             f"A：{a['requested_model']}；B：{b['requested_model']}。", "", "|指标|A|B|", "|---|---:|---:|"]
    for label, key in (("请求数", "submitted_requests"), ("完成案例", "completed_cases"), ("完整响应", "complete_responses"),
                       ("首次运行失败案例", "initial_failed_cases"), ("补跑恢复成功案例", "transport_recovery_cases"),
                       ("严格 JSON 响应", "strict_json_responses"), ("原始输出直接符合 Schema", "raw_schema_valid_responses"),
                       ("超时比例", "timeout_rate"), ("请求失败比例", "failed_request_rate"),
                       ("连接提前中断请求", "transport_interruption_requests"), ("调用耗时合计/秒", "elapsed_seconds"),
                       ("检测到的身份冲突声明", "detected_binding_conflict_claims"),
                       ("独立身份及值匹配的正式标准行", "published_identity_value_match_rows")):
        lines.append(f"|{label}|{a[key]}|{b[key]}|")
    for key, label in (("final", "正式资格表达"), ("candidate", "待核表达"), ("not_publishable", "阻断表达")):
        lines.append(f"|{label}|{a['counts'].get(key, 0)}|{b['counts'].get(key, 0)}|")
    lines += ["", f"双方都有完成结果的文献：{', '.join(sorted(paired)) or '无'}。上表全量表达数受成功文献数影响，不能直接作为内容质量排名。", "",
              "|共同完成文献的表达|A|B|", "|---|---:|---:|"]
    for key, label in (("final", "正式资格"), ("candidate", "待核"), ("not_publishable", "阻断")):
        lines.append(f"|{label}|{a['paired_completed_counts'].get(key, 0)}|{b['paired_completed_counts'].get(key, 0)}|")
    for metric in metrics:
        known_cost = f"{metric['known_cost']} {metric['cost_currency']}" if metric['costed_requests'] else "无已记录费用"
        lines += ["", f"{metric['arm']} 成本：{known_cost}；覆盖 {metric['costed_requests']}/{metric['submitted_requests']} 次请求，状态 {metric['cost_status']}。未知费用不能视为零。"]
        if labels:
            subset = metric["source_binding_label_score"]
            lines += [f"{metric['arm']} 原文材料绑定标注子集：覆盖 {subset['covered_cells']}/{subset['labelled_cells']} 格，其中全部声明绑定正确 {subset['correct_binding_cells']} 格；错误绑定声明 {subset['incorrect_binding_claims']} 条，进入正式集合 {subset['incorrect_binding_claims_published']} 条。此开发诊断集不代表全量准确率。"]
    lines += ["", "独立样品准确率、冲突误接受率尚无足够独立标签，均不报数值。检测出的冲突数不等于误接受率；正式资格表达数及通过比例不等于准确率或召回率。",
              "", "本次不替换生产模型。应扩充独立样品标签与冲突负例，再检验准确率提高且误接受率不升高。所有原始响应和逐条校验结果均保留。"]
    (output_root / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("arm-a", "arm-b", "output-root", "reference-rows", "sample-crosswalk"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--binding-labels", type=Path)
    result = compare(**vars(parser.parse_args()))
    print(json.dumps({"same_requests_rules_and_transport": result["same_requests_rules_and_transport"], "decision": result["decision"]}))


if __name__ == "__main__":
    main()
