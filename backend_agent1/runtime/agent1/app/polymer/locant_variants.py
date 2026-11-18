"""Bounded naming variants: colon locant groups, two dianhydride monomers, a tiny
declared table, and explicit refusals.

Scope and non-claims
--------------------
A match yields a *candidate* finite molecule with an explicit rule id, evidence
note and ``binding_status`` that is never ``REVIEWED``.  It is not a
polymerization fact, not a CRU, not a material identity and not a preferred
IUPAC name.  Names outside the covered set keep whatever diagnostics they had:

Since ADR-006 the table is **on by default**: ``Registry()`` loads it and
``Registry(declared_variants=False)`` (or ``POLYMER_PARSE_LEVERS=0``) puts the
registry back on the legacy namespace.  A passport records the namespace it was
built with, so a card parsed without the table still replays.

- a name of a covered family that carries extra substituents (for example
  ``6,6'-bis(4-tertbutylphenyl)biphenyl-3,3',4,4'-tetracarboxylic anhydride``)
  is **refused**, never guessed, because the locant-free spelling does not pin
  the substitution pattern;
- polymer-class trade names (``ethersulfone``/``PES``, ``etheretherketone``/
  ``PEEK``, ``1,4-polyisoprene``, ``hydrogenated polybutadiene``) are refused with
  a reason instead of being mapped onto a monomer;
- ambiguous trade names (``caprolactone diol``, ``hexamethylene adipamide``) stay
  refusals as well.

Evidence for the two structures lives in the task run directory
(``derive_bpda.py``: in-ring distances {2,3} = meta+para = 3,4; ``derive_pmda.py``:
free benzene positions para = 1,2,4,5).  Refusal and coverage counts are measured,
not asserted.
"""
from __future__ import annotations
import hashlib
import re
from pathlib import Path

from .chemistry import canonicalize

VERSION = 'declared-naming-variant/0.1'
FAMILY_RULE_ID = 'TETRACARBOXYLIC-DIANHYDRIDE-FAMILY/0.1'
TRADE_RULE_ID = 'DECLARED-TRADE-NAME-TABLE/0.1'

# ``3,3':4,4'`` separates locant *groups*; it looks exactly like a ring-position
# colon such as the one in ``1,4:3,6-dianhydro``.  The two cannot be told apart
# by pattern alone, so normalisation is *bounded by the tables*: a name is only
# rewritten when the rewritten form is a declared entry (or a declared refusal).
# Everything else keeps its original spelling.
COLON_LOCANT = re.compile(r"(\d'?):(?=\d)")
SUBSTITUTED_FAMILY = re.compile(r'biphenyl.*tetracarboxylic (?:di)?anhydride$')


def normalize_locant_groups(name):
    """Declared spelling of *name*, else *name* unchanged.

    ``biphenyl-3,3':4,4'-...`` -> ``biphenyl-3,3',4,4'-...`` because (and only
    because) the second spelling is declared below.  ``1,4:3,6-dianhydro-...``
    is not declared, so it is returned untouched instead of being rewritten into
    a name nobody declared.
    """
    if not isinstance(name, str):
        return name
    rewritten = COLON_LOCANT.sub(r'\1,', name)
    return rewritten if (rewritten in DECLARED_VARIANTS or rewritten in REFUSALS) else name


# Verified structures.  Each entry: smiles, formula, derivation note.
BIPHENYL_DIANHYDRIDE = {
    'smiles': 'O=C1OC(=O)c2cc(-c3ccc4c(c3)C(=O)OC4=O)ccc21', 'formula': 'C16H6O6',
    'derivation': 'biphenyl with one anhydride closed across the meta+para carboxyl pair (3,4) on each ring'}
BENZENE_DIANHYDRIDE = {
    'smiles': 'O=C1OC(=O)c2c1cc1c(c2)C(=O)OC1=O', 'formula': 'C10H2O6',
    'derivation': 'benzene with anhydrides across 1,2 and 4,5; the free positions are para to each other'}

# alias (already normalized) -> declaration
DECLARED_VARIANTS = {
    "biphenyl-3,3',4,4'-tetracarboxylic dianhydride": {
        'structure': BIPHENYL_DIANHYDRIDE, 'rule_id': FAMILY_RULE_ID,
        'closure_basis': 'name says dianhydride explicitly',
        'evidence': 'catalogue leaf, 59 records'},
    "biphenyl-3,3',4,4'-tetracarboxylic anhydride": {
        'structure': BIPHENYL_DIANHYDRIDE, 'rule_id': FAMILY_RULE_ID,
        'closure_basis': 'CATALOGUE_USAGE_AS_DIANHYDRIDE',
        'evidence': 'poly[(4,4\'-oxydianiline)-alt-(...)] appears as P130079 with "dianhydride" and as '
                    'P372223 with "anhydride": same repeat unit, two spellings'},
    "benzene-1,2,4,5-tetracarboxylic dianhydride": {
        'structure': BENZENE_DIANHYDRIDE, 'rule_id': FAMILY_RULE_ID,
        'closure_basis': 'name says dianhydride explicitly',
        'evidence': 'catalogue leaf, colon spelling normalised'},
    "benzene-1,2,4,5-tetracarboxylic acid 1,2,4,5-dianhydride": {
        'structure': BENZENE_DIANHYDRIDE, 'rule_id': FAMILY_RULE_ID,
        'closure_basis': 'name says dianhydride explicitly',
        'evidence': 'acid-plus-dianhydride spelling of the same monomer'},
    'tetramethylene glycol': {
        'structure': {'smiles': 'OCCCCO', 'formula': 'C4H10O2',
                      'derivation': 'butane-1,4-diol, the only tetramethylene glycol'},
        'rule_id': TRADE_RULE_ID, 'closure_basis': 'trivial name with a single finite structure',
        'evidence': 'declared finite-molecule trade name; not a polymer-class name'},
    'isophoronediamine': {
        'structure': {'smiles': 'CC1(C)CC(N)CC(C)(CN)C1', 'formula': 'C10H22N2',
                      'derivation': '5-amino-1,3,3-trimethylcyclohexanemethylamine'},
        'rule_id': TRADE_RULE_ID, 'closure_basis': 'trivial name with a single finite structure',
        'evidence': 'declared finite-molecule trade name; not a polymer-class name'},
    'terephthalohydrazide': {
        'structure': {'smiles': 'NNC(=O)c1ccc(C(=O)NN)cc1', 'formula': 'C8H10N4O2',
                      'derivation': 'benzene-1,4-dicarbohydrazide'},
        'rule_id': TRADE_RULE_ID, 'closure_basis': 'trivial name with a single finite structure',
        'evidence': 'declared finite-molecule trade name; not a polymer-class name'},
}

# Refusals: the name is recognised as *not* a bounded source molecule, and says so.
REFUSALS = {
    'biphenyltetracarboxylic dianhydride':
        'LOCANTS_REQUIRED_BEFORE_A_STRUCTURE_CAN_BE_STATED',
    'benzophenone tetracarboxylic dianhydride':
        'LOCANTS_REQUIRED_BEFORE_A_STRUCTURE_CAN_BE_STATED',
    "3,3',4,4'-benzophenone tetracarboxylic dianhydride":
        'SUBSTITUTED_FAMILY_MEMBER_NOT_IN_THE_BOUNDED_SET',
    'ethersulfone': 'POLYMER_CLASS_TRADE_NAME_REQUIRES_POLYMER_LEVEL_DECLARATION',
    'ethersulfone(PES)': 'POLYMER_CLASS_TRADE_NAME_REQUIRES_POLYMER_LEVEL_DECLARATION',
    'etheretherketone': 'POLYMER_CLASS_TRADE_NAME_REQUIRES_POLYMER_LEVEL_DECLARATION',
    '1,4-polyisoprene': 'POLYMER_CLASS_TRADE_NAME_REQUIRES_POLYMER_LEVEL_DECLARATION',
    'hydrogenated polybutadiene': 'POLYMER_CLASS_TRADE_NAME_REQUIRES_POLYMER_LEVEL_DECLARATION',
    'caprolactone diol': 'AMBIGUOUS_TRADE_NAME_NO_SINGLE_FINITE_STRUCTURE',
    'hexamethylene adipamide': 'REPEAT_UNIT_NAME_NOT_A_FINITE_SOURCE_MOLECULE',
    'diethoxyphosphazene': 'AMBIGUOUS_TRADE_NAME_NO_SINGLE_FINITE_STRUCTURE',
}


def variant_refusal(name):
    """Reason this name is recognised but deliberately not resolved, else None."""
    if not isinstance(name, str):
        return None
    normalized = normalize_locant_groups(name.strip())
    if normalized in DECLARED_VARIANTS:
        return None
    if normalized in REFUSALS:
        return REFUSALS[normalized]
    if SUBSTITUTED_FAMILY.search(normalized):
        # Same parent as a covered entry but with an unpinned substitution
        # pattern: guessing the positions would be a fabrication.
        return 'SUBSTITUTED_FAMILY_MEMBER_NOT_IN_THE_BOUNDED_SET'
    return None


def resolve_locant_variant(name):
    """Resolver-shaped candidate for a declared variant, else ``None``.

    Exact match on the normalized alias only: no fuzzy matching, no locant
    arithmetic, no guessing of an unpinned substitution pattern.
    """
    if not isinstance(name, str) or not name.strip():
        return None
    normalized = normalize_locant_groups(name.strip())
    declaration = DECLARED_VARIANTS.get(normalized)
    if not declaration:
        return None
    graph = canonicalize(declaration['structure']['smiles'])
    if graph.get('status') != 'PARSED':
        return None
    colon_variant = normalized != name.strip()
    return {
        **graph,
        'name': name,
        'reference_label': normalized,
        'binding_status': 'RULE_DERIVED_CANDIDATE',
        'rule_id': declaration['rule_id'],
        'source': {'type': 'declared_naming_variant', 'version': VERSION,
                   'structure_formula': declaration['structure']['formula'],
                   'closure_basis': declaration['closure_basis'],
                   'evidence': declaration['evidence']},
        'locant_groups_normalized': colon_variant,
        'review_status': 'DRAFT',
        'material_identity_issued': False,
        'polymerization_fact_established': False,
        'preferred_iupac_name': None,
    }


def coverage():
    """Read-only description of what this module claims to cover."""
    return {'version': VERSION, 'declared_variants': sorted(DECLARED_VARIANTS),
            'refusal_reasons': REFUSALS,
            'rule_ids': sorted({d['rule_id'] for d in DECLARED_VARIANTS.values()}),
            'material_identity_issued': False, 'preferred_iupac_name': None}


class DeclaredVariantTable:
    """Opt-in wrapper around the declarations above.

    The declaration *is* this module, so the table pins the digest of its own
    source file: a registry snapshot can then be replayed against the exact
    declarations that produced it.  Nothing here writes registry state, and a
    match is still only a ``RULE_DERIVED_CANDIDATE``.
    """

    def __init__(self):
        self.path = Path(__file__)
        self.source_sha256 = hashlib.sha256(self.path.read_bytes()).hexdigest()

    def lookup(self, alias):
        """Resolver-shaped candidate for *alias*, or ``None``."""
        return resolve_locant_variant(alias)

    def refusal(self, alias):
        """Reason a recognised name is refused, or ``None``."""
        return variant_refusal(alias)

    def summary(self):
        return {'table_version': VERSION, 'path': str(self.path),
                'source_sha256': self.source_sha256,
                'declared_variants': len(DECLARED_VARIANTS),
                'declared_refusals': len(REFUSALS),
                'rule_ids': sorted({d['rule_id'] for d in DECLARED_VARIANTS.values()}),
                'binding_status': 'RULE_DERIVED_CANDIDATE', 'review_status': 'DRAFT',
                'material_identity_issued': False, 'preferred_iupac_name': None}
