"""Read handwritten post-seal notes bound to a delivered immutable version.

No candidate edits, chemical inference, reference comparison or scoring.
"""
import hashlib, json
from pathlib import Path
from .storage import APP, data_root, digest, file_hash

CONTRACT = 'identity-postseal-reader-notes/1.0'


def bounded_bytes(path, limit):
    if path.stat().st_size > limit:
        raise ValueError('NOTE_BINDING_FILE_SIZE_LIMIT')
    data = path.read_bytes()
    if len(data) > limit:
        raise ValueError('NOTE_BINDING_FILE_SIZE_LIMIT')
    return data


def bounded_json(path, limit):
    return json.loads(bounded_bytes(path, limit))


def within(run, relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError('NOTE_PATH_REJECTED')
    target = (run / relative).resolve()
    if not target.is_relative_to(run.resolve()):
        raise ValueError('NOTE_PATH_REJECTED')
    return target


def read_notes(bundle, runs_root=None, jobs_root=None):
    runs_root = Path(runs_root) if runs_root is not None else APP / 'runs'
    jobs_root = Path(jobs_root) if jobs_root is not None else data_root() / 'jobs'
    version = bundle['version']; job_id = bundle['job_id']
    result = {'contract': CONTRACT, 'version': version, 'job_id': job_id,
              'notes': [], 'binding_issues': [], 'independent_review': 'NOT_REVIEWED',
              'scope': 'limited supervisor post-seal model reading'}
    seen = set()
    for index_path in sorted(runs_root.glob('*/postseal-reader-index.json')):
        try:
            index_data = bounded_bytes(index_path, 1_048_576)
            index = json.loads(index_data)
            publication = bounded_json(index_path.with_name('postseal-reader-index-seal.json'), 1_048_576)
            if not isinstance(publication, dict) or publication.get('status') != 'PUBLISHED_POSTSEAL_BINDINGS' or publication.get('index_sha256') != hashlib.sha256(index_data).hexdigest():
                raise ValueError('NOTE_INDEX_PUBLICATION_BINDING_MISMATCH')
            if not isinstance(index, dict) or index.get('contract') != CONTRACT or not isinstance(index.get('rows'), list):
                raise ValueError('NOTE_INDEX_CONTRACT_INVALID')
        except (OSError, ValueError, TypeError) as exc:
            result['binding_issues'].append({'run': index_path.parent.name, 'error': str(exc)})
            continue
        for row in index['rows']:
            if not isinstance(row, dict) or row.get('version') != version:
                continue
            try:
                run = index_path.parent
                note = within(run, row['note'])
                note_data = bounded_bytes(note, 262_144)
                receipt_path = within(run, row['source_review_receipt'])
                receipt_data = bounded_bytes(receipt_path, 1_048_576); receipt = json.loads(receipt_data)
                job = (jobs_root / job_id).resolve()
                if not job.is_relative_to(jobs_root.resolve()):
                    raise ValueError('NOTE_JOB_PATH_REJECTED')
                seal_data = bounded_bytes(job / 'sealed.json', 1_048_576); seal = json.loads(seal_data)
                if not isinstance(receipt, dict) or not isinstance(seal, dict):
                    raise ValueError('NOTE_RECEIPT_OR_JOB_SEAL_INVALID')
                checks = [
                    row['job_id'] == job_id,
                    row['source_sha256'] == bundle['source_sha256'],
                    row['candidate_content_sha256'] == digest(bundle['candidate']),
                    row['source_review_receipt_sha256'] == hashlib.sha256(receipt_data).hexdigest(),
                    row['note_sha256'] == hashlib.sha256(note_data).hexdigest(),
                    row['sealed_sha256'] == hashlib.sha256(seal_data).hexdigest(),
                    row['candidate_file_sha256'] == file_hash(job / 'current.json'),
                    receipt.get('job_id') == job_id,
                    receipt.get('source_sha256') == row['source_sha256'],
                    receipt.get('sealed_sha256') == row['sealed_sha256'],
                    receipt.get('candidate_sha256') == row['candidate_file_sha256'] == seal.get('candidate_sha256'),
                    receipt.get('note_sha256') == row['note_sha256'],
                    Path(receipt.get('note', '')).resolve() == note,
                    receipt.get('status') == 'COARSE_SOURCE_REVIEW_RECORDED',
                    receipt.get('independent_review') == 'NOT_REVIEWED',
                    receipt.get('chemical_intervention') is False,
                    isinstance(row.get('notice'), str) and 0 < len(row['notice']) <= 4000,
                ]
                if not all(checks):
                    raise ValueError('POSTSEAL_NOTE_VERSION_BINDING_MISMATCH')
                manual_text = None
                if row.get('manual_review_receipt'):
                    manual_path = within(run, row['manual_review_receipt'])
                    manual_data = bounded_bytes(manual_path, 1_048_576); manual = json.loads(manual_data)
                    manual_note = within(run, row['manual_note'])
                    manual_note_data = bounded_bytes(manual_note, 262_144)
                    if not isinstance(manual, dict):
                        raise ValueError('MANUAL_NOTE_RECEIPT_INVALID')
                    manual_checks = [
                        row['manual_review_receipt_sha256'] == hashlib.sha256(manual_data).hexdigest(),
                        row['manual_note_sha256'] == hashlib.sha256(manual_note_data).hexdigest() == manual.get('note_sha256'),
                        manual.get('job_id') == job_id,
                        manual.get('source_sha256') == row['source_sha256'],
                        manual.get('sealed_sha256') == row['sealed_sha256'],
                        manual.get('candidate_sha256') == row['candidate_file_sha256'],
                        Path(manual.get('note', '')).resolve() == manual_note,
                        manual.get('status') == 'COARSE_MANUAL_REVIEW_RECORDED',
                        manual.get('independent_review') == 'NOT_REVIEWED',
                        manual.get('chemical_intervention') is False,
                        isinstance(manual.get('at'), str) and isinstance(receipt.get('at'), str)
                        and manual['at'] >= receipt['at'],
                    ]
                    if not all(manual_checks):
                        raise ValueError('POSTSEAL_MANUAL_NOTE_VERSION_BINDING_MISMATCH')
                    manual_text = manual_note_data.decode('utf-8')
                key = row['source_review_receipt_sha256']
                if key not in seen:
                    result['notes'].append({'notice': row['notice'], 'text': note_data.decode('utf-8'),
                                            'manual_text': manual_text,
                                            'note_sha256': row['note_sha256'], 'independent_review': 'NOT_REVIEWED',
                                            'scope': result['scope']})
                    seen.add(key)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                result['binding_issues'].append({'run': index_path.parent.name, 'error': str(exc)})
    return result
