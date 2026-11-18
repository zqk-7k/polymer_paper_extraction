"""Bulk, read-only bindings produced by the pinned local OPSIN parser.

This is the offline counterpart of the per-run candidate path in
``knowledge_runtime.KnowledgeRegistry``: the same ``EXTERNAL_PARSER_CANDIDATE``
status and the same SUCCESS / stereo gates, but precomputed for a whole
catalogue so a run does not have to spend live parser calls.  Policy, scope and
red lines: ``docs/ADR-003-external-parser-candidate-bindings.md``.

Nothing in this module is a polymerization fact, a reviewed binding, a material
identity or a preferred IUPAC name, and nothing here is written into the shared
registry.  Since ADR-006 the shipped default ``Registry`` consults this table;
``Registry(external_candidates=False)`` or ``POLYMER_EXTERNAL_CANDIDATES=0``
puts it back on the legacy namespace, and ``external_candidates=<path>`` selects
a different table.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

from rdkit import Chem

from .chemistry import canonicalize

VERSION = 'external-candidate-table/0.1'
CANDIDATE_STATUS = 'EXTERNAL_PARSER_CANDIDATE'
ACCEPTED_PARSER_STATUS = ('SUCCESS',)
REJECTED_STEREO_STATES = ('requested_not_encoded',)
CANDIDATE_CLASS = 'FINITE_SOURCE_MOLECULE'
TABLE_FIELDS = ('alias', 'canonical_smiles', 'isomeric_smiles', 'molecule_key', 'formula',
                'parser', 'parser_status', 'stereo_state', 'candidate_class')


class CandidateTableError(ValueError):
    """Raised when a candidate table cannot be trusted as read-only evidence."""


def structure_obstructions(smiles):
    """Return the reasons a candidate structure is not a finite molecule.

    A parser SUCCESS only means "the name was understood".  Wildcards, radicals
    and unfilled valences describe fragments or open valences, so they cannot be
    used as a source molecule.
    """
    mol = Chem.MolFromSmiles(smiles) if isinstance(smiles, str) else None
    if mol is None:
        return ['UNPARSEABLE_SMILES']
    reasons = []
    if any(atom.GetAtomicNum() == 0 for atom in mol.GetAtoms()):
        reasons.append('WILDCARD_ATOMS')
    if any(atom.GetNumRadicalElectrons() > 0 for atom in mol.GetAtoms()):
        reasons.append('RADICAL_ELECTRONS')
    try:
        Chem.SanitizeMol(Chem.Mol(mol))
    except Exception:  # noqa: BLE001 - RDKit raises several types
        reasons.append('SANITIZATION_FAILED')
    return reasons


def screen_candidate(entry):
    """Return ``(accepted_entry, rejection_reason_or_None)`` for one table row."""
    if not isinstance(entry, dict):
        return None, 'ENTRY_NOT_AN_OBJECT'
    alias = entry.get('alias')
    if not isinstance(alias, str) or not alias.strip():
        return None, 'ALIAS_REQUIRED'
    # Parser gates come first: a name the parser did not resolve cleanly is
    # rejected for that reason, never for a missing structure field.
    if entry.get('parser_status') not in ACCEPTED_PARSER_STATUS:
        return None, 'PARSER_STATUS_NOT_ACCEPTED:' + str(entry.get('parser_status'))
    if entry.get('stereo_state') in REJECTED_STEREO_STATES:
        return None, 'STEREO_REQUESTED_NOT_ENCODED'
    if entry.get('candidate_class') != CANDIDATE_CLASS:
        return None, 'CANDIDATE_CLASS_NOT_A_SOURCE_MOLECULE:' + str(entry.get('candidate_class'))
    missing = [field for field in ('canonical_smiles', 'isomeric_smiles', 'molecule_key', 'parser')
               if field not in entry]
    if missing:
        return None, 'MISSING_GRAPH_FIELDS:' + ','.join(sorted(missing))
    smiles = entry.get('canonical_smiles') or entry.get('isomeric_smiles')
    graph = canonicalize(smiles)
    if graph.get('status') != 'PARSED':
        return None, 'CANDIDATE_GRAPH_NOT_PARSED:' + str(graph.get('reason_code'))
    if entry.get('molecule_key') and entry['molecule_key'] != graph['molecule_key']:
        # Integrity, not chemistry: a rewritten row must not silently resolve.
        return None, 'MOLECULE_KEY_MISMATCH'
    reasons = structure_obstructions(graph.get('isomeric_smiles') or smiles)
    if reasons:
        return None, 'STRUCTURE_OBSTRUCTION:' + ','.join(reasons)
    return {**entry, 'graph': graph}, None


class ExternalCandidateTable:
    """Read-only alias -> candidate molecule lookup with explicit screening.

    The table is *not* a registry: entries are never active bindings, never
    REVIEWED, and never carry material identity.  ``lookup`` returns a
    resolver-shaped result so a caller can render the candidate without
    importing it as a binding.
    """

    def __init__(self, path):
        self._reset()
        self.path = Path(path)
        if not self.path.is_file():
            raise CandidateTableError('CANDIDATE_TABLE_MISSING:' + str(self.path))
        raw = self.path.read_text(encoding='utf-8')
        self.source_sha256 = hashlib.sha256(raw.encode('utf-8')).hexdigest()
        rows = []
        for line in raw.splitlines():
            if not line.strip():
                continue
            self.rows_seen += 1
            try:
                rows.append(json.loads(line))
            except ValueError:
                self._reject('', 'ROW_NOT_JSON')
        self._ingest(rows)

    @classmethod
    def from_rows(cls, rows, origin='in-memory'):
        """Build a table from already-parsed rows (tests, tooling, dry runs)."""
        self = cls.__new__(cls)
        self._reset()
        self.path = Path(origin)
        payload = ''.join(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n' for row in rows)
        self.source_sha256 = hashlib.sha256(payload.encode('utf-8')).hexdigest()
        self.rows_seen = len(rows)
        self._ingest(list(rows))
        return self

    def _reset(self):
        self.entries = {}
        self.ambiguous = {}
        self.rejections = {}
        self.accepted_rows = 0
        self.rows_seen = 0

    def _ingest(self, rows):
        grouped = {}
        for entry in rows:
            screened, reason = screen_candidate(entry)
            if screened is None:
                self._reject((entry or {}).get('alias', '') if isinstance(entry, dict) else '', reason)
                continue
            self.accepted_rows += 1
            grouped.setdefault(screened['alias'], {}).setdefault(screened['molecule_key'], screened)
        for alias, by_key in grouped.items():
            if len(by_key) > 1:
                # Two parser answers for one name are a conflict, never a pick.
                self.ambiguous[alias] = sorted(by_key)
            else:
                self.entries[alias] = next(iter(by_key.values()))

    def _reject(self, alias, reason):
        bucket = self.rejections.setdefault(reason.split(':')[0], [])
        if len(bucket) < 20:
            bucket.append({'alias': alias, 'reason': reason})

    def lookup(self, alias):
        """Return the screened candidate for an exact alias, else ``None``."""
        return self.entries.get(alias)

    def resolve(self, alias, name=None):
        """Resolver-shaped candidate result for *alias*.

        ``None`` means "this table has nothing to say"; the caller keeps its own
        fallback.  An ambiguous alias returns AMBIGUOUS instead of one answer.
        """
        if alias in self.ambiguous:
            return {'status': 'AMBIGUOUS', 'reason_code': 'EXTERNAL_CANDIDATE_ALIAS_AMBIGUOUS',
                    'name': name if name is not None else alias,
                    'candidate_molecule_keys': self.ambiguous[alias],
                    'binding_status': CANDIDATE_STATUS, 'candidate_only': True}
        entry = self.entries.get(alias)
        if entry is None:
            return None
        graph = entry['graph']
        return {**graph, 'name': name if name is not None else alias,
                'reference_label': alias,
                'binding_status': CANDIDATE_STATUS,
                'candidate_only': True,
                'review_status': 'DRAFT',
                'source': entry.get('parser') or {},
                'parser_status': entry.get('parser_status'),
                'stereo_state': entry.get('stereo_state'),
                'candidate_class': entry.get('candidate_class'),
                'material_identity_issued': False,
                'polymerization_fact_established': False,
                'preferred_iupac_name': None}

    def summary(self):
        return {'table_version': VERSION, 'path': str(self.path),
                'source_sha256': self.source_sha256,
                'rows_seen': self.rows_seen, 'rows_accepted': self.accepted_rows,
                'aliases': len(self.entries), 'ambiguous_aliases': len(self.ambiguous),
                'rejected_by_reason': {k: len(v) for k, v in sorted(self.rejections.items())},
                'binding_status': CANDIDATE_STATUS,
                'review_status': 'DRAFT',
                'material_identity_issued': False,
                'preferred_iupac_name': None}
