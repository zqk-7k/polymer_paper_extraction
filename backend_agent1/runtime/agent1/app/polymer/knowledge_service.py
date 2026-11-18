"""Read-only, versioned knowledge used by browsing and per-run resolution.

No chemical graph is inferred from a catalog ID or formula. Source datasets
remain untouched; missing datasets are not reported as empty databases.
"""
from __future__ import annotations
from collections import Counter
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
import re
import threading
from .common import ROOT

DEFAULT_SOURCES = {
    'catalog': 'data/catalog_rows.jsonl',
    'components': 'runs/COMPONENT-LIBRARY-CONSOLIDATED-20260914T171500Z/consolidated_components.jsonl',
}

class KnowledgeService:
    def __init__(self, root=None):
        self.root = Path(root or ROOT).resolve()
        self.lock = threading.RLock()
        self.cache = {}
        path = self.root / 'config/knowledge_sources.json'
        self.config = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {'sources': DEFAULT_SOURCES}
        self._config_digest = sha256(path.read_bytes()).hexdigest() if path.is_file() else None

    @staticmethod
    def alias_key(value):
        return re.sub(r'\s+', ' ', str(value).strip())

    def refresh(self):
        path = self.root / 'config/knowledge_sources.json'
        if not path.is_file():
            return
        data = path.read_bytes(); digest = sha256(data).hexdigest()
        with self.lock:
            if digest != self._config_digest:
                config = json.loads(data)
                if not isinstance(config.get('sources'), dict):
                    raise ValueError('KNOWLEDGE_CONFIG_INVALID')
                self.config, self._config_digest = config, digest
                self.cache.clear()

    def snapshot(self, kind):
        self.refresh()
        if kind not in ('catalog', 'components'):
            raise ValueError('UNKNOWN_KNOWLEDGE_KIND')
        relative = self.config.get('sources', {}).get(kind)
        if not relative:
            raise ValueError('KNOWLEDGE_SOURCE_NOT_CONFIGURED')
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError('KNOWLEDGE_PATH_OUTSIDE_PROJECT')
        with self.lock:
            if not path.is_file():
                return {'available': False, 'reason_code': 'KNOWLEDGE_SOURCE_MISSING', 'rows': [], 'version': None}
            stat = path.stat()
            signature = (str(path), stat.st_mtime_ns, stat.st_size)
            old = self.cache.get(kind)
            if old and old['signature'] == signature:
                expected = self.config.get('sha256', {}).get(kind)
                if expected and expected != old['version']:
                    raise ValueError('KNOWLEDGE_SOURCE_HASH_MISMATCH')
                return old
            data = path.read_bytes()
            rows = [json.loads(line) for line in data.decode('utf-8-sig').splitlines() if line.strip()]
            if not all(isinstance(row, dict) for row in rows):
                raise ValueError('KNOWLEDGE_RECORD_NOT_OBJECT')
            digest = sha256(data).hexdigest()
            expected = self.config.get('sha256', {}).get(kind)
            if expected and expected != digest:
                raise ValueError('KNOWLEDGE_SOURCE_HASH_MISMATCH')
            result = {'available': True, 'signature': signature, 'rows': rows, 'version': digest, 'source': relative}
            self.cache[kind] = result
            return result

    def summary(self):
        out = {}
        for kind in ('catalog', 'components'):
            snap = self.snapshot(kind)
            rows = snap['rows']
            field = 'polymer_type' if kind == 'catalog' else 'role'
            out[kind] = {'available': snap['available'], 'total': len(rows), 'data_version': snap['version'],
                         'reason_code': snap.get('reason_code'), 'by_type': dict(Counter(r.get(field, 'unknown') for r in rows))}
            if kind == 'components':
                out[kind]['without_labels'] = sum(not r.get('labels') for r in rows)
                from .knowledge_quality import summarize_quality
                with self.lock:
                    if 'quality' not in snap:
                        snap['quality'] = summarize_quality(rows)
                out[kind]['quality'] = snap['quality']
        return {'status': 'PARSED' if all(x['available'] for x in out.values()) else 'PARTIAL',
                'datasets': out, 'read_only': True, 'independent_review': 'PENDING'}

    def search(self, kind, query='', role=None, declared_type=None, offset=0, limit=20):
        snap = self.snapshot(kind)
        if not snap['available']:
            return {'status': 'NEEDS_DETAILS', 'reason_code': snap['reason_code'], 'records': [], 'total': None}
        offset, limit = max(0, int(offset)), max(1, min(100, int(limit)))
        q = str(query or '').strip().casefold()
        # Index the exact previous lexical representation once per snapshot.
        # A new data/config version owns fresh indexes; no derived disk writes.
        with self.lock:
            if q and 'search_text' not in snap:
                snap['search_text'] = [json.dumps(r, ensure_ascii=False).casefold() for r in snap['rows']]
        rows = [row for i, row in enumerate(snap['rows'])
                if (not role or kind != 'components' or row.get('role') == role)
                and (not declared_type or kind != 'catalog' or row.get('polymer_type') == declared_type)
                and (not q or q in snap['search_text'][i])]
        return {'status': 'PARSED', 'kind': kind, 'total': len(rows), 'offset': offset, 'shown': len(rows[offset:offset+limit]),
                'records': deepcopy(rows[offset:offset+limit]), 'data_version': snap['version'], 'read_only': True,
                'result_scope': 'original_catalog_records' if kind == 'catalog' else 'typed_research_components'}

    def record(self, kind, record_id):
        snap = self.snapshot(kind)
        field = 'polymer_id' if kind == 'catalog' else 'component_key'
        if not snap['available']:
            return {'status': 'NEEDS_DETAILS', 'reason_code': snap['reason_code']}
        with self.lock:
            if 'records_by_id' not in snap:
                index = {}
                for record in snap['rows']:
                    key = record.get(field)
                    if isinstance(key, str):
                        index.setdefault(key, record)
                snap['records_by_id'] = index
        row = snap['records_by_id'].get(record_id) if isinstance(record_id, str) else None
        if row is None:
            return {'status': 'NEEDS_DETAILS', 'reason_code': 'KNOWLEDGE_RECORD_NOT_FOUND'}
        result = {'status': 'PARSED', 'kind': kind, 'record': deepcopy(row), 'data_version': snap['version'], 'read_only': True}
        if kind == 'components':
            from .knowledge_quality import classify_structure
            result['structure_quality'] = classify_structure(row)
        return result

    def candidate_index(self):
        """Pin one snapshot. Alias collisions stay separate candidates."""
        snap = self.snapshot('components')
        index = {}
        for row in snap['rows']:
            if row.get('active') is False or any(str(row.get(k, '')).upper() in ('REVOKED', 'WITHDRAWN')
                                               for k in ('review_status', 'status', 'promotion')):
                continue
            for alias in row.get('labels') or []:
                if isinstance(alias, str) and alias.strip():
                    key = (row.get('role'), self.alias_key(alias))
                    index.setdefault(key, []).append(row)
        return snap['version'], index
