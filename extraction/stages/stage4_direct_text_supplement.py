"""Source-exact text supplement within Stage 4; no evaluator/gold dependencies."""
from __future__ import annotations
import copy
import math
import re
from pathlib import Path

from schema.polymer_schema import PropertySeries
from stages.stage4_direct_table_supplement import scalar, plain, canonical_unit
from stages.source_control_escapes import decode_control_escapes, restore_source_control_spellings
from stages.stage4_table_footnote_supplement import table_footnote_facts
from stages.stage4_symbol_condition_binding import bind_symbol_conditions
from stages.source_crystallinity_fraction import normalize_crystallinity_fractions
from stages.source_unit_font_repair import repair_source_unit_fonts
from stages.source_linked_table_units import resolve_linked_table_units
from stages.source_thermal_criteria import bind_linked_thermal_criteria
from stages.source_compound_thermal_peaks import recover_compound_thermal_peaks
from stages.source_intervals import reported_interval

VERSION = "1.5.2"
PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts/stage4_direct_text_supplement.txt"


def text_requests(stage0: dict, max_chars: int = 22000) -> list[dict]:
    chunks, current, size = [], [], 0
    for e in stage0["elements"]:
        if e["type"] not in {"text", "footnote", "title", "equation"}:
            continue
        text = str(e.get("text") or "").strip()
        if not text:
            continue
        if e['type']=='equation' and not re.search(r'=\s*[+−-]?\s*\d',plain(text)):
            continue  # A symbolic formula is not a literal reported result.
        if re.search(r"references|bibliography", str(e.get("section") or ""), re.I):
            continue
        if current and size + len(text) > max_chars:
            chunks.append({"blocks": current})
            # A new numeric/equation block may depend on the preceding sample
            # heading. Carry bounded context; exact repeated facts are deduped.
            overlap=[b for b in current if b.get('block_type')!='equation'][-4:]
            current=[b for b in overlap if len(b['text'])<=1500]
            size=sum(len(b['text']) for b in current)
        current.append({"block_id": e["block_id"], "text": text, "block_type":e['type']})
        size += len(text)
    if current:
        chunks.append({"blocks": current})
    return [c for c in chunks if any(re.search(r'\d',b['text']) for b in c['blocks'])]


def covered_text_facts(stage4: dict, block_ids: set[str]) -> list[dict]:
    """Source-local coverage hints, never reference answers or scoring data.

    A hint is not a reason to suppress a different sample/property/condition.
    Keep the actual source quote so the model can distinguish those cases.
    """
    result, seen = [], set()
    records = [(p, p) for p in stage4.get('properties', [])]
    records += [(s, p) for s in stage4.get('property_series', []) for p in s.get('points', [])]
    for parent, point in records:
        for ev in point.get('evidence') or []:
            if ev.get('block_id') not in block_ids or not ev.get('source_sentence'):
                continue
            item = {'block_id': ev['block_id'],
                    'property_name': parent.get('property_name_normalized') or parent.get('property_name_raw'),
                    'value_raw': point.get('value_raw'),
                    'unit_raw': point.get('unit_raw') or parent.get('unit_raw'),
                    'source_quote': ev['source_sentence']}
            key = tuple(str(item[k]) for k in item)
            if key not in seen:
                seen.add(key); result.append(item)
    return result


def surface_key(text: str) -> str:
    return re.sub(r"\s+", "", plain(decode_control_escapes(text))).replace("−", "-")


def source_temperature_unit(unit: str | None, name: str, source: str) -> str | None:
    """Resolve a damaged superscript ONLY with independent same-block °C.

    Not a global control-character to degree mapping. Preserve unit_raw and
    disclose this contextual inference on the resulting measurement record.
    """
    if (unit and re.search(r'temperature', name, re.I)
            and re.fullmatch(r'<sup>\s*\x01\s*</sup>\s*C', decode_control_escapes(unit), re.I)
            and re.search(r'°\s*C\b', plain(source))):
        return '°C'
    return None


def text_fact_identity(block_id: str, name: str, raw: str, unit: str | None, label: str) -> tuple:
    """Merge synonymous repeats from overlapping chunks, not separate results."""
    normalized = re.sub(r'[^a-z0-9]+', ' ', plain(name).casefold()).strip()
    if re.fullmatch(r'weight average molecular weight(?: mw)?', normalized):
        normalized = 'weight average molecular weight'
    elif re.fullmatch(r'(?:molecular weight dispersity(?: mw mn)?|weight average to number average molecular weight ratio|polydispersity index)', normalized):
        normalized = 'molecular weight dispersity'
    return (block_id, normalized, surface_key(raw), surface_key(unit or ''), surface_key(label))


def parse_value(text: str, *, source_quote: str = "") -> float | None:
    result = scalar(text)
    if result is not None:
        return result
    clean = plain(text).replace("\\times", "×").replace("−", "-")
    # Space-separated numbers can be a list. Regroup only in a math fragment.
    # A printed quantity assignment can cross a TeX delimiter (e.g. $Mw:$
    # followed by 70 600). This is also a single literal, not a prose list.
    if re.fullmatch(r"[+\-\d.,\s]+", clean):
        for match in re.finditer(re.escape(clean), plain(source_quote)):
            prefix=plain(source_quote)[:match.start()]
            # A literal Unicode overbar is typography on the M symbol. It
            # does not separate an explicitly assigned molecular-weight value.
            prefix=re.sub(r'(?<=M)[\u0304\u0305]', '', prefix)
            suffix=plain(source_quote)[match.end():]
            if (re.search(r"(?<![A-Za-z])M\s*(?:_\s*)?[nwvz]?\s*[:=]\s*$",prefix,re.I)
                    and not re.match(r"\s*[\d+*/×]|\s*[.,]\d",suffix)):
                repaired=scalar(re.sub(r"\s+","",clean))
                if repaired is not None:return repaired
    math_fragments = re.findall(r"\$([^$]+)\$", source_quote)
    if (re.fullmatch(r"[+\-\d.,\s]+", clean)
            and any(surface_key(text) in surface_key(fragment) for fragment in math_fragments)):
        repaired = scalar(re.sub(r"\s+", "", clean))
        if repaired is not None:
            return repaired
    # Spaces between digits within a complete power-of-ten notation are OCR
    # typography, not two operands. The full expression must be supplied.
    m = re.fullmatch(r"\s*([+-]?\s*\d[\d\s]*(?:\.\s*[\d\s]+)?)\s*[×x·]\s*1\s*0\s*\^\s*([+-]?\s*\d[\d\s]*)\s*", clean)
    if m:
        mantissa=float(re.sub(r'\s+','',m[1]));exponent=int(re.sub(r'\s+','',m[2]))
        if abs(exponent)>308:return None
        value=mantissa * 10. ** exponent
        return value if math.isfinite(value) and (value!=0 or mantissa==0) else None
    return None


def numeric_part_with_declared_unit(raw: str, unit: str | None) -> str:
    """Model may retain the printed unit inside value_raw as well as unit_raw.

    Remove only an exact declared suffix for numeric parsing; retain the full
    original value_raw in output and verify it against source independently.
    """
    value_text,unit_text=plain(raw),plain(unit) if unit else ''
    if unit_text and value_text.endswith(unit_text):
        candidate=value_text[:-len(unit_text)].strip()
        if candidate:return candidate
    return raw


def equation_reports_literal_value(source: str, raw: str) -> bool:
    """Require a literal RHS, not a number picked out of a calculation."""
    source_key,raw_key=surface_key(source),surface_key(raw)
    for match in re.finditer('=' + re.escape(raw_key), source_key):
        tail=source_key[match.end():]
        if not re.match(r'[\d+*/×−-]|[.,]\d|\\(?:times|frac|cdot)(?![A-Za-z])',tail):
            return True
    return False


def scalar_is_range_endpoint(quote: str, raw: str) -> bool:
    """Do not turn a printed interval into separate measured scalar values.

    An explicitly named limit belongs in a range-aware schema, not this scalar
    supplement. A negative scalar and a comma-separated list remain eligible.
    """
    value = parse_value(raw, source_quote=quote)
    if value is None:
        return False
    text = plain(quote).replace('−', '-')
    text = re.sub(r'(?<=[\d.])\s+(?=[\d.])', '', text)
    number = r'[+-]?(?:\d+(?:\.\d+)?|\.\d+)'
    interval = rf'(?<![\d.])({number})\s*(?:–|—|-|\bto\b)\s*({number})(?![\d.])'
    for match in re.finditer(interval, text, re.I):
        if value in (float(match[1]), float(match[2])):
            return True
    return False


def scalar_is_inequality_bound(quote: str, raw: str) -> bool:
    value = parse_value(raw, source_quote=quote)
    if value is None:
        return False
    text = plain(quote).replace('−', '-')
    text = re.sub(r'(?<=[\d.])\s+(?=[\d.])', '', text)
    for match in re.finditer(r'(?<![\d.])[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?![\d.])', text):
        if float(match[0]) != value:
            continue
        prefix, suffix = text[:match.start()], text[match.end():]
        if re.search(r'(?:[<>≤≥]|\b(?:greater than|less than|more than|at least|at most|above|below|over|under))\s*$', prefix, re.I):
            return True
        if re.match(r'\s*[^\d.,;]{0,12}(?:以上|以下|未満)', suffix):
            return True
    return False


def text_evidence(element: dict, quote: str) -> dict:
    return {"block_id": element["block_id"], "page": element["page"], "bbox": element.get("bbox"),
            "source_type": element["type"], "source_sentence": quote}


def merge_text(stage4: dict, stage0: dict, responses: list[dict]) -> tuple[dict, dict]:
    output = copy.deepcopy(stage4)
    elements = {e["block_id"]: e for e in stage0["elements"]}
    existing = output.setdefault("property_series", [])
    retained_unit_repairs = []
    for series in existing:
        if len(series.get('points') or []) != 1:
            continue
        context = series.get('measurement_context') or {}
        if not (context.get('other_conditions') or {}).get('fact_role'):
            continue
        point = series['points'][0]
        for ev in point.get('evidence') or []:
            block = elements.get(ev.get('block_id'))
            if (not block or block['type'] not in {'text', 'footnote', 'equation'}
                    or not ev.get('source_sentence')
                    or surface_key(ev['source_sentence']) not in surface_key(block.get('text', ''))):
                continue
            raw_unit = point.get('unit_raw') or series.get('unit_raw')
            name = series.get('property_name_normalized') or series.get('property_name_raw') or ''
            repaired = source_temperature_unit(raw_unit, name, block.get('text', ''))
            if not repaired or point.get('unit_normalized') == repaired:
                continue
            retained_unit_repairs.append({'series_id': series['series_id'], 'point_id': point['point_id'],
                                          'unit_before': point.get('unit_normalized'), 'unit_after': repaired,
                                          'source_block_id': block['block_id']})
            for obj in (series, point):
                obj['unit_normalized'] = repaired
                conditions = obj.setdefault('measurement_context', {}).setdefault('other_conditions', {})
                conditions['unit_resolution_status'] = 'inferred_from_same_block_explicit_Celsius_unit'
                conditions['unit_raw_contains_ocr_control_artifact'] = 'true'
            break
    start = max([int(x["series_id"][6:]) for x in existing] or [0]) + 1
    audit, seen = [], set()
    # Replaying or supplementing an existing run must not duplicate an exact
    # same-source fact merely because this is another evolution round.
    for series in existing:
        context=series.get('measurement_context') or {}
        if not (context.get('other_conditions') or {}).get('fact_role'):continue
        name=str(series.get('property_name_normalized') or series.get('property_name_raw') or '')
        for point in series.get('points') or []:
            labels=[c.get('value_raw') for c in point.get('coordinates') or [] if c.get('name_raw')=='source sample label']
            for ev in point.get('evidence') or []:
                for label in labels:
                    seen.add(text_fact_identity(ev.get('block_id'), name, str(point.get('value_raw') or ''), point.get('unit_raw') or None, label))
    source_footnotes = table_footnote_facts(stage0)
    fact_batches = [[(fact, None) for fact in response.get('facts', [])] for response in responses]
    fact_batches.append(source_footnotes)
    for batch in fact_batches:
        for fact, footnote_binding in batch:
            block = elements.get(fact.get("block_id"))
            subject_block = elements.get(fact.get("sample_evidence_block_id"))
            quote, raw = str(fact.get("quote") or ""), str(fact.get("value_raw") or "")
            label, name = str(fact.get("sample_label") or ""), str(fact.get("property_name") or "")
            unit = fact.get("unit_raw") or None
            numeric_raw=numeric_part_with_declared_unit(raw,unit)
            role = fact.get("role")
            reason = None
            if block is None or subject_block is None or block["type"] not in {"text", "footnote", "equation"}:
                reason = "invalid_text_block"
            elif not quote or surface_key(quote) not in surface_key(block.get("text", "")):
                reason = "quote_not_in_source"
            elif not raw or not re.search(r"(?<![\d.])" + re.escape(surface_key(raw)) +
                    (r"(?!\d|\.\d)" if re.search(r'\d$',surface_key(raw)) else ''), surface_key(quote)):
                reason = "value_not_in_quote"
            elif not label or (footnote_binding is None and surface_key(label) not in surface_key(subject_block.get("text", ""))):
                reason = "sample_label_not_in_source"
            elif unit and surface_key(unit) not in surface_key(quote):
                reason = "unit_not_in_quote"
            elif role not in {"material_property", "measurement_criterion", "process_parameter"} or not name:
                reason = "invalid_role_or_property"
            elif scalar_is_range_endpoint(quote, numeric_raw):
                reason = "range_endpoint_is_not_a_scalar_observation"
            elif scalar_is_inequality_bound(quote, numeric_raw):
                reason = "inequality_is_not_an_exact_scalar"
            elif block['type']=='equation' and not equation_reports_literal_value(block.get('text',''),numeric_raw):
                reason = 'equation_is_not_a_literal_reported_value'
            value = parse_value(numeric_raw, source_quote=block.get('text','') if block and block['type']=='equation' else quote) if not reason else None
            interval = reported_interval(numeric_raw) if not reason and value is None else None
            if interval:value=interval['minimum']
            if value is None:
                reason = reason or "not_scalar"
            if reason:
                audit.append({"accepted": False, "reason": reason, "fact": fact}); continue
            key = text_fact_identity(block["block_id"], name, raw, unit, label)
            if key in seen:
                audit.append({"accepted": False, "reason": "duplicate_same_source_fact", "fact": fact})
                continue
            seen.add(key)
            source_text = block.get('text', '')
            quote = restore_source_control_spellings(quote, source_text)
            if unit:
                unit = restore_source_control_spellings(unit, source_text)
            ev = text_evidence(block, quote)
            subject_ev = footnote_binding['subject_evidence'] if footnote_binding else text_evidence(subject_block, label)
            context = {"condition_status": "reported", "other_conditions": {"fact_role": role,
                "confidence_status": "not_estimated", "required_score_placeholder": "0.0"}}
            if numeric_raw!=raw:
                context['other_conditions']['source_literal_unit_embedded']='true; original value_raw retained'
            if interval:
                context['other_conditions']['value_semantics']='reported_'+interval['kind']
                if interval['inequality']:context['other_conditions']['reported_inequality']=interval['inequality']
            if footnote_binding:
                context['other_conditions'].update({k: v for k, v in footnote_binding.items() if k != 'subject_evidence'})
                context['other_conditions']['source_binding_method'] = 'unique_table_footnote_marker'
            repaired_unit = source_temperature_unit(unit, name, source_text)
            normalized_unit = repaired_unit or canonical_unit(unit)
            if repaired_unit:
                context['other_conditions']['unit_resolution_status'] = 'inferred_from_same_block_explicit_Celsius_unit'
                context['other_conditions']['unit_raw_contains_ocr_control_artifact'] = 'true'
            origin=fact.get('reported_origin')
            if origin in {'this_study','reported_comparison','not_specified'}:
                context['other_conditions']['reported_origin']=origin
            condition = str(fact.get("conditions") or "")
            if condition and surface_key(condition) in surface_key(block.get("text", "")):
                context["other_conditions"]["source_context"] = condition
            elif condition:
                audit.append({"accepted": False, "reason": "condition_text_not_verbatim_not_attached", "fact": fact})
            record = {"series_id": f"series{start:03d}", "sample_id": None, "entity_id": None,
                "sample_resolution_status": "unresolved", "property_name_raw": name,
                "property_name_normalized": name, "unit_raw": unit, "unit_normalized": normalized_unit,
                "measurement_context": context,
                "points": [{"point_id": "pt001", "sample_id": None, "entity_id": None,
                    "sample_resolution_status": "unresolved", "coordinates": [
                        {"name_raw": "source sample label", "value_raw": label, "unit_raw": None, "evidence": subject_ev}],
                    "value_raw": raw, "value_min": value, "value_max": interval['maximum'] if interval else value,
                    "unit_raw": unit, "unit_normalized": normalized_unit, "measurement_context": context,
                    "coverage_status": "covered", "evidence": [ev], "confidence": {"score": 0.0}}],
                "coverage": {"expected": 1, "covered": 1, "missing": 0, "not_applicable": 0, "ratio": 1.0},
                "evidence": [ev], "confidence": {"score": 0.0}}
            existing.append(PropertySeries.model_validate(record).model_dump(mode="json")); start += 1
            audit.append({"accepted": True, "reason": "unique_table_footnote" if footnote_binding else "direct_source_text", "fact": fact})
    output.setdefault("warnings", []).append({"stage": "stage4_direct_text_supplement", "code": "direct_text_facts_added",
        "message": "Literal text facts added with declared material-property/measurement-criterion/process-parameter roles; global sample binding remains unresolved. Confidence is not estimated; 0.0 is a required-schema placeholder, not a correctness probability or release criterion.",
        "confidence_status": "not_estimated", "required_score_placeholder": 0.0})
    symbol_audit = bind_symbol_conditions(output, stage0)
    fraction_audit = normalize_crystallinity_fractions(output, stage0)
    font_audit = repair_source_unit_fonts(output, stage0)
    linked_unit_audit = resolve_linked_table_units(output, stage0)
    linked_criterion_audit = bind_linked_thermal_criteria(output, stage0)
    compound_peak_audit = recover_compound_thermal_peaks(output, stage0)
    return output, {"version": VERSION, "decisions": audit, "retained_unit_repairs": retained_unit_repairs,
                    "symbol_condition_binding": symbol_audit, "crystallinity_fraction_normalization": fraction_audit,
                    "unit_font_repair": font_audit, "linked_table_units": linked_unit_audit,
                    "linked_thermal_criteria": linked_criterion_audit,
                    "compound_thermal_peaks": compound_peak_audit}
