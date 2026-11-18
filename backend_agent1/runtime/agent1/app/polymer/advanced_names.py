"""v0.5 bounded recursive source/subunit grammar; graph candidates, not gold.

A name must be fully consumed. Original spelling is not repaired. Parent locants
are attached to explicit atoms, primes refer to different aromatic rings.
Only finite acyclic C=C E/Z labels are assigned here; R/S, isotope names,
unspecified isomers and polymer stereoframes remain out of this grammar.
"""
from __future__ import annotations
import re
from functools import lru_cache
from rdkit import Chem, rdBase
from rdkit.Chem import rdCIPLabeler
from .name_rules import STEM_N
from .queue_rules import GROUPS, MULT, _unwrap, _parent

PAIRS = {'(': ')', '[': ']', '{': '}'}
LIMIT = 8
STEMS_RE = '(?:'+'|'.join(sorted(STEM_N,key=len,reverse=True))+')'
PARENTS_RE = r'(?:benzene|biphenyl|naphthalene|(?:cyclo)?'+STEMS_RE+'ane)'
RULE = 'NR-RECURSIVE-LOCANTED/0.5'


def connect(m, idx, fragment):
    """Consume exactly one explicit root port, preserving its bond order."""
    double = fragment.startswith('=')
    sub = Chem.MolFromSmiles(fragment[1:] if double else fragment)
    if sub is None:
        raise ValueError('INVALID_ROOTED_FRAGMENT')
    ports = [a.GetIdx() for a in sub.GetAtoms() if a.GetAtomicNum() == 0]
    offset = m.GetNumAtoms()
    rw = Chem.RWMol(Chem.CombineMols(m, sub))
    if ports:
        if len(ports) != 1 or sub.GetAtomWithIdx(ports[0]).GetDegree() != 1:
            raise ValueError('ONE_ROOT_PORT_REQUIRED')
        atom = sub.GetAtomWithIdx(ports[0])
        rw.AddBond(idx, offset + atom.GetNeighbors()[0].GetIdx(), atom.GetBonds()[0].GetBondType())
        rw.RemoveAtom(offset + ports[0])
    else:
        rw.AddBond(idx, offset, Chem.BondType.DOUBLE if double else Chem.BondType.SINGLE)
    return rw.GetMol()


def smi(m):
    Chem.SanitizeMol(m)
    return Chem.MolToSmiles(m, canonical=True, isomericSmiles=True)


def port(m, atom, label=0, bond=Chem.BondType.SINGLE):
    rw = Chem.RWMol(m)
    a = Chem.Atom(0)
    a.SetAtomMapNum(label)
    j = rw.AddAtom(a)
    rw.AddBond(atom, j, bond)
    return rw.GetMol()


def balanced_end(text, start=0):
    stack = []
    for i in range(start, len(text)):
        c = text[i]
        if c in PAIRS:
            stack.append(c)
        elif c in PAIRS.values():
            if not stack or PAIRS[stack.pop()] != c:
                return None
        if not stack:
            return i + 1
    return None


def prefixes(text, depth=0):
    """A complete series of locanted, possibly recursively bracketed prefixes."""
    if depth > LIMIT:
        return None
    if not text:
        return []
    if text.endswith('-'):
        text=text[:-1]
        if not text or text.endswith('-'): return None
    match = re.match(r"([0-9]+(?:')?(?:,[0-9]+(?:')?)*)-", text)
    if not match:
        return None
    locs = match[1].split(',')
    tail = text[len(match[0]):]
    for mult in ['', *sorted(MULT, key=len, reverse=True)]:
        n = 1 if not mult else MULT[mult]
        if len(locs) != n or not tail.startswith(mult):
            continue
        remainder = tail[len(mult):]
        # Only top-level boundaries are candidates, never split a bracketed name.
        ends = [len(remainder)]
        stack = []
        for i, char in enumerate(remainder):
            if char in PAIRS:
                stack.append(char)
            elif char in PAIRS.values():
                if not stack or PAIRS[stack.pop()] != char:
                    return None
            if not stack and char == '-' and i + 1 < len(remainder) and remainder[i+1].isdigit():
                ends.append(i)
        if stack:
            return None
        for end in sorted(set(ends)):
            head = remainder[:end]
            rest = remainder[end+1:] if end < len(remainder) else ''
            sub = rooted(_unwrap(head), depth+1)
            if sub is None:
                continue
            following = prefixes(rest, depth+1)
            if following is not None:
                return [(p, sub) for p in locs] + following
    return None


def decorate(m, loc, groups):
    if groups is None:
        raise ValueError('PREFIX_NOT_CONSUMED')
    for p, group in groups:
        if p not in loc:
            raise ValueError('LOCANT_OUT_OF_PARENT')
        m = connect(m, loc[p], group)
    Chem.SanitizeMol(m)
    return m


def rooted(text, depth=0):
    """Return a rooted substituent. Stars are attachment ports, never radicals."""
    if depth > LIMIT or not text or len(text) > 900:
        return None
    text = _unwrap(text)
    if text in GROUPS:
        return GROUPS[text]
    if text == 'diphenylphosphoryl':
        return '*P(=O)(c1ccccc1)c1ccccc1'
    # (substituted phenyl)diazenyl; no E/Z is inferred for the azo linkage.
    if text.endswith('diazenyl'):
        sub = rooted(_unwrap(text[:-len('diazenyl')]), depth+1)
        if sub:
            return smi(connect(Chem.MolFromSmiles('*N=N'), 2, sub))
    for suffix, linker in [('phenoxy', '*O'), ('phenylsulfanyl', '*S'),
                           ('benzoyl', '*C(=O)'), ('benzyl', '*C'),
                           ('benzylidene', '*=C'), ('phenyl', None)]:
        if not text.endswith(suffix):
            continue
        pre = text[:-len(suffix)]
        if pre.startswith('p-'):
            pre = '4-' + pre[2:]
        elif pre.startswith('m-'):
            pre = '3-' + pre[2:]
        elif pre.startswith('o-'):
            pre = '2-' + pre[2:]
        m, loc = _parent('benzene')
        groups = prefixes(pre, depth+1)
        if groups is None:
            continue
        m = decorate(m, loc, groups)
        aryl = smi(port(m, 0))
        if linker is None:
            return aryl
        lm = Chem.MolFromSmiles(linker)
        return smi(connect(lm, 1, aryl))
    # Explicit oxane attachment position (O=1), not an inferred opening product.
    match = re.fullmatch(r'(?:oxan-(\d)-yl|(\d)-oxanyl)', text)
    if match:
        p = int(match[1] or match[2])
        if not 2 <= p <= 6:
            return None
        return smi(port(Chem.MolFromSmiles('O1CCCCC1'), p-1))
    # One substituent on a methylene/methoxy root; grouping must be explicit.
    for suffix, base, target in [('methoxy', '*OC', 2), ('methyl', '*C', 1)]:
        if text.endswith(suffix):
            pre = text[:-len(suffix)]
            if pre and pre[0] in PAIRS and balanced_end(pre) == len(pre):
                sub = rooted(_unwrap(pre), depth+1)
                if sub:
                    return smi(connect(Chem.MolFromSmiles(base), target, sub))
    # Fully locanted normal alkyl / alkoxy groups.
    for stem, n in sorted(STEM_N.items(), key=lambda x: -len(x[0])):
        for suffix, oxygen in [(stem+'yl', False), (stem+'yloxy', True), (stem+'oxy', True)]:
            if not text.endswith(suffix):
                continue
            groups = prefixes(text[:-len(suffix)], depth+1)
            if groups is None:
                continue
            m, loc = _parent(stem+'ane')
            m = decorate(m, loc, groups)
            if oxygen:
                rw = Chem.RWMol(m)
                o = rw.AddAtom(Chem.Atom('O')); rw.AddBond(0,o,Chem.BondType.SINGLE)
                return smi(port(rw.GetMol(),o))
            return smi(port(m,0))
    # v0.7: explicitly grouped alkyl/aryl oxy substituents. No repair of text.
    match=re.fullmatch(r'(\(.+\)|\[.+\]|\{.+\})oxy',text)
    if match:
        inner=rooted(_unwrap(match[1]),depth+1)
        if inner:return smi(connect(Chem.MolFromSmiles('*O'),1,inner))
    return None


def diyl(text):
    """Oriented two-port aryl fragment for CU composition and named bridges."""
    text = _unwrap(text)
    match = re.fullmatch(r'(.*?)([1-6]),([1-6])-phenylene', text)
    if match:
        pre, parent, a, b = match[1], 'benzene', match[2], match[3]
    else:
        match = re.fullmatch(r"(.*?)("+PARENTS_RE+r")-(\d+'?),(\d+'?)-diyl",text)
        if not match:
            return None
        pre, parent, a, b = match.groups()
    m, loc = _parent(parent)
    m = decorate(m, loc, prefixes(pre))
    if a not in loc or b not in loc:
        return None
    return smi(port(port(m,loc[a],1),loc[b],2))


def capped_diyl(fragment, cap='*OC(=O)Cl'):
    m = Chem.MolFromSmiles(fragment)
    ps = [a.GetIdx() for a in m.GetAtoms() if a.GetAtomicNum()==0]
    if len(ps)!=2:
        return None
    # Replace each original dummy by a rooted cap. Addition leaves old indices unchanged.
    for p in ps:
        neighbor = m.GetAtomWithIdx(p).GetNeighbors()[0].GetIdx()
        m = connect(m, neighbor, cap)
    rw = Chem.RWMol(m)
    for p in sorted(ps,reverse=True):
        rw.RemoveAtom(p)
    return smi(rw.GetMol())


def chain_parent(text):
    """Finite source graph plus alkene locant->bond endpoints before canonicalization."""
    match = re.fullmatch(r'(.*?)('+STEMS_RE+r')-(\d+)-(ene|enedioic acid|enedioyl dichloride)',text)
    if match:
        pre, stem, p, suffix = match.groups()
    elif text.endswith('ethene'):
        pre, stem, p, suffix = text[:-6], 'eth', '1', 'ene'
    elif text.endswith('propene'):
        pre, stem, p, suffix = text[:-7], 'prop', '1', 'ene'
    else:
        return None
    if stem not in STEM_N:
        return None
    n, p = STEM_N[stem], int(p)
    if not 1 <= p < n:
        return None
    groups = prefixes(pre)
    m,loc = _parent(stem+'ane')
    rw = Chem.RWMol(m)
    rw.GetBondBetweenAtoms(p-1,p).SetBondType(Chem.BondType.DOUBLE)
    m=rw.GetMol()
    if suffix != 'ene':
        if n<4 or p in (1,n-1):
            return None
        ending='O' if suffix=='enedioic acid' else 'Cl'
        for pos in (0,n-1):
            m=connect(m,pos,'=O');m=connect(m,pos,ending)
    return decorate(m,loc,groups), {str(p):(p-1,p)}


def ez_source(text):
    match = re.fullmatch(r'\((\d*)([EZ])\)-(.+)',text)
    if not match:
        return None
    spec, want, rest = match.groups()
    graph = chain_parent(rest)
    if graph is None:
        return None
    m,bonds=graph
    if spec and spec not in bonds:
        return None
    u,v=next(iter(bonds.values()))
    possible={s.centeredOn for s in Chem.FindPotentialStereo(m) if s.type==Chem.StereoType.Bond_Double}
    bond=m.GetBondBetweenAtoms(u,v)
    if bond.GetIdx() not in possible:
        return None  # A terminal CH2=C or identical ligands cannot carry E/Z.
    # Assign a geometric trial, then use the actual CIP labeler to check E/Z.
    left=next(a.GetIdx() for a in m.GetAtomWithIdx(u).GetNeighbors() if a.GetIdx()!=v)
    right=next(a.GetIdx() for a in m.GetAtomWithIdx(v).GetNeighbors() if a.GetIdx()!=u)
    bond.SetStereoAtoms(left,right)
    for stereo in (Chem.BondStereo.STEREOTRANS, Chem.BondStereo.STEREOCIS):
        bond.SetStereo(stereo)
        if bond.HasProp('_CIPCode'):bond.ClearProp('_CIPCode')
        rdCIPLabeler.AssignCIPLabels(m)
        if bond.HasProp('_CIPCode') and bond.GetProp('_CIPCode')==want:
            Chem.SetDoubleBondNeighborDirections(m)
            result=smi(m)
            check=Chem.MolFromSmiles(result);rdCIPLabeler.AssignCIPLabels(check)
            codes=[b.GetProp('_CIPCode') for b in check.GetBonds() if b.HasProp('_CIPCode')]
            if codes==[want]:return result
    return None


@lru_cache(maxsize=30000)
def resolve_source_v05(raw):
    if not isinstance(raw,str) or not raw or len(raw)>1200:
        return None
    name=raw.replace('\u2032',"'")
    with rdBase.BlockLogs():
        try:
            if re.match(r'^\(\d*[EZ]\)-',name):
                s=ez_source(name)
                return (s,'NR-EXPLICIT-ACYCLIC-CIP-EZ/0.5') if s else None
            # Numbered independent phenyl rings on C=O. Prime remains a ring label.
            if name.endswith('benzophenone'):
                groups=prefixes(name[:-len('benzophenone')])
                m,loc=_parent('biphenyl');rw=Chem.RWMol(m);rw.RemoveBond(0,6)
                c=rw.AddAtom(Chem.Atom('C'));o=rw.AddAtom(Chem.Atom('O'))
                rw.AddBond(c,o,Chem.BondType.DOUBLE);rw.AddBond(c,0,Chem.BondType.SINGLE);rw.AddBond(c,6,Chem.BondType.SINGLE)
                return smi(decorate(rw.GetMol(),loc,groups)),RULE+'-BENZOPHENONE'
            # Two substituted aryl groups and one named alkyl/phenyl attached to P=O.
            match=re.fullmatch(r'bis(\(.+\)|\[.+\]|\{.+\})(.+)phosphine oxide',name)
            if match:
                ar=rooted(_unwrap(match[1]));other=rooted(match[2])
                if ar and other:
                    m=Chem.MolFromSmiles('P=O')
                    for sub in (ar,ar,other):m=connect(m,0,sub)
                    return smi(m),RULE+'-PHOSPHINE-OXIDE'
            # Two outer aniline rings joined through explicitly locanted central dioxy ring.
            match=re.fullmatch(r"([2-6]),([2-6])'-(.+)dioxydianiline",name)
            if match:
                bridge=diyl(_unwrap(match[3]))
                if bridge:
                    m=Chem.MolFromSmiles(bridge)
                    ps=[a.GetIdx() for a in m.GetAtoms() if a.GetAtomicNum()==0]
                    for p, outer in zip(ps,[match[1],match[2]]):
                        ring,rloc=_parent('benzene');ring=decorate(ring,rloc,[('1','N')])
                        # Dummy becomes O: root-to-central numbering/role stays unchanged.
                        m.GetAtomWithIdx(p).SetAtomicNum(8);m.GetAtomWithIdx(p).SetAtomMapNum(0)
                        m=connect(m,p,smi(port(ring,rloc[outer])))
                    return smi(m),RULE+'-PHOSPHORYL-DIOXY-BRIDGE'
            # Diol chloroformates are named molecules, not an inferred polymerization.
            match=re.fullmatch(r'(.+?)(?: bis\(chloroformate\)| bischloroformate)',name)
            if match:
                core=match[1]
                core=re.sub(r'-(\d+),(\d+)-diol$',r'-\1,\2-diyl',core)
                fragment=diyl(core)
                if fragment:return capped_diyl(fragment),RULE+'-BISCHLOROFORMATE'
            # Locanted bis(benzylidene)cycloalkanones; exocyclic C=C geometry unspecified.
            match=re.fullmatch(r'(.*?)cyclo([a-z]+)anone',name)
            if match and match[2] in STEM_N:
                m,loc=_parent('cyclo'+match[2]+'ane');m=connect(m,0,'=O')
                return smi(decorate(m,loc,prefixes(match[1]))),RULE+'-CYCLOALKANONE'
            # General supported parents with recursively bracketed substituents.
            match=re.fullmatch(r'(.*?)('+PARENTS_RE+r')-(\d+(?:,\d+)*)-(diol|diamine|dithiol)',name)
            if match:
                pre,parent,locs,suffix=match.groups();ps=locs.split(',')
                if len(ps)!=2 or len(set(ps))!=2:return None
                m,loc=_parent(parent)
                groups=prefixes(pre)
                if groups is None:return None
                groups += [(p,{'diol':'O','diamine':'N','dithiol':'S'}[suffix]) for p in ps]
                return smi(decorate(m,loc,groups)),RULE+'-FUNCTIONAL-PARENT'
            for suffix,fixed in [('benzoic acid','C(=O)O'),('aniline','N'),('phenol','O'),('styrene','C=C')]:
                if name.endswith(suffix):
                    m,loc=_parent('benzene');groups=prefixes(name[:-len(suffix)])
                    if groups is not None:return smi(decorate(m,loc,[('1',fixed)]+groups)),RULE+'-ARYL'
            chain=chain_parent(name)
            if chain:return smi(chain[0]),RULE+'-ALKENE'
        except (ValueError,RuntimeError,IndexError,KeyError,StopIteration,AttributeError):
            return None
    return None


@lru_cache(maxsize=30000)
def resolve_diyl_v05(raw):
    if not isinstance(raw,str) or len(raw)>1000:return None
    with rdBase.BlockLogs():
        try:return diyl(raw.replace('\u2032',"'"))
        except (ValueError,RuntimeError,KeyError,IndexError):return None
