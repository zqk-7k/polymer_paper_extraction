"""Additional fully consumed molecular-name families; all bindings are candidates.

No catalog IDs/formulas or test answers are read. Asymmetric azoxy orientation,
missing locants, stereochemical specifications and unexpected suffixes are not
silently completed. Existing successful name rules keep precedence.
"""
from __future__ import annotations
import re
from functools import lru_cache
from rdkit import Chem,rdBase
from .name_rules import STEM_N
from .advanced_names import rooted,prefixes,decorate,connect,smi,diyl,_unwrap
from .queue_rules import _parent

VERSION='NR-FUNCTIONAL-FAMILIES/0.7'


def _cap_two(d,group):
    m=Chem.MolFromSmiles(d)
    ps=[a.GetIdx() for a in m.GetAtoms() if a.GetAtomicNum()==0]
    if len(ps)!=2:return None
    # Replace each explicitly open valence by a monovalent named group.
    for p in sorted(ps,reverse=True):
        neighbor=m.GetAtomWithIdx(p).GetNeighbors()[0].GetIdx()
        m=connect(m,neighbor,group)
        rw=Chem.RWMol(m);rw.RemoveAtom(p);m=rw.GetMol()
    return smi(m)


def _n_substituents(prefix):
    if prefix.startswith('N,N-di'):
        x=rooted(_unwrap(prefix[len('N,N-di'):]))
        return [x,x] if x else None
    if prefix.startswith('N,N-bis'):
        x=rooted(_unwrap(prefix[len('N,N-bis'):]))
        return [x,x] if x else None
    if prefix.startswith('N-'):
        tail=prefix[2:]
        # Split a second N only outside brackets.
        depth=0
        for i,ch in enumerate(tail):
            if ch in '([{':depth+=1
            elif ch in ')]}':depth-=1
            if depth==0 and tail.startswith('-N-',i):
                a,b=rooted(_unwrap(tail[:i])),rooted(_unwrap(tail[i+3:]))
                return [a,b] if a and b else None
        x=rooted(_unwrap(tail))
        return [x] if x else None
    return None


def _ester_roots(name):
    m=re.fullmatch(r'bis(\(.+\)|\[.+\]|\{.+\}) (.+)',name)
    if m:
        r=rooted(_unwrap(m[1]));return (r,m[2]) if r else None
    m=re.fullmatch(r'di([a-z]+) (.+)',name)
    if m:
        r=rooted(m[1]);return (r,m[2]) if r else None
    return None


@lru_cache(maxsize=30000)
def resolve_source_v07(name):
    if not isinstance(name,str) or len(name)>1200:return None
    with rdBase.BlockLogs():
        try:
            for tail,base in [('methacrylamide','C=C(C)C(=O)N'),('acrylamide','C=CC(=O)N')]:
                if name.endswith(tail):
                    subs=_n_substituents(name[:-len(tail)])
                    if subs:
                        m=Chem.MolFromSmiles(base);idx=next(a.GetIdx() for a in m.GetAtoms() if a.GetAtomicNum()==7)
                        for sub in subs:m=connect(m,idx,sub)
                        return smi(m),VERSION+'-N-SUBSTITUTED-AMIDE'
            # A fully locanted divalent alcohol skeleton with two acetates,
            # carbonates or cyanoacetates. Ports explicitly mark O attachments.
            for suffix,group in [(' diacetate','OC(=O)C'),(' bis(cyanoacetate)','OC(=O)CC#N'),
                                  (' bis(phenyl carbonate)','OC(=O)Oc1ccccc1')]:
                if name.endswith(suffix):
                    core=name[:-len(suffix)]
                    if core=='p-phenylene':core='1,4-phenylene'
                    d=diyl(core)
                    if d:
                        result=_cap_two(d,group)
                        if result:return result,VERSION+'-DIOL-DIESTER'
            er=_ester_roots(name)
            if er:
                alcohol,acid=er
                # The inserted O belongs to the ester; alcohol's root is C (or
                # explicit aryl C), never an unspecified diol/macromolecule.
                ester=connect(Chem.MolFromSmiles('*C(=O)O'),3,alcohol)
                ester=smi(ester)
                m=re.fullmatch(r'(.*?)((?:naphthalene|biphenyl|benzene|cyclohexane))-(\d+\'?),'+r'(\d+\'?)-dicarboxylate',acid)
                if m:
                    pre,parent,a,b=m.groups()
                    if a==b:return None
                    mol,loc=_parent(parent)
                    gs=prefixes(pre)
                    if gs is None:return None
                    mol=decorate(mol,loc,gs)
                    if a not in loc or b not in loc:return None
                    mol=connect(mol,loc[a],ester);mol=connect(mol,loc[b],ester)
                    return smi(mol),VERSION+'-LOCANTED-DICARBOXYLATE'
                locant={'terephthalate':('1','4'),'isophthalate':('1','3'),'phthalate':('1','2')}.get(acid)
                if locant:
                    mol,loc=_parent('benzene')
                    for p in locant:mol=connect(mol,loc[p],ester)
                    return smi(mol),VERSION+'-PHTHALATE-DIESTER'
                m=re.fullmatch(r'([a-z]+)anedioate',acid)
                if m and m[1] in STEM_N and STEM_N[m[1]]>=2:
                    # Acid backbone includes carbonyl carbons, not two extra C.
                    n=STEM_N[m[1]];mol=Chem.MolFromSmiles('O=C(O)'+'C'*(n-2)+'C(=O)O')
                    oxy=[a.GetIdx() for a in mol.GetAtoms() if a.GetAtomicNum()==8 and a.GetTotalNumHs()==1]
                    for idx in oxy:mol=connect(mol,idx,alcohol)
                    return smi(mol),VERSION+'-ALKANEDIOATE'
            m=re.fullmatch(r'([a-z]+)ano-(\d+)-lactam',name)
            if m and m[1] in STEM_N and int(m[2])==STEM_N[m[1]] and 4<=int(m[2])<=20:
                return 'O=C1'+'C'*(int(m[2])-1)+'N1',VERSION+'-OMEGA-LACTAM'
            m=re.fullmatch(r'(\d+(?:,\d+)*)-(di|tri|tetra)?(bromo|chloro|fluoro|iodo)([a-z]+)ane',name)
            if m and m[4] in STEM_N:
                ps=m[1].split(',');count={None:1,'di':2,'tri':3,'tetra':4}[m[2]]
                if len(ps)!=count:return None
                mol,loc=_parent(m[4]+'ane')
                mol=decorate(mol,loc,[(p,{'bromo':'Br','chloro':'Cl','fluoro':'F','iodo':'I'}[m[3]]) for p in ps])
                return smi(mol),VERSION+'-HALOALKANE'
            m=re.fullmatch(r'(\d+)-amino([a-z]+)anol',name)
            if m and m[2] in STEM_N:
                mol,loc=_parent(m[2]+'ane')
                return smi(decorate(mol,loc,[('1','O'),(m[1],'N')])),VERSION+'-AMINOALKANOL'
            if name.endswith('azoxybenzene'):
                gs=prefixes(name[:-len('azoxybenzene')])
                if gs is None:return None
                base,loc=_parent('biphenyl');base=decorate(base,loc,gs)
                variants=[]
                for oxide_side in (0,1):
                    rw=Chem.RWMol(base);rw.RemoveBond(0,6)
                    ns=[rw.AddAtom(Chem.Atom(7)),rw.AddAtom(Chem.Atom(7))]
                    rw.AddBond(0,ns[0],Chem.BondType.SINGLE);rw.AddBond(6,ns[1],Chem.BondType.SINGLE)
                    rw.AddBond(*ns,Chem.BondType.DOUBLE)
                    rw.GetAtomWithIdx(ns[oxide_side]).SetFormalCharge(1)
                    o=Chem.Atom(8);o.SetFormalCharge(-1);oi=rw.AddAtom(o)
                    rw.AddBond(ns[oxide_side],oi,Chem.BondType.SINGLE)
                    variants.append(smi(rw.GetMol()))
                if variants[0]==variants[1]:return variants[0],VERSION+'-SYMMETRIC-AZOXY'
                return None  # oxide-side ambiguity must not select the first
        except (ValueError,RuntimeError,IndexError,KeyError):return None
    return None
