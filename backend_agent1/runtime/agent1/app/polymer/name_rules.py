"""Bounded, compositional fallback. Outputs are RULE_DERIVED_CANDIDATE, not gold.
Only the exact grammars below are implemented; arbitrary organic names go to
an explicitly configured OPSIN provider, otherwise remain unresolved.
"""
import re
from rdkit import Chem
STEMS=['','meth','eth','prop','but','pent','hex','hept','oct','non','dec','undec','dodec','tridec','tetradec','pentadec','hexadec','heptadec','octadec','nonadec','eicos']
STEM_N={v:i for i,v in enumerate(STEMS) if v}
ALKYL={s+'yl':'C'*i for s,i in STEM_N.items()}
ALKYL.update({'isopropyl':'C(C)C','propan-2-yl':'C(C)C','isobutyl':'CC(C)C','tert-butyl':'C(C)(C)C','butan-2-yl':'C(C)CC','sec-butyl':'C(C)CC','benzyl':'Cc1ccccc1','phenyl':'c1ccccc1','cyclohexyl':'C1CCCCC1','2-ethylhexyl':'CC(CC)CCCC','2-hydroxyethyl':'CCO','2-methoxyethyl':'CCOC'})
# Independently review these proposed bindings before accepting names as verified.
EXTRA=[
(['butadiene'],'C=CC=C'),(['vinyl alcohol','ethenol'],'C=CO'),(['1-phenylethylene'],'C=Cc1ccccc1'),
(['terephthaloyl dichloride','terephthaloyl chloride'],'O=C(Cl)c1ccc(C(=O)Cl)cc1'),
(['isophthaloyl dichloride','isophthaloyl chloride'],'O=C(Cl)c1cccc(C(=O)Cl)c1'),
(["4,4'-oxydianiline"],'Nc1ccc(Oc2ccc(N)cc2)cc1'),
(["4,4'-methylenedianiline"],'Nc1ccc(Cc2ccc(N)cc2)cc1'),
(["4,4'-methylenebis(phenyl isocyanate)"],'O=C=Nc1ccc(Cc2ccc(N=C=O)cc2)cc1'),
(['phosgene','carbonyl dichloride'],'O=C(Cl)Cl'),
(['p-phenylenediamine','benzene-1,4-diamine'],'Nc1ccc(N)cc1'),
(['m-phenylenediamine','benzene-1,3-diamine'],'Nc1cccc(N)c1'),
(['o-phenylenediamine','benzene-1,2-diamine'],'Nc1ccccc1N'),
(['hydroquinone','benzene-1,4-diol'],'Oc1ccc(O)cc1'),
(['resorcinol','benzene-1,3-diol'],'Oc1cccc(O)c1'),(['catechol','benzene-1,2-diol'],'Oc1ccccc1O'),
(["biphenyl-4,4'-diol"],'Oc1ccc(-c2ccc(O)cc2)cc1'),
(["4,4'-(1-methylethane-1,1-diyl)diphenol"],'CC(C)(c1ccc(O)cc1)c1ccc(O)cc1'),
(['aniline','benzenamine'],'Nc1ccccc1'),(['phenol'],'Oc1ccccc1'),
(['maleic anhydride','furan-2,5-dione'],'O=C1OC(=O)C=C1'),
(['hexano-6-lactam','caprolactam'],'O=C1CCCCCN1'),
(['hexano-6-lactone','caprolactone'],'O=C1CCCCCO1'),
(['4-methyl-1,3-phenylene diisocyanate','2,4-toluene diisocyanate'],'Cc1ccc(N=C=O)cc1N=C=O'),
(["4,4'-difluorobenzophenone"],'O=C(c1ccc(F)cc1)c1ccc(F)cc1'),
(['diethylene glycol','2,2\'-oxydiethanol'],'OCCOCCO'),
(['triethylene glycol'],'OCCOCCOCCO'),
(['pyromellitic dianhydride','pyromellitic anhydride'],'O=C1OC(=O)c2cc3c(cc12)C(=O)OC3=O'),
(['piperazine'],'N1CCNCC1'),(['1-vinyl-2-pyrrolidone','N-vinylpyrrolidone'],'C=CN1CCCC1=O'),
(['4-vinylphenol'],'C=Cc1ccc(O)cc1'),(['4-methylstyrene','p-methylstyrene'],'C=Cc1ccc(C)cc1'),
(['3-methylstyrene','m-methylstyrene'],'C=Cc1cccc(C)c1'),(['2-methylstyrene','o-methylstyrene'],'C=Cc1ccccc1C'),
(['alpha-methylstyrene','2-phenylprop-1-ene'],'C=C(C)c1ccccc1'),
(['vinylidene fluoride','1,1-difluoroethene'],'C=C(F)F'),(['vinyl bromide','bromoethene'],'C=CBr'),
(['chlorostyrene'],None), # intentionally unresolved isomer family
(['dimethyl terephthalate'],'COC(=O)c1ccc(C(=O)OC)cc1'),
(['dimethyl isophthalate'],'COC(=O)c1cccc(C(=O)OC)c1'),
(['malonic acid','propanedioic acid'],'O=C(O)CC(=O)O'),
(['glutaric acid','pentanedioic acid'],'O=C(O)CCCC(=O)O'),
(['sebacic acid','decanedioic acid'],'O=C(O)CCCCCCCCC(=O)O'),
(['fumaric acid'],'O=C(O)/C=C/C(=O)O'),(['maleic acid'],'O=C(O)/C=C\\C(=O)O'),
(['2-hydroxyethyl methacrylate'],'C=C(C)C(=O)OCCO'),
(['glycidyl methacrylate'],'C=C(C)C(=O)OCC1CO1'),
(['N-isopropylacrylamide'],'C=CC(=O)NC(C)C'),
(['N,N-dimethylacrylamide'],'C=CC(=O)N(C)C'),
(['vinyl benzoate'],'C=COC(=O)c1ccccc1'),
(['oxetane'],'C1COC1'),(['oxepane'],'C1CCCCCO1'),
(['2,5-furandicarboxylic acid'],'O=C(O)c1ccc(C(=O)O)o1'),
(['4-hydroxybenzoic acid'],'O=C(O)c1ccc(O)cc1'),
(['4-aminobenzoic acid'],'O=C(O)c1ccc(N)cc1'),
]

def _chain(n,doubles=(),subs=()):
    r=Chem.RWMol(Chem.MolFromSmiles('C'*n))
    for p in doubles:
        if not 1<=p<n:return None
        r.GetBondBetweenAtoms(p-1,p).SetBondType(Chem.BondType.DOUBLE)
    for pos,sub in subs:
        if not 1<=pos<=n:return None
        m=Chem.MolFromSmiles(sub);off=r.GetNumAtoms();r=Chem.RWMol(Chem.CombineMols(r.GetMol(),m));r.AddBond(pos-1,off,Chem.BondType.SINGLE)
    try:m=r.GetMol();Chem.SanitizeMol(m);return Chem.MolToSmiles(m)
    except (ValueError,RuntimeError):return None

def systematic(name):
    if len(name)>250 or not re.fullmatch(r'[a-z0-9 ,()\-]+',name):return None
    # Fully matched n-alkyl ester names, no guessed abbreviation expansion.
    for suffix,acid in [(' methacrylate','C=C(C)C(=O)O'),(' acrylate','C=CC(=O)O'),(' 2-methylprop-2-enoate','C=C(C)C(=O)O'),(' prop-2-enoate','C=CC(=O)O')]:
        if name.endswith(suffix):
            alk=name[:-len(suffix)]
            if alk.startswith('n-'):alk=alk[2:]
            if alk in ALKYL:return acid+ALKYL[alk],'NR-ALKYL-ESTER'
    if name.endswith(' vinyl ether'):
        alk=name[:-12]
        if alk in ALKYL:return 'C=CO'+ALKYL[alk],'NR-VINYL-ETHER'
    for stem,n in STEM_N.items():
        if n>=2 and name in (stem+'anedioic acid',):return 'O=C(O)'+'C'*(n-2)+'C(=O)O','NR-DIACID'
        if name==stem+'ane':return 'C'*n,'NR-ALKANE'
        if n>=2 and name in (stem+'ane-1,'+str(n)+'-diol','1,'+str(n)+'-'+stem+'anediol'):return 'O'+'C'*n+'O','NR-ALPHA-OMEGA-DIOL'
        if n>=2 and name in (stem+'ane-1,'+str(n)+'-diamine','1,'+str(n)+'-'+stem+'anediamine'):return 'N'+'C'*n+'N','NR-ALPHA-OMEGA-DIAMINE'
        for p in range(1,n):
            if name in (stem+'-'+str(p)+'-ene',str(p)+'-'+stem+'ene'):
                return _chain(n,[p]),'NR-ALKENE-LOCANT'
        m=re.fullmatch(r'(\d+)-(methyl|ethyl|fluoro|chloro|bromo)'+stem+r'-(\d+)-ene',name)
        if m:
            s=_chain(n,[int(m[3])],[(int(m[1]),{'methyl':'C','ethyl':'CC','fluoro':'F','chloro':'Cl','bromo':'Br'}[m[2]])]);return (s,'NR-SUBSTITUTED-ALKENE') if s else None
    m=re.fullmatch(r'(\d+)-(fluoro|chloro|bromo|methyl)styrene',name)
    if m and int(m[1]) in [2,3,4]:
        base=Chem.MolFromSmiles('C=Cc1ccccc1');r=Chem.RWMol(base);atom={'fluoro':'F','chloro':'Cl','bromo':'Br','methyl':'C'}[m[2]];idx=r.AddAtom(Chem.Atom(atom));r.AddBond(1+int(m[1]),idx,Chem.BondType.SINGLE);return Chem.MolToSmiles(r),'NR-RING-LOCANT'
    return None
