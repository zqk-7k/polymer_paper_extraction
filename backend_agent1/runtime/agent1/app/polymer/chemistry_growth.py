"""Versioned source-backed chemistry reuse, separate from unreviewed extraction cases."""
from pathlib import Path
from copy import deepcopy
import hashlib,json,re
CONTRACT='chemistry-growth-context/1.0'
NAMING_CONTRACT='iupac-supported-naming/1.2'

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

def database_exists(root):
    return (Path(root)/'data/chemistry_growth/library.sqlite3').is_file()

def ledger(root):
    from .chemistry_growth_store import GrowthStore
    return GrowthStore(root)

def freeze(root):
    if not database_exists(root):return None
    release=ledger(root).current()
    if not release:return None
    from collections.abc import Mapping
    def thaw(value):
        if isinstance(value,Mapping):return {k:thaw(v) for k,v in value.items()}
        if isinstance(value,(list,tuple)):return [thaw(v) for v in value]
        return value
    release=thaw(release)
    payload={'contract':CONTRACT,'release':release,'independent_review':'NOT_REVIEWED'}
    return {**payload,'sha256':digest(payload)}

def validate(snapshot):
    if not isinstance(snapshot,dict) or snapshot.get('contract')!=CONTRACT:return None
    if digest({k:v for k,v in snapshot.items() if k!='sha256'})!=snapshot.get('sha256'):
        raise ValueError('CHEMISTRY_KNOWLEDGE_SNAPSHOT_CHANGED')
    return deepcopy(snapshot['release'])

def cards_in(release):
    value=release.get('cards',[])
    if isinstance(value,dict):value=list(value.values())
    if not value:value=list(release.get('rules',[]))+list(release.get('fragments',[]))
    return [x for x in value if isinstance(x,dict)]

def context(snapshot,query='',limit=4):
    release=validate(snapshot)
    if not release:return {}
    query=str(query).casefold();selected=[]
    for row in cards_in(release):
        body=row.get('body',{});words=[row.get('family',''),row.get('title','')]+body.get('keywords',[])
        score=sum(bool(w) and str(w).casefold() in query for w in words)
        if score:selected.append((score,row))
    chosen=sorted(selected,key=lambda p:(-p[0],p[1]['id']))[:min(6,max(0,limit))]
    return {'contract':CONTRACT,'release_id':release.get('id'),'release_sha256':snapshot['sha256'],
        'use':'Reference knowledge, NOT evidence of what this paper reports. Preserve unknowns.',
        'items':[{'id':r['id'],'kind':r['kind'],'title':r['title'],'locator':r.get('locator'),
                  'source_ids':r.get('source_ids',[]),'guidance':r.get('body',{}).get('guidance'),
                  'identity_kind':r.get('body',{}).get('identity_kind'),
                  'graph':r.get('body',{}).get('graph'),'port_count':r.get('body',{}).get('port_count'),
                  'scope':r.get('body',{}).get('supported_scope')} for _,r in chosen]}

def enabled_families(snapshot):
    release=validate(snapshot)
    return {r.get('body',{}).get('capability') for r in cards_in(release or {})
            if r.get('status')=='ACTIVE_SCOPED' and r.get('kind')=='rule'}

def record_result(root,job_id,result):
    if not database_exists(root):return {'status':'LIBRARY_NOT_INITIALIZED','model_calls':0}
    wf=result.get('workflow',{});rows=wf.get('passport_records',{}).get('polymers',[])
    original_hash=digest(result);source=result.get('source_sha256') or wf.get('source_sha256')
    if not source:return {'status':'SOURCE_HASH_UNAVAILABLE','model_calls':0}
    cases=[]
    for row in rows:
        if not isinstance(row,dict) or not isinstance(row.get('ref'),str):continue
        naming=next((p for p in wf.get('passport_chemistry',{}).get('passports',[])
                     if p.get('polymer_ref')==row['ref']),{})
        cases.append({'source_sha256':source,'owner_ref':row['ref'],'revision':'BASE',
            'result_sha256':original_hash,'job_id':job_id,'names':[n.get('text','') if isinstance(n,dict) else str(n) for n in row.get('names',[])],
            'raw_names':deepcopy(row.get('names',[])),
            'src':deepcopy(row.get('src',[])),'status':naming.get('status','NO_NAME'),
            'scope':row.get('nomenclature_scope'),'origin':row.get('origin'),
            'identity_excerpt':{k:deepcopy(row[k]) for k in ('components','monomers','qualifiers','unknowns') if k in row},
            'naming':{'names':deepcopy(naming.get('names',[])),'failures':deepcopy(naming.get('naming_failures',[]))}})
    store=ledger(root);receipt=store.record_cases(cases)
    store.put_task({'id':'SOURCE-'+job_id,'kind':'source_capture','status':'CAPTURED',
        'source_job':job_id,'submitted':bool(wf.get('execution',{}).get('submitted')),
        'cases_seen':len(cases),'automatic_promotion':False,'model_calls':0})
    return {**receipt,'status':'CAPTURED','model_calls':0,'automatic_promotion':False}

def harvest(root,batch_id=None,jobs=None):
    if batch_id:
        if not re.fullmatch(r'LB-[0-9TZ]+-[a-f0-9]{8}',batch_id):raise ValueError('INVALID_BATCH_ID')
        batch=json.loads((Path(root)/'runs/literature-batches'/batch_id/'run.json').read_text(encoding='utf8'))
        jobs=[x['fullpaper_job'] for x in batch['records'] if x.get('fullpaper_job')]
    outcomes=[]
    for job in dict.fromkeys(jobs or []):
        if not re.fullmatch(r'FP-[0-9TZ]+-[a-f0-9]{8}',job):raise ValueError('INVALID_JOB_ID')
        file=Path(root)/'runs/fullpaper'/job/'result.json'
        if not file.is_file():outcomes.append({'job_id':job,'status':'NOT_FINISHED'});continue
        try:outcomes.append({'job_id':job,**record_result(root,job,json.loads(file.read_text(encoding='utf8')))})
        except (ValueError,OSError,KeyError) as exc:outcomes.append({'job_id':job,'status':'CAPTURE_FAILED','reason':str(exc)})
    return {'jobs':outcomes,'new_model_calls':0,'scientific_results_modified':False}

def api(root,operation,inputs):
    if operation=='chemistry_library_read':
        store=ledger(root)
        result=store.snapshot(query=inputs.get('query',''),kind=inputs.get('kind'))
        result['sources']=store.snapshot()['sources']
        from .chemistry_growth_tasks import observe
        result['tasks']=observe(root,result['tasks'])
        result['recent_cases']=store.recent_cases(8)
        current=store.current() or {}
        active=current.get('cards',[])
        result['published_counts']={'rules':sum(r['kind']=='rule' for r in active),'fragments':sum(r['kind']=='fragment' for r in active)}
        return {**result,'contract':'chemistry-library-view/1.0','read_only':True,
            'scope_notice':'登记/来源核对/可检索/可执行不同；不以条目数宣称全部IUPAC覆盖。'}
    if operation=='chemistry_library_name':
        smiles=inputs.get('smiles')
        if not isinstance(smiles,str) or not 0<len(smiles)<4000:raise ValueError('BOUNDED_REPEAT_GRAPH_REQUIRED')
        from .naming_service import NamingService
        from .literature.knowledge_context import create_kernel
        kernel=create_kernel(policy='base_registry_only')
        try:return NamingService(kernel).name_structure(smiles,rule_contract=NAMING_CONTRACT,knowledge_snapshot=freeze(root))
        finally:kernel.registry.close()
    raise ValueError('CHEMISTRY_LIBRARY_OPERATION_UNKNOWN')
