"""Opt-in graph-derived candidates for a bounded triazine/iminopolyalkylene class.

No material IDs, input names, formula keys, catalog or paper answers. Generate
from complete oriented subunits, then compare the entire periodic graph. The
preferred-CRU/locant proof is still outstanding, so this emits CANDIDATE only.
"""
from rdkit import Chem
from .periodic import canonicalize_unit,reverse_unit,assemble,port_mol
from .graph_naming_v09 import label_divalent,_STEMS
from .expansion_v08 import divalent

CONTRACT='iupac-triazine-graph-candidate/1.0'

def oriented_key(text):
    m,_=port_mol(text)
    return Chem.MolToSmiles(m,canonical=True,isomericSmiles=True)

def ring_label(block):
    # Independent atom/bond guard prevents stereo, isotope, charge or radicals
    # being lost when the oriented kernel key rejects/normalizes those features.
    m=Chem.MolFromSmiles(block)
    if any(a.GetIsotope() or a.GetFormalCharge() or a.GetNumRadicalElectrons() or
           a.GetChiralTag()!=Chem.ChiralType.CHI_UNSPECIFIED for a in m.GetAtoms()):return None
    for prefix in ('','6-methyl-','6-phenyl-'):
        text=prefix+'1,3,5-triazine-2,4-diyl'
        unit=divalent(text)
        if unit and oriented_key(unit)==oriented_key(block):return text
    return None

def structure_name(kernel,smiles):
    out={'contract':CONTRACT,'status':'NO_NAME','primary':None,'preferred_iupac_name':None,
         'full_iupac_conformance':False,'independent_review':'NOT_REVIEWED',
         'preferred_cru_selection':'NOT_COMPLETED',
         'source_url':'https://iupac.qmul.ac.uk/rssop/ss05.html'}
    p=canonicalize_unit(smiles)
    if p.get('status')!='PARSED':return {**out,'reason_code':'REPEAT_GRAPH_OUTSIDE_KERNEL_SCOPE'}
    blocks=p['primitive_blocks'];names={};traces=[]
    for seq in (blocks,[reverse_unit(x) for x in reversed(blocks)]):
        for i,block in enumerate(seq):
            label=ring_label(block)
            if not label:continue
            ordered=seq[i:]+seq[:i]
            if len(ordered)<5 or label_divalent(ordered[1])!='phenylimino' or label_divalent(ordered[-1])!='phenylimino':continue
            middle=assemble(ordered[2:-1])
            # This profile permits only an unbranched saturated 2..20 carbon bridge.
            mol,_=port_mol(middle)
            count=sum(a.GetAtomicNum()==6 for a in mol.GetAtoms())
            if count not in _STEMS or not 2<=count<=20 or not all(a.GetAtomicNum() in (0,6) and a.GetDegree()<=2 for a in mol.GetAtoms()) or any(b.GetBondType()!=Chem.BondType.SINGLE for b in mol.GetBonds()):continue
            chain=_STEMS[count]+'ane-1,'+str(count)+'-diyl'
            text='poly[('+label+')(phenylimino)('+chain+')(phenylimino)]'
            parsed=kernel.parse({'name':text,'interpretation_policy':'evidence_only'})
            match=parsed.get('status')=='PARSED' and parsed.get('semantic_projection',{}).get('constitution_key')==p['periodic_graph_key']
            traces.append({'subunits':[label,'phenylimino',chain,'phenylimino'],'full_periodic_graph_match':match})
            if match:names[text]=True
    if len(names)!=1:return {**out,'reason_code':'NO_UNIQUE_COMPLETE_SUBUNIT_CANDIDATE','rule_trace':traces}
    text=next(iter(names))
    return {**out,'status':'CANDIDATE','primary':{'text':text,'kind':'structure_based',
            'origin':'GRAPH_SUBUNIT_DECOMPOSITION','qualification':'CONSISTENCY_CANDIDATE',
            'scope':'complete_supplied_achiral_constitution_only'},'rule_trace':traces,
            'remaining':['Preferred CRU free-valence/substituent locant selection requires a separate rule proof and independent review.',
                         'Unspecified stereochemistry, end groups, chain length and defects remain unknown.']}
