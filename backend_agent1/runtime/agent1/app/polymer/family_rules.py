"""Fully consumed, locant-aware candidate name grammars (v0.3).

No catalog ids/formulas/test expectations are consulted. These are proposed
name->graph rules, not independently reviewed bindings. Unspecified positions,
unknown stereochemistry and broken names are never silently completed.
"""
from __future__ import annotations
import re
from rdkit import Chem
from .name_rules import STEM_N


def _attach(rw: Chem.RWMol, atom: int, substituent: str) -> Chem.RWMol:
    m = Chem.MolFromSmiles(substituent)
    if m is None:
        raise ValueError('INVALID_SUBSTITUENT')
    offset = rw.GetNumAtoms()
    out = Chem.RWMol(Chem.CombineMols(rw.GetMol(), m))
    out.AddBond(atom, offset, Chem.BondType.SINGLE)
    return out


def _ring(substituents: list[tuple[int, str]]) -> Chem.Mol:
    rw = Chem.RWMol(Chem.MolFromSmiles('c1ccccc1'))
    used = set()
    for pos, sub in substituents:
        if pos not in range(1, 7) or pos in used:
            raise ValueError('INVALID_OR_REPEATED_LOCANT')
        used.add(pos)
        rw = _attach(rw, pos - 1, sub)
    m = rw.GetMol(); Chem.SanitizeMol(m)
    return m


def _anhydride_ring() -> Chem.Mol:
    # Ring numbering is phthalic-acid numbering: adjacent acyl groups at 1,2.
    rw = Chem.RWMol(Chem.MolFromSmiles('c1ccccc1'))
    centers = []
    for pos in (0, 1):
        off = rw.GetNumAtoms(); rw = _attach(rw, pos, 'C=O'); centers.append(off)
    oxy = rw.AddAtom(Chem.Atom('O'))
    for c in centers: rw.AddBond(c, oxy, Chem.BondType.SINGLE)
    m = rw.GetMol(); Chem.SanitizeMol(m)
    return m


BRIDGES = {
    'oxy': '*O*', 'sulfonyl': '*S(=O)(=O)*', 'thio': '*S*',
    'sulfanediyl': '*S*', 'carbonyl': '*C(=O)*', 'methylene': '*C*',
    'isopropylidene': '*C(C)(C)*', '1-methylethane-1,1-diyl': '*C(C)(C)*',
    'propane-2,2-diyl': '*C(C)(C)*', 'hexafluoroisopropylidene': '*C(C(F)(F)F)(C(F)(F)F)*',
    '2,2,2-trifluoro-1-(trifluoromethyl)ethane-1,1-diyl': '*C(C(F)(F)F)(C(F)(F)F)*',
    'diazenediyl': '*N=N*', '1,4-phenylenedioxy': '*Oc1ccc(O*)cc1',
    "biphenyl-4,4'-diyldioxy": '*Oc1ccc(-c2ccc(O*)cc2)cc1',
    'sulfonylbis(4,1-phenyleneoxy)': '*Oc1ccc(S(=O)(=O)c2ccc(O*)cc2)cc1',
    '9H-fluorene-9,9-diyl': '*C1(*)c2ccccc2-c2ccccc21',
}


def _bridge_rings(left: Chem.Mol, right: Chem.Mol, a: int, b: int, bridge: str) -> str:
    if a not in range(1, 7) or b not in range(1, 7): raise ValueError('LOCANT_OUT_OF_RANGE')
    bm = Chem.MolFromSmiles(bridge)
    ports = [x.GetIdx() for x in bm.GetAtoms() if x.GetAtomicNum() == 0]
    if len(ports) != 2 or any(bm.GetAtomWithIdx(i).GetDegree() != 1 for i in ports):
        raise ValueError('BRIDGE_NEEDS_TWO_TERMINALS')
    lsize, rsize = left.GetNumAtoms(), right.GetNumAtoms()
    rw = Chem.RWMol(Chem.CombineMols(Chem.CombineMols(left, right), bm)); off = lsize + rsize
    for ring_atom, port in [(a - 1, ports[0]), (lsize + b - 1, ports[1])]:
        target = bm.GetAtomWithIdx(port).GetNeighbors()[0].GetIdx() + off
        rw.AddBond(ring_atom, target, Chem.BondType.SINGLE)
    for port in sorted(ports, reverse=True): rw.RemoveAtom(off + port)
    m = rw.GetMol(); Chem.SanitizeMol(m)
    return Chem.MolToSmiles(m)


def _unwrap(s: str) -> str:
    if s.startswith('(') and s.endswith(')') or s.startswith('[') and s.endswith(']'):
        return s[1:-1]
    return s


SIMPLE = {
    'hydrazine': 'NN', 'pyrrole': 'c1cc[nH]c1', 'thiophene': 'c1ccsc1',
    'epichlorohydrin': 'ClCC1CO1', 'thiophosgene': 'ClC(Cl)=S',
    'carbon monoxide': '[C-]#[O+]',
    'terephthaldehyde': 'O=Cc1ccc(C=O)cc1', 'benzidine': 'Nc1ccc(-c2ccc(N)cc2)cc1',
    '3-hydroxybutyric acid': 'CC(O)CC(=O)O',
    'propane-1,2-diol': 'CC(O)CO',
    'adipoyl dichloride': 'O=C(Cl)CCCCC(=O)Cl',
    'sebacoyl dichloride': 'O=C(Cl)CCCCCCCCC(=O)Cl',
    'benzene-1,4-bis(methylamine)': 'NCc1ccc(CN)cc1',
    '1,4-bis(aminomethyl)benzene': 'NCc1ccc(CN)cc1',
}


def extended_systematic(raw: str):
    """Return (SMILES, rule_id) or None. No partial consumption, lowercase,
    deletion of primes, tautomer collapse, or inferred ring substitution."""
    if not isinstance(raw, str) or len(raw) > 800: return None
    name = raw.replace('\u2032', "'")  # an explicit prime-token normalization
    try:
        if name in SIMPLE: return SIMPLE[name], 'NR-REFERENCE-CANDIDATE/0.3'
        # Acyl chlorides of linear dicarboxylic acids.
        m = re.fullmatch(r'([a-z]+)anedioyl dichloride', name)
        if m and m[1] in STEM_N and STEM_N[m[1]] >= 2:
            return 'O=C(Cl)' + 'C' * (STEM_N[m[1]] - 2) + 'C(=O)Cl', 'NR-LINEAR-DIACYL-CHLORIDE/0.3'
        # Functional class names of aliphatic diisocyanates.
        m = re.fullmatch(r'([a-z]+)ane-(\d+),(\d+)-diyl diisocyanate', name)
        if m and m[1] in STEM_N:
            n, a, b = STEM_N[m[1]], int(m[2]), int(m[3])
            if not (1 <= a <= n and 1 <= b <= n and a != b): return None
            rw = Chem.RWMol(Chem.MolFromSmiles('C' * n))
            for p in (a, b): rw = _attach(rw, p - 1, 'N=C=O')
            mol = rw.GetMol(); Chem.SanitizeMol(mol)
            return Chem.MolToSmiles(mol), 'NR-LOCANTED-DIISOCYANATE/0.3'
        m = re.fullmatch(r'([234]),([23456])-diisocyanatotoluene', name)
        if m:
            mol = _ring([(1, 'C'), (int(m[1]), 'N=C=O'), (int(m[2]), 'N=C=O')])
            return Chem.MolToSmiles(mol), 'NR-TOLUENE-DIISOCYANATE/0.3'
        m = re.fullmatch(r'(1,[23456])-phenylenediamine', name)
        if m: return Chem.MolToSmiles(_ring([(1, 'N'), (int(m[1][-1]), 'N')])), 'NR-PHENYLENEDIAMINE/0.3'
        m = re.fullmatch(r'([omp])-hydroxystyrene', name)
        if m: return Chem.MolToSmiles(_ring([(1, 'C=C'), ({'o':2,'m':3,'p':4}[m[1]], 'O')])), 'NR-HYDROXYSTYRENE/0.3'
        m = re.fullmatch(r'([23456]),([23456])-dimethylphenol', name)
        if m: return Chem.MolToSmiles(_ring([(1,'O'),(int(m[1]),'C'),(int(m[2]),'C')])), 'NR-DIMETHYLPHENOL/0.3'
        # Biphenyl locants are local to their respective rings; primes matter.
        m = re.fullmatch(r"biphenyl-([0-9,']+)-(diamine|tetramine|diol|dicarboxylic acid)", name)
        if m:
            nums=m[1].split(','); mult={'diamine':2,'tetramine':4,'diol':2,'dicarboxylic acid':2}[m[2]]
            if len(nums)!=mult or len(set(nums))!=mult: return None
            sub={'diamine':'N','tetramine':'N','diol':'O','dicarboxylic acid':'C(=O)O'}[m[2]]
            aa=[];bb=[]
            for token in nums:
                if not re.fullmatch(r"[2-6]'?",token):return None
                (bb if token.endswith("'") else aa).append((int(token[0]),sub))
            left,right=_ring(aa),_ring(bb);rw=Chem.RWMol(Chem.CombineMols(left,right));rw.AddBond(0,left.GetNumAtoms(),Chem.BondType.SINGLE)
            mol=rw.GetMol();Chem.SanitizeMol(mol)
            return Chem.MolToSmiles(mol),'NR-BIPHENYL-LOCAL-LOCANTS/0.3'
        # Two locanted terminal aromatic groups joined by an explicit bridge.
        m = re.fullmatch(r"([2-6]),([2-6])'-(.+?)(dianiline|diphenol|bis\(phthalic anhydride\)|bis\(isobenzofuran-1,3-dione\))", name)
        if m:
            a,b=int(m[1]),int(m[2]);bridge=_unwrap(m[3]);base=m[4]
            if bridge not in BRIDGES:return None
            if base=='dianiline':left=right=_ring([(1,'N')])
            elif base=='diphenol':left=right=_ring([(1,'O')])
            else:
                left=right=_anhydride_ring()
                if base=='bis(isobenzofuran-1,3-dione)': a-=1;b-=1
                if a not in (3,4,5,6) or b not in (3,4,5,6):return None
            return _bridge_rings(left,right,a,b,BRIDGES[bridge]),'NR-LOCANTED-AROMATIC-BRIDGE/0.3'
        m=re.fullmatch(r'bis\(([234])-(fluoro|chloro|bromo)phenyl\) ?(sulfone|ketone|ether|sulfide)',name)
        if m:
            sub={'fluoro':'F','chloro':'Cl','bromo':'Br'}[m[2]];a=int(m[1]);mol=_ring([(a,sub)])
            bridge={'sulfone':'*S(=O)(=O)*','ketone':'*C(=O)*','ether':'*O*','sulfide':'*S*'}[m[3]]
            return _bridge_rings(mol,mol,1,1,bridge),'NR-BIS-HALOPHENYL/0.3'
    except (ValueError, RuntimeError, IndexError):
        return None
    return None

# Further bounded grammars used by the high-impact queue. They construct graphs
# from explicit locants; malformed locant lists deliberately remain unresolved.
BRIDGES.update({
    '1,3-phenylenedioxy':'*Oc1cccc(O*)c1',
    'terephthaloyldioxy':'*OC(=O)c1ccc(C(=O)O*)cc1',
    'cyclohexane-1,1-diyl':'*C1(*)CCCCC1',
    'diphenylsilanediyl':'*[Si](c1ccccc1)(c1ccccc1)*',
    '1-methylethane-1,1-diylbis(4,1-phenyleneoxy)':'*Oc1ccc(C(C)(C)c2ccc(O*)cc2)cc1',
    '(1-methylethane-1,1-diyl)bis(4,1-phenyleneoxy)':'*Oc1ccc(C(C)(C)c2ccc(O*)cc2)cc1',
    '2,2,2-trifluoro-1-(trifluoromethyl)ethane-1,1-diylbis(4,1-phenyleneoxy)':'*Oc1ccc(C(C(F)(F)F)(C(F)(F)F)c2ccc(O*)cc2)cc1',
    "biphenyl-2,2'-diyldioxy":'*Oc1ccccc1-c1ccccc1O*',
})
SIMPLE.update({
    'isophthalohydrazide':'NNC(=O)c1cccc(C(=O)NN)c1',
    'succinyl dichloride':'O=C(Cl)CCC(=O)Cl',
    'suberic acid':'O=C(O)CCCCCCC(=O)O',
    'methacrylonitrile':'C=C(C)C#N', 'sulfur dioxide':'O=S=O',
    'dichlorodimethylsilane':'C[Si](C)(Cl)Cl',
    'oxydiacetic acid':'O=C(O)COCC(=O)O',
    'p-hydroxybenzoic acid':'O=C(O)c1ccc(O)cc1',
    '4-acetoxybenzoic acid':'CC(=O)Oc1ccc(C(=O)O)cc1',
    'benzene-1,4-dimethanol':'OCc1ccc(CO)cc1',
    '2,2-bis(4-hydroxyphenyl)propane':'CC(C)(c1ccc(O)cc1)c1ccc(O)cc1',
    'N-phenylmaleimide':'O=C1C=CC(=O)N1c1ccccc1',
    'ethylene bis(chloroformate)':'O=C(Cl)OCCOC(=O)Cl',
    "benzo[1,2-c:4,5-c']difuran-1,3,5,7-tetraone":'O=C1OC(=O)c2cc3c(cc12)C(=O)OC3=O',
    'naphthalene-2,6-dicarboxylic acid':'O=C(O)c1ccc2cc(C(=O)O)ccc2c1',
    'dimethyl naphthalene-2,6-dicarboxylate':'COC(=O)c1ccc2cc(C(=O)OC)ccc2c1',
})
MULT={'di':2,'tri':3,'tetra':4,'penta':5,'hexa':6,'hepta':7,'octa':8,'nona':9,'deca':10}
CHAIN_N={**STEM_N,'icos':20}


def _chain_graph(n, additions, carboxyl_ends=()):
    if not 1<=n<=40:raise ValueError('CHAIN_SIZE')
    rw=Chem.RWMol(Chem.MolFromSmiles('C'*n))
    for p in carboxyl_ends:
        for order in (Chem.BondType.DOUBLE,Chem.BondType.SINGLE):
            j=rw.AddAtom(Chem.Atom('O'));rw.AddBond(p-1,j,order)
    for p,sm in additions:
        if not 1<=p<=n:raise ValueError('CHAIN_LOCANT')
        rw=_attach(rw,p-1,sm)
    mol=rw.GetMol();Chem.SanitizeMol(mol);return Chem.MolToSmiles(mol)

_base_extended=extended_systematic

def extended_systematic(raw):
    result=_base_extended(raw)
    if result:return result
    if not isinstance(raw,str) or len(raw)>800:return None
    name=raw.replace('\u2032',"'")
    try:
        m=re.fullmatch(r"([2-6]),([2-6])'-(.+?)(dibenzoic acid|dibenzoyl chloride|dibenzoyl dichloride|di\(benzoyl chloride\))",name)
        if m:
            bridge=_unwrap(m[3])
            if bridge not in BRIDGES:return None
            sub='C(=O)O' if m[4]=='dibenzoic acid' else 'C(=O)Cl';mol=_ring([(1,sub)])
            return _bridge_rings(mol,mol,int(m[1]),int(m[2]),BRIDGES[bridge]),'NR-BRIDGED-DIARYL-ACYL/0.3'
        m=re.fullmatch(r"([2-6]),([2-6])'-diamino-([2-6]),([2-6])'-(.+)diphenol",name)
        if m:
            br=_unwrap(m[5])
            if br not in BRIDGES:return None
            l=_ring([(1,'O'),(int(m[1]),'N')]);r=_ring([(1,'O'),(int(m[2]),'N')])
            return _bridge_rings(l,r,int(m[3]),int(m[4]),BRIDGES[br]),'NR-AMINOHYDROXY-BRIDGE/0.3'
        m=re.fullmatch(r"([2-6]),([2-6])'-bis\(acetyloxy\)biphenyl",name)
        if m:
            l=_ring([(int(m[1]),'OC(C)=O')]);r=_ring([(int(m[2]),'OC(C)=O')]);rw=Chem.RWMol(Chem.CombineMols(l,r));rw.AddBond(0,l.GetNumAtoms(),Chem.BondType.SINGLE)
            mol=rw.GetMol();Chem.SanitizeMol(mol);return Chem.MolToSmiles(mol),'NR-BIPHENYL-DIACETATE/0.3'
        m=re.fullmatch(r'(1,[23456])-diethynylbenzene',name)
        if m:return Chem.MolToSmiles(_ring([(1,'C#C'),(int(m[1][-1]),'C#C')])),'NR-DIETHYNYLBENZENE/0.3'
        m=re.fullmatch(r'([23456])-methyl-1,([23456])-phenylene diisocyanate',name)
        if m:return Chem.MolToSmiles(_ring([(1,'N=C=O'),(int(m[1]),'C'),(int(m[2]),'N=C=O')])),'NR-METHYLPHENYL-DIISOCYANATE/0.3'
        m=re.fullmatch(r'([23456]),([23456])-di(chloro|fluoro|bromo)styrene',name)
        if m:
            sub={'chloro':'Cl','fluoro':'F','bromo':'Br'}[m[3]]
            return Chem.MolToSmiles(_ring([(1,'C=C'),(int(m[1]),sub),(int(m[2]),sub)])),'NR-DIHALOSTYRENE/0.3'
        m=re.fullmatch(r'(\d+(?:,\d+)*)-(di|tri|tetra|penta|hexa|hepta|octa|nona|deca)fluoro([a-z]+)ane-(\d+),(\d+)-diol',name)
        if m and m[3] in CHAIN_N:
            ps=list(map(int,m[1].split(',')))
            if len(ps)!=MULT[m[2]] or m[4]==m[5]:return None
            return _chain_graph(CHAIN_N[m[3]],[(p,'F') for p in ps]+[(int(m[4]),'O'),(int(m[5]),'O')]),'NR-LOCANTED-FLUORODIOL/0.3'
        m=re.fullmatch(r'(\d+),(\d+)-dimethyl([a-z]+)ane-(\d+),(\d+)-diol',name)
        if m and m[3] in CHAIN_N and m[4]!=m[5]:
            return _chain_graph(CHAIN_N[m[3]],[(int(m[1]),'C'),(int(m[2]),'C'),(int(m[4]),'O'),(int(m[5]),'O')]),'NR-DIMETHYLDIOL/0.3'
        m=re.fullmatch(r'(\d+)-amino([a-z]+)anoic acid',name)
        if m and m[2] in CHAIN_N:
            return _chain_graph(CHAIN_N[m[2]],[(int(m[1]),'N')],(1,)),'NR-LOCANTED-AMINOACID/0.3'
        if name=='6-aminocaproic acid':return _chain_graph(6,[(6,'N')],(1,)),'NR-CAPROIC-AMINOACID/0.3'
        m=re.fullmatch(r'(\d+)-methyladipic acid',name)
        if m:return _chain_graph(6,[(int(m[1]),'C')],(1,6)),'NR-METHYLADIPIC/0.3'
        if name=='icosane-1,20-diol':return _chain_graph(20,[(1,'O'),(20,'O')]),'NR-ICOSANE-DIOL/0.3'
    except (ValueError,RuntimeError,IndexError):return None
    return None
