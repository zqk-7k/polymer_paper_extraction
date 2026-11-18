import argparse,base64,gzip,json,mimetypes,queue,threading,time,unicodedata
from collections import OrderedDict
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit,parse_qs,unquote
from .storage import APP, data_root, read, atomic, digest, now, validate
from .runner import init_job,run_job,require_preflight,preflight
from .revisions import pointer_for,read_version,preview_revision,adopt_revision
from .library import (component_entries, page as library_page, sources as library_sources,
                      records_for_key, identity_summary, association_page)
WORK=queue.Queue();ACTIVE=None
QUEUED_IDS=set();QUEUE_LOCK=threading.RLock()
# Reader-only caches. A changed run, adoption pointer or bundle invalidates its
# entry; chemistry validation and the immutable bundle digest are never changed.
READER_LOCK=threading.RLock()
VERIFIED_BUNDLES=OrderedDict()
DIRECTORY_ROWS={}
LIBRARY_ROWS={}

def file_stamp(path):
    try:
        s=path.stat()
        return (s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    except FileNotFoundError:return None

def verified_bundle(version):
    if not isinstance(version,str) or len(version)!=64 or any(c not in '0123456789abcdef' for c in version):
        raise ValueError('VERSION_HASH_INVALID')
    path=data_root()/'versions'/version/'bundle.json';key=str(path)
    with READER_LOCK:
        stamp=file_stamp(path);cached=VERIFIED_BUNDLES.get(key)
        if stamp and cached and cached[0]==stamp:
            VERIFIED_BUNDLES.move_to_end(key)
            return cached[1]
        VERIFIED_BUNDLES.pop(key,None)
        bundle=read_version(version)
        # Do not retain an entry if the file changed while it was read.
        if stamp and stamp[0]<=8_000_000 and file_stamp(path)==stamp:
            VERIFIED_BUNDLES[key]=(stamp,bundle)
            while len(VERIFIED_BUNDLES)>8 or sum(v[0][0] for v in VERIFIED_BUNDLES.values())>32_000_000:
                VERIFIED_BUNDLES.popitem(last=False)
        return bundle

def directory_row(path):
    job=path.parent;root=data_root();key=str(path)
    control=(file_stamp(path),file_stamp(job/'adopted.json'),file_stamp(root/'revisions'/job.name/'latest.json'))
    cached=DIRECTORY_ROWS.get(key)
    if cached and cached[0]==control:
        row=cached[2]
        if not row or file_stamp(root/'versions'/row['version']/'bundle.json')==cached[1]:return row
    from .reader_cache import load as load_projection, save as save_projection
    projected=load_projection(job.name,control,lambda v:file_stamp(root/'versions'/v/'bundle.json'))
    if projected:
        row,stamp,entries=projected
        DIRECTORY_ROWS[key]=(control,stamp,row);LIBRARY_ROWS[key]=(row['version'],stamp,entries)
        return row
    state=read(path);row=None;stamp=None
    if state.get('status')=='DELIVERED':
        try:b=public_bundle_for(job.name)
        except ValueError:b={}
        if b.get('candidate'):
            c=b['candidate'];materials=list(c.get('materials',{}).values());major=[m for m in materials if m.get('major')]
            entries=component_entries(b)
            row={'job_id':state['job_id'],'title':c.get('title') or state['job_id'],'status':'DELIVERED',
                 'started_at':state['started_at'],'elapsed_seconds':state.get('elapsed_seconds'),'version':b['version'],
                 'source_sha256':b.get('source_sha256') or state.get('source_sha256'),
                 'input_kind':state.get('input_kind','pdf'),
                 'first_run_unattended':state.get('first_run_unattended'),'overview':c.get('overview',''),
                 'page_count':b.get('source_index',{}).get('page_count',0),'major_count':len(major),
                 'polymer_count':sum(m.get('kind') in ('polymer','prepolymer','oligomer','blend','network') for m in major),
                 'material_labels':[m.get('label',m['id']) for m in major],
                 'component_count':len(entries)}
            stamp=file_stamp(root/'versions'/b['version']/'bundle.json')
            LIBRARY_ROWS[key]=(b['version'],stamp,entries)
            if stamp:save_projection(job.name,control,stamp,row,entries)
    # Invalid delivered entries are rechecked, including missing/corrupt bundles.
    if row or state.get('status')!='DELIVERED':DIRECTORY_ROWS[key]=(control,stamp,row)
    else:DIRECTORY_ROWS.pop(key,None)
    return row
def worker():
    global ACTIVE
    while True:
        job=WORK.get();ACTIVE=job.name
        try:execute_queued(job)
        except Exception as e:
            state=read(job/'run.json');state.update(status='ENGINEERING_FAILED',error=type(e).__name__+': '+str(e),first_run_unattended=False);atomic(job/'run.json',state)
        finally:
            with QUEUE_LOCK:QUEUED_IDS.discard(job.name)
            ACTIVE=None;WORK.task_done()

def execute_queued(job):
    state=read(job/'run.json')
    if (job/'stop-request.json').exists():
        state.update(status='STOPPED');atomic(job/'run.json',state);return
    if state.get('status')=='QUEUED':
        state['status']='CHECKING_RUNTIME';atomic(job/'run.json',state)
        try:require_preflight()
        except ValueError as exc:
            if str(exc) not in ('CLI_PREFLIGHT_REQUIRED','CLI_PREFLIGHT_EXPIRED','CLI_PREFLIGHT_IMPLEMENTATION_CHANGED'):raise
            if preflight().get('status')!='PASS':raise ValueError('CLI_PREFLIGHT_FAILED')
            require_preflight()
        if (job/'stop-request.json').exists():
            state.update(status='STOPPED');atomic(job/'run.json',state);return
        # Only a NEW queued request starts its budget here. Resumes keep the deadline.
        epoch=time.time();state.update(status='PREPARING_SOURCE',started_at=now(),started_epoch=epoch,
                                      deadline_epoch=epoch+state['budget_seconds'])
        atomic(job/'run.json',state)
    return run_job(job)

def enqueue(job):
    with QUEUE_LOCK:
        if job.name in QUEUED_IDS or ACTIVE==job.name:raise ValueError('JOB_ALREADY_QUEUED_OR_ACTIVE')
        QUEUED_IDS.add(job.name);WORK.put(job)

def task_summary(job):
    state=read(job/'run.json',{})
    if not state:raise ValueError('TASK_NOT_FOUND')
    keys=('job_id','status','input_kind','started_at','queued_at','deadline_epoch','budget_seconds','error','failure_kind')
    result={k:state.get(k) for k in keys}
    result['title']=read(job/'ui-request.json',{}).get('title') or state['job_id']
    result['elapsed_seconds']=state.get('elapsed_seconds') or (max(0,time.time()-state['started_epoch']) if state.get('started_epoch') else 0)
    result['errors']=(state.get('delivery') or {}).get('errors',[])[:12]
    result['sealed']=(job/'sealed.json').exists()
    result['can_resume']=bool(not result['sealed'] and state.get('status') not in
        ('DELIVERED','QUEUED','CHECKING_RUNTIME','PREPARING_SOURCE','UNDERSTANDING_AND_BUILDING') and
        (state.get('deadline_epoch') is None or time.time()<state['deadline_epoch']))
    result['queue_position']=None
    if state.get('status')=='QUEUED':
        with WORK.mutex:
            queued=[p.name for p in WORK.queue]
        if job.name in queued:result['queue_position']=queued.index(job.name)+1
    return result

def list_workbench():
    rows=[]
    for path in (data_root()/'jobs').glob('SC-*/run.json'):
        state=read(path,{})
        if state.get('input_kind')=='text' or (path.parent/'ui-request.json').exists():rows.append(task_summary(path.parent))
    return sorted(rows,key=lambda r:r.get('queued_at') or r.get('started_at') or '',reverse=True)[:80]
def list_jobs():
    with READER_LOCK:
        paths=list((data_root()/'jobs').glob('SC-*/run.json'));keys={str(p) for p in paths}
        for key in list(DIRECTORY_ROWS):
            if key not in keys:
                DIRECTORY_ROWS.pop(key);LIBRARY_ROWS.pop(key,None)
        rows=[row for p in paths if (row:=directory_row(p)) and row.get('input_kind')!='text']
    latest=[];titles=set();sources=set()
    for row in sorted(rows,key=lambda x:(x['started_at'],x['job_id']),reverse=True):
        title=''.join(c for c in unicodedata.normalize('NFKC',row['title']).casefold() if c.isalnum())
        source=row.get('source_sha256')
        duplicate=title in titles or bool(source and source in sources)
        titles.add(title)
        if source:sources.add(source)
        if not duplicate:latest.append(row)
    return latest

def library_index():
    rows=list_jobs();entries=[]
    for row in rows:
        key=str(data_root()/'jobs'/row['job_id']/'run.json')
        entries.extend(LIBRARY_ROWS[key][2])
    return entries,rows
def library_revision(rows):
    from .library_name_checks import revision
    return digest({'versions':sorted((r['job_id'],r['version']) for r in rows),'name_checks':revision()})
def bundle_for(job_id):
    job=data_root()/'jobs'/job_id;pointer=pointer_for(job_id)
    if not pointer:
        candidate=read(job/'current.json',{});index=read(job/'source-index.json',{})
        if not candidate.get('materials'):return {'status':'NOT_ADOPTED','job_id':job_id}
        body={'candidate':candidate,'source_index':index,'job_id':job_id,'kernel_version':'0.9.0','display_state':'SAVED_DRAFT','independent_review':'NOT_REVIEWED'}
        return {**body,'version':'draft-'+digest(body),'errors':validate(candidate,index)}
    return verified_bundle(pointer['version'])

def result_complete(b):
    # Read sealed validation in its original namespace; do not silently revalidate old chemistry.
    return bool(b and b.get('candidate',{}).get('materials') and b.get('version')
                and b.get('display_state')!='SAVED_DRAFT' and not b.get('validation_errors') and not b.get('errors'))

def public_bundle_for(job_id):
    job=data_root()/'jobs'/job_id
    if read(job/'run.json',{}).get('status')!='DELIVERED' or not pointer_for(job_id):
        return {'status':'NOT_DELIVERED','job_id':job_id}
    b=bundle_for(job_id)
    return b if result_complete(b) else {'status':'NOT_DELIVERED','job_id':job_id}

def public_version(version):
    b=verified_bundle(version)
    job_id=b.get('job_id')
    if not result_complete(b) or not job_id or not public_bundle_for(job_id).get('candidate'):
        raise ValueError('RESULT_NOT_DELIVERED')
    return b
def is_library_component(m,candidate):
    if m.get('kind') in ('monomer','component'):return True
    referenced={x.get(field) for obj in candidate['materials'].values() for x in obj.get('components',[]) if isinstance(x,dict) for field in ('material_id','source_molecule_material_id')}
    return m.get('id') in referenced or m.get('role') in ('blend_component','starting_polymer_and_control')
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send(self,code,body,ctype='application/json; charset=utf-8'):
        content=json.dumps(body,ensure_ascii=False).encode() if not isinstance(body,bytes) else body
        compressed=ctype.startswith('application/json') and len(content)>1024 and any(
            part.split(';')[0].strip()=='gzip' and not any(p.strip()=='q=0' for p in part.split(';')[1:])
            for part in self.headers.get('Accept-Encoding','').split(','))
        if compressed:content=gzip.compress(content,compresslevel=1,mtime=0)
        self.send_response(code);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(content)));self.send_header('Cache-Control','no-store');self.send_header('Vary','Accept-Encoding')
        if compressed:self.send_header('Content-Encoding','gzip')
        self.end_headers();self.wfile.write(content)
    def do_GET(self):
        try:
            url=urlsplit(self.path);path=unquote(url.path);q=parse_qs(url.query)
            if path=='/api/health':return self.send(200,{'contract':'identity-single-core/1.0','kernel':'0.9.0','active':ACTIVE,'concurrency':1,'preflight':read(data_root()/'preflight.json',{}).get('status')})
            if path=='/api/jobs':return self.send(200,list_jobs())
            if path=='/api/workbench':return self.send(200,list_workbench())
            if path.startswith('/api/input/'):
                job=task_path(path.removeprefix('/api/input/'))
                if read(job/'run.json',{}).get('input_kind')!='text':raise ValueError('TEXT_TASK_REQUIRED')
                return self.send(200,{'text':(job/'input.txt').read_text(encoding='utf-8')})
            if path.startswith('/api/library-entry/'):
                version,mid=path.removeprefix('/api/library-entry/').split('/',1)
                b=public_version(version);c=b['candidate']
                entry=next((e for e in component_entries(b) if e['id']==mid),None)
                if not entry:raise ValueError('COMPONENT_NOT_FOUND')
                m=c['materials'][mid]
                from .library_name_checks import verification_for
                graphs={gid:c['graphs'][gid] for gid in m.get('graph_ids',[]) if gid in c.get('graphs',{})}
                return self.send(200,{'entry':entry,'material':m,'graphs':{gid:c['graphs'][gid] for gid in
                    m.get('graph_ids',[]) if gid in c.get('graphs',{})},'source_index':{'page_count':b.get('source_index',{}).get('page_count',0),
                    'blocks':[{'id':x['id'],'page':x.get('page')} for x in b.get('source_index',{}).get('blocks',[])]},
                    'name_verification':verification_for(entry,m,graphs),
                    'kernel_version':b.get('kernel_version'),'independent_review':b.get('independent_review','NOT_REVIEWED')})
            if path.startswith('/api/task/'):
                return self.send(200,task_summary(task_path(path.removeprefix('/api/task/'))))
            if path.startswith('/api/source-review-notes/'):
                from .postseal_notes import read_notes
                return self.send(200,read_notes(public_version(path.removeprefix('/api/source-review-notes/'))))
            if path.startswith('/api/version/'):
                return self.send(200,public_version(path.removeprefix('/api/version/')))
            if path.startswith('/api/job/'):
                job_id=path.removeprefix('/api/job/');job=data_root()/'jobs'/job_id
                if not job.resolve().is_relative_to(data_root()/'jobs'):raise ValueError('PATH_REJECTED')
                return self.send(200,{'run':read(job/'run.json'),'bundle':public_bundle_for(job_id)})
            if path.startswith('/api/evaluation/'):
                job_id=path.removeprefix('/api/evaluation/')
                task_path(job_id)
                from .evaluation_reports import for_job
                return self.send(200,for_job(job_id))
            if path=='/api/library':
                with READER_LOCK:
                    entries,rows=library_index()
                    if not q:return self.send(200,entries)
                    from .library_name_checks import summary_for,root as name_root,coverage as name_coverage
                    result=library_page(entries,rows,q);index=read(name_root()/'index.json',{})
                    result['entries']=[{**e,'name_verification':summary_for(e,index)} for e in result['entries']]
                    return self.send(200,{**result,'revision':library_revision(rows),'name_check_coverage':name_coverage()})
            if path=='/api/library-update-status':
                with READER_LOCK:
                    rows=list_jobs()
                from .library_enrichment import coverage
                from .library_name_checks import coverage as name_coverage
                return self.send(200,{'revision':library_revision(rows),'paper_count':len(rows),'coverage':coverage(),'name_check_coverage':name_coverage()})
            if path.startswith('/api/library-sources/'):
                with READER_LOCK:
                    entries,_=library_index()
                    return self.send(200,library_sources(entries,path.removeprefix('/api/library-sources/'),q))
            if path.startswith('/api/library-associations/'):
                with READER_LOCK:
                    entries,_=library_index()
                    return self.send(200,association_page(entries,path.removeprefix('/api/library-associations/'),q))
            if path.startswith('/api/library-passport/'):
                with READER_LOCK:
                    entries,_=library_index()
                    records=records_for_key(entries,path.removeprefix('/api/library-passport/'))
                    e=identity_summary(records);b=public_version(e['version']);c=b['candidate'];m=c['materials'][e['id']]
                    graphs={gid:c['graphs'][gid] for gid in m.get('graph_ids',[]) if gid in c.get('graphs',{})}
                    from .library_enrichment import properties_for
                    from .library_name_checks import verification_for
                    return self.send(200,{'entry':e,'material':m,'graphs':graphs,
                        'tool_properties':properties_for(e,m,graphs),
                        'name_verification':verification_for(e,m,graphs),
                        'independent_review':b.get('independent_review','NOT_REVIEWED')})
            if path=='/api/library-name-check-status':
                from .library_name_checks import coverage
                return self.send(200,coverage())
            if path=='/api/library-enrichment-status':
                from .library_enrichment import coverage
                return self.send(200,coverage())
            if path.startswith('/source-input/'):
                from html import escape
                job=task_path(path.removeprefix('/source-input/'))
                text=(job/'input.txt').read_text(encoding='utf-8')
                body='<html lang="zh-CN"><meta charset="utf-8"><title>输入来源</title><style>body{max-width:900px;margin:40px auto;padding:20px;font:16px/1.8 sans-serif}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><h1>用户输入的材料描述</h1><pre>'+escape(text)+'</pre></html>'
                return self.send(200,body.encode('utf-8'),'text/html; charset=utf-8')
            if path.startswith('/source-view/'):
                from .source_reader import render_source_pages
                job_id=path.removeprefix('/source-view/');root=(data_root()/'jobs'/job_id).resolve()
                if not root.is_relative_to(data_root()/'jobs') or '/' in job_id:raise ValueError('PATH_REJECTED')
                import struct
                pages=[]
                for p in sorted((root/'pages').glob('page-*.png')):
                    if not p.is_file():continue
                    with p.open('rb') as f:header=f.read(24)
                    dimensions=struct.unpack('!II',header[16:24]) if header[:8]==b'\x89PNG\r\n\x1a\n' and len(header)==24 else (None,None)
                    pages.append({'name':p.name,'width':dimensions[0],'height':dimensions[1]})
                title=read(root/'current.json',{}).get('title','来源文献')
                return self.send(200,render_source_pages(job_id,title,pages,q.get('page',[1])[0]),'text/html; charset=utf-8')
            if path.startswith('/source/'):
                rel=path.removeprefix('/source/');job_id,asset=rel.split('/',1);root=data_root()/'jobs'/job_id;target=(root/asset).resolve()
                if not target.is_relative_to(root) or not (asset in ('source.pdf','fulltext.md','pdf-text.md') or asset.startswith(('pages/','crops/'))):raise ValueError('SOURCE_ASSET_NOT_ALLOWED')
                return self.send(200,target.read_bytes(),mimetypes.guess_type(str(target))[0] or 'application/octet-stream')
            if path in ('/','/paper','/library','/knowledge') or path.startswith('/paper/'):
                return self.send(200,(APP/'web/index.html').read_bytes(),'text/html; charset=utf-8')
            target=(APP/'web'/path.lstrip('/')).resolve()
            if not target.is_relative_to(APP/'web') or not target.is_file():return self.send(404,{'error':'NOT_FOUND'})
            return self.send(200,target.read_bytes(),mimetypes.guess_type(str(target))[0] or 'application/octet-stream')
        except Exception as e:self.send(400,{'error':str(e)})
    def do_POST(self):
        try:
            if int(self.headers.get('Content-Length','0'))>28_000_000:raise ValueError('INPUT_SIZE_LIMIT')
            v=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))));path=urlsplit(self.path).path
            if path.startswith('/api/revisions/'):
                return self.send(200,preview_revision(path.rsplit('/',1)[-1],v))
            if path.startswith('/api/adopt-revision/'):
                return self.send(200,adopt_revision(path.rsplit('/',1)[-1],v['version'],v['expected_version']))
            if path=='/api/start':
                text=v.get('text','')
                if not isinstance(text,str):raise ValueError('TEXT_INPUT_INVALID')
                text=text.strip()
                if len(text)>60_000:raise ValueError('TEXT_SIZE_LIMIT')
                if text and v.get('pdf_base64'):raise ValueError('CHOOSE_TEXT_OR_PDF')
                if v.get('pdf_base64'):
                    raw=base64.b64decode(v['pdf_base64'],validate=True)
                    if not raw.startswith(b'%PDF') or len(raw)>20_000_000:raise ValueError('PDF_INPUT_INVALID')
                    pending=data_root()/'uploads';pending.mkdir(exist_ok=True);p=pending/(digest(v['pdf_base64'])+'.pdf');p.write_bytes(raw);job=init_job(pdf=p)
                elif text:job=init_job(text=text)
                else:raise ValueError('TEXT_OR_PDF_REQUIRED')
                state=read(job/'run.json');state.update(status='QUEUED',queued_at=now(),started_epoch=None,deadline_epoch=None)
                atomic(job/'run.json',state)
                title=(text.splitlines()[0][:100] if text else 'PDF 文献任务')
                atomic(job/'ui-request.json',{'title':title,'at':now()})
                enqueue(job);return self.send(202,{'job_id':job.name,'status':'QUEUED'})
            if path.startswith('/api/stop/') or path.startswith('/api/resume/'):
                job_id=path.rsplit('/',1)[-1];job=(data_root()/'jobs'/job_id).resolve()
                if not job.is_relative_to(data_root()/'jobs'):raise ValueError('PATH_REJECTED')
                state=read(job/'run.json')
                if not state or state['contract']!='identity-single-core/1.0':raise ValueError('ONLY_NEW_JOB_ALLOWED')
                if path.startswith('/api/stop/'):
                    if (job/'sealed.json').exists() or state.get('status')=='DELIVERED':raise ValueError('SEALED_JOB_IMMUTABLE_NEW_JOB_REQUIRED')
                    atomic(job/'stop-request.json',{'at':now(),'requested_by':'USER'})
                    if state.get('status')=='QUEUED':
                        state['status']='STOPPED';atomic(job/'run.json',state)
                    return self.send(200,{'status':'STOP_REQUESTED'})
                if (job/'sealed.json').exists():raise ValueError('SEALED_JOB_IMMUTABLE_NEW_JOB_REQUIRED')
                if state.get('deadline_epoch') is not None and time.time()>=state['deadline_epoch']:raise ValueError('ORIGINAL_JOB_DEADLINE_EXPIRED')
                with QUEUE_LOCK:
                    if ACTIVE==job_id or job_id in QUEUED_IDS:raise ValueError('JOB_ALREADY_QUEUED_OR_ACTIVE')
                stop=job/'stop-request.json'
                if stop.exists():stop.rename(job/('previous-stop-'+digest(read(stop))[:10]+'.json'))
                if state.get('deadline_epoch') is None:
                    state['status']='QUEUED';atomic(job/'run.json',state)
                enqueue(job);return self.send(202,{'status':'EXPLICIT_RESUME_QUEUED','budget_reset':False})
            self.send(404,{'error':'NOT_FOUND'})
        except Exception as e:self.send(400,{'error':str(e)})
def task_path(job_id):
    root=data_root()/'jobs';job=(root/job_id).resolve()
    if not job.is_relative_to(root) or '/' in job_id or '\\' in job_id or not job_id.startswith('SC-'):raise ValueError('PATH_REJECTED')
    return job

def main():
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8771);a=p.parse_args()
    http=ThreadingHTTPServer(('127.0.0.1',a.port),Handler)
    threading.Thread(target=worker,daemon=True).start()
    from .library_updates import start as start_properties
    start_properties()
    from .library_name_checks import start as start_name_checks
    start_name_checks()
    print('http://127.0.0.1:'+str(a.port),flush=True);http.serve_forever()
if __name__=='__main__':main()
