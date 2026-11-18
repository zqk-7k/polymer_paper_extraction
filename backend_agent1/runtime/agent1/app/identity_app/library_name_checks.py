"""Version-bound post-seal OPSIN evidence. Reader GETs never execute chemistry.

An encoded name/graph match is neither preferred-name certification nor a
source/material identity claim. Sealed bundles and first-run receipts are read
only; supplements have their own immutable input and tool bindings.
"""
from copy import deepcopy
from pathlib import Path
import threading
import time

from .storage import atomic, data_root, digest, read, now
from .chemistry_checks import parser_check

CONTRACT='library-name-check/1.0'
LABELS={'GRAPH_MATCH':'名称与保存结构一致', 'PREPARED_GRAPH_MATCH':'补充名称与保存结构一致',
    'MISMATCH':'名称与保存结构不一致', 'UNSUPPORTED':'名称解析未支持',
    'PARSER_GRAPH_BOUNDARY':'元素原子：超出有限分子核对范围',
    'NO_FINITE_GRAPH':'缺少可核对的有限分子图', 'NOT_APPLICABLE':'不适用有限分子核对',
    'NO_NAME':'缺少待核对名称', 'NOT_CHECKED':'尚无补充核验',
    'BINDING_INVALID':'补充核验绑定失效'}
_LOCK=threading.RLock()

def root():return data_root()/'library-name-checks'

def binding(entry,material,graphs):
    return {'version':entry.get('version'),'job_id':entry.get('job_id'),
        'material_id':material.get('id'),'material_sha256':digest(material),
        'graphs_sha256':digest(graphs)}

def result_path(bound):return root()/'results'/(digest(bound)+'.json')

def primary_name(material):return (material.get('most_likely_name') or {}).get('text')

def queries_for(material):
    names=[primary_name(material)]
    # Keep every source-declared spelling available to the real parser. A
    # match on one of these is supplemental evidence only; it never rewrites
    # the sealed primary name or promotes a registry synonym to a PIN.
    for preparation in material.get('identity_preparations',[]):
        if not isinstance(preparation,dict):continue
        names.extend([preparation.get('full_name'), preparation.get('prepared_query'),
                      preparation.get('raw_name'), *(preparation.get('aliases') or [])])
    return list(dict.fromkeys(n for n in names
        if isinstance(n,str) and n.strip() and len(n)<=5000))

def finite_target(material,graphs):
    if material.get('kind') not in ('monomer','component','oligomer') or len(graphs)!=1:return None
    g=next(iter(graphs.values()))
    if g.get('scope')!='finite_molecule' or not g.get('canonical_smiles') or g.get('ports') or '*' in g['canonical_smiles']:return None
    return g

def check_material(k,entry,material,graphs,parsers,extra_names=()):
    bound=binding(entry,material,graphs);g=finite_target(material,graphs)
    name=primary_name(material);queries=list(dict.fromkeys([*queries_for(material),*extra_names]))
    checks=[]
    if g:
        for query in queries:
            result=deepcopy(parsers[query])
            checked=parser_check(k,query,g,result)
            checks.append({**checked,'name':query,'graph_id':g['id'],
                'graph_sha256':digest(g),'prepared_variant':query not in queries_for(material)})
    primary=next((c for c in checks if c['name']==name),None)
    status=(primary or {}).get('status','NO_NAME') if g else 'NO_FINITE_GRAPH' if not graphs else 'NOT_APPLICABLE'
    # OPSIN can output an isolated metal atom, while the existing finite
    # molecule guard rejects radicals. Do not weaken that guard or call it a match.
    if primary and primary['parser_result'].get('parser_status')=='SUCCESS' and primary['parser_result'].get('reason_code')=='RADICAL_NOT_SUPPORTED':
        status='PARSER_GRAPH_BOUNDARY'
    matching=[c['name'] for c in checks if c['status']=='GRAPH_MATCH']
    if status in ('UNSUPPORTED','NO_NAME') and matching:status='PREPARED_GRAPH_MATCH'
    result={'contract':CONTRACT,'binding':bound,'checked_at':now(), 'status':status,
        'primary_status':(primary or {}).get('status'), 'primary_name':name,
        'matching_names':matching,'checks':checks,'provider':k.provider.probe(),
        'kernel_version':'0.9.0','preferred_iupac_name':None,'independent_review':'NOT_REVIEWED',
        'exact_material_identity':False,'scope':'encoded finite name/graph only',
        'first_run_evidence_unchanged':True}
    return {**result,'receipt_sha256':digest(result)}

def publish(result):
    if result.get('receipt_sha256')!=digest({k:v for k,v in result.items() if k!='receipt_sha256'}):raise ValueError('NAME_CHECK_RECEIPT_INVALID')
    path=result_path(result['binding'])
    with _LOCK:
        previous=read(path)
        if previous and previous!=result:raise ValueError('NAME_CHECK_IMMUTABLE_RESULT')
        if not previous:atomic(path,result)
        index=read(root()/'index.json',{})
        key=digest({'version':result['binding']['version'],'id':result['binding']['material_id']})
        index[key]={'status':result['status'],'status_label':LABELS[result['status']],
            'receipt_sha256':result['receipt_sha256'],'primary_name':result['primary_name'],
            'matching_names':result['matching_names']}
        atomic(root()/'index.json',index)
    return path

def verification_for(entry,material,graphs):
    bound=binding(entry,material,graphs)
    base={'contract':CONTRACT,'binding':bound,'status':'NOT_CHECKED','checks':[],
        'matching_names':[],'preferred_iupac_name':None,'independent_review':'NOT_REVIEWED'}
    try:
        result=read(result_path(bound))
        if not result:return {**base,'status_label':LABELS['NOT_CHECKED']}
        if result.get('contract')!=CONTRACT or result.get('binding')!=bound or result.get('receipt_sha256')!=digest({k:v for k,v in result.items() if k!='receipt_sha256'}):
            raise ValueError('NAME_CHECK_RECEIPT_BINDING_INVALID')
        return {**result,'status_label':LABELS.get(result['status'],result['status'])}
    except (OSError,ValueError,KeyError,TypeError):
        return {**base,'status':'BINDING_INVALID','status_label':LABELS['BINDING_INVALID']}

def coverage():return read(root()/'coverage.json',{'status':'NOT_STARTED'})

def summary_for(entry,index=None):
    index=read(root()/'index.json',{}) if index is None else index
    return index.get(digest({'version':entry['version'],'id':entry['id']}),
        {'status':'NOT_CHECKED','status_label':LABELS['NOT_CHECKED']})

def revision():return digest(read(root()/'index.json',{}))

def verify_bundle(bundle,job):
    """Explicit worker entry, never used by a reader or the paper solver."""
    from .tools import kernel
    from .library import component_entries
    c=bundle['candidate'];items=[]
    for entry in component_entries(bundle):
        material=c['materials'][entry['id']]
        gs={gid:c['graphs'][gid] for gid in material.get('graph_ids',[]) if gid in c['graphs']}
        if verification_for(entry,material,gs)['status']=='NOT_CHECKED':items.append((entry,material,gs))
    if not items:return []
    # Configure only this worker's provider; no global environment changes that
    # could leak into a concurrent paper or change its compiler destination.
    k=kernel();k.provider.build=Path(job)/'tool-runtime'/'opsin-build'
    names=list(dict.fromkeys(n for e,m,gs in items if finite_target(m,gs) for n in queries_for(m)))
    parsers=dict(zip(names,k.provider.parse_many(names))) if names else {}
    results=[check_material(k,e,m,gs,parsers) for e,m,gs in items]
    for result in results:
        # A transient tool failure remains retryable, rather than becoming a
        # permanent name failure in an immutable published result.
        if any(ch['parser_result'].get('status')=='NEEDS_DETAILS' for ch in result['checks']):
            atomic(Path(job)/'transient-results.json',results);raise RuntimeError('OPSIN_WORKER_TRANSIENT_FAILURE')
    for result in results:publish(result)
    atomic(Path(job)/'verification-results.json',results)
    return results

def watch_once():
    """Only versions adopted after enrollment; never replay old queues."""
    from .server import list_jobs,public_version
    rows=list_jobs();state=read(root()/'watch.json')
    versions={r['job_id']:r['version'] for r in rows}
    if not state:
        atomic(root()/'watch.json',{'versions':versions,'enrolled_at':now()});return
    known=state.get('versions',{})
    for row in rows:
        if known.get(row['job_id'])==row['version']:continue
        job=data_root()/'jobs'/('AUTO-'+row['version'])
        job.mkdir(parents=True,exist_ok=True)
        verify_bundle(public_version(row['version']),job)
        known[row['job_id']]=row['version']
        atomic(root()/'watch.json',{**state,'versions':known,'updated_at':now()})

def start():
    def watch():
        while True:
            try:watch_once()
            except Exception as exc:atomic(root()/'watch-error.json',{'at':now(),'error':str(exc)})
            time.sleep(30)
    threading.Thread(target=watch,name='library-name-checks',daemon=True).start()
