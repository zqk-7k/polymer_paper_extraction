import json
from pathlib import Path


def test_curated_manifest_keeps_current_and_frozen_metrics_explained() -> None:
    manifest_path = (
        Path(__file__).parents[2]
        / "batch_results"
        / "_gt_review_20260819"
        / "polyinfo_matcher_baseline_v2_20260821"
        / "curated_manifest_v2.2.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    migration = manifest["migration"]
    assert migration["curated_rows"] == 526
    assert migration["a2_output_observations"] == 21

    current = manifest["metrics"]["curated_current_preview"]
    assert (current["credible"], current["strict"]) == (307, 267)

    frozen = manifest["metrics"]["document_frozen_reference"]
    assert (frozen["credible"], frozen["strict"]) == (303, 263)

    explanation = " ".join(manifest["metric_difference_explanation"])
    assert "four 0021296" in explanation
    assert "residual_mass_fraction" in explanation
    assert "exact-match" in explanation


def test_p0_baseline_manifest_matches_current_preview_snapshots() -> None:
    root = Path(__file__).parents[2]
    manifest_path = (
        root
        / "batch_results"
        / "_gt_review_20260819"
        / "polyinfo_matcher_baseline_v2.2_20260821"
        / "baseline_manifest_v2.2.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["scope"] == {
        "batch": "testcode/batch_results/demo20_preview_final_20260812",
        "legacy_gt_points": 695,
        "curated_gt_points": 526,
        "legacy_gt_unchanged": True,
        "historical_gt_tsv_overwritten": False,
    }
    assert manifest["results"]["legacy_695"]["credible"] == 313
    assert manifest["results"]["legacy_695"]["strict"] == 265
    assert manifest["results"]["curated_526"]["credible"] == 307
    assert manifest["results"]["curated_526"]["strict"] == 267
    assert manifest["viscosity_regression"] == {
        "bucket": "viscosity_intrinsic",
        "doc_id": "reference_no_0021296",
        "gt": 4,
        "credible": 4,
        "strict": 4,
        "all_match_tier": "exact",
        "inherent_intrinsic_cross_match": False,
    }
    assert manifest["curated_thermal_mass_regression"]["gt"] == 21
