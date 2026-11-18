"""Versioned table structure rules. Local expansion only; no model/network calls.

Coordinates are zero based, inclusive, and belong to one frozen OCR table.
Rules never supply measured values. A definition is reused only by explicit rules.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
import base64
import hashlib
import json
from pathlib import Path
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

STRUCTURE_VERSION = 'stage4t_table_structure.v2'
EXPANDER_VERSION = 'stage4t_structure_expand.v1.1'


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Region(StrictModel):
    row_start: int = Field(ge=0)
    row_end: int = Field(ge=0)
    column_start: int = Field(ge=0)
    column_end: int = Field(ge=0)

    @model_validator(mode='after')
    def ordered(self):
        if self.row_end < self.row_start or self.column_end < self.column_start:
            raise ValueError('reversed region')
        return self


class Scope(StrictModel):
    regions: list[Region] = Field(default_factory=list)
    cell_ids: list[str] = Field(default_factory=list)
    exclude_cell_ids: list[str] = Field(default_factory=list)


class Definition(StrictModel):
    definition_id: str = Field(min_length=1)
    kind: Literal['property', 'subject', 'condition', 'unit', 'scale', 'measurement_role', 'content']
    source_refs: list[str] = Field(min_length=1)
    source_quote: str = Field(min_length=1)
    role: Literal['official_property', 'material_characteristic', 'unmapped_property'] | None = None
    normalized_name: str | None = None
    semantic_label: str | None = None
    name: str | None = None
    condition_kind: Literal['measurement', 'processing', 'state', 'unknown'] = 'unknown'
    measurement_role: Literal['experimental', 'calculated', 'reported_unknown'] | None = None
    footnote_marker: str | None = None
    scale_relation: Literal['display_equals_quantity_times_power', 'quantity_equals_display_times_power'] | None = None
    power: int | None = Field(default=None, ge=-30, le=30)
    content_type: Literal['scalar', 'range', 'uncertainty', 'multiple', 'value_with_qualifier', 'text', 'unknown'] | None = None
    decimal_style: Literal['dot', 'middle_dot'] = 'dot'
    qualifier_kind: Literal['measurement', 'processing', 'state', 'unknown'] = 'unknown'
    qualifier_name: str | None = None
    reason: str = Field(min_length=1)


class Axis(StrictModel):
    mode: Literal['same_row', 'same_column']
    labels: Scope


class Rule(StrictModel):
    rule_id: str = Field(min_length=1)
    definition_id: str = Field(min_length=1)
    targets: Scope
    axis: Axis | None = None


class ExceptionRule(StrictModel):
    exception_id: str = Field(min_length=1)
    base_rule_id: str = Field(min_length=1)
    operation: Literal['replace', 'supplement', 'exclude', 'unresolved']
    targets: Scope
    definition_id: str | None = None
    source_refs: list[str] = Field(min_length=1)
    source_quote: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class VisualSource(StrictModel):
    source_id: str = Field(pattern=r'^visual:')
    image_id: str
    kind: Literal['header', 'footnote', 'caption', 'label']
    text: str = Field(min_length=1)
    bbox: list[float] = Field(min_length=4, max_length=4)

    @model_validator(mode='after')
    def bounds(self):
        x0, y0, x1, y1 = self.bbox
        if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
            raise ValueError('visual bbox must be normalized to the supplied page')
        return self


class StructureInterpretation(StrictModel):
    schema_version: Literal['stage4t_table_structure.v2'] = STRUCTURE_VERSION
    table_id: str
    input_fingerprint: str
    direction: Literal['row_samples', 'column_samples', 'mixed', 'condition_series', 'unknown']
    data_scope: Scope
    excluded_scope: Scope = Field(default_factory=Scope)
    definitions: list[dict] = Field(default_factory=list)
    rules: list[dict] = Field(default_factory=list)
    exceptions: list[dict] = Field(default_factory=list)
    visual_sources: list[dict] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)


class StructureOutput(StructureInterpretation):
    """Typed schema for model output; offline parser quarantines nodes separately."""
    definitions: list[Definition] = Field(default_factory=list)
    rules: list[Rule] = Field(default_factory=list)
    exceptions: list[ExceptionRule] = Field(default_factory=list)
    visual_sources: list[VisualSource] = Field(default_factory=list)


def build_structure_input(table, *, context=None, images=()):
    """Freeze full OCR and image identities. Does not upload or read image values."""
    from stages.stage4t_table_interpretation import build_interpretation_input, interpretation_catalog
    payload = build_interpretation_input(table, context=context)
    payload['semantic_catalog'] = interpretation_catalog()
    manifest = []
    for image in images:
        # Caller supplies verified PDF page numbering; Stage0 page is zero based.
        if image['table_id'] != table.block_id or image['stage0_page'] != table.page:
            raise ValueError('image/table page mismatch; cross-page continuation needs explicit separate binding')
        path = Path(image['path']).resolve(strict=True)
        manifest.append({'image_id': image['image_id'], 'table_id': table.block_id,
                         'stage0_page': table.page, 'pdf_page': image['pdf_page'],
                         'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    if len({m['image_id'] for m in manifest}) != len(manifest):
        raise ValueError('duplicate image ID')
    payload['images'] = manifest
    payload['structure_protocol'] = STRUCTURE_VERSION
    payload['coordinate_policy'] = 'zero_based_inclusive; spans cover slots but each cell is read once; scopes are positions only'
    payload['input_fingerprint'] = fingerprint(payload)
    return payload


def render_structure_prompt():
    from prompt_loader import PromptLoader
    prompt = PromptLoader().render_stage_prompt(
        'polymer.stage4t.table_structure', StructureOutput,
        expected_stage='stage4t_table_interpretation', expected_output_schema=STRUCTURE_VERSION)
    require_structure_schema([{'role': 'system', 'content': prompt.text}])
    return prompt


def require_structure_schema(messages):
    """Fail before network access if the rendered wire prompt omitted its schema."""
    expected = json.dumps(StructureOutput.model_json_schema(), ensure_ascii=False, indent=2, sort_keys=True)
    system = '\n'.join(m['content'] for m in messages
                       if m.get('role') == 'system' and isinstance(m.get('content'), str))
    if expected not in system or '{{output_schema}}' in system:
        raise ValueError('Full Stage4T structure output schema missing from actual system message')


def prepare_structure_messages(request, image_paths):
    """Build reviewable multimodal messages offline. Never sends a request."""
    from stages.stage4t_compact_transport import compact_input
    wire, mapping = compact_input(request)
    parts = [{'type': 'text', 'text': json.dumps(wire, ensure_ascii=False, separators=(',', ':'))}]
    if set(image_paths) != {i['image_id'] for i in request['images']}:
        raise ValueError('image attachments do not match frozen manifest')
    for entry in request['images']:
        raw = Path(image_paths[entry['image_id']]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise ValueError('image changed after input preparation')
        mime = 'image/png' if raw.startswith(b'\x89PNG\r\n\x1a\n') else 'image/jpeg' if raw.startswith(b'\xff\xd8\xff') else None
        if mime is None:
            raise ValueError('only original PNG/JPEG page attachments supported')
        parts += [{'type':'text','text':'image_id=' + entry['image_id']},
                  {'type':'image_url','image_url':{'url':f'data:{mime};base64,' + base64.b64encode(raw).decode(), 'detail':'high'}}]
    messages = [{'role':'system','content':render_structure_prompt().text}, {'role':'user','content':parts}]
    require_structure_schema(messages)
    return messages, mapping


def select_cells(scope, cells):
    """Do not silently clip a region, split a merged cell, or accept overlap."""
    scope = Scope.model_validate(scope) if isinstance(scope, dict) else scope
    by_id = {c['cell_id']: c for c in cells}
    if len(by_id) != len(cells):
        raise ValueError('duplicate OCR cells')
    slots = {}
    cell_slots = defaultdict(set)
    for c in cells:
        for row in range(c['row_index'], c['row_index'] + c['row_span']):
            for col in range(c['column_index'], c['column_index'] + c['column_span']):
                if (row, col) in slots:
                    raise ValueError('overlapping OCR cells')
                slots[row, col] = c['cell_id']
                cell_slots[c['cell_id']].add((row, col))
    unknown = (set(scope.cell_ids) | set(scope.exclude_cell_ids)) - by_id.keys()
    if unknown:
        raise ValueError('unknown scope cell')
    selected = set(scope.cell_ids)
    max_row = max((p[0] for p in slots), default=-1)
    max_col = max((p[1] for p in slots), default=-1)
    for region in scope.regions:
        if region.row_end > max_row or region.column_end > max_col:
            raise ValueError('scope outside OCR grid')
        wanted = {(r, c) for r in range(region.row_start, region.row_end + 1)
                  for c in range(region.column_start, region.column_end + 1)}
        if wanted - slots.keys():
            raise ValueError('scope contains OCR grid holes')
        selected.update(slots[p] for p in wanted)
        for cid in {slots[p] for p in wanted}:
            occupied = cell_slots[cid]
            if not occupied <= wanted:
                raise ValueError('scope cuts a merged cell; use its explicit cell_id')
    return selected - set(scope.exclude_cell_ids)


def verified_visual_sources(records, request):
    """Validate provenance/geometry, not transcription accuracy or applicability."""
    images = {m['image_id']: m for m in request.get('images', [])}
    ids = [r.get('source_id') for r in records if isinstance(r, dict)]
    duplicated = {sid for sid, n in Counter(ids).items() if n > 1}
    sources, rejected = [], []
    for raw in records:
        try:
            source = VisualSource.model_validate(raw)
            image = images.get(source.image_id)
            if source.source_id in duplicated or not image or image['table_id'] != request['table_id']:
                raise ValueError('unknown, duplicate or wrong-table visual source')
            sources.append({**source.model_dump(), 'evidence_type': 'visual_transcription',
                            'image_sha256': image['sha256'], 'stage0_page': image['stage0_page'],
                            'pdf_page': image['pdf_page'], 'verification': 'provenance_only_not_text_accuracy'})
        except (ValueError, TypeError) as exc:
            rejected.append({'stage': 'visual_source', 'raw': deepcopy(raw), 'reason': str(exc)})
    return sources, rejected


def expand_structure(data, request):
    """Return existing v1 per-cell relations plus a separate local audit bundle."""
    from stages.stage4t_table_interpretation import validate_interpretation
    # Non-core explanation metadata must not discard otherwise valid relations.
    # Keep the original response in the audit; never repair business fields here.
    prepared = deepcopy(data)
    metadata_warnings = []
    if isinstance(prepared, dict) and isinstance(prepared.get('unresolved'), list):
        for index, item in enumerate(prepared['unresolved']):
            if isinstance(item, dict):
                prepared['unresolved'][index] = json.dumps(item, ensure_ascii=False, sort_keys=True)
                metadata_warnings.append({'field': f'unresolved.{index}',
                    'warning': 'object_preserved_as_json_string', 'raw': deepcopy(item)})
    top = StructureInterpretation.model_validate(prepared)
    frozen = deepcopy(request)
    expected = frozen.pop('input_fingerprint', None)
    if expected != fingerprint(frozen) or top.input_fingerprint != expected or top.table_id != request['table_id']:
        raise ValueError('structure input fingerprint/table mismatch')
    cells = request['cells']
    by_id = {c['cell_id']: c for c in cells}
    data_ids = select_cells(top.data_scope, cells) - select_cells(top.excluded_scope, cells)
    if not data_ids:
        raise ValueError('empty data scope')
    visual, rejected = verified_visual_sources(top.visual_sources, request)
    sources = {s['source_id']: s['text'] for s in [*request['sources'], *visual]}
    sources.update({cid: c['text'] for cid, c in by_id.items()})
    validation_input = deepcopy(request)
    validation_input['sources'] += visual
    legacy = {'table_id': top.table_id, 'direction': top.direction, 'axis_role': 'implicit_subject',
              'sample_binding_strategy': 'implicit_subject', 'header_assignments': [],
              'scoped_relations': [], 'requires_human_review': bool(visual or top.unresolved), 'warnings': []}
    definitions, rules, exceptions = {}, {}, defaultdict(list)
    per_cell, content, cell_exceptions = defaultdict(list), defaultdict(list), defaultdict(list)
    axis_values = defaultdict(list)

    def cite(refs, quote):
        if any(ref not in sources for ref in refs) or not any(quote in sources[ref] for ref in refs):
            raise ValueError('quote absent from cited source')

    def load_unique(items, model, key, destination):
        counts = Counter(x.get(key) for x in items if isinstance(x, dict))
        for raw in items:
            try:
                obj = model.model_validate(raw)
                ident = getattr(obj, key)
                if counts[ident] != 1:
                    raise ValueError('duplicate identifier')
                destination[ident] = obj
            except (ValueError, TypeError) as exc:
                rejected.append({'stage': key, 'raw': deepcopy(raw), 'reason': str(exc)})

    load_unique(top.definitions, Definition, 'definition_id', definitions)
    for ident, definition in list(definitions.items()):
        try:
            cite(definition.source_refs, definition.source_quote)
            if definition.kind == 'property' and not definition.role:
                raise ValueError('property requires role')
            if definition.kind == 'content' and not definition.content_type:
                raise ValueError('content type required')
            if definition.kind == 'content' and definition.content_type == 'value_with_qualifier' and not definition.qualifier_name:
                raise ValueError('qualifier name required')
            if definition.kind == 'scale':
                if definition.power is None or definition.scale_relation is None:
                    raise ValueError('scale requires direction and power')
                expression = definition.source_quote
                if definition.footnote_marker:
                    expression = re.sub(r'(10\s*\^\s*\{\s*[+-]?\d+)' + re.escape(definition.footnote_marker) + r'(\s*\})', r'\1\2', expression)
                from stages.stage4t_table_property import _unit_info
                expected_power = -definition.power if definition.scale_relation == 'display_equals_quantity_times_power' else definition.power
                if _unit_info([expression], None).get('scale_factor_exponent') != expected_power:
                    raise ValueError('scale relation not supported by full source expression')
        except (ValueError, TypeError) as exc:
            rejected.append({'stage': 'definition', 'raw': definition.model_dump(), 'reason': str(exc)})
            del definitions[ident]
    load_unique(top.rules, Rule, 'rule_id', rules)
    targets = {}
    for rid, rule in list(rules.items()):
        try:
            if rule.definition_id not in definitions:
                raise ValueError('missing or rejected definition')
            chosen = select_cells(rule.targets, cells)
            if not chosen or not chosen <= data_ids:
                raise ValueError('rule targets outside declared data scope')
            targets[rid] = chosen
        except (ValueError, TypeError) as exc:
            rejected.append({'stage': 'rule', 'raw': rule.model_dump(), 'reason': str(exc)})
            del rules[rid]
    exception_map = {}
    load_unique(top.exceptions, ExceptionRule, 'exception_id', exception_map)
    invalid_exceptions = defaultdict(list)
    for raw in top.exceptions:
        if not isinstance(raw, dict) or raw.get('exception_id') in exception_map:
            continue
        base_id = raw.get('base_rule_id')
        if base_id not in targets:
            continue
        affected = targets[base_id]
        try:
            affected = affected & select_cells(raw.get('targets', {}), cells)
        except (ValueError, TypeError):
            pass
        for cid in affected:
            invalid_exceptions[base_id, cid].append(deepcopy(raw))
    for ex in exception_map.values():
        chosen = None
        try:
            if ex.base_rule_id not in rules:
                raise ValueError('exception base missing')
            cite(ex.source_refs, ex.source_quote)
            chosen = select_cells(ex.targets, cells)
            if not chosen or not chosen <= targets[ex.base_rule_id]:
                raise ValueError('exception not a subset of its base rule')
            if ex.operation in {'replace', 'supplement'}:
                base = definitions[rules[ex.base_rule_id].definition_id]
                replacement = definitions.get(ex.definition_id)
                if not replacement or (base.kind, base.name) != (replacement.kind, replacement.name):
                    raise ValueError('exception changes unrelated kind/field')
                if rules[ex.base_rule_id].axis:
                    raise ValueError('axis replacement requires an explicit separate rule; do not guess labels')
            for cid in chosen:
                exceptions[ex.base_rule_id, cid].append(ex)
        except (ValueError, TypeError) as exc:
            rejected.append({'stage': 'exception', 'raw': ex.model_dump(), 'reason': str(exc)})
            # An explicitly declared but invalid local override cannot silently
            # fall back to a known-inapplicable public rule. Preserve raw cells.
            affected = targets.get(ex.base_rule_id, set())
            if chosen is not None:
                affected = affected & chosen
            for cid in affected:
                invalid_exceptions[ex.base_rule_id, cid].append(ex.model_dump())

    axis_cache = {}

    def emit(definition, cid, rid, axis=None, extra_refs=()):
        refs, quote = list(definition.source_refs), definition.source_quote
        if axis:
            if definition.kind not in {'subject', 'condition'}:
                raise ValueError('only subject/condition axes read labels')
            cache_key = fingerprint(axis.model_dump())
            if cache_key not in axis_cache:
                labels = select_cells(axis.labels, cells)
                if labels & data_ids:
                    raise ValueError('axis labels overlap measured data')
                index = defaultdict(list)
                for lid in sorted(labels):
                    label = by_id[lid]
                    start = label['row_index'] if axis.mode == 'same_row' else label['column_index']
                    span = label['row_span'] if axis.mode == 'same_row' else label['column_span']
                    for pos in range(start, start + span):
                        index[pos].append(label)
                axis_cache[cache_key] = index
            cell = by_id[cid]
            matches = axis_cache[cache_key].get(cell['row_index'] if axis.mode == 'same_row' else cell['column_index'], [])
            if len(matches) != 1 or not matches[0]['text'].strip():
                raise ValueError('axis label missing or ambiguous')
            quote = matches[0]['text']
            refs = [matches[0]['cell_id'], *refs]
            if definition.kind == 'condition':
                from stages.stage4t_table_property import _unit_info
                unit = _unit_info([definition.source_quote], None).get('unit_raw')
                if not unit:
                    match = re.search(r'\((s|sec|min|h|ms|μs|µs|Hz|kHz|MHz|nm|μm|°C|K|%)\)', definition.source_quote)
                    unit = match[1] if match else None
                axis_values[cid].append({'name': definition.name, 'condition_kind': definition.condition_kind,
                    'value_raw': quote, 'unit_raw': unit, 'label_cell_id': matches[0]['cell_id'],
                    'source_refs': refs, 'rule_id': rid})
        node = {'source_refs': list(dict.fromkeys([*refs, *extra_refs])), 'source_quote': quote,
                'target_cell_ids': [cid], 'reason': definition.reason}
        if definition.kind == 'property':
            node.update(role=definition.role, confidence=0.5)
            if definition.normalized_name:
                node['normalized_name'] = definition.normalized_name
            if definition.semantic_label:
                node['semantic_label'] = definition.semantic_label
            field = 'header_assignments'
        elif definition.kind == 'content':
            content[cid].append({'rule_id': rid, **definition.model_dump()})
            return
        else:
            node['kind'] = definition.kind
            for name in ('name', 'measurement_role', 'footnote_marker'):
                if getattr(definition, name):
                    node[name] = getattr(definition, name)
            node['condition_kind'] = definition.condition_kind
            field = 'scoped_relations'
        isolated = {**legacy, 'header_assignments': [], 'scoped_relations': [], field: [node]}
        validate_interpretation(isolated, validation_input)
        legacy[field].append(node)
        per_cell[cid].append({'rule_id': rid, 'definition_id': definition.definition_id,
                              'kind': definition.kind, 'name': definition.name,
                              'source_refs': node['source_refs'], 'source_quote': quote})

    blocked = defaultdict(set)
    excluded = defaultdict(set)
    for rid in sorted(rules):
        rule = rules[rid]
        base = definitions[rule.definition_id]
        for cid in sorted(targets[rid]):
            if invalid_exceptions[rid, cid]:
                blocked[cid].add(base.kind + ':' + str(base.name or ''))
                cell_exceptions[cid].extend(invalid_exceptions[rid, cid])
                continue
            overrides = sorted(exceptions[rid, cid], key=lambda e: e.exception_id)
            cell_exceptions[cid].extend(e.model_dump() for e in overrides)
            destructive = [e for e in overrides if e.operation in {'replace', 'exclude', 'unresolved'}]
            if len(destructive) > 1 or any(e.operation == 'unresolved' for e in destructive):
                blocked[cid].add(base.kind + ':' + str(base.name or ''))
                rejected.append({'stage': 'exception_conflict', 'cell_id': cid, 'rule_id': rid,
                                 'raw': [e.model_dump() for e in overrides], 'reason': 'overlapping exceptions unresolved'})
                continue
            chosen = base
            if destructive:
                if destructive[0].operation == 'exclude':
                    excluded[cid].add(base.kind + ':' + str(base.name or ''))
                    continue
                chosen = definitions[destructive[0].definition_id]
            selected = [(chosen, destructive[0] if destructive else None)]
            selected += [(definitions[e.definition_id], e) for e in overrides if e.operation == 'supplement']
            for definition, ex in selected:
                try:
                    emit(definition, cid, rid, rule.axis,
                         [*ex.source_refs] if ex else ())
                except (ValueError, TypeError) as exc:
                    rejected.append({'stage': 'cell_relation', 'cell_id': cid, 'rule_id': rid, 'reason': str(exc)})
    if rejected:
        legacy['warnings'].append('structure_relations_quarantined')
        legacy['requires_human_review'] = True
    if visual:
        legacy['warnings'].append('visual_transcription_requires_semantic_review')
    if metadata_warnings:
        legacy['warnings'].append('structure_explanation_metadata_preserved_with_warning')
    suppressed = {}
    for cid, fields in excluded.items():
        active = {r['kind'] + ':' + str(r['name'] or '') for r in per_cell[cid]}
        if content.get(cid):
            active.add('content:')
        suppressed[cid] = sorted(fields - active)
    audit = {'expander_version': EXPANDER_VERSION, 'table_id': top.table_id,
             'input_fingerprint': expected, 'request_input': deepcopy(request),
             'raw_structure': deepcopy(data), 'visual_sources': visual, 'rejected_items': rejected,
             'metadata_warnings': metadata_warnings,
             'data_cell_ids': sorted(data_ids), 'cell_rules': dict(per_cell), 'content_rules': dict(content),
             'cell_exceptions': dict(cell_exceptions),
             'axis_values': dict(axis_values),
             'blocked_fields': {cid: sorted(fields) for cid, fields in blocked.items()},
             'suppressed_fields': suppressed,
             'unresolved': top.unresolved, 'completeness': 'structural_only_not_semantic_completeness'}
    audit['audit_sha256'] = fingerprint(audit)
    return legacy, audit


def structure_audit_valid(audit, table, *, context=None):
    """Check table/input/version and replayed local rules, not scientific accuracy."""
    from stages.table_grid import table_cells_for
    if not isinstance(audit, dict) or audit.get('expander_version') != EXPANDER_VERSION:
        return False
    frozen = deepcopy(audit)
    digest = frozen.pop('audit_sha256', None)
    if fingerprint(frozen) != digest or audit.get('table_id') != table.block_id:
        return False
    request = audit.get('request_input', {})
    cells = [{k: getattr(c, k) for k in ('cell_id', 'row_index', 'column_index', 'row_span', 'column_span', 'text')}
             for c in table_cells_for(table)]
    keys = ('cell_id', 'row_index', 'column_index', 'row_span', 'column_span', 'text')
    if not cells or cells != [{k: c.get(k) for k in keys} for c in request.get('cells', [])]:
        return False
    if request.get('page') != table.page or request.get('caption') != table.caption:
        return False
    note_sources = {s['source_id']: s['text'] for s in request.get('sources', [])}
    expected_notes = {f'{table.block_id}:note:{i}': text for i, text in enumerate(table.table_notes)}
    if {sid: text for sid, text in note_sources.items() if sid.startswith(table.block_id + ':note:')} != expected_notes:
        return False
    if context is not None:
        from stages.stage4t_table_interpretation import build_interpretation_input
        current = build_interpretation_input(table, context=context)
        if any(request.get(key) != current.get(key) for key in ('sources', 'context', 'subject_catalog')):
            return False
    expected = deepcopy(request)
    digest = expected.pop('input_fingerprint', None)
    if fingerprint(expected) != digest:
        return False
    try:
        _, replayed = expand_structure(audit['raw_structure'], request)
        return replayed['audit_sha256'] == audit['audit_sha256']
    except (KeyError, TypeError, ValueError):
        return False


def replay_visual_sources(audit, table):
    """Downstream reconstructs evidence from table-level input, not candidate claims."""
    if not structure_audit_valid(audit, table):
        return []
    request = audit['request_input']
    sources, _ = verified_visual_sources(audit.get('raw_structure', {}).get('visual_sources', []), request)
    return sources


def apply_structure_table(table, shadow, data, request, *, context=None):
    """Explicit v2 application; live entry points remain on the v1 protocol."""
    from stages.stage4t_interpretation_apply import apply_table_interpretation
    from stages.stage4t_table_interpretation import build_interpretation_input
    from stages.stage4t_table_property import _observation
    from stages.table_grid import table_cells_for
    from stages.value_normalization import normalize_observation
    current = build_interpretation_input(table, context=context)
    for field in ('table_id', 'page', 'caption', 'cells', 'sources', 'subject_catalog', 'context'):
        if request.get(field) != current.get(field):
            raise ValueError('structure request differs from current OCR/context: ' + field)
    legacy, expansion = expand_structure(data, request)
    selected = set(expansion['data_cell_ids'])
    # The v2 data region is explicit. Do not retain inferred axes/metadata from v1.
    prepared = deepcopy(shadow)
    prepared['observations'] = [_observation(table_id=table.block_id, cell=c, sample_label=None,
        property_raw='', property_name=None, semantic_label=None, property_variant=None,
        conditions={}, unit={}, direction=data['direction'])
        for c in table_cells_for(table) if c.cell_id in selected]
    result, audit = apply_table_interpretation(table, prepared, legacy, context=context,
                                              _structure_sources=expansion['visual_sources'])
    for candidate in result['observations']:
        cid = candidate['cell_id']
        candidate['structure_trace'] = {
            'input_fingerprint': expansion['input_fingerprint'],
            'rules': deepcopy(expansion['cell_rules'].get(cid, [])),
            'content_rules': deepcopy(expansion['content_rules'].get(cid, [])),
            'exceptions': deepcopy(expansion['cell_exceptions'].get(cid, [])),
            'unresolved_fields': expansion['blocked_fields'].get(cid, []),
            'suppressed_fields': expansion['suppressed_fields'].get(cid, []),
            'evidence_accuracy': 'not_proved_by_offline_validation'}
        candidate['confidence'] = None
        candidate['interpretation_confidence'] = None
        candidate['confidence_source'] = 'structure_adapter_no_model_confidence'
        condition_axes = expansion['axis_values'].get(cid, [])
        if condition_axes:
            candidate['condition_axes'] = deepcopy(condition_axes)
            for axis in condition_axes:
                name = axis['name']
                if name in candidate.get('conditions', {}) and axis['unit_raw']:
                    candidate['conditions'][name] = axis['value_raw'] + ' ' + axis['unit_raw']
        subjects = candidate.get('subject_relations', [])
        labels = sorted({r['source_quote'] for r in subjects})
        if len(labels) == 1:
            candidate['sample_label_raw'] = labels[0]
        elif len(labels) > 1:
            candidate['sample_label_raw'] = None
            candidate.setdefault('warnings', []).append('structure_subject_conflict')
        contents = expansion['content_rules'].get(cid, [])
        signatures = {fingerprint({k: d[k] for k in ('content_type', 'decimal_style', 'qualifier_kind', 'qualifier_name')})
                      for d in contents}
        if len(signatures) > 1:
            candidate.setdefault('warnings', []).append('structure_content_conflict')
            candidate.setdefault('unresolved_metadata_fields', []).append('content')
        elif contents:
            definition = sorted(contents, key=lambda d: d['definition_id'])[0]
            try:
                projection = project_content(candidate['value_raw'], definition)
                if projection:
                    candidate['value_projection'] = projection
                    candidate['value_kind'] = {'scalar': 'numeric_scalar', 'range': 'numeric_range',
                        'multiple': 'numeric_multiple', 'uncertainty': 'numeric_with_uncertainty'}[projection['parsed_kind']]
                    if projection['qualifier']:
                        qualifier = projection['qualifier']
                        from stages.stage4t_table_interpretation import ScopedRelation
                        relation = ScopedRelation(kind='condition', name=qualifier['name'],
                            condition_kind=qualifier['kind'], source_refs=[cid],
                            source_quote=qualifier['text'], target_cell_ids=[cid], reason='Explicit OCR parenthetical qualifier')
                        from stages.stage4t_scoped_relations import apply_scoped_metadata
                        apply_scoped_metadata(candidate, [relation], append=True)
                elif definition['content_type'] == 'text':
                    candidate['value_kind'] = 'text'
            except (ValueError, TypeError) as exc:
                candidate.setdefault('warnings', []).append('structure_content_unresolved:' + str(exc))
        # Do not let a different public rule silently fill a field explicitly unresolved by exceptions.
        for field in sorted(set(expansion['blocked_fields'].get(cid, [])) |
                            set(expansion['suppressed_fields'].get(cid, []))):
            kind, _, name = field.partition(':')
            if kind == 'condition':
                candidate.setdefault('conditions', {}).pop(name, None)
            elif kind == 'measurement_role':
                candidate['measurement_role'] = 'reported_unknown'
            elif kind in {'unit', 'scale'}:
                prefix = 'unit_' if kind == 'unit' else 'scale_factor_'
                for key in list(candidate):
                    if key.startswith(prefix):
                        candidate.pop(key)
                candidate[prefix + 'status'] = 'unresolved'
                candidate.setdefault('unresolved_metadata_fields', []).append(prefix.rstrip('_'))
            elif kind == 'property':
                candidate['property_name_normalized'] = None
                candidate['semantic_label'] = None
                candidate['semantic_status'] = 'unmapped'
            elif kind == 'subject':
                candidate['sample_label_raw'] = None
                candidate['subject_relations'] = []
            elif kind == 'content':
                candidate.pop('value_projection', None)
                candidate.setdefault('unresolved_metadata_fields', []).append('content')
            candidate.setdefault('warnings', []).append('structure_exception_unresolved:' + field)
        candidate.update(normalize_observation(candidate))
    result['structure_audit'] = expansion
    result['structure_unresolved'] = expansion['unresolved']
    result['structure_coverage'] = {
        'data_cells': len(selected), 'retained_cells': len({o['cell_id'] for o in result['observations']}),
        'property_interpreted_cells': sum(bool(o.get('property_name_normalized') or o.get('semantic_label')) for o in result['observations']),
        'property_labeled_cells': sum(bool(o.get('property_source_relations')) for o in result['observations']),
        'numeric_projected_cells': sum('value_projection' in o for o in result['observations']),
        'quarantined_items': len(expansion['rejected_items']),
        'scope': 'retention_and_rule_application_not_property_recall'}
    if 'input_cell_inventory' in result:
        from stages.table_value_inventory import capture_coverage
        result['input_capture_coverage'] = capture_coverage(result['input_cell_inventory'], result['observations'])
    audit['structure_coverage'] = result['structure_coverage']
    return result, audit


def project_content(raw, definition):
    """Return an OCR substring projection. Never scan arbitrary prose for numbers."""
    from stages.final_unit_conversion import parse_numeric
    kind = definition['content_type']
    if kind in {'text', 'unknown'}:
        return None
    text, start, end, qualifier = raw, 0, len(raw), None
    if kind == 'value_with_qualifier':
        match = re.fullmatch(r'\s*(?P<value>[+-]?\d+(?:[.·]\d+)?)\s*\((?P<qualifier>[^()]*)\)\s*', raw)
        if not match:
            raise ValueError('unsupported value/qualifier shape')
        numeric_qualifier = re.sub(r'(?<=\d)·(?=\d)', '.', match['qualifier'])
        if parse_numeric(numeric_qualifier) is not None:
            raise ValueError('numeric parenthesis may be another reported value, not a qualifier')
        text = match['value']
        start, end = match.span('value')
        qualifier = {'name': definition['qualifier_name'], 'kind': definition['qualifier_kind'],
                     'text': match['qualifier'], 'source_start': match.start('qualifier'), 'source_end': match.end('qualifier')}
    numeric = text
    if definition['decimal_style'] == 'middle_dot':
        # Only digit-middle-dot-digit inside a complete numeric shape; not x·10.
        numeric = re.sub(r'(?<=\d)·(?=\d)', '.', numeric)
    expected = {'multiple': 'multiple', 'scalar': 'scalar', 'range': 'range', 'uncertainty': 'uncertainty',
                'value_with_qualifier': 'scalar'}[kind]
    parsed = parse_numeric(numeric, 'numeric_multiple' if kind == 'multiple' else '')
    if not parsed or parsed['kind'] != expected:
        raise ValueError('content type differs from complete OCR expression')
    return {'source_start': start, 'source_end': end, 'source_text': text, 'numeric_text': numeric,
            'decimal_style': definition['decimal_style'], 'parsed_kind': parsed['kind'],
            'definition_id': definition['definition_id'], 'rule_id': definition['rule_id'], 'qualifier': qualifier}


def refresh_structure_derivation(item, blocks, fallback):
    """Stage6 rechecks OCR projections instead of reparsing a mixed whole cell."""
    from stages.source_context_semantics import field
    from stages.table_grid import table_cells_for
    from stages.stage4t_table_interpretation import build_interpretation_input, validate_interpretation
    from stages.stage4t_scoped_relations import apply_scoped_metadata
    from stages.value_normalization import normalize_observation
    bundle = (getattr(item, 'candidate_trace', None) or {}).get('stage4t_relations', {})
    projection = bundle.get('value_projection')
    if projection is None or not bundle.get('structure_trace'):
        return fallback
    annotation = {k: deepcopy(v) for k, v in (fallback or {}).items()
                  if k not in {'actual_values', 'candidate_values', 'uncertainty'}}
    annotation.update(status='review_required', warnings=[], numeric_origin='stage4t_ocr_projection',
                      structure_projection=deepcopy(projection), structure_expander_version=EXPANDER_VERSION)
    try:
        definitions = bundle['structure_trace'].get('content_rules', [])
        definitions = [d for d in definitions if d['definition_id'] == projection['definition_id']
                       and d['rule_id'] == projection['rule_id']]
        if not definitions or project_content(item.value_raw, definitions[0]) != projection:
            raise ValueError('projection no longer matches its source definition')
        anchored = []
        for evidence in item.evidence:
            block = blocks.get(field(evidence, 'block_id'))
            locator = field(evidence, 'table_locator')
            if block is None or block.type != 'table' or not locator:
                continue
            for cell in table_cells_for(block):
                if cell.cell_id == field(locator, 'cell_id') and cell.text.strip() == item.value_raw:
                    anchored.append((block, cell))
        if not anchored:
            raise ValueError('projection original cell not present in current Stage0')
        table, cell = anchored[0]
        context = {'referencing_text': [{'block_id': b.block_id, 'page': b.page, 'text': b.text}
                   for b in blocks.values() if b.type in {'text', 'footnote'} and b.text]}
        request = build_interpretation_input(table, context=context)
        request['sources'].extend(deepcopy(bundle.get('visual_evidence', [])))
        legacy = {'table_id': table.block_id, 'direction': 'unknown', 'axis_role': 'implicit_subject',
                  'sample_binding_strategy': 'implicit_subject', 'requires_human_review': False,
                  'scoped_relations': bundle.get('scoped_relations', [])}
        validated = validate_interpretation(legacy, request)
        candidate = {'cell_id': cell.cell_id, 'value_raw': item.value_raw, 'value_projection': projection,
            'value_kind': {'scalar': 'numeric_scalar', 'range': 'numeric_range', 'multiple': 'numeric_multiple',
                           'uncertainty': 'numeric_with_uncertainty'}[projection['parsed_kind']],
            'unit_raw': getattr(item, 'unit_raw', None), 'unit_normalized': getattr(item, 'unit_normalized', None),
            'unresolved_metadata_fields': deepcopy(bundle.get('unresolved_metadata_fields', []))}
        apply_scoped_metadata(candidate, validated.scoped_relations)
        normalized = normalize_observation(candidate)
        annotation.update(numeric_kind=projection['parsed_kind'], actual_unit=normalized.get('normalized_unit'),
                          scale_exponent=normalized.get('scale_factor_exponent'))
        values = normalized.get('restored_values')
        if normalized['normalization_status'] == 'normalized' and values is not None:
            annotation.update(status='normalized', actual_values=values)
            if normalized.get('normalized_uncertainty') is not None:
                annotation['uncertainty'] = normalized['normalized_uncertainty']
        else:
            annotation['warnings'] = [normalized.get('normalization_warning', 'structure_value_requires_review')]
            if values is not None:
                annotation['candidate_values'] = values
    except (KeyError, TypeError, ValueError) as exc:
        annotation['warnings'] = ['structure_projection_rejected:' + str(exc)]
    return annotation
