"""v0.4 locant-compositional candidate grammar, shared by molecular and CU paths.

All strings must be consumed; no catalog IDs, formulas, expectations or fuzzy
matching are available here. Primes label different rings. The original input
is never edited. These are engineering candidates, NOT independently reviewed
name bindings or complete IUPAC preferred-name rules.
"""
from __future__ import annotations
import re
from functools import lru_cache
from rdkit import Chem, rdBase
from .name_rules import STEM_N, ALKYL
from .family_rules import BRIDGES, _ring, _anhydride_ring, _bridge_rings

MULT = {'di':2, 'tri':3, 'tetra':4, 'penta':5, 'hexa':6, 'bis':2, 'tris':3, 'tetrakis':4}
GROUPS = {
    'oxo':'=O','thioxo':'=S','methyl':'C','ethyl':'CC','propyl':'CCC','butyl':'CCCC','phenyl':'c1ccccc1',
    'fluoro':'F','chloro':'Cl','bromo':'Br','iodo':'I','hydroxy':'O','amino':'N',
    'sulfanyl':'S','mercapto':'S','nitro':'[N+](=O)[O-]','cyano':'C#N',
    'trifluoromethyl':'C(F)(F)F','chloromethyl':'CCl','hydroxymethyl':'CO',
    'aminomethyl':'CN','methoxy':'OC','ethoxy':'OCC','acetoxy':'OC(=O)C',
    'acetyloxy':'OC(=O)C','carboxy':'C(=O)O','carbamoyl':'C(=O)N',
    'phenoxy':'Oc1ccccc1','tert-butyl':'C(C)(C)C','tert-pentyl':'C(C)(C)CC',
    'vinyl':'C=C','ethynyl':'C#C','isocyanato':'N=C=O','isocyanatomethyl':'CN=C=O',
    'methoxycarbonyl':'C(=O)OC','ethoxycarbonyl':'C(=O)OCC',
    '2-hydroxyethoxycarbonyl':'C(=O)OCCO','(2-hydroxyethoxy)carbonyl':'C(=O)OCCO',
    '2-hydroxyethoxy':'OCCO','2-methoxyethoxy':'OCCOC',
    'oxiranylmethoxycarbonyl':'C(=O)OCC1CO1','chlorocarbonyl':'C(=O)Cl',
    'dimethylamino':'N(C)C','N,N-dimethylamino':'N(C)C',
    '9H-carbazol-9-yl':'*n1c2ccccc2c2ccccc21',
    'phthalimido':'N1C(=O)c2ccccc2C1=O',
    '4-fluorobenzoyl':'C(=O)c1ccc(F)cc1','3-fluorobenzoyl':'C(=O)c1cccc(F)c1',
}
for stem,n in STEM_N.items():
    GROUPS.setdefault(stem+'yl','C'*n)
    GROUPS.setdefault(stem+'yloxy','O'+'C'*n)
    GROUPS.setdefault(stem+'oxycarbonyl','C(=O)O'+'C'*n)


def _unwrap(s):
    pairs={'(':')','[':']','{':'}'}
    while s and s[0] in pairs and s[-1]==pairs[s[0]]:
        depth=0;good=True
        for i,c in enumerate(s):
            if c in pairs:depth+=1
            elif c in pairs.values():depth-=1
            if depth==0 and i<len(s)-1:good=False;break
        if not good:break
        s=s[1:-1]
    return s


def _attach(m, idx, text):
    """Attach a finite rooted substituent or one explicitly marked single port."""
    bond=Chem.BondType.DOUBLE if text.startswith('=') else Chem.BondType.SINGLE
    s=Chem.MolFromSmiles(text[1:] if text.startswith('=') else text)
    if s is None:raise ValueError('INVALID_SUBSTITUENT')
    ps=[a.GetIdx() for a in s.GetAtoms() if a.GetAtomicNum()==0]
    off=m.GetNumAtoms(); rw=Chem.RWMol(Chem.CombineMols(m,s))
    if ps:
        if len(ps)!=1 or s.GetAtomWithIdx(ps[0]).GetDegree()!=1:raise ValueError('SUBSTITUENT_PORT')
        target=s.GetAtomWithIdx(ps[0]).GetNeighbors()[0].GetIdx()
        rw.AddBond(idx,off+target,Chem.BondType.SINGLE);rw.RemoveAtom(off+ps[0])
    else:rw.AddBond(idx,off,bond)
    return rw.GetMol()


def _parent(kind):
    """Return graph and explicit nomenclature locant -> atom map."""
    if kind in ('benzene','phenylene'):
        return Chem.MolFromSmiles('c1ccccc1'),{str(i+1):i for i in range(6)}
    if kind=='naphthalene':
        rw=Chem.RWMol()
        for _ in range(10):
            a=Chem.Atom('C');a.SetIsAromatic(True);rw.AddAtom(a)
        for i in range(10):rw.AddBond(i,(i+1)%10,Chem.BondType.AROMATIC)
        rw.AddBond(4,9,Chem.BondType.AROMATIC)
        m=rw.GetMol();Chem.SanitizeMol(m)
        return m,{str(i):j for i,j in zip(range(1,9),[0,1,2,3,5,6,7,8])}
    if kind=='biphenyl':
        m=Chem.MolFromSmiles('c1ccccc1-c1ccccc1')
        # Build explicitly so numbered bridge positions 1 and 1' are unambiguous.
        m=Chem.CombineMols(Chem.MolFromSmiles('c1ccccc1'),Chem.MolFromSmiles('c1ccccc1'))
        rw=Chem.RWMol(m);rw.AddBond(0,6,Chem.BondType.SINGLE);m=rw.GetMol();Chem.SanitizeMol(m)
        return m,{**{str(i):i-1 for i in range(1,7)},**{str(i)+"'":i+5 for i in range(1,7)}}
    if kind in ('thiophene','furan','pyrrole','piperazine'):
        s={'thiophene':'s1cccc1','furan':'o1cccc1','pyrrole':'[nH]1cccc1','piperazine':'N1CCNCC1'}[kind]
        m=Chem.MolFromSmiles(s);return m,{str(i+1):i for i in range(m.GetNumAtoms())}
    if kind=='1,3-dioxoisoindoline':
        # 1 acyl C, 2 N, 3 acyl C, 3a aromatic, 4..7 aromatic, 7a aromatic.
        m=Chem.MolFromSmiles('O=C1NC(=O)c2ccccc21')
        return m,{'1':1,'2':2,'3':3,'4':6,'5':7,'6':8,'7':9}
    mat=re.fullmatch(r'(cyclo)?([a-z]+)ane',kind)
    if mat and mat[2] in STEM_N:
        n=STEM_N[mat[2]]
        if mat[1] and not 3<=n<=16:raise ValueError('CYCLE_SIZE_LIMIT')
        s=('C1'+'C'*(n-1)+'1') if mat[1] else 'C'*n
        return Chem.MolFromSmiles(s),{str(i+1):i for i in range(n)}
    from .heterocycles_v09 import ring_parent
    extra=ring_parent(kind)
    if extra:return extra
    raise ValueError('PARENT_OUTSIDE_SCOPE')


def _prefix_groups(prefix):
    """Parse complete locanted substituent prefixes, including multiplicities."""
    if not prefix:return []
    remaining=prefix;out=[]
    names=sorted(GROUPS,key=len,reverse=True)
    # Every successful iteration consumes at least two characters.
    while remaining:
        mat=re.match(r"([0-9]+(?:')?(?:,[0-9]+(?:')?)*)-",remaining)
        if not mat:return None
        locs=mat[1].split(',');rest=remaining[len(mat[0]):];found=None
        for mult in ['',*sorted(MULT,key=len,reverse=True)]:
            if not rest.startswith(mult):continue
            s=rest[len(mult):];needed=1 if not mult else MULT[mult]
            if len(locs)!=needed:continue
            for group in names:
                for token in [group,'('+group+')','['+group+']','{'+group+'}']:
                    if s.startswith(token):
                        tail=s[len(token):]
                        if tail.startswith('-'):tail=tail[1:]
                        # A chemical prefix remainder must start with another locant.
                        if tail and not re.match(r'\d',tail):continue
                        found=(group,tail);break
                if found:break
            if found:break
        if not found:return None
        out.extend((loc,GROUPS[found[0]]) for loc in locs);remaining=found[1]
    return out


def _decorate(m,locants,groups):
    for loc,sub in groups:
        if loc not in locants:raise ValueError('INVALID_LOCANT')
        m=_attach(m,locants[loc],sub)
    Chem.SanitizeMol(m);return m


def _smiles(m):
    Chem.SanitizeMol(m)
    return Chem.MolToSmiles(m,canonical=True,isomericSmiles=True)


def _direct_birings(left,right,a,b):
    rw=Chem.RWMol(Chem.CombineMols(left,right))
    rw.AddBond(a,left.GetNumAtoms()+b,Chem.BondType.SINGLE)
    return _smiles(rw.GetMol())


REFERENCES={
    'carbon monooxide':'[C-]#[O+]', # alternate explicit stoichiometric spelling, raw retained
    'phthalic anhydride':'O=C1OC(=O)c2ccccc21',
    'trifluoronitrosomethane':'O=NC(F)(F)F',
    'maleimide':'O=C1C=CC(=O)N1',
    '1-vinylpyrrolidone':'C=CN1CCCC1=O',
    'triethoxymethane':'CCOC(OCC)OCC',
    'diethyl carbonate':'CCOC(=O)OCC',
    'phenolphthalein':'O=C1OC(c2ccc(O)cc2)(c2ccc(O)cc2)c2ccccc21',
    'isophorone diisocyanate':'CC1(CN=C=O)CC(N=C=O)CC(C)(C)C1',
    '1,8-dihydroxyanthraquinone':'O=C1c2cccc(O)c2C(=O)c2c(O)cccc21',
    'octamethylcyclotetrasiloxane':'C[Si]1(C)O[Si](C)(C)O[Si](C)(C)O[Si](C)(C)O1',
    'decamethylcyclopentasiloxane':'C[Si]1(C)O[Si](C)(C)O[Si](C)(C)O[Si](C)(C)O[Si](C)(C)O1',
    'tetramethylcyclotetrasiloxane':'C[SiH]1O[SiH](C)O[SiH](C)O[SiH](C)O1',
    '(ethylenedioxy)diacetic acid':'O=C(O)COCCOCC(=O)O',
    'ethylene bis(chloroformate)':'O=C(Cl)OCCOC(=O)Cl',
    '2-(N,N-dimethylamino)ethyl methacrylate':'C=C(C)C(=O)OCCN(C)C',
    '2-(dimethylamino)ethyl methacrylate':'C=C(C)C(=O)OCCN(C)C',
    'dimethyl itaconate':'C=C(CC(=O)OC)C(=O)OC',
    'N-(1,1-dimethyl-3-oxobutyl)acrylamide':'C=CC(=O)NC(C)(C)CC(=O)C',
    'oxalyl chloride':'O=C(Cl)C(=O)Cl','oxalyl dichloride':'O=C(Cl)C(=O)Cl',
    'glutaryl dichloride':'O=C(Cl)CCCC(=O)Cl',
    'toluene 2,4-diisocyanate':'Cc1ccc(N=C=O)cc1N=C=O',
    "methylenebis(4,1-phenylene) diisocyanate":'O=C=Nc1ccc(Cc2ccc(N=C=O)cc2)cc1',
    "3,3'-dihydroxybenzidine":'Nc1ccc(-c2ccc(N)c(O)c2)cc1O',
    '3,5,5-trimethyl-3-(isocyanatomethyl)cyclohexyl isocyanate':'CC1(CN=C=O)CC(N=C=O)CC(C)(C)C1',
    '2,2-bis[4-(chlorocarbonyloxy)phenyl]propane':'CC(C)(c1ccc(OC(=O)Cl)cc1)c1ccc(OC(=O)Cl)cc1',
    # COV-01 bounded leaf references.  These are finite molecules whose
    # spelling is complete; polymer family labels (for example
    # ``ethersulfone`` or ``hexamethylene adipamide``) deliberately remain
    # unresolved because they do not identify a unique finite graph.
    '5-ethylidene-2-norbornene':'C=C1C2CCC1C2',
    'isobutene':'C=C(C)C',
    'acetylene':'C#C',
    'acenaphthylene':'C1=CC2=C(C=C1)C1=CC=CC=C21',
    'p-divinylbenzene':'C=Cc1ccc(C=C)cc1',
    'benzene-1,3-disulfonyl dichloride':'ClS(=O)(=O)c1cccc(S(=O)(=O)Cl)c1',
    "3,3'-(ethyne-1,2-diyl)dianiline":'Nc1cccc(C#Cc2cccc(N)c2)c1',
    '1,4-bis[(ethylamino)methyl]benzene':'CCNCc1ccc(CNCC)cc1',
    "2,2'-bis{4-[(oxiran-2-yl)methoxy]phenyl}propane":'CC(C)(c1ccc(OCC2CO2)cc1)c1ccc(OCC2CO2)cc1',
    '4-vinylbenzenesulfonic acid':'C=Cc1ccc(S(=O)(=O)O)cc1',
}


@lru_cache(maxsize=30000)
def resolve_source(raw):
    if not isinstance(raw,str) or len(raw)>1200:return None
    name=raw.replace('\u2032',"'")
    with rdBase.BlockLogs():
        try:
            if name in REFERENCES:return _smiles(Chem.MolFromSmiles(REFERENCES[name])),'NR-EXPLICIT-REFERENCE-CANDIDATE/0.4'
            # A locanted diyl bridge (including substituted heterocycles) is a
            # graph fragment, not a guessed bridge synonym.
            mat=re.fullmatch(r"([2-6]),([2-6])'-(.+)(dianiline|diphenol|dibenzoic acid)",name)
            if mat:
                br=resolve_diyl(_unwrap(mat[3]))
                if br:
                    sub={'dianiline':'N','diphenol':'O','dibenzoic acid':'C(=O)O'}[mat[4]]
                    ring=_ring([(1,sub)])
                    return _bridge_rings(ring,ring,int(mat[1]),int(mat[2]),br),'NR-DYNAMIC-DIYL-AROMATIC-BRIDGE/0.4'
            # Two explicitly locanted phthalic anhydrides, linked without an invented spacer.
            mat=re.fullmatch(r"\[?([4-7]),([4-7])'-biisobenzofuran\]?-1,1',3,3'-(tetraone|tetrone)",name)
            if mat:return _direct_birings(_anhydride_ring(),_anhydride_ring(),int(mat[1])-2,int(mat[2])-2),'NR-BIISOBENZOFURAN/0.4'
            # Colon is the established separator for two adjacent locant
            # pairs on a biphenyl (e.g. ``3,3':4,4'``).  It is structural
            # punctuation, so normalize it only after the full pattern has
            # matched; malformed/spelling variants stay unresolved.
            mat=re.fullmatch(r"biphenyl-([0-9,':]+)-tetracarboxylic dianhydride",name)
            if mat:
                positions=mat[1].replace(':',',').split(',')
                if len(positions)!=4 or len(set(positions))!=4:return None
                m,loc=_parent('biphenyl');rw=Chem.RWMol(m)
                for prime in ('',"'"):
                    ps=[p for p in positions if p.endswith("'")==bool(prime)]
                    if len(ps)!=2 or any(p not in loc for p in ps):return None
                    if not rw.GetBondBetweenAtoms(loc[ps[0]],loc[ps[1]]):return None
                    centers=[]
                    for p in ps:
                        off=rw.GetNumAtoms();mm=_attach(rw.GetMol(),loc[p],'C=O');rw=Chem.RWMol(mm);centers.append(off)
                    j=rw.AddAtom(Chem.Atom('O'))
                    for c in centers:rw.AddBond(c,j,Chem.BondType.SINGLE)
                return _smiles(rw.GetMol()),'NR-BIPHENYL-ADJACENT-DIANHYDRIDE/0.4'
            # Oxy/sulfonyl/other bridge between locanted o-phenylenediamine groups.
            mat=re.fullmatch(r"([3-6]),([3-6])'-(.+)bis\(([omp])-phenylenediamine\)",name)
            if mat and _unwrap(mat[3]) in BRIDGES:
                pos={'o':2,'m':3,'p':4}[mat[4]]
                m=_ring([(1,'N'),(pos,'N')])
                return _bridge_rings(m,m,int(mat[1]),int(mat[2]),BRIDGES[_unwrap(mat[3])]),'NR-BRIDGED-PHENYLENEDIAMINES/0.4'
            mat=re.fullmatch(r"([3-6])-(chloroformyl|chlorocarbonyl) ?phthalic anhydride",name)
            if mat:
                m=_anhydride_ring();m=_attach(m,int(mat[1])-1,'C(=O)Cl')
                return _smiles(m),'NR-ACYL-CHLORIDE-PHTHALIC-ANHYDRIDE/0.4'
            mat=re.fullmatch(r"([23456]),([23456])'-(.+)bis\(cyclohexylamine\)",name)
            if mat and _unwrap(mat[3]) in BRIDGES:
                m,loc=_parent('cyclohexane');m=_decorate(m,loc,[('1','N')])
                return _bridge_rings(m,m,int(mat[1]),int(mat[2]),BRIDGES[_unwrap(mat[3])]),'NR-BRIDGED-CYCLOHEXYLAMINE/0.4'
            mat=re.fullmatch(r'(1,[23456])-phenylenebis\(methyl isocyanate\)',name)
            if mat:
                m,loc=_parent('benzene');return _smiles(_decorate(m,loc,[(p,'CN=C=O') for p in mat[1].split(',')])),'NR-XYLYLENE-DIISOCYANATE/0.4'
            # Preformed imide-containing difunctional sources. 2,2' explicitly
            # labels the two imide nitrogens, not a guessed polymer reaction.
            forms=[r"2,2'-(.+)bis\(1,3-dioxoisoindolin(?:e)?-([4-7])-(carboxylic acid|carbonyl chloride)\)",
                   r"1,1',3,3'-tetraoxo-2,2'-(.+)bis\(isoindolin(?:e)?-([4-7])-(carboxylic acid|carbonyl chloride)\)"]
            for pattern in forms:
                mat=re.fullmatch(pattern,name)
                if not mat:continue
                br=_unwrap(mat[1])
                if br not in BRIDGES:return None
                m,loc=_parent('1,3-dioxoisoindoline');sub='C(=O)O' if mat[3]=='carboxylic acid' else 'C(=O)Cl'
                m=_decorate(m,loc,[(mat[2],sub)])
                return _bridge_rings(m,m,loc['2']+1,loc['2']+1,BRIDGES[br]),'NR-BIS-IMIDE-FUNCTIONAL-SOURCE/0.4'
            # Generic position-bearing parent suffixes (incl. naphthalene and cycloalkane).
            kinds=r'(benzene|naphthalene|biphenyl|cyclo(?:prop|but|pent|hex|hept|oct)ane|(?:meth|eth|prop|but|pent|hex|hept|oct|non|dec|undec|dodec)ane)'
            suffixes={
                'diol':('O',2),'diamine':('N',2),'tetramine':('N',4),'dithiol':('S',2),
                'dicarboxylic acid':('C(=O)O',2),'dicarbohydrazide':('C(=O)NN',2),
                'dimethanol':('CO',2),'diacetic acid':('CC(=O)O',2),
                'bis(methylamine)':('CN',2),'bis(ethylamine)':('CCN',2),
                'bis(methyl isocyanate)':('CN=C=O',2),'dicarbonyl dichloride':('C(=O)Cl',2),
            }
            mat=re.fullmatch(r'(.*?)'+kinds+r"-([0-9,']+)-(.+)",name)
            if mat and mat[4] in suffixes:
                groups=_prefix_groups(mat[1]);ps=mat[3].split(',');sub,n=suffixes[mat[4]]
                if groups is None or len(ps)!=n or len(set(ps))!=n:return None
                m,loc=_parent(mat[2]);m=_decorate(m,loc,[(p,sub) for p in ps]+groups)
                return _smiles(m),'NR-NUMBERED-PARENT-FUNCTIONAL-GROUPS/0.4'
            # Functionally named ring parents accept only fully consumed prefix groups.
            roots={
                'styrene':[(1,'C=C')],'aniline':[(1,'N')],'phenol':[(1,'O')],
                'benzoic acid':[(1,'C(=O)O')],'isophthalic acid':[(1,'C(=O)O'),(3,'C(=O)O')],
                'isophthaloyl dichloride':[(1,'C(=O)Cl'),(3,'C(=O)Cl')],
                'terephthalic acid':[(1,'C(=O)O'),(4,'C(=O)O')],
                'p-phenylenediamine':[(1,'N'),(4,'N')],
                'piperazine':[], 'thiophene':[], 'furan':[], 'benzene':[],
            }
            for root in sorted(roots,key=len,reverse=True):
                if name.endswith(root):
                    pre=name[:-len(root)];groups=_prefix_groups(pre)
                    if groups is None:return None
                    m,loc=_parent(root if root in ('piperazine','thiophene','furan') else 'benzene')
                    groups=[(str(p),s) for p,s in roots[root]]+groups
                    return _smiles(_decorate(m,loc,groups)),'NR-SUBSTITUTED-RING-FUNCTIONAL-PARENT/0.4'
            # Positional alkene spelling variants and arbitrary supported substituent prefixes.
            mat=re.fullmatch(r'(.*?)([a-z]+)-(\d+)-ene',name)
            if not mat:
                mat0=re.fullmatch(r'(.*?)(\d+)-([a-z]+)ene',name)
                if mat0: parts=(mat0[1],mat0[3],mat0[2])
                else:parts=None
            else:parts=(mat[1],mat[2],mat[3])
            if parts and parts[1] in STEM_N:
                groups=_prefix_groups(parts[0]);n=STEM_N[parts[1]];pos=int(parts[2])
                if groups is None or not 1<=pos<n:return None
                m,loc=_parent(parts[1]+'ane');rw=Chem.RWMol(m);rw.GetBondBetweenAtoms(pos-1,pos).SetBondType(Chem.BondType.DOUBLE)
                return _smiles(_decorate(rw.GetMol(),loc,groups)),'NR-LOCANTED-ALKENE-WRITING/0.4'
            # Amino/hydroxy acids; carboxyl C is explicitly position 1.
            mat=re.fullmatch(r'(\d+)-(hydroxy|amino)([a-z]+)anoic acid',name)
            if mat and mat[3] in STEM_N:
                m,loc=_parent(mat[3]+'ane');rw=Chem.RWMol(m)
                oxy=rw.AddAtom(Chem.Atom('O'));rw.AddBond(0,oxy,Chem.BondType.DOUBLE)
                oxy=rw.AddAtom(Chem.Atom('O'));rw.AddBond(0,oxy,Chem.BondType.SINGLE)
                return _smiles(_decorate(rw.GetMol(),loc,[(mat[1],{'hydroxy':'O','amino':'N'}[mat[2]])])),'NR-HYDROXY-AMINO-ACID/0.4'
            if name in ('5-hydroxyvaleric acid','3-hydroxypropionic acid'):
                return resolve_source({'5-hydroxyvaleric acid':'5-hydroxypentanoic acid','3-hydroxypropionic acid':'3-hydroxypropanoic acid'}[name])
            # Hydroxyalkyl arms linked by a named divalent bridge.
            mat=re.fullmatch(r"(\d+),(\d+)'-(.+)di([a-z]+)an(?:-1-)?ol",name)
            if mat and mat[4] in STEM_N:
                n=STEM_N[mat[4]];br=_unwrap(mat[3])
                if int(mat[1])!=n or int(mat[2])!=n or br not in BRIDGES:return None
                bm=Chem.MolFromSmiles(BRIDGES[br]);ps=[a.GetIdx() for a in bm.GetAtoms() if a.GetAtomicNum()==0]
                if len(ps)!=2:return None
                rw=Chem.RWMol(bm)
                for p in ps:
                    # Replace the bridge * with the terminal C of an n-carbon hydroxyalkyl arm.
                    rw.GetAtomWithIdx(p).SetAtomicNum(6)
                    tail=('C'*(n-1)+'O') if n>1 else 'O'
                    rw=Chem.RWMol(_attach(rw.GetMol(),p,tail))
                return _smiles(rw.GetMol()),'NR-HYDROXYALKYL-BRIDGE/0.4'
            # Cycloalkanones, not an inferred ring-opening product.
            mat=re.fullmatch(r'cyclo([a-z]+)anone',name)
            if mat and mat[1] in STEM_N:
                m,_=_parent('cyclo'+mat[1]+'ane');rw=Chem.RWMol(m);o=rw.AddAtom(Chem.Atom('O'));rw.AddBond(0,o,Chem.BondType.DOUBLE)
                return _smiles(rw.GetMol()),'NR-CYCLOALKANONE/0.4'
        except (ValueError,RuntimeError,IndexError,AttributeError):return None
    return None


@lru_cache(maxsize=30000)
def resolve_diyl(raw):
    """Generate one oriented two-port fragment. Map 1/2 preserves locant order."""
    if not isinstance(raw,str) or len(raw)>900:return None
    name=raw.replace('\u2032',"'")
    with rdBase.BlockLogs():
        try:
            # legacy ethylene and phenylene subunit forms are explicit divalent scopes here
            mat=re.fullmatch(r'(.*?)(\d+),(\d+)-phenylene',name)
            if mat:pre,parent,ports=mat[1],'benzene',[mat[2],mat[3]]
            elif name.endswith('ethylene'):
                pre,parent,ports=name[:-len('ethylene')],'ethane',['1','2']
            else:
                roots=r"(1,3-dioxoisoindoline|naphthalene|biphenyl|thiophene|furan|pyrrole|benzene|(?:cyclo)?[a-z]+ane)"
                mat=re.fullmatch(r'(.*?)'+roots+r"-(\d+'?),(\d+'?)-diyl",name)
                if not mat:return None
                pre,parent,ports=mat[1],mat[2],[mat[3],mat[4]]
            groups=_prefix_groups(pre)
            if groups is None:return None
            m,loc=_parent(parent)
            # Carbonyl substituent prefixes need a double bond, not a hydroxyl guess.
            m=_decorate(m,loc,groups)
            rw=Chem.RWMol(m)
            for lab,p in enumerate(ports,1):
                if p not in loc:return None
                a=rw.GetAtomWithIdx(loc[p])
                if a.GetIsAromatic() and a.GetAtomicNum()==7 and a.GetNumExplicitHs():a.SetNumExplicitHs(0)
                dummy=Chem.Atom(0);dummy.SetAtomMapNum(lab);idx=rw.AddAtom(dummy)
                rw.AddBond(loc[p],idx,Chem.BondType.SINGLE)
            return _smiles(rw.GetMol())
        except (ValueError,RuntimeError,IndexError,AttributeError):return None
    return None


def name_diagnostic(raw):
    """Non-executing repair proposals. No repaired candidate enters identity keys."""
    if not isinstance(raw,str):return None
    proposals=[]
    substitutions=[('bipheny-','biphenyl-'),('dicarbnyl','dicarbonyl'),('hydoxymethyl','hydroxymethyl'),('4,4,-hexafluoro','4,4-hexafluoro')]
    for wrong,right in substitutions:
        if wrong in raw:proposals.append({'proposed_text':raw.replace(wrong,right),'change':wrong+' -> '+right})
    if proposals:return {'status':'NEEDS_DETAILS','reason_code':'SPELLING_REPAIR_REQUIRES_REVIEW','repair_proposals':proposals,'applied':False}
    if raw in ('dichlorostyrene','chlorostyrene','methylsiloxane','caprolactone diol','hydrogenated polybutadiene'):
        return {'status':'NEEDS_DETAILS','reason_code':'LOCANTS_OR_POLYMER_SPECIFICATION_MISSING','applied':False}
    if 'tetracarboxylic anhydride' in raw or ('tetracarboxylic dianhydride' in raw and ':' in raw):
        return {'status':'NEEDS_DETAILS','reason_code':'ANHYDRIDE_CLOSURE_OR_NAMING_VARIANT_REQUIRES_EVIDENCE','applied':False}
    return None

# Explicitly numbered naphthalene dioxy bridges. No 1,5/2,6 collapse.
for _a in range(1,9):
    for _b in range(1,9):
        if _a==_b:continue
        _m,_loc=_parent('naphthalene');_rw=Chem.RWMol(_m)
        for _label,_p in enumerate((_a,_b),1):
            _o=_rw.AddAtom(Chem.Atom('O'));_rw.AddBond(_loc[str(_p)],_o,Chem.BondType.SINGLE)
            _star=Chem.Atom(0);_star.SetAtomMapNum(_label);_j=_rw.AddAtom(_star);_rw.AddBond(_o,_j,Chem.BondType.SINGLE)
        BRIDGES[f'naphthalene-{_a},{_b}-diyldioxy']=_smiles(_rw.GetMol())

BRIDGES.update({
 'oxydi(4,1-phenylene)':'*c1ccc(Oc2ccc(*)cc2)cc1',
 'methylenedi(4,1-phenylene)':'*c1ccc(Cc2ccc(*)cc2)cc1',
 'sulfonyldi(4,1-phenylene)':'*c1ccc(S(=O)(=O)c2ccc(*)cc2)cc1',
})
from .periodic import assemble as _assemble_bridge
for _a in range(1,9):
    for _b in range(1,9):
        if _a==_b:continue
        _dioxy=BRIDGES[f'naphthalene-{_a},{_b}-diyldioxy']
        BRIDGES[f'naphthalene-{_a},{_b}-diylbis(oxy-4,1-phenylene)']=_assemble_bridge(['*c1ccc(*)cc1',_dioxy,'*c1ccc(*)cc1'])
