"""Chemical display projections; never amend source graphs or passport identities."""
from collections import Counter
from copy import deepcopy
from functools import lru_cache
import base64
import math
from rdkit import Chem, rdBase
from rdkit.Chem import Descriptors, Lipinski, Crippen, rdMolDescriptors, rdDepictor
from rdkit.Chem.Draw import rdMolDraw2D

VERSION = 'component-profile/1.0'
METHOD = 'RDKit/' + rdBase.rdkitVersion
GROUPS = {'碳碳双键': '[CX3]=[CX3]', '芳香六元环': 'a1aaaaa1', '腈基': '[CX2]#[NX1]', '异氰酸酯基': '[NX2]=[CX2]=[OX1]',
          '羟基': '[OX2H]', '羧酸': '[CX3](=O)[OX2H]', '酯基': '[CX3](=O)[OX2][#6]',
          '酰胺': '[CX3](=O)[NX3]', '胺': '[NX3;H1,H2;!$(N[C,S,P]=O)]',
          '醚键': '[#6][OX2][#6]', '环氧': '[OX2]1[CX4][CX4]1',
          '硅氧键': '[Si]-[O]', '砜基': '[SX4](=O)(=O)', '卤素': '[F,Cl,Br,I]'}
PATTERNS = {n: Chem.MolFromSmarts(s) for n, s in GROUPS.items()}

def observation(key, label, value, unit='', scope='finite_source', method=METHOD):
    return {'key': key, 'label': label, 'value': value, 'unit': unit,
            'scope': scope, 'method': method, 'evidence_kind': 'COMPUTED_FROM_ENCODED_GRAPH'}

def graph_key(smiles):
    mol = Chem.MolFromSmiles(smiles) if isinstance(smiles, str) and len(smiles) <= 12000 else None
    if mol is None: return None
    copy = Chem.Mol(mol)
    for atom in copy.GetAtoms(): atom.SetAtomMapNum(0)
    return Chem.MolToSmiles(copy, isomericSmiles=True)

@lru_cache(maxsize=1024)
def _graph_details(smiles, role, image):
    out = {'status': 'STRUCTURE_MISSING', 'properties': [], 'functional_groups': [],
           'ports': [], 'smiles': smiles, 'image': None, 'method': METHOD}
    if not smiles: return out
    mol = Chem.MolFromSmiles(smiles) if isinstance(smiles, str) and len(smiles) <= 12000 else None
    if mol is None or mol.GetNumAtoms() > 1200:
        return {**out, 'status': 'STRUCTURE_INVALID_OR_TOO_LARGE'}
    ports = [a for a in mol.GetAtoms() if a.GetAtomicNum() == 0]
    is_unit = bool(ports) or role in ('unit', 'fragments_cu', 'repeat_unit', 'end_groups', 'fragment')
    scope = 'explicit_unit_inventory_not_sample' if is_unit else ('finite_source' if role in ('source', 'source_molecule', 'source_molecules') else 'unassigned_finite_graph')
    expected = {'source': 0, 'source_molecules': 0, 'fragments_cu': 2, 'unit': 2, 'end_groups': 1}.get(role)
    out['status'] = 'GRAPH_ROLE_CONFLICT' if expected is not None and expected != len(ports) else 'GRAPH_READABLE'
    if ports and (len(Chem.GetMolFrags(mol)) != 1 or any(a.GetDegree() != 1 for a in ports)):
        out['status'] = 'GRAPH_ROLE_CONFLICT'
    out['port_count'] = len(ports); out['scope'] = scope
    for atom in ports:
        out['ports'].append({'port': atom.GetAtomMapNum() or None, 'atom_index': atom.GetIdx(),
            'neighbours': [{'atom_index': n.GetIdx(), 'element': n.GetSymbol(),
                'bond_order': mol.GetBondBetweenAtoms(atom.GetIdx(), n.GetIdx()).GetBondTypeAsDouble()}
                for n in atom.GetNeighbors()]})
    if is_unit:
        atoms = Counter()
        for atom in mol.GetAtoms():
            if atom.GetAtomicNum() == 0: continue
            label = ('[' + str(atom.GetIsotope()) + atom.GetSymbol() + ']') if atom.GetIsotope() else atom.GetSymbol()
            atoms[label] += 1; atoms['H'] += atom.GetTotalNumHs()
        formula = ''.join(k + (str(atoms[k]) if atoms[k] != 1 else '') for k in
            sorted(atoms, key=lambda x: (0 if x == 'C' else 1 if x == 'H' else 2, x)) if atoms[k])
    else:
        formula = rdMolDescriptors.CalcMolFormula(mol)
    def add(key, label, value, unit=''):
        if isinstance(value, float): value = round(value, 5) if math.isfinite(value) else None
        out['properties'].append(observation(key, label, value, unit, scope))
    add('formula', '单元原子组成（不含端口、不补氢）' if is_unit else '分子式', formula)
    add('molar_mass', '单元质量贡献（非聚合物 Mn/Mw）' if is_unit else '摩尔质量', Descriptors.MolWt(mol), 'g/mol')
    add('formal_charge', '图中总形式电荷', Chem.GetFormalCharge(mol))
    add('heavy_atoms', '非氢实原子数', sum(a.GetAtomicNum() > 1 for a in mol.GetAtoms()))
    add('rings', '图中环数', rdMolDescriptors.CalcNumRings(mol))
    add('port_count', '连接端口数', len(ports))
    add('isotope_atoms', '显式同位素原子数', sum(bool(a.GetIsotope()) for a in mol.GetAtoms()))
    add('specified_stereo_atoms', '已编码四面体立体原子数', sum(a.GetChiralTag() != Chem.ChiralType.CHI_UNSPECIFIED for a in mol.GetAtoms()))
    add('specified_stereo_bonds', '已编码双键立体键数', sum(b.GetStereo() != Chem.BondStereo.STEREONONE for b in mol.GetBonds()))
    add('radical_electrons', '图中自由基电子数', sum(a.GetNumRadicalElectrons() for a in mol.GetAtoms()))
    if not is_unit:
        add('exact_mass', '单同位素精确质量（计算）', Descriptors.ExactMolWt(mol), 'Da')
        add('logp', 'MolLogP（计算，非实测）', Crippen.MolLogP(mol))
        add('tpsa', '拓扑极性表面积', rdMolDescriptors.CalcTPSA(mol), 'Å²')
        add('hbd', '氢键供体数', Lipinski.NumHDonors(mol))
        add('hba', '氢键受体数', Lipinski.NumHAcceptors(mol))
        add('rotatable_bonds', '可旋转键数', Lipinski.NumRotatableBonds(mol))
        try:
            out['inchikey'] = Chem.MolToInchiKey(mol)
        except Exception:
            out['inchikey'] = None
    for label, pattern in PATTERNS.items():
        matches = mol.GetSubstructMatches(pattern)
        if matches:
            out['functional_groups'].append({'label': label, 'count': len(matches), 'atom_matches': [list(m) for m in matches[:12]],
                                             'method': 'SMARTS motif match; not reaction evidence'})
    if image and mol.GetNumAtoms() <= 400:
        try:
            drawing = Chem.Mol(mol); rdDepictor.Compute2DCoords(drawing)
            drawer = rdMolDraw2D.MolDraw2DCairo(500, 290)
            for atom in drawing.GetAtoms():
                if atom.GetAtomicNum() == 0:
                    drawer.drawOptions().atomLabels[atom.GetIdx()] = 'R' + str(atom.GetAtomMapNum() or atom.GetIdx())
            rdMolDraw2D.PrepareAndDrawMolecule(drawer, drawing)
            drawer.FinishDrawing()
            out['image'] = 'data:image/png;base64,' + base64.b64encode(drawer.GetDrawingText()).decode()
            out['image_caption'] = '二维编码结构；R 标记为开放连接端口，不是实际端基。' if is_unit else '来源分子二维编码结构，非聚合后的链结构。'
        except Exception as exc:
            out['image_error'] = type(exc).__name__
    out['limitations'] = ['局部图参数不能当作聚合物样品的 Mn、Mw、Tg、熔点或密度。',
                          '官能团命中不证明可聚合性或实际反应；无编码立体不代表无立体中心。']
    if is_unit: out['limitations'].append('不为开放 CU 计算 LogP/HBD/HBA；单元计量不证明最小或优选 CRU。')
    return out

def describe_component(component, image=True):
    graph = component.get('graph') or {}
    smiles = graph.get('smiles') or component.get('canonical_smiles') or component.get('smiles')
    role = component.get('kind') or component.get('role') or 'unknown'
    result = deepcopy(_graph_details(smiles, role, image))
    result.update(version=VERSION, component_key=component.get('component_key'), role=role,
                  label=component.get('label') or next(iter(component.get('labels') or []), None) or '未命名组分',
                  occurrence_id=component.get('occurrence_id'), aliases=component.get('labels', []),
                  subunit_names=component.get('subunit_names', []), graph_key=component.get('graph_key'))
    result['hierarchy_context'] = deepcopy(component.get('hierarchy_context') or {})
    if result['hierarchy_context'].get('polymeric_source'):
        result['polymeric_member_name'] = result['hierarchy_context']['polymeric_source_name']
        result['image_caption'] = '该聚合物来源所对应的命名源分子，不是预聚物整链；链长与实际端基未知。'
    result['sources'] = [{'type': 'LOCAL_GRAPH_COMPUTATION', 'label': METHOD,
        'url': 'https://www.rdkit.org/docs/GettingStartedInPython.html', 'scope': '当前编码图的计算性质，非实验测定'}]
    if component.get('source'):
        result['sources'].append({'type': 'IDENTITY_GRAPH_SOURCE', 'label': '身份解析来源', 'details': component['source']})
    if component.get('evidence_ref'):
        result['sources'].append({'type': 'PASSPORT', 'label': '本次身份证证据', 'reference': component['evidence_ref']})
    if component.get('component_key'):
        refs = component.get('evidence_refs') or []
        result['sources'].append({'type': 'COMPONENT_LIBRARY', 'label': '内部组件库',
            'reference': component['component_key'], 'evidence_refs': refs[:12], 'evidence_count': len(refs),
            'alias_evidence': (component.get('alias_evidence') or [])[:3],
            'source_ids': (component.get('source_ids') or [])[:12],
            'review_status': component.get('review_status', 'PENDING')})
    parents = component.get('parent_record_ids') or []
    result['parent_record_ids'] = parents[:20]
    result['parent_count'] = component.get('parent_count', len(parents))
    result['aliases_are_unreviewed_library_labels'] = True
    result['external'] = {'status': 'NOT_QUERIED', 'properties': [], 'reason': '尚未查询或无已验证缓存'}
    return result


def browse_summary(row):
    """Small local-only table projection; full image/provenance are loaded on demand."""
    profile = describe_component(row, image=False)
    props = {p['key']: p for p in profile.get('properties', [])}
    return {'status': profile['status'], 'formula': props.get('formula', {}).get('value'),
            'mass': props.get('molar_mass', {}).get('value'),
            'mass_label': props.get('molar_mass', {}).get('label'),
            'port_count': profile.get('port_count'),
            'functional_groups': [g['label'] for g in profile.get('functional_groups', [])],
            'method': METHOD, 'scope': profile.get('scope'), 'network_requests': 0}
