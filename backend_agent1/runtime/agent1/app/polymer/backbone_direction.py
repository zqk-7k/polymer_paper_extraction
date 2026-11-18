"""RSSOP 2002 Rules 4/13/19: a deliberately bounded executable profile."""
from rdkit import Chem

VERSION = 'backbone-direction/1.0'
SOURCE = 'https://iupac.qmul.ac.uk/rssop/ss05.html'
ORDER = {8: 0, 16: 1, 7: 2}
NAMES = {8: 'oxy', 16: 'sulfanediyl', 7: 'imino'}
STEMS = {3: 'prop', 4: 'but', 5: 'pent', 6: 'hex', 7: 'hept',
         8: 'oct', 9: 'non', 10: 'dec', 11: 'undec', 12: 'dodec'}


def direction_evidence(smiles):
    """Two distinct isolated O/S/N subunits in an unbranched saturated unit.

    Equal path lengths are NOT resolved here. Input atom indices are retained;
    this is a subset of Rule 13, not a general preferred-CRU proof.
    """
    base = {'version': VERSION, 'status': 'OUTSIDE_SCOPE', 'source_url': SOURCE,
            'rule_ids': ['PI-PATH13-001'], 'official_rules': [4, 13, 19],
            'scope': 'saturated_unbranched_two_distinct_isolated_O_S_N_subunits',
            'input_smiles': smiles, 'full_preferred_CRU_proven': False,
            'independent_review': 'NOT_RUN'}
    def stop(reason):
        return {**base, 'reason_code': reason}
    mol = Chem.MolFromSmiles(smiles) if isinstance(smiles, str) and smiles else None
    if mol is None or not 4 <= mol.GetNumAtoms() <= 60:
        return stop('GRAPH_OUTSIDE_SIZE_OR_SYNTAX_SCOPE')
    ports = [a.GetIdx() for a in mol.GetAtoms() if a.GetAtomicNum() == 0]
    if len(ports) != 2 or len(Chem.GetMolFrags(mol)) != 1 or mol.GetRingInfo().NumRings():
        return stop('CONNECTED_ACYCLIC_TWO_PORT_UNIT_REQUIRED')
    if any(mol.GetAtomWithIdx(i).GetDegree() != 1 for i in ports):
        return stop('TERMINAL_PORTS_REQUIRED')
    atoms = list(mol.GetAtoms())
    if any(a.GetIsotope() or a.GetFormalCharge() or a.GetNumRadicalElectrons() or
           a.GetChiralTag() != Chem.ChiralType.CHI_UNSPECIFIED for a in atoms):
        return stop('ISOTOPE_CHARGE_RADICAL_OR_STEREO_NOT_IN_PROFILE')
    if any(b.GetBondType() != Chem.BondType.SINGLE or
           b.GetStereo() != Chem.BondStereo.STEREONONE for b in mol.GetBonds()):
        return stop('SATURATED_SINGLE_BONDS_REQUIRED')
    path = list(Chem.GetShortestPath(mol, *ports))[1:-1]
    if len(path) != mol.GetNumAtoms() - 2:
        return stop('BRANCHED_UNIT_OUTSIDE_PROFILE')
    zs = [mol.GetAtomWithIdx(i).GetAtomicNum() for i in path]
    hetero = [i for i, z in enumerate(zs) if z != 6]
    if len(hetero) != 2 or any(zs[i] not in ORDER for i in hetero) or zs[hetero[0]] == zs[hetero[1]]:
        return stop('TWO_DISTINCT_O_S_N_SUBUNITS_REQUIRED')
    start, end = sorted(hetero, key=lambda i: ORDER[zs[i]])
    n = len(path)
    forward, reverse = (end - start) % n, (start - end) % n
    distances = {'forward_intervening_atoms': forward - 1, 'reverse_intervening_atoms': reverse - 1}
    if min(forward, reverse) <= 1:
        return stop('ADJACENT_HETEROATOMS_FORM_DIFFERENT_SUBUNIT_SCOPE')
    if forward == reverse:
        return {**base, 'status': 'TIED', 'reason_code': 'RULE14_OR_FURTHER_TIE_BREAK_REQUIRED',
                'path_lengths': distances, 'candidate_name': None}
    step = 1 if forward < reverse else -1
    traversal = [path[(start + step * i) % n] for i in range(n)]
    ordered_z = [mol.GetAtomWithIdx(i).GetAtomicNum() for i in traversal]
    subunits, i = [], 0
    while i < n:
        if ordered_z[i] in NAMES:
            subunits.append(NAMES[ordered_z[i]])
            i += 1
        else:
            j = i
            while j < n and ordered_z[j] == 6:
                j += 1
            length = j - i
            label = {1: 'methylene', 2: 'ethylene'}.get(length)
            if label is None:
                if length not in STEMS:
                    return stop('CARBON_SUBUNIT_LENGTH_OUTSIDE_NAMING_VOCABULARY')
                label = STEMS[length] + 'ane-1,' + str(length) + '-diyl'
            subunits.append(label)
            i = j
    body = ''.join('(' + s + ')' if '-diyl' in s else s for s in subunits)
    return {**base, 'status': 'DECIDED', 'reason_code': None,
            'path_lengths': distances, 'selected_direction': 'forward' if step == 1 else 'reverse',
            'highest_seniority_atom': path[start], 'second_seniority_atom': path[end],
            'traversal_input_atom_indices': traversal, 'subunits': subunits,
            'candidate_name': 'poly(' + body + ')',
            'candidate_status': 'REQUIRES_EXISTING_KERNEL_ROUNDTRIP',
            'assumptions': ['Input is the explicit regular single-strand unit; no synthesis inferred.']}
