"""Canonicalization for achiral, connected 1-D single-bond bridge chains.
Split a ported cell at single backbone bridges, obtain oriented finite blocks,
reduce the cyclic word to its primitive period, and quotient by reversal.
This is a declared graph class, not an arbitrary network or IUPAC name oracle.
"""
from __future__ import annotations
from functools import lru_cache
from collections import deque
import networkx as nx
import re
from rdkit import Chem,rdBase
from rdkit.Chem import rdMolDescriptors
from .chemistry import ChemistryError,read_molecule
from .common import key,fail

def port_mol(s):
    m=read_molecule(s,allow_ports=True)
    if len(Chem.GetMolFrags(m))!=1:raise ChemistryError('UNIT_MUST_BE_CONNECTED')
    ports=[a.GetIdx() for a in m.GetAtoms() if a.GetAtomicNum()==0]
    if len(ports)!=2:raise ChemistryError('EXACTLY_TWO_PORTS_REQUIRED')
    for p in ports:
        a=m.GetAtomWithIdx(p)
        if a.GetDegree()!=1 or a.GetBonds()[0].GetBondType()!=Chem.BondType.SINGLE:raise ChemistryError('SINGLE_BOND_PORT_REQUIRED')
    if any(a.GetChiralTag()!=Chem.ChiralType.CHI_UNSPECIFIED for a in m.GetAtoms()) or any(b.GetStereo()!=Chem.BondStereo.STEREONONE for b in m.GetBonds()):raise ChemistryError('PERIODIC_STEREO_FRAME_NOT_IMPLEMENTED')
    params=Chem.SmilesParserParams();params.parseName=False;raw=Chem.MolFromSmiles(s,params)
    nums={a.GetAtomMapNum():a.GetIdx() for a in raw.GetAtoms() if a.GetAtomicNum()==0}
    if set(nums)=={1,2}:ports=[nums[1],nums[2]]
    for lab,p in enumerate(ports,1):m.GetAtomWithIdx(p).SetAtomMapNum(lab)
    return m,ports

def atom_graph(m):
    g=nx.Graph();g.add_nodes_from(range(m.GetNumAtoms()))
    for b in m.GetBonds():g.add_edge(b.GetBeginAtomIdx(),b.GetEndAtomIdx())
    return g

def make_block(m,nodes,left,right):
    r=Chem.RWMol();mp={}
    for i in sorted(nodes):
        a=Chem.Atom(m.GetAtomWithIdx(i));a.SetAtomMapNum(0);mp[i]=r.AddAtom(a)
    for b in m.GetBonds():
        u,v=b.GetBeginAtomIdx(),b.GetEndAtomIdx()
        if u in mp and v in mp:r.AddBond(mp[u],mp[v],b.GetBondType())
    for label,i in [(1,left),(2,right)]:
        a=Chem.Atom(0);a.SetAtomMapNum(label);j=r.AddAtom(a);r.AddBond(mp[i],j,Chem.BondType.SINGLE)
    out=r.GetMol();Chem.SanitizeMol(out);return Chem.MolToSmiles(out,canonical=True,isomericSmiles=True)

def reverse_unit(s):
    m,ps=port_mol(s);m.GetAtomWithIdx(ps[0]).SetAtomMapNum(2);m.GetAtomWithIdx(ps[1]).SetAtomMapNum(1)
    return Chem.MolToSmiles(m,canonical=True,isomericSmiles=True)

def split_blocks(s):
    m,ports=port_mol(s);g=atom_graph(m);path=nx.shortest_path(g,ports[0],ports[1])[1:-1]
    if not path:raise ChemistryError('PORT_TO_PORT_EMPTY_UNIT')
    real=set(g)-set(ports);h=g.subgraph(real).copy();bridges={frozenset(e) for e in nx.bridges(h)}
    cuts=[(u,v) for u,v in zip(path,path[1:]) if frozenset((u,v)) in bridges and m.GetBondBetweenAtoms(u,v).GetBondType()==Chem.BondType.SINGLE]
    h.remove_edges_from(cuts);sets=list(nx.connected_components(h));where={v:i for i,c in enumerate(sets) for v in c};order=[]
    for v in path:
        if not order or order[-1]!=where[v]:order.append(where[v])
    if len(order)!=len(sets):raise ChemistryError('UNIT_DECOMPOSITION_ERROR')
    blocks=[]
    for i in order:
        p=[v for v in path if where[v]==i];blocks.append(make_block(m,sets[i],p[0],p[-1]))
    return blocks

def assemble(units):
    if not isinstance(units,list) or not 1<=len(units)<=256:raise ChemistryError('UNIT_COUNT_LIMIT')
    mols=[];bounds=[];off=0
    for s in units:
        m,ports=port_mol(s);mols.append(m);bounds.append([p+off for p in ports]);off+=m.GetNumAtoms()
    combined=mols[0]
    for m in mols[1:]:combined=Chem.CombineMols(combined,m)
    rw=Chem.RWMol(combined);remove=[]
    for i in range(len(bounds)-1):
        a,b=bounds[i][1],bounds[i+1][0];u=rw.GetAtomWithIdx(a).GetNeighbors()[0].GetIdx();v=rw.GetAtomWithIdx(b).GetNeighbors()[0].GetIdx()
        rw.AddBond(u,v,Chem.BondType.SINGLE);remove.extend([a,b])
    rw.GetAtomWithIdx(bounds[0][0]).SetAtomMapNum(1);rw.GetAtomWithIdx(bounds[-1][1]).SetAtomMapNum(2)
    for i in sorted(remove,reverse=True):rw.RemoveAtom(i)
    out=rw.GetMol();Chem.SanitizeMol(out);return Chem.MolToSmiles(out,canonical=True,isomericSmiles=True)

def primitive(seq):
    for n in range(1,len(seq)+1):
        if len(seq)%n==0 and seq==seq[:n]*(len(seq)//n):return seq[:n]
    return seq

@lru_cache(maxsize=30000)
def canonicalize_unit(smiles):
    try:
        f=split_blocks(smiles);r=[reverse_unit(x) for x in reversed(f)];options=[tuple(x[i:]+x[:i]) for x in [f,r] for i in range(len(x))]
        p=primitive(list(min(options)));s=assemble(p);m,_=port_mol(s);formula=re.sub(r'\*\d*','',rdMolDescriptors.CalcMolFormula(m))
        return {'status':'PARSED','periodic_graph_key':key('bridge-chain/0.2/rdkit-'+rdBase.rdkitVersion,p),'scope':'infinite_unoriented_achiral_constitution','canonical_repeat_smiles':s,'primitive_formula':formula,'primitive_blocks':p,'input_block_count':len(f),'primitive_block_count':len(p),'cell_multiplier':len(f)//len(p),'method':'SINGLE_BRIDGE_BLOCK_WORD_PRIMITIVE_DIHEDRAL','is_iupac_preferred_cru':False,'exact_material_identity':False}
    except (ValueError,RuntimeError,nx.NetworkXException) as exc:return fail(str(exc))

def periodic_json_to_unit(graph):
    """A valid cut leaves a balanced connected voltage graph; seam voltage is ±1.
    Gauge changes may move atoms many cells. Integer supercells are accepted.
    All cycles remaining after the cut must have exactly zero net translation.
    """
    if graph.get('schema')!='periodic_graph_1d/1':raise ChemistryError('PERIODIC_SCHEMA_UNSUPPORTED')
    if graph.get('scope')!='infinite_unoriented_constitution':raise ChemistryError('PERIODIC_SCOPE_UNSUPPORTED')
    atoms=graph.get('atoms',[]);edges=graph.get('bonds',[])
    if not 1<=len(atoms)<=256 or not 1<=len(edges)<=600:raise ChemistryError('PERIODIC_SIZE_LIMIT')
    ids={a['id']:i for i,a in enumerate(atoms)}
    if len(ids)!=len(atoms):raise ChemistryError('DUPLICATE_ATOM_IDS')
    if any(a.get('stereo') not in (None,'unspecified') for a in atoms):raise ChemistryError('PERIODIC_STEREO_FRAME_NOT_IMPLEMENTED')
    clean=[];seen=set()
    for b in edges:
        if b['u'] not in ids or b['v'] not in ids or type(b['offset']) is not int:raise ChemistryError('INVALID_PERIODIC_EDGE')
        if b.get('stereo') not in (None,'unspecified'):raise ChemistryError('PERIODIC_STEREO_FRAME_NOT_IMPLEMENTED')
        e=(ids[b['u']],ids[b['v']],b['offset'],b['order']);rev=(e[1],e[0],-e[2],e[3]);ek=min(e,rev)
        if ek in seen:raise ChemistryError('DUPLICATE_PERIODIC_EDGE')
        if e[0]==e[1] and e[2]==0:raise ChemistryError('ZERO_OFFSET_SELF_BOND')
        seen.add(ek);clean.append(e)
    for cut,(u,v,offset,order) in enumerate(clean):
        if order!=1:continue
        adj=[[] for _ in atoms]
        for j,(x,y,z,o) in enumerate(clean):
            if j==cut:continue
            adj[x].append((y,z));adj[y].append((x,-z))
        pot={0:0};q=deque([0]);balanced=True
        while q and balanced:
            x=q.popleft()
            for y,z in adj[x]:
                expected=pot[x]+z
                if y in pot:
                    if pot[y]!=expected:balanced=False;break
                else:pot[y]=expected;q.append(y)
        if not balanced or len(pot)!=len(atoms):continue
        seam=offset+pot[u]-pot[v]
        if abs(seam)!=1:continue
        rw=Chem.RWMol()
        for a in atoms:
            at=Chem.Atom(a['element']);at.SetFormalCharge(int(a.get('charge',0)));at.SetIsotope(int(a.get('isotope') or 0));at.SetNumExplicitHs(int(a.get('hydrogen_count',0)));at.SetNoImplicit(True);rw.AddAtom(at)
        bt={1:Chem.BondType.SINGLE,2:Chem.BondType.DOUBLE,3:Chem.BondType.TRIPLE,1.5:Chem.BondType.AROMATIC}
        for j,(x,y,z,o) in enumerate(clean):
            if j==cut:continue
            if x==y or rw.GetBondBetweenAtoms(x,y):raise ChemistryError('MULTIEDGE_NOT_SUPPORTED_IN_FINITE_CELL')
            if o not in bt:raise ChemistryError('BOND_ORDER_UNSUPPORTED')
            rw.AddBond(x,y,bt[o])
        for label,x in [(1,u),(2,v)]:
            a=Chem.Atom(0);a.SetAtomMapNum(label);j=rw.AddAtom(a);rw.AddBond(x,j,Chem.BondType.SINGLE)
        m=rw.GetMol();Chem.SanitizeMol(m);return Chem.MolToSmiles(m,canonical=True,isomericSmiles=True)
    raise ChemistryError('NOT_A_CONNECTED_SINGLE_SEAM_BRIDGE_CHAIN')

def canonicalize_graph(graph):
    try:
        s=periodic_json_to_unit(graph);r=canonicalize_unit(s)
        return {**r,'cell_smiles':s,'input_schema':'periodic_graph_1d/1'}
    except (ValueError,RuntimeError,KeyError,TypeError) as exc:return fail(str(exc))
