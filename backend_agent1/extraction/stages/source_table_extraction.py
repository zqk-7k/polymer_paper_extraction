"""Source-first table observations, independent of standardization and legacy gates."""
from collections import Counter, defaultdict
from copy import deepcopy
import re

from stages.sample_catalog import source_index, digest
from stages.binding_identity import build_article_sample_key
from stages.standard_mapping import resolve_standard_property, units_in_text
from stages.source_table_layout import refine_layout, inferred_sample_columns, active_material_group, material_label, preceding_material, inline_temperature
from stages.source_field_enrichment import enrich_fields, caption_material, clean_header
from stages.source_claim_recovery import trace_claim
from stages.source_text_extraction import build_text_observations
from stages.source_text_reviews import reviewed_text_observations
from stages.source_derivation_enrichment import inherit_cell_interpretations


SAMPLE = re.compile(r"^(?:samples?|specimens?|materials?|polymers?|polyimides?|monomers?|compounds?)(?:\b|\s)|^(?:code|codes)$", re.I)
CONTEXT = re.compile(r"^(?:dose|temperature|temp\.?|time|frequency|pressure|humidity|catalyst|solvent|reaction|location|state|description|method|sample history|run|entry|no\.|lp\.)(?:\b|(?<=\.))", re.I)
COMPOSITION = re.compile(r"composition|content|feed ratio|unit ratio|weight fraction|molar fraction|concentration|conc\.", re.I)
PROPERTY = re.compile(r"yield|strength|modulus|elongation|solubility|uptake|viscosity|conductivity|density|enthalpy|crystall|transition|melting|contact|energy|(?:^|[\\$_{ ])(?:T[_{} ]?[gmcdi]|M[_{} ]?[nw])|eta|lambda|epsilon|properties|\([^)]*(?:°C|MPa|GPa|nm|%|g/mol)[^)]*\)", re.I)
UNIT = re.compile(r"(?<![A-Za-z])(?:g/mol|dL/g|dl/g|mL/g|J/g|J/m|kJ/mol|S/cm|mJ/m2|MPa|GPa|kPa|kGy|°C|°F|℃|nm|µm|μm|cm-1|cm⁻¹|%|K)(?![A-Za-z])")
MISSING = re.compile(r"^(?:[—–-]+(?:[a-z]|\s*\(?[a-z]\)?)?|N/?A|n\.d\.|not reported)$", re.I)


def _sample(text):
    return bool(SAMPLE.search(text + " ") or re.match(r'^(?:name of polymers|resultant polymer|code[a-z]?(?:\b|\$))', text, re.I))


def _covers(cell, target, axis):
    start = cell[axis + "_index"]
    return start <= target[axis + "_index"] < start + cell[axis + "_span"]


def _axis_kind(headers, caption=''):
    # The nearest named header defines the column; an outer group may be a sample.
    texts = [h["text"].strip() for h in headers if h["text"].strip()]
    for text in reversed(texts):
        if (re.fullmatch(r'Tc\s*\(°C\)', clean_header(text))
                and re.search(r'Crystallinities.*for Various Values', caption, re.I)):
            return 'context'
        if UNIT.fullmatch(text.strip("()[] ")):
            continue
        if COMPOSITION.search(text):
            return "composition"
        if re.match(r'^\$?MR(?:\W|$)',text):
            return 'composition'
        if re.search(r'^(?:solute|amount used|dissolved in|column loading|amine\b|wtPEP|C mol|\$?f\(|T \(K\))', text, re.I):
            return "context"
        if any(re.search(r'dicarboxylic', t, re.I) for t in texts):
            return "composition"
        if CONTEXT.search(text):
            return "context"
        if re.search(r"comment|remark|note", text, re.I):
            return "note"
        return "property"
    return "property" if texts else "unknown"


def table_layout(cells, caption=""):
    """Infer only spatial header boundaries; preserve every header verbatim."""
    first = [c for c in cells if c["row_index"] == 0]
    if not first or not any(c["row_index"] > 0 for c in cells):
        return {"orientation": "unknown", "header_rows": 0, "basis": "structure_unresolved"}
    explicit = [c for c in cells if c.get("is_header")]
    depth = max(c["row_span"] for c in first)
    left = [c for c in cells if c["column_index"] == 0 and c["row_index"] >= depth and c["text"]]
    right = [c for c in first if c["column_index"] > 0 and c["text"]]
    left_properties = sum(bool(PROPERTY.search(c["text"])) for c in left)
    right_properties = sum(bool(PROPERTY.search(c["text"])) for c in right)
    corner = first[0]["text"].strip().casefold()
    if corner in {"property", "properties"} or (corner == "solvent" and re.search(r"solub", caption, re.I)):
        return {"orientation": "samples_in_columns", "header_rows": depth, "basis": "explicit_row_axis_label"}
    if left and left_properties >= max(1, len(left) / 2) and not right_properties:
        return {"orientation": "samples_in_columns", "header_rows": depth, "basis": "row_property_labels_and_column_labels"}
    anchor = any(_sample(c["text"]) or CONTEXT.search(c["text"]) or COMPOSITION.search(c["text"]) for c in first)
    if explicit or anchor or right_properties:
        # A top spanning group can introduce a second header row even without rowspan.
        second = [c for c in cells if c["row_index"] == 1]
        if depth == 1 and any(c["column_span"] > 1 for c in first) and second:
            if sum(bool(PROPERTY.search(c["text"])) for c in second) >= 2:
                depth = 2
        return {"orientation": "samples_in_rows", "header_rows": depth,
                "basis": "explicit_headers" if explicit else "source_header_geometry"}
    return {"orientation": "unknown", "header_rows": 0, "basis": "structure_unresolved"}


def _claims(publication):
    for status in ("final", "candidate", "not_publishable"):
        for group in (publication or {}).get(status, []):
            yield {"claim_id": group["measurement_id"], "claim_kind": "publication", "legacy_status": status,
                   "source_cell_ids": group["identity"].get("source_cell_ids", []), "original": deepcopy(group)}
    for row in (publication or {}).get("raw_candidate_ledger", {}).get("records", []):
        yield {"claim_id": row["measurement_id"], "claim_kind": "historical_candidate", "legacy_status": row["publication_status"],
               "source_cell_ids": row.get("source_cell_ids", []), "original": deepcopy(row)}


def _enrichment(claims):
    # Reuse certified associations only; the source observation does not require them.
    accepted = [c["original"]["record"] for c in claims if c["claim_kind"] == "publication"
                and c["legacy_status"] == "final" and c["original"].get("record")]
    identities = {(r.get("sample_id"), r.get("entity_id")) for r in accepted}
    sid, eid = next(iter(identities)) if len(identities) == 1 else (None, None)
    return {"sample_id": sid, "entity_id": eid,
            "identity_status": "legacy_source_verified" if sid or eid else "not_linked",
            "legacy_final_measurement_ids": sorted(c["claim_id"] for c in claims if c["legacy_status"] == "final")}


def build_source_extraction(stage0, publication=None, *, include_local_reviews=True):
    doc = stage0["document_id"]
    if publication and publication.get("document_id") != doc:
        raise ValueError("Source extraction document mismatch")
    blocks, cell_map = source_index(stage0)
    by_table = defaultdict(list)
    for cell in cell_map.values():
        by_table[cell["table_id"]].append(cell)
    claims = list(_claims(publication))
    bundle = (publication or {}).get("source_interpretation_bundle") or {}
    if bundle and bundle.get("document_id") != doc:
        raise ValueError("Source interpretation document mismatch")
    interpreted_by_cell = defaultdict(list)
    for row in bundle.get("records", []):
        for cid in row.get("source_cell_ids", []):
            interpreted_by_cell[cid].append(row)
    by_cell = defaultdict(list)
    for claim in claims:
        for cid in claim["source_cell_ids"]:
            if cid in cell_map:
                by_cell[cid].append(claim)
    observations, tables = [], []
    for bid, cells in sorted(by_table.items()):
        cells = sorted(cells, key=lambda c: (c["row_index"], c["column_index"]))
        block = blocks[bid]
        layout = refine_layout(cells, table_layout(cells, str(block.get("caption") or "")), str(block.get('caption') or ''))
        depth, orientation = layout["header_rows"], layout["orientation"]
        headers = [c for c in cells if c["row_index"] < depth]
        sample_cols = {col for c in headers if _sample(c["text"]) and (c['column_span'] == 1 or c['text'].casefold() in {'sample', 'samples'} or
                       all(re.match(r'^(?:no\.|code)', h['text'], re.I) for h in headers if h['row_index'] > c['row_index'] and _covers(c, h, 'column')))
                       for col in range(c['column_index'], c['column_index'] + c['column_span'])}
        sample_cols = inferred_sample_columns(cells, headers, depth, sample_cols)
        elements=stage0.get('elements', [])
        position=next((i for i,b in enumerate(elements) if b.get('block_id')==bid), -1)
        nearby=[deepcopy(b) for b in elements[max(0,position-2):position+3] if b.get('type')=='text'] if position >= 0 else []
        tables.append({"table_id": bid, "page": block.get("page"), "caption": block.get("caption"),
                       "source_block_index": block.get("source_block_index"),
                       "table_notes": deepcopy(block.get("table_notes", [])), "layout": layout,
                       "nearby_text_blocks": nearby,
                       "cells": deepcopy(cells), "source_table_sha256": digest(block)})
        width = max(c["column_index"] + c["column_span"] for c in cells)
        solubility = bool(re.search(r"solub|溶解", str(block.get("caption") or ""), re.I))
        for cell in cells:
            if not cell["text"] or cell["row_index"] < depth:
                continue
            if orientation in {'samples_in_rows','property_rows_with_column_conditions'} and cell['column_span']>=width and width>1 and material_label(cell['text']):
                continue  # A material section heading remains in source inventory, not a measurement.
            row_cells = [c for c in cells if c["row_index"] >= depth and _covers(c, cell, "row")]
            above = [h for h in headers if _covers(h, cell, "column") and h["text"]]
            samples, context = [], []
            sample_basis = 'source_axis' if sample_cols else 'unresolved'
            unresolved_fields = list(layout.get('unresolved_fields', []))
            if orientation == 'property_value_pairs':
                if cell['column_index'] == 0:
                    continue
                property_cells = [c for c in row_cells if c['column_index'] == 0 and c['text']]
            elif orientation == 'two_condition_axes':
                if cell['column_index'] == 0:
                    continue
                property_cells = []
                context = [{'name_raw': 'column condition', 'value_raw': h['text'], 'cell_id': h['cell_id']} for h in above]
                context.extend({'name_raw': first['text'], 'value_raw': c['text'], 'cell_id': c['cell_id']}
                               for first in headers if first['column_index'] == 0
                               for c in row_cells if c['column_index'] == 0 and c['text'])
            elif orientation == 'material_sections_with_inline_properties':
                if cell['column_index'] == 1 or (cell['column_index'] == 0 and material_label(cell['text'])):
                    continue
                group = preceding_material(cells, cell, depth)
                if group is not None:
                    samples, sample_basis = [group], 'material_section_with_inline_properties'
                if cell['column_index'] == 0:
                    property_cells = [cell]
                    unresolved_fields.append('inline_temperature_treatment_not_assigned')
                else:
                    property_cells = above
                    context = [{'name_raw':'treatment', 'value_raw':c['text'], 'cell_id':c['cell_id']}
                               for c in row_cells if c['column_index'] == 1 and c['text']]
            elif orientation == 'structure_substituents':
                if cell['column_index'] >= 2:
                    continue
                property_cells = above
                samples = [c for c in row_cells if c['column_index'] == 2 and c['text']]
                sample_basis = 'same_row_structure_code'
            elif orientation == 'named_property_rows_unlabeled_columns':
                if cell['column_index'] == 0:
                    continue
                row_headers = [c for c in row_cells if c['column_index'] == 0 and c['text']]
                property_cells = above or row_headers
                if above:
                    unresolved_fields = []
                context = [{'name_raw':'source column index', 'value_raw':str(cell['column_index']),
                            'cell_id':cell['cell_id'], 'basis':'position_only_not_conformation_identity'}]
            elif orientation == 'property_rows_with_column_conditions':
                if cell['column_index']==0:
                    continue
                property_cells=[c for c in row_cells if c['column_index']==0 and c['column_span']==1 and c['text']]+above
                group=active_material_group(cells,cell,depth,width)
                if group is not None:
                    samples,sample_basis=[group],'spanning_material_group'
                context=[{'name_raw':'column condition','value_raw':h['text'],'cell_id':h['cell_id']} for h in above]
            elif orientation == "samples_in_columns":
                property_cols = layout.get('property_columns', [0])
                if cell["column_index"] in property_cols:
                    continue
                property_cells = [c for c in row_cells if c["column_index"] in property_cols and c["text"]]
                samples = above
                sample_basis = 'column_header'
                for axis in cells:
                    if axis['column_index'] != 0 or axis['row_index'] < depth or _axis_kind([axis]) != 'composition':
                        continue
                    for other in cells:
                        if other['row_index']==axis['row_index'] and other['column_index'] > 0 and _covers(other,cell,'column') and other['cell_id'] != cell['cell_id'] and other['text'] and not MISSING.fullmatch(other['text']):
                            context.append({'name_raw':axis['text'],'value_raw':other['text'],'cell_id':other['cell_id']})
            elif orientation == 'samples_in_column_groups':
                if not above or above[0]['row_index'] != 0 or not material_label(above[0]['text']):
                    continue
                samples = [above[0]]
                property_cells = [h for h in above if h['row_index'] > 0]
                sample_basis = 'column_group'
                for other in row_cells:
                    if other['column_index'] == 0 and other['column_index'] < min(h['column_index'] for h in headers if h['text']):
                        context.append({'name_raw': 'row condition', 'value_raw': other['text'], 'cell_id': other['cell_id']})
            elif orientation == "samples_in_rows":
                if cell["column_index"] in sample_cols:
                    continue
                property_cells = above
                # Repeated side-by-side sample/property sections: nearest sample axis wins.
                eligible = [c for c in row_cells if c["column_index"] in sample_cols and c["column_index"] < cell["column_index"]]
                if eligible:
                    # Combine adjacent columns under a merged Sample header; keep repeated sections local.
                    nearest = max(c['column_index'] for c in eligible)
                    group_start = nearest
                    while group_start - 1 in sample_cols:
                        group_start -= 1
                    samples = [c for c in eligible if c['column_index'] >= group_start and c['text']]
                group = active_material_group(cells, cell, depth, width)
                if not samples and group is not None:
                    samples, sample_basis = [group], 'spanning_material_group'
                if not samples:
                    direct = [c for c in row_cells if c['column_index'] == 0 and c['column_span'] == 1 and material_label(c['text'])]
                    if direct and any(COMPOSITION.search(h['text']) for h in headers if h['column_index'] == 0):
                        samples, sample_basis = direct, 'material_in_composition_column'
                if any(s['cell_id'] == cell['cell_id'] for s in samples):
                    continue
                for other in row_cells:
                    hs = [h for h in headers if _covers(h, other, "column") and h["text"]]
                    name = " | ".join(h["text"] for h in hs)
                    if other is not cell and other not in samples and _axis_kind(hs, str(block.get('caption') or '')) in {"context", "composition"}:
                        context.append({"name_raw": name, "value_raw": other["text"], "cell_id": other["cell_id"]})
                embedded = re.match(r'^(Ox|Red)\s*=', cell['text'])
                if embedded:
                    context.append({'name_raw': 'state', 'value_raw': embedded[1], 'cell_id': cell['cell_id']})
            else:
                property_cells = []
            texts = [h["text"] for h in property_cells]
            name = " | ".join(texts) or None
            issues = []
            kind = _axis_kind(property_cells, str(block.get('caption') or ''))
            if orientation == 'structure_substituents':
                kind = 'composition'
            if kind == 'property' and re.search(r'Atomic Compositions',str(block.get('caption') or ''),re.I):
                kind = 'composition'
            if not name:
                kind = "unknown"
                issues.append("property_axis_requires_interpretation")
            qualitative = bool(name and re.search(r"solub", name, re.I)) or (solubility and bool(re.fullmatch(r"[+\-±]+|soluble|insol\.?|insoluble|partially soluble", cell["text"].strip(), re.I)))
            if qualitative and kind in {"property", "context"}:
                kind = "qualitative_property"
            # Preserve missing markers in the table inventory, not as measured zero.
            if MISSING.fullmatch(cell["text"].strip()) and not (qualitative and cell["text"].strip() == "-"):
                continue
            if cell["column_span"] > 1 and cell["column_span"] >= width:
                kind = "note"
                issues.append("spanning_group_row")
            if cell["column_span"] > 1 and len({h["column_index"] for h in above if h["row_index"] == depth - 1}) > 1:
                issues.append("value_spans_multiple_axes")
            if sample_basis != 'spanning_material_group' and any(not (s["row_index"] <= cell["row_index"] and s["row_index"] + s["row_span"] >= cell["row_index"] + cell["row_span"]) for s in samples) and orientation == "samples_in_rows":
                issues.append("value_spans_multiple_sample_rows")
            if qualitative and name and not re.search(r"solub", name, re.I):
                name = " | ".join([str(block.get("caption") or "Solubility"), name])
            matches = list(dict.fromkeys(UNIT.findall(" ".join(texts))))
            unit = matches[0] if len(matches) == 1 else None
            label = " | ".join(s["text"] for s in samples) or None
            scope = [s["cell_id"] for s in samples]
            caption_source=caption_material(str(block.get('caption') or '')) if not label and kind=='property' else None
            if caption_source:
                label=caption_source['text']; sample_basis='explicit_caption_phrase'
            # The row/column anchor is part of identity even when treatment is implicit.
            key = build_article_sample_key(doc, bid, label, variant_context={"axis": scope, "conditions": context,
                "source_row": cell["row_index"] if orientation == "samples_in_rows" else None}) if label else None
            mapping = resolve_standard_property(name, unit) if name else {}
            enriched=enrich_fields(texts,name,unit,str(block.get('caption') or ''))
            cid = cell["cell_id"]
            linked = by_cell[cid]
            observations.append({"observation_id": "observation_" + digest([doc, cid])[:24], "document_id": doc,
                "table_id": bid, "source_cell_id": cid, "row_index": cell["row_index"], "column_index": cell["column_index"],
                "row_span": cell["row_span"], "column_span": cell["column_span"], "value_raw": cell["text"],
                "value_normalized": None, "property_name_raw": name, "property_header_path": texts,
                "property_header_cell_ids": [h["cell_id"] for h in property_cells], "unit_raw": unit,
                "unit_source_texts": texts, "unit_candidates": units_in_text(" ".join(texts)),
                "unit_status": "source_token" if unit else "not_stated_or_not_parsed",
                "article_sample_label_raw": label, "article_sample_key": key, "sample_axis_cell_ids": scope,
                "sample_label_basis": sample_basis if label else 'unresolved',
                "sample_label_caption_span":caption_source,
                "header_context_raw":[{'cell_id':h['cell_id'],'text':h['text']} for h in property_cells[:-1]],
                "condition_context_raw": context, "record_kind": kind,
                "extraction_status": "needs_review" if issues else "usable", "review_fields": issues,
                "unresolved_context_fields": unresolved_fields,
                "evidence_basis": "current_source_recheck", "historical_request_verified": False,
                "layout_basis": layout["basis"], "source_table_sha256": digest(block),
                "standard_property_code": mapping.get("standard_property_code"),
                "standard_status": mapping.get("standard_status", "standard_unmapped"),
                "claim_ids": sorted(set(c["claim_id"] for c in linked)), **_enrichment(linked), **enriched})
    for observation in observations:
        inherit_cell_interpretations(observation, interpreted_by_cell[observation['source_cell_id']])
    observation_by_cell = {r["source_cell_id"]: r for r in observations}
    for claim in claims:
        ids = claim["source_cell_ids"]
        claim["observation_ids"] = [observation_by_cell[c]["observation_id"] for c in ids if c in observation_by_cell]
        claim["disposition"] = "linked_source_observation" if claim["observation_ids"] else "source_context_only" if ids and all(c in cell_map for c in ids) else "source_missing_or_unlocated"
        original = claim["original"]
        value = (original.get("identity") or original.get("effective_candidate") or {}).get("value_raw")
        claim["value_check"] = "exact_source_text" if len(ids) == 1 and ids[0] in cell_map and str(value).strip() == cell_map[ids[0]]["text"].strip() else "interpretation_retained_separately"
        claim['source_trace']=trace_claim(claim,blocks,cell_map,(publication or {}).get('source_evidence_catalog',[]))
    source_blocks = [deepcopy(b) for b in blocks.values() if b.get('type') == 'text']
    source_context_blocks = [deepcopy(b) for b in blocks.values() if b.get('type') in {'title','footnote','equation'}]
    text_observations = build_text_observations(doc, source_blocks)
    reviewed_text, text_review_issues = reviewed_text_observations(doc, source_blocks + source_context_blocks) if include_local_reviews else ([], [])
    reviewed_ids = {r['observation_id'] for r in reviewed_text}
    text_observations = [r for r in text_observations if r['observation_id'] not in reviewed_ids] + reviewed_text
    observations.extend(text_observations)
    counts = dict(Counter(r["extraction_status"] for r in observations))
    counts.update(observation_count=len(observations), table_count=len(tables), source_cell_count=len(cell_map),
                  usable_property=sum(r["extraction_status"] == "usable" and r["record_kind"] in {"property", "qualitative_property"} for r in observations),
                  claim_count=len(claims), claims_without_observation=sum(not c["observation_ids"] for c in claims),
                  text_observation_count=len(text_observations))
    return {"schema_version": "source_table_extraction.v1", "document_id": doc, "source_sha256": digest(stage0),
            "definition": "One source-cell observation or explicit prose mention; neither count implies unique measurements. Standardization and sample links are optional.",
            "tables": tables, "observations": observations, "claims": claims, "counts": counts,
            "source_interpretation_bundle": deepcopy(bundle),
            "source_blocks":source_blocks,
            "source_context_blocks":source_context_blocks,
            "source_figure_blocks":[deepcopy(b) for b in blocks.values() if b.get('type') in {'image','figure'}],
            "text_review_issues":text_review_issues,
            "claim_trace_counts":dict(Counter(c['source_trace']['status'] for c in claims)),
            "record_kind_counts": dict(Counter(r["record_kind"] for r in observations))}
