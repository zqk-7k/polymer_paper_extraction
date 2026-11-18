"""Use the proven receiver before R/Stage5, with source-bound table evidence."""
from copy import deepcopy
from common import digest
from evidence_handoff import prepare

def prepare_tables(tasks, raw):
    augmented = deepcopy(raw)
    blocks = {b['block_id']: b for b in augmented['elements']}
    prepared = []
    for task in tasks:
        tid = task['table_id']
        for source in task['packet'].get('evidence_sources', []):
            sid, text = source['source_id'], source.get('text', '')
            if sid in blocks:
                assert blocks[sid].get('text', '') == text, 'Conflicting evidence address'
                continue
            # Only literal notes already present on this source table may be registered.
            assert source.get('kind') == 'ocr_footnote' and source.get('table_id') == tid
            assert text in task['source_table'].get('notes', []), 'Unbound table note'
            binding={k: source[k] for k in ('marker','page_1based','source_pdf_sha256',
                                            'source_kind','source_sha256','json_pointer') if k in source}
            block = {'block_id': sid, 'type': 'text', 'text': text,
                     'page': task['source_table'].get('page', 0), 'table_id': tid,
                     'source_provenance': {'kind': 'literal_ocr_table_note',
                         'table_id': tid, 'content_sha256': digest(text),
                         'pdf_binding': binding or 'hash_marker_page_binding_not_supplied'}}
            augmented['elements'].append(block)
            blocks[sid] = block
        ready, _ = prepare(task, augmented, [])
        prepared.append(ready)
    return prepared, augmented

def receive(data, task, raw, identity, catalog, stage):
    from replay import adapt_fixed
    from field_groups import owner
    source = deepcopy(task)
    source['_owner_identity'] = identity
    rows, audit = adapt_fixed(data, source, raw, identity, catalog, 'new')
    for row in rows:
        row['field_owner_stage'] = owner(row['target_id']) if row.get('target_id') else None
        row['source_processing_stage'] = stage
    return rows, audit
