"""Explicit finite, end-capped chain models. No chain length is guessed.

Segments are oriented two-port CU graphs, NOT free monomer SMILES. This entry
point does no reaction inference and no material identification. It preserves
occurrence IDs, atom provenance and the user's explicit model evidence.
"""
from __future__ import annotations
from rdkit import Chem
from .periodic import port_mol, reverse_unit
from .chemistry import canonicalize
from .common import fail

CAPS = {'hydro': None, 'hydroxy': 'O', 'methoxy': 'OC', 'ethoxy': 'OCC',
        'amino': 'N', 'methyl': 'C', 'chloro': 'Cl', 'bromo': 'Br'}
MAX_SEGMENTS = 64
MAX_REPEATS = 256
MAX_ATOMS = 1000


def resolve_end_group(label):
    """Chemical fragment candidate for a written cap, not a finite macromolecule."""
    from .advanced_names import rooted, _unwrap
    if not isinstance(label,str):return fail('END_GROUP_MUST_BE_TEXT','INVALID')
    text=_unwrap(label)
    if text=='hydro':return {'status':'PARSED','kind':'TERMINAL_HYDROGEN','rooted_smiles':'[*][H]','review_status':'DRAFT'}
    try:
        fragment=rooted(text)
        if fragment:
            # Explicit cap fragments do not inherit any polymer chain length.
            return {'status':'PARSED','kind':'ROOTED_CAP_CANDIDATE','rooted_smiles':fragment,'review_status':'DRAFT'}
    except (ValueError,RuntimeError,KeyError,IndexError):pass
    return fail('END_GROUP_NAME_OUTSIDE_GRAMMAR','NEEDS_DETAILS',raw=label)


def end_group_contexts(parsed):
    """List each end-group scope without collecting siblings into a single chain."""
    out=[]
    def visit(n):
        if n.get('kind')=='end_groups':
            out.append({'scope_id':n['occurrence_id'], 'span':n['span'],
                        'alpha':n['alpha'], 'omega':n['omega'],
                        'child_scope_id':n['children'][0]['occurrence_id'],
                        'orientation_anchored':True,
                        'alpha_resolution':n.get('alpha_resolution',resolve_end_group(n['alpha'])),
                        'omega_resolution':n.get('omega_resolution',resolve_end_group(n['omega'])),
                        'delimiter_form':n.get('delimiter_form','standard_hyphen'),
                        'repeat_count':None, 'finite_molecule_key':None,
                        'knowledge_status':'END_GROUPS_DESCRIBED_CHAIN_LENGTH_NOT_REPORTED'})
        for child in n.get('children',[]):visit(child)
    if parsed.get('ast'):visit(parsed['ast'])
    return out


def _validate(inputs):
    if inputs.get('sequence') not in (None,'explicit','block'):
        return fail('UNSPECIFIED_SEQUENCE_CANNOT_BUILD_UNIQUE_FINITE_CHAIN','NEEDS_DETAILS')
    evidence=inputs.get('evidence')
    if not isinstance(evidence,str) or not evidence.strip():
        return fail('EXPLICIT_MODEL_EVIDENCE_REQUIRED','NEEDS_DETAILS')
    segments=inputs.get('segments');ends=inputs.get('end_groups')
    if not isinstance(segments,list) or not 1<=len(segments)<=MAX_SEGMENTS:
        return fail('SEGMENT_LIST_REQUIRED_OR_LIMIT','INVALID')
    if not isinstance(ends,dict) or set(ends)!={'alpha','omega'}:
        return fail('BOTH_END_GROUPS_REQUIRED','NEEDS_DETAILS')
    if any(not isinstance(x,str) or x not in CAPS for x in ends.values()):
        return fail('END_GROUP_OUTSIDE_SUPPORTED_CAPS','UNSUPPORTED',supported=sorted(CAPS))
    ids=set();total=0;atoms=0;prepared=[];missing=[]
    for i,segment in enumerate(segments):
        if not isinstance(segment,dict):return fail('SEGMENT_OBJECT_REQUIRED','INVALID')
        ident=segment.get('id');n=segment.get('repeat_count');s=segment.get('unit_smiles')
        if not isinstance(ident,str) or not ident or ident in ids:
            return fail('MISSING_OR_DUPLICATE_SEGMENT_ID','INVALID')
        ids.add(ident)
        if n is None:
            missing.append(f'segments[{i}].repeat_count');continue
        if type(n) is not int or n<1 or n>MAX_REPEATS:
            return fail('POSITIVE_INTEGER_REPEAT_COUNT_REQUIRED','INVALID')
        if not isinstance(s,str):return fail('EXPLICIT_UNIT_SMILES_REQUIRED','NEEDS_DETAILS',segment_id=ident)
        orientation=segment.get('orientation','forward')
        if orientation not in ('forward','reverse'):return fail('INVALID_ORIENTATION','INVALID')
        # Finite end assignment cannot silently use parser atom order as a direction.
        p=Chem.SmilesParserParams();p.parseName=False
        raw=Chem.MolFromSmiles(s,p)
        if raw is None:return fail('INVALID_UNIT_SMILES','INVALID',segment_id=ident)
        labels=[a.GetAtomMapNum() for a in raw.GetAtoms() if a.GetAtomicNum()==0]
        if sorted(labels)!=[1,2]:return fail('EXPLICIT_UNIQUE_PORT_LABELS_1_2_REQUIRED','INVALID',segment_id=ident)
        try:
            m,ports=port_mol(s)
            if orientation=='reverse':
                ports=list(reversed(ports))
                for label,p in enumerate(ports,1):m.GetAtomWithIdx(p).SetAtomMapNum(label)
        except (ValueError,RuntimeError) as exc:
            return fail(str(exc),'UNSUPPORTED',segment_id=ident)
        if any(m.GetAtomWithIdx(p).GetNeighbors()[0].GetAtomicNum()==0 for p in ports):
            return fail('EMPTY_UNIT_NOT_ALLOWED','INVALID')
        total+=n;atoms+=(m.GetNumAtoms()-2)*n
        if total>MAX_REPEATS or atoms+4>MAX_ATOMS:
            return fail('FINITE_MODEL_SIZE_LIMIT','UNSUPPORTED')
        prepared.append((ident,n,orientation,m,ports))
    if missing:return fail('CHAIN_LENGTH_NOT_REPORTED','NEEDS_DETAILS',missing_fields=missing,
                           finite_molecule_key=None,exact_material_identity=False)
    return prepared


def compile_finite_chain(inputs):
    checked=_validate(inputs)
    if isinstance(checked,dict):return checked
    try:
        combined=None;bounds=[];offset=0;instances=[]
        for ident,n,orientation,m,ports in checked:
            for repeat in range(1,n+1):
                molecule=Chem.Mol(m)
                instance=f'{ident}:{repeat}'
                for a in molecule.GetAtoms():
                    a.SetProp('_origin_scope',instance)
                    a.SetIntProp('_unit_atom_index',a.GetIdx())
                bounds.append([offset+p for p in ports])
                combined=molecule if combined is None else Chem.CombineMols(combined,molecule)
                offset+=molecule.GetNumAtoms()
                instances.append({'instance_id':instance,'segment_id':ident,'repeat_index':repeat,
                                  'orientation':orientation,'ports_consumed_or_capped':[1,2]})
        rw=Chem.RWMol(combined);remove=[];joins=[]
        for i in range(len(bounds)-1):
            lp,rp=bounds[i][1],bounds[i+1][0]
            u=rw.GetAtomWithIdx(lp).GetNeighbors()[0].GetIdx()
            v=rw.GetAtomWithIdx(rp).GetNeighbors()[0].GetIdx()
            rw.AddBond(u,v,Chem.BondType.SINGLE);remove.extend([lp,rp])
            joins.append({'left_instance':instances[i]['instance_id'],'left_port':2,
                          'right_instance':instances[i+1]['instance_id'],'right_port':1,
                          'bond_type':'SINGLE'})
        ends=inputs['end_groups'];cap_trace=[]
        for role,p in [('alpha',bounds[0][0]),('omega',bounds[-1][1])]:
            atom=rw.GetAtomWithIdx(p);neighbor=atom.GetNeighbors()[0].GetIdx()
            name=ends[role];sm=CAPS[name]
            if sm:
                cm=Chem.MolFromSmiles(sm)
                for a in cm.GetAtoms():
                    a.SetProp('_origin_scope','end:'+role)
                    a.SetIntProp('_unit_atom_index',a.GetIdx())
                off=rw.GetNumAtoms();rw=Chem.RWMol(Chem.CombineMols(rw.GetMol(),cm))
                rw.AddBond(neighbor,off,Chem.BondType.SINGLE)
            cap_trace.append({'role':role,'name':name,
                              'attached_to_instance':instances[0 if role=='alpha' else -1]['instance_id'],
                              'consumed_port':1 if role=='alpha' else 2,
                              'encoding':'implicit_terminal_H' if sm is None else 'explicit_cap_atoms'})
            remove.append(p)
        for p in sorted(remove,reverse=True):rw.RemoveAtom(p)
        m=rw.GetMol();Chem.SanitizeMol(m)
        finite=canonicalize(Chem.MolToSmiles(m,canonical=True,isomericSmiles=True))
        if finite['status']!='PARSED':return finite
        provenance=[]
        for a in m.GetAtoms():
            a.SetAtomMapNum(a.GetIdx()+1)
            provenance.append({'atom_map':a.GetAtomMapNum(),'element':a.GetSymbol(),
                               'instance_id':a.GetProp('_origin_scope'),
                               'input_unit_atom_index':a.GetIntProp('_unit_atom_index')})
        return {**finite,'scope':'EXPLICIT_FINITE_CHAIN_MODEL',
                'finite_molecule_key':finite['molecule_key'],
                'mapped_smiles':Chem.MolToSmiles(m,canonical=True,isomericSmiles=True),
                'atom_provenance':provenance,'segment_instances':instances,
                'segment_occurrence_count':len(checked),'unit_instance_count':len(instances),
                'junctions':joins,'end_group_trace':cap_trace,
                'evidence':inputs['evidence'],'support_type':'USER_SPECIFIED_FINITE_MODEL',
                'reaction_inferred':False,'actual_sample_verified':False,
                'exact_material_identity':False,'whole_periodic_constitution_key':None,
                'preferred_iupac_name':None,
                'exclusions':['actual_chain_length_distribution','actual_junction_defects',
                              'sample_identity','full_IUPAC_preferred_name']}
    except (ValueError,RuntimeError,IndexError) as exc:
        return fail('FINITE_MODEL_COMPILATION_FAILED','INVALID',detail=str(exc))
