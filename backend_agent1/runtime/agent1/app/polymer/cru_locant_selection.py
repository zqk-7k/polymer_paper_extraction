"""Bounded Rule 11/12 decision for simple CRUs (RSSOP 2002 §5.1).

Implements steps 3 and 4 of §5.1 inside the classes this module declares:
  * step 3 - the free valences (attachment atoms) of the single subunit take the
    lowest possible locants;
  * step 4 - the direction is chosen so that substituent locants are as low as
    possible.
Everything else (fused/bridged/spiro systems, ring assemblies, polycyclic
numbering, more than two ring heteroatoms, stereochemistry, isotopes, radicals,
charges) is refused with an explicit reason code.  The result is a located
decision: not a conformance proof, not an independent review, and not a claim
that the preferred CRU has been proven.
"""
from __future__ import annotations
from rdkit import Chem

VERSION = 'cru-locant-selection/1.0'
SOURCE = 'https://iupac.qmul.ac.uk/rssop/ss05.html'
OFFICIAL_LOCATOR = '§5.1 Simple CRUs (Rules 11, 12)'
OFFICIAL_RULES = [11, 12]

# Worked examples printed with the official §5.1 text, recorded per outcome so
# the bounded scope can be compared with the official example set instead of
# being asserted in prose.  'naphthalene-2,6-diyl' is the one official example
# this module refuses: fused-ring numbering is not modelled here.
OFFICIAL_EXAMPLE_LOCATOR = '§5.1 Simple CRUs, worked examples table'
OFFICIAL_EXAMPLES = {
    'ACYCLIC_SINGLE_SUBUNIT': ['1-chloropropane-1,3-diyl'],
    'MONOCARBOCYCLIC_SINGLE_RING': ['cyclohexane-1,4-diyl'],
    'FIXED_NUMBERING_RING_SYSTEM': ['morpholine-2,6-diyl'],
    'MULTIPLE_RINGS_FUSED_BRIDGED_SPIRO_OR_RING_ASSEMBLY_OUTSIDE_SCOPE': ['naphthalene-2,6-diyl'],
}
OFFICIAL_EXAMPLES_OUTSIDE_BOUNDED_SCOPE = ['naphthalene-2,6-diyl']
HETERO_PRIORITY = [8, 16, 34, 52, 7, 15, 33, 51, 83, 14, 32, 50, 82, 5, 80]
MAX_ATOMS = 60
MAX_RING_ATOMS = 8

def _base(smiles):
    return {'version': VERSION, 'status': 'OUTSIDE_SCOPE', 'source_url': SOURCE,
            'official_locator': OFFICIAL_LOCATOR, 'official_rules': OFFICIAL_RULES,
            'scope': 'single_subunit_two_port_unit_locant_steps_3_and_4',
            'official_example_locator': OFFICIAL_EXAMPLE_LOCATOR,
            'official_examples_outside_scope': OFFICIAL_EXAMPLES_OUTSIDE_BOUNDED_SCOPE,
            'input_smiles': smiles, 'preferred_cru_proven': False, 'independent_review': 'NOT_RUN'}

def _priority(atomic_number):
    return HETERO_PRIORITY.index(atomic_number) if atomic_number in HETERO_PRIORITY else len(HETERO_PRIORITY)

def _substituent_locants(mol, ordered, excluded):
    locants = []
    for position, index in enumerate(ordered, 1):
        for neighbour in mol.GetAtomWithIdx(index).GetNeighbors():
            other = neighbour.GetIdx()
            if other in excluded or other in ordered:
                continue
            locants.append(position)
    return sorted(locants)

def _key(ordered, attachments, mol, ports):
    return (tuple(sorted(ordered.index(atom) + 1 for atom in attachments)),
            tuple(_substituent_locants(mol, ordered, set(ports))))

def locant_selection(smiles):
    """Return the bounded §5.1 steps 3-4 decision for one two-port subunit graph."""
    base = _base(smiles)
    mol = Chem.MolFromSmiles(smiles) if isinstance(smiles, str) and smiles else None
    if mol is None or not 2 <= mol.GetNumAtoms() <= MAX_ATOMS:
        return {**base, 'reason_code': 'GRAPH_OUTSIDE_SIZE_OR_SYNTAX_SCOPE'}
    if len(Chem.GetMolFrags(mol)) != 1:
        return {**base, 'reason_code': 'SINGLE_CONNECTED_UNIT_REQUIRED'}
    if any(atom.GetFormalCharge() for atom in mol.GetAtoms()):
        return {**base, 'reason_code': 'CHARGE_NOT_IN_PROFILE'}
    if any(atom.GetIsotope() or atom.GetNumRadicalElectrons()
           or atom.GetChiralTag() != Chem.ChiralType.CHI_UNSPECIFIED for atom in mol.GetAtoms()):
        return {**base, 'reason_code': 'STEREO_ISOTOPE_OR_RADICAL_NOT_IN_PROFILE'}
    ports = [atom.GetIdx() for atom in mol.GetAtoms() if atom.GetAtomicNum() == 0]
    if len(ports) != 2 or any(mol.GetAtomWithIdx(index).GetDegree() != 1 for index in ports):
        return {**base, 'reason_code': 'TWO_TERMINAL_PORTS_REQUIRED'}
    attachments = sorted({neighbour.GetIdx() for port in ports for neighbour in mol.GetAtomWithIdx(port).GetNeighbors()})
    if len(attachments) != 2:
        return {**base, 'reason_code': 'DISTINCT_ATTACHMENT_ATOMS_REQUIRED'}
    rings = [list(ring) for ring in mol.GetRingInfo().AtomRings()]
    if len(rings) > 1:
        return {**base, 'reason_code': 'MULTIPLE_RINGS_FUSED_BRIDGED_SPIRO_OR_RING_ASSEMBLY_OUTSIDE_SCOPE'}
    if rings:
        return _ring_case(mol, base, rings[0], attachments, ports)
    return _acyclic_case(mol, base, attachments, ports)

def _attachment_locants(mol, ports, ordered):
    locants = {}
    for port, name in zip(ports, ('port1', 'port2')):
        neighbour = mol.GetAtomWithIdx(port).GetNeighbors()[0].GetIdx()
        locants[name] = ordered.index(neighbour) + 1 if neighbour in ordered else None
    return locants

def _acyclic_case(mol, base, attachments, ports):
    path = [index for index in Chem.GetShortestPath(mol, attachments[0], attachments[1])
            if mol.GetAtomWithIdx(index).GetAtomicNum() != 0]
    reverse = list(reversed(path))
    forward_key, reverse_key = _key(path, attachments, mol, ports), _key(reverse, attachments, mol, ports)
    if forward_key <= reverse_key:
        orientation, chosen, chosen_key = 'FORWARD', path, forward_key
    else:
        orientation, chosen, chosen_key = 'REVERSE', reverse, reverse_key
    locants = _attachment_locants(mol, ports, chosen)
    result = {**base, 'status': 'DECIDED', 'subunit_class': 'ACYCLIC_SINGLE_SUBUNIT', 'official_rule': 11,
              'attachment_locants': locants, 'substituent_locants': list(chosen_key[1]),
              'preferred_orientation': orientation, 'direction_decided': True,
              'lowest_locant_pair_achievable': True, 'chain_atoms_between_attachments': len(path),
              'steps_applied': ['rule_11_step_3_free_valences_lowest_locants',
                                'rule_11_step_4_substituents_lowest_locants'],
              'left_hand_lowest_locant': locants['port1'] is not None and locants['port2'] is not None
              and locants['port1'] < locants['port2'],
              'official_examples': OFFICIAL_EXAMPLES['ACYCLIC_SINGLE_SUBUNIT'],
              'note': ('Rule 11 step 4 applied to off-path substituents'
                       if chosen_key[1] else 'no off-path substituents; Rule 11 step 4 has nothing to decide')}
    return result

def _ring_case(mol, base, ring, attachments, ports):
    if not set(attachments) <= set(ring):
        return {**base, 'reason_code': 'BOTH_ATTACHMENTS_ON_THE_SINGLE_RING_REQUIRED'}
    if len(ring) > MAX_RING_ATOMS:
        return {**base, 'reason_code': 'RING_SIZE_OUTSIDE_BOUNDED_PROFILE'}
    hetero = [index for index in ring if mol.GetAtomWithIdx(index).GetAtomicNum() != 6]
    if len(hetero) > 2:
        return {**base, 'reason_code': 'RING_SYSTEM_NUMBERING_OUTSIDE_BOUNDED_PROFILE'}
    if hetero:
        start = min(hetero, key=lambda index: (_priority(mol.GetAtomWithIdx(index).GetAtomicNum()), index))
        index = ring.index(start)
        forward = ring[index:] + ring[:index]
        reverse = [start] + list(reversed(ring[index + 1:] + ring[:index]))
        subunit_class, rule = 'FIXED_NUMBERING_RING_SYSTEM', 12
        forward_key, reverse_key = _key(forward, attachments, mol, ports), _key(reverse, attachments, mol, ports)
        best_key = min(forward_key, reverse_key)
        if forward_key == reverse_key:
            orientation, chosen, chosen_key = 'EQUAL', forward, forward_key
        elif forward_key == best_key:
            orientation, chosen, chosen_key = 'FORWARD', forward, forward_key
        else:
            orientation, chosen, chosen_key = 'REVERSE', reverse, reverse_key
    else:
        subunit_class, rule, orientation = 'MONOCARBOCYCLIC_SINGLE_RING', 11, 'EQUAL'
        candidates = []
        for index in range(len(ring)):
            rotation = ring[index:] + ring[:index]
            candidates.extend([rotation, [rotation[0]] + list(reversed(rotation[1:]))])
        chosen, chosen_key = min(((candidate, _key(candidate, attachments, mol, ports)) for candidate in candidates),
                                 key=lambda pair: pair[1])
    locants = _attachment_locants(mol, ports, chosen)
    steps = ['rule_11_step_3_free_valences_lowest_locants']
    if rule == 12:
        steps = ['rule_12_fixed_ring_numbering'] + steps
    else:
        steps.append('rule_11_ring_numbering_by_minimal_rotation_and_direction')
    return {**base, 'status': 'DECIDED', 'subunit_class': subunit_class, 'official_rule': rule,
            'attachment_locants': locants, 'minimal_attachment_pair': list(sorted(chosen_key[0])),
            'substituent_locants': list(chosen_key[1]), 'preferred_orientation': orientation,
            'direction_decided': True, 'lowest_locant_pair_achievable': True, 'ring_size': len(ring),
            'steps_applied': steps,
            'hetero_atoms_in_ring': len(hetero),
            'fixed_numbering_start': 'highest_priority_ring_heteroatom' if hetero else 'attachment_atom',
            'left_hand_lowest_locant': locants['port1'] is not None and locants['port2'] is not None
            and locants['port1'] < locants['port2'],
            'official_examples': OFFICIAL_EXAMPLES[subunit_class],
            'note': ('Rule 12 fixed ring numbering retained for both directions of progress'
                     if rule == 12 else 'Rule 11 lowest locants for the two attachment atoms')}
