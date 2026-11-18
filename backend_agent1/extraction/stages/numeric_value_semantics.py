"""保留原文的数值解释；没有可靠倍率关系时只记录候选，不补猜。"""
from __future__ import annotations

import html
import math
import re
from decimal import Decimal
from typing import Any
from types import SimpleNamespace

from stages.final_unit_conversion import parse_numeric
from stages.source_context_semantics import derive_source_semantics, literal_value_supported, plain
from stages.table_grid import table_cells_for

DERIVATION_VERSION = "numeric_semantics.v5"


def _middle_dot_column(item: Any, blocks: dict, contexts: list[dict]) -> list[dict]:
    """Repeated decimal typography in the same column, with an explicit unit header."""
    anchors = [c for c in contexts if c["scope"] == "table_cell"]
    headers = [plain(c["text_raw"]) for c in contexts if c["scope"] == "table_header"]
    if not any(re.search(r"%|°C|k?cal/(?:mol|mole)|[kM]?Hz|g/mol", h) for h in headers):
        return []
    for context in anchors:
        block = blocks.get(context["block_id"])
        cells = table_cells_for(block) if block is not None and block.type == "table" else []
        anchor = next((c for c in cells if c.cell_id == context["source_cell_id"]), None)
        if anchor is None: continue
        column = [plain(c.text) for c in cells if c.column_index == anchor.column_index
                  and c.row_index > max((h.row_index for h in cells if h.cell_id in {x["source_cell_id"] for x in contexts if x["scope"] == "table_header"}), default=0) and not c.is_header]
        decimal = r"[+-]?\d+·\d+(?:[*†‡])?"
        repeated = sum(bool(re.fullmatch(decimal, text)) for text in column)
        if repeated >= 3 and sum(bool(re.fullmatch(r"[+-]?\d+·\d{2,}(?:[*†‡])?", text)) for text in column) >= 2 and not any(re.search(r"(?:×|\*\s*\d|·\s*10\^|\\cdot)", text) for text in column):
            return [{"block_id":block.block_id,"source_cell_id":c.cell_id,"text_raw":c.text}
                    for c in cells if c.column_index == anchor.column_index and re.fullmatch(decimal,plain(c.text))]
    return []


_POWER = re.compile(r"10\s*\^\s*\{?\s*([+-]?\d+)\s*\}?")
_SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻", "0123456789+-")


def _text(value: str) -> str:
    value = re.sub(r"10\s*<sup>([+-]?\d+)</sup>", r"10^{\1}", value, flags=re.I)
    value = html.unescape(re.sub(r"<[^>]+>", "", value)).replace("−", "-")
    value = re.sub(r"10([⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻]+)",
                   lambda m: "10^{" + m[1].translate(_SUPERSCRIPTS) + "}", value)
    return re.sub(r"\s+", "", value.replace("$", "").replace(r"\times", "×"))


def _source(block: Any) -> str:
    return "\n".join(str(part) for part in (
        block.text, block.caption, block.table_body, *block.table_notes,
    ) if part)


def _locator_field(locator: Any, name: str) -> Any:
    return locator.get(name) if isinstance(locator, dict) else getattr(locator, name, None)


def _fraction_header(expression: str) -> bool:
    # Only explicit property / power, not Mw/Mn or a unit denominator.
    prop = r"[A-Za-zΔδ](?:[A-Za-z0-9_{}\\]+)?"
    power = r"10\^\{?[+-]?\d+\}?"
    return bool(re.fullmatch(prop + r"/" + power, expression)
                or re.fullmatch(r"\\frac\{" + prop + r"\}\{" + power + r"\}", expression))


def derive_numeric_value(item: Any, blocks: dict[str, Any]) -> dict[str, Any] | None:
    """计算派生量值，并检查脚注/倍率声明是否在所指原文中。"""
    semantics = item.value_semantics
    source_semantics = derive_source_semantics(item, blocks)
    annotation = {"derivation_version": DERIVATION_VERSION, "source_semantics": source_semantics}
    warnings = []
    if (getattr(item, "candidate_trace", None) or {}).get("original_scale_status") == "ambiguous_display_scale":
        warnings.append("candidate_scale_requires_review")
    for link in semantics.footnote_links if semantics else []:
        block = blocks.get(link.block_id)
        if block is None or _text(link.text_raw) not in _text(_source(block)):
            warnings.append("footnote_text_not_in_source")
    raw = (item.value_raw or "").strip().strip("$").strip()
    if re.search(r"[*†‡]$", raw) and any(n["status"] == "confirmed" and n["marker_raw"] == raw[-1]
                                        for n in source_semantics["footnote_associations"]):
        annotation["value_marker_raw"] = raw[-1]
        raw = raw[:-1].rstrip()
    elif re.search(r"[*†‡]$", raw) and any(n["status"]=="candidate" and n.get("anchor_marker_raw")==raw[-1]
                                             for n in source_semantics["footnote_associations"]):
        annotation["value_marker_raw"] = raw[-1]
        warnings.append("value_marker_unverified")
        raw = raw[:-1].rstrip()
    # 约数仍在原值及 qualifiers_raw 中；剥离前缀只用于派生数值。
    raw = re.sub(r"^\s*(?:about\s+|approximately\s+|approx\.\s*|ca\.\s*|[~≈]\s*)", "", raw, flags=re.I)
    embedded_percent = bool(re.search(r"(?:%|\\%)\s*$", raw))
    if embedded_percent:
        raw = re.sub(r"(?:\\?%)\s*$", "", raw).strip()
    parsed = parse_numeric(raw)
    # A single unspaced comma may be a decimal separator or two observations.
    # Model scalar bounds are only a candidate interpretation, not source proof.
    if re.fullmatch(r"[+-]?\d+,\d+", raw):
        decimal = float(raw.replace(",", "."))
        lo, hi = getattr(item, "value_min", None), getattr(item, "value_max", None)
        if lo == hi == decimal and literal_value_supported(item, blocks):
            parsed = parse_numeric(raw.replace(",", "."))
            annotation["numeric_interpretation"] = "decimal_comma_candidate"
        else:
            annotation["numeric_interpretation"] = "comma_list_or_decimal"
        warnings.append("comma_separator_requires_review")
    middle_decimal = parsed is None and bool(re.fullmatch(r"[+-]?\d+·\d+", raw))
    if middle_decimal and literal_value_supported(item, blocks):
        parsed = parse_numeric(raw.replace("·", "."))
        confirmed = _middle_dot_column(item, blocks, source_semantics["source_contexts"])
        if not confirmed: warnings.append("typographic_decimal_requires_review")
        annotation["numeric_interpretation"] = "middle_dot_decimal_confirmed" if confirmed else "middle_dot_decimal_candidate"
        if confirmed: annotation["numeric_interpretation_basis"] = confirmed
    parenthesized = False
    if parsed is None and raw.startswith("(") and raw.endswith(")"):
        parsed = parse_numeric(raw[1:-1].strip())
        parenthesized = parsed is not None
    if parsed is None:
        if "\ufffd" in raw:
            warnings.append("damaged_numeric_symbol")
        return {**annotation, "status": "not_numeric", "warnings": warnings}
    values = parsed["values"]
    factor = Decimal(1)
    status = "review_required" if warnings else "normalized"
    if parenthesized:
        status = "review_required"
        warnings.append("parenthesized_value_requires_review")
    scale = semantics.scale if semantics else None
    if scale is None:
        candidates = []
        for context in source_semantics["source_contexts"]:
            if context["scope"] != "table_header":
                continue
            expression = _text(context["text_raw"])
            powers = list(_POWER.finditer(expression))
            if len(powers) != 1:
                continue
            prefix, suffix = expression[:powers[0].start()], expression[powers[0].end():].lstrip(")}")
            unit_suffix = bool(re.match(r"(?:g/|kg/|J/|cal/|Pa|S/|Ω|ohm|Hz)", suffix))
            multiplier = bool(re.search(r"(?:×|x|·)\s*$", prefix, re.I))
            unit_prefix = prefix.count("(") > prefix.count(")") and unit_suffix
            relation = ("actual_equals_displayed_times_scale" if _fraction_header(expression) or unit_suffix and (not multiplier or unit_prefix)
                        else "displayed_equals_actual_times_scale" if multiplier and re.search(r"[A-Za-zΔδ]", prefix)
                        else "unknown")
            candidates.append(SimpleNamespace(expression_raw=context["text_raw"], source_block_id=context["block_id"],
                source_cell_id=context["source_cell_id"], relation=relation))
        if len(candidates) == 1:
            scale = candidates[0]
            annotation["scale_origin"] = "source_header"
        elif candidates:
            status = "review_required"
            warnings.append("multiple_header_scales")
    exponent = None
    if scale is not None:
        block = blocks.get(scale.source_block_id)
        expression = _text(scale.expression_raw)
        powers = list(_POWER.finditer(expression))
        if block is None or expression not in _text(_source(block)) or len(powers) != 1:
            return {**annotation, "status": "review_required", "warnings": warnings + ["scale_source_unverified"]}
        exponent = int(powers[0][1])
        if abs(exponent) > 30:
            return {**annotation, "status": "review_required", "warnings": warnings + ["scale_exponent_out_of_bounds"]}
        factor = Decimal(10) ** exponent
        prefix = expression[:powers[0].start()]
        basis = expression
        cells = {cell.cell_id: cell for cell in block.table_cells or []}
        anchor = cells.get(scale.source_cell_id)
        locators = [e.table_locator for e in item.evidence if e.table_locator is not None]
        # 模型可能只引用“×10^n”片段；方向由同一列的真实表头补充，不能靠全表猜。
        if (scale.relation != "repeated_cell_exponent" and anchor is not None
                and (anchor.is_header or anchor.row_index <= 2)
                and expression in _text(anchor.text) and locators
                and all(_locator_field(loc, "table_id") == block.block_id
                        and _locator_field(loc, "row_index") is not None
                        and _locator_field(loc, "row_index") > anchor.row_index
                        and _locator_field(loc, "column_index") is not None
                        and anchor.column_index <= _locator_field(loc, "column_index") < anchor.column_index + anchor.column_span
                        for loc in locators)):
            header = _text(anchor.text)
            header_powers = list(_POWER.finditer(header))
            if len(header_powers) == 1 and int(header_powers[0][1]) == exponent:
                basis = header
                prefix = header[:header_powers[0].start()]
        if scale.relation == "displayed_equals_actual_times_scale":
            # 性质/单位后的 ×10^n 表示所展示的性质乘了倍率。
            if not re.search(r"(?:×|x|·)\s*$", prefix, flags=re.I) or not re.search(r"[A-Za-zΔδ]", prefix):
                status = "review_required"
                warnings.append("scale_direction_unverified")
            factor = Decimal(1) / factor
        elif scale.relation == "actual_equals_displayed_times_scale":
            # 单位前缀 10^n unit 与“性质 ×10^n”不能混为同一方向。
            suffix = basis[list(_POWER.finditer(basis))[0].end():].lstrip(")}")
            unit_suffix = bool(re.match(r"(?:g/|kg/|J/|cal/|Pa|S/|Ω|ohm|Hz)", suffix))
            unit_prefix = prefix.count("(") > prefix.count(")") and unit_suffix
            if ((re.search(r"(?:×|x|·)\s*$", prefix, flags=re.I) and not unit_prefix) or not unit_suffix) and not (
                    _fraction_header(basis) and any(c["scope"] == "table_header" and _text(c["text_raw"]) == basis
                                                  for c in source_semantics["source_contexts"])):
                status = "review_required"
                warnings.append("scale_direction_unverified")
        elif scale.relation == "repeated_cell_exponent":
            cells = {cell.cell_id: cell for cell in block.table_cells or []}
            anchor = cells.get(scale.source_cell_id)
            locators = [e.table_locator for e in item.evidence if e.table_locator is not None]
            valid = anchor is not None and expression == _text(anchor.text)
            valid = valid and bool(locators) and all(
                _locator_field(locator, "table_id") == block.block_id
                and _locator_field(locator, "column_index") == anchor.column_index
                and _locator_field(locator, "row_index") is not None
                and _locator_field(locator, "row_index") > anchor.row_index
                for locator in locators
            )
            if valid:
                # 同列中间出现新指数便不能沿用更早的指数锚点。
                valid = not any(
                    anchor.row_index < cell.row_index < _locator_field(loc, "row_index")
                    and cell.column_index == anchor.column_index
                    and _POWER.search(_text(cell.text))
                    for loc in locators for cell in cells.values()
                )
            # 不能因前一行有指数就自动改后续值；保留候选供人工核对。
            status = "review_required"
            warnings.append("repeated_exponent_requires_review" if valid else "repeated_exponent_locator_unverified")
            if not valid or _POWER.search(_text(raw)):
                return {**annotation, "status": status, "warnings": warnings}
        else:
            return {**annotation, "status": "review_required", "warnings": warnings + ["scale_relation_unknown"]}
    actual = [float(value * factor) for value in values]
    if not all(math.isfinite(value) for value in actual):
        return {**annotation, "status": "review_required", "warnings": warnings + ["non_finite_derived_value"]}
    unit = item.unit_normalized or item.unit_raw
    headers = [plain(c["text_raw"]) for c in source_semantics["source_contexts"] if c["scope"] == "table_header"]
    percent_header = any(re.fullmatch(r"\s*[A-Z][a-z]?\s*%\s*", h) for h in headers)
    if percent_header:
        if unit and unit != "%":
            status = "review_required"
            warnings.append("raw_unit_header_conflict")
        unit = "%"
    if unit and ("\ufffd" in unit or re.search(r"\^[+-]?(?=$|[)\s])", _text(unit))):
        status = "review_required"
        warnings.append("damaged_unit_symbol_or_exponent")
    if not unit:
        from stages.stage4t_table_property import _unit_info
        header_sources = [c for c in source_semantics["source_contexts"] if c["scope"] == "table_header"]
        damaged_units = [c for c in header_sources if "\ufffd" in c["text_raw"]]
        unit_candidates = {info["unit_normalized"] for c in header_sources
                           if "\ufffd" not in c["text_raw"]
                           if (info := _unit_info([c["text_raw"]], None))["unit_location"] == "header"
                           and info["unit_normalized"]}
        unit_candidates.update(m[0].replace("mole", "mol") for h in headers
                               for m in re.finditer(r"\b(?:kcal|cal|kJ|J)/(?:mol|mole)\b", h))
        if len(unit_candidates) == 1:
            unit = next(iter(unit_candidates))
            annotation["unit_origin"] = {"scope":"table_header", "sources":header_sources}
        elif unit_candidates:
            status = "review_required"
            warnings.append("multiple_header_units")
        elif damaged_units:
            status = "review_required"
            warnings.append("damaged_header_unit")
    if embedded_percent:
        if unit and _text(unit).lower() not in {"%", "percent", "percentage"}:
            status = "review_required"
            warnings.append("embedded_percent_unit_conflict")
        unit = "%"
    if scale is not None and unit:
        unit = re.sub(r"(?:×|x|·)?10\^\{?[+-]?\d+\}?", "", _text(unit)).strip()
    result = {
        **annotation,
        "status": status, "actual_unit": unit,
        "numeric_kind": parsed["kind"], "scale_exponent": exponent,
        "scale_relation": scale.relation if scale else None,
        "scale_source_block_id": scale.source_block_id if scale else None,
        "scale_source_cell_id": scale.source_cell_id if scale else None,
        "warnings": warnings,
    }
    result["actual_values" if status == "normalized" else "candidate_values"] = actual
    if parsed.get("uncertainty") is not None:
        result["uncertainty"] = float(parsed["uncertainty"] * abs(factor))
    return result


def preserve_numeric_fields(candidate: Any, observation: Any, blocks: dict[str, Any]) -> Any:
    observation = observation.model_copy(update={
        "article_sample_key": candidate.article_sample_key,
        "value_semantics": candidate.value_semantics,
        "aggregate_relation_audit": getattr(candidate, "aggregate_relation_audit", None),
        "candidate_trace": getattr(candidate, "candidate_trace", None),
    })
    return observation.model_copy(update={"value_derivation": derive_numeric_value(observation, blocks)})
