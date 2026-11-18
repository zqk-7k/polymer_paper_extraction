"""Explicit 1.2 naming extension; release-bound, no learned names promoted from papers."""
from copy import deepcopy
from .chemistry_growth import enabled_families,validate,NAMING_CONTRACT

def structure_name(kernel,smiles,knowledge_snapshot=None):
    from .supported_naming import structure_name as prior
    allowed=enabled_families(knowledge_snapshot)
    if not allowed:return prior(kernel,smiles)
    from .heterochain_naming import name as heterochain
    candidate=heterochain(smiles,kernel=kernel)
    primary=candidate.get('primary') or {}
    capability=('polydimethylsiloxane' if primary.get('text')=='poly[oxy(dimethylsilanediyl)]'
                else 'polyether-oxyalkylene')
    if primary and capability in allowed:
        release=validate(knowledge_snapshot)
        candidate.update(contract=NAMING_CONTRACT,knowledge_release_id=release['id'],
                         knowledge_snapshot_sha256=knowledge_snapshot['sha256'])
        primary.update(knowledge_release_id=release['id'],
                       rule_refs=deepcopy(candidate.get('rule_refs',[])))
        if candidate.get('status')=='IUPAC_AT_DECLARED_SCOPE':
            primary['validation']={'accepted':True,'comparison_scope':'complete_supplied_constitution_only','sample_identity_asserted':False}
            primary['rule_validation']={'status':'PASS','checks':[{'rule':r['rule'],'status':'PASS','url':r['url']} for r in candidate['rule_refs']],
                'source_url':'https://iupac.qmul.ac.uk/BriefGuide/polymer.html','knowledge_release_id':release['id']}

        return candidate
    return prior(kernel,smiles)

def name(kernel,passport,knowledge_snapshot=None):
    from .supported_naming import name as prior
    result=prior(kernel,passport)
    result['contract']=NAMING_CONTRACT
    release=validate(knowledge_snapshot)
    result['knowledge_release_id']=release.get('id') if release else None
    if not passport or not release:return result
    core=passport.get('chemical_core',{}).get('constitution_model') or {}
    graph=core.get('canonical_repeat_smiles') or core.get('ported_unit_basis')
    if graph:
        structured=structure_name(kernel,graph,knowledge_snapshot)
        result['structure_naming']=structured
        if structured.get('primary'):
            previous=[r for r in result.get('alternatives',[]) if r.get('text')!=structured['primary']['text']]
            result['alternatives']=[structured['primary']]+previous
    return result
