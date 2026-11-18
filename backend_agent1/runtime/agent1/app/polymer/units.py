"""Compositional CU-name subset: tokens and locanted chain/ring diyl graphs.
It does not reinterpret every unrecognized polymer leaf as an actual monomer.
"""
from functools import lru_cache
import re
from rdkit import Chem
from .periodic import assemble,canonicalize_unit
from .name_rules import STEM_N
from .queue_rules import resolve_diyl
from .advanced_names import resolve_diyl_v05
from .common import fail
from .unit_extensions import EXTRA_TOKENS,PRODUCT_ALIASES,tokenize_complete
TOKENS={
'oxy':'*O*','imino':'*N*','thio':'*S*','sulfanediyl':'*S*','sulfonyl':'*S(=O)(=O)*','carbonyl':'*C(=O)*',
'methylene':'*C*','ethylene':'*CC*','trimethylene':'*CCC*','tetramethylene':'*CCCC*','pentamethylene':'*CCCCC*','hexamethylene':'*CCCCCC*',
'1,2-phenylene':'*c1ccccc1*','1,3-phenylene':'*c1cccc(*)c1','1,4-phenylene':'*c1ccc(*)cc1',
'phthaloyl':'*C(=O)c1ccccc1C(=O)*','isophthaloyl':'*C(=O)c1cccc(C(=O)*)c1','terephthaloyl':'*C(=O)c1ccc(C(=O)*)cc1',
'dimethylsilanediyl':'*[Si](C)(C)*','silanediyl':'*[SiH2]*','1-phenylethylene':'*C(c1ccccc1)C*',
'1-vinylethane-1,2-diyl':'*C(C=C)C*','1-methylethylene':'*C(C)C*','1-chloroethylene':'*C(Cl)C*','1-fluoroethylene':'*C(F)C*',
'1,1-difluoroethylene':'*C(F)(F)C*','difluoromethylene':'*C(F)(F)*',
'1-(methoxycarbonyl)-1-methylethylene':'*C(C)(C(=O)OC)C*',
'1-(methoxycarbonyl)ethylene':'*C(C(=O)OC)C*',
}
TOKENS.update({k:v for k,v in EXTRA_TOKENS.items() if k not in TOKENS})
STRUCTURAL_ALIASES={'dimethylsiloxane':'oxy(dimethylsilanediyl)','oxymethylene':'oxymethylene'}
STRUCTURAL_ALIASES.update(PRODUCT_ALIASES)
PAIRS={'(':')','[':']','{':'}'}

def _diyl(name):
    extended = resolve_diyl(name) or resolve_diyl_v05(name)
    if extended: return extended
    m=re.fullmatch(r'([a-z]+)ane-(\d+),(\d+)-diyl',name)
    if m and m[1] in STEM_N:
        n=STEM_N[m[1]];a,b=int(m[2]),int(m[3]);s='C'*n
    else:
        m=re.fullmatch(r'benzene-1,([234])-diyl',name)
        if m:s='c1ccccc1';a,b=1,int(m[1]);n=6
        else:
            m=re.fullmatch(r'([a-z]+)-(\d+)-ene-(\d+),(\d+)-diyl',name)
            if not m or m[1] not in STEM_N:return None
            n=STEM_N[m[1]];p=int(m[2]);a,b=int(m[3]),int(m[4])
            if not 1<=p<n:return None
            s='C'*n;double_at=p
    if not (1<=a<=n and 1<=b<=n):return None
    rw=Chem.RWMol(Chem.MolFromSmiles(s))
    if 'double_at' in locals():rw.GetBondBetweenAtoms(double_at-1,double_at).SetBondType(Chem.BondType.DOUBLE)
    for lab,pos in [(1,a),(2,b)]:
        at=Chem.Atom(0);at.SetAtomMapNum(lab);i=rw.AddAtom(at);rw.AddBond(pos-1,i,Chem.BondType.SINGLE)
    try:r=rw.GetMol();Chem.SanitizeMol(r);return Chem.MolToSmiles(r)
    except (RuntimeError,ValueError):return None

def tokenize(name):
    """Full-consumption parser; choose longest named token only when complete.
    A branch can contain one nested CU expression; structural meaning is never
    obtained by globally deleting all parentheses.
    """
    if name in TOKENS:return [(name,TOKENS[name])]
    d=_diyl(name)
    if d:return [(name,d)]
    pos=0;out=[];ordered=sorted(TOKENS,key=len,reverse=True)
    while pos<len(name):
        if name[pos] in PAIRS:
            stack=[name[pos]];j=pos+1
            while j<len(name) and stack:
                c=name[j]
                if c in PAIRS:stack.append(c)
                elif c in PAIRS.values():
                    if not stack or PAIRS[stack.pop()]!=c:return None
                j+=1
            if stack:return None
            sub=tokenize(name[pos+1:j-1])
            if not sub:return None
            out.extend(sub);pos=j;continue
        found=next((t for t in ordered if name.startswith(t,pos)),None)
        if not found:return None
        out.append((found,TOKENS[found]));pos+=len(found)
    return out or None

@lru_cache(maxsize=30000)
def resolve_unit(name):
    if not isinstance(name,str) or len(name)>1200:return fail('CU_INPUT_LIMIT')
    a=name.strip();a=STRUCTURAL_ALIASES.get(a,a);parts=tokenize(a) or tokenize_complete(a,TOKENS,_diyl)
    new_grammar=not bool(parts)
    if not parts:
        from .expansion_v08 import sequence
        candidate=sequence(a)
        if not candidate:return fail('CU_NAME_OUTSIDE_IMPLEMENTED_GRAMMAR')
        parts=[(a,candidate)]
    try:
        s=assemble([x[1] for x in parts]);p=canonicalize_unit(s)
        if p['status']!='PARSED':return p
        return {'status':'PARSED','unit_smiles':s,'periodic':p,'subunit_names':[x[0] for x in parts],
                'support_type':'RULE_DERIVED_STRUCTURE_NAME_CANDIDATE','rule_id':('CU-ROOTED-COMPOSITION/0.8' if new_grammar else 'CU-COMPOSITIONAL/0.3'),
                'name_independently_verified':False}
    except (ValueError,RuntimeError) as exc:return fail(str(exc))
