"""Versioned adoption of model proposals with explicit tool coverage and rule reasoning."""
from copy import deepcopy
from .storage import digest, file_hash
from .diagnostics import attach

CONTRACT = 'identity-model-nomenclature/1.0'
CURRENT_CONTRACT = 'identity-model-nomenclature/1.1'
CONTRACTS = (CONTRACT, CURRENT_CONTRACT)
TOPICS = {'subunit_identity', 'numbering', 'cru_selection', 'direction', 'syntax', 'product_identity'}
RULE_URLS = ('https://iupac.qmul.ac.uk/', 'https://iupac.org/', 'https://goldbook.iupac.org/',
             'https://publications.iupac.org/', 'https://doi.org/10.1515/pac-')


def context_hash(material, candidate, contract=CONTRACT, proposal=None):
    from .adoption import enabled, context as adoption_context
    if enabled(candidate):
        return digest(adoption_context(material,candidate,naming=True,proposal=proposal))
    ignored = {'review','kernel_passport','kernel_naming','kernel_rule_naming','kernel_inputs',
               'naming_verification','iupac_assessment','nomenclature_declaration','most_likely_name','tool_evidence'}
    def body(m, dependency=False):
        return {'material': {k:v for k,v in m.items() if k not in ignored},
                'graphs': {g:candidate['graphs'].get(g) for g in m.get('graph_ids',[])},
                'dependency_name':m.get('most_likely_name') if dependency else None}
    dependencies = {}
    pending = [x.get('material_id') for x in material.get('components',[])]
    if contract == CURRENT_CONTRACT:
        source = ((material.get('nomenclature_declaration') or {}).get('proposal') or {}).get('source_declaration') or {}
        pending += [source.get('base_material_id'), source.get('branch_material_id')]
        pending += [r.get('from_material_id') for r in candidate.get('relations', []) if r.get('to_material_id') == material['id']]
    seen = {material['id']}
    while pending:
        mid = pending.pop()
        if mid in seen or mid not in candidate['materials']: continue
        seen.add(mid); other = candidate['materials'][mid]; dependencies[mid] = body(other,True)
        pending.extend(x.get('material_id') for x in other.get('components',[]))
    context = {'current':body(material),'dependencies':dependencies,
                   'relations':candidate.get('relations',[]),'source_facts':candidate.get('source_facts',[]),
                   'unknowns':candidate.get('unknowns',[])}
    if contract == CURRENT_CONTRACT: context['source_conflicts'] = candidate.get('source_conflicts', [])
    return digest(context)


def proposal_errors(proposal, material):
    errors = []
    current = proposal.get('contract') == CURRENT_CONTRACT
    if proposal.get('contract', CONTRACT) not in CONTRACTS: errors.append('UNKNOWN_MODEL_NAMING_CONTRACT')
    if not proposal.get('text') or proposal.get('kind') not in ('structure_polymer','evidence_name'):
        errors.append('NAMING_TEXT_ROUTE_REQUIRED')
    refs = proposal.get('source_refs',[])
    if not refs or not set(refs).issubset(set(material.get('source_refs',[]))): errors.append('NAMING_SOURCE_BINDING_REQUIRED')
    bases = ('source_supported','broader_scope','most_likely_hypothesis') + (('feasible_hypothesis',) if current else ())
    if proposal.get('evidence_basis') not in bases: errors.append('NAMING_EVIDENCE_BASIS_REQUIRED')
    if proposal.get('evidence_basis') in ('most_likely_hypothesis','feasible_hypothesis') and not proposal.get('hypotheses'): errors.append('NAMING_HYPOTHESES_REQUIRED')
    if current and proposal.get('evidence_basis') == 'most_likely_hypothesis':
        ranking = proposal.get('hypothesis_ranking') or {}
        if not ranking.get('alternatives') or not ranking.get('reason') or not ranking.get('source_refs') or not set(ranking['source_refs']).issubset(set(refs)):
            errors.append('MOST_LIKELY_REQUIRES_SOURCED_ALTERNATIVE_RANKING')
    for h in proposal.get('hypotheses',[]):
        if not h.get('statement') or not h.get('reason') or not h.get('source_refs') or not set(h['source_refs']).issubset(set(refs)): errors.append('SOURCED_NAMING_HYPOTHESIS_REQUIRED')
    review = proposal.get('rule_review',[])
    required = TOPICS if proposal.get('kind') == 'structure_polymer' else {'syntax','product_identity'}
    if current and proposal.get('kind') == 'evidence_name': required = required | {'scope'}
    if current and proposal.get('tacticity'):
        t = proposal['tacticity']; required = required | {'tacticity'}
        if not t.get('reason') or not t.get('source_refs') or not set(t['source_refs']).issubset(set(refs)):
            errors.append('SOURCED_RELATIVE_TACTICITY_REQUIRED')
    if not isinstance(review,list) or not required.issubset({x.get('topic') for x in review if isinstance(x,dict)}): errors.append('NAMING_RULE_REVIEW_REQUIRED')
    for x in review if isinstance(review,list) else []:
        if not x.get('reason') or x.get('conclusion') not in ('supported','assumed','broader_scope','unresolved') or not x.get('rule_ref','').startswith(RULE_URLS): errors.append('EXPLICIT_RULE_REASON_REQUIRED')
    if any(x.get('conclusion') == 'unresolved' for x in review if isinstance(x,dict)): errors.append('UNRESOLVED_RULE_REQUIRES_REVISED_OR_BROADER_NAME')
    if current and any(x.get('conclusion') == 'assumed' for x in review if isinstance(x,dict)) and proposal.get('evidence_basis') not in ('feasible_hypothesis','most_likely_hypothesis'):
        errors.append('ASSUMED_RULE_MUST_REMAIN_HYPOTHETICAL')
    if current and proposal.get('kind') == 'structure_polymer':
        known = (material.get('identity_attributes') or {}).get('tacticity')
        if known in ('isotactic','syndiotactic','atactic') and (proposal.get('tacticity') or {}).get('value') != known:
            errors.append('DECLARED_TACTICITY_MUST_BE_PRESERVED')
    if not proposal.get('product_identity_check') or not proposal.get('selection_reason'): errors.append('FINAL_PRODUCT_NAMING_REASON_REQUIRED')
    return list(dict.fromkeys(errors))


def _review_proposal(kernel, material, candidate, proposal):
    contract = proposal.get('contract', CONTRACT)
    diagnostics = []
    errors = proposal_errors(proposal,material)
    if contract == CURRENT_CONTRACT:
        from .source_conflicts import naming_conflict_errors
        errors.extend(naming_conflict_errors(material, candidate, proposal, diagnostics))
    if errors:
        exc = ValueError(';'.join(errors)); exc.diagnostics = diagnostics
        raise exc
    if proposal['kind'] == 'structure_polymer':
        gid = proposal.get('graph_id'); g = candidate['graphs'].get(gid)
        if not g or gid not in material.get('graph_ids',[]) or g['scope'] != 'repeat_unit' or (material.get('constitution') or {}).get('graph_id') != gid or (material.get('constitution') or {}).get('coverage') != 'ideal_repeat': raise ValueError('WHOLE_IDEAL_REPEAT_REQUIRED')
        for part in proposal.get('parts',[]):
            if not part.get('src') or not set(part['src']).issubset(set(proposal['source_refs'])): raise ValueError('SUBUNIT_SOURCE_BINDING_REQUIRED')
        from polymer.naming_service import NamingService
        checked = NamingService(kernel).check_model_structure(proposal,g['canonical_smiles'])
        if checked['status'] == 'MISMATCH': return {'status':'MISMATCH','formal_name':None,'checks':checked}
        if checked['whole_graph_check'] != 'GRAPH_MATCH':
            return {'status':'NEEDS_EVIDENCE','formal_name':None,'checks':checked,
                    'reason_code':'WHOLE_PROPOSED_CONSTITUTION_CHECK_REQUIRED'}
        status = 'MODEL_STRUCTURE_GRAPH_CHECKED' if checked['status'] == 'GRAPH_MATCH' else 'MODEL_RULE_REVIEWED_WITH_TOOL_GAPS'
    else:
        from .nomenclature import assess
        declaration = proposal.get('source_declaration') or {}
        if contract == CURRENT_CONTRACT and proposal.get('name_scope') == 'class_based':
            if material.get('kind') not in ('polymer','prepolymer','oligomer','network'):
                raise ValueError('POLYMER_CLASS_MATERIAL_REQUIRED')
            if proposal.get('evidence_basis') != 'broader_scope' or not proposal.get('identity_qualifiers'):
                raise ValueError('CLASS_NAME_REQUIRES_BROAD_SCOPE_AND_PRODUCT_QUALIFIERS')
            if declaration or not proposal['text'].startswith('poly') or any(x in proposal['text'] for x in ('-co-', '-graft-', '-blend-')):
                raise ValueError('CLASS_NAME_CANNOT_ASSERT_SPECIFIC_SOURCES_OR_TOPOLOGY')
            checked = {'status':'MODEL_CLASS_SCOPE_REVIEWED', 'identity_qualifiers':deepcopy(proposal['identity_qualifiers']),
                       'tool_coverage':'CLASS_NAME_RULES_NOT_IMPLEMENTED_BY_LOCAL_PARSER',
                       'product_constitution_inferred':False}
            status = 'MODEL_CLASS_NAME_REVIEWED_WITH_TOOL_GAPS'
        else:
            contracts = ('identity-evidence-nomenclature/1.0','identity-evidence-nomenclature/1.1') + (('identity-evidence-nomenclature/1.3','identity-evidence-nomenclature/1.4','identity-evidence-nomenclature/1.5') if contract == CURRENT_CONTRACT else ())
            if declaration.get('contract') not in contracts: raise ValueError('EXPLICIT_EVIDENCE_NAME_DECLARATION_REQUIRED')
            if declaration.get('kind')=='matrix_with_components' and proposal.get('name_scope')!='polymer_matrix':
                raise ValueError('PRIMARY_MATRIX_NAME_SCOPE_REQUIRED')
            checked = assess(kernel,{**material,'nomenclature_declaration':declaration},candidate)
            if not checked or checked.get('formal_name') != proposal['text']: return {'status':'MISMATCH','formal_name':None,'checks':checked}
            if contract == CURRENT_CONTRACT and checked.get('hypotheses') and proposal.get('evidence_basis') not in ('feasible_hypothesis','most_likely_hypothesis'):
                raise ValueError('INHERITED_NAMING_HYPOTHESIS_MUST_BE_PRESERVED')
            status = 'MODEL_EVIDENCE_NAME_REVIEWED'
    hypotheses = deepcopy(proposal.get('hypotheses',[]))
    for h in checked.get('hypotheses',[]):
        if h not in hypotheses: hypotheses.append(deepcopy(h))
    from .source_conflicts import conflicts_for
    return {'contract':contract,'status':status,'formal_name':proposal['text'],'primary':proposal['text'],
            'proposal':deepcopy(proposal),'context_sha256':context_hash(material,candidate,contract,proposal),
            'adoption_policy':candidate.get('adoption_policy'),
            'checks':checked,'hypotheses':hypotheses,
            'evidence_basis':proposal['evidence_basis'],'conflict_review':deepcopy(proposal.get('conflict_review')),
            'source_conflicts':deepcopy(conflicts_for(material,candidate)),
            'tool_graph_match':status == 'MODEL_STRUCTURE_GRAPH_CHECKED',
            'rule_review_origin':'SAME_PRIMARY_MODEL_NOT_INDEPENDENT_REVIEW',
            'full_iupac_conformance':False,'preferred_iupac_name':None,'independent_review':'NOT_REVIEWED',
            'source_url':next((x['rule_ref'] for x in proposal['rule_review'] if x['topic']=='scope'),'https://iupac.qmul.ac.uk/rssop/'),
            'identity_qualifiers':deepcopy(checked.get('identity_qualifiers',[])),
            'scope':checked['scope'] if proposal.get('source_declaration',{}).get('kind')=='matrix_with_components' else 'model_rule_review_with_explicit_tool_coverage_and_preserved_source_unknowns'}


def review_proposal(kernel, material, candidate, proposal):
    try:
        return _review_proposal(kernel, material, candidate, proposal)
    except ValueError as exc:
        attach(exc, stage='review_naming', material_id=material.get('id'), path='proposal', error_codes=str(exc).split(';'))
        raise


def assessment(material, candidate):
    from pathlib import Path
    d = material['nomenclature_declaration']; r = candidate.get('tool_receipts',{}).get(d.get('review_receipt_id'),{})
    path = Path(r.get('receipt_path',''))
    fail = {'contract':d.get('contract'),'status':'NEEDS_EVIDENCE','formal_name':None,'primary':None}
    if r.get('operation') != 'review_naming' or r.get('exit_code') != 0 or not r.get('stored_from_actual_operation') or not path.is_file() or file_hash(path) != r.get('sha256'): return {**fail,'reason_code':'ACTUAL_NAMING_REVIEW_RECEIPT_REQUIRED'}
    out = deepcopy(r.get('result') or {})
    if out.get('adoption_policy') != candidate.get('adoption_policy'):
        return {**fail,'reason_code':'NAMING_ADOPTION_POLICY_CHANGED'}
    if out.get('contract') != d.get('contract') or r['input'].get('material_id') != material['id'] or digest(r['input'].get('proposal')) != digest(d.get('proposal')) or out.get('context_sha256') != context_hash(material,candidate,d.get('contract')): return {**fail,'reason_code':'NAMING_PROPOSAL_OR_CONTEXT_CHANGED'}
    out['primary_matches_display'] = out.get('formal_name') == (material.get('most_likely_name') or {}).get('text')
    return out
