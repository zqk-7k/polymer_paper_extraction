"""Bounded graph -> name candidates, independent of input names and catalog rows.

Only complete graph matches survive. Round trips are consistency checks, NOT
independent chemistry or preferred-IUPAC certification. Old name policies remain
unchanged. Unspecified stereo is never silently turned into specified stereo.
"""
from __future__ import annotations
from collections import defaultdict
from functools import lru_cache
import re
from rdkit import Chem, rdBase
from .common import fail, key
from .chemistry import canonicalize
from .periodic import port_mol, split_blocks, assemble, reverse_unit, canonicalize_unit
from .expansion_v08 import rooted, divalent, GROUPS_NEW, NAMES, connect, smi
from .queue_rules import GROUPS, _parent
from .units import TOKENS, resolve_unit

PROFILE = 'graph-derived-naming-candidate/0.9.0'
_STEMS = {v:k for k,v in NAMES.items()}
_STEMS.update({1:'meth',2:'eth',3:'prop',4:'but',20:'icos'})
_SIMPLE = {'fluoro','chloro','bromo','iodo','hydroxy','amino','nitro','cyano',
           'methyl','ethyl','propyl','butyl','phenyl','vinyl','methoxy','ethoxy',
           'oxo','carboxy','sulfanyl','trifluoromethyl'}


def _graph_validation(m, *, ports=0, graph_key=None, oriented=False):
    """Return machine-readable evidence for a graph naming attempt.

    This is deliberately structural evidence only.  It records the checks that
    make a candidate safe to expose (connectivity, terminal ports and the
    canonical graph key); it does not claim independent chemical review.
    """
    actual_ports = [a.GetIdx() for a in m.GetAtoms() if a.GetAtomicNum() == 0]
    return {
        'connected_components': len(Chem.GetMolFrags(m)),
        'atom_count': m.GetNumAtoms(),
        'port_count': len(actual_ports),
        'expected_port_count': ports,
        'ports_terminal': all(m.GetAtomWithIdx(i).GetDegree() == 1 for i in actual_ports),
        'oriented_port_check': bool(oriented),
        'whole_graph_key': graph_key,
        'whole_graph_roundtrip': False,
        'independent_chemical_review': False,
    }


def _read(s, ports=None):
    if not isinstance(s,str) or not s or len(s)>6000:
        raise ValueError('GRAPH_INPUT_LIMIT')
    params=Chem.SmilesParserParams();params.parseName=False
    m=Chem.MolFromSmiles(s,params)
    if m is None:raise ValueError('INVALID_GRAPH')
    if m.GetNumAtoms()>600 or len(Chem.GetMolFrags(m))!=1:
        raise ValueError('CONNECTED_GRAPH_SIZE_LIMIT')
    if any(a.GetIsotope() or a.GetNumRadicalElectrons() or a.GetChiralTag()!=Chem.ChiralType.CHI_UNSPECIFIED for a in m.GetAtoms()) or any(b.GetStereo()!=Chem.BondStereo.STEREONONE for b in m.GetBonds()):
        raise ValueError('STEREO_ISOTOPE_OR_RADICAL_NAMING_NOT_IMPLEMENTED')
    ps=[a.GetIdx() for a in m.GetAtoms() if a.GetAtomicNum()==0]
    if ports is not None and len(ps)!=ports:raise ValueError('WRONG_PORT_COUNT')
    if any(m.GetAtomWithIdx(i).GetDegree()!=1 for i in ps):raise ValueError('NONTERMINAL_PORT')
    for a in m.GetAtoms():
        if a.GetAtomicNum()!=0:a.SetAtomMapNum(0)
    return m


def _root_key(s):
    m=_read(s,1)
    for a in m.GetAtoms():a.SetAtomMapNum(0)
    return Chem.MolToSmiles(m,canonical=True,isomericSmiles=True)


def _oriented_key(s):
    m,ps=port_mol(s)
    return Chem.MolToSmiles(m,canonical=True,isomericSmiles=True)


def _fragment(m,nodes,attach,bond=Chem.BondType.SINGLE):
    """Copy a pendant component and replace its one exterior bond by a port."""
    rw=Chem.RWMol();mapping={}
    for i in sorted(nodes):
        a=Chem.Atom(m.GetAtomWithIdx(i));a.SetAtomMapNum(0);mapping[i]=rw.AddAtom(a)
    for b in m.GetBonds():
        u,v=b.GetBeginAtomIdx(),b.GetEndAtomIdx()
        if u in mapping and v in mapping:rw.AddBond(mapping[u],mapping[v],b.GetBondType())
    p=rw.AddAtom(Chem.Atom(0));rw.AddBond(p,mapping[attach],bond)
    out=rw.GetMol();Chem.SanitizeMol(out)
    return Chem.MolToSmiles(out,canonical=True,isomericSmiles=True)


def _component(m,start,barriers):
    todo=[start];seen=set()
    while todo:
        i=todo.pop()
        if i in seen or i in barriers:continue
        seen.add(i);todo.extend(a.GetIdx() for a in m.GetAtomWithIdx(i).GetNeighbors())
    return seen


def _pendants(m,scaffold,locants,ignored=(),depth=0):
    """Reject any residual component attached at two places (not a substituent)."""
    scaffold=set(scaffold);blocked=scaffold|set(ignored);seen=set();items=[]
    for i in sorted(scaffold):
        for a in m.GetAtomWithIdx(i).GetNeighbors():
            j=a.GetIdx()
            if j in blocked or j in seen:continue
            nodes=_component(m,j,blocked);seen|=nodes
            links=[(x,b.GetOtherAtomIdx(x),b.GetBondType()) for x in nodes
                   for b in m.GetAtomWithIdx(x).GetBonds() if b.GetOtherAtomIdx(x) in scaffold]
            if len(links)!=1 or i not in locants:return None
            name=root_name(_fragment(m,nodes,j,m.GetBondBetweenAtoms(i,j).GetBondType()),depth+1)
            if not name:return None
            items.append((str(locants[i]),name))
    if scaffold|seen|set(ignored)!=set(range(m.GetNumAtoms())):return None
    return items


def _prefix(items):
    groups=defaultdict(list)
    for loc,label in items:groups[label].append(loc)
    out=[]
    for label,locs in sorted(groups.items()):
        locs.sort(key=lambda s:(int(re.match(r'\d+',s)[0]) if re.match(r'\d+',s) else 999,s))
        n=len(locs)
        if n==1:chunk=label if label in _SIMPLE else '('+label+')'
        elif n<=6:
            simple={2:'di',3:'tri',4:'tetra',5:'penta',6:'hexa'}
            multiple={2:'bis',3:'tris',4:'tetrakis',5:'pentakis',6:'hexakis'}
            chunk=simple[n]+label if label in _SIMPLE else multiple[n]+'('+label+')'
        else:return None
        out.append(','.join(locs)+'-'+chunk)
    return '-'.join(out)


def _sublist(labels):
    if not labels:return ''
    labels=sorted(labels)
    if len(labels)==1:return labels[0] if labels[0] in _SIMPLE or re.fullmatch(r'[a-z]+yl',labels[0]) else '('+labels[0]+')'
    if len(labels)==2 and labels[0]==labels[1]:return 'di'+labels[0] if labels[0] in _SIMPLE or re.fullmatch(r'[a-z]+yl',labels[0]) else 'bis('+labels[0]+')'
    return ''.join('('+x+')' for x in labels)


@lru_cache(maxsize=1)
def _root_dictionary():
    names=set(GROUPS)|set(GROUPS_NEW)|{'oxo','phenyl','benzyl','phenoxy','hydroxy','amino'}
    for stem,n in NAMES.items():
        if n<=30:
            names.update({stem+'yl',stem+'oxy',stem+'oxycarbonyl',stem+'ylcarbonyl'})
    candidates=defaultdict(list)
    for label in sorted(names):
        try:
            s=rooted(label)
            if s:candidates[_root_key(s)].append(label)
        except (ValueError,RuntimeError):pass
    return {g:min(ns,key=lambda n:(n not in _SIMPLE,len(n),n)) for g,ns in candidates.items()}


@lru_cache(maxsize=60000)
def root_name(s,depth=0):
    if depth>7:return None
    try:
        target=_root_key(s);known=_root_dictionary().get(target)
        if known:return known
        m=_read(s,1);p=next(a.GetIdx() for a in m.GetAtoms() if a.GetAtomicNum()==0)
        r=m.GetAtomWithIdx(p).GetNeighbors()[0].GetIdx();atom=m.GetAtomWithIdx(r)
        candidates=[]
        # Heteroatom-root linkers. The bond to the parent stays on this atom.
        neigh=[a.GetIdx() for a in atom.GetNeighbors() if a.GetIdx()!=p]
        if atom.GetAtomicNum() in (8,16) and len(neigh)==1 and not atom.IsInRing() and atom.GetFormalCharge()==0:
            j=neigh[0]
            if m.GetBondBetweenAtoms(r,j).GetBondType()==Chem.BondType.SINGLE:
                nodes=set(range(m.GetNumAtoms()))-{p,r}
                child=root_name(_fragment(m,nodes,j),depth+1)
                if child:candidates.append('('+child+')'+('oxy' if atom.GetAtomicNum()==8 else 'sulfanyl'))
        if atom.GetAtomicNum() in (6,16) and not atom.IsInRing():
            oxos=[j for j in neigh if m.GetAtomWithIdx(j).GetAtomicNum()==8 and m.GetBondBetweenAtoms(r,j).GetBondType()==Chem.BondType.DOUBLE and m.GetAtomWithIdx(j).GetDegree()==1]
            rest=[j for j in neigh if j not in oxos]
            if len(rest)==1 and ((atom.GetAtomicNum()==6 and len(oxos)==1) or (atom.GetAtomicNum()==16 and len(oxos) in (1,2))):
                child=root_name(_fragment(m,set(range(m.GetNumAtoms()))-{p,r,*oxos},rest[0]),depth+1)
                if child:candidates.append('('+child+')'+('carbonyl' if atom.GetAtomicNum()==6 else 'sulfonyl' if len(oxos)==2 else 'sulfinyl'))
        if atom.GetAtomicNum()==7 and not atom.IsInRing() and atom.GetFormalCharge()==0 and all(b.GetBondType()==Chem.BondType.SINGLE for b in atom.GetBonds()):
            items=_pendants(m,{r},{r:'1'},{p},depth)
            if items and 1<=len(items)<=2:candidates.append(_sublist([v for _,v in items])+'amino')
        # Phenyl root: anchored ring position is 1; pendant regions must be disjoint.
        ring=Chem.MolFromSmiles('c1ccccc1')
        if atom.GetIsAromatic():
            for match in m.GetSubstructMatches(ring,uniquify=False,maxMatches=128):
                if match[0]!=r:continue
                items=_pendants(m,match,{j:str(i+1) for i,j in enumerate(match)},{p},depth)
                if items is not None:
                    pre=_prefix(items)
                    if pre is not None:candidates.append(pre+'phenyl')
        # Explicit numbered heterocyclic roots, including N-H replacement only.
        from .heterocycles_v09 import STEM_PARENT, ring_parent
        for stem,parent in STEM_PARENT.items():
            if parent in ('thiophene','furan','pyrrole','naphthalene'):
                base,loc=_parent(parent)
            else:
                data=ring_parent(parent)
                if not data:continue
                base,loc=data
            inv={j:p for p,j in loc.items()}
            for match in m.GetSubstructMatches(base,uniquify=False,maxMatches=128):
                if r not in match:continue
                at=match.index(r);position=inv.get(at)
                if position is None:continue
                items=_pendants(m,match,{match[j]:p for p,j in loc.items()},{p},depth)
                if items is not None:
                    pre=_prefix(items)
                    if pre is not None:candidates.append(pre+stem+'-'+position+'-yl')

        # Longest saturated acyclic carbon path, anchored at substituent position 1.
        if atom.GetAtomicNum()==6 and not atom.GetIsAromatic() and not atom.IsInRing() and all(b.GetBondType()==Chem.BondType.SINGLE for b in atom.GetBonds()):
            paths=[]
            def walk(path):
                if len(paths)>128 or len(path)>30:return
                nxt=[a.GetIdx() for a in m.GetAtomWithIdx(path[-1]).GetNeighbors()
                     if a.GetAtomicNum()==6 and not a.IsInRing() and not a.GetIsAromatic() and a.GetIdx() not in path
                     and all(b.GetBondType()==Chem.BondType.SINGLE for b in a.GetBonds())]
                if not nxt:paths.append(path)
                else:
                    for j in nxt:walk(path+[j])
            walk([r])
            maxlen=max((len(x) for x in paths),default=0)
            for path in paths:
                if len(path)!=maxlen or len(path) not in _STEMS:continue
                items=_pendants(m,path,{j:str(i+1) for i,j in enumerate(path)},{p},depth)
                if items is not None:
                    pre=_prefix(items)
                    if pre is not None:candidates.append(pre+_STEMS[len(path)]+'yl')
        for candidate in sorted(set(candidates),key=lambda x:(len(x),x)):
            parsed=rooted(candidate)
            if parsed and _root_key(parsed)==target:return candidate
    except (ValueError,RuntimeError,KeyError,IndexError):return None
    return None


@lru_cache(maxsize=1)
def _oriented_tokens():
    result=defaultdict(list)
    for label,s in TOKENS.items():
        try:result[_oriented_key(s)].append(label)
        except (ValueError,RuntimeError):pass
    return {g:min(ns,key=lambda n:(n=='thio',len(n),n)) for g,ns in result.items()}


@lru_cache(maxsize=50000)
def label_divalent(s):
    """Name an oriented subunit, not the full periodic polymer."""
    try:
        m=_read(s,2);m,ports=port_mol(s);target=_oriented_key(s)
        known=_oriented_tokens().get(target)
        if known:return known
        left,right=[m.GetAtomWithIdx(p).GetNeighbors()[0].GetIdx() for p in ports]
        path=list(Chem.GetShortestPath(m,ports[0],ports[1]))[1:-1]
        candidates=[]
        if path and all(m.GetAtomWithIdx(j).GetAtomicNum()==6 and not m.GetAtomWithIdx(j).IsInRing() and not m.GetAtomWithIdx(j).GetIsAromatic() for j in path) and all(m.GetBondBetweenAtoms(a,b).GetBondType()==Chem.BondType.SINGLE for a,b in zip(path,path[1:])):
            items=_pendants(m,path,{j:str(i+1) for i,j in enumerate(path)},ports)
            if items is not None:
                n=len(path)
                if n==1:candidates.append(_sublist([x[1] for x in items])+'methylene')
                elif n in _STEMS:
                    pre=_prefix(items)
                    if pre is not None:candidates.append(pre+('ethylene' if n==2 else _STEMS[n]+f'ane-1,{n}-diyl'))
        if left==right and m.GetAtomWithIdx(left).GetAtomicNum() in (7,14):
            items=_pendants(m,{left},{left:'1'},ports)
            if items is not None and 1<=len(items)<=2:
                candidates.append(_sublist([x[1] for x in items])+('imino' if m.GetAtomWithIdx(left).GetAtomicNum()==7 else 'silanediyl'))
        # Complete monocyclic/fused scaffold matching; only pendant substitution.
        for parent in (('benzene','naphthalene','thiophene','furan','pyrrole','cyclohexane','cyclopentane','pyridine','pyrimidine','pyridazine','pyrazine','piperidine','piperazine','pyrrolidine','morpholine','thiomorpholine','pyrrolidine-2,5-dione','piperidine-2,6-dione') if any(m.GetAtomWithIdx(j).IsInRing() for j in path) else ()):
            try:base,loc=_parent(parent)
            except (ValueError,KeyError):continue
            if base is None:continue
            inverse={j:p for p,j in loc.items()}
            for match in m.GetSubstructMatches(base,uniquify=False,maxMatches=256):
                invmatch={j:i for i,j in enumerate(match)}
                if left not in invmatch or right not in invmatch:continue
                a,b=inverse.get(invmatch[left]),inverse.get(invmatch[right])
                if a is None or b is None:continue
                items=_pendants(m,match,{match[j]:p for p,j in loc.items()},ports)
                if items is None:continue
                pre=_prefix(items)
                if pre is None:continue
                tail=(a+','+b+'-phenylene') if parent=='benzene' else parent+'-'+a+','+b+'-diyl'
                candidates.append(pre+('-' if pre and tail[0].isdigit() else '')+tail)
        # Keep the attachment orientation: periodic equality alone is insufficient here.
        def candidate_rank(name):
            loc=re.search(r"(?:^|[-)])([0-9]+'?),([0-9]+'?)-(?:phenylene|diyl)$",name)
            free=tuple(int(re.match(r'\d+',x)[0]) for x in loc.groups()) if loc else (0,0)
            return (free,len(name),name)
        for name in sorted(set(candidates),key=candidate_rank):
            d=divalent(name)
            if d and _oriented_key(d)==target:return name
    except (ValueError,RuntimeError,KeyError,IndexError):return None
    return None


@lru_cache(maxsize=60000)
def _segment_label(blocks):
    try:return label_divalent(assemble(list(blocks)))
    except (ValueError,RuntimeError):return None


def _emit(labels):
    simple={'oxy','imino','carbonyl','sulfonyl','sulfanediyl','methylene','ethylene',
            'trimethylene','tetramethylene','pentamethylene','hexamethylene'}
    if len(labels)==1:return labels[0]
    return ''.join(x if x in simple else '('+x+')' for x in labels)


@lru_cache(maxsize=1)
def _legacy_blocks():
    from .naming import lexicon
    return {b for blocks,_,_ in lexicon() for b in blocks}

@lru_cache(maxsize=16000)
def _chain_block(s):
    m,ps=port_mol(s);a,b=[m.GetAtomWithIdx(p).GetNeighbors()[0] for p in ps]
    return a.GetIdx()==b.GetIdx() and a.GetAtomicNum()==6 and not a.IsInRing() and not a.GetIsAromatic()

@lru_cache(maxsize=16000)
def name_unit(smiles):
    from .naming import name_from_unit
    try:_read(smiles,2)
    except (ValueError,RuntimeError) as e:return fail(str(e),profile=PROFILE)
    p=canonicalize_unit(smiles)
    if p['status']!='PARSED':return fail('PERIODIC_GRAPH_OUTSIDE_NAMING_PROFILE',periodic=p,profile=PROFILE)
    try:
        raw, raw_ports = port_mol(smiles)
        evidence = _graph_validation(raw, ports=2,
                                     graph_key=p['periodic']['periodic_graph_key'],
                                     oriented=True)
    except (ValueError, RuntimeError, KeyError, IndexError):
        evidence = None
    word=tuple(p['primitive_blocks']);n=len(word)
    if n>48:return fail('GRAPH_NAMING_SEARCH_BUDGET',profile=PROFILE,primitive_blocks=n)
    # Preserve existing successful candidate strings; the extension is explicit fallback.
    if n<=16 and all(b in _legacy_blocks() for b in word):
        old=name_from_unit(p['canonical_repeat_smiles'])
        if old['status']=='PARSED':
            try:
                raw, _ = port_mol(smiles)
                ev = _graph_validation(raw, ports=2,
                                       graph_key=p['periodic']['periodic_graph_key'],
                                       oriented=True)
                ev.update({'whole_graph_roundtrip':True,
                           'oriented_port_check':True,
                           'primitive_block_count':len(p['primitive_blocks'])})
            except (ValueError, RuntimeError, KeyError, IndexError):
                ev = None
            return {**old,'profile':PROFILE,'candidate_method':'LEGACY_GRAPH_NAMER_PRESERVED',
                    'graph_validation':ev}
    reverse=tuple(reverse_unit(b) for b in reversed(word));choices={}
    for seq in (word,reverse):
        for i in range(n):choices[seq[i:]+seq[:i]]=None
    results=[]
    for seq in sorted(choices):
        dp={0:([],0)}
        for i in range(n):
            if i not in dp:continue
            labels,cost=dp[i]
            # Only contiguous bridge blocks may be combined as a subunit.
            for length in range(1,min(n-i,30)+1):
                if length>1 and not all(_chain_block(b) for b in seq[i:i+length]):break
                label=_segment_label(seq[i:i+length])
                if not label:continue
                candidate=labels+[label];j=i+length
                rank=(len(candidate),sum(len(x) for x in candidate),candidate)
                previous=dp.get(j)
                if previous is None or rank<(len(previous[0]),sum(len(x) for x in previous[0]),previous[0]):dp[j]=(candidate,cost+1)
        if n in dp:
            labels=dp[n][0];label=_emit(labels)
            priority=0 if labels[0]=='oxy' else 1 if labels[0] in ('sulfanediyl','sulfonyl') else 2 if labels[0].endswith('imino') else 3 if any(x in labels[0] for x in ('phenylene','naphthalene','thiophene','furan','pyrrole')) else 4
            results.append(((priority,len(labels),len(label),label),labels,label))
    for _,labels,label in sorted(results):
        parsed=resolve_unit(label)
        if parsed['status']=='PARSED' and parsed['periodic']['periodic_graph_key']==p['periodic_graph_key']:
            return {'status':'PARSED','profile':PROFILE,'structure_based_name_candidate':'poly('+label+')',
                    'unit_label':label,'periodic':p,'candidate_method':'COMPLETE_ORIENTED_GRAPH_DECOMPOSITION',
                    'rule_trace':[{'rule':'GRAPH-PENDANT-PARTITION-0.9','subunits':labels},
                                  {'rule':'ORIENTED-SUBUNIT-GRAPH-ROUNDTRIP-0.9','checks':'all'},
                                  {'rule':'WHOLE-PERIODIC-ROUNDTRIP-0.9','graph_key':p['periodic_graph_key']}],
                    'graph_roundtrip_consistent':True,
                    'graph_validation':{**(evidence or {}),'whole_graph_roundtrip':True,
                                       'oriented_port_check':True,
                                       'primitive_block_count':len(p['primitive_blocks'])},
                    'preferred_iupac_name':None,'full_iupac_conformance':False,
                    'independent_rule_validation':'NOT_COMPLETED','exact_material_identity':False}
    return fail('CU_COMPLETE_GRAPH_DECOMPOSITION_UNSUPPORTED',profile=PROFILE,
                periodic=p, graph_validation=evidence)


@lru_cache(maxsize=1)
def _source_templates():
    templates=[]
    # These templates are declared grammar, never collected from catalog names.
    for suffix,fg in [('benzoic acid','*C(=O)O'),('aniline','*N'),('phenol','*O'),('styrene','*C=C')]:
        m,loc=_parent('benzene');m=connect(m,0,fg);Chem.SanitizeMol(m)
        templates.append((suffix,m,loc))
    for parent in ('benzene','biphenyl','naphthalene','cyclohexane'):
        base,loc=_parent(parent)
        valid=list(loc)
        for x,a in enumerate(valid):
            for b in valid[x+1:]:
                for suffix,fg in [('diamine','*N'),('diol','*O'),('dicarboxylic acid','*C(=O)O')]:
                    try:
                        with rdBase.BlockLogs():
                            m=connect(connect(base,loc[a],fg),loc[b],fg);Chem.SanitizeMol(m)
                    except (ValueError,RuntimeError):continue
                    templates.append((parent+'-'+a+','+b+'-'+suffix,m,loc))
    for n in range(2,21):
        stem=_STEMS[n];base=Chem.MolFromSmiles('C'*n);loc={str(i+1):i for i in range(n)}
        for suffix,fg in [('diamine','*N'),('diol','*O')]:
            m=connect(connect(base,0,fg),n-1,fg);Chem.SanitizeMol(m)
            templates.append((f'{stem}ane-1,{n}-{suffix}',m,loc))
    from .heterocycles_v09 import RINGS,ring_parent
    for parent in RINGS:
        if parent=='maleimide':continue
        base,loc=ring_parent(parent);templates.append((parent,base,loc))
    return tuple(templates)


@lru_cache(maxsize=16000)
def name_source(smiles):
    try:
        m=_read(smiles,0);g=canonicalize(smiles)
        if g['status']!='PARSED':return g
        evidence=_graph_validation(m, ports=0, graph_key=g['molecule_key'])
        candidates=[]
        # Graph-derived parent rule for an unbranched acyclic mono-alkene.
        # The chain and double-bond locant are taken from the graph; no input
        # or catalog label participates in candidate construction.
        atoms=list(m.GetAtoms())
        if (atoms and all(a.GetAtomicNum()==6 and not a.IsInRing() for a in atoms)
                and m.GetNumBonds()==m.GetNumAtoms()-1
                and sum(b.GetBondType()==Chem.BondType.DOUBLE for b in m.GetBonds())==1
                and all(a.GetDegree()<=2 for a in atoms)):
            ends=[a.GetIdx() for a in atoms if a.GetDegree()==1]
            if len(ends)==2:
                paths=[]
                def walk(path):
                    if len(path)==len(atoms): paths.append(path); return
                    for nb in m.GetAtomWithIdx(path[-1]).GetNeighbors():
                        j=nb.GetIdx()
                        if j not in path: walk(path+[j])
                walk([ends[0]])
                walk([ends[1]])
                for path in paths:
                    dbl=[i for i,(u,v) in enumerate(zip(path,path[1:]),1)
                         if m.GetBondBetweenAtoms(u,v).GetBondType()==Chem.BondType.DOUBLE]
                    if len(dbl)!=1 or len(path) not in _STEMS: continue
                    candidates.append(f'{_STEMS[len(path)]}-{dbl[0]}-ene')
        imide=Chem.MolFromSmiles('N1C(=O)C=CC1=O')
        for match in m.GetSubstructMatches(imide,uniquify=False,maxMatches=64):
            items=_pendants(m,match,{match[0]:'N'})
            if items is not None and len(items)==1:candidates.append('N-('+items[0][1]+')maleimide')
        # Acrylic esters: cut only the single O-alkyl/aryl bond, preserving attachment.
        for suffix,acid in [(' acrylate','C=CC(=O)O'),(' methacrylate','C=C(C)C(=O)O')]:
            query=Chem.MolFromSmiles(acid);ox=query.GetNumAtoms()-1
            for match in m.GetSubstructMatches(query,uniquify=False,maxMatches=128):
                sites=[a.GetIdx() for a in m.GetAtomWithIdx(match[ox]).GetNeighbors() if a.GetIdx() not in match]
                if len(sites)!=1:continue
                nodes=_component(m,sites[0],set(match))
                if nodes|set(match)!=set(range(m.GetNumAtoms())):continue
                links=sum(b.GetOtherAtomIdx(i) in set(match) for i in nodes for b in m.GetAtomWithIdx(i).GetBonds())
                if links!=1:continue
                label=root_name(_fragment(m,nodes,sites[0]))
                if label:candidates.append(label+suffix)
        for suffix,base,loc in _source_templates():
            if base.GetNumAtoms()>m.GetNumAtoms():continue
            for match in m.GetSubstructMatches(base,uniquify=False,maxMatches=64):
                items=_pendants(m,match,{match[j]:p for p,j in loc.items()})
                if items is None:continue
                pre=_prefix(items)
                if pre is not None:candidates.append(pre+suffix)
        from .name_rules import systematic
        from .family_rules import extended_systematic
        from .queue_rules import resolve_source
        from .advanced_names import resolve_source_v05
        from .families_v07 import resolve_source_v07
        from .expansion_v08 import source
        from .heterocycles_v09 import source as source09
        for label in sorted(set(candidates),key=lambda x:(len(x),x)):
            r=systematic(label) or extended_systematic(label) or resolve_source(label) or resolve_source_v05(label) or resolve_source_v07(label) or source(label) or source09(label)
            if r:
                back=canonicalize(r[0])
                if back.get('molecule_key')==g['molecule_key']:
                    return {'status':'PARSED','label':label,'graph_key':g['molecule_key'],'smiles':g['isomeric_smiles'],
                            'profile':PROFILE,'candidate_method':'COMPLETE_FINITE_GRAPH_TEMPLATE_AND_PENDANTS',
                            'graph_roundtrip_consistent':True,'independent_chemical_review':False,
                            'graph_validation':{**evidence,'whole_graph_roundtrip':True,
                                               'rooted_fragment_roundtrip':True},
                            'preferred_iupac_name':None,'full_iupac_conformance':False}
        return fail('SOURCE_GRAPH_NAMING_OUTSIDE_PROFILE',profile=PROFILE,
                    graph_validation=evidence)
    except (ValueError,RuntimeError,KeyError,IndexError) as e:return fail(str(e),profile=PROFILE)
