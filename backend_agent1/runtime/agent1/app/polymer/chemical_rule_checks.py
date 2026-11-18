"""Executable identity/naming prerequisites; not full IUPAC certification."""
import re
from rdkit import Chem

VERSION = 'chemical-rule-checks/1.0'
HETERO_ORDER = [8, 16, 34, 52, 7, 15, 33, 51, 83, 14, 32, 50, 82, 5, 80]

def seniority_class(smiles):
    """RSSOP Rule 1 class along a two-port backbone, not all tie-breaks."""
    mol = Chem.MolFromSmiles(smiles) if smiles else None
    if mol is None:
        return {'status': 'NOT_RUN'}
    ports = [a.GetIdx() for a in mol.GetAtoms() if a.GetAtomicNum() == 0]
    if len(ports) != 2 or len(Chem.GetMolFrags(mol)) != 1:
        return {'status': 'OUTSIDE_SCOPE'}
    path = set(Chem.GetShortestPath(mol, ports[0], ports[1])) - set(ports)
    rings = [set(r) for r in mol.GetRingInfo().AtomRings() if set(r) & path]
    heteroring = any(any(mol.GetAtomWithIdx(i).GetAtomicNum() not in (0, 6) for i in ring) for ring in rings)
    ring_atoms = set().union(*rings) if rings else set()
    heterochain = [mol.GetAtomWithIdx(i).GetAtomicNum() for i in path - ring_atoms if mol.GetAtomWithIdx(i).GetAtomicNum() not in (0, 6)]
    rank = 0 if heteroring else 1 if heterochain else 2 if rings else 3
    labels = ['heterocyclic_ring', 'heteroatom_chain', 'carbocyclic_ring', 'acyclic_carbon_chain']
    priority = min((HETERO_ORDER.index(z) for z in heterochain if z in HETERO_ORDER), default=None)
    return {'status': 'CLASSIFIED', 'category': labels[rank], 'category_rank': rank,
            'heteroatom_priority': priority, 'rule_id': 'PI-SENIORITY-001',
            'scope': 'backbone_class_only_not_full_subdivision_or_preferred_CRU',
            'full_tie_breaks_checked': False}

def enrich_support(support):
    """Add executed graph/role checks to a new support view, not the passport."""
    from .units import resolve_unit
    checks = []
    def check(rule, scope, status, detail):
        checks.append({'rule_id': rule, 'scope': scope, 'status': status, 'detail': detail,
                       'evidence_ref': support.get('passport_ref'), 'method_version': VERSION})
    for component in support.get('components', []):
        graph = component['graph']; smiles = graph.get('smiles'); oid = component['occurrence_id']
        mol = Chem.MolFromSmiles(smiles) if smiles else None
        component['lexical_locants'] = re.findall(r"(?<![A-Za-z0-9])(\d+['′]*(?:,\d+['′]*)+)(?=-|\))", component.get('label') or '')
        component['locants_to_atom_mapping'] = 'NOT_ESTABLISHED_BY_LEXICAL_EXTRACTION'
        if mol is None:
            check('PI-IDENTITY-001', oid, 'NOT_RUN', 'No usable component graph; preserve unresolved name.')
            continue
        graph['atoms'] = [{'index': a.GetIdx(), 'element': a.GetSymbol(), 'isotope': a.GetIsotope(),
                           'charge': a.GetFormalCharge(), 'aromatic': a.GetIsAromatic(),
                           'stereo_tag': str(a.GetChiralTag())} for a in mol.GetAtoms()]
        graph['bonds'] = [{'atoms': [b.GetBeginAtomIdx(), b.GetEndAtomIdx()], 'order': b.GetBondTypeAsDouble(),
                           'stereo': str(b.GetStereo())} for b in mol.GetBonds()]
        source = component['kind'] == 'source'
        role_ok = graph['port_count'] == 0 if source else graph['port_count'] == 2 and graph['port_check'] == 'PASS'
        check('PI-IDENTITY-001', oid, 'PASS' if role_ok else 'FAIL', 'Finite source and port-bearing unit are distinct roles.')
        if not source:
            check('PI-PORTS-001', oid, graph['port_check'], 'Terminal port degree, supported bond order and connected graph.')
            periodic = graph.get('periodic') or {}
            check('PI-CRU-001', oid, 'PASS' if periodic.get('status') == 'PARSED' else 'NOT_RUN',
                  'Existing periodic representation checked; preferred/minimal CRU selection is NOT certified.')
            component['subunit_classification'] = []
            for label in component.get('subunit_names', []):
                unit = resolve_unit(label)
                classification = seniority_class(unit.get('unit_smiles'))
                component['subunit_classification'].append({'label': label, **classification})
            if component['subunit_classification']:
                check('PI-SENIORITY-001', oid, 'PASS' if all(c['status'] == 'CLASSIFIED' for c in component['subunit_classification']) else 'NOT_RUN',
                      'Only Rule 1 backbone category classified; not a complete preferred-CRU ordering proof.')
    for relation in support.get('connections', []):
        count = len(relation['children_order'])
        check(relation['rule_id'], relation['occurrence_id'], 'PASS' if count >= 2 else 'FAIL',
              'Ordered component occurrences retained; connective is not an atomic junction model.')
    support['rule_checks'] = checks
    support['rule_ids'] = sorted(set(support.get('rule_ids', [])) | {c['rule_id'] for c in checks})
    support['chemical_check_status'] = 'FAIL' if any(c['status'] == 'FAIL' for c in checks) else 'PARTIAL' if any(c['status'] == 'NOT_RUN' for c in checks) else 'PASS'
    support['capability_boundary'] = {'local_graphs_and_roles': True, 'connection_occurrences': True,
                                     'name_structure_consistency': 'checked_by_naming_service',
                                     'preferred_CRU_global_search': 'NOT_FULLY_IMPLEMENTED',
                                     'full_IUPAC_rule_conformance': False, 'independent_review': False}
    return support
