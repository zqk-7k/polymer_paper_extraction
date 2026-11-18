"""Model proposes nomenclature; generic graph checks never certify its rule review."""
from copy import deepcopy
from rdkit import Chem
from .supplied_fragment_join import assemble
from .periodic import canonicalize_unit

CONTRACT = 'model-proposed-polymer-name/1.0'


def enclose(text):
    left, right = ('{','}') if '[' in text else ('[',']') if '(' in text else ('(',')')
    return left+text+right


def exact_key(smiles):
    params = Chem.SmilesParserParams(); params.removeHs = False; params.parseName = False
    mol = Chem.MolFromSmiles(smiles, params)
    if mol is None: return None
    for atom in mol.GetAtoms(): atom.SetAtomMapNum(0)
    return Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)


def graph_relation(left, right, periodic=False):
    a, b = exact_key(left), exact_key(right)
    if not a or not b: return 'UNSUPPORTED'
    if a == b: return 'GRAPH_MATCH'
    # The old periodic key is achiral. Never let it erase supplied chemistry.
    if periodic:
        for text in (left, right):
            mol = Chem.MolFromSmiles(text)
            if any(x.GetIsotope() or x.GetFormalCharge() or x.GetNumRadicalElectrons() or
                   x.GetChiralTag() != Chem.ChiralType.CHI_UNSPECIFIED for x in mol.GetAtoms()) or any(
                   x.GetStereo() != Chem.BondStereo.STEREONONE for x in mol.GetBonds()):
                return 'UNSUPPORTED'
        p, q = canonicalize_unit(left), canonicalize_unit(right)
        if p.get('status') != 'PARSED' or q.get('status') != 'PARSED': return 'UNSUPPORTED'
        if p['periodic_graph_key'] == q['periodic_graph_key']: return 'GRAPH_MATCH'
    return 'MISMATCH'


def check_structure_proposal(kernel, proposal, target):
    profile=proposal.get('subunit_parser_contract')
    if profile is not None and profile!='iupac-substituted-acyclic-diyl/1.0':
        raise ValueError('UNKNOWN_SUBUNIT_PARSER_CONTRACT')
    if profile and proposal.get('contract')!='identity-model-nomenclature/1.1':
        raise ValueError('EXPLICIT_CURRENT_MODEL_CONTRACT_FOR_SUBUNIT_PROFILE_REQUIRED')
    parts = proposal.get('parts')
    if not isinstance(parts, list) or not 1 <= len(parts) <= 12:
        raise ValueError('EXPLICIT_NAMED_SUBUNITS_REQUIRED')
    checks, fragments, links = [], [], []
    for i, part in enumerate(parts):
        name = part.get('name')
        if not isinstance(name, str) or not name.strip() or len(name) > 500:
            raise ValueError('SUBUNIT_NAME_REQUIRED')
        mol = Chem.MolFromSmiles(part.get('smiles', ''))
        ports = [a.GetAtomMapNum() for a in mol.GetAtoms() if a.GetAtomicNum() == 0] if mol else []
        if len(ports) != 2 or set(ports) != {part.get('left_port'), part.get('right_port')} or len(set(ports)) != 2:
            raise ValueError('EXPLICIT_TWO_SUBUNIT_PORTS_REQUIRED')
        local = kernel.parser._resolve_unit(name)
        parsed, provider = local, 'LOCAL_UNIT_PARSER'
        if local.get('status') != 'PARSED':
            parsed = kernel.provider.resolve_divalent_unit(name)
            provider = 'OPSIN_EXPLICIT_DIVALENT'
        if profile and parsed.get('status') in ('UNSUPPORTED','INVALID'):
            from .substituted_diyl import resolve
            scoped=resolve(kernel,name)
            if scoped.get('status')=='PARSED':
                scoped['prior_parser_result']=parsed
                parsed,provider=scoped,'SCOPED_ACYCLIC_SUBSTITUENT_COMPOSITION'
            elif scoped.get('reason_code')!='ACYCLIC_SUBSTITUTED_DIYL_OUTSIDE_PROFILE':
                parsed={**scoped,'prior_parser_result':parsed};provider='SCOPED_ACYCLIC_SUBSTITUENT_COMPOSITION'
        relation = graph_relation(part['smiles'], parsed['unit_smiles']) if parsed.get('status') == 'PARSED' and parsed.get('unit_smiles') else 'UNSUPPORTED'
        checks.append({'name': name, 'status': relation, 'provider': provider,
                       'local_result': local, 'parser_result': parsed,
                       'comparison_scope': 'exact_subunit_attachment_sites_and_encoded_chemistry'})
        fragments.append({'id': 'u'+str(i), 'smiles': part['smiles'], 'src': part['src']})
        if i:
            links.append({'left': {'fragment': 'u'+str(i-1), 'port': parts[i-1]['right_port']},
                          'right': {'fragment': 'u'+str(i), 'port': part['left_port']},
                          'bond': 'single', 'src': list(dict.fromkeys(parts[i-1]['src']+part['src']))})
    assembly = assemble(fragments, links) if len(parts) > 1 else {
        'status': 'ASSEMBLED_CANDIDATE', 'product_smiles': parts[0]['smiles'], 'single_supplied_unit': True}
    whole = graph_relation(target, assembly['product_smiles'], periodic=True) if assembly.get('status') == 'ASSEMBLED_CANDIDATE' else 'UNSUPPORTED'
    # Render the proposed ordered subunits, rather than accept an unrelated free string.
    text = 'poly'+enclose(parts[0]['name']) if len(parts) == 1 else 'poly'+enclose(''.join(enclose(p['name']) for p in parts))
    tacticity = proposal.get('tacticity') if proposal.get('contract') == 'identity-model-nomenclature/1.1' else None
    if tacticity:
        prefixes = {'isotactic': 'it-', 'syndiotactic': 'st-', 'atactic': 'at-'}
        if tacticity.get('value') not in prefixes:
            raise ValueError('RELATIVE_TACTICITY_VALUE_REQUIRED')
        text = prefixes[tacticity['value']] + text
    mismatch = whole == 'MISMATCH' or any(c['status'] == 'MISMATCH' for c in checks) or proposal.get('text') != text
    status = 'MISMATCH' if mismatch else ('GRAPH_MATCH' if whole == 'GRAPH_MATCH' and all(c['status'] == 'GRAPH_MATCH' for c in checks) else 'TOOL_COVERAGE_GAP')
    return {'contract': CONTRACT, 'status': status, 'text': text,
            'subunit_checks': checks, 'whole_graph_check': whole, 'assembly': assembly,
            'tacticity_check': {'status': 'MODEL_SOURCE_RULE_REVIEWED' if tacticity else 'NOT_DECLARED',
                               'declaration': deepcopy(tacticity), 'graph_proves_chain_tacticity': False},
            'model_rule_review': deepcopy(proposal.get('rule_review')),
            'rule_review_origin': 'SAME_PRIMARY_MODEL_NOT_INDEPENDENT_REVIEW',
            'preferred_iupac_name': None, 'full_iupac_conformance': False,
            'independent_review': 'NOT_REVIEWED'}
