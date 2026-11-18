"""Explicit new-job adoption semantics; historical hashes/gates remain replayable."""
from copy import deepcopy

POLICY = 'identity-adoption/1.3'
SOURCE_POLICY = 'identity-adoption/1.4'
CURRENT_POLICY = 'identity-adoption/1.5'
SUPPORTED_POLICIES = ('identity-adoption/1.2', POLICY, SOURCE_POLICY, CURRENT_POLICY)
DERIVED = {'review', 'kernel_passport', 'kernel_naming', 'kernel_rule_naming',
           'kernel_inputs', 'naming_verification', 'iupac_assessment', 'tool_evidence',
           'change_reason', 'model_naming_proposal', 'identity_preparations'}
GRAPH_DERIVED = {'depiction', 'chemical_profile', 'periodic', 'deterministic_name',
                 'rule_profile_result', 'input_smiles'}


def enabled(candidate):
    return candidate.get('adoption_policy') in SUPPORTED_POLICIES


def declaration(material):
    d = deepcopy(material.get('nomenclature_declaration') or {})
    d.pop('review_receipt_id', None)
    return d


def dependencies(material, candidate, proposal=None):
    d = material.get('nomenclature_declaration') or {}
    p = proposal if proposal is not None else d.get('proposal') or {}
    source = p.get('source_declaration') or d.get('source_declaration') or d
    ids = [x.get('material_id') for x in material.get('components', [])]
    ids += [source.get('base_material_id'), source.get('branch_material_id')]
    ids += [x.get('material_id') for key in ('monomers', 'graft_sources') for x in source.get(key, [])]
    ids += [x.get('source_material_id') for x in source.get('substituents', [])]
    if source.get('contract')=='identity-evidence-nomenclature/1.5':
        ids += [x.get('material_id') for x in source.get('blocks',[]) if isinstance(x,dict)]
    ids += [r.get('from_material_id') for r in candidate.get('relations', [])
            if r.get('to_material_id') == material['id']]
    return [x for x in ids if x in candidate['materials'] and x != material['id']]


def relevant(items, ids):
    """Unscoped evidence stays global; explicitly other-object evidence stays local."""
    out = []
    for item in items or []:
        bound = set()
        if isinstance(item, dict):
            bound.update(item.get('material_ids') or [])
            bound.update(item.get(k) for k in ('material_id', 'from', 'to',
                         'from_material_id', 'to_material_id') if item.get(k))
        if not bound or bound & ids:
            out.append(item)
    return out


def material_body(material, graphs, naming=False, dependency=False):
    ignored = DERIVED | ({'most_likely_name', 'nomenclature_declaration'} if naming else set())
    m = {k:v for k,v in material.items() if k not in ignored}
    if not naming and 'nomenclature_declaration' in m:
        m['nomenclature_declaration'] = declaration(material)
    if dependency:
        m['most_likely_name'] = material.get('most_likely_name')
        m['nomenclature_declaration'] = declaration(material)
    # Preparation/lookup records are candidate tool evidence. Adopting a changed
    # name, graph, source, alias, assumption or unknown must still change m.
    gs = {gid:{k:v for k,v in graphs.get(gid, {}).items() if k not in GRAPH_DERIVED}
          for gid in material.get('graph_ids', [])}
    return {'material':m, 'graphs':gs}


def context(material, candidate, naming=False, proposal=None):
    seen = {material['id']}; pending = dependencies(material, candidate, proposal); deps = {}
    while pending:
        mid = pending.pop()
        if mid in seen:
            continue
        seen.add(mid); other = candidate['materials'][mid]
        deps[mid] = material_body(other, candidate['graphs'], naming, dependency=True)
        pending.extend(dependencies(other, candidate))
    return {'adoption_policy':candidate['adoption_policy'],
            'current':material_body(material, candidate['graphs'], naming),
            'dependencies':deps,
            'policies':{k:candidate.get(k) for k in ('foundation_contract', 'naming_policy',
                'relation_policy', 'product_structure_policy')},
            'relations':relevant(candidate.get('relations'), seen),
            'source_facts':relevant(candidate.get('source_facts'), seen),
            'source_conflicts':relevant(candidate.get('source_conflicts'), seen),
            'unknowns':candidate.get('unknowns', [])}


def passport_issues(passport):
    """Only the proven periodic stereo capability gap is non-conflicting here.

    The original passport remains PARTIAL and the issue remains visible. Unknown
    codes/severities and actual constitution conflicts still block adoption.
    """
    issues = (passport or {}).get('chemical_core', {}).get('conflicts', [])
    gaps = [x for x in issues if x.get('code') == 'SUPPLIED_CONSTITUTION_OUTSIDE_PERIODIC_SCOPE'
            and x.get('severity') == 'partial'
            and x.get('reason_code') == 'PERIODIC_STEREO_FRAME_NOT_IMPLEMENTED']
    return [x for x in issues if x not in gaps], gaps
