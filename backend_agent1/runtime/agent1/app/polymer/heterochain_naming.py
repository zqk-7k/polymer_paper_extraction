"""Two bounded structural naming families; no catalog or formation inference."""
from rdkit import Chem, rdBase

CONTRACT = 'iupac-heterochain-scoped/1.0'
GUIDE = 'https://iupac.qmul.ac.uk/BriefGuide/polymer.html'
RSSOP = 'https://iupac.qmul.ac.uk/rssop/'
ALKANES = ('methane', 'ethane', 'propane', 'butane', 'pentane', 'hexane',
           'heptane', 'octane', 'nonane', 'decane', 'undecane', 'dodecane')


def _result():
    return dict(contract=CONTRACT, status='OUTSIDE_SCOPE', primary=None,
                reason_code=None, rule_refs=[], canonical_repeat_smiles=None,
                scope='CONSTITUTION_ONLY',
                assumptions=['Supplied ports denote an ideal regular infinite chain.',
                             'Atom maps are labels, not chemical identity.'],
                omitted_fields=['sample_identity', 'end_groups', 'chain_length',
                                'periodic_stereochemistry'],
                preferred_iupac_name=None, full_iupac_conformance=False,
                independent_review='NOT_REVIEWED')


def _read_original(smiles):
    if not isinstance(smiles, str) or not smiles.strip():
        return None, 'INVALID_SMILES_INPUT'
    if len(smiles) > 20000:
        return None, 'INPUT_LIMIT'
    if '|' in smiles:
        return None, 'CXSMILES_UNSUPPORTED'
    params = Chem.SmilesParserParams()
    params.sanitize = False
    params.removeHs = False  # Do not silently remove explicit atoms.
    params.parseName = False
    params.allowCXSMILES = False
    with rdBase.BlockLogs():
        mol = Chem.MolFromSmiles(smiles, params)
    if mol is None:
        return None, 'INVALID_SMILES'
    if mol.GetNumAtoms() > 256:
        return None, 'ATOM_LIMIT'
    if len(Chem.GetMolFrags(mol)) != 1:
        return None, 'MULTIPLE_COMPONENTS'
    ports = [a for a in mol.GetAtoms() if a.GetAtomicNum() == 0]
    if len(ports) != 2:
        return None, 'EXACTLY_TWO_PORTS_REQUIRED'
    if any(a.GetDegree() != 1 or a.GetNumExplicitHs() or
           a.GetBonds()[0].GetBondType() != Chem.BondType.SINGLE or
           a.GetNeighbors()[0].GetAtomicNum() == 0 for a in ports):
        return None, 'TERMINAL_SINGLE_BOND_PORTS_REQUIRED'
    if any(a.GetIsotope() for a in mol.GetAtoms()):
        return None, 'ISOTOPE_UNSUPPORTED'
    if any(a.GetFormalCharge() for a in mol.GetAtoms()):
        return None, 'CHARGE_UNSUPPORTED'
    # Inspect raw tags before sanitization can discard invalid/redundant stereo.
    if (any(a.GetChiralTag() != Chem.ChiralType.CHI_UNSPECIFIED for a in mol.GetAtoms())
            or any(b.GetStereo() != Chem.BondStereo.STEREONONE or
                   b.GetBondDir() != Chem.BondDir.NONE for b in mol.GetBonds())):
        return None, 'STEREOCHEMISTRY_UNSUPPORTED'
    with rdBase.BlockLogs():
        Chem.SanitizeMol(mol)
    if any(a.GetNumRadicalElectrons() for a in mol.GetAtoms()):
        return None, 'RADICAL_UNSUPPORTED'
    if any(a.GetAtomicNum() not in (0, 6, 8, 14) for a in mol.GetAtoms()):
        return None, 'ELEMENT_OUTSIDE_FAMILIES'
    valences = {0: 1, 6: 4, 8: 2, 14: 4}
    if any(a.GetTotalValence() != valences[a.GetAtomicNum()] for a in mol.GetAtoms()):
        return None, 'NORMAL_VALENCE_REQUIRED'
    return mol, None


def _classify(mol):
    if mol.GetRingInfo().NumRings():
        return None, None, 'RING_UNSUPPORTED'
    if any(b.GetBondType() != Chem.BondType.SINGLE for b in mol.GetBonds()):
        return None, None, 'UNSATURATED_BOND_UNSUPPORTED'
    ports = [a.GetIdx() for a in mol.GetAtoms() if a.GetAtomicNum() == 0]
    path = set(Chem.GetShortestPath(mol, *ports)[1:-1])
    atoms = [a for a in mol.GetAtoms() if a.GetAtomicNum()]
    oxygens = [a for a in atoms if a.GetAtomicNum() == 8]
    carbons = [a for a in atoms if a.GetAtomicNum() == 6]
    silicon = [a for a in atoms if a.GetAtomicNum() == 14]
    if len(oxygens) != 1 or oxygens[0].GetDegree() != 2:
        return None, None, 'PRIMITIVE_OXYGEN_COUNT_OR_CONNECTIVITY'
    if not silicon:
        # All atoms must lie on the port path, with exactly one divalent O.
        if len(path) != len(atoms) or any(a.GetDegree() != 2 for a in atoms):
            return None, None, 'ETHER_BRANCH_OR_PENDANT_UNSUPPORTED'
        n = len(carbons)
        if not 1 <= n <= 12:
            return None, None, 'ALKYLENE_LENGTH_OUTSIDE_1_12'
        subunit = ('oxymethylene' if n == 1 else 'oxyethylene' if n == 2
                   else f'oxy({ALKANES[n - 1]}-1,{n}-diyl)')
        return subunit, 'ether', None
    # Full graph: two backbone atoms, exactly two terminal CH3 attached to Si.
    if (len(atoms) == 4 and len(silicon) == 1 and len(carbons) == 2
            and path == {oxygens[0].GetIdx(), silicon[0].GetIdx()}
            and silicon[0].GetDegree() == 4
            and all(a.GetDegree() == 1 and a.GetTotalNumHs() == 3 and
                    a.GetNeighbors()[0].GetIdx() == silicon[0].GetIdx() for a in carbons)):
        return 'oxy(dimethylsilanediyl)', 'silicon', None
    return None, None, 'SILICON_OUTSIDE_EXACT_DIMETHYLSILOXANE'


def _roundtrip(text, subunit, kernel):
    """Local consistency evidence only; supplied kernels must also be offline."""
    try:
        if kernel is not None:
            parsed = kernel.parse({'name': text, 'interpretation_policy': 'evidence_only'})
            if parsed.get('status') == 'PARSED':
                return parsed.get('semantic_projection', {}).get('constitution_key')
        else:
            # resolve_unit consumes the CRU expression, not its poly wrapper;
            # it constructs the graph directly, without source-name inference.
            from polymer.units import resolve_unit
            parsed = resolve_unit(subunit)
            if parsed.get('status') == 'PARSED':
                return parsed.get('periodic', {}).get('periodic_graph_key')
    except Exception:
        # An unavailable/failed optional parser must never upgrade a candidate.
        pass
    return None


def name(smiles, kernel=None):
    """Name a supplied two-port graph within contract iupac-heterochain-scoped/1.0."""
    result = _result()
    try:
        mol, reason = _read_original(smiles)
    except (ValueError, RuntimeError, TypeError, OverflowError):
        mol, reason = None, 'INVALID_SMILES_OR_VALENCE'
    if mol is None:
        return {**result, 'reason_code': reason}
    try:
        from polymer.periodic import canonicalize_unit
        periodic = canonicalize_unit(smiles)
        if periodic.get('status') != 'PARSED':
            return {**result, 'reason_code': 'REPEAT_GRAPH_OUTSIDE_KERNEL_SCOPE'}
        result['canonical_repeat_smiles'] = periodic['canonical_repeat_smiles']
        primitive = Chem.MolFromSmiles(periodic['canonical_repeat_smiles'])
        subunit, family, reason = _classify(primitive)
    except ImportError:
        return {**result, 'reason_code': 'CANONICALIZER_UNAVAILABLE'}
    except (ValueError, RuntimeError, TypeError, KeyError):
        return {**result, 'reason_code': 'REPEAT_GRAPH_OUTSIDE_KERNEL_SCOPE'}
    if reason:
        return {**result, 'reason_code': reason}
    text = f'poly[{subunit}]' if '(' in subunit else f'poly({subunit})'
    result['rule_refs'] = [
        {'rule': 'RSSOP2002 Rule4', 'url': RSSOP + 'ss04.html#p42'},
        {'rule': 'RSSOP2002 Rule13', 'url': RSSOP + 'ss05.html#52r13'},
        *[{'rule': f'RSSOP2002 Rule{n}', 'url': RSSOP + 'ss06t08.html'}
          for n in (18, 19, 20)],
        {'rule': ('BriefGuide2012 §5' if family == 'silicon' else
                  'BriefGuide2012 §4.1/Table3'),
         'url': GUIDE + ('#5.0' if family == 'silicon' else '#4.1')}]
    recovered = _roundtrip(text, subunit, kernel)
    if not recovered:
        status, reason = 'CANDIDATE', 'NAME_ROUNDTRIP_UNAVAILABLE'
    elif recovered != periodic['periodic_graph_key']:
        return {**result, 'reason_code': 'NAME_ROUNDTRIP_MISMATCH'}
    else:
        status, reason = 'IUPAC_AT_DECLARED_SCOPE', None
    return {**result, 'status': status, 'reason_code': reason,
            'primary': {'text': text, 'kind': 'structure_based',
                        'qualification': status, 'scope': 'CONSTITUTION_ONLY'}}
