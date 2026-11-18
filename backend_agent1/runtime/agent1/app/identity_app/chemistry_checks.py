"""Typed adapters into the existing kernel. Checks do not certify IUPAC PINs."""
from copy import deepcopy
import re
from rdkit import Chem
from polymer.naming_service import NamingService
from polymer.name_validation import check_name
from polymer.passport import create_passport
from polymer.component_profile import describe_component
from polymer.supplied_constitution import CONTRACT as SUPPLIED
from .storage import digest

CONTRACT = 'identity-foundation/1.1'
RULE_CONTRACTS = ('iupac-supported-naming/1.0', 'iupac-supported-naming/1.1')

def source_only_oligomer(m,candidate):
    d=m.get('structure_expression') or {}
    current=candidate.get('naming_policy')=='iupac-model-assisted/1.1' or (m.get('nomenclature_declaration') or {}).get('contract')=='identity-model-nomenclature/1.1'
    return current and m.get('kind')=='oligomer' and d.get('contract')=='product-structure-expression/1.0' and d.get('kind')=='source_only'

def graph_profile(g):
    role = 'source' if g['scope'] == 'finite_molecule' else 'unit' if g['scope'] == 'repeat_unit' else 'fragment'
    result = describe_component({'smiles': g['canonical_smiles'], 'kind': role, 'label': g.get('id')}, image=False)
    result['encoded_scope'] = g['scope']
    return result

def compare_graphs(kernel, left, right, scope):
    if scope == 'finite_molecule':
        result = kernel.dispatch('compare_molecules', {'left': left, 'right': right})
        status = ('GRAPH_MATCH' if result.get('relation') == 'EQUAL' else 'MISMATCH') if result.get('status') == 'PARSED' else 'UNSUPPORTED'
    elif scope == 'repeat_unit':
        a = kernel.dispatch('canonicalize_unit', {'smiles': left})
        b = kernel.dispatch('canonicalize_unit', {'smiles': right})
        result = {'left': a, 'right': b, 'scope': 'infinite_unoriented_achiral_constitution'}
        status = ('GRAPH_MATCH' if a['periodic_graph_key'] == b['periodic_graph_key'] else 'MISMATCH') if a.get('status') == b.get('status') == 'PARSED' else 'UNSUPPORTED'
    else:
        return {'status': 'NOT_APPLICABLE', 'reason_code': 'LOCAL_SCOPE_NOT_WHOLE_NAME', 'scope': scope}
    return {'status': status, 'comparison': result, 'scope': scope, 'atom_maps_are_correspondence_not_identity': True,
            'exact_material_identity': False, 'preferred_iupac_name': None}

def name_graph(kernel, g, rule_contract='iupac-supported-naming/1.1'):
    if rule_contract not in RULE_CONTRACTS+('iupac-triazine-graph-candidate/1.0','iupac-regular-unit-graph-candidate/1.0'):
        raise ValueError('RULE_CONTRACT_NOT_ENABLED_EXPLICIT_SNAPSHOT_REQUIRED')
    if g['scope'] == 'finite_molecule':
        return kernel.dispatch('name_source_graph', {'smiles': g['canonical_smiles']})
    if g['scope'] == 'repeat_unit':
        return NamingService(kernel).name_structure(g['canonical_smiles'], rule_contract=rule_contract)
    return {'status': 'NOT_APPLICABLE', 'reason_code': 'LOCAL_SCOPE_NOT_WHOLE_NAME',
            'preferred_iupac_name': None, 'scope': g['scope']}

def finite_scope(spec, graphs):
    gid = spec.get('graph_id')
    if gid:
        g = graphs.get(gid)
        if not g or g['scope'] != 'finite_molecule' or g.get('ports'):
            raise ValueError('FINITE_GRAPH_REQUIRED')
        return g
    if spec.get('scope') != 'finite_molecule':
        raise ValueError('DECLARED_FINITE_SCOPE_REQUIRED')
    name = spec.get('name', '')
    if re.search(r'(?i)\bpoly\w*|graft|copolymer|network|\[\*|\(\*', name):
        raise ValueError('POLYMER_NAME_NOT_FINITE_LOOKUP')
    return None

def parser_check(kernel, name, graph, parser=None, receipt=None):
    result = parser if parser is not None else kernel.dispatch('resolve_name_opsin', {'name': name})
    if result.get('status') != 'PARSED':
        return {'status': 'UNSUPPORTED', 'reason_code': result.get('reason_code', 'PARSER_NOT_PARSED'),
                'parser_result': result, 'reused_receipt': receipt, 'independent_review': 'NOT_REVIEWED'}
    smiles = result.get('isomeric_smiles') or result.get('candidate_smiles')
    check = compare_graphs(kernel, graph['canonical_smiles'], smiles, 'finite_molecule')
    return {**check, 'name': name, 'graph_id': graph['id'], 'parser_result': result,
            'reused_receipt': receipt, 'parser_success_is_not_pin': True, 'independent_review': 'NOT_REVIEWED'}

def passport_inputs(m, candidate):
    name = (m.get('most_likely_name') or {})
    raw = name.get('text') if name.get('basis') == 'structure_based' else m.get('passport_name') or name.get('text') or m['label']
    refs = m.get('source_refs', [])
    selected = {gid: deepcopy(candidate['graphs'][gid]) for gid in m.get('graph_ids', []) if gid in candidate['graphs']}
    # Preserve unmapped facts in evidence. Never coerce a sample/mixture ratio into a CRU fraction.
    evidence = {'kind': 'CURRENT_MATERIAL_STRUCTURED_FACTS', 'contract': CONTRACT,
                'material_id': m['id'], 'kind_declared': m['kind'], 'source_refs': refs,
                'graphs': [{k: v for k, v in g.items() if k not in ('depiction', 'chemical_profile')} for g in selected.values()],
                'components': deepcopy(m.get('components', [])), 'composition': deepcopy(m.get('composition')),
                'relationships': deepcopy(m.get('relationships', [])),
                'relations': deepcopy([r for r in candidate.get('relations', []) if m['id'] in
                                       [r.get('material_id'), r.get('from'), r.get('to'), r.get('from_material_id'), r.get('to_material_id'), *r.get('material_ids', [])]]),
                'preparation': deepcopy(m.get('preparation')), 'source_facts': deepcopy(m.get('evidence_facts', [])),
                'scoped_source_facts': deepcopy([f for f in candidate.get('source_facts', []) if isinstance(f, dict) and m['id'] in
                                               [f.get('material_id'), f.get('from'), f.get('to'), *f.get('material_ids', [])]]),
                'unassigned_common_source_facts': deepcopy([f for f in candidate.get('source_facts', []) if not isinstance(f, dict) or
                                                          not any(f.get(k) for k in ('material_id','material_ids','from','to'))]),
                'unmapped_identity_properties': deepcopy(m.get('identity_properties', [])),
                'tool_evidence_refs': deepcopy(m.get('tool_evidence', []))}
    if m.get('nomenclature_declaration'):
        evidence['nomenclature_declaration']=deepcopy(m['nomenclature_declaration'])
    if candidate.get('naming_policy')=='iupac-model-assisted/1.1' or (m.get('nomenclature_declaration') or {}).get('contract')=='identity-model-nomenclature/1.1':
        from .source_conflicts import conflicts_for
        evidence['source_conflicts']=deepcopy(conflicts_for(m,candidate))
    out = {'name': raw, 'interpretation_policy': 'evidence_only', 'naming_profile': 'frozen-name-candidate/0.9.0',
           'source_ref': refs[0] if refs else 'interactive-input',
           'unresolved_segments': [str(x) for x in m.get('unknowns', [])][:128],
           'evidence_assertions': [evidence]}
    attrs = deepcopy(m.get('identity_attributes', {}))
    distribution = (m.get('composition') or {}).get('molecular_weight_distribution', {})
    if isinstance(distribution, dict) and distribution.get('Mn_g_per_mol') is not None:
        attrs.setdefault('number_average_molar_mass', {'value': distribution['Mn_g_per_mol'], 'unit': 'g/mol'})
    if attrs:
        out['attributes'] = attrs
    declaration = m.get('constitution')
    if declaration:
        if name.get('basis') == 'material_expression':
            raise ValueError('MATERIAL_DESCRIPTION_CANNOT_DECLARE_WHOLE_REPEAT')
        gid = declaration.get('graph_id')
        if gid not in selected or selected[gid]['scope'] != 'repeat_unit' or declaration.get('coverage') != 'ideal_repeat':
            raise ValueError('EXPLICIT_WHOLE_REPEAT_DECLARATION_REQUIRED')
        if m['kind'] not in ('polymer', 'prepolymer'):
            raise ValueError('MATERIAL_TYPE_NOT_REGULAR_WHOLE_REPEAT')
        out['supplied_constitution'] = {'contract': SUPPLIED, 'graph_id': gid,
                                      'scope': 'repeat_unit', 'coverage': 'ideal_repeat',
                                      'smiles': selected[gid]['canonical_smiles'],
                                      'source_refs': selected[gid].get('source_refs', refs),
                                      'assumptions': deepcopy(declaration.get('assumptions', []))}
    return out

def verify_name(kernel, m, candidate, passport, saved_parser=None):
    name = (m.get('most_likely_name') or {})
    text, basis = name.get('text'), name.get('basis')
    base = {'contract': CONTRACT, 'name': text, 'basis': basis, 'scope': name.get('scope'),
            'preferred_iupac_name': None, 'full_iupac_conformance': False,
            'independent_review': 'NOT_REVIEWED', 'preferred_cru_selection': 'NOT_COMPLETED'}
    if basis == 'material_expression':
        return {**base, 'status': 'NOT_APPLICABLE', 'reason_code': 'MATERIAL_DESCRIPTION_NOT_FORMAL_NAME'}
    graphs = [candidate['graphs'][gid] for gid in m.get('graph_ids', []) if gid in candidate['graphs']]
    if source_only_oligomer(m,candidate):
        return {**base,'status':'UNSUPPORTED','reason_code':'FINITE_SOURCE_GRAPH_IS_NOT_FINITE_PRODUCT',
                'validation_scope':'source_only_oligomer_family'}
    if m['kind'] in ('component', 'monomer', 'oligomer'):
        stored, ref = saved_parser or (None, None)
        if len(graphs) == 1 and graphs[0]['scope'] == 'finite_molecule':
            return {**base, **parser_check(kernel, text, graphs[0], stored, ref)}
        return {**base, 'status':'UNSUPPORTED',
                'reason_code':stored.get('reason_code','FINITE_GRAPH_NOT_RECEIVED') if stored else 'FINITE_GRAPH_NOT_RECEIVED',
                'parser_result':stored, 'reused_receipt':ref, 'validation_scope':'finite_source_candidate'}
    if not passport:
        return {**base, 'status': 'UNSUPPORTED', 'reason_code': 'POLYMER_PASSPORT_NOT_CREATED'}
    check = check_name(kernel, passport, text, basis)
    if basis == 'structure_based' and not m.get('constitution'):
        return {**base, 'status': 'NOT_APPLICABLE', 'reason_code': 'WHOLE_REPEAT_NOT_DECLARED', 'check': check}
    return {**base, 'status': 'GRAPH_MATCH' if check['accepted'] and basis == 'structure_based' else
            'SOURCE_DESCRIPTOR_MATCH' if check['accepted'] else 'UNSUPPORTED',
            'reason_code': check.get('reason_code'), 'check': check,
            'validation_scope': 'encoded_constitution' if basis == 'structure_based' else 'source_descriptor_not_product_graph'}

def review_material(kernel, m, candidate, saved_parser=None):
    inputs = passport_inputs(m, candidate)
    made = create_passport(kernel, inputs)
    passport = made.get('passport')
    # Bare finite names remain outside polymer passport scope; finite checks are separate.
    naming = NamingService(kernel).name(passport)
    rule_contract = m.get('rule_contract', 'iupac-supported-naming/1.1')
    if rule_contract not in RULE_CONTRACTS:
        raise ValueError('RULE_CONTRACT_NOT_ENABLED_EXPLICIT_SNAPSHOT_REQUIRED')
    rules = NamingService(kernel).name(passport, rule_contract=rule_contract) if passport else {
        'status': 'NOT_APPLICABLE', 'reason_code': 'POLYMER_PASSPORT_NOT_CREATED', 'primary': None}
    validation = verify_name(kernel, m, candidate, passport, saved_parser)
    from .nomenclature import assess
    assessment = assess(kernel, m, candidate)
    from .adoption import enabled, passport_issues
    blocking, gaps = passport_issues(passport) if enabled(candidate) else (
        (passport or {}).get('chemical_core',{}).get('conflicts',[]), [])
    if assessment and gaps:
        assessment['kernel_capability_gaps'] = deepcopy(gaps)
    if assessment and blocking:
        assessment.update(status='NEEDS_EVIDENCE',formal_name=None,reason_code='PASSPORT_FACT_CONFLICT')
    if assessment and assessment.get('formal_name') and assessment.get('primary_matches_display'):
        structural=assessment.get('status')=='STRUCTURE_NAME_SUPPORTED'
        model_review=assessment.get('contract') in ('identity-model-nomenclature/1.0','identity-model-nomenclature/1.1')
        validation.update(status=('MODEL_RULE_REVIEWED' if model_review else 'GRAPH_MATCH' if structural else 'SOURCE_SCOPE_MATCH'), reason_code=None,
                          validation_scope='bounded_ideal_constitution_name_graph_roundtrip' if structural else 'reported_source_nomenclature_not_product_constitution',
                          evidence_nomenclature_contract=assessment['contract'])
        if model_review:
            validation.update(validation_scope=assessment['scope'],tool_graph_match=assessment.get('tool_graph_match',False),
                              model_rule_review=assessment['proposal']['rule_review'],
                              tool_checks=assessment['checks'],rule_review_origin=assessment['rule_review_origin'])
    if assessment and assessment.get('contract') in ('identity-model-nomenclature/1.0','identity-model-nomenclature/1.1') and not assessment.get('formal_name'):
        validation.update(status='MISMATCH' if assessment.get('status')=='MISMATCH' else 'UNSUPPORTED',
                          reason_code=assessment.get('reason_code','MODEL_NAMING_REVIEW_NOT_ACCEPTED'))
    if passport and any(x.get('code') == 'SUPPLIED_GRAPH_NAME_CONSTITUTION_CONFLICT' for x in passport['chemical_core']['conflicts']):
        validation.update(status='MISMATCH', reason_code='SUPPLIED_GRAPH_NAME_CONSTITUTION_CONFLICT')
    return {'iupac_assessment':assessment,
            'kernel_inputs': inputs, 'kernel_passport': made, 'kernel_naming': naming,
            'kernel_rule_naming': rules, 'naming_verification': validation,
            'input_sha256': digest(inputs)}
