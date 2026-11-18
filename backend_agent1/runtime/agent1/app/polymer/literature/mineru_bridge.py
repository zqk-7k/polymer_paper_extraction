"""MinerU async ingestion with immutable source/ZIP/layout/image provenance.
Derived transport and archive verification live in .mineru (reference copied read-only).
"""
from __future__ import annotations
import base64, hashlib, json, re, threading, time, uuid, zipfile
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import urlencode
from .documents import make_document, digest, MAX_BYTES
from .mineru.corpus import atomic_json, sha256, digest_json, normalize_archive, validate_document
from .mineru.service import MinerUClient, safe_error

OPTIONS = {'model_version':'vlm','enable_formula':True,'enable_table':True,'language':'en'}

def now():
    return datetime.now(timezone.utc).isoformat()

def asset_url(ident, name):
    return '/mineru-asset?' + urlencode({'id':ident,'file':name})

def text_value(value):
    if isinstance(value, str): return value
    if isinstance(value, list): return '\n'.join(text_value(v) for v in value if text_value(v))
    if isinstance(value, dict): return text_value(value.get('text', value.get('content', '')))
    return ''

def preserve_layout(folder, state):
    """Retain all returned JSON and exact image references; never invent page offsets."""
    doc_id=state['doc_id']; normalized=folder/'normalized'/doc_id
    proof=json.loads((normalized/'provenance.json').read_text(encoding='utf-8'))
    metadata={}; json_files=[]; blocks=None; content_name=None
    with zipfile.ZipFile(folder/'result.zip') as z:
        # normalize_archive has already rejected unsafe/duplicate paths and oversized ZIPs.
        for name in z.namelist():
            if name.lower().endswith('.json'):
                raw=z.read(name)
                if len(raw)>60_000_000: raise ValueError('MINERU_METADATA_SIZE_LIMIT')
                target='metadata-'+str(len(json_files)+1)+'.json'
                (folder/target).write_bytes(raw)
                json_files.append({'file':target,'original_name':name,'sha256':digest(raw)})
                metadata[name]=json.loads(raw.decode('utf-8-sig'))
        candidates=[n for n,v in metadata.items() if n.endswith('content_list.json') and isinstance(v,list)]
        if len(candidates)==1: content_name=candidates[0];blocks=metadata[content_name]
        if blocks is None:
            candidates=[n for n,v in metadata.items() if n.endswith('content_list_v2.json') and isinstance(v,list)]
            if len(candidates)==1:
                content_name=candidates[0];value=metadata[content_name]
                blocks=[dict(b,page_idx=i) for i,page in enumerate(value) for b in page] if all(isinstance(x,list) for x in value) else value
        if blocks is None:
            raise ValueError('MINERU_CONTENT_LIST_MISSING_OR_AMBIGUOUS_LAYOUT_REVIEW_REQUIRED')
        if not all(isinstance(b,dict) for b in blocks): raise ValueError('MINERU_CONTENT_LIST_FORMAT_UNSUPPORTED')
        image_lookup={}
        for name in z.namelist():
            if PurePosixPath(name).suffix.lower() in {'.png','.jpg','.jpeg','.webp','.gif','.bmp','.tif','.tiff'}:
                content=z.read(name);key=digest(content)
                match=[rel for rel,h in proof['assets'].items() if h==key]
                if len(match)==1:image_lookup[name.replace('\\','/')]=match[0]
    page_blocks=defaultdict(list); index=[]; assets=[]; missing=[]
    for i,block in enumerate(blocks):
        kind=block.get('type','unknown');page=block.get('page_idx')
        if type(page) is not int or not 0<=page<state['pages']:
            page=None;missing.append({'block':i,'reason':'PAGE_INDEX_MISSING_OR_INVALID'})
        else:page+=1
        pieces=[]
        if kind in ('table','image'):
            pieces.extend(text_value(block.get(k)) for k in (kind+'_caption',kind+'_body',kind+'_footnote'))
        else:pieces.append(text_value(block.get('text',block.get('content',''))))
        text='\n'.join(p for p in pieces if p)
        bid='B'+str(i+1).zfill(5)
        item={'id':bid,'kind':kind,'page':page,'source_block_index':i,'bbox':block.get('bbox'),'text':text}
        image=block.get('img_path') or block.get('image_path')
        if image:
            clean=str(image).replace('\\','/');rel=image_lookup.get(clean)
            if not rel:
                matches={v for k,v in image_lookup.items() if PurePosixPath(k).name==PurePosixPath(clean).name}
                if len(matches)==1:rel=next(iter(matches))
            if rel:
                target='image-'+str(len(assets)+1)+Path(rel).suffix
                shutil_copy=normalized/rel
                (folder/target).write_bytes(shutil_copy.read_bytes())
                a={'block_id':bid,'kind':kind,'page':page,'file':target,'image_url':asset_url(state['job_id'],target),'sha256':proof['assets'][rel],
                   'caption':text_value(block.get(kind+'_caption')),'bbox':block.get('bbox'),'original_img_path':image}
                if kind=='table':a['table_html']=text_value(block.get('table_body'));a['footnotes']=block.get('table_footnote',[])
                assets.append(a);item['asset_file']=target
            else:missing.append({'block':i,'reason':'IMAGE_REFERENCE_UNRESOLVED','path':image})
        if kind in ('table','image') and page:
            # Content-list bbox coordinate scales differ by server version. Keep raw bbox;
            # default to the actual full PDF page until its coordinate scale is verified.
            item['visual_region']={'page':page,'bbox':[0,0,1,1],'task':'tables' if kind=='table' else 'structures','label':bid+' '+kind,
                                   'selection_basis':'FULL_PAGE_WITH_PARSER_BLOCK_HINT','block_id':bid}
        page_blocks[page].append(item);index.append(item)
    pages=[];cursor=0
    for page in sorted(k for k in page_blocks if k is not None)+([None] if None in page_blocks else []):
        parts=[]
        for item in page_blocks[page]:
            item['start']=cursor+sum(len(s)+2 for s in parts);parts.append(item['text']);item['end']=item['start']+len(item['text'])
        text='\n\n'.join(parts);pages.append({'page':page,'text':text});cursor+=len(text)+1
    doc=make_document(state['name'],pages,state['role']);doc['input_sha256']=state['source_sha256']
    doc['parser']={'engine':'MinerU','model_version':state['options']['model_version'],'job_id':state['job_id'],'batch_id':state['batch_id'],
                   'archive_sha256':sha256(folder/'result.zip'),'options_hash':state['options_hash'],'source_pages':state['pages'],
                   'content_list':content_name,'parse_status':'PARSED','independent_review':'NOT_REVIEWED'}
    doc['source_assets']=assets;doc['blocks']=index
    doc['visual_regions']=[b['visual_region'] for b in index if 'visual_region' in b]
    doc['warnings']=[{'code':'MINERU_OUTPUT_REQUIRES_SEMANTIC_AND_VISUAL_VALIDATION'},*missing]
    manifest={'metadata':json_files,'assets':assets,'source_sha256':state['source_sha256'],'document_sha256':digest_json(doc)}
    atomic_json(folder/'document.json',doc);atomic_json(folder/'asset-manifest.json',manifest)
    return doc,{'blocks':len(index),'tables':sum(b['kind']=='table' for b in index),'figures':sum(b['kind']=='image' for b in index),
                'images':len(assets),'pages':state['pages'],'mapped_pages':len({b['page'] for b in index if b['page']}),'metadata_files':len(json_files),'warnings':len(missing)}

class MinerUService:
    def __init__(self, root, env_file):
        self.root=Path(root);self.env_file=Path(env_file);self.lock=threading.RLock();self.slots=threading.BoundedSemaphore(2);self.active=set()
    def folder(self,ident):
        if not isinstance(ident,str) or not re.fullmatch(r'MU-[0-9TZ]+-[a-f0-9]{8}',ident):raise ValueError('MINERU_JOB_ID_INVALID')
        return self.root/ident
    def read(self,ident):
        with self.lock:return json.loads((self.folder(ident)/'run.json').read_text(encoding='utf-8'))
    def update(self,ident,**changes):
        with self.lock:
            state=self.read(ident);state.update(changes);state['updated_at']=now();atomic_json(self.folder(ident)/'run.json',state);return state
    def get(self,ident):
        state=self.read(ident)
        if state['status']=='COMPLETED':
            folder=self.folder(ident);doc=json.loads((folder/'document.json').read_text(encoding='utf-8'))
            manifest=json.loads((folder/'asset-manifest.json').read_text(encoding='utf-8'))
            if digest_json(doc)!=manifest['document_sha256'] or sha256(folder/'source.pdf')!=state['source_sha256']:raise ValueError('MINERU_PROVENANCE_HASH_MISMATCH')
            for a in manifest['assets']+manifest['metadata']:
                if sha256(folder/a['file'])!=a['sha256']:raise ValueError('MINERU_ASSET_HASH_MISMATCH')
            state['document']=doc
        return state
    def asset(self,ident,name):
        folder=self.folder(ident);state=self.get(ident)
        approved={'source.pdf','result.zip','document.json','asset-manifest.json'}
        if state['status']=='COMPLETED':
            manifest=json.loads((folder/'asset-manifest.json').read_text(encoding='utf-8'))
            approved.update(a['file'] for a in manifest['assets']+manifest['metadata'])
        if name not in approved:raise ValueError('MINERU_ASSET_NOT_ALLOWED')
        path=folder/name
        if not path.is_file():raise ValueError('MINERU_ASSET_NOT_FOUND')
        return path
    def start(self,inputs):
        if inputs.get('allow_mineru') is not True:raise ValueError('MINERU_PDF_UPLOAD_AUTHORIZATION_REQUIRED')
        name=inputs.get('name');role=inputs.get('role','main')
        if not isinstance(name,str) or Path(name).suffix.lower()!='.pdf' or len(name)>300:raise ValueError('MINERU_PDF_NAME_REQUIRED')
        if role not in ('main','supplement','reference'):raise ValueError('DOCUMENT_ROLE_INVALID')
        try:data=base64.b64decode(inputs.get('data_base64',''),validate=True)
        except Exception:raise ValueError('DOCUMENT_BASE64_REQUIRED') from None
        if not 0<len(data)<=MAX_BYTES:raise ValueError('MINERU_LOCAL_UPLOAD_LIMIT_20_MB')
        import fitz
        with fitz.open(stream=data,filetype='pdf') as pdf:
            if pdf.is_encrypted or not 1<=len(pdf)<=200:raise ValueError('MINERU_PDF_PREFLIGHT_FAILED')
            pages=len(pdf)
        MinerUClient(self.env_file) # Missing configuration fails before queue creation.
        if not self.slots.acquire(False):raise ValueError('MINERU_TWO_JOBS_ALREADY_ACTIVE')
        ident='MU-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
        folder=self.folder(ident)
        try:
            folder.mkdir(parents=True,exist_ok=False);(folder/'source.pdf').write_bytes(data)
            state={'job_id':ident,'name':name,'role':role,'status':'QUEUED','created_at':now(),'source_sha256':digest(data),'pages':pages,
                   'doc_id':'pdf_'+digest(data)[:20],'options':dict(OPTIONS),'options_hash':digest_json(OPTIONS),'network_calls':0,
                   'source_url':asset_url(ident,'source.pdf'),'authorization':'USER_ALLOWED_MINERU_PDF_UPLOAD','cancel_requested':False}
            atomic_json(folder/'run.json',state);self.active.add(ident)
            threading.Thread(target=self.execute,args=(ident,),daemon=True).start();return state
        except Exception:self.slots.release();raise
    def resume(self,ident):
        with self.lock:
            state=self.read(ident)
            if state['status']=='COMPLETED':return self.get(ident)
            if ident in self.active:raise ValueError('MINERU_JOB_ALREADY_ACTIVE')
            if not state.get('batch_id'):raise ValueError('MINERU_NO_BATCH_TO_RESUME_EXPLICIT_NEW_UPLOAD_REQUIRED')
            if not self.slots.acquire(False):raise ValueError('MINERU_TWO_JOBS_ALREADY_ACTIVE')
            self.active.add(ident);self.update(ident,cancel_requested=False,status='QUEUED')
            threading.Thread(target=self.execute,args=(ident,),daemon=True).start();return self.read(ident)
    def execute(self,ident,wait_seconds=600):
        folder=self.folder(ident);state=self.read(ident)
        try:
            client=MinerUClient(self.env_file)
            transport=client.transport
            def traced(method,url,**kwargs):
                from urllib.parse import urlsplit
                if urlsplit(url).scheme!='https':raise ValueError('MINERU_HTTPS_REQUIRED')
                kwargs['allow_redirects']=False
                current=self.read(ident);n=current['network_calls']+1;self.update(ident,network_calls=n)
                result=transport(method,url,**kwargs)
                atomic_json(folder/f'http-{n:03d}.json',{'method':method,'host':urlsplit(url).hostname,'path':urlsplit(url).path,'http_status':result.status_code,'time':now(),'credentials_recorded':False})
                return result
            client.transport=traced
            document={'doc_id':state['doc_id'],'sha256':state['source_sha256'],'source_paths':[str(folder/'source.pdf')],'pages':state['pages']}
            if not state.get('batch_id'):
                self.update(ident,status='SUBMITTING')
                batch,urls=client.submit([document],state['options']);self.update(ident,batch_id=batch,status='UPLOADING')
                # Signed URL is deliberately not written to run.json or public logs.
                client.upload(document,urls[0]);self.update(ident,uploaded=True,status='PARSING')
            deadline=time.monotonic()+wait_seconds
            while True:
                state=self.read(ident)
                if state.get('cancel_requested'):self.update(ident,status='PAUSED',pause_reason='LOCAL_POLLING_CANCELLED_REMOTE_JOB_MAY_CONTINUE');return
                data=client.api('GET','/extract-results/batch/'+state['batch_id'])
                entries=[r for r in data.get('extract_result',[]) if r.get('data_id')==state['doc_id'] or r.get('file_name')==state['doc_id']+'.pdf']
                if entries:
                    result=entries[0];remote=result.get('state');self.update(ident,remote_state=remote,progress=result.get('extract_progress'))
                    if remote=='failed':raise ValueError('MINERU_REMOTE_PARSE_FAILED: '+str(result.get('err_msg',''))[:200])
                    if remote=='waiting-file' and not state.get('uploaded'):raise ValueError('MINERU_UPLOAD_NOT_CONFIRMED_NEW_UPLOAD_REQUIRED')
                    if remote=='done':
                        if not result.get('full_zip_url'):raise ValueError('MINERU_RESULT_URL_MISSING')
                        self.update(ident,status='DOWNLOADING');client.download(result['full_zip_url'],folder/'result.zip')
                        self.update(ident,status='VERIFYING')
                        normalize_archive(folder/'result.zip',folder/'normalized',document,state['options_hash'],state['batch_id'])
                        doc,counts=preserve_layout(folder,self.read(ident))
                        self.update(ident,status='COMPLETED',counts=counts,finished_at=now(),result_archive_sha256=sha256(folder/'result.zip'));return
                if time.monotonic()>=deadline:self.update(ident,status='PAUSED',pause_reason='POLL_DEADLINE_RESUME_SAME_BATCH');return
                time.sleep(3)
        except Exception as error:
            self.update(ident,status='FAILED',error={'type':type(error).__name__,'message':safe_error(error)},finished_at=now())
        finally:
            with self.lock:self.active.discard(ident)
            self.slots.release()
    def call(self,operation,inputs):
        if operation=='literature_mineru_start':return self.start(inputs)
        if operation=='literature_mineru_get':return self.get(inputs.get('job_id'))
        if operation=='literature_mineru_resume':return self.resume(inputs.get('job_id'))
        if operation=='literature_mineru_cancel':return self.update(inputs.get('job_id'),cancel_requested=True)
        if operation=='literature_mineru_list':return {'jobs':[self.read(p.parent.name) for p in sorted(self.root.glob('MU-*/run.json'),reverse=True)[:50]]}
        raise ValueError('MINERU_OPERATION_UNKNOWN')
