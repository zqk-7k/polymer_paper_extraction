"""Explicit product-expression decisions and selected edits; no reaction prediction."""
from copy import deepcopy
from rdkit import Chem
from .storage import digest

CONTRACT = 'product-structure-expression/1.0'

def prepare_sites(graph):
    raw = graph['canonical_smiles']
    params = Chem.SmilesParserParams(); params.removeHs = False; params.parseName = False
    mol = Chem.MolFromSmiles(raw, params)
    if mol is None: raise ValueError('SOURCE_GRAPH_INVALID')
    if any(a.GetAtomicNum() == 0 for a in mol.GetAtoms()): raise ValueError('FINITE_SOURCE_REQUIRED')
    used = {a.GetAtomMapNum() for a in mol.GetAtoms() if a.GetAtomMapNum()}
    if len(used) != sum(bool(a.GetAtomMapNum()) for a in mol.GetAtoms()): raise ValueError('SOURCE_MAPS_NOT_UNIQUE')
    n = 1
    for atom in mol.GetAtoms():
        if not atom.GetAtomMapNum():
            while n in used: n += 1
            atom.SetAtomMapNum(n); used.add(n)
    sites = {}
    for ring in mol.GetRingInfo().AtomRings():
        atoms = [mol.GetAtomWithIdx(i) for i in ring]
        if len(ring) != 5 or sorted(a.GetAtomicNum() for a in atoms) != [6,6,6,6,16] or not all(a.GetIsAromatic() for a in atoms): continue
        sulfur = next(a for a in atoms if a.GetAtomicNum() == 16)
        for atom in sulfur.GetNeighbors():
            if atom.GetIdx() in ring and atom.GetAtomicNum() == 6 and atom.GetTotalNumHs() > 0:
                ident = 'alpha-H:'+str(atom.GetAtomMapNum())
                sites[ident] = {'site_id':ident,'anchor_map':atom.GetAtomMapNum(),'ring_maps':sorted(a.GetAtomMapNum() for a in atoms),'hydrogen_delta':-1}
    return {'contract':CONTRACT,'source_graph_id':graph['id'],'source_graph_sha256':digest(graph),
            'mapped_smiles':Chem.MolToSmiles(mol,isomericSmiles=True),'sites':list(sites.values()),
            'all_atom_maps':sorted(used),'source_fact':False,
            'limitations':['Possible thiophene alpha C–H sites only; no site selected automatically.',
                           'Stereo/explicit hydrogen edit limitations remain those of the existing mapped-residue Kernel.']}

def derive_selected(kernel, graph, spec):
    prepared = prepare_sites(graph)
    if spec.get('expected_source_sha256') != prepared['source_graph_sha256']: raise ValueError('STALE_SOURCE_GRAPH')
    chosen = spec.get('selected_site_ids')
    if not isinstance(chosen,list) or not chosen or len(chosen) != len(set(chosen)): raise ValueError('EXPLICIT_UNIQUE_SITES_REQUIRED')
    by_id = {x['site_id']:x for x in prepared['sites']}
    if any(x not in by_id for x in chosen): raise ValueError('SELECTED_SITE_NOT_AVAILABLE')
    if spec.get('evidence_basis') not in ('source_supported','most_likely_hypothesis') or not spec.get('reason') or not spec.get('source_refs'): raise ValueError('SOURCED_EDIT_REASON_REQUIRED')
    if spec['evidence_basis'] == 'most_likely_hypothesis' and not spec.get('assumptions'): raise ValueError('EDIT_HYPOTHESIS_REQUIRED')
    ports = [{'anchor_map':by_id[x]['anchor_map'],'port_map':max(prepared['all_atom_maps'])+i+1,
              'hydrogen_delta':-1,'src':spec['source_refs']} for i,x in enumerate(chosen)]
    edited = kernel.dispatch('mapped_residue',{'smiles':prepared['mapped_smiles'],
        'retain_maps':prepared['all_atom_maps'],'ports':ports,'src':spec['source_refs'],
        'uncertainties':spec.get('unknowns',[])})
    return {'contract':CONTRACT,'preparation':prepared,'edit':edited,
            'evidence_basis':spec['evidence_basis'],'reason':spec['reason'],
            'assumptions':deepcopy(spec.get('assumptions',[])),'source_fact':False}

def expression_errors(material, candidate):
    d = material.get('structure_expression') or {}
    if d.get('contract') != CONTRACT: return ['PRODUCT_EXPRESSION_DECISION_REQUIRED']
    if not d.get('reason') or not d.get('source_refs') or not set(d['source_refs']).issubset(set(material.get('source_refs',[]))): return ['PRODUCT_EXPRESSION_SOURCE_REASON_REQUIRED']
    kind = d.get('kind'); gids = d.get('graph_ids',[])
    if not isinstance(gids,list) or not all(isinstance(x,str) for x in gids):return ['PRODUCT_EXPRESSION_GRAPH_BINDING_REQUIRED']
    if kind not in ('ideal_repeat','local_connectivity','source_only','assembly'): return ['PRODUCT_EXPRESSION_KIND_REQUIRED']
    if d.get('evidence_basis') not in ('source_supported','most_likely_hypothesis','insufficient_evidence'): return ['PRODUCT_EXPRESSION_EVIDENCE_BASIS_REQUIRED']
    if d['evidence_basis'] == 'most_likely_hypothesis' and not d.get('assumptions'): return ['PRODUCT_EXPRESSION_HYPOTHESIS_REQUIRED']
    gs = [candidate['graphs'].get(g) for g in gids]
    if any(g not in material.get('graph_ids',[]) for g in gids) or any(g is None for g in gs): return ['PRODUCT_EXPRESSION_GRAPH_BINDING_REQUIRED']
    if kind == 'ideal_repeat':
        constitution = material.get('constitution') or {}
        if len(gs)!=1 or gs[0]['scope']!='repeat_unit' or len(gs[0].get('ports',[]))!=2 or constitution.get('graph_id')!=gids[0] or constitution.get('coverage')!='ideal_repeat': return ['IDEAL_REPEAT_DECLARATION_REQUIRED']
        name = material.get('most_likely_name') or {}
        if name.get('basis') == 'material_expression': return ['IDEAL_REPEAT_NAME_CANNOT_BE_MATERIAL_DESCRIPTION']
    elif kind == 'local_connectivity':
        if not gs or any(g['scope'] not in ('component','residue','local_network','constitutional_unit') or not g.get('ports') for g in gs) or material.get('constitution'): return ['LOCAL_PRODUCT_IS_NOT_WHOLE_REPEAT']
        name = material.get('most_likely_name') or {}
        if name.get('basis') == 'structure_based' and name.get('scope') in ('ideal_repeat','structure_polymer','structure_polymer_candidate'):
            return ['LOCAL_PRODUCT_NAME_EXCEEDS_GRAPH_SCOPE']
    elif kind == 'source_only':
        if not d.get('unknowns') or not gs or any(g['scope']!='finite_molecule' for g in gs): return ['SOURCE_ONLY_LIMITS_REQUIRED']
        name = material.get('most_likely_name') or {}
        if name.get('basis') == 'structure_based': return ['SOURCE_ONLY_NAME_EXCEEDS_GRAPH_SCOPE']
    elif material.get('constitution'): return ['ASSEMBLY_IS_NOT_COVALENT_REPEAT']
    return []
