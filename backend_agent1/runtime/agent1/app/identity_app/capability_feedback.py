"""Immutable post-seal diagnostics for model-led general capability maintenance.

This is neither a chemical answer library nor a comparison/scoring module.
Pending diagnostics never become active rules or enter a paper solver by default.
"""
from pathlib import Path
from collections import Counter
from .storage import read,atomic,file_hash,digest,data_root

CONTRACT='identity-capability-feedback/1.0'


def _codes(value):
    if isinstance(value,dict):
        for key,item in value.items():
            if key in ('code','reason_code') and isinstance(item,str):yield item
            elif isinstance(item,(dict,list)):yield from _codes(item)
    elif isinstance(value,list):
        for item in value:yield from _codes(item)


def describe(job):
    job=Path(job);seal=read(job/'sealed.json',{});run=read(job/'run.json',{})
    if not seal or run.get('status') not in ('DELIVERED','INCOMPLETE'):
        raise ValueError('CAPABILITY_FEEDBACK_REQUIRES_SEALED_ATTEMPT')
    for name,key in (('run.json','run_sha256'),('current.json','candidate_sha256'),('completion.json','completion_sha256')):
        actual=file_hash(job/name) if (job/name).is_file() else None
        if actual!=seal.get(key):raise ValueError('CAPABILITY_FEEDBACK_SEAL_BINDING_MISMATCH:'+name)
    c=read(job/'current.json');rows=[]
    for mid,m in c.get('materials',{}).items():
        if not m.get('major'):continue
        a=m.get('iupac_assessment') or {};p=a.get('proposal') or (m.get('nomenclature_declaration') or {}).get('proposal') or {}
        d=p.get('source_declaration') or m.get('nomenclature_declaration') or {}
        gaps=set();subunits=(a.get('checks') or {}).get('subunit_checks',[]) if isinstance(a.get('checks'),dict) else []
        for check in subunits:
            if check.get('status')!='GRAPH_MATCH':gaps.update(_codes(check))
        for gap in m.get('capability_gaps',[]):gaps.update(_codes(gap))
        if a.get('status')=='MODEL_CLASS_NAME_REVIEWED_WITH_TOOL_GAPS':gaps.add('CLASS_NAME_RULES_NOT_IMPLEMENTED_BY_LOCAL_PARSER')
        used=[]
        adopted_current=run['status']=='DELIVERED' and a.get('primary_matches_display') is True
        if adopted_current and any(x.get('provider')=='SCOPED_ACYCLIC_SUBSTITUENT_COMPOSITION' and x.get('status')=='GRAPH_MATCH' for x in subunits):
            used.append('iupac-substituted-acyclic-diyl/1.0')
        if adopted_current and d.get('contract')=='identity-evidence-nomenclature/1.5' and a.get('formal_name'):
            used.append(d['contract']+':'+('block' if d.get('kind')=='block_copolymer' else str(d.get('sequence','unspecified'))))
        rows.append({'material_id':mid,'kind':m.get('kind'),'naming_status':a.get('status'),
                     'declared_tool_gap_codes':sorted(gaps),'new_routes_actually_used':used})
    return {'contract':CONTRACT,'job_id':job.name,'source_sha256':run.get('source_sha256'),
            'version':(run.get('delivery') or {}).get('version'),'attempt_status':run['status'],
            'sealed_at':seal.get('sealed_at'),'sealed_sha256':file_hash(job/'sealed.json'),
            'run_sha256':seal['run_sha256'],'candidate_sha256':seal['candidate_sha256'],
            'implementation_sha256':(read(job/'implementation.json',{}) or {}).get('sha256'),
            'materials':rows,'status':'PENDING_GENERAL_MODEL_REVIEW','solver_input':False,
            'human_reference_used':False,'chemical_accuracy_score':None,
            'scope':'saved route and declared tool gaps only; no source interpretation or rule promotion',
            'independent_review':'NOT_REVIEWED'}


def record(job,root=None):
    root=Path(root) if root is not None else data_root()/'capability-feedback';body=describe(job)
    path=root/body['job_id']/'feedback.json'
    if path.exists():
        if digest(read(path))!=digest(body):raise ValueError('CAPABILITY_FEEDBACK_IMMUTABLE_BINDING_CHANGED')
    else:atomic(path,body)
    return {'path':str(path),'sha256':file_hash(path),'status':body['status']}


def collect(root=None,jobs_root=None):
    root=Path(root) if root is not None else data_root()/'capability-feedback'
    jobs_root=Path(jobs_root) if jobs_root is not None else data_root()/'jobs'
    gaps=Counter();routes=Counter();rows=[];errors=[]
    for path in sorted(root.glob('*/feedback.json')):
        try:
            body=read(path);job_id=body['job_id']
            if not isinstance(job_id,str) or job_id in ('.','..') or Path(job_id).name!=job_id:
                raise ValueError('FEEDBACK_JOB_ID_INVALID')
            if not (jobs_root/job_id).resolve().is_relative_to(jobs_root.resolve()):raise ValueError('FEEDBACK_JOB_ID_INVALID')
            if digest(body)!=digest(describe(jobs_root/job_id)):raise ValueError('FEEDBACK_BINDING_CHANGED')
            for m in body['materials']:
                gaps.update(m['declared_tool_gap_codes']);routes.update(m['new_routes_actually_used'])
            rows.append({'job_id':job_id,'version':body['version'],'feedback':str(path),'sha256':file_hash(path)})
        except (ValueError,KeyError,OSError,TypeError) as exc:errors.append({'file':str(path),'error':str(exc)})
    return {'contract':CONTRACT,'status':'BINDINGS_PASS' if not errors else 'BINDINGS_FAIL',
            'feedback_count':len(rows),'declared_tool_gap_material_counts':dict(gaps),
            'actual_new_route_material_counts':dict(routes),'rows':rows,'errors':errors,
            'rule_promotion':'NONE; model review and engineering gate required','solver_input':False,
            'human_reference_used':False,'chemical_accuracy_score':None}
