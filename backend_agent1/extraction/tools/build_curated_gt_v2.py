"""Build a versioned Curated GT from the immutable Legacy review TSV.

The script only writes a new JSONL file.  It never edits the Legacy TSV.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

A2_DOCS = {
    "reference_no_0020284": (600.0, "residual_mass_fraction"),
    "reference_no_0021296": (800.0, "residual_mass_fraction"),
    "reference_no_0037645": (800.0, "mass_loss_fraction"),
}


def _is_a2_td(row: dict[str, str]) -> bool:
    if row.get("doc_id") not in A2_DOCS or row.get("bucket") != "td":
        return False
    try:
        return float(row["value_min"]) == A2_DOCS[row["doc_id"]][0]
    except (KeyError, TypeError, ValueError):
        return False


def build_curated_rows(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    """Return 526 rows: Legacy keep rows minus A2 td, with A2 td_wl migrated."""
    a2_temperature_by_sample: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in rows:
        if _is_a2_td(row):
            key = (row["doc_id"], row["sample_id"], row["measurement_condition"])
            a2_temperature_by_sample[key] = row

    curated: list[dict[str, object]] = []
    for row in rows:
        if row.get("suggest") != "keep" or _is_a2_td(row):
            continue
        out: dict[str, object] = dict(row)
        if out.get("bucket") == "viscosity":
            out["bucket"] = "viscosity_intrinsic"
        if row.get("doc_id") in A2_DOCS and row.get("bucket") == "td_wl":
            key = (row["doc_id"], row["sample_id"], row["measurement_condition"])
            td = a2_temperature_by_sample.get(key)
            if td is None:
                raise ValueError(f"A2 td_wl 无法配对 td: {row['row_id']}")
            quantity_kind = A2_DOCS[row["doc_id"]][1]
            original_value = float(row["value_min"])
            if quantity_kind == "residual_mass_fraction":
                # Legacy stores wt-loss converted from the reported residue for
                # both 0020284 and 0021296.  Curated restores the source basis.
                original_value = round(100.0 - original_value, 10)
            out.update({
                "bucket": "thermal_mass_fraction",
                "property_name": "Thermal mass fraction at temperature",
                "quantity_kind": quantity_kind,
                "value_min": original_value,
                "value_max": original_value,
                "source_value_min": float(row["value_min"]),
                "source_value_basis": "legacy_wt_loss" if quantity_kind == "residual_mass_fraction" else quantity_kind,
                "condition_temperature": float(td["value_min"]),
                "pair_row": int(td["row_id"]),
                "migration": "A2_td_wl_to_observation",
            })
        curated.append(out)

    if len(curated) != 526:
        raise ValueError(f"Curated 行数应为 526，实际 {len(curated)}")
    if sum(item.get("migration") == "A2_td_wl_to_observation" for item in curated) != 21:
        raise ValueError("A2 迁移行数应为 21")
    return curated


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy-tsv", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    with args.legacy_tsv.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    curated = build_curated_rows(rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for row in curated:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"写出 {args.out}：{len(curated)} 行，A2 迁移 {sum('migration' in x for x in curated)} 行")


if __name__ == "__main__":
    main()
