import csv
from pathlib import Path

from tools.build_curated_gt_v2 import build_curated_rows


def test_a2_migration_reduces_547_keep_rows_to_526_and_preserves_basis() -> None:
    path = Path(__file__).parents[2] / "batch_results" / "_gt_review_20260819" / "gt_review_20260819.tsv"
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    curated = build_curated_rows(rows)
    migrated = [row for row in curated if row.get("migration") == "A2_td_wl_to_observation"]
    assert len(curated) == 526
    assert len(migrated) == 21
    assert {row["quantity_kind"] for row in migrated} == {"residual_mass_fraction", "mass_loss_fraction"}
    assert all(row["bucket"] == "thermal_mass_fraction" for row in migrated)
    assert all(row["pair_row"] for row in migrated)
    assert all(row["bucket"] != "viscosity" for row in curated)
    by_doc = {}
    for row in migrated:
        by_doc.setdefault(row["doc_id"], []).append(row)
    assert sorted(row["value_min"] for row in by_doc["reference_no_0021296"]) == [33.2, 34.0, 34.1, 39.7]
    assert sorted(row["value_min"] for row in by_doc["reference_no_0037645"]) == [72.0, 75.0, 76.0, 85.0, 85.0, 90.0]
