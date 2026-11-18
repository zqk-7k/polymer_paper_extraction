"""Rebuild source observations without requiring complete Stage3–6 or model calls."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from stages.source_table_extraction import build_source_extraction
from tools.source_extraction_export import render_source_report


def rebuild(input_root, publication_root, output_root, documents=None):
    input_root, publication_root, output_root = (Path(p).resolve() for p in (input_root, publication_root, output_root))
    if output_root.exists() or any(output_root == p or p in output_root.parents or output_root in p.parents for p in (input_root, publication_root)):
        raise ValueError("Output must be a new separate directory")
    sources = sorted(input_root.glob('reference_no_*/stage0_blocks.json'))
    if documents:
        sources = [p for p in sources if p.parent.name in documents]
        if {p.parent.name for p in sources} != set(documents):
            raise ValueError("Requested document source is missing")
    if not sources:
        raise ValueError("No source documents")
    snapshots = {p: p.read_bytes() for p in sources}
    for path in sources:
        pub = publication_root / path.parent.name / 'measurement_publication.json'
        if pub.is_file():
            snapshots[pub] = pub.read_bytes()
            merged = pub.with_name('final.json')
            if merged.is_file():
                snapshots[merged] = merged.read_bytes()
    output_root.mkdir(parents=True)
    results, counts = [], Counter()
    for path in sources:
        doc = path.parent.name
        pub = publication_root / doc / 'measurement_publication.json'
        publication = json.loads(snapshots[pub]) if pub in snapshots else None
        merged = pub.with_name('final.json')
        if publication is not None and 'source_evidence_catalog' not in publication and merged in snapshots:
            payload = json.loads(snapshots[merged])
            if payload.get('document_id') != doc:
                raise ValueError('Merged evidence belongs to another document')
            publication['source_evidence_catalog'] = payload.get('evidence') or []
        data = build_source_extraction(json.loads(snapshots[path]), publication)
        target = output_root / doc
        target.mkdir()
        (target / 'source_extraction.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        render_source_report(data, target / 'report.html')
        counts.update(data['counts'])
        results.append({'document_id': doc, 'status': 'source_rechecked', 'counts': data['counts']})
        print(json.dumps(results[-1]), flush=True)
    unchanged = all(p.read_bytes() == v for p, v in snapshots.items())
    code = Path(__file__).resolve().parents[1]
    rules = [code / ('stages/' + name + '.py') for name in ('source_table_extraction','source_table_layout','source_field_enrichment','source_claim_recovery','source_text_extraction','source_text_reviews')]
    rules.append(code / 'config/source_text_reviews.v1.json')
    rules += [code / 'tools/source_extraction_export.py', code / 'tools/source_evidence_view.py', Path(__file__).resolve()]
    summary = {'schema_version': 'source_extraction_rebuild.v1', 'documents': results, 'counts': dict(counts),
               'original_inputs_unchanged': unchanged, 'api_requests': 0,
               'input_hashes': {str(p): hashlib.sha256(v).hexdigest() for p, v in snapshots.items()},
               'rule_hashes': {str(p.relative_to(code)): hashlib.sha256(p.read_bytes()).hexdigest() for p in rules}}
    (output_root / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    if not unchanged:
        raise ValueError("Inputs changed during rebuild")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('input-root', 'publication-root', 'output-root'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--documents', nargs='+')
    rebuild(**vars(parser.parse_args()))


if __name__ == '__main__':
    main()
