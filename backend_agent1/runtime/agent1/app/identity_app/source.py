from pathlib import Path
from urllib.parse import urlsplit
import shutil,time,uuid,zipfile
import requests
from .storage import atomic, read, now, file_hash, data_root
from polymer.literature.mineru.service import MinerUClient, safe_error
from polymer.literature.mineru.corpus import normalize_archive, digest_json
from polymer.literature.mineru_bridge import preserve_layout, OPTIONS

def download_archive(client,url,path,deadline,receipt,receipt_path):
    """Retry interrupted read-only downloads, including stream/ZIP failures."""
    attempts=receipt.setdefault('archive_attempts',[])
    for attempt in range(3):
        if time.time()>=deadline:raise TimeoutError('MINERU_ARCHIVE_DEADLINE')
        record={'attempt':attempt+1,'started_at':now()};attempts.append(record)
        atomic(receipt_path,receipt)
        try:
            client.download(url,path)
            with zipfile.ZipFile(path) as archive:
                if archive.testzip():raise zipfile.BadZipFile('Archive CRC failure')
            record.update(status='COMPLETED',sha256=file_hash(path))
            atomic(receipt_path,receipt);return
        except (requests.RequestException,zipfile.BadZipFile) as exc:
            record.update(status='FAILED',error=safe_error(exc));atomic(receipt_path,receipt)
            if attempt==2:raise
            time.sleep(min(2**attempt,max(0,deadline-time.time())))

def prepare(job):
    import fitz
    job=Path(job);state=read(job/'run.json');deadline=state['deadline_epoch']
    if state['input_kind']=='text':
        text=(job/'input.txt').read_text(encoding='utf-8');index={'page_count':0,'blocks':[{'id':'text:input','page':None,'text':text,'kind':'text'}],'source_sha256':state['source_sha256']}
        atomic(job/'source-index.json',index);(job/'fulltext.md').write_text(text,encoding='utf-8');return
    doc=fitz.open(job/'source.pdf');pages=[];blocks=[];(job/'pages').mkdir(exist_ok=True)
    for i,page in enumerate(doc,1):
        page.get_pixmap(matrix=fitz.Matrix(2,2)).save(job/'pages'/('page-'+str(i).zfill(3)+'.png'))
        text=page.get_text();pages.append('## PDF page '+str(i)+'\n\n'+text)
        blocks.append({'id':'PDF-P'+str(i),'page':i,'text':text,'kind':'pdf_text','source_type':'DIRECT_PDF_TEXT_NOT_OCR'})
    (job/'pdf-text.md').write_text('\n\n'.join(pages),encoding='utf-8')
    index={'page_count':len(doc),'blocks':blocks,'source_sha256':state['source_sha256'],'page_images':{str(i):{'file':'pages/page-'+str(i).zfill(3)+'.png','sha256':file_hash(job/'pages'/('page-'+str(i).zfill(3)+'.png'))} for i in range(1,len(doc)+1)}}
    miner=job/'mineru';miner.mkdir(exist_ok=True)
    receipt=read(miner/'receipt.json',{'network_calls':[],'status':'PREPARING','started_at':now(),'options':OPTIONS,'options_sha256':digest_json(OPTIONS),'source_sha256':state['source_sha256']})
    try:
        client=MinerUClient(data_root()/'private/mineru.env');transport=client.transport
        def traced(method,url,**kwargs):
            if time.time()>deadline-900:raise ValueError('SOURCE_PREPARATION_CLOSEOUT_BUDGET')
            record={'method':method,'host':urlsplit(url).hostname,'time':now(),'credentials_recorded':False}
            receipt['network_calls'].append(record);atomic(miner/'receipt.json',receipt)
            remaining=deadline-900-time.time()
            kwargs['timeout']=(max(.1,min(30,remaining)),max(.1,min(180,remaining)))
            try:
                result=transport(method,url,**kwargs);record['status']=result.status_code;return result
            except Exception as exc:
                record['error']=safe_error(exc);raise
            finally:atomic(miner/'receipt.json',receipt)
        client.transport=traced
        d={'doc_id':'pdf_'+state['source_sha256'][:20],'sha256':state['source_sha256'],'source_paths':[str(job/'source.pdf')],'pages':len(doc)}
        batch=receipt.get('batch_id')
        if not batch:
            batch,urls=client.submit([d],OPTIONS);receipt.update(batch_id=batch,status='UPLOADING');atomic(miner/'receipt.json',receipt)
            client.upload(d,urls[0]);receipt.update(uploaded=True,status='PARSING');atomic(miner/'receipt.json',receipt)
        limit=min(deadline-900,time.time()+600)
        while time.time()<limit:
            response=client.api('GET','/extract-results/batch/'+batch)
            matches=[r for r in response.get('extract_result',[]) if r.get('data_id')==d['doc_id'] or r.get('file_name')==d['doc_id']+'.pdf']
            if matches:
                r=matches[0];receipt['remote_state']=r.get('state');atomic(miner/'receipt.json',receipt)
                if r.get('state')=='failed':raise RuntimeError('MINERU_REMOTE_PARSE_FAILED:'+str(r.get('err_msg'))[:200])
                if r.get('state')=='done':
                    download_archive(client,r['full_zip_url'],miner/'result.zip',limit,receipt,miner/'receipt.json')
                    normalize_archive(miner/'result.zip',miner/'normalized',d,digest_json(OPTIONS),batch)
                    # This copied parser creates exact original metadata/page bindings.
                    mdoc,counts=preserve_layout(miner,{'doc_id':d['doc_id'],'pages':len(doc),'name':'source.pdf','role':'main','job_id':job.name,'source_sha256':state['source_sha256'],'options':OPTIONS,'options_hash':digest_json(OPTIONS),'batch_id':batch})
                    index['blocks'].extend({**b,'source_type':'MINERU_EXTRACTED'} for b in mdoc['blocks']);index['mineru_warnings']=mdoc['warnings'];index['mineru_assets']=mdoc['source_assets']
                    full='\n\n'.join('['+b['id']+'] page '+str(b.get('page'))+' '+b['kind']+'\n'+b['text'] for b in mdoc['blocks'])
                    (job/'fulltext.md').write_text(full,encoding='utf-8')
                    receipt.update(status='COMPLETED',counts=counts,finished_at=now(),archive_sha256=file_hash(miner/'result.zip'));break
            time.sleep(3)
        else:raise TimeoutError('MINERU_POLL_DEADLINE')
    except Exception as e:
        receipt.update(status='FAILED',error=safe_error(e),finished_at=now())
        # Original pages remain available; a parser failure is an explicit limitation.
        shutil.copy2(job/'pdf-text.md',job/'fulltext.md');index['parser_failure']=receipt['error']
    atomic(miner/'receipt.json',receipt);atomic(job/'source-index.json',index)
