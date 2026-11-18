"""Disposable reader projections; sealed bundles are never written or migrated."""
from .storage import atomic, data_root, digest, read

CONTRACT = 'identity-reader-projection/4.0'


def cache_path(job_id):
    return data_root() / 'cache' / 'reader-projections-v4' / (job_id + '.json')


def load(job_id, control, stamp_for_version):
    try:
        value = read(cache_path(job_id), {})
        body = value.get('body', {})
        if (value.get('sha256') != digest(body) or body.get('contract') != CONTRACT or
                body.get('control') != list(map(lambda x:list(x) if x else None, control))):
            return None
        row = body['row']; version = row['version']
        if not isinstance(version,str) or len(version)!=64 or any(c not in '0123456789abcdef' for c in version):
            return None
        stamp = stamp_for_version(version)
        if not stamp or list(stamp) != body['bundle_stamp'] or row['job_id'] != job_id:
            return None
        return row, stamp, body['entries']
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save(job_id, control, stamp, row, entries):
    body = {'contract':CONTRACT, 'control':control, 'bundle_stamp':stamp, 'row':row, 'entries':entries}
    try:
        atomic(cache_path(job_id), {'body':body, 'sha256':digest(body)})
    except OSError:
        pass  # Cache availability never decides whether a sealed result is valid.
