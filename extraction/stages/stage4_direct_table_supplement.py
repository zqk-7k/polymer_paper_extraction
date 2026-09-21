"""Source-only Stage 4 table completeness pass; no gold or evaluator imports.

The model selects source cell IDs and interprets headings. Numeric values are
read deterministically from those cells. Source-labelled series are retained
without pretending an ambiguous global sample binding has been resolved.
"""
from __future__ import annotations

import copy
import hashlib
import html
import json
import math
import re
from pathlib import Path
from typing import Any

from schema.polymer_schema import PropertySeries, Stage0Document
from stages.table_grid import table_cells_for
from stages.stage4t_table_property import _conductivity_display_scale, _reciprocal_ohm_cm_unit
from stages.source_number_literals import scientific_literal
from stages.source_intervals import reported_interval

VERSION = "1.13.1"
PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts/stage4_direct_table_supplement.txt"
_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"


def plain(value: Any) -> str:
    text = html.unescape(str(value or ""))
    # OCR may wrap a printed unit in an empty-denominator layout fraction.
    # Remove that wrapper only; real fractions retain their denominator.
    text = re.sub(r'\\frac\s*\{([^{}]*)\}\s*\{\s*\}', r'\1', text)
    # Preserve printed superscript exponents before removing HTML markup.
    text = re.sub(r"<sup>\s*([+-]?\d+)\s*</sup>", r"^\1", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\\(?:text|mathrm|textrm|overline|bar)\s*\{([^{}]*)\}", r"\1", text)
    text = text.replace("\\cdot", "·").replace("\\eta", "η").replace("\\theta", "θ")
    text = text.replace("\\circ", "°").replace("\\mu", "μ").replace("\\AA", "Å")
    return re.sub(r"\s+", " ", text.replace("$", "").replace("{", "").replace("}", "")).strip()


def scalar(surface: str) -> float | None:
    text = plain(surface).replace("−", "-").replace("–", "-")
    text = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", text)
    match = re.fullmatch(rf"\s*({_NUMBER})(?:\s*(?:±|\\pm)\s*{_NUMBER})?\s*", text)
    if not match:
        return scientific_literal(text)
    value = float(match.group(1))
    return value if math.isfinite(value) else None


def table_cell_scalar(surface: str) -> float | None:
    """Full-cell thousands typography, never used by the prose parser."""
    text=plain(surface)
    approximate = re.fullmatch(rf'(?:~|≈|\\sim|\\approx)\s*({_NUMBER})', text)
    if approximate:
        return scalar(approximate[1])
    if re.fullmatch(r'[+−-]\s+\d+(?:\.\d+)?', text):
        return scalar(re.sub(r'\s+', '', text))
    if re.fullmatch(rf'—{_NUMBER}', text):
        return scalar('-' + text[1:])
    if re.fullmatch(r'[+-]?\d{1,3}(?:\s+\d{3})+(?:\.\d+)?',text):
        return scalar(re.sub(r'\s+','',text))
    return scalar(surface)


def inline_contact_angle(surface: str, name: str, caption: str) -> dict | None:
    """Read explicit degree-marked contact-angle cells, preserving bounds/notes."""
    if not (re.search(r'contact[ -]?angle', name, re.I)
            and re.search(r'contact[ -]?angles?', plain(caption), re.I)):
        return None
    text=plain(surface).replace('^°','°').replace(r'\sim','~').replace('−','-')
    numeric=rf'(?:[<>≤≥]=?\s*)?{_NUMBER}(?:\s*(?:~|–|—|to)\s*{_NUMBER})?'
    match=re.fullmatch(rf'\s*({numeric})\s*°\s*([a-z]\)?)?\s*',text)
    if not match:return None
    raw=match[1].strip();interval=reported_interval(raw);value=scalar(raw)
    if interval is None and value is None:return None
    if interval is None:interval={'minimum':value,'maximum':value,'kind':'scalar','inequality':None}
    if not 0 <= interval['minimum'] <= interval['maximum'] <= 180:return None
    return {**interval,'raw':raw,'unit':'degree','marker':match[2] or ''}


def middle_dot_decimal_value(cell: dict, cells: dict) -> float | None:
    """Historical decimal typography, corroborated within one table column."""
    pattern = r'[+−-]?\d+·\d{1,6}'
    text = plain(cell['text'])
    if not re.fullmatch(pattern, text):
        return None
    peers = [c for c in cells.values() if c['column_index'] == cell['column_index']
             and re.fullmatch(pattern, plain(c['text']))]
    if len(peers) < 2:
        return None
    return float(text.replace('·', '.').replace('−', '-'))


def table_reported_interval(surface: str, name: str, header: str = '') -> dict | None:
    result = reported_interval(surface)
    if result:
        return result
    # Historical thermal tables use an ASCII hyphen for a melting/softening
    # interval. Only a complete two-endpoint cell under a thermal property is
    # accepted; arbitrary prose subtraction and range endpoints stay rejected.
    if not re.search(r'temperature|melting|softening|T_?[mgc](?![A-Za-z])', name+' '+plain(header), re.I):
        return None
    m = re.fullmatch(rf'\s*({_NUMBER})\s*-\s*({_NUMBER})\s*', plain(surface))
    return reported_interval(m[1]+'–'+m[2]) if m else None


def footnoted_thermal_components(surface: str, name: str, notes: str) -> list[dict]:
    if not re.search(r'melting|T_?m(?![A-Za-z])', name, re.I):
        return []
    text = plain(surface)
    pattern = rf'({_NUMBER}(?:\s*,\s*{_NUMBER})*)\s*\^([a-z])\)?'
    matches = list(re.finditer(pattern, text))
    if not matches or re.sub(pattern, '', text).strip():
        return []
    # Every marker must have its own printed endotherm definition. A number
    # followed by a letter is never enough to infer a peak or processing state.
    definitions = {}
    for marker in {m[2] for m in matches}:
        found = re.search(r'(?:^|\n)\s*(?:\^)?'+re.escape(marker)+r'\)\s*([^\n]+)', plain_lines(notes), re.I)
        if not found or not re.search(r'endotherm', found[1], re.I):
            return []
        definitions[marker] = found[1]
    result = []
    for m in matches:
        for i, raw in enumerate(re.split(r'\s*,\s*', m[1])):
            result.append({'raw':raw, 'value':float(raw), 'role':f'footnote_{m[2]}_peak_{i+1}',
                'binding_method':'source_footnote_defines_thermal_endotherm',
                'source_footnote_definition':definitions[m[2]]})
    return result


def plain_lines(text: str) -> str:
    return '\n'.join(plain(line) for line in str(text).splitlines())


def inline_glass_peaks(surface: str, property_name: str) -> list[dict]:
    """Explicit Tg1=..., Tg2=... labels are separate reported peaks, not a range."""
    if not re.search(r'glass.?transition|T_?g', property_name, re.I):
        return []
    text = re.sub(r'\s+', '', plain(surface))
    pattern = rf'T_?g_?([1-9])=({_NUMBER})'
    matches = list(re.finditer(pattern, text, re.I))
    if not 2 <= len(matches) <= 8 or len({m[1] for m in matches}) != len(matches):
        return []
    if re.sub(pattern, '', text, flags=re.I).strip(',;'):
        return []
    return [{'role': 'Tg' + m[1], 'raw': m[2], 'value': float(m[2])} for m in matches]


def inline_heat_capacity_components(surface: str, property_name: str) -> list[dict]:
    """Read fully printed phase-labelled increments, never infer a heat capacity."""
    if not re.search(r'heat.?capacity|specific.?heat|C_?p', property_name, re.I):
        return []
    text = re.sub(r'\\+Delta\b', 'Δ', plain(surface))
    text = re.sub(r'\s+', '', text)
    pattern = rf'ΔC_?p_?([1-9])=({_NUMBER})'
    matches = list(re.finditer(pattern, text, re.I))
    if not 2 <= len(matches) <= 8 or len({m[1] for m in matches}) != len(matches):
        return []
    if re.sub(pattern, '', text, flags=re.I).strip(',;'):
        return []
    return [{'role': 'DeltaCp' + m[1], 'raw': m[2], 'value': float(m[2]),
             'binding_method': 'explicit_inline_heat_capacity_increment_label'} for m in matches]


def power_header(surface: str) -> str:
    """Normalize printed exponent typography without treating plain 103 as 10^3."""
    superscripts = str.maketrans('⁺⁻⁰¹²³⁴⁵⁶⁷⁸⁹', '+-0123456789')
    text = re.sub('[⁺⁻⁰¹²³⁴⁵⁶⁷⁸⁹]+', lambda m: '^' + m[0].translate(superscripts), str(surface))
    return plain(text).replace('−', '-').replace('⁻', '-')


def has_display_exponent(header: str, exponent: int) -> bool:
    return bool(re.search(rf'10\s*\^\s*{exponent}(?!\d)', power_header(header)))


def header_declared_peaks(surface: str, header: str, source_notes: str = '') -> list[dict]:
    """Semicolon-separated literals only when the source declares thermal peaks."""
    heading = plain(header)
    double = bool(re.search(r'\b(?:double|dual|two|multiple)\s+(?:thermal\s+)?transitions\b',
                            plain(source_notes), re.I))
    thermal = bool(re.search(r'glass\s+transition|crystallization|melting|fusion', heading, re.I))
    slash = '/' in plain(surface) and double and thermal
    if not ((slash or (re.search(r'\bpeaks\b', heading, re.I)
            and re.search(r'fusion|melting', heading, re.I)
            )) and re.search(r'°\s*C', heading)):
        return []
    parts = [x.strip() for x in plain(surface).split('/' if slash else ';')]
    if not 2 <= len(parts) <= 4 or not all(re.fullmatch(_NUMBER, x) for x in parts):
        return []
    values = [float(x) for x in parts]
    if len(set(values)) != len(values) or not all(math.isfinite(x) for x in values):
        return []
    return [{'role': f'reported_peak_{i+1}', 'raw': raw, 'value': value,
             'binding_method': ('source_caption_declares_double_transitions' if slash else
                                'source_header_declares_multiple_melting_peaks')}
            for i, (raw, value) in enumerate(zip(parts, values))]


def caption_defines_property(table: dict, group: dict) -> bool:
    """Require an actual multi-word property phrase copied from this caption.

    The per-point gate additionally requires orthogonal subject/condition axes.
    This never infers units or borrows a unit from a different table column.
    """
    raw = plain(group.get('property_name_raw', '')).casefold()
    return len(raw) >= 8 and len(raw.split()) >= 2 and caption_contains_phrase(raw, table.get('caption', ''))


def caption_contains_phrase(quote: str, caption: str) -> bool:
    """A material/property token must not be cut from a longer named token."""
    return bool(quote and re.search(r'(?<![\w-])'+re.escape(plain(quote))+r'(?![\w-])',
        plain(caption),re.I))


def decimal_comma_value(cell: dict, cells: dict) -> float | None:
    """Use comma decimals only when the source response column repeats them.

    Exactly one or two fractional digits avoids confusing a comma-thousands
    group with a decimal. Chemical formulae and multi-number lists are rejected.
    """
    pattern=r'[+-]?\d+,\d{1,2}'
    text=plain(cell['text'])
    if not re.fullmatch(pattern,text):return None
    peers=[c for c in cells.values() if c['column_index']==cell['column_index']
           and re.fullmatch(pattern,plain(c['text']))]
    if len(peers)<2:return None
    return float(text.replace(',','.'))


def footnoted_scalar(surface: str, source_notes: str) -> tuple[float | None, str | None]:
    """Strip a trailing letter ONLY if that footnote is explicitly declared."""
    value = scalar(surface)
    if value is not None:
        return value, None
    match = re.fullmatch(rf"\s*({_NUMBER})\s*\^?\s*([a-z*])\s*", plain(surface))
    if not match:
        return None, None
    marker = match[2]
    escaped = re.escape(marker)
    declared = (re.search(r"\^\s*\{\s*" + escaped + r"\s*\}", source_notes)
                or re.search(r"<sup>\s*" + escaped + r"\s*</sup>", source_notes)
                or re.search(r"(?:^|\n)\s*" + escaped + r"[).]\s+", source_notes)
                or (marker == '*' and re.search(r'(?:^|\n)\s*\*\s+[A-Za-z]', source_notes)))
    return (scalar(match[1]), marker) if declared else (None, None)


def canonical_unit(surface: Any) -> str | None:
    """Typography normalization only: no inferred unit or value conversion."""
    # Font directives carry no unit semantics, including nested/double braces.
    # Keep mathematical commands/exponents (e.g. \hat or citation digits) intact.
    unstyled = re.sub(r'\\(?:mathrm|mathbf|textrm|mathsf|mathtt|mathit|text)\b\s*', '', str(surface or ''))
    text = power_header(unstyled).strip().rstrip(".,;").replace("℃", "°C").replace("º", "°")
    # In a TeX unit expression, ~ is a non-breaking space, not part of the unit.
    if re.search(r"\\(?:mathrm|text|textrm)\b", str(surface or '')):
        text = text.replace('~', '')
    text = text.replace("\\", "").replace(" ", "").replace("^", "")
    if text.casefold() in {'å', 'ångström', 'ångstrom', 'angstroem'}:
        return 'angstrom'
    if text in {"degree", "degrees", "deg"}:
        return "degree"
    if text in {"dL·g-1", "dLg-1", "dL/g"}:
        return "dL/g"
    return text or None


def declared_footnote(marker: str, notes: str) -> bool:
    return bool(re.search(r'\^\s*\{\s*'+re.escape(marker)+r'\s*\}',notes)
                or re.search(r'<sup>\s*'+re.escape(marker)+r'\s*</sup>',notes,re.I)
                or re.search(r'(?:^|\n)\s*'+re.escape(marker)+r'[).]\s+',notes))


def unit_in_header(unit: str, header: str, source_notes: str = '') -> bool:
    candidate = canonical_unit(unit) or ""
    source = power_header(header)
    # OCR commonly represents a degree symbol as superscript o. Only accept
    # this explicit typographic form, not an arbitrary letter o in prose.
    source = re.sub(r"\^\s*o\s*([CF])\b", r"°\1", source)
    source = source.replace("^", "").replace("\\", "").replace("℃", "°C")
    # Preserve real word boundaries before the legacy compact-typography pass.
    # Otherwise 'char wt % at 700 °C' becomes 'charwt%at700°C' and rejects
    # its explicitly printed unit. Do not match a unit inside an ordinary word.
    spaced_source=source.replace("dL·g-1", "dL/g").replace("dLg-1", "dL/g")
    if candidate and candidate not in {"°C", "°F", "angstrom", "degree", "°"}:
        unit_pattern=r'\s*'.join(re.escape(c) for c in candidate)
        if re.search(r'(?<![A-Za-z])'+unit_pattern+r'(?![A-Za-z])',spaced_source,re.I):
            return True
    source = re.sub(r"\s+", "", source).replace("dL·g-1", "dL/g").replace("dLg-1", "dL/g")
    if candidate in {"°C", "°F"}:
        if re.search(re.escape(candidate) + r"(?![A-Za-z])", source):return True
        # A detached superscript footnote can be flattened to e.g. °Ca.
        # Accept it only when that exact marker is declared in source notes.
        match=re.search(re.escape(candidate)+r'([a-z])(?![A-Za-z])',source)
        return bool(match and declared_footnote(match[1],source_notes))
    if candidate == 'angstrom':
        return bool(re.search(r'Å|angstrom|ångström|ångstrom|angstroem', source, re.I))
    if candidate in {"degree", "°"}:
        return bool(re.search(r"°(?![CFK])", source, re.I)) or bool(re.search(r"\bdegrees?\b", plain(header), re.I))
    return bool(re.search(r"(?<![A-Za-z])" + re.escape(candidate) + r"(?![A-Za-z])", source, re.I))


def header_applies(header: dict, response: dict) -> bool:
    hr, hc = int(header['row_index']), int(header['column_index'])
    vr, vc = int(response['row_index']), int(response['column_index'])
    rs, cs = int(header.get('row_span') or 1), int(header.get('column_span') or 1)
    certified=header.get('_pdf_verified_header_columns')
    if certified and hr < vr and vc in certified:
        return True
    return (hr < vr and hc <= vc < hc + cs) or (hc < vc and hr <= vr < hr + rs)


def attach_verified_header_scopes(cells: list[dict], table_id: str, stage0: dict) -> None:
    """Use a PDF-reviewed header scope without inventing table-grid geometry."""
    notes=stage0.get('ocr',{}).get('source_header_scope_review',{})
    if (notes.get('version')!='pdf-header-scope/1.0.0' or notes.get('predictions_accessed') is not False
            or notes.get('reference_values_accessed') is not False):return
    by_id={c['cell_id']:c for c in cells};available={c['column_index'] for c in cells}
    accepted={}
    for item in notes.get('scopes',[]):
        if item.get('table_id')!=table_id or item.get('review_method')!='codex_pdf_visual':continue
        if not re.fullmatch('[a-f0-9]{64}',item.get('source_image_sha256','')):continue
        h=by_id.get(item.get('header_cell_id'));cols=item.get('applies_to_columns')
        if not h or h['text']!=item.get('exact_header_text') or h['row_index']>1:continue
        if not isinstance(cols,list) or not cols or any(type(x)!=int or x not in available for x in cols):continue
        accepted.setdefault(h['cell_id'],set()).add((tuple(sorted(set(cols))),item['source_image_sha256']))
    for cid,scopes in accepted.items():
        # Conflicting source certificates never use last-write-wins semantics.
        if len(scopes)!=1:continue
        cols,digest=next(iter(scopes))
        by_id[cid]['_pdf_verified_header_columns']=list(cols)
        by_id[cid]['_pdf_verified_header_image_sha256']=digest


def table_requests(stage0: dict) -> list[dict]:
    document = Stage0Document.model_validate(stage0)
    elements = document.elements
    result = []
    for index, table in enumerate(elements):
        if table.type != "table":
            continue
        cells = [cell.model_dump(mode="json") for cell in table_cells_for(table)]
        attach_verified_header_scopes(cells,table.block_id,stage0)
        if not any(table_cell_scalar(cell["text"]) is not None or reported_interval(plain(cell['text'])) for cell in cells):
            continue
        nearby = []
        for element in elements[max(0, index - 2):index + 3]:
            if element.type in {"text", "footnote"} and element.text:
                nearby.append(element.text[:5000])
        result.append({
            "table_id": table.block_id, "caption": table.caption or "",
            "nearby_prose": nearby, "cells": cells,
            "page": table.page, "bbox": table.bbox,
        })
    return result


def evidence(table: dict, cell: dict, *, row_label: str, column_label: str) -> dict:
    return {
        "block_id": table["table_id"], "page": table["page"], "bbox": table.get("bbox"),
        "source_type": "table", "source_sentence": cell["text"],
        "table_locator": {
            "table_id": table["table_id"], "cell_id": cell["cell_id"],
            "row_index": cell["row_index"], "column_index": cell["column_index"],
            "row_label": row_label, "column_label": column_label, "cell_value": cell["text"],
        },
    }


def caption_subject(table: dict, point: dict) -> str | None:
    """Retain a verbatim caption material, never manufacture a subject cell.

    This is a source-local model attribution, not a resolved global sample.
    The separate scope declaration prevents accidental use of old free text.
    """
    if point.get('subject_cell_ids') or point.get('subject_caption_scope') != 'single_material_table':
        return None
    quote = plain(point.get('subject_caption_quote'))
    if len(quote) < 4 or not re.search(r'[A-Za-z\u3040-\u30ff\u4e00-\u9fff]', quote):
        return None
    if quote not in plain(table.get('caption')) or not caption_contains_phrase(quote, table.get('caption','')):
        return None
    if quote.casefold() in {'sample', 'samples', 'polymer', 'polymers', 'properties', 'table',
                            'material', 'materials', 'system', 'systems', 'copolymer', 'copolymers'}:
        return None
    return quote


def source_unit(unit: Any, header: str, caption: str) -> str | None:
    """Historical printed A. means angstrom only for a named X-ray d column."""
    normalized = canonical_unit(unit)
    if (normalized == 'A' and re.fullmatch(r'd\s*[,(/]\s*A\.?\s*\)?', plain(header))
            and re.search(r'x[ -]?ray\s+(?:reflections?|diffraction)', plain(caption), re.I)):
        return 'angstrom'
    return normalized


def materialize(table: dict, response: dict, start_id: int) -> tuple[list[dict], list[dict]]:
    cells = {cell["cell_id"]: cell for cell in table["cells"]}
    series, audit, seen = [], [], set()
    claims: dict[str, set[str]] = {}
    assignments: dict[str, set[tuple]] = {}
    response_rows = []
    source_notes=table.get('caption','')+'\n'+'\n'.join(table.get('nearby_prose') or [])
    for group in response.get('groups', []):
        for point in group.get('points', []):
            cid = point.get('cell_id')
            if cid in cells:
                claims.setdefault(cid, set()).add(str(group.get('property_name_normalized') or group.get('property_name_raw') or '').casefold())
                assignments.setdefault(cid, set()).add((tuple(point.get('subject_cell_ids') or []), tuple(point.get('condition_cell_ids') or []), caption_subject(table, point)))
                response_rows.append(cells[cid]['row_index'])
    first_data_row = min(response_rows, default=0)
    for group in response.get("groups", []):
        header_ids = group.get("header_cell_ids") or []
        if not header_ids or any(cid not in cells for cid in header_ids):
            audit.append({"accepted": False, "reason": "invalid_header_ids", "group": group})
            continue
        header = " | ".join(cells[cid]["text"] for cid in header_ids)
        caption_scope = caption_defines_property(table, group)
        raw = str(group.get("property_name_raw") or "").strip()
        name = str(group.get("property_name_normalized") or raw).strip()
        if not raw or not name:
            continue
        exponent = group.get("scale_exponent") or 0
        if isinstance(exponent, bool) or not isinstance(exponent, int) or abs(exponent) > 12:
            audit.append({"accepted": False, "reason": "invalid_scale", "group": group})
            continue
        if exponent and not has_display_exponent(header, exponent):
            audit.append({"accepted": False, "reason": "scale_not_in_header", "group": group})
            continue
        unit = group.get("unit_raw") or None
        angle_group = (canonical_unit(unit) in {'degree','°'} and
                       any(inline_contact_angle(cells[p['cell_id']]['text'],name,table.get('caption',''))
                           for p in group.get('points',[]) if p.get('cell_id') in cells))
        # A unit must be present in the source heading, modulo typography.
        if unit and not unit_in_header(unit, header, source_notes) and not angle_group:
            audit.append({"accepted": False, "reason": "unit_not_in_header", "group": group})
            continue
        points = []
        group_evidence = []
        for point in group.get("points", []):
            cid = point.get("cell_id")
            subjects = point.get("subject_cell_ids") or []
            caption_label = caption_subject(table, point)
            requested_conditions = point.get("condition_cell_ids") or []
            blank_conditions=[x for x in requested_conditions if x in cells and not str(cells[x]['text']).strip()]
            # A blank source coordinate supplies no condition evidence. Keep a
            # trace of the missing cell, but never fabricate text or abort all
            # other tables in this paper over an empty schema string.
            conditions = [x for x in requested_conditions if x not in blank_conditions]
            angle = inline_contact_angle(cells[cid]['text'],name,table.get('caption','')) if angle_group and cid in cells else None
            reason = None
            if cid not in cells or not (subjects or caption_label) or any(x not in cells for x in subjects + conditions):
                reason = "invalid_cell_or_subject"
            elif cid in subjects or cid in conditions or cid in header_ids:
                reason = "response_is_header_or_coordinate"
            elif len(claims.get(cid, set())) > 1:
                reason = "source_cell_has_conflicting_property_claims"
            elif len(assignments.get(cid, set())) > 1:
                reason = "source_cell_has_conflicting_subject_or_state"
            elif any(not str(cells[x]["text"]).strip() for x in subjects):
                reason = "empty_subject"
            elif not any(header_applies(cells[h], cells[cid]) for h in header_ids) and not (
                caption_scope and any(header_applies(cells[s], cells[cid]) for s in subjects)
                and any(header_applies(cells[c], cells[cid]) for c in conditions)
            ):
                reason = "property_header_not_on_response_axis"
            elif unit and not unit_in_header(unit, ' | '.join(
                cells[h]['text'] for h in header_ids if header_applies(cells[h], cells[cid])
            ), source_notes) and not angle:
                reason = "unit_header_does_not_apply_to_response"
            elif exponent and not any(
                header_applies(cells[h], cells[cid]) and has_display_exponent(cells[h]['text'], exponent)
                for h in header_ids
            ):
                reason = "scale_header_does_not_apply_to_response"
            value, footnote = (None, None) if reason else footnoted_scalar(
                cells[cid]["text"], table.get('caption','') + '\n' + '\n'.join(table.get('nearby_prose') or []))
            comma_decimal=False
            if not reason and value is None:
                value=table_cell_scalar(cells[cid]['text'])
            if not reason and value is None:
                value=decimal_comma_value(cells[cid],cells)
                comma_decimal=value is not None
            middle_dot_decimal = False
            if not reason and value is None:
                value = middle_dot_decimal_value(cells[cid], cells)
                middle_dot_decimal = value is not None
            interval_surface=plain(cells[cid]['text']) if cid in cells else ''
            reported_decomposition=False
            if not reason and re.search(r'melting|softening',name,re.I) and re.search(r'\s*\(dec\.?\)\s*$',interval_surface,re.I):
                interval_surface=re.sub(r'\s*\(dec\.?\)\s*$','',interval_surface,flags=re.I)
                reported_decomposition=True
            interval = table_reported_interval(interval_surface, name, header) if not reason and value is None else None
            if not reason and value is None and angle:
                value=angle['minimum']
                interval=angle if angle['kind']!='scalar' else None
            if interval:
                value=interval['minimum']
            components = inline_glass_peaks(cells[cid]['text'], name) if not reason and value is None else []
            if not reason and value is None and not components:
                components = inline_heat_capacity_components(cells[cid]['text'], name)
            if not reason and value is None and not components:
                components = header_declared_peaks(cells[cid]['text'], ' | '.join(
                    cells[h]['text'] for h in header_ids if header_applies(cells[h], cells[cid])),
                    table.get('caption',''))
            if not reason and value is None and not components:
                components = footnoted_thermal_components(cells[cid]['text'], name,
                    table.get('caption','')+'\n'+'\n'.join(table.get('nearby_prose') or []))
            if components:
                value = components[0]['value']
            if value is None:
                reason = reason or "not_direct_scalar"
            if reason:
                audit.append({"accepted": False, "reason": reason, "point": point, "property": name})
                continue
            key = (cid, name, tuple(subjects), tuple(conditions))
            if key in seen:
                continue
            seen.add(key)
            label = " | ".join(cells[x]["text"] for x in subjects) or caption_label
            ev = evidence(table, cells[cid], row_label=label, column_label=header)
            coords = [{"name_raw": "source sample label", "value_raw": cells[x]["text"],
                       "unit_raw": None, "evidence": evidence(table, cells[x], row_label=label, column_label="sample")}
                      for x in subjects]
            if caption_label:
                coords.append({'name_raw': 'source material in table caption', 'value_raw': caption_label,
                    'unit_raw': None, 'evidence': {'block_id': table['table_id'], 'page': table['page'],
                    'bbox': table.get('bbox'), 'source_type': 'table', 'source_sentence': caption_label}})
            coords += [{"name_raw": "source condition/state", "value_raw": cells[x]["text"],
                        "unit_raw": None, "evidence": evidence(table, cells[x], row_label=label, column_label="condition")}
                       for x in conditions]
            context = {"condition_status": "reported", "other_conditions": {
                "confidence_status": "not_estimated", "required_score_placeholder": "0.0",
                "source_property_header": header,
                "source_subject_binding_scope": "table-local labels retained; canonical sample identity unresolved",
                **({"source_caption": table["caption"]} if table.get("caption") else {}),
                **({"source_condition_state": " | ".join(cells[x]["text"] for x in conditions)} if conditions else {}),
            }}
            if comma_decimal:
                context['other_conditions']['source_numeric_typography']='decimal comma corroborated by repeated source-column values'
            if blank_conditions:
                context['other_conditions']['source_blank_condition_cell_ids']=json.dumps(blank_conditions)
            if middle_dot_decimal:
                context['other_conditions']['source_numeric_typography']='decimal middle dot corroborated by repeated source-column values'
            if caption_scope:
                context['other_conditions']['source_property_definition_scope']='verbatim property phrase in table caption; subject and condition axes retained'
            factor = 10 ** exponent
            normalized_unit = source_unit(unit, header, table.get('caption', ''))
            if caption_label:
                context['other_conditions'].update(source_subject_caption_quote=caption_label,
                    source_subject_binding_scope='model-attributed single material in exact table caption; canonical sample identity unresolved')
            if normalized_unit != canonical_unit(unit):
                context['other_conditions']['unit_resolution_basis']='printed A. in X-ray reflection d column denotes angstrom'
            if angle:
                normalized_unit='degree'
                context['other_conditions'].update(
                    unit_resolution_basis='degree_symbol_explicit_in_response_cell',
                    full_source_cell=cells[cid]['text'],
                    source_inline_footnote_marker=angle['marker'],
                    source_inline_footnote_status='marker_preserved; meaning not inferred')
            applicable_header = ' | '.join(cells[h]['text'] for h in header_ids if header_applies(cells[h], cells[cid]))
            # A printed response multiplier and a bracketed unit multiplier
            # have opposite meanings. Apply the same source-only interpretation
            # here as in repair of earlier structured observations.
            from stages.source_display_scaling import scale_rule
            explicit_scale = scale_rule(applicable_header)
            if explicit_scale:
                factor, basis = explicit_scale
                context['other_conditions'].update(source_display_scale_basis=basis,
                    source_display_scale_factor=str(factor), source_display_header=applicable_header)
            if re.fullmatch(rf'(?:~|≈|\\sim|\\approx)\s*{_NUMBER}', plain(cells[cid]['text'])):
                context['other_conditions']['reported_approximation']='approximation marker retained in full source cell'
            display = _conductivity_display_scale(applicable_header) if 'conductivity' in name.casefold() else {}
            if display and display['display_multiplier_exponent'] == exponent:
                factor = display['value_scale_factor']
                normalized_unit = 'S/cm'
                context['other_conditions']['display_scale_interpretation'] = display['scale_interpretation']
                context['other_conditions']['source_display_exponent'] = str(exponent)
            elif 'conductivity' in name.casefold() and unit and _reciprocal_ohm_cm_unit(unit):
                normalized_unit = 'S/cm'
            if footnote:
                context['other_conditions']['source_footnote_marker'] = footnote
                context['other_conditions']['source_footnotes'] = table.get('caption','') + '\n' + '\n'.join(table.get('nearby_prose') or [])
            ancestors = [c for c in table['cells'] if c['row_index'] < first_data_row
                         and c.get('text') and header_applies(c, cells[cid])]
            if ancestors:
                context['other_conditions']['full_source_column_header_path'] = ' | '.join(c['text'] for c in ancestors)
            uncertainty = re.search(rf"(?:±|\\pm)\s*({_NUMBER})", cells[cid]['text'])
            if uncertainty:
                context['other_conditions']['reported_uncertainty_raw'] = uncertainty.group(0)
                context['other_conditions']['value_semantics'] = 'reported central estimate; uncertainty preserved, not interpreted as an interval'
            if interval:
                context['other_conditions']['value_semantics']='reported_'+interval['kind']
                if interval['inequality']:context['other_conditions']['reported_inequality']=interval['inequality']
                if reported_decomposition:context['other_conditions']['reported_decomposition_qualifier']='dec (verbatim source-cell qualifier)'
            candidate = {
                "point_id": f"pt{len(points)+1:03d}", "sample_id": None, "entity_id": None,
                "sample_resolution_status": "unresolved", "coordinates": coords,
                "value_raw": cells[cid]["text"], "value_min": value * factor,
                "value_max": (interval['maximum'] if interval else value) * factor, "unit_raw": unit, "unit_normalized": normalized_unit,
                "measurement_context": context, "coverage_status": "covered", "evidence": [ev],
                "confidence": {"score": 0.0},
            }
            if angle:candidate['value_raw']=angle['raw']
            for component in components or [None]:
                item = copy.deepcopy(candidate)
                item['point_id'] = f'pt{len(points)+1:03d}'
                if component:
                    item.update(value_raw=component['raw'], value_min=component['value'] * factor,
                                value_max=component['value'] * factor)
                    item['measurement_context']['other_conditions'].update(
                        source_peak_role=component['role'], full_source_cell=cells[cid]['text'],
                        source_binding_method=component.get('binding_method', 'explicit_inline_Tg_peak_label'))
                    if component.get('source_footnote_definition'):
                        item['measurement_context']['other_conditions']['source_footnote_definition'] = component['source_footnote_definition']
                points.append(item)
                group_evidence.append(ev)
                audit.append({"accepted": True, "reason": "explicit_inline_peak" if component else "source_cell_scalar_with_label",
                              "cell_id": cid, "property": name, "subject": label, "scale_exponent": exponent,
                              **({'peak_role': component['role']} if component else {})})
        if not points:
            continue
        payload = {
            "series_id": f"series{start_id+len(series):03d}", "sample_id": None, "entity_id": None,
            "sample_resolution_status": "unresolved", "property_name_raw": raw,
            "property_name_normalized": name, "unit_raw": unit, "unit_normalized": source_unit(unit, header, table.get('caption', '')),
            "measurement_context": {"condition_status": "reported", "other_conditions": {
                "source_property_header": header, "point_specific_conditions": "See each point's source condition/state coordinates",
                "confidence_status": "not_estimated", "required_score_placeholder": "0.0",
            }}, "points": points,
            "coverage": {"expected": len(points), "covered": len(points), "missing": 0,
                         "not_applicable": 0, "ratio": 1.0},
            "evidence": group_evidence, "confidence": {"score": 0.0},
        }
        series.append(PropertySeries.model_validate(payload).model_dump(mode="json"))
    return series, audit


def source_point_identity(series: dict, point: dict) -> tuple | None:
    """Conservative replay identity, not a cross-sample numeric deduplicator.

    Existing enriched context is preserved. Different cells, subjects, states,
    peak roles, bounds or numeric interpretations must remain distinguishable.
    """
    locators = tuple(sorted((e.get('block_id', ''), (e.get('table_locator') or {}).get('cell_id', ''))
        for e in point.get('evidence', []) if (e.get('table_locator') or {}).get('cell_id')))
    if not locators:
        return None
    conditions = (point.get('measurement_context') or {}).get('other_conditions') or {}
    recorded = conditions.get('source_supplement_identity_v1')
    if isinstance(recorded, str) and re.fullmatch('[0-9a-f]{64}', recorded):
        return ('frozen_source_claim', locators, plain(point.get('value_raw', '')), recorded)
    coordinates = tuple(sorted((c.get('name_raw', ''), plain(c.get('value_raw', '')),
        (c.get('evidence') or {}).get('block_id', ''),
        ((c.get('evidence') or {}).get('table_locator') or {}).get('cell_id', ''))
        for c in point.get('coordinates', [])))
    claim = (locators, plain(series.get('property_name_raw', '')).casefold(),
            plain(series.get('property_name_normalized', '')).casefold(),
            plain(point.get('value_raw', '')), point.get('value_min'), point.get('value_max'),
            canonical_unit(point.get('unit_normalized') or point.get('unit_raw')), coordinates,
            tuple((key, conditions.get(key)) for key in ['source_peak_role', 'reported_inequality', 'fact_role']))
    fingerprint = hashlib.sha256(json.dumps(claim, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return ('frozen_source_claim', locators, plain(point.get('value_raw', '')), fingerprint)


def merge_supplement(stage4: dict, table_results: list[tuple[dict, dict]]) -> tuple[dict, dict]:
    output = copy.deepcopy(stage4)
    existing = output.setdefault("property_series", [])
    start = max([int(x["series_id"][6:]) for x in existing] or [0]) + 1
    retained_keys = {key for s in existing for p in s.get('points', [])
                     if (key := source_point_identity(s, p)) is not None}
    audits = []
    for table, response in table_results:
        additions, decisions = materialize(table, response, start)
        admitted, skipped = [], []
        for addition in additions:
            points = []
            for point in addition['points']:
                key = source_point_identity(addition, point)
                if key is not None and key in retained_keys:
                    skipped.append({'cell_id': point['evidence'][0]['table_locator']['cell_id'],
                                    'property': addition['property_name_normalized']})
                    continue
                points.append(point)
                if key is not None:
                    # Downstream Celsius/unit repairs may change the structured
                    # display without creating a new source observation.
                    point['measurement_context']['other_conditions']['source_supplement_identity_v1'] = key[-1]
                    retained_keys.add(key)
            if not points:
                continue
            addition['series_id'] = f'series{start:03d}'
            start += 1
            addition['points'] = points
            addition['coverage'] = {'expected': len(points), 'covered': len(points), 'missing': 0,
                                    'not_applicable': 0, 'ratio': 1.0}
            addition['evidence'] = [e for p in points for e in p.get('evidence', [])]
            admitted.append(PropertySeries.model_validate(addition).model_dump(mode='json'))
        skip_keys = {(s['cell_id'], s['property']) for s in skipped}
        for decision in decisions:
            if decision.get('accepted') and (decision.get('cell_id'), decision.get('property')) in skip_keys:
                decision.update(accepted=False, reason='duplicate_existing_source_fact', materialized=True)
        existing.extend(admitted)
        audits.append({"table_id": table["table_id"], "series_added": len(admitted),
                       "points_added": sum(len(s['points']) for s in admitted),
                       "duplicate_points_skipped": len(skipped), "decisions": decisions})
    warning = {"stage": "stage4_direct_table_supplement", "code": "source_labelled_supplement",
        "message": "Direct source-cell series added; global sample binding is explicitly unresolved, not inferred. Supplement is additive; existing results retained. Confidence is not estimated: the required score field uses 0.0 as a schema placeholder, not a calibrated correctness probability or a release criterion.",
        "confidence_status": "not_estimated", "required_score_placeholder": 0.0}
    if table_results and not any(w.get('stage') == warning['stage'] and w.get('code') == warning['code']
                                for w in output.setdefault('warnings', [])):
        output['warnings'].append(warning)
    return output, {"version": VERSION, "prompt_sha256": hashlib.sha256(PROMPT_PATH.read_bytes()).hexdigest(), "tables": audits}
