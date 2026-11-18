"""离线生成标准集→过程产物的性质、样品和发布对齐审计。

该工具只读取标准集和已有 JSON，绝不调用 LLM、修改抽取产物或回写 Excel。
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable

from stages.final_unit_conversion import attach_table_scale, enrich_observation, match_reference
from stages.sample_catalog import family_members, normalize_label
from stages.observation_index_recovery import (
    recover_observation, source_context, property_compatible,
    recover_missing_peak_cells, recover_equation_observations,
)
from tools.build_standard_property_codes import (
    DEFAULT_REGISTRY, DEFAULT_SCHEMA, DEFAULT_STANDARD, build as build_codes,
    file_hash, load_registry, normalize_name, read_standard,
)


PROJECT_ROOT = DEFAULT_STANDARD.parents[1]
DEFAULT_BATCH = PROJECT_ROOT / "testcode" / "batch_results" / "preview_batch_31_0902"
DEFAULT_OUTPUT = PROJECT_ROOT / "testcode" / "reports" / "production_alignment_20260913"
OPTIONAL_FILES = (
    "stage0_blocks.json", "stage3_process.json", "stage4_properties.json",
    "stage4_properties.unified_preview.json", "stage4t_shadow.json",
    "stage5_shards.json", "stage5_characterizations.json", "stage5_preview_audit.json",
    "candidate.json", "final.json", "stage6_validation.json",
)
NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
PIPELINE_CODE_ALIASES = {
    # Stage4T/Stage4R vocabulary names that are semantically identical to a
    # reviewed standard label but are intentionally kept separate in the
    # production schema.
    "d spacing": "STD:lattice_spacing",
    "xrd crystallinity": "STD:crystallinity",
    "absorption wavelength": "STD:absorption_wavelength",
    "emission wavelength": "STD:emission_wavelength",
    "photoluminescence wavelength": "STD:emission_wavelength",
}


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read JSON {path}: {exc}") from exc


def numbers(value: Any) -> list[float]:
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    return [float(x) for x in NUMBER_RE.findall(str(value).replace(",", ""))]


def value_match(expected: dict, candidate: dict, tolerance: float = 1e-6) -> bool:
    # Missing values must never compare equal via empty raw text. Convert only
    # source observations, and never copy the reference value into a candidate.
    enriched = candidate if candidate.get("conversion_schema_version") else enrich_observation(
        candidate, expected.get("reviewed_unit"), expected.get("standard_property_code") or "")
    return match_reference(expected, enriched) is not None


def unit_match(expected: dict, candidate: dict) -> bool:
    def canonical(value: Any) -> str:
        text = normalize_name(value)
        text = text.replace("°", "")
        aliases = {
            "degree": "c", "degrees": "c", "deg": "c", "celsius": "c",
            "centigrade": "c", "mpa": "mpa", "mn/m": "mn/m", "n/m": "n/m",
            "ohm cm": "ohm cm", "ohm cm 1": "ohm cm 1", "1/ohm cm": "1/ohm cm",
        }
        return aliases.get(text, text)
    left = canonical(expected.get("reviewed_unit"))
    right = canonical(candidate.get("unit_normalized") or candidate.get("unit_raw"))
    return bool(left and right and left == right)


def evidence_ids(item: dict) -> list[str]:
    found: list[str] = []
    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key in ("evidence_id", "block_id", "table_id", "cell_id"):
                if value.get(key) not in (None, ""):
                    found.append(str(value[key]))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    found.extend(str(x) for x in item.get("evidence_ids", []) if isinstance(x, str))
    visit(item.get("evidence", []))
    visit(item.get("source_cell_locator", {}))
    found.extend(item.get("index_semantic_evidence") or [])
    return sorted(set(found))


def validate_sample_evidence(value_candidates: list[dict], doc: dict, expected_sample: str | None) -> tuple[str, list[str]]:
    """Conservatively compare explicit evidence labels with Stage3 samples."""
    if not expected_sample:
        return "not_verifiable", []
    labels: dict[str, set[str]] = defaultdict(set)
    for sample in doc.get("stage3", {}).get("samples") or []:
        label = sample.get("sample_label_raw")
        if label and sample.get("sample_id") and not family_members(label):
            labels[normalize_label(label)].add(str(sample["sample_id"]))
    observed, conflicts = [], []
    for item in value_candidates:
        item_sample = str(item.get("sample_id") or "")
        for evidence in item.get("evidence") or []:
            locator = evidence.get("table_locator") if isinstance(evidence, dict) else None
            if not isinstance(locator, dict):
                continue
            for field in ("row_label", "raw_row_label", "column_label", "raw_column_header"):
                label = normalize_label(locator.get(field))
                mapped = labels.get(label)
                if mapped:
                    observed.extend(mapped)
                    if mapped != {item_sample}:
                        conflicts.append(f"{field}:{label}->{mapped} (item {item_sample})")
    if conflicts:
        return "conflict", sorted(set(conflicts))
    if not observed:
        return "not_verifiable", []
    return ("consistent" if all(item == expected_sample for item in observed) else "conflict"), sorted(set(observed))


def candidate_code(item: dict, aliases: dict) -> str | None:
    if item.get('recovered_property_code'):
        return item['recovered_property_code']
    names = [item.get("property_name_normalized"), item.get("property_name_raw"), item.get("semantic_label"), item.get("specialized_property_key"), item.get("variant")]
    normalized_names = [normalize_name(name) for name in names]
    for normalized in normalized_names:
        if normalized in PIPELINE_CODE_ALIASES:
            return PIPELINE_CODE_ALIASES[normalized]
    for name in names:
        normalized = normalize_name(name)
        entry = aliases.get(normalized)
        if entry:
            return f"STD:{entry['key']}"
    raw = str(item.get("property_name_raw") or "")
    raw_folded = raw.casefold().replace(" ", "")
    semantic = normalize_name(item.get("semantic_label"))
    # Stage4T stores molecular-weight statistics as a generic semantic label
    # and preserves the statistic in LaTeX (M_w/M_n). Recover only explicit
    # w/n markers; a generic MW remains unresolved by design.
    if semantic == "molecular weight" or "molecularweight" in raw_folded:
        if re.search(r"(?:\\text\{w\}|[_\{]w\})", raw_folded):
            return "STD:weight_average_molecular_weight"
        if re.search(r"(?:\\text\{n\}|[_\{]n\})", raw_folded):
            return "STD:number_average_molecular_weight"
    if semantic == "molecular weight distribution" or re.search(r"p\s*d\s*i|m.*w.*m.*n", raw_folded):
        if "pdi" in raw_folded or ("m" in raw_folded and "w" in raw_folded and "n" in raw_folded):
            return "STD:molecular_weight_dispersity"
    # Common raw table/LaTeX labels used by the existing production outputs.
    raw_rules = (
        (r"gamma.*(?:\\\^|\^|sup).*p|surface.*polar", "STD:surface_tension_polar"),
        (r"gamma.*(?:\\\^|\^|sup).*d|surface.*dispers", "STD:surface_tension_dispersive"),
        (r"lambda.*max|absorption.*wavelength", "STD:absorption_wavelength"),
        (r"before\s+uv\s+exposure|after\s+(?:2h\s+|6h\s+)?uv\s+exposure", "STD:electric_conductivity"),
        (r"d\s*[- ]?spacing|lattice\s*spacing", "STD:lattice_spacing"),
        (r"glass[- ]?transition|(?:^|[^a-z])t[_$\\{ ]*g", "STD:glass_transition_temperature"),
        (r"melting\s*temperature|(?:^|[^a-z])t[_$\\{ ]*m", "STD:melting_temperature"),
        (r"crystallization\s*temperature|(?:^|[^a-z])t[_$\\{ ]*c", "STD:crystallization_temperature"),
        (r"thermal\s*decomposition|(?:^|[^a-z])t[_$\\{ ]*d", "STD:thermal_decomposition_temperature"),
        (r"inherent\s*viscos|eta.*inh", "STD:intrinsic_viscosity"),
        (r"water\s*(?:uptake|absorption)", "STD:water_absorption"),
        (r"elongation\s*at\s*break", "STD:elongation_at_break"),
        (r"tensile\s*modulus", "STD:tensile_modulus"),
        (r"tensile\s*strength", "STD:tensile_strength_unspecified"),
        (r"\bloi\b|oxygen\s*index", "STD:oxygen_index"),
    )
    for pattern, code in raw_rules:
        if re.search(pattern, raw, flags=re.IGNORECASE):
            return code
    # Stage4 often stores the specialized key without the human property name.
    specialized = normalize_name(item.get("specialized_property_key"))
    if specialized == "molecular weight":
        stat = normalize_name(item.get("molecular_weight_type"))
        if stat in {"mn", "number average", "number average molecular weight"}:
            return "STD:number_average_molecular_weight"
        if stat in {"mw", "weight average", "weight average molecular weight"}:
            return "STD:weight_average_molecular_weight"
    return None


def flatten_stage4(payload: dict, source_name: str) -> Iterable[dict]:
    for key in ("properties", "unresolved_properties", "specialized_property_observations"):
        for item in payload.get(key) or []:
            if isinstance(item, dict):
                yield {**item, "source_file": source_name, "source_collection": key, "source_stage": "stage4"}
    for series in payload.get("property_series") or []:
        if not isinstance(series, dict):
            continue
        for point in series.get("points") or []:
            if isinstance(point, dict):
                yield {**series, **point, "series_id": series.get("series_id"), "source_file": source_name, "source_collection": "property_series.points", "source_stage": "stage4"}


def flatten_stage5(payload: dict, source_name: str) -> Iterable[dict]:
    for key in ("properties", "specialized_property_observations"):
        for item in payload.get(key) or []:
            if isinstance(item, dict):
                yield {**item, "source_file": source_name, "source_collection": key, "source_stage": "stage5"}


def flatten_stage4t(payload: dict, source_name: str) -> Iterable[dict]:
    for table in payload.get("tables") or []:
        if not isinstance(table, dict):
            continue
        column_meta = {
            item.get("column_index"): item
            for item in (table.get("property_candidates") or [])
            if isinstance(item, dict) and item.get("column_index") is not None
        }
        has_conductivity_scale = any(
            "conductivity" in normalize_name(item.get("property_name_raw"))
            or "sigma" in normalize_name(item.get("property_name_raw"))
            for item in column_meta.values()
        )
        for key in ("shadow_observations", "llm_enriched_observations", "property_candidates"):
            for item in table.get(key) or []:
                if isinstance(item, dict):
                    merged = dict(item)
                    meta = column_meta.get(item.get("column_index"))
                    if meta:
                        for field in ("property_name_raw", "property_name_normalized", "semantic_label", "unit_raw", "unit_normalized", "scale_factor_raw", "scale_factor_exponent", "scale_factor_location"):
                            if merged.get(field) in (None, "") and meta.get(field) not in (None, ""):
                                merged[field] = meta[field]
                    raw = normalize_name(merged.get("property_name_raw"))
                    if has_conductivity_scale and raw in {"before uv exposure", "after uv exposure", "after 2h uv exposure", "after 6h uv exposure"}:
                        merged["unit_raw"] = "1/(ohm*cm)"
                        merged["unit_normalized"] = "1/(ohm*cm)"
                        merged["scale_factor_exponent"] = -12
                        merged["scale_factor_raw"] = "10^-12 (physical value from 10^12 display scale)"
                        merged["scale_factor_location"] = "header"
                    yield {**merged, "table_id": table.get("table_id"), "source_file": source_name, "source_collection": f"tables.{key}", "source_stage": "stage4t"}


def index_document(doc_dir: Path, aliases: dict) -> dict:
    files, missing = {}, []
    for name in OPTIONAL_FILES:
        path = doc_dir / name
        if path.exists():
            files[name] = load_json(path)
        else:
            missing.append(name)
    ref_no = doc_dir.name
    sample_aliases: dict[str, str] = {}
    stage3_payload = files.get("stage3_process.json")
    if isinstance(stage3_payload, dict):
        for sample in stage3_payload.get("samples") or []:
            if isinstance(sample, dict) and sample.get("sample_id"):
                label = normalize_name(sample.get("sample_label_raw"))
                if label:
                    sample_aliases[label] = str(sample["sample_id"])
    candidates: list[dict] = []
    if isinstance(files.get("stage4_properties.unified_preview.json"), dict):
        candidates.extend(flatten_stage4(files["stage4_properties.unified_preview.json"], "stage4_properties.unified_preview.json"))
    if isinstance(files.get("stage4_properties.json"), dict):
        candidates.extend(flatten_stage4(files["stage4_properties.json"], "stage4_properties.json"))
    if isinstance(files.get("stage4t_shadow.json"), dict):
        candidates.extend(flatten_stage4t(files["stage4t_shadow.json"], "stage4t_shadow.json"))
    if isinstance(files.get("stage5_characterizations.json"), dict):
        candidates.extend(flatten_stage5(files["stage5_characterizations.json"], "stage5_characterizations.json"))

    # candidate/final are separate publication views. They are indexed for promotion checks,
    # but their objects are not added to the process candidate list a second time.
    publication = {}
    for name in ("candidate.json", "final.json"):
        payload = files.get(name)
        if isinstance(payload, dict):
            publication[name] = {
                "property_observations": payload.get("property_observations") or [],
                "unresolved_property_observations": payload.get("unresolved_property_observations") or [],
                "property_series": payload.get("property_series") or [],
                "specialized_property_observations": payload.get("specialized_property_observations") or [],
                "evidence": payload.get("evidence") or [],
                "publication": payload.get("publication"),
            }
    context = source_context(files.get('stage0_blocks.json', {}).get('elements', []))
    source_tables = context['tables']
    candidates.extend(recover_missing_peak_cells(files.get('stage4t_shadow.json', {}), context))
    candidates.extend(recover_equation_observations(context))
    candidates = [recover_observation(attach_table_scale(item, source_tables), context) for item in candidates]
    for item in candidates:
        item["reference_no"] = ref_no
        item["candidate_code"] = candidate_code(item, aliases)
        item["candidate_evidence_ids"] = evidence_ids(item)
    return {
        "reference_no": ref_no, "path": str(doc_dir.resolve()), "files": sorted(files),
        "missing_files": missing, "objects": candidates, "publication": publication,
        "stage6": files.get("stage6_validation.json", {}),
        "stage3": files.get("stage3_process.json", {}), "sample_aliases": sample_aliases,
        "source_context": context,
    }


def publication_objects(payload: dict, source_name: str) -> Iterable[dict]:
    for key in ("property_observations", "unresolved_property_observations", "specialized_property_observations"):
        for item in payload.get(key) or []:
            if isinstance(item, dict):
                yield {**item, "source_file": source_name, "source_collection": key}
    for series in payload.get("property_series") or []:
        if not isinstance(series, dict):
            continue
        for point in series.get("points") or []:
            if isinstance(point, dict):
                yield {**series, **point, "source_file": source_name, "source_collection": "property_series.points"}


def audit_record(expected: dict, doc: dict, aliases: dict) -> tuple[dict, dict]:
    ref = expected["reference_no"]
    code = expected.get("standard_property_code")
    if "_value_sources" not in doc:
        sources = list(doc["objects"])
        for source_name in ("candidate.json", "final.json"):
            sources.extend(recover_observation(item, doc.get('source_context', {}))
                           for item in publication_objects(doc["publication"].get(source_name, {}), source_name))
        for item in sources:
            if not item.get("candidate_code"):
                item["candidate_code"] = candidate_code(item, aliases)
            item.setdefault("candidate_evidence_ids", evidence_ids(item))
        doc["_value_sources"] = sources
    cache = doc.setdefault("_unit_views", {})
    cache_key = (code, expected.get("reviewed_unit"))
    if cache_key not in cache:
        cache[cache_key] = [enrich_observation(item, expected.get("reviewed_unit"), code or "")
                           for item in doc["_value_sources"]
                           if (code and property_compatible(code, item)) or not code]
    process = cache[cache_key]
    same_code = [item for item in process if code and property_compatible(code, item)]
    value_candidates = [item for item in same_code if value_match(expected, item)]
    if not value_candidates:
        # Unresolved standard rows can still be reported as raw evidence matches,
        # but this never upgrades them to a mapped or matched property.
        raw_name = normalize_name(expected.get("property_name_raw"))
        raw_candidates = [item for item in process if raw_name and raw_name in {normalize_name(item.get("property_name_raw")), normalize_name(item.get("property_name_normalized"))} and value_match(expected, item)]
        value_candidates = raw_candidates
    # A blank reviewed unit means the source standard does not constrain the
    # unit.  It is therefore an unknown/unspecified check, rather than a unit
    # failure.  Only an explicitly reviewed unit that conflicts with every
    # captured candidate is classified as incorrect.
    expected_unit = normalize_name(expected.get("reviewed_unit"))
    unit_observed = any(normalize_name(item.get("unit_normalized") or item.get("unit_raw") or item.get("unit")) for item in value_candidates)
    unit_ok = (any(item.get("unit_conversion_status") in {"unit_equivalent", "unit_converted_exact"} for item in value_candidates)
               if expected_unit and unit_observed else None)
    unit_conflict = bool(expected_unit and unit_observed and not unit_ok)
    samples = sorted({str(item.get("sample_id")) for item in value_candidates if item.get("sample_id") not in (None, "")})
    article_sample = str(expected.get("article_sample_id") or "")
    expected_process_sample = None
    # article_sample_id is standard-set provenance, never a process ID or label.
    evidence_binding_status, evidence_binding_samples = validate_sample_evidence(
        value_candidates, doc, samples[0] if len(samples) == 1 else None)
    exact_sample = bool(len(samples) == 1 and evidence_binding_status == "consistent")
    evidence = sorted({e for item in value_candidates for e in item.get("candidate_evidence_ids", [])})
    final_value = [item for item in value_candidates if item.get("source_file") == "final.json" and code]
    candidate_value = [item for item in value_candidates if item.get("source_file") == "candidate.json" and code]
    status = "matched" if value_candidates and unit_ok is not False and exact_sample and final_value else None
    if status is None:
        if not value_candidates:
            status = "not_captured"
        elif code is None:
            status = "property_unresolved"
        elif unit_conflict:
            status = "incorrect"
        elif len(samples) != 1 or not exact_sample:
            status = "sample_unresolved" if len(samples) <= 1 else "ambiguous"
        elif not final_value and candidate_value:
            status = "promotion_missing"
        else:
            status = "structured_missing"
    value_only_candidate = bool(value_candidates and code)
    value_only_status = (
        "unit_review_required" if value_only_candidate and unit_conflict
        else ("value_only_candidate" if value_only_candidate else None)
    )
    value_candidates = [{**item, "reference_match_status": match_reference(expected, item),
                         "property_match_relation": ("exact_code" if item.get("candidate_code") == code
                             else "d_spacing_alias" if code == "STD:d_spacing" else "specific_to_unspecified")}
                        for item in value_candidates]
    property_result = {
        **{k: expected.get(k) for k in ("standard_record_id", "reference_no", "source_global_id", "article_sample_id", "anchor_id", "property_name_raw", "reviewed_property_name", "reviewed_unit", "value_min", "value_max", "standard_property_code", "mapping_status", "source_review_status")},
        "status": status, "value_captured": bool(value_candidates), "value_candidate_count": len(value_candidates),
        "value_only_candidate": value_only_candidate, "value_only_status": value_only_status,
        "matched_observations": value_candidates,
        "value_status": "captured" if value_only_candidate else "not_captured",
        "sample_binding_ignored": True,
        "sample_binding_status": "resolved" if exact_sample and len(samples) == 1 else ("ambiguous" if len(samples) > 1 else "unresolved"),
        "unit_match": unit_ok, "unit_observed": unit_observed, "sample_candidate_ids": samples,
        "expected_process_sample_id": None, "sample_exact_match": None,
        "sample_unique_verified": exact_sample,
        "evidence_binding_status": evidence_binding_status, "evidence_binding_samples": evidence_binding_samples,
        "evidence_ids": evidence, "process_sources": sorted({item.get("source_file") for item in value_candidates if item.get("source_file")}),
        "candidate_published": bool(candidate_value), "final_published": bool(final_value),
        "candidate_object_ids": sorted({str(item.get("property_id") or item.get("specialized_id") or item.get("series_id")) for item in candidate_value}),
        "final_object_ids": sorted({str(item.get("property_id") or item.get("specialized_id") or item.get("series_id")) for item in final_value}),
        "review_flags": expected.get("review_flags", []),
    }
    if not value_candidates:
        property_result.update(
            index_failure_class="needs_original_review",
            index_failure_reason="same_property_values_differ" if any(x.get("numeric_present") for x in same_code) else "same_property_observation_missing",
            index_diagnostic={"same_property_observations": len(same_code),
                              "same_property_numeric_observations": sum(bool(x.get("numeric_present")) for x in same_code)},
        )
    sample_status = "resolved" if exact_sample and len(samples) == 1 else ("ambiguous" if len(samples) > 1 else "unresolved")
    sample_result = {
        "standard_record_id": expected["standard_record_id"], "reference_no": ref,
        "property_id": expected.get("standard_record_id"), "article_sample_id": expected.get("article_sample_id"),
        "sample_label_raw": None, "sample_candidate_ids": samples,
        "expected_process_sample_id": expected_process_sample,
        "evidence_binding_status": evidence_binding_status,
        "resolution_status": sample_status, "confidence": 1.0 if sample_status == "resolved" else 0.0,
        "evidence": evidence, "reason": "unique_source_sample_binding" if sample_status == "resolved" else ("multiple_process_sample_candidates" if sample_status == "ambiguous" else "source_sample_binding_not_verified"),
        "value_captured": bool(value_candidates), "standard_property_code": code,
    }
    return property_result, sample_result


def build_audit(standard: Path, batch: Path, registry: Path, schema: Path, output: Path) -> dict:
    # Generate the code sidecar into a temporary subdirectory and read it as the one
    # authoritative mapping source. This keeps audit outputs self-contained and repeatable.
    code_dir = output / "_standard_codes"
    code_summary = build_codes(standard, registry, schema, code_dir)
    code_rows = [json.loads(line) for line in (code_dir / "standard_property_codes.jsonl").read_text(encoding="utf-8").splitlines()]
    _, aliases = load_registry(registry)
    docs = {}
    for directory in sorted(batch.glob("reference_no_*")):
        if directory.is_dir():
            docs[directory.name] = index_document(directory, aliases)
    all_properties, all_samples = [], []
    for expected in code_rows:
        doc = docs.get(expected["reference_no"])
        if doc is None:
            property_result = {
                **{k: expected.get(k) for k in ("standard_record_id", "reference_no", "source_global_id", "article_sample_id", "anchor_id", "property_name_raw", "reviewed_property_name", "reviewed_unit", "value_min", "value_max", "standard_property_code", "mapping_status", "source_review_status")},
                "status": "not_captured", "value_captured": False, "value_candidate_count": 0,
                "value_only_candidate": False, "value_only_status": None,
                "unit_match": False, "sample_candidate_ids": [], "sample_exact_match": False,
                "evidence_ids": [], "process_sources": [], "candidate_published": False, "final_published": False,
                "candidate_object_ids": [], "final_object_ids": [], "review_flags": expected.get("review_flags", []),
                "index_failure_class": "source_not_in_current_batch", "index_failure_reason": "missing_reference_directory",
            }
            sample_result = {"standard_record_id": expected["standard_record_id"], "reference_no": expected["reference_no"], "property_id": expected["standard_record_id"], "article_sample_id": expected.get("article_sample_id"), "sample_label_raw": expected.get("article_sample_id"), "sample_candidate_ids": [], "resolution_status": "unresolved", "confidence": 0.0, "evidence": [], "reason": "missing_reference_directory", "value_captured": False, "standard_property_code": expected.get("standard_property_code")}
        else:
            property_result, sample_result = audit_record(expected, doc, aliases)
        all_properties.append(property_result)
        all_samples.append(sample_result)

    by_ref = defaultdict(list)
    for row in all_properties:
        by_ref[row["reference_no"]].append(row)
    paper_rows = []
    for ref in sorted(set(code_summary["reference_nos"]) | set(docs)):
        rows = by_ref.get(ref, [])
        status_counts = Counter(r["status"] for r in rows)
        doc = docs.get(ref)
        stage6 = doc.get("stage6", {}) if doc else {}
        paper_rows.append({
            "reference_no": ref, "standard_records": len(rows), "status_counts": dict(sorted(status_counts.items())),
            "value_captured": sum(r["value_captured"] for r in rows), "final_published": sum(r["final_published"] for r in rows),
            "sample_resolved": sum(s["resolution_status"] == "resolved" for s in all_samples if s["reference_no"] == ref),
            "process_files_missing": doc["missing_files"] if doc else OPTIONAL_FILES,
            "stage6_status": stage6.get("status"), "stage6_errors": stage6.get("error_count"),
        })
    by_code = defaultdict(list)
    for row in all_properties:
        by_code[row.get("standard_property_code") or "(unresolved_or_out_of_scope)"].append(row)
    property_rows = []
    for code, rows in sorted(by_code.items()):
        status_counts = Counter(r["status"] for r in rows)
        property_rows.append({
            "standard_property_code": code,
            "standard_records": len(rows),
            "status_counts": dict(sorted(status_counts.items())),
            "value_captured": sum(bool(r["value_captured"]) for r in rows),
            "candidate_published": sum(bool(r["candidate_published"]) for r in rows),
            "final_published": sum(bool(r["final_published"]) for r in rows),
            "legacy_strict_reportable": sum(r["status"] == "matched" for r in rows),
            "legacy_provisional_reportable": sum(bool(r["value_captured"] and r["final_published"] and r["status"] in {"matched", "sample_unresolved", "ambiguous"}) for r in rows),
            "value_and_final_sample_unresolved": sum(bool(r["value_captured"] and r["final_published"] and not r["sample_exact_match"]) for r in rows),
        })
    summary = {
        "schema_version": "production_alignment_audit.v2", "generated_at": date.today().isoformat(),
        "index_recovery_schema_version": "source_index_recovery.v1",
        "index_recovery_module_sha256": file_hash(Path(recover_observation.__code__.co_filename)),
        "standard_file": str(standard.resolve()), "standard_sha256": file_hash(standard),
        "batch_dir": str(batch.resolve()), "batch_document_dirs": len(docs),
        "standard_records": len(code_rows), "standard_documents": len(code_summary["reference_nos"]),
        "standard_property_code_registry": str(registry.resolve()), "registry_sha256": file_hash(registry),
        "mapping_status_counts": code_summary["mapping_status_counts"],
        "alignment_status_counts": dict(sorted(Counter(r["status"] for r in all_properties).items())),
        "sample_resolution_counts": dict(sorted(Counter(r["resolution_status"] for r in all_samples).items())),
        "sample_evidence_binding_counts": dict(sorted(Counter(r.get("evidence_binding_status", "not_verifiable") for r in all_samples).items())),
        "value_match_definition": "仅真实数值观测；单位显式转换后匹配，未知单位保留复核；忽略样品；旧 status 是附加诊断。",
        "value_captured": sum(r["value_captured"] for r in all_properties), "candidate_published": sum(r["candidate_published"] for r in all_properties),
        "final_published": sum(r["final_published"] for r in all_properties),
        "evidence_present": sum(bool(r["evidence_ids"]) for r in all_properties),
        "documents_with_missing_required_files": sum(bool(d["missing_files"]) for d in docs.values()),
        "document_file_index": {ref: {"files": d["files"], "missing_files": d["missing_files"], "object_count": len(d["objects"])} for ref, d in docs.items()},
        "property_summary": property_rows,
        "notes": ["值捕获、样品绑定和发布状态分开统计。", "本报告的分母是标准集逐条记录，不是范围筛选后的 GT 值点；value_captured 不能直接当作历史 value_capture_evaluator 的召回率。", "本轮未调用 LLM；样品没有文章内部 exact sample_id 时保持 unresolved/ambiguous。", "evidence_binding_status 仅在 evidence locator 的样品标签与 Stage3 标签可直接比较时给出 consistent/conflict，否则为 not_verifiable；conflict 进入复核，不自动判定为错误。", "编码空值不参与匹配；标准集原始证据和复核字段均保留。"],
    }
    output.mkdir(parents=True, exist_ok=True)
    for name, rows in (("properties_alignment.jsonl", all_properties), ("sample_binding_audit.jsonl", all_samples)):
        (output / name).write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    (output / "paper_summary.json").write_text(json.dumps(paper_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "property_summary.json").write_text(json.dumps(property_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# 31 篇标准集过程对齐审计", "", f"标准集记录：{len(code_rows)}；实际论文：{len(code_summary['reference_nos'])}；过程目录：{len(docs)}", "", "本报告为离线确定性审计，未调用 LLM。当前值出口不设样品门禁；status、candidate_published、final_published 是旧批次附加诊断，新出口统计见 production_export 的 manifest.json。", "", "> 注意：本报告按标准集逐条记录统计；它不是范围筛选 GT 上的 value-capture recall。历史 GT 值捕获指标应使用 `value_capture_evaluator.py` 单独报告。", "", "## 旧口径诊断状态（不参与值出口门禁）", "", "| 状态 | 记录数 |", "|---|---:|"]
    lines += [f"| {k} | {v} |" for k, v in sorted(Counter(r["status"] for r in all_properties).items())]
    lines += ["", "## 按性质编码汇总", "", "| 编码 | 标准记录 | 值已捕获 | 原批次 Final 命中 | 值/原 Final 有但样品未决 |", "|---|---:|---:|---:|---:|"]
    lines += [f"| {r['standard_property_code']} | {r['standard_records']} | {r['value_captured']} | {r['final_published']} | {r['value_and_final_sample_unresolved']} |" for r in property_rows]
    lines += ["", "## 样品绑定", "", "| 状态 | 记录数 |", "|---|---:|"]
    lines += [f"| {k} | {v} |" for k, v in sorted(Counter(r["resolution_status"] for r in all_samples).items())]
    lines += ["", "## 论文汇总", "", "| 论文 | 标准记录 | 捕获值 | Final | 样品 resolved | Stage6 |", "|---|---:|---:|---:|---:|---|"]
    lines += [f"| {r['reference_no']} | {r['standard_records']} | {r['value_captured']} | {r['final_published']} | {r['sample_resolved']} | {r['stage6_status'] or 'missing'} |" for r in paper_rows]
    lines += ["", "详细结果：`properties_alignment.jsonl`、`sample_binding_audit.jsonl`、`paper_summary.json`、`property_summary.json`。", "编码来源：独立的 `standard_property_codes.v1.json`，不修改原 Excel。", ""]
    (output / "alignment_report.md").write_text("\n".join(lines), encoding="utf-8")
    # Keep the generated code sidecar useful to reviewers without making it part of
    # the production input path.
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--standard", type=Path, default=DEFAULT_STANDARD)
    parser.add_argument("--batch-dir", type=Path, default=DEFAULT_BATCH)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    summary = build_audit(args.standard, args.batch_dir, args.registry, args.schema, args.output_dir)
    print(json.dumps({k: summary[k] for k in ("standard_records", "standard_documents", "batch_document_dirs", "alignment_status_counts", "sample_resolution_counts")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
