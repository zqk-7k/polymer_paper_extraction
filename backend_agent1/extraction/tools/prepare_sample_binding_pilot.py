"""Create an isolated, schema-checked pilot with explicit entity references."""
from __future__ import annotations

import argparse
import copy
from pathlib import Path

from schema.polymer_schema import Stage4Document, Stage5Document
from stages.subject_lineage import inherit_entity_ids, audit_lineage
from stages.sample_catalog import build_catalog, digest
from tools.review_sample_binding_llm import INPUT_FILES, read_json, write_json


def prepare(source: Path, target: Path) -> dict:
    source, target = source.resolve(), target.resolve()
    if source == target or source in target.parents or target in source.parents:
        raise ValueError("Pilot must be separate from original inputs")
    if target.exists():
        raise ValueError("Pilot target already exists; use a new output directory")
    files = {name: read_json(source / name) for name in INPUT_FILES if (source / name).is_file()}
    stage2, stage3 = files["stage2_entities.json"], files["stage3_process.json"]
    before = audit_lineage(files)
    original = copy.deepcopy(files)
    enrichments = []
    for name, value in list(files.items()):
        if name.startswith(("stage4_properties", "stage5_characterizations")):
            enriched = inherit_entity_ids(value, stage2, stage3)
            schema = Stage5Document if name.startswith("stage5") else Stage4Document
            schema.model_validate(enriched)
            if enriched != value:
                enrichments.append(name)
            files[name] = enriched
        # Candidate/Final keep their own historical version and IDs; they are
        # audited separately, not treated as newly merged upstream results.
        write_json(target / name, files[name])
    catalog = build_catalog(files["stage0_blocks.json"], stage3)
    write_json(target / "stage3_sample_catalog.json", catalog)
    write_json(target / "subject_lineage_audit.json", audit_lineage(files))
    manifest = {"source_dir": str(source), "output_dir": str(target), "mode": "exact_reference_enrichment",
                "updated_files": enrichments, "before_status_counts": before["observation_status_counts"],
                "original_hashes": {key: digest(value) for key, value in original.items()},
                "output_hashes": {key: digest(value) for key, value in files.items()},
                "stage3_reextracted": False, "candidate_final_remerged": False}
    write_json(target / "lineage_enrichment_manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--ref-no", action="append", required=True)
    args = parser.parse_args()
    manifests = []
    for ref in args.ref_no:
        name = ref if ref.startswith("reference_no_") else "reference_no_" + ref
        manifests.append(prepare(args.batch_dir / name, args.output_dir / name))
    write_json(args.output_dir / "lineage_enrichment_summary.json", manifests)
    print(f"Prepared {len(manifests)} documents with unchanged sample/process IDs")


if __name__ == "__main__":
    main()
