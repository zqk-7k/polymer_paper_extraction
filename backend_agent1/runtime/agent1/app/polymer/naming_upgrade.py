"""Pure chemical-core-preserving migration to graph-derived name candidates.

No name from an input record or catalog is used to generate a missing label.
Naming runs at construction/migration only; validate/replay stay offline/pure.
"""
from copy import deepcopy
from .common import fail, key
from .passport import (validate_passport, _name_tree, _digest, render_name_ast,
                       NAMING09, SCHEMA09)
from .graph_naming_v09 import name_source, name_unit, PROFILE


def upgrade_passport_naming(passport, increment_revision=True):
    valid=validate_passport(passport)
    if valid['status']!='PARSED':return valid
    if passport['policies']['naming']==NAMING09:
        return {'status':passport['assessment']['status'],'passport':deepcopy(passport),
                'chemical_keys_unchanged':True,'already_current':True,'exact_material_identity':False}
    result=deepcopy(passport);old_key=passport['integrity']['snapshot_key']
    result['schema_version']=SCHEMA09;result['policies']['naming']=NAMING09
    result['build_manifest'].update({'kernel':'identity/0.9','contract_engine':'identity/0.9',
        'naming_profile':NAMING09,'graph_naming_profile':PROFILE,
        'migrated_from_naming_profile':passport['policies']['naming']})
    snap=result['naming_snapshot'];snap['profile']=NAMING09
    label_evidence={};diagnostics=[];generated_count=0
    for ref,entity in result['entities'].items():
        if entity.get('display_label'):
            label_evidence[ref]={'status':'PRESERVED','origin_profile':entity.get('label_profile'),
                'label':entity['display_label'],'chemical_review':'NOT_INDEPENDENTLY_REVIEWED'}
            continue
        named=(name_source if entity['kind']=='source_molecule' else name_unit)(entity['smiles'])
        if named['status']=='PARSED':
            if entity['kind']=='source_molecule':label=named['label']
            else:label=named['structure_based_name_candidate'][5:-1]
            entity['display_label']=label;entity['label_profile']=NAMING09
            label_evidence[ref]={'status':'GRAPH_DERIVED_CANDIDATE','label':label,
                'input_graph_key':ref,'method':named.get('candidate_method'),'profile':PROFILE,
                'graph_roundtrip_consistent':True,'rule_trace':named.get('rule_trace',[]),
                'chemical_review':'NOT_INDEPENDENTLY_REVIEWED'}
            generated_count+=1
        else:
            label_evidence[ref]={'status':'UNAVAILABLE','reason_code':named['reason_code'],'profile':PROFILE}
            diagnostics.append({'kind':'MISSING_ENTITY_LABEL','entity_ref':ref,'entity_kind':entity['kind'],
                                'reason_code':named['reason_code']})
    directions=snap.get('end_direction_mappings',{})
    snap['source_or_cu_ast']=_name_tree(result['chemical_core']['definition_tree'],result['entities'],directions)
    period=result['chemical_core']['constitution_model']
    if period and snap['structure_ast'] is None:
        named=name_unit(period['canonical_repeat_smiles'])
        if named['status']=='PARSED':
            snap['structure_ast']={'kind':'polymer','children':[{'kind':'unit',
                'label':named['structure_based_name_candidate'][5:-1],'entity_ref':period['graph_key']}]}
            snap['graph_roundtrip_consistent']=True
            snap['structure_generation_evidence']={'profile':PROFILE,'method':named.get('candidate_method'),
                'rule_trace':named.get('rule_trace',[]),'scope':period['scope'],
                'independent_chemical_review':False}
        else:diagnostics.append({'kind':'STRUCTURE_NAMING','reason_code':named['reason_code']})
    if snap['source_or_cu_ast'] is None and not diagnostics:
        diagnostics.append({'kind':'TREE_OR_END_DIRECTION','reason_code':'WHOLE_TREE_OR_END_DIRECTION_UNSUPPORTED'})
    if not period:diagnostics.append({'kind':'STRUCTURE_MISSING','reason_code':'NO_WHOLE_CONSTITUTION_MODEL'})
    if result['assessment']['status']!='PARSED':
        diagnostics.append({'kind':'DESCRIPTION_NOT_COMPLETE','reason_code':'UNRESOLVED_OR_CONFLICTING_DESCRIPTION'})
    snap['label_evidence']=label_evidence;snap['naming_diagnostics']=diagnostics
    # Keep a copy of the prior frozen tree so an upgraded card can be replayed
    # under its original policy without invoking any chemical naming code.
    # This is provenance, not a second answer and is intentionally excluded
    # from identity/evidence keys.
    snap['migration']={'from_profile':passport['policies']['naming'],
        'from_snapshot':old_key,'generated_entity_labels':generated_count,
        'chemical_core_modified':False,'input_names_used_as_fallback_labels':False,
        'legacy_snapshot':deepcopy(passport['naming_snapshot']),
        'legacy_replay':'AVAILABLE_FROM_SNAPSHOT_ONLY'}
    # This is a naming-policy revision, not a new chemical identity or new evidence.
    if increment_revision:
        result['record']['revision']+=1;result['record']['parent_snapshot_key']=old_key
    result['integrity']={'snapshot_key':_digest(result),'is_signature':False}
    assert result['identity_keys']==passport['identity_keys']
    assert result['chemical_core']==passport['chemical_core']
    check=validate_passport(result)
    if check['status']!='PARSED':return check
    return {'status':result['assessment']['status'],'passport':result,
        'chemical_keys_unchanged':True,'generated_entity_labels':generated_count,'exact_material_identity':False}


def naming_diagnostics(passport):
    check=validate_passport(passport)
    if check['status']!='PARSED':return check
    from .passport import name_from_passport
    snap=passport['naming_snapshot'];issues=deepcopy(snap.get('naming_diagnostics',[]))
    if passport['policies']['naming']!=NAMING09:
        for ref,e in passport['entities'].items():
            if not e.get('display_label'):
                issues.append({'kind':'MISSING_ENTITY_LABEL','entity_ref':ref,'entity_kind':e['kind'],
                               'reason_code':'LEGACY_LABEL_UNAVAILABLE'})
    return {'status':'PARSED','profile':snap['profile'],'issues':issues,
        'source':name_from_passport(passport,'source'),'structure':name_from_passport(passport,'structure'),
        'chemical_accuracy':None,'full_iupac_conformance':False}
