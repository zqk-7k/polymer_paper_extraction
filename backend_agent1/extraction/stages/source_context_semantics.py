"""Source-bound semantic annotations; never rewrite model values or guess identity."""
from __future__ import annotations

import html
import re
from typing import Any

from stages.table_grid import table_cells_for
from stages.stage4t_table_survey import survey_table

SEMANTIC_VERSION = "source_context.v4"
# Explicit superscripts survive HTML/LaTeX; plain letters still require punctuation.
_TOKEN = r"(?:\*\d+|[a-z]|[*†‡•])"
_MARKER = re.compile(r"<sup>\s*(?P<html>" + _TOKEN + r")\s*[).]?\s*</sup>"
    r"|\^\s*\{\s*(?P<latex>" + _TOKEN + r")\s*[).]?\s*\}"
    r"|\^(?P<bare>[a-z])(?![A-Za-z0-9])"
    r"|(?<![A-Za-z0-9])(?P<star>\*\d+)(?!\d)"
    r"|(?<![A-Za-z])(?P<plain>" + _TOKEN + r")\s*[)]"
    r"|(?<=[\d)])(?P<value_symbol>[*†‡])(?=\s*(?:$|</|[A-Za-z]))")
_NOTE = re.compile(r"(?<![A-Za-z0-9])(?P<plain>" + _TOKEN + r")\s*[)]\s*"
    r"|(?:^|\n)\s*(?P<dot>[a-z])\.\s+"
    r"|<sup>\s*(?P<html>" + _TOKEN + r")\s*[).]?\s*</sup>\s*"
    r"|\^\s*\{\s*(?P<latex>" + _TOKEN + r")\s*[).]?\s*\}\s*"
    r"|\^(?P<bare>[a-z])(?![A-Za-z0-9])\s*"
    r"|(?<![A-Za-z0-9])(?P<star>\*\d+)(?!\d)\s*"
    r"|^[ \t$]*(?P<symbol>[*†‡•])\s+(?=[A-Za-z])")


def _marker_token(match: re.Match) -> str:
    return next(v for v in match.groupdict().values() if v is not None).lower()
_ROLES = {
    "calculated": r"\b(?:calculated|computed|calcd\.?|theoretical)\b",
    "predicted": r"\bpredicted\b",
    "reference": r"\b(?:literature\s+values?|taken\s+from\s+(?:the\s+)?literature|previously\s+reported)\b",
    "measured": r"\b(?:measured|experimental)\b|^\s*Found\s*(?=:|\(|$)",
}
_QUALIFIERS = re.compile(r"\b(?:approximately|about|around|roughly|approx|broad|flat|may|estimated|assumed|difficult\s+to\s+determine)\b|\bca\.(?=\s|\d)|[~≈]", re.I)


def plain(value: str) -> str:
    value = html.unescape(re.sub(r"<[^>]*>", "", value or ""))
    value = re.sub(r"\\(?:mathrm|text|rm)\s*\{([^{}]*)\}", r"\1", value)
    return re.sub(r"\s+", " ", value.replace("$", "")).strip()


def compact(value: str) -> str:
    return re.sub(r"\s+", "", plain(value)).replace("{", "").replace("}", "").replace("−", "-")


def field(item: Any, name: str, default: Any = None) -> Any:
    return item.get(name, default) if isinstance(item, dict) else getattr(item, name, default)


def _notes(text: str, block_id: str, source_cell_id: str | None = None) -> list[dict]:
    markers = list(_NOTE.finditer(text))
    return [{"marker_raw": _marker_token(m), "text_raw": text[m.start():markers[i+1].start() if i+1 < len(markers) else len(text)].strip(),
             "block_id": block_id, "source_cell_id": source_cell_id}
            for i, m in enumerate(markers)]


def explicit_note_markers(text: str) -> set[str]:
    """Called only for declared footnote sources; never strip source text."""
    markers = {_marker_token(m) for m in _NOTE.finditer(text)}
    # Legacy OCR also emits a bare leading marker followed by the definition.
    bare = re.match(r'^\s*\$?\s*([A-Za-z]|\*?\d+|[*†‡])(?:[.)}:]|\s)', text)
    if bare:
        markers.add(bare[1].lower())
    return markers


def table_notes(table: Any, blocks: dict[str, Any]) -> list[dict]:
    records = [n for text in table.table_notes for n in _notes(text, table.block_id)]
    cells = table_cells_for(table)
    width = max((c.column_index + c.column_span for c in cells), default=0)
    for cell in cells:
        if cell.row_index > 0 and cell.column_span >= max(2, width - 1):
            records.extend(_notes(cell.text, table.block_id, cell.cell_id))
    # A separate note belongs to this table only before the next table/body block.
    following = sorted((b for b in blocks.values() if b.page == table.page
                        and table.source_block_index < b.source_block_index <= table.source_block_index + 3),
                       key=lambda b: b.source_block_index)
    for block in following:
        if block.type == "table":
            break
        text = block.text or ""
        if not text.strip():
            continue
        notes = _notes(text, block.block_id)
        if not notes or not _NOTE.match(text.lstrip(" $")):
            break
        records.extend(notes)
    unique = {}
    for record in records:
        unique[(record["marker_raw"], compact(record["text_raw"]))] = record
    return list(unique.values())


def _cell_markup(table: Any) -> dict[str, str]:
    parts = re.findall(r"<(?:td|th)\b[^>]*>(.*?)</(?:td|th)>", table.table_body or "", re.I | re.S)
    cells = table_cells_for(table)
    return {c.cell_id: text for c, text in zip(cells, parts)} if len(cells) == len(parts) else {}


def table_evidence_context(evidence: Any, table: Any, blocks: dict[str, Any], value_raw: str | None = None) -> tuple[list[dict], list[dict]]:
    cells = table_cells_for(table)
    locator = field(evidence, "table_locator")
    cell_id = field(locator, "cell_id")
    anchors = [c for c in cells if c.cell_id == cell_id] if cell_id else []
    if not anchors and locator:
        anchors = [c for c in cells if c.row_index == field(locator, "row_index")
                   and c.column_index == field(locator, "column_index")]
    if not anchors:
        quote = compact(field(evidence, "source_sentence", ""))
        anchors = [c for c in cells if quote and compact(c.text) == quote]
    if len(anchors) != 1:
        return [], []
    anchor = anchors[0]
    contexts = [{"block_id": table.block_id, "source_cell_id": anchor.cell_id,
                 "text_raw": anchor.text, "scope": "table_cell"}]
    header_rows = set(survey_table(table).get("header_rows") or [0])
    data_rows = {c.row_index for c in cells if c.row_index > 0 and not c.is_header
                 and (re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", _MARKER.sub("", plain(c.text)).strip())
                      or re.match(r"^g\s*[+-]?\d", plain(c.text)))}
    headers = [c for c in cells if c.row_index < anchor.row_index
               and (c.is_header or c.row_index in header_rows)
               and (c.is_header or c.row_index not in data_rows)
               and (c.is_header or not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)",
                                                    _MARKER.sub("", plain(c.text)).strip()))
               and c.column_index <= anchor.column_index < c.column_index + c.column_span]
    contexts += [{"block_id": table.block_id, "source_cell_id": c.cell_id,
                  "text_raw": c.text, "scope": "table_header"} for c in headers]
    # Explicit result-role labels can also head a row, e.g. Found / Calcd.
    contexts += [{"block_id": table.block_id, "source_cell_id": c.cell_id,
                  "text_raw": c.text, "scope": "table_row_label"}
                 for c in cells if c.row_index == anchor.row_index and c.column_index < anchor.column_index
                 and re.fullmatch(r"\s*(?:Found|Calcd\.?|Calculated|Measured|Experimental)\s*:?\s*", plain(c.text), re.I)]
    markup = _cell_markup(table)
    definitions = table_notes(table, blocks)
    associations = []
    for cell in [anchor, *headers]:
        raw_cell = markup.get(cell.cell_id, cell.text)
        selected = []
        for match in _MARKER.finditer(raw_cell):
            if cell.cell_id == anchor.cell_id and value_raw:
                numbers = re.findall(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", plain(raw_cell[:match.start()]))
                targets = re.findall(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", plain(value_raw))
                if numbers and targets and numbers[-1] not in targets:
                    continue
            selected.append(_marker_token(match))
        for marker in dict.fromkeys(selected):
            matching = [n for n in definitions if n["marker_raw"] == marker]
            for note in matching:
                association = {**note, "anchor_cell_id": anchor.cell_id, "marker_cell_id": cell.cell_id,
                               "status": "confirmed" if len(matching) == 1 else "ambiguous"}
                if association not in associations:
                    associations.append(association)
            # OCR can change a note symbol. A unique alternative is a review
            # candidate only, scoped to an explicitly marked value, never a header.
            alternatives = [n for n in definitions if n["marker_raw"] == "•"]
            if not matching and marker in "*†‡" and cell.cell_id == anchor.cell_id and len(alternatives)==1:
                associations.append({**alternatives[0],"anchor_marker_raw":marker,
                    "anchor_cell_id":anchor.cell_id,"marker_cell_id":cell.cell_id,
                    "status":"candidate","association_basis":"unique_symbol_mismatch"})
    return contexts, associations


def _value_in_quote(raw: str, text: str) -> bool:
    target = compact(raw)
    source = compact(text)
    return bool(target and re.search(r"(?<![\d.])" + re.escape(target) + r"(?!\d|\.\d)", source))


def literal_value_supported(item: Any, blocks: dict[str, Any]) -> bool:
    """Verify literal source value before relaxing a relation, never infer a value."""
    raw = field(item, "value_raw", "") or ""
    for evidence in field(item, "evidence", []):
        block = blocks.get(field(evidence, "block_id"))
        if block is None:
            continue
        if block.type == "table":
            locator = field(evidence, "table_locator")
            if not locator:
                continue
            cells = [c for c in table_cells_for(block)
                     if (not field(locator, "cell_id") or c.cell_id == field(locator, "cell_id"))
                     and (field(locator, "row_index") is None or c.row_index == field(locator, "row_index"))
                     and (field(locator, "column_index") is None or c.column_index == field(locator, "column_index"))]
            if len(cells) == 1 and compact(raw) == compact(cells[0].text):
                return True
            trace = field(item, "candidate_trace") or {}
            span = trace.get("source_span")
            if (len(cells) == 1 and isinstance(span, list) and len(span) == 2
                    and all(isinstance(n, int) and not isinstance(n, bool) for n in span)
                    and 0 <= span[0] < span[1] <= len(cells[0].text)
                    and trace.get("source_cell_raw") == cells[0].text
                    and cells[0].text[span[0]:span[1]] == raw):
                return True
        else:
            quote = field(evidence, "source_sentence", "") or ""
            if quote and compact(quote) in compact(block.text or "") and _value_in_quote(raw, quote):
                return True
    return False


def derive_source_semantics(item: Any, blocks: dict[str, Any]) -> dict:
    contexts, associations, warnings = [], [], []
    raw = field(item, "value_raw", "") or ""
    for evidence in field(item, "evidence", []):
        block = blocks.get(field(evidence, "block_id"))
        if block is None:
            continue
        if block.type == "table":
            linked, notes = table_evidence_context(evidence, block, blocks, raw)
            contexts.extend(linked)
            associations.extend(n for n in notes if n not in associations)
        else:
            quote = field(evidence, "source_sentence", "") or ""
            if quote and compact(quote) in compact(block.text or block.caption or ""):
                # Keep only clauses containing this literal value, not an entire article.
                for clause in re.split(r"(?<=[.;])\s+(?=[A-Z])", plain(quote)):
                    if _value_in_quote(raw, clause):
                        contexts.append({"block_id": block.block_id, "text_raw": clause, "scope": "body"})
    for note in associations:
        if note["status"] == "confirmed":
            contexts.append({**note, "scope": "table_note"})
        elif note["status"] == "candidate":
            contexts.append({**note, "scope":"table_note_candidate"})
            warnings.append("footnote_marker_unverified")
        else:
            warnings.append("footnote_marker_ambiguous")
    roles, role_sources, qualifiers = set(), [], []
    trace = field(item, "candidate_trace") or {}
    part_position = trace.get("part_position")
    for context in contexts:
        found = {role for role, pattern in _ROLES.items() if re.search(pattern, plain(context["text_raw"]), re.I)}
        if context["scope"] == "table_note_candidate": found = set()
        if (not part_position and trace.get("composite_status") in {
                "explicit_parenthetical_pair", "ambiguous_concatenated_numbers"}
                and context["scope"] == "table_header" and re.search(r"\(\s*(?:calcd\.?|calculated|theoretical)\s*\)",
                                                                       plain(context["text_raw"]),re.I)):
            found = set()
            warnings.append("composite_role_requires_review")
        if part_position and context["scope"] == "table_header" and re.search(
                r"\(\s*(?:calcd\.?|calculated|theoretical)\s*\)", plain(context["text_raw"]), re.I):
            found = ({"calculated"} if part_position == "inside" else {"measured"} if re.search(
                r"\b(?:found|measured|experimental)\s*\(", plain(context["text_raw"]), re.I) else set())
        for role in list(found):
            if re.search(r"\b(?:not|never|neither)\s+(?:\w+\s+){0,2}(?:" + _ROLES[role] + ")", plain(context["text_raw"]), re.I):
                found.remove(role)
                warnings.append("negated_role_statement")
        roles.update(found)
        if found:
            role_sources.append(context)
        for match in _QUALIFIERS.finditer(plain(context["text_raw"])):
            record = {"qualifier_raw": match[0], **context}
            if record not in qualifiers:
                qualifiers.append(record)
    role = next(iter(roles)) if len(roles) == 1 else "unknown"
    model_role = field(field(item, "value_semantics"), "value_role", "unknown")
    role_status = "confirmed" if role != "unknown" else "unresolved"
    if len(roles) > 1:
        role_status = "ambiguous"
        warnings.append("source_role_ambiguous")
    elif role != "unknown" and model_role not in ("unknown", role):
        role_status = "conflict"
        warnings.append("model_source_role_conflict")
    return {"version": SEMANTIC_VERSION, "model_role": model_role, "source_role": role,
            "role_status": role_status, "role_sources": role_sources,
            "source_contexts": contexts,
            "footnote_associations": associations, "qualifiers_from_source": qualifiers,
            "conditions_from_source": derive_context_conditions(contexts),
            "warnings": list(dict.fromkeys(warnings))}


def derive_context_conditions(contexts: list[dict]) -> list[dict]:
    """Extract explicit parameters only within this value's verified body/note scope."""
    number = r"(?<![\w.,·])(?:[+-]?\d+(?:[.,·]\d+)?\s*(?:–|—|to|±|(?<=\d)-)\s*)?[+-]?\d+(?:[.,·]\d+)?"
    patterns = {
        "heating_rate": number + r"\s*(?:°C|K)\s*(?:/\s*min|min\s*\^?\s*-1)",
        "frequency": number + r"\s*(?:MHz|kHz|Hz)\b",
        "concentration": number + r"\s*g\s*(?:/\s*(?:dl|mL|L)\b|dl\s*\^?\s*-1)",
        "temperature": number + r"\s*(?:°C|K)(?![A-Za-z])",
        "time": number + r"\s*(?:μs|µs|ms|min|h|s)\b",
        "weight_loss_threshold": number + r"\s*%\s*(?:weight\s+loss|loss\s+(?:in|of)\s+weight)",
        "measurement_method": r"\b(?:GPC|DSC|TGA|NMR|ASTM\s+D\s*\d+(?:,?\s*method\s+[A-Z])?|dynamic\s+calorimetry)\b",
    }
    result = []
    for context in contexts:
        if context["scope"] not in {"body", "table_note", "table_note_candidate"}:
            continue
        text = plain(context["text_raw"])
        text = re.sub(r"\\[,;!]", " ", text).replace(r"\circ", "°").replace("{", "").replace("}", "").replace("^°", "°")
        text = re.sub(r"°\s+C\b", "°C", text)
        occupied = []
        for key, pattern in patterns.items():
            for match in re.finditer(pattern, text, re.I):
                if key in {"temperature", "time"} and any(a <= match.start() < b for a,b in occupied):
                    continue
                if key == "heating_rate": occupied.append(match.span())
                result.append({"parameter":key, "value_raw":match[0], "quote":context["text_raw"],
                               "block_id":context["block_id"], "source_cell_id":context.get("source_cell_id"),
                               "scope":context["scope"], "status":"candidate" if context["scope"]=="table_note_candidate" else "source_supported"})
    return list({str(sorted(r.items())):r for r in result}.values())


def _parameter_compact(text: str) -> str:
    text = re.sub(r"\\(?:,|;|!|quad|qquad|left|right)", "", text)
    return compact(text).replace(r"\circ", "°").replace("^°", "°").replace(r"\cdot", "·").replace("^-", "-")


def _nucleus(text: str) -> str | None:
    match = re.search(r"(?:1h|13c|31p)", compact(text).lower())
    return match[0] if match else "1h" if "proton" in text.lower() else None


def _parameter_scope_status(value: str, nucleus: str | None, source: str) -> str:
    if not nucleus:
        return "confirmed"
    text, target = _parameter_compact(source).lower(), _parameter_compact(value).lower()
    nuclei = [(m.start(), "1h" if m[0] == "proton" else m[0])
              for m in re.finditer(r"1h|13c|31p|proton", text)]
    position = text.find(target)
    if not nuclei or position < 0:
        return "unverified"
    # Co-occurrence in a paragraph is insufficient; keep uncertain nuclear scopes as candidates.
    distances = [(abs(p-position), n) for p,n in nuclei]
    nearest = min(d for d,_ in distances)
    closest = {n for d,n in distances if d == nearest}
    return "confirmed" if closest == {nucleus} else "candidate"


def derive_parameter_sources(characterization: Any, properties: list[Any], blocks: dict[str, Any]) -> dict[str, list[dict]]:
    """Preserve model parameter values; annotate body/table contexts separately."""
    table_contexts = []
    relevant = [p for p in properties if field(p, "characterization_id") == characterization.characterization_id]
    for prop in relevant:
        for evidence in prop.evidence:
            table = blocks.get(evidence.block_id)
            if table is not None and table.type == "table":
                contexts, notes = table_evidence_context(evidence, table, blocks)
                table_contexts.append((contexts, notes))
    # Explicit raw labels can anchor a table row even when the model cites only body text.
    label = field(characterization, "article_sample_key")
    if label:
        for table in blocks.values():
            if table.type != "table":
                continue
            cells = table_cells_for(table)
            rows = [c.row_index for c in cells if c.column_index == 0 and compact(c.text) == compact(label)]
            if len(rows) != 1:
                continue
            for cell in cells:
                if cell.row_index == rows[0] and cell.column_index > 0:
                    contexts, notes = table_evidence_context({"table_locator":{"cell_id":cell.cell_id}}, table, blocks)
                    table_contexts.append((contexts, notes))
    result = {}
    for key, value in characterization.parameters.items():
        records = []
        target, nucleus = _parameter_compact(value), _nucleus(key)
        for evidence in characterization.evidence:
            block = blocks.get(evidence.block_id)
            if block is None:
                continue
            if block.type == "table":
                # A directly quoted table note need not pass through a property binding.
                source = field(evidence, "source_sentence", "") or ""
                available = [block.caption or "", *block.table_notes,
                             *(c.text for c in table_cells_for(block))]
                if not source or not any(_parameter_compact(source) in _parameter_compact(t) for t in available):
                    continue
                scope = "table_quote"
            else:
                source = block.text or block.caption or ""
                scope = "body"
            if nucleus and nucleus not in compact(source).lower() and not (nucleus == "1h" and "proton" in source.lower()):
                continue
            if target and re.search(r"(?<![\d.])" + re.escape(target) + r"(?!\d|\.\d)", _parameter_compact(source)):
                scope_status = _parameter_scope_status(value, nucleus, source)
                records.append({"value_raw":value, "block_id":block.block_id, "quote":source,
                                "scope":scope, "status":scope_status,
                                "relation":"model_value_source" if scope_status == "confirmed" else "scope_not_unique"})
        for contexts, notes in table_contexts:
            headers = " ".join(c["text_raw"] for c in contexts if c["scope"] == "table_header")
            if nucleus and nucleus not in compact(headers).lower():
                continue
            for note in notes:
                if nucleus and note["marker_cell_id"] == note["anchor_cell_id"]:
                    continue
                text = note["text_raw"]
                if target and re.search(r"(?<![\d.])" + re.escape(target) + r"(?!\d|\.\d)", _parameter_compact(text)):
                    records.append({**note, "value_raw":value, "quote":text,
                                    "scope":"table_note", "status":note["status"], "relation":"model_value_source"})
                elif re.search(r"(?:M|k)?Hz\b", value):
                    # A frequency belongs only to its explicitly marked NMR column.
                    if not nucleus and "nmr" not in compact(headers).lower():
                        continue
                    for match in re.finditer(r"(?<![\d.])(\d+(?:\.\d+)?)\s*((?:M|k)?Hz)\b", plain(text)):
                        records.append({**note, "value_raw": f"{match[1]} {match[2]}", "quote":text,
                                        "scope":"table_note", "status":"candidate", "relation":"alternate_context"})
        unique = {str(sorted(record.items())):record for record in records}
        result[key] = list(unique.values()) or [{"value_raw":value, "status":"unverified", "scope":"unverified"}]
    return result
