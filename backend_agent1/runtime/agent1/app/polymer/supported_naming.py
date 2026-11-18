"""Opt-in IUPAC rule profiles, independent from frozen candidate selection.

Source nomenclature and a saturated acyclic hydrocarbon CRU profile only.
Unimplemented seniority, stereo and end-direction rules cannot pass by roundtrip.
"""
from copy import deepcopy
import re
from rdkit import Chem
from .naming import render_ast
from .source_naming_validation import CONTRACT as IDENTITY_CONTRACT
from .name_validation import check_name

CONTRACT = 'iupac-supported-naming/1.1'
GUIDE = 'https://iupac.qmul.ac.uk/BriefGuide/polymer.html'
RSSOP = 'https://iupac.qmul.ac.uk/rssop/ss05.html'
CONNECTIVES = {'co','stat','ran','alt','per','block','graft','blend'}
QUALIFIERS = {'isotactic','syndiotactic','atactic','linear','branch','star','net','cyclo'}
# Well-established monomer names permitted by source nomenclature, not polymer
# structure answers. Other names must satisfy the implemented local grammar.
RETAINED_MONOMERS = {'styrene','acrylonitrile','methacrylonitrile','ethylene','propylene',
    'butadiene','isoprene','vinyl chloride','vinyl acetate','methyl methacrylate',
    'ethyl methacrylate','methyl acrylate','ethyl acrylate','acrylic acid','methacrylic acid',
    'ethylene oxide','buta-1,3-diene'}


def source_rules(kernel, text):
    parsed=kernel.parse({'name':text,'interpretation_policy':'evidence_only'})
    checks=[]
    def add(rule,passed,detail=None):checks.append({'rule':rule,'status':'PASS' if passed else 'OUTSIDE_SCOPE','detail':detail})
    add('IUPAC-BG-2012:3 source-name parsing',parsed.get('status')=='PARSED')
    from .registry import local_rule_chain
    def visit(node):
        kind=node.get('kind')
        if kind=='source':
            name=node.get('raw','').strip()
            try:recognized=bool(local_rule_chain(name))
            except (ValueError,KeyError,TypeError):recognized=False
            add('IUPAC-BG-2012:3.1 monomer nomenclature',recognized or name.lower() in RETAINED_MONOMERS,name)
        elif kind=='connective':add('IUPAC-BG-2012:Tables 1-2 connective',node.get('operator') in CONNECTIVES,node.get('operator'))
        elif kind=='qualifier':add('IUPAC-BG-2012:qualifier scope',node.get('qualifier') in QUALIFIERS,node.get('qualifier'))
        elif kind=='end_groups':add('IUPAC-BG-2012:end groups',False,'End-group orientation not validated by this source profile')
        elif kind not in ('polymer','group'):add('IUPAC-BG-2012:supported syntax',False,kind)
        for child in node.get('children',[]):visit(child)
    if parsed.get('ast'):visit(parsed['ast'])
    else:add('source AST',False)
    return {'profile':'iupac-source-homopolymer-copolymer-assembly/1.0',
            'status':'PASS' if checks and all(x['status']=='PASS' for x in checks) else 'OUTSIDE_SCOPE',
            'checks':checks,'source_url':GUIDE,'preferred_name_selection':'NOT_ASSERTED'}


def structure_name(kernel, smiles):
    from .periodic import canonicalize_unit, reverse_unit, assemble, port_mol
    from .graph_naming_v09 import label_divalent, name_unit
    from .cru_locant_selection import locant_selection
    p=canonicalize_unit(smiles)
    result={'contract':CONTRACT,'basis':'structure','status':'NO_NAME','primary':None,
            'preferred_iupac_name':None,'independent_review':'NOT_REVIEWED','source_url':RSSOP}
    if p.get('status')!='PARSED':return {**result,'reason_code':'REPEAT_GRAPH_OUTSIDE_KERNEL_SCOPE'}
    unit=p['canonical_repeat_smiles'];m=Chem.MolFromSmiles(unit)
    atoms=[a for a in m.GetAtoms() if a.GetAtomicNum()]
    simple=bool(atoms) and not m.GetRingInfo().NumRings() and all(
        a.GetAtomicNum()==6 and not a.GetFormalCharge() and not a.GetIsotope() and not a.GetNumRadicalElectrons()
        and a.GetChiralTag()==Chem.ChiralType.CHI_UNSPECIFIED for a in atoms) and all(
        b.GetBondType()==Chem.BondType.SINGLE and b.GetStereo()==Chem.BondStereo.STEREONONE for b in m.GetBonds())
    if simple:
        # The older graph labeler also generates branched substituent candidates.
        # Roundtrip does not establish their substituent nomenclature. This
        # profile therefore validates only terminal, straight C1-C4 pendants.
        mol,ports=port_mol(unit)
        path=set(Chem.GetShortestPath(mol,ports[0],ports[1]))
        seen=set()
        for atom in path:
            for adjacent in mol.GetAtomWithIdx(atom).GetNeighbors():
                start=adjacent.GetIdx()
                if start in path or start in seen:continue
                pending=[start];branch=set()
                while pending:
                    current=pending.pop()
                    if current in branch or current in path:continue
                    branch.add(current)
                    pending.extend(a.GetIdx() for a in mol.GetAtomWithIdx(current).GetNeighbors())
                seen|=branch
                if (len(branch)>4 or any(mol.GetAtomWithIdx(a).GetDegree()>2 for a in branch)
                        or sum(n.GetIdx() in branch for n in mol.GetAtomWithIdx(start).GetNeighbors())>1):
                    simple=False
    if not simple:
        candidate=name_unit(unit)
        return {**result,'status':'CANDIDATE' if candidate.get('structure_based_name_candidate') else 'NO_NAME',
                'primary':({'text':candidate['structure_based_name_candidate'],'kind':'structure_based',
                            'qualification':'CONSISTENCY_CANDIDATE'} if candidate.get('structure_based_name_candidate') else None),
                'reason_code':'FEATURE_OR_SUBSTITUENT_NAMING_RULES_NOT_COMPLETE', 'candidate_check':candidate}
    names=[];traces=[]
    blocks=p['primitive_blocks']
    orientations=set()
    for sequence in (blocks,[reverse_unit(x) for x in reversed(blocks)]):
        for i in range(len(sequence)):
            orientations.add(assemble(sequence[i:]+sequence[:i]))
    for oriented in sorted(orientations):
        decision=locant_selection(oriented)
        mol,ports=port_mol(oriented)
        path=list(Chem.GetShortestPath(mol,ports[0],ports[1]))[1:-1]
        # Compute locants in the named, mapped-port direction. The older local
        # checker numbers by atom indices, which are not the port orientation.
        locants=sorted(i for i,a in enumerate(path,1) for n in mol.GetAtomWithIdx(a).GetNeighbors()
                       if n.GetIdx() not in path and n.GetIdx() not in ports)
        one=len(path)==1
        if not one and decision.get('status')!='DECIDED':continue
        # Only alkyl pendants on a saturated carbon-chain subunit. All atoms are
        # accounted for by the complete graph parser below, not a label lookup.
        label=label_divalent(oriented)
        if not label:continue
        name='poly('+label+')'
        parsed=kernel.parse({'name':name,'interpretation_policy':'evidence_only'})
        if parsed.get('semantic_projection',{}).get('constitution_key')!=p['periodic_graph_key']:continue
        rank=tuple(locants)
        names.append((rank,name));traces.append({'orientation':oriented,'locant_decision':decision,'name':name})
    if not names:return {**result,'reason_code':'NO_RULE_CHECKED_SUBUNIT_NAME'}
    best=min(x[0] for x in names);winners=set(n for r,n in names if r==best)
    if len(winners)!=1:return {**result,'status':'CANDIDATE','reason_code':'RULE_SELECTION_TIE','alternatives':sorted(winners),'rule_trace':traces}
    text=next(iter(winners))
    return {**result,'status':'IUPAC_AT_DECLARED_SCOPE','primary':{'text':text,'kind':'structure_based',
        'qualification':'IUPAC_AT_DECLARED_SCOPE','scope':'saturated_acyclic_carbon_chain_with_terminal_linear_C1_C4_pendants_constitution_only'},
        'rule_checks':{'status':'PASS','minimal_period':True,'complete_graph_roundtrip':True,
                       'all_primitive_cuts_and_directions':len(orientations),
                       'rules':['RSSOP 2002 §5.1 Rule 11','IUPAC-BG-2012 §4.1']},
        'rule_trace':traces,'omitted_fields':['stereochemistry','end_groups','sample_identity'],
        'full_iupac_conformance':False}


def name(kernel, passport):
    result={'contract':CONTRACT,'primary':None,'alternatives':[],'unverified':[],
            'preferred_iupac_name':None,'full_iupac_conformance':False,'independent_review':'NOT_REVIEWED'}
    if not passport:return {**result,'reason_code':'PASSPORT_NOT_CREATED'}
    original=passport.get('evidence',{}).get('original_name')
    parsed=kernel.parse({'name':original,'interpretation_policy':'evidence_only'})
    if parsed.get('status')!='PARSED':return {**result,'reason_code':'NAME_INPUT_UNRESOLVED'}
    # Build an explicitly derived name using source AST and supported attributes.
    # This avoids mutating the old frozen display snapshot with missing labels.
    text=render_ast(parsed['ast'])
    attrs=passport['chemical_core'].get('attributes',{})
    tacticity=attrs.get('tacticity',{})
    if tacticity.get('knowledge_status')=='specified' and tacticity.get('value') in ('isotactic','syndiotactic','atactic'):
        if not re.match(r'^(?:isotactic|syndiotactic|atactic)-',text):text=tacticity['value']+'-'+text
    outcome=check_name(kernel,passport,text,'source_based',contract=IDENTITY_CONTRACT)
    rules=source_rules(kernel,text)
    candidate={'text':text,'kind':'source_based','scope':'source_definition_and_reported_identity_qualifiers',
               'origin':'DERIVED_SOURCE_AST_AND_IDENTITY_ATTRIBUTES','validation':outcome,'rule_validation':rules,
               'qualification':'IUPAC_AT_DECLARED_SCOPE' if outcome['accepted'] and rules['status']=='PASS' else 'CONSISTENCY_CANDIDATE',
               'independent_review':'NOT_REVIEWED','preferred_iupac_name':None}
    if outcome['accepted']:
        result.update(primary=candidate,reason_code=None if rules['status']=='PASS' else 'NAMING_RULE_SCOPE_INCOMPLETE')
    else:result.update(unverified=[candidate],reason_code=outcome.get('reason_code','IDENTITY_CHECK_FAILED'))
    constitution=passport['chemical_core'].get('constitution_model') or {}
    smi=constitution.get('canonical_repeat_smiles') or constitution.get('ported_unit_basis')
    if smi:
        structural=structure_name(kernel,smi);result['structure_naming']=structural
        if structural.get('primary'):result['alternatives'].append(structural['primary'])
    return result
