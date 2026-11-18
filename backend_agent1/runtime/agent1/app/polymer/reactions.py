"""Graph edits under explicit reaction hypotheses, not synthesis prediction.
Every returned structure carries rule/evidence/hypothesis; no reaction is
inferred just because a name or formula happens to match a catalog record.
"""
from __future__ import annotations
from rdkit import Chem
from rdkit.Chem import rdMolDescriptors
from .chemistry import read_molecule,ChemistryError
from .periodic import canonicalize_unit
from .common import fail
RULES={'vinyl_addition','diene_1_4','diene_1_2','ring_opening_ether','ring_opening_ester','ring_opening_amide','condensation_ester','condensation_amide','polyurethane','polyurea','imidization'}

def _port(rw,atom,label):
    a=Chem.Atom(0);a.SetAtomMapNum(label);i=rw.AddAtom(a);rw.AddBond(atom,i,Chem.BondType.SINGLE)

def _finish(rw,rule,evidence,edits,byproducts=None):
    m=rw.GetMol();Chem.SanitizeMol(m);s=Chem.MolToSmiles(m,canonical=True,isomericSmiles=True)
    period=canonicalize_unit(s)
    return {'status':'PARSED','repeat_smiles':s,'repeat_fragment_smiles':s,'port_count':2,'rule_id':'RX-'+rule+'/0.2','reaction_class':rule,
            'support_type':'RULE_DERIVED_UNDER_EXPLICIT_HYPOTHESIS','evidence':evidence,
            'atom_edit_trace':edits,'formal_byproducts_per_cell':byproducts or [],'periodic':period,
            'not_a_prediction_of_experimental_product':True,'exact_material_identity':False}

def derive(inputs):
    rule=inputs.get('reaction_class')
    if not rule:return fail('REACTION_HYPOTHESIS_REQUIRED','AMBIGUOUS')
    if rule not in RULES:return fail('REACTION_CLASS_NOT_IMPLEMENTED')
    evidence=inputs.get('evidence',inputs.get('evidence_kind'))
    if not evidence:return fail('EXPLICIT_HYPOTHESIS_OR_EVIDENCE_REQUIRED','NEEDS_DETAILS')
    try:
        if rule=='imidization':
            from .imidization import compile_imide
            return compile_imide(inputs)
        if rule.startswith('condensation_') or rule in ('polyurethane','polyurea'):return _bifunctional(inputs,rule,evidence)
        m=read_molecule(inputs['monomer_smiles'])
        if len(Chem.GetMolFrags(m))!=1:return fail('CONNECTED_MONOMER_REQUIRED','AMBIGUOUS')
        if any(a.GetChiralTag()!=Chem.ChiralType.CHI_UNSPECIFIED for a in m.GetAtoms()):return fail('REACTION_STEREO_MAPPING_NOT_IMPLEMENTED')
        candidates=[]
        if rule=='vinyl_addition':
            matches=[b for b in m.GetBonds() if b.GetBondType()==Chem.BondType.DOUBLE and b.GetBeginAtom().GetAtomicNum()==6 and b.GetEndAtom().GetAtomicNum()==6]
            if len(matches)!=1:return fail('ONE_CARBON_DOUBLE_BOND_REQUIRED','AMBIGUOUS',candidate_site_count=len(matches))
            b=matches[0]
            if b.IsInRing():return fail('CYCLIC_ALKENE_ADDITION_OUT_OF_SCOPE')
            if inputs.get('regioselectivity') not in ('head_to_tail','explicit_ports'):return fail('REGIOSELECTIVITY_REQUIRED','NEEDS_DETAILS')
            u,v=b.GetBeginAtomIdx(),b.GetEndAtomIdx();rw=Chem.RWMol(m);rw.GetBondBetweenAtoms(u,v).SetBondType(Chem.BondType.SINGLE);rw.GetBondBetweenAtoms(u,v).SetStereo(Chem.BondStereo.STEREONONE)
            _port(rw,u,1);_port(rw,v,2)
            return _finish(rw,rule,evidence,[{'edit':'reduce_bond','atoms':[u,v],'from':2,'to':1},{'edit':'attach_growth_ports','atoms':[u,v]}])
        if rule in ('diene_1_4','diene_1_2'):
            pat=Chem.MolFromSmarts('[C]=[C]-[C]=[C]');matches=m.GetSubstructMatches(pat)
            groups={tuple(sorted(x)) for x in matches}
            if len(groups)!=1:return fail('UNIQUE_CONJUGATED_DIENE_REQUIRED','AMBIGUOUS')
            a,b,c,d=matches[0]
            if any(m.GetBondBetweenAtoms(x,y).IsInRing() for x,y in [(a,b),(b,c),(c,d)]):return fail('CYCLIC_DIENE_OUT_OF_SCOPE')
            if rule=='diene_1_2' and inputs.get('site') not in ('1,2','3,4'):return fail('DIENE_ADDITION_SITE_REQUIRED','NEEDS_DETAILS')
            if rule=='diene_1_2' and inputs.get('site')=='3,4':a,b,c,d=d,c,b,a
            rw=Chem.RWMol(m);rw.GetBondBetweenAtoms(a,b).SetBondType(Chem.BondType.SINGLE)
            if rule=='diene_1_4':
                rw.GetBondBetweenAtoms(c,d).SetBondType(Chem.BondType.SINGLE);rw.GetBondBetweenAtoms(b,c).SetBondType(Chem.BondType.DOUBLE);ends=[a,d]
            else:ends=[a,b]
            for label,x in enumerate(ends,1):_port(rw,x,label)
            result=_finish(rw,rule,evidence,[{'edit':'diene_connectivity','site_order':[a,b,c,d],'mode':rule}]);result['remaining_double_bond_stereo']='not_specified';return result
        if rule=='ring_opening_ether':
            if any(b.GetBondType()!=Chem.BondType.SINGLE for b in m.GetBonds()):return fail('SATURATED_MONOCYCLIC_ETHER_REQUIRED')
            if m.GetRingInfo().NumRings()!=1:return fail('ONE_RING_REQUIRED','AMBIGUOUS')
            oxy=[a for a in m.GetAtoms() if a.GetAtomicNum()==8 and a.IsInRing() and a.GetDegree()==2]
            if len(oxy)!=1:return fail('ONE_RING_ETHER_OXYGEN_REQUIRED','AMBIGUOUS')
            bonds=[b for b in oxy[0].GetBonds() if b.IsInRing()]
        else:
            hetero='O' if rule=='ring_opening_ester' else 'N'
            pat=Chem.MolFromSmarts('[C;R](=[O])['+hetero+';R]');matches=m.GetSubstructMatches(pat)
            if len(matches)!=1 or m.GetRingInfo().NumRings()!=1:return fail('UNIQUE_CYCLIC_ACYL_HETERO_BOND_REQUIRED','AMBIGUOUS')
            a,o,h=matches[0];bonds=[m.GetBondBetweenAtoms(a,h)]
        for b in bonds:
            u,v=b.GetBeginAtomIdx(),b.GetEndAtomIdx();rw=Chem.RWMol(m);rw.RemoveBond(u,v);_port(rw,u,1);_port(rw,v,2)
            candidates.append(_finish(rw,rule,evidence,[{'edit':'open_ring_bond','atoms':[u,v]}]))
        pkeys={x['periodic'].get('periodic_graph_key',x['repeat_smiles']) for x in candidates}
        if len(pkeys)>1:return fail('MULTIPLE_NON_EQUIVALENT_RING_OPENINGS','AMBIGUOUS',candidates=candidates)
        out=candidates[0];out['equivalent_cut_candidates']=len(candidates);return out
    except (ValueError,RuntimeError,KeyError,TypeError) as exc:return fail(str(exc),'INVALID')

def _bifunctional(inputs,rule,evidence):
    from .pair_candidates import enumerate_pair
    result=enumerate_pair(inputs)
    if result['status']!='PARSED':return result
    if result['distinct_candidate_count']!=1:
        return fail('MULTIPLE_LOCAL_ORIENTATIONS_REQUIRE_EXPLICIT_CHOICE','AMBIGUOUS',
                    candidates=result['candidates'], raw_assignment_count=result['raw_assignment_count'],
                    distinct_candidate_count=result['distinct_candidate_count'], exact_material_identity=False)
    out=dict(result['candidates'][0]['result'])
    out['orientation_enumeration']={'raw_assignments':result['raw_assignment_count'],'distinct_candidates':1}
    return out
