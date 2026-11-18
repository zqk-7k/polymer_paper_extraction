"""Checked locants and explicit repeat connections; not a second identity kernel."""
import re
from rdkit import Chem
from .repeat_connection import repeat_window
from .periodic import canonicalize_unit

VERSION = 'unit-evidence/1.0'
STEMS = {'meth': 1, 'eth': 2, 'prop': 3, 'but': 4, 'pent': 5, 'hex': 6,
         'hept': 7, 'oct': 8, 'non': 9, 'dec': 10, 'undec': 11, 'dodec': 12}

def locant_mapping(name, smiles):
    """Enumerate equivalent graph mappings for a small, explicit parent vocabulary."""
    result = {'version': VERSION, 'status': 'OUTSIDE_SCOPE', 'mappings': [],
              'scope': 'unsubstituted_benzene_or_saturated_acyclic_diyl_only',
              'index_semantics': 'indices_refer_to_input_smiles_not_to_IUPAC_locants',
              'is_independent_nomenclature_review': False}
    if not isinstance(name, str) or not isinstance(smiles, str):
        return result
    ring = re.fullmatch(r'(\d+),(\d+)-phenylene', name)
    ring = ring or re.fullmatch(r'benzene-(\d+),(\d+)-diyl', name)
    chain = re.fullmatch(r'([a-z]+)ane-(\d+),(\d+)-diyl', name)
    if ring:
        parent, n, a, b = 'c1ccccc1', 6, int(ring[1]), int(ring[2])
    elif chain and chain[1] in STEMS:
        n, a, b = STEMS[chain[1]], int(chain[2]), int(chain[3])
        parent = 'C' * n
    else:
        return result
    if not 1 <= a <= n or not 1 <= b <= n:
        return {**result, 'status': 'FAIL', 'reason_code': 'LOCANT_OUTSIDE_PARENT'}
    target = Chem.MolFromSmiles(smiles)
    if target is None:
        return {**result, 'status': 'FAIL', 'reason_code': 'GRAPH_INVALID'}
    reference = Chem.RWMol(Chem.MolFromSmiles(parent))
    for pos in (a, b):
        port = reference.AddAtom(Chem.Atom(0))
        reference.AddBond(pos - 1, port, Chem.BondType.SINGLE)
    try:
        reference = reference.GetMol()
        Chem.SanitizeMol(reference)
    except (ValueError, RuntimeError):
        return {**result, 'status': 'FAIL', 'reason_code': 'PARENT_LOCANT_VALENCE'}
    clean = Chem.Mol(target)
    for atom in clean.GetAtoms():
        atom.SetAtomMapNum(0)
    if Chem.MolToSmiles(clean, isomericSmiles=True) != Chem.MolToSmiles(reference, isomericSmiles=True):
        return {**result, 'status': 'FAIL', 'reason_code': 'NAME_PARENT_GRAPH_MISMATCH'}
    matches = clean.GetSubstructMatches(reference, useChirality=True, uniquify=False, maxMatches=33)
    mappings = [{'locant_to_atom': {str(i + 1): match[i] for i in range(n)},
                 'ports': [{'locant': str(pos), 'port_atom': match[n + j], 'attached_atom': match[pos - 1]}
                           for j, pos in enumerate((a, b))]} for match in matches[:32]]
    return {**result, 'status': 'MAPPED' if len(matches) == 1 else 'SYMMETRY_EQUIVALENT_MAPPINGS',
            'name': name, 'input_smiles': smiles, 'mappings': mappings,
            'graph_match': 'PASS', 'truncated': len(matches) > 32,
            'unique_absolute_atom_numbering': len(matches) == 1,
            'method': 'explicit_parent_locants_then_full_isomeric_graph_match'}

def enrich_unit_evidence(support):
    """Called by the shared support builder, so naming and agents receive it."""
    for component in support.get('components', []):
        if component.get('kind') != 'unit':
            continue
        graph = component.get('graph') or {}
        mapping = locant_mapping(component.get('label'), graph.get('smiles'))
        component['locant_graph_mapping'] = mapping
        component['locants_to_atom_mapping'] = mapping['status']
    constitution = support.get('constitution') or {}
    smiles, key = constitution.get('canonical_repeat_smiles'), constitution.get('graph_key')
    connection = {'status': 'NOT_APPLICABLE', 'reason_code': 'NO_WHOLE_REGULAR_CONSTITUTION',
                  'scope': 'no_connections_invented_between_source_or_irregular_components'}
    if smiles and key:
        actual = canonicalize_unit(smiles)
        if actual.get('periodic_graph_key') != key:
            connection = {'status': 'FAIL', 'reason_code': 'PASSPORT_CONSTITUTION_GRAPH_MISMATCH'}
        else:
            connection = repeat_window(smiles)
            connection['evidence_ref'] = support.get('passport_ref')
            connection['constitution_key'] = key
    from .backbone_direction import direction_evidence
    from .cru_locant_selection import locant_selection
    support['backbone_direction_evidence'] = direction_evidence(smiles)
    selection = locant_selection(smiles)
    if not smiles:
        selection = {**selection, 'reason_code': 'NO_WHOLE_REGULAR_CONSTITUTION'}
    support['cru_locant_selection_evidence'] = selection
    support['repeat_connection_evidence'] = connection
    support['chemical_capability_version'] = VERSION
    support['connection_claims'] = {'architecture': 'reported_descriptor_relationships',
                                  'atomic': 'explicit_regular_unit_only',
                                  'source_reaction': 'not_inferred_as_experimental_fact'}
    extra = [{'rule_id': 'PI-UNIT-WINDOW-001', 'status': connection['status'], 'scope': connection.get('scope'), 'evidence_ref': support.get('passport_ref')}]
    for c in support.get('components', []):
        mapping = c.get('locant_graph_mapping')
        if mapping:
            extra.append({'rule_id': 'PI-LOCANT-MAPPING-001', 'status': mapping.get('graph_match', mapping['status']), 'scope': c.get('occurrence_id'), 'evidence_ref': support.get('passport_ref')})
    direction = support['backbone_direction_evidence']
    if direction['status'] in ('DECIDED', 'TIED'):
        extra.append({'rule_id': 'PI-PATH13-001', 'status': 'PASS' if direction['status'] == 'DECIDED' else 'NOT_RUN',
                      'scope': direction['scope'], 'evidence_ref': support.get('passport_ref')})
    extra.append({'rule_id': 'PI-CRU-SELECTION-001',
                  'status': 'PASS' if selection['status'] == 'DECIDED' else 'OUTSIDE_SCOPE',
                  'scope': selection.get('subunit_class') or selection.get('reason_code'),
                  'reason_code': selection.get('reason_code'),
                  'evidence_ref': support.get('passport_ref')})
    support.setdefault('rule_checks', []).extend(extra)
    support['rule_ids'] = sorted(set(support.get('rule_ids', [])) | {c['rule_id'] for c in extra})
    if any(c['status'] == 'FAIL' for c in extra):
        support['chemical_check_status'] = 'FAIL'
    return support
