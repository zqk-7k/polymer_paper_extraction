"""为原文复核标准集生成独立的性质编码对齐表；不改 Excel 或抽取产物。"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import unicodedata


EXTRACTION_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = EXTRACTION_ROOT.parents[1]
DEFAULT_STANDARD = PROJECT_ROOT / "标准集" / "31篇标准集_原文复核.xlsx"
DEFAULT_REGISTRY = EXTRACTION_ROOT / "config" / "standard_property_codes.v1.json"
DEFAULT_SCHEMA = EXTRACTION_ROOT / "config" / "polymer_schema.yaml"
DEFAULT_OUTPUT = PROJECT_ROOT / "testcode/reports/standard_property_codes_20260913"
REQUIRED_COLUMNS = (
    "全局序号", "论文编号", "样品ID", "性质名称", "数值最小", "数值最大",
    "来源JSON", "锚点ID", "证据摘录", "原文复核后规范性质名",
    "原文复核后规范单位", "原文复核状态", "原文复核依据", "原文复核建议",
    "主评估纳入_v2", "性质变体_v2",
)
UNIT_FAMILIES = {
    "temperature": {"c", "°c", "k", "degc"},
    "stress": {"pa", "kpa", "mpa", "gpa"},
    "fraction": {"%", "wt%", "1", "dimensionless"},
    "dimensionless": {"1", "dimensionless"},
    "impact": {"j/m", "kj/m", "j/m2", "kj/m2", "j/m²", "kj/m²"},
    "specific_energy": {"j/g", "kj/g", "cal/g", "kcal/g"},
    "molecular_weight": {"g/mol", "kg/mol", "da", "kda"},
    "viscosity": {"dl/g", "ml/g", "cm3/g", "cm³/g", "1", "dimensionless"},
    "angle": {"degree", "degrees", "°", "deg"},
    "length": {"nm", "angstrom", "å", "m", "µm"},
    "surface": {"mn/m", "n/m", "dyn/cm", "mj/m2", "mj/m²"},
    "conductivity": {"1/(ohm*cm)", "s/cm", "s/m"},
}


def normalize_name(value) -> str:
    """仅规范空格、下划线、大小写；不做子串、数值或相似度匹配。"""
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).casefold().replace("_", " ").split())


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_registry(path: Path = DEFAULT_REGISTRY) -> tuple[dict, dict]:
    registry = json.loads(path.read_text(encoding="utf-8"))
    if registry.get("schema_version") != "standard_property_code_registry.v1" or registry.get("namespace") != "STD:":
        raise ValueError("Unsupported property code registry")
    aliases, keys = {}, set()
    for entry in registry["entries"]:
        key = entry["key"]
        if not re.fullmatch(r"[a-z][a-z0-9_]*", key) or key in keys:
            raise ValueError(f"Invalid or duplicate code key: {key}")
        keys.add(key)
        if entry["unit_family"] not in UNIT_FAMILIES:
            raise ValueError(f"Unknown unit family: {entry['unit_family']}")
        for surface in [key, *entry["aliases"]]:
            name = normalize_name(surface)
            if name in aliases and aliases[name]["key"] != key:
                raise ValueError(f"Ambiguous alias: {surface}")
            aliases[name] = entry
    return registry, aliases


def read_standard(path: Path) -> tuple[list[dict], dict]:
    import openpyxl

    records, anchors, ids = [], set(), set()
    with path.open("rb") as stream:
        wb = openpyxl.load_workbook(stream, read_only=True, data_only=False)
        try:
            if "Sheet1" not in wb.sheetnames:
                raise ValueError("Standard workbook is missing Sheet1")
            iterator = wb["Sheet1"].iter_rows()
            headers = [cell.value for cell in next(iterator, [])]
            missing = set(REQUIRED_COLUMNS) - set(headers)
            if missing or len(headers) != len(set(headers)):
                raise ValueError(f"Missing or duplicate column names: {sorted(missing)}")
            for row_number, cells in enumerate(iterator, 2):
                if not any(cell.value is not None for cell in cells):
                    continue
                if any(cell.data_type == "f" for cell in cells):
                    raise ValueError(f"Formula in standard row {row_number}; literal reviewed values required")
                record = dict(zip(headers, (cell.value for cell in cells)))
                for name in ("全局序号", "论文编号", "样品ID", "锚点ID", "原文复核状态"):
                    if record.get(name) in (None, ""):
                        raise ValueError(f"Missing {name} at row {row_number}")
                anchor = (record["论文编号"], record["锚点ID"])
                if anchor in anchors or record["全局序号"] in ids:
                    raise ValueError(f"Duplicate standard identity at row {row_number}")
                anchors.add(anchor)
                ids.add(record["全局序号"])
                record["_excel_row"] = row_number
                records.append(record)
            other_sheets = {
                ws.title: sum(any(v is not None for v in row) for row in ws.iter_rows(values_only=True))
                for ws in wb.worksheets if ws.title != "Sheet1"
            }
            if any(other_sheets.values()):
                raise ValueError("Additional populated sheets need explicit selection; refusing to silently skip them")
            if not records:
                raise ValueError("Standard workbook contains no records")
            return records, {"sheet": "Sheet1", "columns": len(headers), "other_sheets_nonempty_rows": other_sheets}
        finally:
            wb.close()


def check_unit(unit, family: str) -> str:
    if unit in (None, ""):
        return "dimensionless_implicit" if family == "dimensionless" else "missing"
    token = str(unit).strip().casefold()
    if token in UNIT_FAMILIES[family]:
        return "compatible"
    known_units = set().union(*UNIT_FAMILIES.values())
    return "conflict" if token in known_units else "unrecognized"


def map_record(row: dict, aliases: dict, official: dict, specialized: dict) -> dict:
    reviewed = row.get("原文复核后规范性质名")
    unit = row.get("原文复核后规范单位")
    review_status = row["原文复核状态"]
    raw = row.get("性质名称") or ""
    flags, qualifiers = [], {}
    entry = aliases.get(normalize_name(reviewed))
    mapping_status = "mapped" if entry else "unresolved"

    # The review workbook deliberately keeps several compound source columns
    # as one row, while value_no/component_index identifies the actual table
    # component. Resolve these deterministically before applying the generic
    # pending-review guards below.
    raw_norm = normalize_name(raw)
    raw_compact = re.sub(r"[^a-z0-9]+", " ", raw_norm).strip()
    component_index = row.get("数值分量序号")
    try:
        component_index = int(component_index) if component_index not in (None, "") else None
    except (TypeError, ValueError):
        component_index = None
    if raw_compact == "uv vis lambda max":
        entry = aliases.get("absorption wavelength")
        mapping_status = "mapped"
        qualifiers.update({"measurement_type": "absorption", "wavelength_type": "lambda_max"})
        flags.append("compound_column_split_deterministic")
    elif raw_compact in {"uv vis and pl max in thf", "uv vis and pl max in thf"}:
        key = "absorption wavelength" if component_index == 0 else "emission wavelength" if component_index == 1 else None
        entry = aliases.get(key) if key else None
        mapping_status = "mapped" if entry else "unresolved"
        if entry:
            qualifiers.update({"measurement_type": "absorption" if component_index == 0 else "photoluminescence", "wavelength_type": "lambda_max", "solvent_raw": "THF"})
            flags.append("compound_column_split_deterministic")
    elif raw_norm.startswith("dc conductivity"):
        entry = aliases.get("electric conductivity")
        mapping_status = "mapped"
        qualifiers.update({"measurement_type": "dc_conductivity"})
        if "before uv" in raw_norm:
            qualifiers["uv_exposure"] = "before"
        elif "after 2h uv" in raw_norm:
            qualifiers["uv_exposure"] = "after_2h"
        elif "after 6h uv" in raw_norm:
            qualifiers["uv_exposure"] = "after_6h"
        flags.append("compound_column_split_deterministic")
    elif component_index in (0, 1) and raw_norm in {"surface tension (polar and dispersive force)", "surface free energy (polar and dispersive force)"}:
        key = "surface tension polar" if component_index == 0 else "surface tension dispersive"
        entry = aliases.get(key)
        mapping_status = "mapped" if entry else "unresolved"
        if entry:
            qualifiers["surface_component"] = "polar" if component_index == 0 else "dispersive"
            flags.append("surface_component_split_deterministic")

    # 空复核列是明确待定，不回退到旧建议列或原始名称强行编码。
    if review_status == "原文确认-过程信息":
        entry, mapping_status = None, "out_of_scope"
        flags.append("process_information")
    elif review_status == "原文确认-待拆列" and "compound_column_split_deterministic" not in flags:
        entry, mapping_status = None, "unresolved"
        flags.append("compound_column_requires_review")
        if normalize_name(raw).startswith("dc conductivity"):
            flags.append("raw_conductivity_conflicts_with_uv_pl_review")
    elif (review_status == "原文确认-待分量" or row.get("性质变体_v2") == "total_or_polar_or_dispersive") and "surface_component_split_deterministic" not in flags:
        # An explicit reviewed Surface tension row keeps its registered code;
        # the component flag remains a review concern for publication.
        if normalize_name(reviewed) == "surface tension":
            flags.append("surface_component_unresolved")
        else:
            entry, mapping_status = None, "unresolved"
            flags.append("surface_component_unresolved")
    elif normalize_name(raw) == "mw" and raw.strip() != "Mw" and normalize_name(reviewed) == "mw":
        entry, mapping_status = None, "unresolved"
        flags.append("uppercase_MW_statistic_unresolved")
    elif normalize_name(reviewed) == "mw of paa":
        entry, mapping_status = None, "unresolved"
        flags.append("uppercase_MW_statistic_unresolved")
    elif entry and entry["key"] == "molecular_weight_dispersity" and normalize_name(raw) not in {
        "molecular weight dispersity (mw/mn)", "mw/mn", "pdi", "dispersity",
    }:
        entry, mapping_status = None, "unresolved"
        flags.append("distribution_not_confirmed_as_dispersity")

    unit_status = check_unit(unit, entry["unit_family"]) if entry else ("missing" if unit in (None, "") else "not_checked")
    proposed_code = f"STD:{entry['key']}" if entry else None
    if unit_status == "conflict":
        mapping_status = "unresolved"
        flags.append("reviewed_property_unit_conflict")
    elif unit_status in {"missing", "unrecognized", "dimensionless_implicit"}:
        flags.append(f"unit_{unit_status}")
    if entry:
        flags.extend(entry.get("review_flags", []))
    elif not flags:
        flags.append("reviewed_name_blank_or_not_registered")
    if review_status == "原文文本层未完整命中":
        flags.append("pdf_visual_review_pending")
    recommendation = row.get("原文复核建议") or ""
    if recommendation.startswith("纳入主评估") and row.get("主评估纳入_v2") == "否":
        flags.append("evaluation_inclusion_conflict")

    # 保留原文已明确写出的分量/事件信息；这些不是样品绑定或实验条件推断。
    explicit_qualifiers = {
        "Tg1": {"transition_index": 1}, "Tg2": {"transition_index": 2},
        "Tm2": {"transition_index": 2}, "Tm1 of PEP": {"transition_index": 1, "component_label_raw": "PEP"},
        "Water contact angle": {"probe_liquid_raw": "water"},
        "Crystallinity of sPP": {"component_label_raw": "sPP"},
        "Crystallinity of PEP": {"component_label_raw": "PEP"},
        "Tc (cold crystn. temp.)": {"event_raw": "cold crystallization"},
        "Tr (recrystn. temp.)": {"event_raw": "recrystallization"},
        "Total wt. loss at 800C": {"temperature_raw": "800C", "event_raw": "total weight loss"},
    }
    qualifiers.update(explicit_qualifiers.get(raw, {}))
    pipeline_name = entry.get("pipeline_property_name") if entry else None
    specialized_key = entry.get("pipeline_specialized_key") if entry else None
    if pipeline_name and pipeline_name not in official:
        raise ValueError(f"Registry references missing pipeline property: {pipeline_name}")
    if specialized_key and specialized_key not in specialized:
        raise ValueError(f"Registry references missing specialized key: {specialized_key}")
    return {
        "standard_record_id": f"GT:{row['论文编号']}:{row['全局序号']}",
        "reference_no": row["论文编号"], "source_sheet": "Sheet1", "source_excel_row": row["_excel_row"],
        "source_global_id": row["全局序号"], "article_sample_id": row["样品ID"],
        "anchor_id": row["锚点ID"], "source_json": row.get("来源JSON"),
        "property_name_raw": raw, "reviewed_property_name": reviewed,
        "reviewed_unit": unit, "value_min": row.get("数值最小"), "value_max": row.get("数值最大"),
        "standard_property_code": proposed_code if mapping_status == "mapped" else None,
        "proposed_standard_property_code": proposed_code,
        "mapping_status": mapping_status, "unit_status": unit_status,
        "pipeline_property_name": pipeline_name,
        "pipeline_specialized_key": specialized_key,
        "polyinfo_group_code": official[pipeline_name][0] if pipeline_name else None,
        "mapping_basis": "reviewed_column_and_explicit_registry" if mapping_status == "mapped" else "requires_review_or_out_of_scope",
        "property_variant_raw": row.get("性质变体_v2"), "qualifiers": qualifiers,
        "source_review_status": review_status, "source_review_basis": row.get("原文复核依据"),
        "source_review_recommendation": recommendation, "source_main_evaluation_v2": row.get("主评估纳入_v2"),
        "evidence_excerpt": row.get("证据摘录"), "needs_review": bool(flags), "review_flags": flags,
    }


def build(standard: Path, registry_path: Path, schema_path: Path, output: Path) -> dict:
    import yaml

    source_hash = file_hash(standard)
    registry, aliases = load_registry(registry_path)
    schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    rows, sheet_info = read_standard(standard)
    mapped = [map_record(r, aliases, schema["property_vocabulary"], schema["specialized_property_vocabulary"]) for r in rows]
    if file_hash(standard) != source_hash:
        raise ValueError("Standard workbook changed during read; regenerate from one stable snapshot")
    summary = {
        "schema_version": "standard_property_codes.v1", "registry_version": registry["registry_version"],
        "source_file": str(standard.resolve()), "source_sha256": source_hash,
        "registry_file": str(registry_path.resolve()), "registry_sha256": file_hash(registry_path),
        "pipeline_schema_sha256": file_hash(schema_path), **sheet_info,
        "records": len(mapped), "documents": len({r["reference_no"] for r in mapped}),
        "reference_nos": sorted({r["reference_no"] for r in mapped}),
        "mapping_status_counts": dict(sorted(Counter(r["mapping_status"] for r in mapped).items())),
        "unit_status_counts": dict(sorted(Counter(r["unit_status"] for r in mapped).items())),
        "code_counts": dict(sorted(Counter(r["standard_property_code"] for r in mapped if r["standard_property_code"]).items())),
        "review_flag_counts": dict(sorted(Counter(f for r in mapped for f in r["review_flags"]).items())),
        "needs_review_records": sum(r["needs_review"] for r in mapped),
        "note": "编码成功仅表示性质标签映射成功，不表示数值、单位、样品绑定或数据发布通过验收；问题标签可能重叠。",
    }
    output.mkdir(parents=True, exist_ok=True)
    # 固定顺序和显式版本使同一输入可重复生成；原 Excel 不被写入。
    mapped.sort(key=lambda r: r["standard_record_id"])
    (output / "standard_property_codes.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in mapped), encoding="utf-8")
    (output / "manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# 标准集性质编码基线", "", f"词表版本：`{registry['registry_version']}`", "",
             f"源文件：`{standard.name}`；SHA-256：`{source_hash}`", "",
             f"记录 {len(mapped)} 条，论文 {summary['documents']} 篇。", "", summary["note"], "",
             "| 编码状态 | 记录数 |", "| --- | ---: |"]
    lines += [f"| {status} | {count} |" for status, count in summary["mapping_status_counts"].items()]
    lines += ["", "`unresolved` 的编码为空；`out_of_scope` 为过程信息。所有原始记录仍在 JSONL 中。", "",
              "| standard_property_code | 记录数 |", "| --- | ---: |"]
    lines += [f"| {code} | {count} |" for code, count in summary["code_counts"].items()]
    lines += ["", "## 待复核原因（可重叠）", "", "| 原因 | 记录数 |", "| --- | ---: |"]
    lines += [f"| {flag} | {count} |" for flag, count in summary["review_flag_counts"].items()]
    lines += ["", "同码只用于性质维度对齐；后续仍需分别核对数值、单位、样品、事件阈值、变体及 evidence。",
              "原文复核列为空时不回退旧列。PDI、AC、非特定拉伸强度等项目编码不代表生产 Schema 已支持发布。",
              "`STD:` 是项目内部命名空间；`polyinfo_group_code` 单独记录现有配置中的官方分组编号。", ""]
    (output / "standard_property_codes_report.md").write_text("\n".join(lines), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--standard", type=Path, default=DEFAULT_STANDARD)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = build(args.standard, args.registry, args.schema, args.output_dir)
    print(json.dumps({k: result[k] for k in ("records", "documents", "mapping_status_counts", "registry_version")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
