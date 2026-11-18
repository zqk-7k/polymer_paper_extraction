"""Explicit post-seal revisions. First jobs, receipts and bundles stay immutable."""
from copy import deepcopy
from pathlib import Path
from threading import RLock
import time, uuid
from .storage import APP, data_root, read, atomic, digest, now, validate, file_hash
from .evidence import receipts_for
from .tools import execute

LOCK = RLock()
PATCH_FIELDS = {'most_likely_name','passport_name','description','components','composition','relationships',
                'preparation','source_refs','unknowns','assumptions','constitution','identity_attributes',
                'identity_properties','molar_mass','rule_contract','label','nomenclature_declaration','structure_expression','graph_scope_note'}

def checked_job(job_id,require_run=True):
    root=(data_root()/'jobs').resolve();job=(root/job_id).resolve()
    if not job.is_relative_to(root) or job.parent!=root or (require_run and not (job/'run.json').is_file()):
        raise ValueError('JOB_NOT_FOUND')
    return job

def pointer_for(job_id):
    checked_job(job_id,require_run=False)
    return read(data_root()/'revisions'/job_id/'latest.json') or read(data_root()/'jobs'/job_id/'adopted.json')

def read_version(version):
    if not isinstance(version,str) or len(version)!=64 or any(c not in '0123456789abcdef' for c in version):
        raise ValueError('VERSION_HASH_INVALID')
    b=read(data_root()/'versions'/version/'bundle.json')
    if not b or digest({k:v for k,v in b.items() if k!='version'})!=version:
        raise ValueError('VERSION_HASH_INVALID')
    return b

def current_bundle(job_id):
    pointer=pointer_for(job_id)
    if not pointer:raise ValueError('ADOPTED_BASE_REQUIRED')
    return read_version(pointer['version'])

def start_revision(job_id, expected_version, reason, actor='USER_EDIT'):
    if not isinstance(reason,str) or not reason.strip() or len(reason)>2000:raise ValueError('REVISION_REASON_REQUIRED')
    base=current_bundle(job_id)
    if base['version']!=expected_version:raise ValueError('STALE_VERSION')
    rid='RV-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'-'+uuid.uuid4().hex[:8]
    work=data_root()/'revisions'/job_id/rid;work.mkdir(parents=True,exist_ok=False)
    inherited=receipts_for(checked_job(job_id),base.get('tool_evidence'))
    candidate=deepcopy(base['candidate']);candidate['tool_receipts']=inherited
    atomic(work/'current.json',candidate);atomic(work/'source-index.json',base['source_index'])
    atomic(work/'run.json',{'contract':'identity-single-core/1.0','job_id':job_id,'source_sha256':base['source_sha256'],
                          **({'material_reference_policy':candidate['material_reference_policy']} if 'material_reference_policy' in candidate else {}),
                          'deadline_epoch':time.time()+3600,'status':'POST_SEAL_REVISION','model_calls':0})
    atomic(work/'revision.json',{'id':rid,'job_id':job_id,'parent_version':base['version'],
                              'reason':reason,'actor':actor,'created_at':now(),
                              'post_seal':True,'first_run_evidence_unchanged':True})
    return work,base

def finish_revision(work, base, diff=None):
    candidate=read(work/'current.json');snap=execute('snapshot',{},work)
    pending=[{'id':m['id'],'state_sha256':snap['material_state_sha256'][m['id']],
              'reason':read(work/'revision.json')['reason'], 'reviewer':'LOCAL_REVALIDATION_NOT_INDEPENDENT'}
             for m in candidate['materials'].values() if (m.get('review') or {}).get('state_sha256')!=snap['material_state_sha256'][m['id']]
             or (m.get('review') or {}).get('contract')!='identity-foundation/1.1']
    if pending:execute('review',{'materials':pending},work)
    c=read(work/'current.json');errors=validate(c,base['source_index'],expected_reference_policy=read(work/'run.json',{}).get('material_reference_policy'))
    events=receipts_for(work,c.pop('tool_receipts',{}))
    body={k:deepcopy(v) for k,v in base.items() if k not in ('version','candidate','tool_evidence','revision','validation_errors')}
    body.update(candidate=c,tool_evidence=events,revision=read(work/'revision.json'),
                foundation_contract='identity-foundation/1.1',validation_errors=errors)
    body['revision']['implementation_hashes']={str(p.relative_to(APP)).replace('\\','/'):file_hash(p)
                 for folder in ('identity_app','polymer','resources') for p in (APP/folder).rglob('*')
                 if p.is_file() and p.suffix in ('.py','.md','.json') and '__pycache__' not in p.parts}
    version=digest(body);bundle={**body,'version':version}
    path=data_root()/'versions'/version/'bundle.json'
    if path.exists():
        if read(path)!=bundle:raise ValueError('IMMUTABLE_VERSION_CONFLICT')
    else:atomic(path,bundle)
    atomic(work/'preview.json',{'version':version,'errors':errors,'diff':diff or {},'workdir':str(work)})
    return {'version':version,'errors':errors,'diff':diff or {},'revision_id':body['revision']['id'],
            'adopted':False,'independent_review':'NOT_REVIEWED'}

def preview_revision(job_id,request):
    with LOCK:
        work,base=start_revision(job_id,request.get('expected_version'),request.get('reason'))
        mid=request.get('material_id');m=base['candidate']['materials'].get(mid)
        if not m:raise ValueError('MATERIAL_NOT_FOUND')
        patch=deepcopy(request.get('patch',{}))
        if set(patch)-PATCH_FIELDS:raise ValueError('REVISION_FIELD_NOT_EDITABLE')
        if 'name' in request:
            if not isinstance(request['name'],str) or not 0<len(request['name'])<=5000:raise ValueError('NAME_LIMIT')
            patch['most_likely_name']={**m.get('most_likely_name',{}),'text':request['name']}
        if request.get('graph'):
            spec=request['graph'];execute('check_structure',spec,work)
            patch['graph_ids']=[spec['id']]
        changed={k:{'previous':m.get(k),'proposed':v} for k,v in patch.items() if m.get(k)!=v}
        if not changed:raise ValueError('NO_REVISION_CHANGE')
        execute('upsert',{'materials':[{'id':mid,**patch}],'change_reason':request['reason']},work)
        return finish_revision(work,base,{'material':m['label'],'changes':changed})

def adopt_revision(job_id,version,expected_version):
    with LOCK:
        current=current_bundle(job_id)
        if current['version']!=expected_version:raise ValueError('STALE_VERSION')
        b=read_version(version)
        if b.get('job_id')!=job_id or b.get('revision',{}).get('parent_version')!=expected_version:
            raise ValueError('REVISION_PARENT_MISMATCH')
        errors=b.get('validation_errors',[])+validate(b['candidate'],b['source_index'])
        if errors:raise ValueError('REVISION_NOT_READY:'+','.join(errors))
        pointer={'job_id':job_id,'version':version,'previous_version':expected_version,'adopted_at':now(),
                 'revision_id':b['revision']['id'],'post_seal':True}
        atomic(data_root()/'revisions'/job_id/'latest.json',pointer)
        if read_version(version)['version']!=version:raise ValueError('READBACK_FAILED')
        return {'status':'ADOPTED_REVISION','version':version,'previous_version':expected_version,
                'first_job_pointer_preserved':True,'readback':'PASS'}
