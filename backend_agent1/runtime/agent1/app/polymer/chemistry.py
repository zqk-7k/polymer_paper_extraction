"""Finite molecular graphs. Never silently erase isotope, salt or stereo."""
from __future__ import annotations
from functools import lru_cache
from rdkit import Chem,rdBase
from rdkit.Chem import rdMolDescriptors,Draw
from .common import key,fail
class ChemistryError(ValueError):pass

def read_molecule(smiles:str,allow_ports=False):
    if not isinstance(smiles,str) or not smiles.strip():raise ChemistryError('EMPTY_SMILES')
    if len(smiles)>20000:raise ChemistryError('INPUT_LIMIT')
    if '|' in smiles:raise ChemistryError('CXSMILES_NOT_SUPPORTED')
    params=Chem.SmilesParserParams();params.parseName=False
    with rdBase.BlockLogs():mol=Chem.MolFromSmiles(smiles,params)
    if mol is None:raise ChemistryError('INVALID_SMILES')
    if mol.GetNumAtoms()>1000:raise ChemistryError('ATOM_LIMIT')
    if mol.GetStereoGroups():raise ChemistryError('ENHANCED_STEREO_NOT_SUPPORTED')
    if not allow_ports and any(a.GetAtomicNum()==0 for a in mol.GetAtoms()):raise ChemistryError('WILDCARD_REQUIRES_UNIT_SCOPE')
    if any(a.GetNumRadicalElectrons() for a in mol.GetAtoms()):raise ChemistryError('RADICAL_NOT_SUPPORTED')
    for a in mol.GetAtoms():a.SetAtomMapNum(0)
    return mol

@lru_cache(maxsize=50000)
def canonicalize(smiles:str):
    try:
        m=read_molecule(smiles);s=Chem.MolToSmiles(m,canonical=True,isomericSmiles=True)
        return {'status':'PARSED','isomeric_smiles':s,'molecule_key':key('finite-molecule/rdkit-'+rdBase.rdkitVersion,s),'formula':rdMolDescriptors.CalcMolFormula(m),'scope':'encoded_finite_graph','evidence_status':'COMPUTED_GRAPH_NOT_NAME_VERIFICATION','atom_count':m.GetNumAtoms()}
    except (ChemistryError,ValueError,RuntimeError) as exc:return fail(str(exc),'INVALID')

def svg(smiles:str,width=440,height=220):
    m=read_molecule(smiles,allow_ports=True);d=Draw.MolDraw2DSVG(width,height);d.DrawMolecule(m);d.FinishDrawing();return d.GetDrawingText()

def compare_molecules(left,right):
    a=canonicalize(left);b=canonicalize(right)
    if a['status']!='PARSED' or b['status']!='PARSED':return fail('MOLECULE_UNRESOLVED','PARTIAL',left=a,right=b)
    return {'status':'PARSED','relation':'EQUAL' if a['molecule_key']==b['molecule_key'] else 'DIFFERENT','scope':'encoded_finite_graph','left':a,'right':b,'exact_material_identity':False}
