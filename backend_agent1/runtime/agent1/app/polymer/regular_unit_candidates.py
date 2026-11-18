"""Opt-in graph-derived names for bounded neutral regular constitutions.

Graph features select a chemical parent, never a paper/catalog/expected answer.
All candidates must roundtrip through the same Kernel and actual unit parser.
"""
from rdkit import Chem
from .periodic import canonicalize_unit

CONTRACT = 'iupac-regular-unit-graph-candidate/1.0'

def structure_name(kernel, smiles):
    result = {'contract':CONTRACT,'status':'NO_NAME','primary':None,'preferred_iupac_name':None,
              'full_iupac_conformance':False,'independent_review':'NOT_REVIEWED',
              'source_url':'https://iupac.qmul.ac.uk/rssop/','rule_trace':[]}
    raw=Chem.MolFromSmiles(smiles)
    if raw is None: return {**result,'reason_code':'INVALID_GRAPH'}
    if any(a.GetIsotope() or a.GetFormalCharge() or a.GetNumRadicalElectrons() or a.GetChiralTag()!=Chem.ChiralType.CHI_UNSPECIFIED for a in raw.GetAtoms()) or any(b.GetStereo()!=Chem.BondStereo.STEREONONE for b in raw.GetBonds()):
        return {**result,'reason_code':'SPECIFIED_ISOTOPE_CHARGE_STEREO_OUTSIDE_PROFILE','raw_smiles':smiles}
    p = canonicalize_unit(smiles)
    if p.get('status')!='PARSED': return {**result,'reason_code':'REGULAR_TWO_PORT_GRAPH_REQUIRED'}
    m = Chem.MolFromSmiles(p['canonical_repeat_smiles'])
    if any(a.GetIsotope() or a.GetFormalCharge() or a.GetNumRadicalElectrons() or a.GetChiralTag()!=Chem.ChiralType.CHI_UNSPECIFIED for a in m.GetAtoms()) or any(b.GetStereo()!=Chem.BondStereo.STEREONONE for b in m.GetBonds()):
        return {**result,'reason_code':'SPECIFIED_ISOTOPE_CHARGE_STEREO_OUTSIDE_PROFILE','raw_smiles':smiles}
    ports = [a for a in m.GetAtoms() if not a.GetAtomicNum()]
    if len(ports)!=2 or any(a.GetDegree()!=1 for a in ports): return {**result,'reason_code':'REGULAR_TWO_PORT_GRAPH_REQUIRED'}
    anchors = {a.GetNeighbors()[0].GetIdx() for a in ports}
    atoms = [a for a in m.GetAtoms() if a.GetAtomicNum()]; parent=None; text=None
    rings = m.GetRingInfo().AtomRings()
    # A complete five-member heteroaromatic ring with both alpha termini.
    for ring in rings:
        ring_atoms=[m.GetAtomWithIdx(i) for i in ring]
        hetero=[a for a in ring_atoms if a.GetAtomicNum()!=6]
        if len(ring)!=5 or len(hetero)!=1 or hetero[0].GetAtomicNum() not in (7,8,16) or not all(a.GetIsAromatic() for a in ring_atoms): continue
        alpha={a.GetIdx() for a in hetero[0].GetNeighbors() if a.GetIdx() in ring}
        if anchors!=alpha: continue
        element=hetero[0].GetAtomicNum()
        if len(atoms)==5:
            parent={7:'1H-pyrrole',8:'furan',16:'thiophene'}[element]+'-2,5-diyl'
        elif element==16 and len(atoms)==9:
            beta=set(ring)-anchors-{hetero[0].GetIdx()}
            oxy=[next((n for n in m.GetAtomWithIdx(i).GetNeighbors() if n.GetIdx() not in ring and n.GetAtomicNum()==8),None) for i in beta]
            if len(oxy)==2 and all(oxy):
                carbons=[next((n for n in a.GetNeighbors() if n.GetIdx() not in ring and n.GetAtomicNum()==6),None) for a in oxy]
                if all(carbons) and carbons[0].GetIdx()!=carbons[1].GetIdx() and m.GetBondBetweenAtoms(carbons[0].GetIdx(),carbons[1].GetIdx()) and all(a.GetTotalNumHs()==2 for a in carbons):
                    parent='2,3-dihydrothieno[3,4-b][1,4]dioxine-5,7-diyl'
        if parent:
            text='poly('+parent+')';result['rule_trace']=[{'rule':'RSSOP heterocyclic complete subunit and lowest port locants','parent':parent,'alpha_termini':sorted(anchors),'all_real_atoms_accounted':True}];break
    # Explicit IUPAC Brief Guide §5 oxy–dimethylsilanediyl constitution.
    if not parent and sorted(a.GetAtomicNum() for a in atoms)==[6,6,8,14] and not rings:
        si=next(a for a in atoms if a.GetAtomicNum()==14);o=next(a for a in atoms if a.GetAtomicNum()==8)
        cs=[a for a in atoms if a.GetAtomicNum()==6]
        if anchors=={si.GetIdx(),o.GetIdx()} and m.GetBondBetweenAtoms(si.GetIdx(),o.GetIdx()) and all(a.GetDegree()==1 and a.GetTotalNumHs()==3 and a.GetNeighbors()[0].GetIdx()==si.GetIdx() for a in cs) and all(b.GetBondType()==Chem.BondType.SINGLE for b in m.GetBonds()):
            parent='oxy(dimethylsilanediyl)';text='poly[oxy(dimethylsilanediyl)]';result['rule_trace']=[{'rule':'IUPAC Brief Guide §5; oxy precedes dimethylsilanediyl','all_real_atoms_accounted':True}]
    if not parent: return {**result,'reason_code':'COMPLETE_CONSTITUTION_OUTSIDE_BOUNDED_PROFILE'}
    parsed=kernel.parser._resolve_unit(parent)
    if parsed.get('status')!='PARSED' and parent.endswith('-diyl'):
        parsed=kernel.provider.resolve_divalent_unit(parent)
    result['unit_parser']=parsed
    if parsed.get('status')!='PARSED': return {**result,'reason_code':'NAMED_UNIT_PARSER_UNSUPPORTED'}
    q=canonicalize_unit(parsed['unit_smiles']);match=q.get('status')=='PARSED' and q['periodic_graph_key']==p['periodic_graph_key']
    result['roundtrip']={'status':'GRAPH_MATCH' if match else 'MISMATCH','target_key':p.get('periodic_graph_key'),'named_key':q.get('periodic_graph_key')}
    if not match: return {**result,'reason_code':'NAMED_COMPLETE_GRAPH_MISMATCH'}
    return {**result,'status':'CANDIDATE','primary':{'text':text,'kind':'structure_based','qualification':'GRAPH_VERIFIED_IDEAL_CONSTITUTION_NOT_CERTIFIED_PREFERRED'},
            'conformance_scope':'bounded complete parent/locant rules and whole periodic graph roundtrip; no sample/chain-end/PIN certification'}
