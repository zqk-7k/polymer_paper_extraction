"""Bounded connectivity evidence for an explicit two-port unit, not synthesis."""
from rdkit import Chem

VERSION = 'repeat-connection/1.0'

def repeat_window(smiles, copies=3):
    """Build a small open chain window; never infer a unit from a source graph."""
    base = {'version': VERSION, 'is_synthesis_fact': False, 'is_sample_chain_length': False,
            'index_semantics': 'zero_based_atom_indices_not_IUPAC_locants',
            'preferred_CRU_proven': False, 'independent_review': 'NOT_RUN'}
    def stop(code):
        return {**base, 'status': 'OUTSIDE_SCOPE', 'reason_code': code}
    if type(copies) is not int or not 2 <= copies <= 5:
        return stop('WINDOW_COPIES_MUST_BE_2_TO_5')
    mol = Chem.MolFromSmiles(smiles) if isinstance(smiles, str) and smiles else None
    if mol is None or mol.GetNumAtoms() > 240:
        return stop('UNIT_GRAPH_MISSING_INVALID_OR_TOO_LARGE')
    ports = [a for a in mol.GetAtoms() if a.GetAtomicNum() == 0]
    if len(ports) != 2 or len(Chem.GetMolFrags(mol)) != 1:
        return stop('CONNECTED_TWO_PORT_UNIT_REQUIRED')
    if any(a.GetDegree() != 1 or a.GetBonds()[0].GetBondType() != Chem.BondType.SINGLE for a in ports):
        return stop('ONLY_TERMINAL_SINGLE_BOND_PORTS_SUPPORTED')
    if any(a.GetChiralTag() != Chem.ChiralType.CHI_UNSPECIFIED or a.GetNumRadicalElectrons() for a in mol.GetAtoms()):
        return stop('STEREOCENTRE_OR_RADICAL_WINDOW_NOT_IMPLEMENTED')
    if any(b.GetStereo() != Chem.BondStereo.STEREONONE for b in mol.GetBonds()):
        return stop('STEREOBOND_WINDOW_NOT_IMPLEMENTED')
    labels = [p.GetAtomMapNum() for p in ports]
    if any(labels) and (0 in labels or len(set(labels)) != 2):
        return stop('PORT_MAP_LABELS_AMBIGUOUS')
    if all(labels):
        ports.sort(key=lambda a: a.GetAtomMapNum())
    left, right = [p.GetIdx() for p in ports]
    left_atom, right_atom = [p.GetNeighbors()[0].GetIdx() for p in ports]
    if left_atom in (left, right) or right_atom in (left, right):
        return stop('PORT_MUST_CONNECT_TO_A_REAL_ATOM')
    count, combined = mol.GetNumAtoms(), None
    for unit_index in range(copies):
        unit = Chem.Mol(mol)
        for atom in unit.GetAtoms():
            atom.SetIntProp('_pi_repeat', unit_index)
            atom.SetIntProp('_pi_unit_atom', atom.GetIdx())
        combined = unit if combined is None else Chem.CombineMols(combined, unit)
    graph, remove, junctions = Chem.RWMol(combined), [], []
    for index in range(copies - 1):
        graph.AddBond(index * count + right_atom, (index + 1) * count + left_atom, Chem.BondType.SINGLE)
        remove.extend([index * count + right, (index + 1) * count + left])
        junctions.append({'from_repeat': index, 'from_unit_atom': right_atom,
                          'to_repeat': index + 1, 'to_unit_atom': left_atom, 'bond_order': 1})
    for atom_index in sorted(remove, reverse=True):
        graph.RemoveAtom(atom_index)
    try:
        molecule = graph.GetMol()
        Chem.SanitizeMol(molecule)
    except (ValueError, RuntimeError):
        return stop('WINDOW_VALENCE_CHECK_FAILED')
    atom_map = {(a.GetIntProp('_pi_repeat'), a.GetIntProp('_pi_unit_atom')): a.GetIdx()
                for a in molecule.GetAtoms()}
    for junction in junctions:
        first = atom_map[junction['from_repeat'], junction['from_unit_atom']]
        second = atom_map[junction['to_repeat'], junction['to_unit_atom']]
        junction['window_atoms'] = [first, second]
        if molecule.GetBondBetweenAtoms(first, second) is None:
            return stop('WINDOW_JUNCTION_NOT_FOUND')
    return {**base, 'status': 'PASS', 'unit_smiles': smiles,
            'window_smiles': Chem.MolToSmiles(molecule, isomericSmiles=True),
            'window_atom_index_basis': 'window_graph_not_canonical_SMILES_order',
            'window_graph': {'atoms': [{'index': a.GetIdx(), 'element': a.GetSymbol(), 'isotope': a.GetIsotope(), 'charge': a.GetFormalCharge()} for a in molecule.GetAtoms()],
                             'bonds': [{'atoms': [b.GetBeginAtomIdx(), b.GetEndAtomIdx()], 'order': b.GetBondTypeAsDouble()} for b in molecule.GetBonds()]},
            'copies_for_visualization': copies, 'remaining_open_ports': 2,
            'junctions': junctions, 'valence_check': 'PASS',
            'atom_origins': [{'window_atom': a.GetIdx(), 'repeat_index': a.GetIntProp('_pi_repeat'),
                             'unit_atom': a.GetIntProp('_pi_unit_atom')} for a in molecule.GetAtoms()],
            'orientation': 'ascending_explicit_port_labels' if all(labels) else 'one_unanchored_display_orientation',
            'scope': 'open_window_of_explicit_achiral_regular_single_strand_unit',
            'actual_degree_of_polymerization': None,
            'limitations': ['This projection does not establish end groups, synthesis or preferred CRU seniority.']}
