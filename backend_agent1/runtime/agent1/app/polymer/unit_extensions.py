"""Additional compositional CU fragments; all generated structures are candidates.
Hyphens are consumed only as boundaries between complete tokens, never erased
from a source name. No arbitrary parenthesized text is treated as a branch.
"""
import re
from rdkit import Chem
from .name_rules import STEM_N

EXTRA_TOKENS={
'dimethylmethylene':'*C(C)(C)*','1,1-dimethylethylene':'*C(C)(C)C*',
'phenylmethylene':'*C(c1ccccc1)*','diphenylmethylene':'*C(c1ccccc1)(c1ccccc1)*',
'methylmethylene':'*C(C)*','1-cyanoethylene':'*C(C#N)C*','1-hydroxyethylene':'*C(O)C*',
'1-acetoxyethylene':'*C(OC(C)=O)C*',
'sulfinyl':'*S(=O)*','carbonothioyl':'*C(=S)*','thiocarbonyl':'*C(=S)*',
'diazenediyl':'*N=N*','hydrazine-1,2-diyl':'*NN*','ethene-1,2-diyl':'*C=C*',
'vinylene':'*C=C*',
"biphenyl-4,4'-diyl":'*c1ccc(-c2ccc(*)cc2)cc1',
'1-methylbut-1-ene-1,4-diyl':'*C(C)=CCC*',
'hexafluoroisopropylidene':'*C(C(F)(F)F)(C(F)(F)F)*',
'2,2,2-trifluoro-1-(trifluoromethyl)ethane-1,1-diyl':'*C(C(F)(F)F)(C(F)(F)F)*',
'1-oxohexane-1,6-diyl':'*C(=O)CCCCC*',
'diethylsilanediyl':'*[Si](CC)(CC)*','diphenylsilanediyl':'*[Si](c1ccccc1)(c1ccccc1)*',
}
for stem,n in STEM_N.items():
    if n>=2:
        EXTRA_TOKENS[stem+'anedioyl']='*C(=O)'+'C'*(n-2)+'C(=O)*'
        EXTRA_TOKENS[stem+f'ane-1,{n}-diyl']='*'+'C'*n+'*'
for alias,root in [('adipoyl','hexanedioyl'),('glutaryl','pentanedioyl'),('malonyl','propanedioyl'),('succinyl','butanedioyl'),('oxalyl','ethanedioyl'),('sebacoyl','decanedioyl')]:
    EXTRA_TOKENS[alias]=EXTRA_TOKENS[root]
for pos in (2,3,4):
    ring='c1ccccc1'
    for group,label in [('C','methyl'),('Cl','chloro'),('F','fluoro')]:
        # Only positions not occupied by the two 1,4 ports can be substituted.
        if pos==4:continue
        rw=Chem.RWMol(Chem.MolFromSmiles(ring));i=rw.AddAtom(Chem.Atom(group));rw.AddBond(pos-1,i,Chem.BondType.SINGLE)
        for p in (0,3):
            j=rw.AddAtom(Chem.Atom(0));rw.AddBond(p,j,Chem.BondType.SINGLE)
        m=rw.GetMol();Chem.SanitizeMol(m)
        EXTRA_TOKENS[f'{pos}-{label}-1,4-phenylene']=Chem.MolToSmiles(m)

# Alkoxycarbonyl-substituted ethylene units, constructed from the alkyl chain.
for stem,n in STEM_N.items():
    alkoxy=stem+'oxy'
    EXTRA_TOKENS['1-('+alkoxy+'carbonyl)ethylene']='*C(C(=O)O'+'C'*n+')C*'
    EXTRA_TOKENS['1-('+alkoxy+'carbonyl)-1-methylethylene']='*C(C)(C(=O)O'+'C'*n+')C*'

# Traditional PRODUCT names do not designate finite monomer molecules.
PRODUCT_ALIASES={
'ethylene terephthalate':'oxyethyleneoxyterephthaloyl',
'butylene terephthalate':'oxybutane-1,4-diyloxyterephthaloyl',
'hexane-1,6-diyladipamide':'iminoadipoyliminohexane-1,6-diyl',
'bisphenol A carbonate':'oxy-1,4-phenylene(dimethylmethylene)-1,4-phenyleneoxycarbonyl',
'phenylene oxide':'oxy-1,4-phenylene',
}


def tokenize_complete(name,tokens,old_diyl):
    """Memoized full-parse search with longest-token preference. All input must
    be consumed. This bounded lexicon is not a general ambiguous CU grammar;
    alternate tokenizations are not an independent chemical oracle.
    """
    pairs={'(':')','[':']','{':'}'};memo={};ordered=sorted(tokens,key=lambda t:(-len(t),t))
    def parse(s):
        if s in memo:return memo[s]
        if not s:return []
        if s in tokens:return [(s,tokens[s])]
        d=old_diyl(s)
        if d:return [(s,d)]
        result=None
        if s[0] in pairs:
            stack=[s[0]];j=1
            while j<len(s) and stack:
                c=s[j]
                if c in pairs:stack.append(c)
                elif c in pairs.values():
                    if not stack or pairs[stack.pop()]!=c:return None
                j+=1
            if not stack:
                inner=parse(s[1:j-1]);tail=s[j:]
                if tail.startswith('-'):tail=tail[1:]
                rest=parse(tail) if tail else []
                if inner is not None and rest is not None and not (s.endswith('-')): result=inner+rest
        if result is None:
            # A dynamic locanted fragment can be followed by more subunits.
            # Explore only explicit divalent suffix boundaries, never arbitrary cuts.
            ends=[m.end() for m in re.finditer(r'(?:diyl|phenylene|ethylene)',s)]
            for end in sorted(ends,reverse=True)[:64]:
                if end==len(s):continue
                token=s[:end];value=old_diyl(token)
                if not value:continue
                tail=s[end:]
                if tail.startswith('-'):tail=tail[1:]
                if not tail:continue
                rest=parse(tail)
                if rest is not None:result=[(token,value)]+rest;break
        if result is None:
            for t in ordered:
                if not s.startswith(t):continue
                tail=s[len(t):]
                if tail.startswith('-'):tail=tail[1:]
                if not tail:continue # exact token handled above; disallow a dangling '-'
                rest=parse(tail)
                if rest is not None:
                    result=[(t,tokens[t])]+rest;break
        memo[s]=result;return result
    return parse(name)

# Fully specified N-substituted divalent units.
for _n,_s in [('methyl','C'),('ethyl','CC'),('propyl','CCC'),('phenyl','c1ccccc1'),('benzyl','Cc1ccccc1')]:
    EXTRA_TOKENS[_n+'imino']='*N('+_s+')*'
EXTRA_TOKENS['bis(trifluoromethyl)methylene']='*C(C(F)(F)F)(C(F)(F)F)*'
