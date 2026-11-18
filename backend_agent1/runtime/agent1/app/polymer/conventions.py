"""Explicitly scoped idealized-name interpretation, not experimental identity.

RSSOP 2002 §11.2 supplies common source/structure-name correspondences. This
profile implements a bounded analogue rule and labels its assumptions. It is
not a reaction inference service. `evidence_only` disables this projection.
No catalog/test records are read, and ambiguous functionality is not guessed.
"""
from __future__ import annotations
from functools import lru_cache
from rdkit import Chem
from .periodic import canonicalize_unit
from .reactions import derive
from .common import fail

SOURCE = 'https://iupac.qmul.ac.uk/rssop/ss10n11.html#11.2'
PROFILE = 'IDEALIZED_COMMON_CHAIN/0.3'
EXCLUSIONS = ['stereoregularity', 'end_groups', 'minor_connectivity_defects',
              'molar_mass_distribution', 'branching_defects', 'material_composition', 'sample_identity']


@lru_cache(maxsize=20000)
def from_source(smiles: str, lexical_name: str = '') -> dict:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None or len(Chem.GetMolFrags(mol)) != 1:
        return fail('CONVENTION_CONNECTED_GRAPH_REQUIRED')
    if any(a.GetChiralTag() != Chem.ChiralType.CHI_UNSPECIFIED or a.GetIsotope() or a.GetFormalCharge() for a in mol.GetAtoms()):
        return fail('CONVENTION_STEREO_ISOTOPE_OR_CHARGE_OUT_OF_SCOPE')
    if any(b.GetStereo() != Chem.BondStereo.STEREONONE for b in mol.GetBonds()):
        return fail('CONVENTION_STEREO_OUT_OF_SCOPE')
    canon = Chem.MolToSmiles(mol)
    sm = None; rule = None; derived = None
    # The glycol usage is a traditional product descriptor, NOT a claim that
    # ethylene glycol was the experimentally polymerized monomer.
    if canon == 'OCCO' and lexical_name in ('ethylene glycol', 'ethane-1,2-diol'):
        sm = '*OCC*'; rule = 'TRADITIONAL_PEG_BACKBONE_MODEL'
    elif canon == 'C=O':
        sm = '*OC*'; rule = 'RSSOP_COMMON_POLYOXYMETHYLENE'
    else:
        alkenes = [b for b in mol.GetBonds() if b.GetBondType() == Chem.BondType.DOUBLE
                   and b.GetBeginAtom().GetAtomicNum() == b.GetEndAtom().GetAtomicNum() == 6]
        competing = [
            '[C;R]1[O;R][C;R]1',  # epoxide can polymerize instead of alkene
            '[N]=[C]=[O]', '[C;H1](=O)', '[C]#[C]',
        ]
        if len(alkenes) == 1 and not alkenes[0].IsInRing() and not any(mol.HasSubstructMatch(Chem.MolFromSmarts(p)) for p in competing):
            bond = alkenes[0]
            # A saturated H2/halogen-substituted terminus; internal alkene
            # regiochemistry is outside the conventional-analogue profile.
            terminal = any(all(n.GetIdx()==other.GetIdx() or n.GetAtomicNum() in (9,17,35,53)
                               for n in atom.GetNeighbors())
                           for atom,other in [(bond.GetBeginAtom(),bond.GetEndAtom()),(bond.GetEndAtom(),bond.GetBeginAtom())])
            if terminal:
                derived = derive({'monomer_smiles':smiles,'reaction_class':'vinyl_addition',
                                  'regioselectivity':'head_to_tail','evidence':'NAMING_CONVENTION_MODEL_NOT_FORMATION_FACT'})
                rule = 'COMMON_VINYL_HEAD_TO_TAIL_MODEL'
        elif not alkenes and mol.GetRingInfo().NumRings() == 1:
            rings=mol.GetRingInfo().AtomRings()
            # Only the unambiguous, saturated three-membered cyclic ether is
            # implicit here. Larger cyclic ethers require explicit formation.
            if len(rings[0]) == 3 and sum(mol.GetAtomWithIdx(i).GetAtomicNum()==8 for i in rings[0]) == 1 and all(b.GetBondType()==Chem.BondType.SINGLE for b in mol.GetBonds()):
                derived = derive({'monomer_smiles':smiles,'reaction_class':'ring_opening_ether',
                                  'evidence':'NAMING_CONVENTION_MODEL_NOT_FORMATION_FACT'})
                rule = 'COMMON_OXIRANE_POLYETHER_MODEL'
    if derived and derived['status']=='PARSED': sm=derived['repeat_smiles']
    if not sm: return fail('NO_UNAMBIGUOUS_COMMON_CHAIN_CONVENTION','NEEDS_DETAILS')
    periodic=canonicalize_unit(sm)
    if periodic['status']!='PARSED':return periodic
    return {'status':'PARSED','repeat_smiles':sm,'periodic':periodic,
            'profile':PROFILE,'rule_id':rule,'reference':SOURCE,
            'scope':'idealized_unoriented_achiral_constitution',
            'support_type':'NAMING_CONVENTION_MODEL','excluded_fields':EXCLUSIONS,
            'source_binding_independently_reviewed':False,
            'experimental_formation_inferred':False,'exact_material_identity':False,
            'assumptions':['regular_chain_model','head_to_tail_where_applicable','no_sample_specific_connectivity_asserted']}


def apply(parsed: dict, policy: str = 'evidence_only') -> dict:
    if policy not in ('idealized_common_chain','evidence_only'):
        return fail('UNKNOWN_INTERPRETATION_POLICY','INVALID')
    parsed['interpretation_policy']=policy
    if policy=='evidence_only' or parsed.get('status')!='PARSED':return parsed
    leaves=parsed.get('components',[])
    def disallowed(n):
        return n.get('kind') in ('end_groups','qualifier','polymer_class') or bool(n.get('operator')) or any(disallowed(c) for c in n.get('children',[]))
    if len(leaves)!=1 or disallowed(parsed.get('ast',{})):return parsed
    # Only a polymer wrapper conveys this conventional meaning. A naked source
    # molecule is not turned into a polymer merely because it is polymerizable.
    def wrapper(n):return n.get('kind')=='polymer' or any(wrapper(c) for c in n.get('children',[]))
    if not wrapper(parsed.get('ast',{})):return parsed
    leaf=leaves[0]
    if leaf['kind']!='source':return parsed
    result=from_source(leaf['molecule']['isomeric_smiles'],leaf['raw'])
    if result['status']=='PARSED':
        parsed['idealized_constitution']=result
        p=parsed['semantic_projection'];p['constitution_key']=result['periodic']['periodic_graph_key']
        p['constitution_support']='NAMING_CONVENTION_MODEL';p['constitution_scope']=result['scope']
        p['constitution_excluded_fields']=EXCLUSIONS
    return parsed
