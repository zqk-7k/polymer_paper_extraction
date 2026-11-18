"""Opt-in named acyclic diyl composition, with actual monovalent OPSIN results.

Fully consume locanted substituents; never reinterpret OPSIN's finite alkene as
a polymer unit. Specified stereo outside the existing joiner's scope stays a gap.
"""
import re
from rdkit import Chem
from .name_rules import STEM_N
from .supplied_fragment_join import assemble

CONTRACT='iupac-substituted-acyclic-diyl/1.0'
RULE='https://iupac.qmul.ac.uk/BlueBook/P2.html#P-29'
PAIRS={'(':')','[':']','{':'}'}


def dissect(name):
    if not isinstance(name,str) or not 0<len(name)<=500:return None
    stems='|'.join(re.escape(s) for s in sorted(STEM_N,key=len,reverse=True) if STEM_N[s]<=12)
    m=re.search(r'('+stems+r')ane-(\d+),(\d+)-diyl$',name)
    if m and m[1] in STEM_N:
        n=STEM_N[m[1]];ports=(int(m[2]),int(m[3]));prefix=name[:m.start()]
    elif name.endswith('methylene'):
        n=1;ports=(1,1);prefix=name[:-len('methylene')]
    elif name.endswith('ethylene'):
        n=2;ports=(1,2);prefix=name[:-len('ethylene')]
    else:return None
    if not 1<=n<=12 or any(not 1<=x<=n for x in ports):return None
    prefix=prefix.rstrip('-');items=[];pos=0
    while pos<len(prefix):
        loc=re.match(r'(\d+)-',prefix[pos:])
        if not loc:return None
        site=int(loc[1]);pos+=loc.end()
        if not 1<=site<=n or pos>=len(prefix):return None
        if prefix[pos] in PAIRS:
            start=pos;stack=[prefix[pos]];pos+=1
            while pos<len(prefix) and stack:
                c=prefix[pos]
                if c in PAIRS:stack.append(c)
                elif c in PAIRS.values():
                    if PAIRS[stack.pop()]!=c:return None
                pos+=1
            if stack:return None
            group=prefix[start+1:pos-1]
        else:
            word=re.match(r'[a-z]+',prefix[pos:])
            if not word:return None
            group=word[0];pos+=word.end()
        if not group:return None
        items.append({'locant':site,'name':group})
        if pos<len(prefix):
            if prefix[pos]!='-':return None
            pos+=1
            if pos==len(prefix):return None
    return (n,ports,items) if 1<=len(items)<=10 else None


def resolve(kernel,name):
    result={'contract':CONTRACT,'status':'UNSUPPORTED','reason_code':'ACYCLIC_SUBSTITUTED_DIYL_OUTSIDE_PROFILE',
            'source_url':RULE,'name':name,'substituent_checks':[],
            'preferred_iupac_name':None,'full_iupac_conformance':False,'independent_review':'NOT_REVIEWED'}
    parsed=dissect(name)
    if parsed is None:return result
    n,sites,groups=parsed;parent=Chem.RWMol(Chem.MolFromSmiles('C'*n));fragments=[];links=[]
    def port(site,label):
        a=Chem.Atom(0);a.SetAtomMapNum(label);parent.AddBond(site-1,parent.AddAtom(a),Chem.BondType.SINGLE)
    for label,site in enumerate(sites,1):port(site,label)
    params=Chem.SmilesParserParams();params.removeHs=False;params.parseName=False
    for i,group in enumerate(groups):
        checked=kernel.provider.resolve_substituent(group['name'])
        result['substituent_checks'].append({**group,'parser_result':checked})
        if checked.get('status')!='PARSED':return {**result,'reason_code':'SUBSTITUENT_RADICAL_NOT_PARSED'}
        mol=Chem.MolFromSmiles(checked.get('isomeric_smiles',''),params)
        if mol is None or len(Chem.GetMolFrags(mol))!=1:return {**result,'reason_code':'CONNECTED_SUBSTITUENT_REQUIRED'}
        if (any(a.GetChiralTag()!=Chem.ChiralType.CHI_UNSPECIFIED for a in mol.GetAtoms())
                or any(b.GetStereo()!=Chem.BondStereo.STEREONONE for b in mol.GetBonds())):
            return {**result,'reason_code':'SUBSTITUENT_STEREO_OUTSIDE_SCOPED_JOINER','specified_stereo_preserved_as_gap':True}
        radicals=[a.GetIdx() for a in mol.GetAtoms() if a.GetNumRadicalElectrons()==1]
        if len(radicals)!=1 or sum(a.GetNumRadicalElectrons() for a in mol.GetAtoms())!=1 or any(a.GetAtomicNum()==0 for a in mol.GetAtoms()):
            return {**result,'reason_code':'SINGLE_MONOVALENT_SUBSTITUENT_REQUIRED'}
        rw=Chem.RWMol(mol);rw.GetAtomWithIdx(radicals[0]).SetNumRadicalElectrons(0)
        used={a.GetAtomMapNum() for a in mol.GetAtoms()};label=max(used or {0})+1
        a=Chem.Atom(0);a.SetAtomMapNum(label);rw.AddBond(radicals[0],rw.AddAtom(a),Chem.BondType.SINGLE)
        try:
            residue=rw.GetMol();Chem.SanitizeMol(residue)
        except (ValueError,RuntimeError):return {**result,'reason_code':'SUBSTITUENT_VALENCE_INVALID'}
        branch='s'+str(i);src=['naming-rule:'+CONTRACT]
        fragments.append({'id':branch,'smiles':Chem.MolToSmiles(residue,isomericSmiles=True),'src':src})
        parent_label=100+i;port(group['locant'],parent_label)
        links.append({'left':{'fragment':'parent','port':parent_label},'right':{'fragment':branch,'port':label},'bond':'single','src':src})
    try:
        scaffold=parent.GetMol();Chem.SanitizeMol(scaffold)
    except (ValueError,RuntimeError):return {**result,'reason_code':'SUBSTITUTED_PARENT_VALENCE_INVALID'}
    joined=assemble([{'id':'parent','smiles':Chem.MolToSmiles(scaffold,isomericSmiles=True),'src':['naming-rule:'+CONTRACT]},*fragments],links)
    result['assembly']=joined
    if joined.get('status')!='ASSEMBLED_CANDIDATE' or len(joined.get('remaining_ports',[]))!=2:
        return {**result,'reason_code':'SCOPED_SUBSTITUENT_ASSEMBLY_UNSUPPORTED'}
    return {**result,'status':'PARSED','reason_code':None,'unit_smiles':joined['product_smiles'],
            'scope':'named_substituents_and_locanted_neutral_acyclic_parent; charge/isotope retained; stereo outside joiner scope',
            'parent_chain_length':n,'parent_free_valence_locants':list(sites),
            'support_type':'OPT_IN_NAMED_SUBUNIT_GRAPH_CHECK_NOT_PREFERRED_NAME_SELECTION'}
