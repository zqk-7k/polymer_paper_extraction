"""Enumerate bounded local step-growth cells without first-match orientation.

Four acid/nucleophile endpoint assignments (two for imidization) are evaluated.
Only equal canonical periodic keys are grouped. Counts are NOT global sequence
probabilities or a complete enumeration of realistic polymer microstructures.
"""
from __future__ import annotations
from collections import Counter
from rdkit import Chem
from .chemistry import read_molecule
from .periodic import canonicalize_unit
from .common import fail

PAIR_RULES={'condensation_ester','condensation_amide','polyurethane','polyurea','imidization'}
ACID=Chem.MolFromSmarts('[C](=[O])-[O;H1]')
ACYL_CHLORIDE=Chem.MolFromSmarts('[C](=[O])-[Cl]')
ISOCYANATE=Chem.MolFromSmarts('[N]=[C]=[O]')
AMINE=Chem.MolFromSmarts('[N;H2;D1;!$(N-C=O)]')
ALCOHOL=Chem.MolFromSmarts('[O;H1;D1;!$(O-C=O)]')


def counts(m):
    out=Counter()
    for a in Chem.AddHs(m).GetAtoms():
        if a.GetAtomicNum():out[a.GetSymbol()]+=1
    return out


def _port(rw,idx,label):
    a=Chem.Atom(0);a.SetAtomMapNum(label);j=rw.AddAtom(a);rw.AddBond(idx,j,Chem.BondType.SINGLE)


def enumerate_pair(inputs):
    rule=inputs.get('reaction_class');evidence=inputs.get('evidence',inputs.get('evidence_kind'))
    raw=inputs.get('reactants_smiles')
    if rule not in PAIR_RULES:return fail('PAIR_REACTION_NOT_SUPPORTED')
    if not isinstance(evidence,str) or not evidence.strip():return fail('EXPLICIT_HYPOTHESIS_OR_EVIDENCE_REQUIRED','NEEDS_DETAILS')
    if not isinstance(raw,list) or len(raw)!=2:return fail('TWO_EXPLICIT_REACTANT_GRAPHS_REQUIRED','NEEDS_DETAILS')
    try:
        mols=[read_molecule(s) for s in raw]
        if any(len(Chem.GetMolFrags(m))!=1 for m in mols):return fail('CONNECTED_REACTANTS_REQUIRED')
        if any(a.GetChiralTag()!=Chem.ChiralType.CHI_UNSPECIFIED or a.GetIsotope() or a.GetFormalCharge() for m in mols for a in m.GetAtoms()):
            return fail('PAIR_STEREO_ISOTOPE_CHARGE_OUT_OF_SCOPE')
        if any(b.GetStereo()!=Chem.BondStereo.STEREONONE for m in mols for b in m.GetBonds()):return fail('PAIR_BOND_STEREO_OUT_OF_SCOPE')
        before=counts(mols[0])+counts(mols[1]);attempts=[]
        if rule=='imidization':
            from .imidization import compile_imide
            for assignment in ([0,1],[1,0]):
                result=compile_imide({**inputs,'endpoint_assignment':assignment})
                if result.get('status')!='PARSED':return result
                after=counts(Chem.MolFromSmiles(result['repeat_smiles']))+Counter({'H':4,'O':2})
                result['element_balance']={'before':dict(before),'product_plus_byproducts':dict(after),'passed':before==after}
                if before!=after:return fail('ELEMENT_BALANCE_FAILED','INVALID')
                attempts.append({'assignment':assignment,'result':result})
        else:
            is_iso=rule in ('polyurethane','polyurea')
            nuc_pat=AMINE if rule in ('condensation_amide','polyurea') else ALCOHOL
            choices=[]
            for ai,ni in ((0,1),(1,0)):
                acid_sites=list(mols[ai].GetSubstructMatches(ISOCYANATE)) if is_iso else list(mols[ai].GetSubstructMatches(ACID))+list(mols[ai].GetSubstructMatches(ACYL_CHLORIDE))
                nu_sites=list(mols[ni].GetSubstructMatches(nuc_pat))
                if len(acid_sites)==2 and len(nu_sites)==2:choices.append((ai,ni,acid_sites,nu_sites))
            if len(choices)!=1:return fail('UNIQUE_BIFUNCTIONAL_PAIR_REQUIRED','AMBIGUOUS')
            ai,ni,acids,nus=choices[0];off=mols[ai].GetNumAtoms()
            for acid_order in ([0,1],[1,0]):
                for nu_order in ([0,1],[1,0]):
                    aa=[acids[i] for i in acid_order];nn=[nus[i][0]+off for i in nu_order]
                    rw=Chem.RWMol(Chem.CombineMols(mols[ai],mols[ni]));removed=[];byproducts=[];lost=Counter()
                    if is_iso:
                        centers=[a[1] for a in aa]
                        for n,c,o in aa:rw.GetBondBetweenAtoms(n,c).SetBondType(Chem.BondType.SINGLE)
                    else:
                        centers=[a[0] for a in aa]
                        for c,o,l in aa:
                            el=rw.GetAtomWithIdx(l).GetSymbol();removed.append(l)
                            if el=='O':byproducts.append('H2O');lost.update({'H':2,'O':1})
                            else:byproducts.append('HCl');lost.update({'H':1,'Cl':1})
                    rw.AddBond(centers[0],nn[0],Chem.BondType.SINGLE)
                    _port(rw,nn[1],1);_port(rw,centers[1],2)
                    for idx in sorted(removed,reverse=True):rw.RemoveAtom(idx)
                    m=rw.GetMol();Chem.SanitizeMol(m);s=Chem.MolToSmiles(m,isomericSmiles=True)
                    after=counts(m)+lost
                    if before!=after:return fail('ELEMENT_BALANCE_FAILED','INVALID',before=dict(before),after=dict(after))
                    result={'status':'PARSED','repeat_smiles':s,'repeat_fragment_smiles':s,'port_count':2,
                            'periodic':canonicalize_unit(s),'reaction_class':rule,'rule_id':'RX-LOCAL-ORIENTATION-ENUMERATION/0.4',
                            'support_type':'RULE_DERIVED_UNDER_EXPLICIT_HYPOTHESIS','evidence':evidence,
                            'formal_byproducts_per_cell':byproducts,
                            'element_balance':{'before':dict(before),'product_plus_byproducts':dict(after),'passed':True},
                            'atom_edit_trace':[{'reactant_order':[ai,ni], 'acyl_or_isocyanate_site_atoms':[list(x) for x in aa],
                                               'nucleophile_atom_indices':[x-off for x in nn],
                                               'removed_atoms_in_electrophile':removed}],
                            'not_a_prediction_of_experimental_product':True,'exact_material_identity':False}
                    attempts.append({'assignment':{'electrophile_order':acid_order,'nucleophile_order':nu_order},'result':result})
        groups={}
        for i,attempt in enumerate(attempts):
            r=attempt['result'];p=r.get('periodic',{})
            # Unsupported periodic comparison must not collapse unrelated candidates.
            graph_key=p.get('periodic_graph_key') if p.get('status')=='PARSED' else 'uncompared-'+str(i)
            if graph_key not in groups:groups[graph_key]={'result':r,'endpoint_assignments':[],'comparison_scope':p.get('scope','NOT_COMPARABLE')}
            groups[graph_key]['endpoint_assignments'].append(attempt['assignment'])
        return {'status':'PARSED','scope':'local_pair_orientation_candidates','reaction_class':rule,'candidates':list(groups.values()),
                'raw_assignment_count':len(attempts),'distinct_candidate_count':len(groups),
                'whole_constitution_key':None,'global_sequence':None,'product_fractions':None,
                'actual_reaction_verified':False,'equal_fractions_assumed':False,'exact_material_identity':False,
                'limitations':['local_cells_only','not_all_global_regiosequences','unspecified_new_stereocenters','no_sample_identity']}
    except (ValueError,RuntimeError,KeyError,TypeError,IndexError) as exc:return fail('PAIR_GRAPH_ERROR','INVALID',detail=str(exc))
