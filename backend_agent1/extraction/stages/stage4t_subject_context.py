"""Read-only material/sample summaries and addressable table evidence."""
from copy import deepcopy
import hashlib
import json
import re
from pathlib import Path

from stages.table_grid import table_cells_for


def _brief_evidence(evidence):
    if not isinstance(evidence, dict):
        return deepcopy(evidence)
    result = {k: deepcopy(evidence[k]) for k in ('block_id', 'page', 'source_type', 'source_sentence', 'table_locator') if k in evidence}
    quote = result.get('source_sentence')
    if isinstance(quote, str) and len(quote) > 480:
        result['source_sentence'] = quote[:480]
        result['quote_truncated'] = True
    return result


def subject_summary(stage2, stage3):
    entities = [{k: deepcopy(e[k]) for k in (
        'entity_id', 'polymer_name', 'canonical_name', 'normalized_name', 'display_name',
        'source_names', 'evidence') if k in e}
        for e in stage2.get('polymer_entities', [])]
    samples = []
    for sample in stage3.get('samples', []):
        item = {k: deepcopy(sample[k]) for k in (
            'sample_id', 'refers_to_entity', 'polymer_name', 'sample_label_raw',
            'sample_label_aliases', 'sample_kind', 'state_description', 'evidence') if k in sample}
        item['processes'] = [{k: deepcopy(step[k]) for k in (
            'step_id', 'process_type', 'input_sample_ids', 'output_sample_ids', 'parameters', 'evidence') if k in step}
            for step in stage3.get('process_steps', [])
            if sample.get('sample_id') in (step.get('output_sample_ids') or [])]
        samples.append(item)
    for item in [*entities, *samples]:
        if 'evidence' in item:
            item['evidence'] = _brief_evidence(item['evidence'])
        for step in item.get('processes', []):
            if 'evidence' in step:
                step['evidence'] = _brief_evidence(step['evidence'])
    return {'entities': entities, 'samples': samples,
            'policy': 'Candidates only. Match source evidence and state; never force a sample choice.'}


def load_subject_summary(directory: Path, document_id=None, fallback_directory: Path | None = None):
    documents, hashes, warnings = [], {}, []
    for name in ('stage2_entities.json', 'stage3_process.json'):
        path = directory / name
        if not path.is_file() and fallback_directory is not None:
            path = fallback_directory / name
        if not path.is_file():
            documents.append({})
            hashes[name] = None
            warnings.append('subject_context_missing:' + name)
            continue
        raw = path.read_bytes()
        hashes[name] = hashlib.sha256(raw).hexdigest()
        doc = json.loads(raw)
        if document_id is not None and doc.get('document_id') != document_id:
            warnings.append('subject_context_document_mismatch:' + name)
            doc = {}
        documents.append(doc)
    result = subject_summary(*documents)
    result['warnings'] = warnings
    return result, hashes


def evidence_sources(table, context=None):
    """Stable IDs distinguish caption, individual notes, cells and text blocks."""
    sources = [{'source_id': c.cell_id, 'kind': 'cell', 'text': c.text}
               for c in table_cells_for(table)]
    if table.caption:
        sources.append({'source_id': table.block_id + ':caption', 'kind': 'caption', 'text': table.caption})
    for i, text in enumerate(table.table_notes):
        sources.append({'source_id': f'{table.block_id}:note:{i}', 'kind': 'footnote', 'text': text})
    for section in ('preceding_text', 'following_text', 'referencing_text', 'footnotes'):
        for item in (context or {}).get(section, []):
            sid = item.get('block_id')
            if 'table_note_index' in item:
                sid = f"{table.block_id}:note:{item['table_note_index']}"
            if sid and item.get('text') and not any(s['source_id'] == sid for s in sources):
                sources.append({'source_id': sid, 'kind': 'footnote' if section == 'footnotes' else 'text',
                                'text': item['text']})
    return sources


def _label_present(label, text):
    if not label or not str(label).strip():
        return False
    return re.search(r'(?<!\w)' + re.escape(str(label).strip()) + r'(?!\w)', text, re.I) is not None


def state_conflict(candidate, sample):
    """Only explicit physical state evidence, not a test solvent or temperature."""
    texts = [r['source_quote'] for r in candidate.get('subject_relations', [])]
    texts += [r['source_quote'] for r in candidate.get('scoped_relations', [])
              if r.get('kind') == 'condition' and r.get('condition_kind') == 'state']
    text = ' '.join(texts)
    known = str(sample.get('state_description') or '')
    states = {'film': r'\bfilm\b|薄膜|干膜', 'liquid': r'\bliquid\b|液态',
              'solution': r'\bsolution\b|溶液', 'powder': r'\bpowder\b|粉末'}
    source_states = {k for k,p in states.items() if re.search(p, text, re.I)}
    sample_states = {k for k,p in states.items() if re.search(p, known, re.I)}
    return bool(source_states and sample_states and source_states.isdisjoint(sample_states))


def resolve_subject(candidate, catalog):
    relations = candidate.get('subject_relations') or []
    if not relations:
        return None
    text = ' | '.join(r['source_quote'] for r in relations)
    samples = catalog.get('samples', [])
    entities = catalog.get('entities', [])
    matched_entities = {e['entity_id'] for e in entities if any(_label_present(label, text)
        for label in [e.get('polymer_name'), e.get('canonical_name'), e.get('normalized_name'), e.get('display_name'), *(e.get('source_names') or [])])}
    matched = [s for s in samples if any(_label_present(label, text) for label in
        [s.get('sample_label_raw'), s.get('polymer_name'), *(s.get('sample_label_aliases') or [])])]
    matched_entities.update(s['refers_to_entity'] for s in matched if s.get('refers_to_entity'))
    entity_names = [label for e in entities for label in [e.get('polymer_name'), e.get('canonical_name'), e.get('normalized_name'),
                    e.get('display_name'), *(e.get('source_names') or [])]]
    def specific_sample(s):
        labels = [s.get('sample_label_raw'), *(s.get('sample_label_aliases') or [])]
        # Material names are not a sample identifier, even if only one sample exists.
        return any(_label_present(label, text) and str(label).casefold() not in
                   {str(n).casefold() for n in entity_names if n} for label in labels if label)
    compatible = [s for s in matched if specific_sample(s) and not state_conflict(candidate, s)]
    # An explicitly stated processing parameter must have a matching declared
    # process on this sample. Unknown processing identity stays unresolved.
    processing = [r for r in candidate.get('scoped_relations', [])
                  if r.get('kind') == 'condition' and r.get('condition_kind') == 'processing']
    if processing:
        compatible = [s for s in compatible if all(any(
            r['source_quote'] == str(value)
            for step in s.get('processes', []) for value in step.get('parameters', {}).values()) for r in processing)]
    ids = sorted({s['sample_id'] for s in compatible})
    result = {'status': 'unmatched_sample', 'label': text, 'matches': ids,
              'confidence': 0.0, 'anchors': ['scoped_subject_quote'],
              'entity_id': next(iter(matched_entities)) if len(matched_entities) == 1 else None}
    # Candidate IDs cannot remove ambiguity present in the source evidence.
    proposed = {sid for r in relations for sid in r.get('candidate_sample_ids', [])}
    proposed_entities = {eid for r in relations for eid in r.get('candidate_entity_ids', [])}
    proposals_agree = (not proposed or proposed == set(ids)) and (not proposed_entities or proposed_entities == matched_entities)
    if len(ids) == 1 and proposals_agree:
        sample = next(s for s in compatible if s['sample_id'] == ids[0])
        result.update(status='matched', sample_id=ids[0], entity_id=sample.get('refers_to_entity'),
                      basis='scoped_subject_label_and_state', confidence=0.85)
    elif len(ids) > 1:
        result['status'] = 'ambiguous_sample'
    elif matched and not compatible:
        result['anchors'].append('sample_state_or_processing_conflict')
    if not proposals_agree:
        result['anchors'].append('identity_proposal_conflict')
    if result['status'] == 'unmatched_sample' and result['entity_id']:
        result['status'] = 'entity_matched'
    return result
