"""Dianhydride + diamine -> ported polyimide cell under an EXPLICIT hypothesis.
Anhydride O atoms leave; both nitrogen atoms originate from the diamine. A
single original diamine C-N bond becomes the cell seam, preserving atom origin.
No implicit hydrolysis, cyclization, yield, sequence or material identity claim.
"""
from rdkit import Chem
from rdkit.Chem import rdMolDescriptors
from .chemistry import read_molecule
from .common import fail
from .periodic import canonicalize_unit

ANHYDRIDE=Chem.MolFromSmarts('[C;R](=[O])-[O;R]-[C;R](=[O])')
AMINE=Chem.MolFromSmarts('[N;H2;D1;!$(N-C=O)]')


def sites(m):
    matches={x[2]:x for x in m.GetSubstructMatches(ANHYDRIDE)}
    return list(matches.values()), [x[0] for x in m.GetSubstructMatches(AMINE)]


def compile_imide(inputs):
    raw=inputs.get('reactants_smiles');evidence=inputs.get('evidence',inputs.get('evidence_kind'))
    if not evidence:return fail('EXPLICIT_IMIDIZATION_HYPOTHESIS_REQUIRED','NEEDS_DETAILS')
    if not isinstance(raw,list) or len(raw)!=2:return fail('TWO_EXPLICIT_REACTANT_GRAPHS_REQUIRED','NEEDS_DETAILS')
    try:
        mols=[read_molecule(s) for s in raw]
        symmetry=[list(Chem.CanonicalRankAtoms(m,breakTies=False)) for m in mols]
        # RDKit can encode fused dianhydrides as aromatic. Use an equivalent
        # Kekule representation for reactive-site matching and bond editing;
        # sanitize the final graph to restore the normal aromaticity model.
        for mol in mols:
            Chem.Kekulize(mol, clearAromaticFlags=True)
        if any(len(Chem.GetMolFrags(m))!=1 for m in mols):return fail('CONNECTED_REACTANTS_REQUIRED')
        if any(a.GetChiralTag()!=Chem.ChiralType.CHI_UNSPECIFIED or a.GetIsotope() or a.GetFormalCharge() for m in mols for a in m.GetAtoms()):
            return fail('IMIDE_STEREO_ISOTOPE_CHARGE_OUT_OF_SCOPE')
        choices=[]
        for di,ai in ((0,1),(1,0)):
            an,_=sites(mols[di]);_,amines=sites(mols[ai])
            if len(an)==2 and len(amines)==2:choices.append((di,ai,an,amines))
        if len(choices)!=1:return fail('UNIQUE_DIANHYDRIDE_DIAMINE_PAIR_REQUIRED','AMBIGUOUS')
        di,ai,an,amines=choices[0];d,a=mols[di],mols[ai]
        # Symmetric endpoints permit no hidden regioisomer selection.
        dr,ar=symmetry[di],symmetry[ai]
        assignment=inputs.get('endpoint_assignment')
        if assignment is not None:
            if assignment not in ([0,1],[1,0]):return fail('INVALID_ENDPOINT_ASSIGNMENT','INVALID')
            amines=[amines[i] for i in assignment]
        elif dr[an[0][2]]!=dr[an[1][2]] or ar[amines[0]]!=ar[amines[1]]:
            return fail('ASYMMETRIC_IMIDE_ENDPOINTS_REQUIRE_EXPLICIT_ORIENTATION','AMBIGUOUS')
        off=d.GetNumAtoms();rw=Chem.RWMol(Chem.CombineMols(d,a));remove=[];trace=[]
        original_neighbor=a.GetAtomWithIdx(amines[1]).GetNeighbors()[0].GetIdx()+off
        n2=amines[1]+off
        rw.RemoveBond(n2,original_neighbor)
        for group,ni in zip(an,amines):
            c1,oxo1,leaving,c2,oxo2=group;nitrogen=ni+off
            rw.AddBond(c1,nitrogen,Chem.BondType.SINGLE);rw.AddBond(c2,nitrogen,Chem.BondType.SINGLE)
            # N hydrogens are removed in imidization (no isotope/labeled-H scope).
            rw.GetAtomWithIdx(nitrogen).SetNumExplicitHs(0)
            remove.append(leaving)
            trace.append({'nitrogen_from_reactant':ai,'nitrogen_atom_index':ni,
                          'anhydride_from_reactant':di,'carbonyl_atom_indices':[c1,c2],
                          'leaving_oxygen_atom_index':leaving})
        for label,idx in ((1,n2),(2,original_neighbor)):
            atom=Chem.Atom(0);atom.SetAtomMapNum(label);j=rw.AddAtom(atom);rw.AddBond(idx,j,Chem.BondType.SINGLE)
        for idx in sorted(remove,reverse=True):rw.RemoveAtom(idx)
        result=rw.GetMol();Chem.SanitizeMol(result);sm=Chem.MolToSmiles(result,isomericSmiles=True)
        return {'status':'PARSED','repeat_smiles':sm,'repeat_fragment_smiles':sm,'port_count':2,
                'reaction_class':'imidization','rule_id':'RX-SYMMETRIC-IMIDIZATION/0.3',
                'support_type':'RULE_DERIVED_UNDER_EXPLICIT_HYPOTHESIS','evidence':evidence,
                'periodic':canonicalize_unit(sm),'atom_edit_trace':trace,
                'formal_byproducts_per_cell':['H2O','H2O'],
                'reactant_formulas':[rdMolDescriptors.CalcMolFormula(x) for x in mols],
                'no_element_transmutation':True,'not_a_prediction_of_experimental_product':True,
                'exact_material_identity':False}
    except (ValueError,RuntimeError,KeyError,TypeError) as exc:
        return fail('IMIDIZATION_GRAPH_ERROR','INVALID',detail=str(exc))
