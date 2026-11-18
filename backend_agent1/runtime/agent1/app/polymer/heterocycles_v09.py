"""Explicitly locanted heterocycles and nitrogen-substituted sources.

Fallback rules only, no spelling repair, no implicit stereochemical selection.
These rules produce candidates, not independently verified actual monomers.
"""
from functools import lru_cache
import re
from rdkit import Chem,rdBase
from .advanced_names import connect,port,smi

RINGS={
 'pyridine':('n1ccccc1',[0,1,2,3,4,5]),
 'pyrimidine':('n1cnccc1',[0,1,2,3,4,5]),
 'pyrazine':('n1ccncc1',[0,1,2,3,4,5]),
 'pyridazine':('n1ncccc1',[0,1,2,3,4,5]),
 '1,3,5-triazine':('n1cncnc1',[0,1,2,3,4,5]),
 'piperidine':('N1CCCCC1',[0,1,2,3,4,5]),
 'piperazine':('N1CCNCC1',[0,1,2,3,4,5]),
 'pyrrolidine':('N1CCCC1',[0,1,2,3,4]),
 'morpholine':('O1CCNCC1',[0,1,2,3,4,5]),
 'thiomorpholine':('S1CCNCC1',[0,1,2,3,4,5]),
 'pyrrolidin-2-one':('N1C(=O)CCC1',[0,1,3,4,5]),
 'pyrrolidine-2-one':('N1C(=O)CCC1',[0,1,3,4,5]),
 'pyrrolidine-2-thione':('N1C(=S)CCC1',[0,1,3,4,5]),
 'piperidin-2-one':('N1C(=O)CCCC1',[0,1,3,4,5,6]),
 'pyrrolidine-2,5-dione':('N1C(=O)CCC1=O',[0,1,3,4,5]),
 'piperidine-2,6-dione':('N1C(=O)CCCC1=O',[0,1,3,4,5,6]),
 'maleimide':('N1C(=O)C=CC1=O',[0,1,3,4,5]),
}
STEM_PARENT={'pyridin':'pyridine','pyrimidin':'pyrimidine','pyrazin':'pyrazine','pyridazin':'pyridazine',
             'piperidin':'piperidine','piperazin':'piperazine','pyrrolidin':'pyrrolidine',
             'morpholin':'morpholine','thiomorpholin':'thiomorpholine',
             'thien':'thiophene','thiophen':'thiophene','fur':'furan','furan':'furan','pyrrol':'pyrrole',
             'naphthalen':'naphthalene'}
RULE='LOCANTED-HETEROCYCLE/0.9'


def ring_parent(name):
    if name not in RINGS:return None
    text,indices=RINGS[name];m=Chem.MolFromSmiles(text)
    return m,{str(i+1):j for i,j in enumerate(indices)}


def _parent(name):
    from .queue_rules import _parent as old
    return ring_parent(name) or old(name)


def _attach(m,i,f):
    # Aromatic [nH] requires explicit replacement of H, not addition to [nH].
    a=m.GetAtomWithIdx(i)
    if a.GetTotalNumHs()==0:raise ValueError('SUBSTITUTION_SITE_HAS_NO_REPLACEABLE_H')
    if a.GetIsAromatic() and a.GetAtomicNum()==7:
        m=Chem.Mol(m);m.GetAtomWithIdx(i).SetNumExplicitHs(0)
    return connect(m,i,f)


def _decorate(m,loc,items):
    if items is None:return None
    for position,fragment in items:
        if position not in loc:return None
        m=_attach(m,loc[position],fragment);Chem.SanitizeMol(m)
    return m


@lru_cache(maxsize=30000)
def rooted_extension(s,depth=0):
    from .expansion_v08 import _safe,prefixes,_unwrap
    if depth>8 or not _safe(s):return None
    s=_unwrap(s)
    with rdBase.BlockLogs():
        try:
            match=re.fullmatch(r'(.*?)('+ '|'.join(sorted(STEM_PARENT,key=len,reverse=True))+r')-(\d+)-yl',s)
            if match:pre,parent,pos=match[1],STEM_PARENT[match[2]],match[3]
            else:
                match=re.fullmatch(r'(.*?)([1-9])-(pyridyl|thienyl|furyl)',s)
                if not match:return None
                pre,pos=match[1],match[2];parent={'pyridyl':'pyridine','thienyl':'thiophene','furyl':'furan'}[match[3]]
            m,loc=_parent(parent);m=_decorate(m,loc,prefixes(pre,depth+1))
            if m is None or pos not in loc:return None
            if m.GetAtomWithIdx(loc[pos]).GetTotalNumHs()==0:return None
            if m.GetAtomWithIdx(loc[pos]).GetAtomicNum()==7 and m.GetAtomWithIdx(loc[pos]).GetIsAromatic():m.GetAtomWithIdx(loc[pos]).SetNumExplicitHs(0)
            return smi(port(m,loc[pos]))
        except (ValueError,RuntimeError,KeyError,IndexError):return None


@lru_cache(maxsize=30000)
def divalent_extension(s,depth=0):
    from .expansion_v08 import _safe,prefixes,divalent,sequence,join,_unwrap
    if depth>8 or not _safe(s):return None
    s=_unwrap(s)
    with rdBase.BlockLogs():
        try:
            # Two oxy termini around the explicitly named central diyl.
            if s.endswith('dioxy'):
                middle=s[:-5]
                middle={'o-phenylene':'1,2-phenylene','m-phenylene':'1,3-phenylene','p-phenylene':'1,4-phenylene'}.get(middle,middle)
                central=divalent(middle,depth+1)
                if central:return join(['*O*',central,'*O*'])
            match=re.fullmatch(r'(.*?)('+ '|'.join(sorted(RINGS,key=len,reverse=True))+r')-(\d+),(\d+)-diyl',s)
            if not match:return None
            pre,parent,a,b=match.groups();m,loc=_parent(parent);m=_decorate(m,loc,prefixes(pre,depth+1))
            if m is None or a not in loc or b not in loc:return None
            for label,p in [(1,a),(2,b)]:
                atom=m.GetAtomWithIdx(loc[p])
                if atom.GetTotalNumHs()==0:return None
                if atom.GetAtomicNum()==7 and atom.GetIsAromatic():atom.SetNumExplicitHs(0)
                m=port(m,loc[p],label);Chem.SanitizeMol(m)
            return smi(m)
        except (ValueError,RuntimeError,KeyError,IndexError):return None


@lru_cache(maxsize=30000)
def source(s):
    from .expansion_v08 import _safe,prefixes,rooted,sequence,_unwrap
    from .queue_rules import name_diagnostic
    if not _safe(s) or name_diagnostic(s):return None
    with rdBase.BlockLogs():
        try:
            # N-substituted maleimides: accept explicit N, not an unlocated substituent.
            match=re.fullmatch(r'N-(.+?)\s*maleimide',s)
            if match:
                f=rooted(_unwrap(match[1].strip()))
                if f:
                    m,loc=_parent('maleimide');return smi(_attach(m,loc['1'],f)),RULE+'-N-IMIDE'
            # Exact ring parent plus fully consumed locanted substitutions.
            for parent in sorted(RINGS,key=len,reverse=True):
                if s.endswith(parent):
                    pre=s[:-len(parent)];m,loc=_parent(parent);m=_decorate(m,loc,prefixes(pre))
                    if m is not None:return smi(m),RULE+'-RING'
            parents='|'.join(sorted(set(RINGS)|{'naphthalene','benzene','biphenyl'},key=len,reverse=True))
            match=re.fullmatch(r'(.*?)('+parents+r')-([0-9,\']+)-(diamine|triamine|diol|dicarboxylic acid|carboxylic acid|dicarbonyl dichloride|carbonyl chloride)',s)
            if match:
                pre,parent,positions,func=match.groups();ps=positions.split(',')
                count=3 if func=='triamine' else 2 if func.startswith('di') else 1
                if len(ps)!=count or len(set(ps))!=count:return None
                fg='*N' if 'amine' in func else '*O' if func=='diol' else '*C(=O)Cl' if 'chloride' in func else '*C(=O)O'
                groups=prefixes(pre)
                if groups is None:return None
                m,loc=_parent(parent);m=_decorate(m,loc,list(groups)+[(p,fg) for p in ps])
                if m is not None:return smi(m),RULE+'-FUNCTIONAL'
            match=re.fullmatch(r'(.*?)([1-8])-(naphthol|naphthoic acid)',s)
            if match:
                m,loc=_parent('naphthalene');items=prefixes(match[1])
                if items is not None:
                    m=_decorate(m,loc,list(items)+[(match[2],'*O' if match[3]=='naphthol' else '*C(=O)O')])
                    if m is not None:return smi(m),RULE+'-NAPHTHALENE'
            # Substituted two-ring sources. Prime locants remain on the second ring.
            match=re.fullmatch(r"(.*)([2-6]),([2-6])'-(.+?)(dianiline|diphenol|dibenzoic acid)",s)
            if match:
                pre,a,b,bridge_name,suffix=match.groups();items=prefixes(pre)
                central=sequence(_unwrap(bridge_name))
                if items is None or central is None:return None
                fg={'dianiline':'*N','diphenol':'*O','dibenzoic acid':'*C(=O)O'}[suffix]
                left,lloc=_parent('benzene');right,rloc=_parent('benzene')
                left=_attach(left,0,fg);right=_attach(right,0,fg)
                left=_decorate(left,lloc,[(p,f) for p,f in items if "'" not in p])
                right=_decorate(right,rloc,[(p[:-1],f) for p,f in items if p.endswith("'")])
                if left is None or right is None:return None
                # Two attachment sites must not already be saturated by source substituents.
                if left.GetAtomWithIdx(int(a)-1).GetTotalNumHs()==0 or right.GetAtomWithIdx(int(b)-1).GetTotalNumHs()==0:return None
                lf=smi(port(left,int(a)-1));rf=smi(port(right,int(b)-1))
                m=Chem.MolFromSmiles(central);ps={x.GetAtomMapNum():x.GetIdx() for x in m.GetAtoms() if x.GetAtomicNum()==0}
                if set(ps)!={1,2}:return None
                targets=[m.GetAtomWithIdx(ps[i]).GetNeighbors()[0].GetIdx() for i in (1,2)]
                m=connect(connect(m,targets[0],lf),targets[1],rf);rw=Chem.RWMol(m)
                for p in sorted(ps.values(),reverse=True):rw.RemoveAtom(p)
                return smi(rw.GetMol()),RULE+'-LOCANTED-BRIDGE'
        except (ValueError,RuntimeError,KeyError,IndexError):return None
    return None
