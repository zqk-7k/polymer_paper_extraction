"""Read-only graph completeness: absent structure is not a malformed structure."""
from collections import Counter
from rdkit import Chem

VERSION = 'knowledge-quality/1.0'

def classify_structure(row):
    smiles = row.get('canonical_smiles') or row.get('smiles')
    if smiles is None or (isinstance(smiles, str) and not smiles.strip()):
        return {'state': 'STRUCTURE_MISSING', 'reason': 'NO_REPORTED_GRAPH',
                'graph_parsed': False, 'port_count': None}
    mol = Chem.MolFromSmiles(smiles) if isinstance(smiles, str) else None
    if mol is None:
        return {'state': 'STRUCTURE_INVALID', 'reason': 'GRAPH_PARSE_FAILED',
                'graph_parsed': False, 'port_count': None}
    ports = [a for a in mol.GetAtoms() if a.GetAtomicNum() == 0]
    expected = {'source_molecules': 0, 'fragments_cu': 2, 'end_groups': 1}.get(row.get('role'))
    valid = expected is None or len(ports) == expected
    if ports:
        valid = valid and len(Chem.GetMolFrags(mol)) == 1 and all(a.GetDegree() == 1 for a in ports)
    return {'state': 'GRAPH_ROLE_CONFLICT' if not valid else 'GRAPH_READABLE',
            'reason': None if valid else 'ROLE_OR_PORT_CHECK_FAILED',
            'graph_parsed': True, 'port_count': len(ports), 'independent_review': 'NOT_RUN'}

def summarize_quality(rows):
    counts = Counter(classify_structure(row)['state'] for row in rows)
    return {'version': VERSION, 'counts': dict(counts), 'total': len(rows),
            'scope': 'readability_and_basic_role_only_not_chemical_truth',
            'full_iupac_conformance': False, 'records_modified': 0}
