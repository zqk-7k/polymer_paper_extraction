"""Read-only chemical/connection evidence for naming; never edits a passport."""
from copy import deepcopy
from rdkit import Chem
from .periodic import canonicalize_unit

VERSION = 'chemical-support/1.0'
BG = 'https://iupac.qmul.ac.uk/BriefGuide/polymer.html'
RSSOP = 'https://iupac.qmul.ac.uk/rssop/ss01t03.html'
RELATIONS = {
    'co': ('unspecified_copolymer_sequence', 'PI-SEQUENCE-001'),
    'ran': ('random_sequence', 'PI-SEQUENCE-001'),
    'stat': ('statistical_sequence', 'PI-SEQUENCE-001'),
    'alt': ('alternating_sequence', 'PI-SEQUENCE-001'),
    'per': ('periodic_sequence', 'PI-SEQUENCE-001'),
    'block': ('ordered_blocks', 'PI-BLOCK-001'),
    'graft': ('backbone_and_sidechain', 'PI-GRAFT-001'),
    'blend': ('physical_assembly_not_covalent_connection', 'PI-BLEND-001'),
    '/': ('irregular_units_sequence_unspecified', 'PI-IRREGULAR-001'),
}
FUNCTIONS = {'alkene': '[CX3]=[CX3]', 'alcohol': '[OX2H][CX4]',
             'carboxylic_acid': '[CX3](=O)[OX2H]', 'amine': '[NX3;H1,H2;!$(N[C,S,P]=O)]',
             'ester': '[CX3](=O)[OX2][#6]', 'amide': '[CX3](=O)[NX3]'}

def inspect_graph(smiles, role='unknown'):
    mol = Chem.MolFromSmiles(smiles) if isinstance(smiles, str) and smiles else None
    if mol is None:
        return {'status': 'NOT_AVAILABLE', 'reason_code': 'STRUCTURE_MISSING_OR_INVALID', 'ports': []}
    ports = []
    for atom in mol.GetAtoms():
        if atom.GetAtomicNum() != 0:
            continue
        neighbours = list(atom.GetNeighbors())
        ports.append({'atom_index': atom.GetIdx(), 'map_label': atom.GetAtomMapNum() or None,
                      'degree': atom.GetDegree(), 'neighbour_indices': [n.GetIdx() for n in neighbours],
                      'bond_orders': [b.GetBondTypeAsDouble() for b in atom.GetBonds()]})
    connected = len(Chem.GetMolFrags(mol)) == 1
    port_valid = bool(ports) and all(p['degree'] == 1 and p['bond_orders'] == [1.0] for p in ports)
    if not ports:
        kind = 'finite_source_molecule' if role in ('source', 'source_molecule', 'source_molecules') else 'finite_graph'
    else:
        kind = 'two_port_unit' if len(ports) == 2 else 'multi_or_single_port_fragment'
    periodic = canonicalize_unit(smiles) if len(ports) == 2 and connected and port_valid else None
    flags = {'stereo_encoded': any(a.GetChiralTag() != Chem.ChiralType.CHI_UNSPECIFIED for a in mol.GetAtoms())
             or any(b.GetStereo() != Chem.BondStereo.STEREONONE for b in mol.GetBonds()),
             'isotopes_encoded': any(a.GetIsotope() for a in mol.GetAtoms()),
             'charge_encoded': any(a.GetFormalCharge() for a in mol.GetAtoms()),
             'radicals_encoded': any(a.GetNumRadicalElectrons() for a in mol.GetAtoms())}
    groups = {name: [list(match) for match in mol.GetSubstructMatches(Chem.MolFromSmarts(pattern))]
              for name, pattern in FUNCTIONS.items()}
    return {'status': 'GRAPH_CHECKED', 'role': kind, 'smiles': smiles, 'ports': ports,
            'port_count': len(ports), 'connected': connected,
            'port_check': 'PASS' if port_valid and connected else ('NOT_APPLICABLE' if not ports else 'FAIL'),
            'periodic': periodic, 'features': flags, 'functional_group_matches': groups,
            'functional_groups_are_reactivity_hypotheses': True,
            'index_semantics': 'RDKit_atom_indices_NOT_IUPAC_locants',
            'independent_review': 'NOT_RUN'}

def build_support(kernel, passport, include_models=False):
    if not passport:
        return {'version': VERSION, 'status': 'PARTIAL', 'components': [], 'connections': [],
                'rule_ids': [], 'reason_code': 'PASSPORT_REQUIRED'}
    core = passport.get('chemical_core') or {}
    ref = (passport.get('integrity') or {}).get('snapshot_key')
    original = (passport.get('evidence') or {}).get('original_name')
    parsed = kernel.parse({'name': original, 'interpretation_policy': 'evidence_only'}) if original else {}
    components = []
    for leaf in parsed.get('components') or []:
        unit, molecule = leaf.get('unit') or {}, leaf.get('molecule') or {}
        smiles = unit.get('unit_smiles') or molecule.get('isomeric_smiles')
        components.append({'occurrence_id': leaf.get('occurrence_id'), 'label': leaf.get('raw'),
                           'kind': leaf.get('kind'), 'role': leaf.get('role'), 'name_span': leaf.get('span'),
                           'graph_key': molecule.get('molecule_key') or (unit.get('periodic') or {}).get('periodic_graph_key'),
                           'subunit_names': unit.get('subunit_names', []), 'graph': inspect_graph(smiles, leaf.get('kind')),
                           'source': molecule.get('source') or unit.get('source'), 'evidence_ref': ref})
    connections, rules = [], {'PI-BRACKET-001', 'PI-IDENTITY-001'}
    def walk(node):
        op = node.get('operator')
        if op:
            meaning, rule = RELATIONS.get(op, ('scope_specific_relation_not_fully_implemented', 'PI-IDENTITY-001'))
            children = node.get('children') or []
            connections.append({'occurrence_id': node.get('occurrence_id'), 'operator': op, 'meaning': meaning,
                                'children_order': [c.get('occurrence_id') for c in children],
                                'backbone_occurrence': children[0].get('occurrence_id') if op == 'graft' and children else None,
                                'atomic_junction': 'NOT_APPLICABLE' if op in ('blend', 'ipn', 'sipn', 'compl') else 'NOT_SPECIFIED_BY_CONNECTIVE',
                                'evidence_ref': ref, 'rule_id': rule})
            rules.add(rule)
        for child in node.get('children') or []:
            walk(child)
    walk(parsed.get('ast') or {})
    kinds = {c['kind'] for c in components}
    if 'source' in kinds:
        rules.add('PI-SOURCE-001')
    if 'unit' in kinds:
        rules.update(('PI-CRU-001', 'PI-PORTS-001'))
    constitution = deepcopy(core.get('constitution_model'))
    supported = bool(constitution and constitution.get('graph_key'))
    hypotheses = []
    if include_models and original and not supported and parsed.get('status') == 'PARSED':
        modelled = kernel.parse({'name': original, 'interpretation_policy': 'idealized_common_chain'})
        projection = modelled.get('semantic_projection') or {}
        if projection.get('constitution_key'):
            hypotheses.append({'kind': 'IDEALIZED_REACTION_TEMPLATE', 'graph_key': projection['constitution_key'],
                               'interpretation_policy': 'idealized_common_chain', 'is_reported_fact': False,
                               'repeat_smiles': (modelled.get('idealized_constitution') or {}).get('repeat_smiles'),
                               'assumptions': (modelled.get('idealized_constitution') or {}).get('assumptions', []),
                               'actual_product_verified': False, 'source': 'existing_local_conventions'})
    result = {'version': VERSION, 'status': parsed.get('status', 'PARTIAL'), 'passport_ref': ref,
            'components': components, 'connections': connections, 'rule_ids': sorted(rules),
            'constitution': constitution, 'structure_naming_ready': supported,
            'source_naming_ready': bool(components) and parsed.get('status') == 'PARSED' and 'source' in kinds,
            'hypotheses': hypotheses, 'composition_sets': deepcopy(core.get('composition_sets', [])),
            'attributes': deepcopy(core.get('attributes', {})), 'conflicts': deepcopy(core.get('conflicts', [])),
            'unresolved_segments': deepcopy(core.get('unresolved_segments', [])),
            'atom_junctions_across_source_components': 'NOT_INFERRED_FROM_NAMES',
            'rules_sources': [{'source_id': 'IUPAC-BG-2012', 'url': BG, 'sections': '2, 3.1–3.3, 4.1'},
                              {'source_id': 'IUPAC-RSSOP-2002', 'url': RSSOP, 'sections': '2–3'}],
            'rule_id_namespace': 'PROJECT_NOT_OFFICIAL_CLAUSE',
            'full_iupac_conformance': False, 'independent_review': 'NOT_RUN',
            'limitations': ['Periodic equivalence is within the existing kernel scope, not a preferred-CRU proof.',
                            'Functional groups and optional reaction templates do not prove an actual synthesis.']}

    from .composite_evidence import annotate
    result['source_hierarchy'] = annotate(parsed, result['components'])
    from .chemical_rule_checks import enrich_support
    from .unit_evidence import enrich_unit_evidence
    return enrich_unit_evidence(enrich_support(result))
