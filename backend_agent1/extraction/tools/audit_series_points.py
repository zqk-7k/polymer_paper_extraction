"""Read-only source audit for saved Stage4 series points. No model calls."""
import argparse
import hashlib
import json
from pathlib import Path

from stages.series_point_audit import audit_series_points


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--stage4", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--origin-trace", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Report already exists")
    paths = [args.input_dir / name for name in ("stage0_blocks.json", "stage2_entities.json", "stage3_process.json")] + [args.stage4]
    contents = [p.read_bytes() for p in paths]
    extra = {}
    for key, path in (("trace", args.trace), ("origin_trace", args.origin_trace)):
        if path:
            content = path.read_bytes()
            paths.append(path)
            contents.append(content)
            extra[key] = json.loads(content.decode("utf-8-sig"))
    result = audit_series_points(*(json.loads(c.decode("utf-8-sig")) for c in contents[:4]), **extra)
    result["input_hashes"] = {str(p.resolve()): hashlib.sha256(c).hexdigest() for p, c in zip(paths, contents)}
    if any(p.read_bytes() != c for p, c in zip(paths, contents)):
        raise ValueError("Input changed during audit")
    result.update(api_requests=0, original_inputs_unchanged=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("record_count", "binding_counts", "source_audit_counts", "source_reason_counts", "publication_counts", "input_proof")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
