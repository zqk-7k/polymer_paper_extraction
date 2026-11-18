"""Apply one current validator to both saved arms; never call a model here."""
from copy import deepcopy
import argparse
import hashlib
from pathlib import Path
import shutil

from tools.run_stage4_ab import load_dataset, read, write, evaluate


def reevaluate(dataset, arm_a, arm_b, output_root, recovery_a=None, recovery_b=None):
    cases, input_hashes = load_dataset(dataset)
    packets = {p["document_id"]: (p, inputs) for p, inputs in cases}
    output_root = Path(output_root).resolve()
    if output_root.exists():
        raise ValueError("Output already exists")
    roots = [Path(arm_a).resolve(), Path(arm_b).resolve()]
    if any(root == output_root or root in output_root.parents or output_root in root.parents for root in roots):
        raise ValueError("Output must be separate")
    originals = [read(root / "summary.json") for root in roots]
    if any(r.get("status") != "completed" or not r.get("rules_unchanged") or not r.get("original_inputs_unchanged") for r in originals):
        raise ValueError("Original arms are not complete and verified")
    if originals[0]["rule_hashes"] != originals[1]["rule_hashes"]:
        raise ValueError("Original arms used different rules")
    recoveries = {}
    for original, recovery_path in zip(originals, (recovery_a, recovery_b)):
        if recovery_path:
            recovery_root = Path(recovery_path).resolve()
            recovery = read(recovery_root / "summary.json")
            if (recovery.get("status") != "completed" or not recovery.get("rules_unchanged")
                    or not recovery.get("original_inputs_unchanged") or recovery["requested_model"] != original["requested_model"]
                    or recovery["rule_hashes"] != original["rule_hashes"] or recovery["transport"] != original["transport"]):
                raise ValueError("Recovery is not verified for the same model")
            failed_ids = {c["document_id"] for c in original["cases"] if c["status"] == "failed"}
            recovery_ids = [c["document_id"] for c in recovery["cases"]]
            if len(set(recovery_ids)) != len(recovery_ids) or set(recovery_ids) - failed_ids:
                raise ValueError("Recovery must contain only original failed cases")
            recoveries[original["arm"]] = (recovery_root, recovery)
    code_root = Path(__file__).resolve().parents[1]
    rules = list((code_root / "stages").glob("*.py")) + list((code_root / "config").glob("*.v1.json")) + [Path(__file__).resolve(), code_root / "tools/run_stage4_ab.py"]
    rule_hashes = {str(p.relative_to(code_root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in rules}
    source_hashes = {}
    output_root.mkdir(parents=True)
    for root, original in zip(roots, originals):
        recovery_root, recovery = recoveries.get(original["arm"], (None, None))
        if {c["document_id"] for c in original["cases"]} != set(packets):
            raise ValueError("Original run differs from frozen case set")
        summary = deepcopy(original)
        summary.update(mode="offline_reevaluation", new_api_requests=0, original_run=str(root),
                       original_rule_hashes=original["rule_hashes"], rule_hashes=rule_hashes, cases=[])
        target_root = output_root / original["arm"]
        target_root.mkdir()
        for initial in original["cases"]:
            packet, inputs = packets[initial["document_id"]]
            chosen, source = initial, root / initial["document_id"]
            attempts = [initial]
            if initial["request_sha256"] != packet["request_sha256"]:
                raise ValueError("Original request differs from frozen input")
            if recovery and initial["status"] == "failed":
                matches = [c for c in recovery["cases"] if c["document_id"] == initial["document_id"]]
                if matches:
                    # Recover transport failures only, never resample a low-scoring response.
                    if ((source / "stage4_properties.json").exists() or (source / "raw_response.json").exists()
                            or initial.get("error_type") not in {"ChunkedEncodingError", "ConnectionError", "Timeout", "ReadTimeout", "LLMRequestError"}
                            or len(matches) != 1 or matches[0]["api_requests"] != 1
                            or matches[0]["request_sha256"] != initial["request_sha256"]):
                        raise ValueError("Recovery must be a single identical-input transport retry")
                    attempts.append(matches[0])
                    if matches[0]["status"] == "completed":
                        chosen, source = matches[0], recovery_root / initial["document_id"]
            row = deepcopy(chosen)
            row.update(initial_status=initial["status"], initial_error_type=initial.get("error_type"), recovery_used=chosen is not initial)
            row["attempt_history"] = [{k: item.get(k) for k in ("status", "error_type", "api_requests", "elapsed_seconds", "cost", "timeout")}
                                      for item in attempts]
            row["api_requests"] = sum(a["api_requests"] for a in row["attempt_history"])
            row["elapsed_seconds"] = sum(a["elapsed_seconds"] for a in row["attempt_history"])
            row["timeout"] = any(a.get("timeout") for a in row["attempt_history"])
            directory = target_root / row["document_id"]
            directory.mkdir()
            for name in ("stage4_properties.json", "stage4_request_trace.json", "stage4_llm_response.json", "raw_response.json"):
                path = source / name
                if path.is_file():
                    source_hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
                    shutil.copy2(path, directory / name)
            if (directory / "stage4_properties.json").is_file():
                row.update(evaluation=evaluate(directory, inputs), status="completed")
            elif row["status"] == "completed":
                raise ValueError("Completed case is missing its Stage4 output")
            write(directory / "case_result.json", row)
            summary["cases"].append(row)
        summary.update(api_requests=sum(c["api_requests"] for c in summary["cases"]),
                       rules_unchanged=rule_hashes == {str(p.relative_to(code_root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in rules},
                       original_inputs_unchanged=all(hashlib.sha256(p.read_bytes()).hexdigest() == h for p, h in input_hashes.items()))
        write(target_root / "summary.json", summary)
    unchanged = all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p, h in source_hashes.items())
    write(output_root / "manifest.json", {"schema_version": "stage4_ab_reevaluation.v1", "new_api_requests": 0,
                                         "source_hashes": source_hashes, "original_results_unchanged": unchanged})
    if not unchanged:
        raise ValueError("Saved responses changed during evaluation")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "arm-a", "arm-b", "output-root"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--recovery-a", type=Path)
    parser.add_argument("--recovery-b", type=Path)
    reevaluate(**vars(parser.parse_args()))


if __name__ == "__main__":
    main()
