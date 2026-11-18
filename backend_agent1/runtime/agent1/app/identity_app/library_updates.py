"""Independent, restartable property updates after delivered paper adoption.

No solver inputs, paper budgets, gates or sealed files are modified. The worker
owns only library-enrichment sidecars and never calls init_job/run_job/publish.
"""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time

from .storage import APP, atomic, digest, now, read


@contextmanager
def worker_lock(filename='worker.lock'):
    from .library_enrichment import root
    path=root()/filename;path.parent.mkdir(parents=True,exist_ok=True)
    handle=path.open('a+b');acquired=False
    try:
        if path.stat().st_size==0:handle.write(b'0');handle.flush()
        handle.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            acquired=True
        except OSError:pass
        yield acquired
    finally:
        if acquired:
            handle.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
        handle.close()


def needs_lookup(spec):
    from .library_enrichment import query_path, root
    lookup=read(query_path(spec),{})
    if lookup.get('status') not in ('MATCHED','COMPUTED_ONLY','NAME_ONLY','MISMATCH','AMBIGUOUS','NO_MATCH','UNSUPPORTED'):return True
    return any(read(root()/'compounds'/f"{c['CID']}.json",{}).get('status') not in ('OK','NO_MATCH')
               for c in lookup.get('candidates',[])[:5] if isinstance(c.get('CID'),int) and c['CID']>0)


def plan_update(entries, papers):
    from .library_enrichment import CONTRACT, finite_graph, name_query, query_spec, query_key, root
    from .library import identity_groups
    from .server import public_version
    from .chemistry_checks import graph_profile
    queries={};items=[];version=None;bundle=None
    for key,records in identity_groups(entries).items():
        entry=records[0]
        if entry['version']!=version:
            version=entry['version'];bundle=public_version(version)
        candidate=bundle['candidate'];material=candidate['materials'][entry['id']]
        graphs={gid:candidate['graphs'][gid] for gid in material.get('graph_ids',[]) if gid in candidate.get('graphs',{})}
        specs=[query_spec(g) for g in graphs.values() if finite_graph(g)]
        if not specs and (named:=name_query(material,graphs)):specs.append(named)
        for graph in graphs.values():
            path=root()/'local'/(digest({'smiles':graph.get('canonical_smiles'),'scope':graph.get('scope')})+'.json')
            if not path.exists():atomic(path,graph_profile(graph))
        pending=[query_key(spec) for spec in specs if needs_lookup(spec)]
        queries.update({query_key(spec):spec for spec in specs if query_key(spec) in pending})
        items.append({'identity_key':key,'label':entry['label'],'queries':pending,
            'scope_status':'QUERY_PLANNED' if pending else 'CACHED_OR_NOT_APPLICABLE',
            'sources':[{k:r[k] for k in ('job_id','version','id')} for r in records]})
    return {'contract':CONTRACT,'kind':'DELIVERED_PAPER_INCREMENT','created_at':now(),
        'paper_count':len(papers),'identity_count':len(items),'record_count':len(entries),
        'queries':queries,'items':items,'rate_per_second':0.5,'kernel_version':'0.9.0',
        'sources':[{k:p[k] for k in ('job_id','version')} for p in papers],
        'implementation_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def tick():
    from .library_enrichment import root, coverage, _execute_batch
    from .server import library_index
    state_path=root()/'watch-state.json';state=read(state_path,{'sources':{},'pending':None})
    main=coverage()
    # A pre-lock legacy full batch also has priority. Reader refresh is independent.
    if main.get('status') in ('RUNNING','PLANNED','RATE_LIMITED'):
        atomic(root()/'watch-status.json',{'status':'WAITING_FOR_FULL_BATCH','updated_at':now()});return
    pending=state.get('pending')
    if pending:
        if pending.get('next_try_at',0)>time.time():return
        job=root()/'jobs'/pending['job_id']
    else:
        entries,papers=library_index();current={p['job_id']:p['version'] for p in papers}
        changed={key for key,value in current.items() if state['sources'].get(key)!=value}
        if not changed:
            atomic(root()/'watch-status.json',{'status':'NEEDS_RETRY' if state.get('failed_jobs') else 'UP_TO_DATE','updated_at':now(),
                'source_count':len(current),'poll_seconds':30,'failed_jobs':state.get('failed_jobs',[])});return
        selected=[e for e in entries if e['job_id'] in changed]
        manifest=plan_update(selected,[p for p in papers if p['job_id'] in changed])
        if not manifest['queries']:
            atomic(state_path,{**state,'sources':current,'pending':None,'updated_at':now()})
            atomic(root()/'watch-status.json',{'status':'NEEDS_RETRY' if state.get('failed_jobs') else 'UP_TO_DATE','updated_at':now(),
                'source_count':len(current),'poll_seconds':30,'failed_jobs':state.get('failed_jobs',[])});return
        job_id='AUTO-PUBCHEM-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'-'+digest(manifest)[:10]
        job=root()/'jobs'/job_id;manifest['job_id']=job_id;atomic(job/'manifest.json',manifest)
        pending={'job_id':job_id,'attempts':0,'sources':current}
        state['pending']=pending;atomic(state_path,state)
    atomic(root()/'watch-status.json',{'status':'RUNNING','job_id':pending['job_id'],'updated_at':now()})
    result=_execute_batch(job,rate=0.5);pending['attempts']+=1
    if result['status']=='RATE_LIMITED':
        pending['next_try_at']=max(time.time()+900,result.get('retry_at') or 0);state['pending']=pending
        atomic(state_path,state)
        atomic(root()/'watch-status.json',{'status':'RETRY_WAIT','updated_at':now(),
            'job_id':pending['job_id'],'retry_at':pending['next_try_at'],'last_job':result});return
    if result['status']=='COMPLETED' or pending['attempts']>=3:
        failed=[*state.get('failed_jobs',[]),*([pending['job_id']] if result['status']!='COMPLETED' else [])]
        state={'sources':pending['sources'],'pending':None,'updated_at':now(),'failed_jobs':failed}
        atomic(root()/'watch-status.json',{'status':'UP_TO_DATE' if result['status']=='COMPLETED' else 'NEEDS_RETRY',
            'updated_at':now(),'last_job':result,'source_count':len(state['sources']),'poll_seconds':30})
    else:
        pending['next_try_at']=time.time()+900;state['pending']=pending
        atomic(root()/'watch-status.json',{'status':'RETRY_WAIT','updated_at':now(),
            'job_id':pending['job_id'],'retry_at':pending['next_try_at'],'last_job':result})
    atomic(state_path,state)


def watch():
    from .library_enrichment import root
    # One process owns the worker for its lifetime; another server does not duplicate it.
    with worker_lock('watch.lock') as acquired:
        if not acquired:return
        while True:
            try:
                with worker_lock() as owns_batch:
                    if owns_batch:tick()
            except Exception as exc:
                atomic(root()/'watch-status.json',{'status':'ERROR','updated_at':now(),
                    'error':type(exc).__name__+': '+str(exc)})
            time.sleep(30)


def start():
    """Spawn a property-only worker without making server/paper startup wait."""
    from .library_enrichment import root
    try:
        directory=root();directory.mkdir(parents=True,exist_ok=True)
        with (directory/'watch.log').open('ab') as log:
            return subprocess.Popen([sys.executable,'-X','utf8','-m','identity_app.library_updates'],
                cwd=APP,stdin=subprocess.DEVNULL,stdout=log,stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    except OSError as exc:
        # Failure is property-worker status, never a paper queue or delivery failure.
        try:atomic(root()/'watch-status.json',{'status':'ERROR','updated_at':now(),'error':str(exc)})
        except OSError:pass
        return None


if __name__=='__main__':watch()
