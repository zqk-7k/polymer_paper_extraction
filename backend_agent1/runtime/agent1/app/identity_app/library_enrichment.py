"""Sidecar tool properties; never change a sealed material or its name.

Network access is restricted to the explicitly started batch CLI. Reader GETs
only read receipts and compute encoded-graph descriptors with the existing core.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from email.utils import parsedate_to_datetime
from pathlib import Path
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .storage import atomic, data_root, digest, now, read
from .chemistry_checks import graph_profile
from .tools import kernel

CONTRACT = 'library-tool-properties/1.0'
PUG = 'https://pubchem.ncbi.nlm.nih.gov/rest/pug'
VIEW = 'https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/'
PROPERTY_TAGS = ('IUPACName,MolecularFormula,MolecularWeight,SMILES,InChI,InChIKey,'
    'ExactMass,MonoisotopicMass,XLogP,TPSA,Complexity,Charge,HBondDonorCount,'
    'HBondAcceptorCount,RotatableBondCount,HeavyAtomCount,IsotopeAtomCount,'
    'DefinedAtomStereoCount,UndefinedAtomStereoCount,DefinedBondStereoCount,'
    'UndefinedBondStereoCount,CovalentUnitCount')
PROPERTIES = {
    'MolecularFormula':('分子式',''), 'MolecularWeight':('摩尔质量','g/mol'),
    'ExactMass':('精确质量','Da'), 'MonoisotopicMass':('单同位素质量','Da'),
    'XLogP':('XLogP（计算）',''), 'TPSA':('拓扑极性表面积','Å²'),
    'Complexity':('分子复杂度',''), 'Charge':('总形式电荷',''),
    'HBondDonorCount':('氢键供体数',''), 'HBondAcceptorCount':('氢键受体数',''),
    'RotatableBondCount':('可旋转键数',''), 'HeavyAtomCount':('非氢原子数',''),
    'IsotopeAtomCount':('同位素原子数',''), 'DefinedAtomStereoCount':('已定义立体原子数',''),
    'UndefinedAtomStereoCount':('未定义立体原子数',''),
    'DefinedBondStereoCount':('已定义立体键数',''),
    'UndefinedBondStereoCount':('未定义立体键数',''), 'CovalentUnitCount':('共价单元数','')}
HEADINGS = {
    'Melting Point':'熔点', 'Boiling Point':'沸点', 'Density':'密度',
    'Solubility':'溶解性', 'Vapor Pressure':'蒸气压', 'Flash Point':'闪点',
    'Autoignition Temperature':'自燃温度', 'Viscosity':'黏度',
    'Refractive Index':'折射率', 'Dissociation Constants':'解离常数',
    'LogP':'实验分配系数', 'Physical Description':'外观与物态',
    'Decomposition':'分解条件', 'GHS Classification':'GHS 危害分类',
    'CAS':'CAS 登记信息', 'IUPAC Name':'PubChem IUPAC 名称',
    'Depositor-Supplied Synonyms':'提交者提供的名称'}
STATUS_LABELS = {'MATCHED':'结构匹配', 'NAME_ONLY':'名称查询候选，结构未核对',
    'COMPUTED_ONLY':'在线结构计算，未对应登记 CID',
    'MISMATCH':'数据库结构与保存图不同', 'AMBIGUOUS':'多个数据库候选',
    'NO_MATCH':'未检索到记录', 'FAILED':'查询失败', 'NOT_APPLICABLE':'不适用有限分子查询',
    'NOT_QUERIED':'等待全库查询', 'UNSUPPORTED':'结构核对未支持'}


class PubChemPaused(RuntimeError):
    """The provider requested a cooldown; unstarted queries remain pending."""


def root(): return data_root() / 'library-enrichment'


def query_spec(graph=None, name=None):
    value = graph.get('canonical_smiles') if graph else name
    return {'kind':'smiles' if graph else 'name', 'value':value}


def query_key(spec): return digest({'contract':CONTRACT, **spec})


def query_path(spec): return root() / 'queries' / (query_key(spec)+'.json')


def finite_graph(g):
    return (g.get('scope')=='finite_molecule' and g.get('canonical_smiles') and
            '*' not in g['canonical_smiles'] and not g.get('ports'))


def name_query(material, graphs):
    # A polymer/unit/fragment never becomes a finite molecule by searching its name.
    if graphs or material.get('kind') not in ('component','monomer'): return None
    name=(material.get('most_likely_name') or {}).get('text') or material.get('label')
    import re
    if not isinstance(name,str) or not name.strip() or len(name)>500 or re.search(
            r'(?i)\bpoly\w*|graft|copolymer|network|\[\*|\(\*|聚合|共聚|接枝|混合|固化',name):return None
    return query_spec(name=name)


def annotations(payload):
    """Retain full value strings/units/conditions and each depositor reference."""
    record=payload.get('Record',{});refs={r['ReferenceNumber']:r for r in record.get('Reference',[])}
    values=[]
    def walk(sections, path):
        for section in sections:
            heading=section.get('TOCHeading',''); trail=[*path,heading]
            if heading in HEADINGS:
                for info in section.get('Information',[]):
                    value=info.get('Value',{});texts=[x.get('String','') for x in value.get('StringWithMarkup',[])]
                    if value.get('Number') is not None:texts.append(', '.join(map(str,value['Number'])))
                    if not texts:continue
                    reference=refs.get(info.get('ReferenceNumber'),{})
                    values.append({'key':heading,'label':HEADINGS[heading],'values':texts,
                        'unit':value.get('Unit',''),'name':info.get('Name'),
                        'description':info.get('Description'), 'reference':reference,
                        'reference_number':info.get('ReferenceNumber'), 'path':trail,
                        'evidence_kind':'DATABASE_ANNOTATION', 'value_metadata':value})
            walk(section.get('Section',[]),trail)
    walk(record.get('Section',[]),[])
    return values


def database_profile(candidate, lookup):
    cid=candidate.get('CID');registered=isinstance(cid,int) and cid>0
    compound=read(root()/'compounds'/f'{cid}.json',{}) if registered else {}
    properties=candidate or {}
    return {'cid':cid if registered else None,'returned_cid':cid,'registered_record':registered,
        'url':f'https://pubchem.ncbi.nlm.nih.gov/compound/{cid}' if registered else None,
        'iupac_name':properties.get('IUPACName'),'smiles':properties.get('SMILES') or properties.get('IsomericSMILES'),
        'inchi':properties.get('InChI'),'inchikey':properties.get('InChIKey'),
        'properties':[{'key':k,'label':label,'value':properties[k],'unit':unit,
            'method':'PubChem PUG-REST','evidence_kind':'PUBCHEM_COMPUTED'}
            for k,(label,unit) in PROPERTIES.items() if properties.get(k) is not None],
        'annotations':compound.get('annotations',[]), 'annotation_status':compound.get('status','NOT_QUERIED') if registered else 'NOT_APPLICABLE',
        'annotation_receipt':compound.get('receipt'), 'retrieved_at':lookup.get('finished_at'),
        'receipt':lookup.get('receipt')}


def coverage():
    pointer=read(root()/'latest-job.json',{});job_id=pointer.get('job_id')
    if not job_id or Path(job_id).name!=job_id:return {'status':'NOT_STARTED'}
    result=read(root()/'jobs'/job_id/'status.json',{'status':'NOT_STARTED'})
    wait=read(root()/'jobs'/job_id/'provider-wait.json',{})
    if result.get('status') in ('RUNNING','RATE_LIMITED') and wait.get('retry_at',0)>time.time():
        result={**result,'provider_wait':wait}
    return {**result,'automatic_updates':read(root()/'watch-status.json',{'status':'NOT_STARTED'})}


def properties_for(entry, material, graphs):
    structures=[]
    for gid,g in graphs.items():
        local=read(root()/'local'/f"{digest({'smiles':g.get('canonical_smiles'),'scope':g.get('scope')})}.json",{})
        if not local:local=graph_profile(g)
        spec=query_spec(g) if finite_graph(g) else None
        lookup=read(query_path(spec),{}) if spec else {}
        status=lookup.get('status','NOT_QUERIED') if spec else 'NOT_APPLICABLE'
        structures.append({'graph_id':gid,'scope':g.get('scope'),'input_smiles':g.get('canonical_smiles'),
            'local':local,'status':status,'status_label':STATUS_LABELS.get(status,status),
            'match':lookup.get('match'), 'lookup':lookup,
            'database':[database_profile(c,lookup) for c in lookup.get('candidates',[])[:5]]})
    spec=name_query(material,graphs);named=read(query_path(spec),{}) if spec else {}
    return {'contract':CONTRACT,'identity_key':entry['identity_key'], 'structures':structures,
        'name_lookup':{**named,'database':[database_profile(c,named) for c in named.get('candidates',[])[:5]]}
            if spec else None,'coverage':coverage(), 'kernel_version':'0.9.0',
        'independent_review':'NOT_REVIEWED','preferred_iupac_name':None}


class PubChemClient:
    def __init__(self, job, rate=2):
        self.job=Path(job);self.rate=rate;self.lock=threading.Lock();self.next_time=0
        wait=read(root()/'provider-wait.json',{})
        self.cooldown_until=time.monotonic()+max(0,wait.get('retry_at',0)-time.time())
        self.cid_locks={};self.events=0;self.paused=threading.Event()

    def wait(self):
        while True:
            if self.paused.is_set():raise PubChemPaused('PUBCHEM_PROVIDER_COOLDOWN')
            with self.lock:
                current=time.monotonic();delay=max(self.next_time,self.cooldown_until)-current
                if delay<=0:
                    self.next_time=current+1/self.rate
                    return
            time.sleep(min(2,delay))

    def request(self,url,form=None):
        # Public annotations are data, never actions or instructions.
        attempts=[]
        for attempt in range(3):
            self.wait();start=now();body=urlencode(form).encode() if form else None
            req=Request(url,data=body,headers={'User-Agent':'PolymerIdentityApp/0.9 library-enrichment',
                'Accept':'application/json',**({'Content-Type':'application/x-www-form-urlencoded'} if form else {})})
            status='FAILED';payload={};http=None;error=None;sha=None;headers={};error_body=None
            try:
                with urlopen(req,timeout=25) as response:
                    http=response.status;headers=dict(response.headers);data=response.read(12_000_001)
                sha=hashlib.sha256(data).hexdigest()
                if len(data)>12_000_000:raise ValueError('PUBCHEM_RESPONSE_TOO_LARGE')
                payload=json.loads(data);status='OK'
            except HTTPError as exc:
                http=exc.code;headers=dict(exc.headers or {});error=str(exc);status='NO_MATCH' if http==404 else 'FAILED'
                try:
                    data=exc.read(100_000);sha=hashlib.sha256(data).hexdigest();error_body=data.decode('utf-8',errors='replace');payload=json.loads(data)
                except (ValueError,OSError):pass
            except (URLError,OSError,ValueError) as exc:error=type(exc).__name__+': '+str(exc)
            event={'url':url,'form':form,'started_at':start,'finished_at':now(),'http_status':http,
                'status':status,'error':error,'response_sha256':sha,'payload':payload,
                'response_headers':{k:v for k,v in headers.items() if k.lower() in ('retry-after','x-throttling-control','date')},
                **({'error_response_text':error_body} if error_body else {})}
            receipt=digest(event);atomic(self.job/'receipts'/(receipt+'.json'),event);attempts.append(receipt)
            if status!='FAILED' or http in (400,405,501):break
            if http in (429,503):
                retry=next((v for k,v in headers.items() if k.lower()=='retry-after'),None)
                try:delay=max(1,float(retry))
                except (ValueError,TypeError):
                    try:delay=max(1,parsedate_to_datetime(retry).timestamp()-time.time())
                    except (ValueError,TypeError,AttributeError):delay=(1800 if http==429 else 60)*(attempt+1)
                with self.lock:self.cooldown_until=max(self.cooldown_until,time.monotonic()+delay)
                wait={'status':'RATE_LIMITED','retry_at':time.time()+delay,
                    'http_status':http,'updated_at':now(),'delay_seconds':delay}
                atomic(self.job/'provider-wait.json',wait);atomic(root()/'provider-wait.json',wait)
                if http==429:
                    self.paused.set()
                    break
            else:time.sleep(2*(attempt+1))
        return {**event,'receipt':receipt,'attempt_receipts':attempts}

    def compound(self,cid):
        if not isinstance(cid,int) or cid<=0:return {'cid':cid,'status':'NOT_APPLICABLE','annotations':[],'reason':'NO_REGISTERED_CID'}
        with self.lock:guard=self.cid_locks.setdefault(cid,threading.Lock())
        with guard:
            path=root()/'compounds'/f'{cid}.json';stored=read(path,{})
            if stored.get('status') in ('OK','NO_MATCH'):return stored
            response=self.request(VIEW+str(cid)+'/JSON')
            result={k:response[k] for k in ('status','finished_at','receipt','error','attempt_receipts')}
            result.update(cid=cid,annotations=annotations(response['payload']))
            atomic(path,result);return result

    def resolve(self,spec):
        path=query_path(spec);cached=read(path,{})
        if cached.get('status') in ('MATCHED','COMPUTED_ONLY','NAME_ONLY','MISMATCH','AMBIGUOUS','NO_MATCH','UNSUPPORTED'):
            for c in cached.get('candidates',[])[:5]:self.compound(c['CID'])
            return cached
        value=spec['value'];kind=spec['kind']
        # POST avoids the URL syntax issue for '/' in stereo SMILES and long graphs.
        url=PUG+'/compound/'+kind+'/property/'+PROPERTY_TAGS+'/JSON'
        response=self.request(url,{kind:value})
        candidates=response['payload'].get('PropertyTable',{}).get('Properties',[])
        status='NO_MATCH' if response['status']=='NO_MATCH' else 'FAILED';match=None
        if response['status']=='OK':
            if not candidates:status='NO_MATCH'
            elif len(candidates)>1:status='AMBIGUOUS'
            elif kind=='name':status='NAME_ONLY'
            else:
                candidate=candidates[0];encoded=candidate.get('SMILES') or candidate.get('IsomericSMILES')
                match=kernel().dispatch('compare_molecules',{'left':value,'right':encoded})
                status=('MATCHED' if match.get('relation')=='EQUAL' else 'MISMATCH') if match.get('status')=='PARSED' else 'UNSUPPORTED'
                if status=='MATCHED' and not (isinstance(candidate.get('CID'),int) and candidate['CID']>0):status='COMPUTED_ONLY'
        result={'contract':CONTRACT,'query':spec,'status':status,'match':match,'candidates':candidates,
            'finished_at':response['finished_at'],'receipt':response['receipt'],
            'attempt_receipts':response['attempt_receipts'],'error':response['error'],
            'http_status':response.get('http_status'),
            'atom_maps_preserved_in_input':True,'match_scope':'encoded finite graph; atom maps are correspondence labels',
            'independent_review':'NOT_REVIEWED','preferred_iupac_name':None}
        atomic(path,result)
        # Even unverified hits are retained as candidates, never assigned as facts.
        for c in candidates[:5]:self.compound(c['CID'])
        return result


def create_batch(job_id):
    from .server import library_index, public_version
    from .library import identity_groups
    if Path(job_id).name!=job_id:raise ValueError('JOB_ID_INVALID')
    job=root()/'jobs'/job_id
    if job.exists():raise ValueError('ENRICHMENT_JOB_EXISTS_USE_RESUME')
    job.mkdir(parents=True);entries,papers=library_index();groups=identity_groups(entries)
    queries={};items=[];bundles={}
    for key,records in groups.items():
        e=records[0];version=e['version']
        if version not in bundles:bundles={version:public_version(version)}
        c=bundles[version]['candidate'];material=c['materials'][e['id']]
        graphs={gid:c['graphs'][gid] for gid in material.get('graph_ids',[]) if gid in c['graphs']}
        keys=[]
        for g in graphs.values():
            local_key=digest({'smiles':g.get('canonical_smiles'),'scope':g.get('scope')})
            atomic(root()/'local'/(local_key+'.json'),graph_profile(g))
            if finite_graph(g):
                spec=query_spec(g);qk=query_key(spec);queries[qk]=spec;keys.append(qk)
        if not keys and (spec:=name_query(material,graphs)):
            qk=query_key(spec);queries[qk]=spec;keys.append(qk)
        items.append({'identity_key':key,'label':e['label'],'queries':keys,
            'scope_status':'QUERY_PLANNED' if keys else 'NOT_APPLICABLE',
            'sources':[{k:r[k] for k in ('job_id','version','id')} for r in records]})
    manifest={'contract':CONTRACT,'job_id':job_id,'created_at':now(),'paper_count':len(papers),
        'record_count':len(entries),'identity_count':len(groups),'items':items,'queries':queries,
        'rate_per_second':2,'kernel_version':'0.9.0','independent_review':'NOT_REVIEWED'}
    atomic(job/'manifest.json',manifest);atomic(root()/'latest-job.json',{'job_id':job_id})
    atomic(job/'status.json',{'job_id':job_id,'status':'PLANNED','query_total':len(queries),
        'identity_total':len(groups),'scope_excluded':sum(not i['queries'] for i in items),'completed':0})
    return job


def _execute_batch(job,rate=None):
    manifest=read(job/'manifest.json');queries=manifest['queries'];client=PubChemClient(job,rate or manifest['rate_per_second'])
    counts=Counter();completed=0;started=now();query_status={};annotation_status={}
    def save(status):
        wait=read(root()/'provider-wait.json',{})
        atomic(job/'status.json',{'job_id':manifest['job_id'],'status':status,'started_at':started,
            'updated_at':now(),'completed':completed,'query_total':len(queries),
            'identity_total':manifest['identity_count'],'scope_excluded':sum(not x['queries'] for x in manifest['items']),
            'statuses':dict(counts),'remaining':len(queries)-completed,
            **({'annotation_statuses':dict(annotation_status)} if annotation_status else {}),
            **({'retry_at':wait.get('retry_at')} if status=='RATE_LIMITED' else {})})
    save('RUNNING')
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(client.resolve,spec):qk for qk,spec in queries.items()}
        for future in as_completed(futures):
            key=futures[future]
            try:result=future.result()
            except PubChemPaused:
                for other in futures:other.cancel()
                break
            except Exception as exc:
                result={'contract':CONTRACT,'query':queries[key],'status':'FAILED','finished_at':now(),
                    'error':type(exc).__name__+': '+str(exc),'candidates':[]};atomic(query_path(queries[key]),result)
            query_status[key]=result['status'];counts[result['status']]+=1;completed+=1;save('RUNNING')
            if completed%25==0 or completed==len(queries):print(json.dumps({'completed':completed,'total':len(queries),'statuses':dict(counts)}),flush=True)
            if client.paused.is_set():
                for other in futures:other.cancel()
                break
    if client.paused.is_set():
        save('RATE_LIMITED');return read(job/'status.json')
    for item in manifest['items']:
        atomic(job/'items'/(item['identity_key']+'.json'),{**item,'query_statuses':{k:query_status[k] for k in item['queries']},'finished_at':now()})
    cids={c['CID'] for spec in queries.values() for c in read(query_path(spec),{}).get('candidates',[])[:5] if isinstance(c.get('CID'),int) and c['CID']>0}
    annotation_status.update(Counter(read(root()/'compounds'/f'{cid}.json',{}).get('status','NOT_QUERIED') for cid in cids))
    save('COMPLETED_WITH_FAILURES' if counts['FAILED'] or annotation_status.get('FAILED') or annotation_status.get('NOT_QUERIED') else 'COMPLETED')
    return read(job/'status.json')


def execute_batch(job,rate=None):
    from .library_updates import worker_lock
    with worker_lock() as acquired:
        if not acquired:raise ValueError('PROPERTY_WORKER_BUSY_RETRY_AFTER_CURRENT_BATCH')
        return _execute_batch(job,rate)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--job',required=True);parser.add_argument('--resume',action='store_true');parser.add_argument('--rate',type=float);parser.add_argument('--until-complete',action='store_true')
    args=parser.parse_args();job=root()/'jobs'/args.job if args.resume else create_batch(args.job)
    if not (job/'manifest.json').is_file():raise ValueError('ENRICHMENT_MANIFEST_MISSING')
    if args.rate is not None and not 0<args.rate<=2:raise ValueError('REQUEST_RATE_OUT_OF_RANGE')
    if args.resume:
        atomic(job/('resume-'+str(time.time_ns())+'.json'),{'resumed_at':now(),'rate':args.rate,
            'implementation_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    while True:
        wait=read(root()/'provider-wait.json',{})
        while wait.get('retry_at',0)>time.time():
            time.sleep(min(30,wait['retry_at']-time.time()));wait=read(root()/'provider-wait.json',{})
        result=execute_batch(job,args.rate)
        print(json.dumps(result,ensure_ascii=False),flush=True)
        if not args.until_complete or result['status']!='RATE_LIMITED':break


if __name__=='__main__':main()
