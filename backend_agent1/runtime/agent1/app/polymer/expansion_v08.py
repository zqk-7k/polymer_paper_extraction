"""Complete-consumption, bounded rooted-fragment grammar (candidate only).

Fallback only: existing 0.7 resolutions take priority. No input repair, catalog
identifiers, formulas, sample data or test expectations participate in parsing.
Molecular sources and explicitly divalent constitutional units are distinct.
"""
from __future__ import annotations
import re
from functools import lru_cache
from rdkit import Chem, rdBase
from .advanced_names import rooted as old_rooted, balanced_end, port, connect, smi
from .queue_rules import _parent, _unwrap, GROUPS, MULT, name_diagnostic
from .name_rules import STEM_N

NAMES = {**STEM_N, 'icos':20, 'henicos':21, 'docos':22, 'tricos':23,
         'tetracos':24, 'pentacos':25, 'hexacos':26, 'triacont':30}
MULTS = {**MULT, 'hepta':7,'octa':8,'nona':9,'deca':10}
PAIRS={'(':')','[':']','{':'}'}
GROUPS_NEW = {
 'sulfo':'*S(=O)(=O)O','sulfamoyl':'*S(=O)(=O)N',
 'sulfonato':'*S(=O)(=O)[O-]','carboxylato':'*C(=O)[O-]',
 'formyl':'*C=O','acetyl':'*C(=O)C','acryloyl':'*C(=O)C=C',
 'methacryloyl':'*C(=O)C(=C)C', 'acryloyloxy':'*OC(=O)C=C',
 'methacryloyloxy':'*OC(=O)C(=C)C','benzoyloxy':'*OC(=O)c1ccccc1',
 'benzyloxy':'*OCc1ccccc1','methylsulfonyl':'*S(=O)(=O)C',
 'ethylsulfonyl':'*S(=O)(=O)CC','phenylsulfonyl':'*S(=O)(=O)c1ccccc1',
 'phenylsulfanyl':'*Sc1ccccc1','phenylthio':'*Sc1ccccc1',
 'trimethylsilyl':'*[Si](C)(C)C','dimethylphosphoryl':'*P(=O)(C)C',
 'diethoxyphosphoryl':'*P(=O)(OCC)OCC','dimethoxyphosphoryl':'*P(=O)(OC)OC',
 'isopropyl':'*C(C)C','isobutyl':'*CC(C)C','sec-butyl':'*C(C)CC',
 'tert-butyl':'*C(C)(C)C', 'cyclohexyl':'*C1CCCCC1',
}
RULE='NR-ROOTED-COMPOSITION/0.8'

def _safe(s):
 return isinstance(s,str) and 0<len(s)<=1200 and '--' not in s and not re.search(r'\^|λ|lambda|lamda|(?:^|\W)(?:R|S|E|Z)(?:\W|$)|cis-|trans-|isotactic|syndiotactic',s)

def rooted_form(fragment):
 """Convert an old root-at-first-atom fragment into one explicit port."""
 m=Chem.MolFromSmiles(fragment[1:] if fragment.startswith('=') else fragment)
 if not m:return None
 ps=[a.GetIdx() for a in m.GetAtoms() if a.GetAtomicNum()==0]
 if ps:return fragment if len(ps)==1 and m.GetAtomWithIdx(ps[0]).GetDegree()==1 else None
 return smi(port(m,0,bond=Chem.BondType.DOUBLE if fragment.startswith('=') else Chem.BondType.SINGLE))

def flip(fragment):
 m=Chem.MolFromSmiles(fragment)
 for a in m.GetAtoms():
  if a.GetAtomicNum()==0 and a.GetAtomMapNum() in (1,2):a.SetAtomMapNum(3-a.GetAtomMapNum())
 return smi(m)

def join(parts):
 """Join oriented 1/2 port fragments, without a periodic-graph assumption."""
 if not parts or len(parts)>64:raise ValueError('FRAGMENT_COUNT_LIMIT')
 def indexed(s):
  m=Chem.MolFromSmiles(s)
  if not m:raise ValueError('INVALID_FRAGMENT')
  ps=[a for a in m.GetAtoms() if a.GetAtomicNum()==0]
  if len(ps)!=2 or any(a.GetDegree()!=1 for a in ps):raise ValueError('TWO_TERMINAL_PORTS_REQUIRED')
  labs={a.GetAtomMapNum() for a in ps}
  if labs!={1,2}:
   if labs!={0}:raise ValueError('INVALID_PORT_LABELS')
   for i,a in enumerate(ps,1):a.SetAtomMapNum(i)
  return m
 m=indexed(parts[0])
 for s in parts[1:]:
  n=indexed(s); a=next(a for a in m.GetAtoms() if a.GetAtomicNum()==0 and a.GetAtomMapNum()==2)
  b=next(a for a in n.GetAtoms() if a.GetAtomicNum()==0 and a.GetAtomMapNum()==1)
  if a.GetBonds()[0].GetBondType()!=b.GetBonds()[0].GetBondType():raise ValueError('PORT_BOND_MISMATCH')
  off=m.GetNumAtoms();rw=Chem.RWMol(Chem.CombineMols(m,n))
  rw.AddBond(a.GetNeighbors()[0].GetIdx(),off+b.GetNeighbors()[0].GetIdx(),a.GetBonds()[0].GetBondType())
  for idx in sorted([a.GetIdx(),off+b.GetIdx()],reverse=True):rw.RemoveAtom(idx)
  m=rw.GetMol();Chem.SanitizeMol(m)
  if m.GetNumAtoms()>600:raise ValueError('ATOM_LIMIT')
 return smi(m)

def substitute(m,loc,items):
 if items is None:return None
 for p,f in items:
  if p not in loc:return None
  m=connect(m,loc[p],f)
 Chem.SanitizeMol(m);return m

@lru_cache(maxsize=60000)
def prefixes(s,depth=0):
 if depth>10:return None
 if s.endswith('-'):s=s[:-1]
 if not s:return ()
 mat=re.match(r"([0-9]+(?:')?(?:,[0-9]+(?:')?)*)-",s)
 if not mat:return None
 locs=mat[1].split(',');tail=s[len(mat[0]):]
 for prefix,count in [('',1),*sorted(MULTS.items(),key=lambda x:-len(x[0]))]:
  if len(locs)!=count or not tail.startswith(prefix):continue
  body=tail[len(prefix):];ends=[len(body)];stack=[]
  for i,c in enumerate(body):
   if c in PAIRS:stack.append(c)
   elif c in PAIRS.values():
    if not stack or PAIRS[stack.pop()]!=c:return None
   if not stack and c=='-' and i+1<len(body) and body[i+1].isdigit():ends.append(i)
  if stack:return None
  for end in sorted(set(ends)):
   f=rooted(_unwrap(body[:end]),depth+1)
   if not f:continue
   rest=prefixes(body[end+1:] if end<len(body) else '',depth+1)
   if rest is not None:return tuple((p,f) for p in locs)+rest
 return None

@lru_cache(maxsize=60000)
def rooted(s,depth=0):
 if depth>10 or not _safe(s):return None
 s=_unwrap(s)
 with rdBase.BlockLogs():
  try:
   old=old_rooted(s)
   if old:return rooted_form(old)
   if s in GROUPS_NEW:return GROUPS_NEW[s]
   # Suffix linkers are rooted on the named functional group, never on an
   # arbitrary canonical SMILES first atom.
   for suffix,link,target in [('carbonyloxy','*OC(=O)',2),('oxycarbonyl','*C(=O)O',3),
       ('sulfonyloxy','*OS(=O)(=O)',2),('sulfonyl','*S(=O)(=O)',1),('sulfinyl','*S(=O)',1),
       ('carbonyl','*C(=O)',1),('sulfanyl','*S',1),('thio','*S',1),('oxy','*O',1)]:
    if s.endswith(suffix) and len(s)>len(suffix):
     f=rooted(_unwrap(s[:-len(suffix)]),depth+1)
     if f:
      lm=Chem.MolFromSmiles(link);return smi(connect(lm,target,f))
   for suffix,base in [('benzoyl','benzene'),('benzyl','benzene'),('phenoxy','benzene'),('phenyl','benzene')]:
    if s.endswith(suffix):
     pre=s[:-len(suffix)]; locpre=prefixes(pre,depth+1)
     if locpre is None:continue
     m,loc=_parent(base);m=substitute(m,loc,locpre)
     if not m:return None
     ar=smi(port(m,0))
     link={'benzoyl':'*C(=O)','benzyl':'*C','phenoxy':'*O','phenyl':None}[suffix]
     return smi(connect(Chem.MolFromSmiles(link),1,ar)) if link else ar
   # Explicitly locanted saturated alkyl and alkenyl roots.
   mat=re.fullmatch(r'(.*?)('+ '|'.join(sorted(NAMES,key=len,reverse=True)) +r')(?:an-(\d+)-yl|-(\d+)-en-(\d+)-yl)',s)
   if mat:
    pre,stem,a,double,b=mat.groups();n=NAMES[stem];a=int(a or b)
    if not 1<=a<=n:return None
    rw=Chem.RWMol(Chem.MolFromSmiles('C'*n))
    if double:
     p=int(double)
     if not 1<=p<n:return None
     rw.GetBondBetweenAtoms(p-1,p).SetBondType(Chem.BondType.DOUBLE)
    m=substitute(rw.GetMol(),{str(i+1):i for i in range(n)},prefixes(pre,depth+1))
    if m:return smi(port(m,a-1))
   for stem,n in sorted(NAMES.items(),key=lambda x:-len(x[0])):
    for suffix,link in [(stem+'yl',None),(stem+'oxy','*O')]:
     if s.endswith(suffix):
      pre=s[:-len(suffix)];m=substitute(Chem.MolFromSmiles('C'*n),{str(i+1):i for i in range(n)},prefixes(pre,depth+1))
      if m:
       rt=smi(port(m,0));return smi(connect(Chem.MolFromSmiles(link),1,rt)) if link else rt
   # A bracketed substituent attached to methylene/methoxy.
   for suffix,base,target in [('methyl','*C',1),('methoxy','*OC',2)]:
    if s.endswith(suffix):
     pre=s[:-len(suffix)]
     if pre:
      f=rooted(_unwrap(pre),depth+1)
      if f:return smi(connect(Chem.MolFromSmiles(base),target,f))
   # Nitrogen substitutions: explicit one/two rooted groups on amino N.
   if s.endswith('amino'):
    subs=substituent_list(s[:-5],depth+1,max_count=2)
    if subs and len(subs)<=2:
     m=Chem.MolFromSmiles('*N')
     for f in subs:m=connect(m,1,f)
     return smi(m)
  except (ValueError,RuntimeError,IndexError,KeyError,AttributeError):return None
 from .heterocycles_v09 import rooted_extension
 return rooted_extension(s,depth+1)

def substituent_list(s,depth=0,max_count=3):
 if depth>10 or not s:return None
 # Explicit multiplicative brackets or simple identical substituents.
 for prefix,count in [('bis',2),('tris',3),('di',2),('tri',3)]:
  if count<=max_count and s.startswith(prefix):
   f=rooted(_unwrap(s[len(prefix):]),depth+1)
   if f:return [f]*count
 # At a named divalent center, adjacent simple substituents are separate
 # groups: ethylmethylmethylene is C(ethyl)(methyl), not C(propyl)H.
 simple={stem+'yl' for stem in NAMES}|{'phenyl','benzyl','isopropyl','isobutyl','tert-butyl'}
 pairs=[(a,s[len(a):]) for a in sorted(simple) if s.startswith(a) and s[len(a):] in simple]
 if pairs and max_count>=2:
  distinct={tuple(sorted(pair)) for pair in pairs}
  if len(distinct)!=1:return None
  a,b=next(iter(distinct));fa,fb=rooted(a,depth+1),rooted(b,depth+1)
  if fa and fb:return [fa,fb]
 one=rooted(_unwrap(s),depth+1)
 if one:return [one]
 if s[0] in PAIRS:
  end=balanced_end(s)
  if end and end<len(s):
   first=rooted(_unwrap(s[:end]),depth+1);rest=substituent_list(s[end:].lstrip('-'),depth+1,max_count-1)
   if first and rest:return [first]+rest
 for i,c in enumerate(s):
  if i and c in PAIRS:
   first=rooted(s[:i].rstrip('-'),depth+1);rest=substituent_list(s[i:],depth+1,max_count-1)
   if first and rest:return [first]+rest
 return None

@lru_cache(maxsize=60000)
def divalent(s,depth=0):
 if depth>10 or not _safe(s):return None
 s=_unwrap(s)
 with rdBase.BlockLogs():
  try:
   # Preserve the existing interpretation whenever available.
   from .queue_rules import resolve_diyl
   from .advanced_names import resolve_diyl_v05
   from .units import TOKENS
   if s in TOKENS:return join([TOKENS[s]])
   old=resolve_diyl(s) or resolve_diyl_v05(s)
   if old:return old
   if s.endswith('imino'):
    sub=rooted(_unwrap(s[:-5]),depth+1)
    if sub:return smi(connect(Chem.MolFromSmiles('[*:1]N[*:2]'),1,sub))
   # Two explicit substituents on a tetravalent Si atom; no guessed hydrides.
   if s.endswith('silanediyl'):
    subs=substituent_list(s[:-10],depth+1,max_count=2)
    if subs and len(subs)==2:
     m=Chem.MolFromSmiles('[*:1][SiH2][*:2]');m.GetAtomWithIdx(1).SetNumExplicitHs(0)
     for f in subs:m=connect(m,1,f)
     return smi(m)
   if s.endswith('methylene'):
    subs=substituent_list(s[:-9],depth+1,max_count=2)
    if subs and len(subs)<=2:
     m=Chem.MolFromSmiles('[*:1]C[*:2]')
     for f in subs:m=connect(m,1,f)
     return smi(m)
   parent=None;pre=None;ports=None
   if s.endswith('ethylene'):pre,parent,ports=s[:-8],'ethane',['1','2']
   else:
    mat=re.fullmatch(r'(.*?)([1-6]),([1-6])-phenylene',s)
    if mat:pre,parent,ports=mat[1],'benzene',[mat[2],mat[3]]
    else:
     mat=re.fullmatch(r"(.*?)(benzene|biphenyl|naphthalene|thiophene|furan|pyrrole|1,3-dioxoisoindoline|(?:cyclo)?[a-z]+ane)-(\d+'?),(\d+'?)-diyl",s)
     if mat:pre,parent,ports=mat[1],mat[2],[mat[3],mat[4]]
   if parent:
    if parent.endswith('ane') and parent[:-3] in NAMES:
     n=NAMES[parent[:-3]];m=Chem.MolFromSmiles('C'*n);loc={str(i+1):i for i in range(n)}
    else:m,loc=_parent(parent)
    m=substitute(m,loc,prefixes(pre,depth+1))
    if m and all(p in loc for p in ports):return smi(port(port(m,loc[ports[0]],1),loc[ports[1]],2))
   # Locanted ring substituents on the three phthaloyl forms.
   for suffix,ps in [('terephthaloyl',(1,4)),('isophthaloyl',(1,3)),('phthaloyl',(1,2))]:
    if s.endswith(suffix):
     m,loc=_parent('benzene');m=substitute(m,loc,prefixes(s[:-len(suffix)],depth+1))
     if m:
      for lab,p in enumerate(ps,1):
       off=m.GetNumAtoms();m=connect(m,loc[str(p)],'C=O');m=port(m,off,lab)
      return smi(m)
   # Explicit saturated/unsaturated dioyl segments.
   mat=re.fullmatch(r'(.*?)('+ '|'.join(sorted(NAMES,key=len,reverse=True)) +r')(?:anedioyl|-(\d+)-enedioyl)',s)
   if mat:
    pre,stem,p=mat.groups();n=NAMES[stem]
    if n<2:return None
    m=Chem.MolFromSmiles('C'*n);rw=Chem.RWMol(m)
    if p:
     p=int(p)
     if not 1<p<n-1:return None
     rw.GetBondBetweenAtoms(p-1,p).SetBondType(Chem.BondType.DOUBLE)
    m=substitute(rw.GetMol(),{str(i+1):i for i in range(n)},prefixes(pre,depth+1))
    if m:
     m=connect(m,0,'=O');m=connect(m,n-1,'=O');return smi(port(port(m,0,1),n-1,2))
   # Multiplicative bridge: the first atom of each arm is adjacent to the central segment.
   # This is a divalent expression, not a source-pool enumeration.
   stack=[]
   for i in range(len(s)-3):
    c=s[i]
    if c in PAIRS:stack.append(c)
    elif c in PAIRS.values():
     if not stack or PAIRS[stack.pop()]!=c:return None
    if not stack and s.startswith('bis',i) and i>0 and i+3<len(s) and s[i+3] in PAIRS:
     end=balanced_end(s,i+3)
     if end==len(s):
      center=divalent(s[:i],depth+1);arm=sequence(_unwrap(s[i+3:]),depth+1)
      if center and arm:return join([flip(arm),center,arm])
  except (ValueError,RuntimeError,IndexError,KeyError,AttributeError):return None
 from .heterocycles_v09 import divalent_extension
 return divalent_extension(s,depth+1)

@lru_cache(maxsize=60000)
def sequence(s,depth=0):
 if depth>10 or not _safe(s):return None
 s=_unwrap(s)
 direct=divalent(s,depth+1)
 if direct:return direct
 stack=[];cuts=[]
 for i,c in enumerate(s):
  if c in PAIRS:stack.append(c)
  elif c in PAIRS.values():
   if not stack or PAIRS[stack.pop()]!=c:return None
  if not stack and (c in PAIRS.values() or c=='-'):cuts.append(i+1 if c!='-' else i)
 if stack:return None
 # Named divalent suffixes, never arbitrary character boundaries.
 for m in re.finditer(r'(?:phenylene|ethylene|methylene|silanediyl|enedioyl|anedioyl|phthaloyl|diyl|imino|carbonyl|sulfonyl|sulfinyl|oxy|thio)',s):
  if not any(a<m.end()<b for a,b in _bracket_spans(s)):cuts.append(m.end())
 for end in sorted(set(cuts),reverse=True)[:100]:
  if not 0<end<len(s):continue
  head=s[:end].rstrip('-');tail=s[end:]
  if tail.startswith('-'):tail=tail[1:]
  if not tail:continue
  first=divalent(_unwrap(head),depth+1)
  if not first and head and head[0] in PAIRS and balanced_end(head)==len(head):first=sequence(_unwrap(head),depth+1)
  if first:
   rest=sequence(tail,depth+1)
   if rest:
    try:return join([first,rest])
    except (ValueError,RuntimeError):pass
 return None

def _bracket_spans(s):
 out=[];stack=[]
 for i,c in enumerate(s):
  if c in PAIRS:stack.append(i)
  elif c in PAIRS.values() and stack:out.append((stack.pop(),i+1))
 return out

@lru_cache(maxsize=60000)
def source(s):
 if not _safe(s) or name_diagnostic(s):return None
 with rdBase.BlockLogs():
  try:
   # Existing aryl/alkane parents with full recursive prefixes.
   for suffix,base,fg in [('benzoic acid','benzene','*C(=O)O'),('aniline','benzene','*N'),('phenol','benzene','*O'),('styrene','benzene','*C=C')]:
    if s.endswith(suffix):
     m,loc=_parent(base);m=substitute(m,loc,prefixes(s[:-len(suffix)]))
     if m:return smi(connect(m,0,fg)),RULE+'-SOURCE'
   mat=re.fullmatch(r"(.*?)(benzene|biphenyl|naphthalene|(?:cyclo)?[a-z]+ane)-([0-9,']+)-(diamine|diol|dithiol|dicarboxylic acid)",s)
   if mat:
    pre,parent,locs,suffix=mat.groups();ps=locs.split(',')
    if len(ps)!=2 or len(set(ps))!=2:return None
    m,loc=_parent(parent);items=prefixes(pre)
    if items is not None:
     fg={'diamine':'*N','diol':'*O','dithiol':'*S','dicarboxylic acid':'*C(=O)O'}[suffix]
     m=substitute(m,loc,list(items)+[(p,fg) for p in ps])
     if m:return smi(m),RULE+'-FUNCTIONAL'
   # Saturated long-chain dicarboxylic acids.
   mat=re.fullmatch(r'('+ '|'.join(NAMES)+r')anedioic acid',s)
   if mat and NAMES[mat[1]]>=2:
    n=NAMES[mat[1]];return 'O=C(O)'+'C'*(n-2)+'C(=O)O',RULE+'-DIACID'
   # Explicit source bridge with locally numbered two-ring substituents.
   mat=re.fullmatch(r"([2-6]),([2-6])'-(.+?)(dianiline|diphenol|dibenzoic acid)",s)
   if mat:
    a,b,br,suffix=mat.groups();bridge=sequence(_unwrap(br))
    if bridge:
     ring1,loc=_parent('benzene');ring1=connect(ring1,0,{'dianiline':'*N','diphenol':'*O','dibenzoic acid':'*C(=O)O'}[suffix]);left=smi(port(ring1,int(a)-1))
     ring2,loc=_parent('benzene');ring2=connect(ring2,0,{'dianiline':'*N','diphenol':'*O','dibenzoic acid':'*C(=O)O'}[suffix]);right=smi(port(ring2,int(b)-1))
     m=Chem.MolFromSmiles(bridge);ps={x.GetAtomMapNum():x.GetIdx() for x in m.GetAtoms() if x.GetAtomicNum()==0}
     targets=[m.GetAtomWithIdx(ps[lab]).GetNeighbors()[0].GetIdx() for lab in (1,2)]
     m=connect(m,targets[0],left);m=connect(m,targets[1],right);rw=Chem.RWMol(m)
     for idx in sorted(ps.values(),reverse=True):rw.RemoveAtom(idx)
     return smi(rw.GetMol()),RULE+'-BRIDGE'
   # Ester naming uses an explicitly rooted alcohol moiety, no methyl default.
   for suffix,acyl in [(' methacrylate','*C(=O)C(=C)C'),(' acrylate','*C(=O)C=C')]:
    if s.endswith(suffix):
     f=rooted(s[:-len(suffix)])
     if f:
      m=connect(Chem.MolFromSmiles('O'),0,acyl);return smi(connect(m,0,f)),RULE+'-ESTER'
  except (ValueError,RuntimeError,IndexError,KeyError,AttributeError):return None
 return None
