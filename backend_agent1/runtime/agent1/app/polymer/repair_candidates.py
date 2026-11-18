"""Validated spelling-repair candidates kept outside identity and registry state.

Repairs are proposals only.  The original text remains the lookup key and no
alias is inserted into the registry.  A candidate is returned only when the
bounded local grammar resolves the proposed spelling to a finite graph.

Two paths exist and they must not be confused:

- :func:`propose_source_repairs` is the original advisory path driven by
  ``queue_rules.name_diagnostic``.  Its behaviour is frozen: it proposes, it
  never resolves, and the registry only attaches its output to a diagnostic.
- :class:`DeclaredRepairTable` is a table of declared typo rules
  (``data/repair_declarations.json``, built by
  ``tools/build_repair_declarations.py`` with measured evidence).  Since
  ADR-006 the shipped default registry loads it; it is switched off with
  ``Registry(declared_repairs=False)`` or ``POLYMER_PARSE_LEVERS=0``.  The
  repaired text
  is looked up in the *bounded local grammar*; a repaired alias then resolves
  with ``binding_status='SPELLING_REPAIR_CANDIDATE'``, the raw text is kept as
  the reference label, and no identity, CRU or preferred name is issued.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

from .chemistry import canonicalize
from .queue_rules import name_diagnostic, resolve_source

VERSION = 'declared-spelling-repair/0.1'
REPAIR_CANDIDATE_STATUS = 'SPELLING_REPAIR_CANDIDATE'


def propose_source_repairs(raw: str) -> list[dict]:
    """Return locally validated, candidate-only repairs for *raw*.

    This deliberately does not apply aliases or infer polymer architecture.
    Invalid or unresolved proposals remain diagnostic text only.
    """
    diagnostic = name_diagnostic(raw)
    if not diagnostic:
        return []
    candidates = []
    for proposal in diagnostic.get("repair_proposals", []):
        proposed = proposal.get("proposed_text")
        if not isinstance(proposed, str) or proposed == raw:
            continue
        resolved = resolve_source(proposed)
        if not resolved:
            continue
        smiles, rule_id = resolved
        graph = canonicalize(smiles)
        if graph.get("status") != "PARSED":
            continue
        candidates.append({
            "original_text": raw,
            "proposed_text": proposed,
            "change": proposal.get("change"),
            "rule_id": rule_id,
            "candidate_graph": graph,
            "candidate_only": True,
            "applied": False,
            "review_status": "DRAFT",
            "source": {"type": "bounded_spelling_repair", "version": "0.1"},
            "raw_preserved": True,
            "material_identity_issued": False,
            "preferred_iupac_name": None,
        })
    return candidates


class DeclaredRepairError(ValueError):
    """Raised when a declared repair table cannot be trusted as bounded evidence."""


class DeclaredRepairTable:
    """Declared typo rules, applied one at a time and validated by the caller.

    The table is a *declaration*, not a guess: each rule names the exact wrong
    substring it fixes and carries the measured evidence recorded when the file
    was built.  Application is intentionally limited to one rule per raw name
    (no rule chaining), so the repaired text of an alias is always explainable
    by a single declared change.
    """

    def __init__(self, source):
        if isinstance(source, (list, tuple)):
            payload, origin = {'version': VERSION, 'rules': [dict(r) for r in source]}, 'in-memory'
        elif isinstance(source, dict):
            payload, origin = dict(source), 'in-memory'
        else:
            self.path = Path(source)
            if not self.path.is_file():
                raise DeclaredRepairError('DECLARATION_FILE_MISSING:' + str(self.path))
            payload = json.loads(self.path.read_text(encoding='utf-8'))
            origin = str(self.path)
        if not isinstance(payload, dict):
            raise DeclaredRepairError('DECLARATION_NOT_AN_OBJECT:' + origin)
        self.path = Path(origin)
        self.payload_version = payload.get('version') or VERSION
        self.source_sha256 = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
        self.rules = []
        for entry in payload.get('rules') or []:
            if not isinstance(entry, dict):
                raise DeclaredRepairError('RULE_NOT_AN_OBJECT')
            find, replace, rule_id = entry.get('find'), entry.get('replace'), entry.get('rule_id')
            if not isinstance(find, str) or not find or not isinstance(replace, str) or not rule_id:
                raise DeclaredRepairError('RULE_REQUIRES_FIND_REPLACE_AND_ID')
            if find == replace:
                raise DeclaredRepairError('RULE_WOULD_NOT_CHANGE_ANYTHING:' + str(rule_id))
            self.rules.append({'rule_id': rule_id, 'find': find, 'replace': replace,
                               'rationale': entry.get('rationale'),
                               'evidence': entry.get('evidence')})
        if not self.rules:
            raise DeclaredRepairError('DECLARATION_HAS_NO_RULES:' + origin)

    @classmethod
    def from_rules(cls, rules, version=VERSION):
        """Build an in-memory table from rule dicts (tests, dry runs)."""
        return cls({'version': version, 'rules': [dict(r) for r in rules]})

    def proposals(self, raw):
        """Single-rule repairs for *raw*, in declared order, without duplicates."""
        if not isinstance(raw, str) or not raw:
            return []
        seen, out = set(), []
        for rule in self.rules:
            if rule['find'] not in raw:
                continue
            proposed = raw.replace(rule['find'], rule['replace'])
            if proposed == raw or proposed in seen:
                continue
            seen.add(proposed)
            out.append({'rule_id': rule['rule_id'], 'proposed_text': proposed,
                        'change': rule['find'] + ' -> ' + rule['replace']})
        return out

    def summary(self):
        return {'table_version': self.payload_version, 'declaration_version': VERSION,
                'path': str(self.path), 'source_sha256': self.source_sha256,
                'rule_count': len(self.rules),
                'rule_ids': [r['rule_id'] for r in self.rules],
                'binding_status': REPAIR_CANDIDATE_STATUS, 'review_status': 'DRAFT',
                'material_identity_issued': False, 'preferred_iupac_name': None}
