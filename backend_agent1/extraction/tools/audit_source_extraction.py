"""Score source-first observations against labels selected from original tables."""
import argparse
import hashlib
import json
from pathlib import Path


def score(labels, observations):
    indexed = {(r['document_id'], r['source_cell_id']): r for r in observations}
    rows = []
    for label in labels:
        actual = indexed.get((label['document_id'], label['source_cell_id']))
        failures = []
        if actual is None:
            failures.append('observation_missing')
        else:
            for field, expected in label['expected'].items():
                if actual.get(field) != expected:
                    failures.append(field)
        rows.append({'document_id': label['document_id'], 'source_cell_id': label['source_cell_id'],
                     'category': label['category'], 'present': actual is not None, 'correct': not failures,
                     'usable': actual is not None and actual['extraction_status'] == 'usable', 'failed_fields': failures})
    return {'labelled_cells': len(rows), 'present_cells': sum(r['present'] for r in rows),
            'correct_cells': sum(r['correct'] for r in rows), 'incorrect_cells': sum(r['present'] and not r['correct'] for r in rows),
            'missing_cells': sum(not r['present'] for r in rows),
            'usable_correct_cells': sum(r['correct'] and r['usable'] for r in rows), 'rows': rows,
            'scope': 'source-table development review; not independent human blind labels or population accuracy'}


def audit(labels_path, extraction_root, output_root):
    labels_path, extraction_root, output_root = map(Path, (labels_path, extraction_root, output_root))
    if output_root.exists():
        raise ValueError('Output exists')
    labels = json.loads(labels_path.read_text(encoding='utf-8'))
    for path, expected in labels['source_hashes'].items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
            raise ValueError('Reviewed source changed')
    observations = []
    for path in extraction_root.glob('reference_no_*/source_extraction.json'):
        observations.extend(json.loads(path.read_text(encoding='utf-8'))['observations'])
    result = score(labels['labels'], observations)
    result['unreviewed_observations'] = len(observations) - result['present_cells']
    output_root.mkdir(parents=True)
    (output_root / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('labels-path', 'extraction-root', 'output-root'):
        p.add_argument('--' + name, type=Path, required=True)
    result = audit(**vars(p.parse_args()))
    print(json.dumps({k: v for k, v in result.items() if k != 'rows'}))


if __name__ == '__main__':
    main()
