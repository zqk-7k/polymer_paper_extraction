"""End-aware name candidates in a bounded two-port, achiral single-chain class.

Not a complete RSSOP preferred-CRU engine.  The backbone candidate comes from
naming.py.  Direction/cut changes are established with oriented block words
and exact rooted-cap graphs, not with an unoriented periodic key alone.

For U=AB and V=BA, the equalities
  (X B) (A B)^n R = X (B A)^n (B R),
  L (A B)^n (A Y) = (L A) (B A)^n Y
prove a cap transfer for every n>=1. Rooted graph equalities verify the terms.
Only count-preserving conjugacies are used; no chain length is inferred.
"""
from __future__ import annotations
from functools import lru_cache
from rdkit import Chem, rdBase
from .common import fail, stable_json
from .periodic import port_mol, split_blocks, reverse_unit, assemble, canonicalize_unit
from .finite_chains import resolve_end_group
from .naming import name_from_unit
from .units import resolve_unit

PROFILE = 'end-aware-candidate/0.7'
RULE_SOURCE = 'IUPAC-RSSOP-2002-R21'
CAP_LABELS = ('hydro','hydroxy','methoxy','ethoxy','propoxy','butoxy','amino',
              'methyl','ethyl','propyl','butyl','chloro','bromo','fluoro','phenoxy')


def _read(s):
    p=Chem.SmilesParserParams();p.parseName=False;p.removeHs=False
    with rdBase.BlockLogs():m=Chem.MolFromSmiles(s,p)
    if m is None:raise ValueError('INVALID_ROOTED_END_GRAPH')
    if len(Chem.GetMolFrags(m))!=1 or m.GetNumAtoms()>128:
        raise ValueError('END_GRAPH_SIZE_OR_CONNECTIVITY')
    if any(a.GetIsotope() or a.GetFormalCharge() or a.GetChiralTag()!=Chem.ChiralType.CHI_UNSPECIFIED for a in m.GetAtoms()):
        raise ValueError('END_STATE_OR_STEREO_OUT_OF_SCOPE')
    if any(b.GetStereo()!=Chem.BondStereo.STEREONONE for b in m.GetBonds()):
        raise ValueError('END_STEREO_OUT_OF_SCOPE')
    return m


def _root_key(m):
    p=[a.GetIdx() for a in m.GetAtoms() if a.GetAtomicNum()==0]
    if len(p)!=1 or m.GetAtomWithIdx(p[0]).GetDegree()!=1:
        raise ValueError('ONE_ROOTED_CAP_PORT_REQUIRED')
    for a in m.GetAtoms():a.SetAtomMapNum(1 if a.GetAtomicNum()==0 else 0)
    with rdBase.BlockLogs():m=Chem.RemoveHs(m)
    Chem.SanitizeMol(m)
    return Chem.MolToSmiles(m,canonical=True,isomericSmiles=True)


@lru_cache(maxsize=1024)
def cap_graph(label):
    r=resolve_end_group(label)
    if r['status']!='PARSED':raise ValueError('END_LABEL_OUTSIDE_ROOTED_GRAMMAR')
    m=_read(r['rooted_smiles'])
    if not any(a.GetAtomicNum()==0 for a in m.GetAtoms()):
        rw=Chem.RWMol(m);i=rw.AddAtom(Chem.Atom(0));rw.AddBond(i,0,Chem.BondType.SINGLE)
        m=rw.GetMol();Chem.SanitizeMol(m)
    return _root_key(m)


def _extend(cap,blocks,side):
    """Return L A (side=left) or B R (side=right) as a rooted cap graph."""
    if not blocks:return cap
    m,ports=port_mol(assemble(list(blocks)))
    c=_read(cap);cp=next(a.GetIdx() for a in c.GetAtoms() if a.GetAtomicNum()==0)
    p=ports[0] if side=='left' else ports[1]
    off=m.GetNumAtoms();rw=Chem.RWMol(Chem.CombineMols(m,c))
    x=m.GetAtomWithIdx(p).GetNeighbors()[0].GetIdx()
    y=off+c.GetAtomWithIdx(cp).GetNeighbors()[0].GetIdx()
    rw.AddBond(x,y,Chem.BondType.SINGLE)
    for i in sorted([p,off+cp],reverse=True):rw.RemoveAtom(i)
    result=rw.GetMol();Chem.SanitizeMol(result)
    return _root_key(result)


def _alphabet(label):
    # Restricted, unsubstituted cap labels use ordinary alphabetic comparison.
    # General complex-substituent alphabetization is NOT implemented here.
    return label.lower()


@lru_cache(maxsize=2048)
def _candidates(smiles,alpha,omega):
    input_mol,ports=port_mol(smiles)
    if any(a.GetIsotope() or a.GetFormalCharge() for a in input_mol.GetAtoms()):
        raise ValueError('UNIT_STATE_OUTSIDE_END_NAMING_SCOPE')
    u=split_blocks(smiles)
    if len(u)>16:raise ValueError('END_DIRECTION_BLOCK_BUDGET')
    named=name_from_unit(smiles)
    if named['status']!='PARSED':return None,named,[]
    label=named['structure_based_name_candidate'][5:-1]
    target=resolve_unit(label)
    if target['status']!='PARSED':raise ValueError('CANDIDATE_CRU_NOT_REPARSEABLE')
    v=split_blocks(target['unit_smiles'])
    # Powers have a valid unoriented periodic key but require a count transform.
    if len(u)!=len(v):return None,named,[{'code':'CELL_MULTIPLICITY_MAPPING_NOT_IMPLEMENTED'}]
    lg,rg=cap_graph(alpha),cap_graph(omega)
    caps={}
    for name in sorted(set(CAP_LABELS)|{alpha,omega}):
        try:caps.setdefault(cap_graph(name),[]).append(name)
        except (ValueError,RuntimeError):pass
    found=[]
    def add(left,right,direction,shift,proof):
        if left not in caps or right not in caps:return
        # Limit re-expression ranking to supported simple cap labels; a named
        # input outside them is retained but no all-IUPAC ranking is claimed.
        a=min(caps[left],key=_alphabet);b=min(caps[right],key=_alphabet)
        found.append({'alpha':a,'omega':b,'unit_label':label,
                      'unit_smiles':target['unit_smiles'], 'direction':direction,
                      'rotation_blocks':shift,'repeat_count_multiplier':1,
                      'repeat_count_offset':0,'proof':proof,
                      'output_cap_graphs':{'alpha':left,'omega':right}})
    for direction,seq,L,R in [('forward',u,lg,rg),
                              ('reverse',[reverse_unit(x) for x in reversed(u)],rg,lg)]:
        if seq==v:
            add(L,R,direction,0,{'kind':'EXACT_ORIENTED_BLOCK_WORD',
                'input_word':seq,'named_word':v,'equation':'L U^n R = L U^n R'})
        for cut in range(1,len(seq)):
            A,B=seq[:cut],seq[cut:]
            if B+A!=v:continue
            for X in caps:
                if _extend(X,B,'left')==L:
                    right=_extend(R,B,'right')
                    add(X,right,direction,cut,{'kind':'ROOTED_CAP_LEFT_CONJUGACY',
                        'input_word':seq,'A':A,'B':B,'named_word':v,
                        'verified_equal_cap_graph':L,
                        'equation':'(X B) (A B)^n R = X (B A)^n (B R)'})
            for Y in caps:
                if _extend(Y,A,'right')==R:
                    left=_extend(L,A,'left')
                    add(left,Y,direction,cut,{'kind':'ROOTED_CAP_RIGHT_CONJUGACY',
                        'input_word':seq,'A':A,'B':B,'named_word':v,
                        'verified_equal_cap_graph':R,
                        'equation':'L (A B)^n (A Y) = (L A) (B A)^n Y'})
    unique={stable_json([x['alpha'],x['omega'],label]):x for x in reversed(found)}
    ordered=sorted(unique.values(),key=lambda x:(_alphabet(x['alpha']),_alphabet(x['omega']),stable_json(x)))
    return (ordered[0] if ordered else None),named,ordered


def name_with_end_groups(inputs):
    allowed={'unit_smiles','end_groups'}
    if not isinstance(inputs,dict) or set(inputs)-allowed:return fail('END_NAMING_FIELDS_INVALID','INVALID')
    ends=inputs.get('end_groups');s=inputs.get('unit_smiles')
    if not isinstance(ends,dict) or set(ends)!={'alpha','omega'} or not all(isinstance(v,str) for v in ends.values()):
        return fail('EXPLICIT_ALPHA_OMEGA_REQUIRED','NEEDS_DETAILS')
    if not isinstance(s,str):return fail('PORTED_UNIT_REQUIRED','NEEDS_DETAILS')
    try:
        chosen,backbone,alternatives=_candidates(s,ends['alpha'],ends['omega'])
        if chosen is None:return fail('END_DIRECTION_OR_CAP_REEXPRESSION_UNSUPPORTED','NEEDS_DETAILS',
                                     backbone_candidate=backbone,details=alternatives)
        a,b=chosen['alpha'],chosen['omega']
        # Expose the deterministic end/backbone synchronization decision as
        # reviewable evidence.  It records the path/cap graph proof and the
        # bounded alphabetic tie-break without implying preferred IUPAC.
        oriented=list(chosen.get('proof',{}).get('input_word',split_blocks(s)))
        positions=[{'block_index':i+1,'primitive_block':block} for i,block in enumerate(oriented)]
        sync_trace={
            'seniority': {'backbone_first':True,
                          'cap_alphabetization_scope':'simple_CAP_LABELS_ONLY'},
            'path': {'direction':chosen['direction'],
                     'rotation_blocks':chosen['rotation_blocks'],
                     'repeat_count_multiplier':chosen['repeat_count_multiplier'],
                     'repeat_count_offset':chosen['repeat_count_offset']},
            'locant': {'basis':'oriented_port_to_port_parser_block_positions_not_chemical_locants',
                       'input_block_count':len(split_blocks(s)),
                       'oriented_primitive_blocks':oriented,
                       'block_positions':positions,
                       'unit_label':chosen['unit_label']},
            'tie_break': {'ordered_keys':['alpha_cap_alphabetical',
                                          'omega_cap_alphabetical','proof_serialization'],
                          'candidate_assignments_considered':len(alternatives),
                          'selected_candidate_key':stable_json(chosen)},
            'end_groups_synchronized':True,
            'candidate_only':True,
            'preferred_iupac_name':None,
        }
        return {'status':'PARSED','profile':PROFILE,
            'name_candidate':f'alpha-{a}-omega-{b}-poly({chosen["unit_label"]})',
            'direction_mapping':chosen,'equivalent_cap_assignments':alternatives,
            'selection_trace':sync_trace,
            'input_basis':{'unit_smiles':s,'end_groups':dict(ends)},
            'rule_refs':[RULE_SOURCE,'PROJECT-BOUNDED-CRU-CANDIDATE','PROJECT-PORT-WORD-CONJUGACY'],
            'scope':'end_capped_regular_single_chain_candidate',
            'backbone_is_iupac_preferred':False,'preferred_iupac_name':None,
            'full_iupac_conformance':False,'exact_material_identity':False,
            'chain_length_inferred':False,'graph_basis_verified_at_scope':True,
            'independent_chemical_review':False}
    except (ValueError,RuntimeError,KeyError,IndexError) as exc:
        return fail(str(exc),'UNSUPPORTED')
