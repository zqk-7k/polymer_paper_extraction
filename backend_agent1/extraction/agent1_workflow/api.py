"""Explicit production intake; immutable run contract and bounded concurrency."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys

PACKAGE=Path(__file__).resolve().parent
REQUIRED=('agent1_entities.json','agent1_directory_samples.json','agent1_handoff.json')
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,v):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_name(p.name+'.writing')
    tmp.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(p)

def add_arguments(parser):
    parser.add_argument('--directory-source',choices=('native','agent1'),default='native',
                        help='默认原 Stage1/2；agent1 显式使用已验证的分组抽取链路')
    parser.add_argument('--agent1-bundle-root',type=Path,help='每篇 reference_no_* 子目录内的目录三件套')
    parser.add_argument('--agent1-compare-native',action='store_true',
                        help='已停用：agent1 正式入口仅运行单路，不再执行 A/B')

def forwarded_arguments(args):
    out=['--directory-source',getattr(args,'directory_source','native')]
    if getattr(args,'agent1_bundle_root',None):out+=['--agent1-bundle-root',str(args.agent1_bundle_root.resolve())]
    if getattr(args,'agent1_compare_native',False):out+=['--agent1-compare-native']
    return out

def validate_bundle(raw,bundle):
    missing=[n for n in REQUIRED if not (bundle/n).is_file()]
    if missing:raise ValueError('Agent1 bundle incomplete; no native fallback: '+str(missing))
    e,s,h=(read(bundle/n) for n in REQUIRED)
    doc=raw['document_id']
    if e.get('document_id')!=doc or s.get('document_id')!=doc:raise ValueError('Document identity mismatch')
    ids=[x['sample_id'] for x in s['samples']];eids={x['entity_id'] for x in e['polymer_entities']}
    if len(ids)!=len(set(ids)) or len(eids)!=len(e['polymer_entities']):raise ValueError('Duplicate directory IDs')
    if set(ids)!={x['sample_id'] for x in h['identities']}:raise ValueError('Directory handoff membership mismatch')
    if any(x.get('refers_to_entity') not in eids for x in s['samples']):raise ValueError('Dangling entity reference')
    # Evidence IDs must refer to this article, not merely a matching document name.
    blocks={b['block_id']:b for b in raw['elements']}
    for item in e['polymer_entities']+s['samples']:
        ev=item.get('evidence') or {};bid=ev.get('block_id')
        if bid not in blocks:raise ValueError('Directory evidence block missing: '+str(bid))
        loc=ev.get('table_locator') or {}
        if loc.get('cell_id') and loc['cell_id'] not in {c['cell_id'] for c in blocks[bid].get('table_cells',[])}:
            raise ValueError('Directory evidence cell missing')
    # A source stage0 alongside a prepared bundle provides an exact version lock.
    if (bundle/'stage0_blocks.json').is_file():
        supplied=read(bundle/'stage0_blocks.json')
        # Compare original OCR blocks; supplemental evidence blocks remain separate.
        def clean(value):
            if isinstance(value,dict):return {k:clean(v) for k,v in value.items() if v is not None}
            if isinstance(value,list):return [clean(v) for v in value]
            return value
        original=lambda d:[clean(b) for b in d['elements'] if 'source_block_index' in b]
        if original(supplied)!=original(raw):raise ValueError('Prepared bundle belongs to a different source version')
    return e,s,h

def prepare(documents,bundle_root,output_root,config_path,*,compare_native=False):
    if compare_native:raise ValueError('This candidate supports agent1 only; A/B is disabled')
    from stages.stage0_load_document import load_source_document,load_document_elements,recover_missing_equations
    output_root=Path(output_root).resolve();config_path=Path(config_path).resolve()
    if not config_path.is_file():raise FileNotFoundError(config_path)
    if not documents:raise ValueError('No selected documents')
    prepared=[];sources={str(config_path):sha(config_path)}
    for document in documents:
        document=Path(document).resolve();candidate=read(document)
        raw=candidate if 'source_document_schema_version' in candidate else load_document_elements(recover_missing_equations(load_source_document(document))).model_dump(mode='json',exclude_none=True)
        doc=raw['document_id'];paper=doc.removeprefix('reference_no_')
        if not paper.isdigit() or not paper:raise ValueError('Invalid reference number')
        bundle=Path(bundle_root).resolve()/doc
        validate_bundle(raw,bundle)
        sources[str(document)]=sha(document)
        for name in REQUIRED:sources[str(bundle/name)]=sha(bundle/name)
        prepared.append((paper,raw,bundle))
    if len({p for p,_,_ in prepared})!=len(prepared):raise ValueError('Duplicate document selection')
    contract={'schema':'agent1.production.v1','papers':[p for p,_,_ in prepared],
        'sources':sources,'code':{str(p.relative_to(PACKAGE)):sha(p) for p in sorted(PACKAGE.rglob('*')) if p.is_file() and p.suffix in ('.py','.json')},
        'arms':['A','B'] if compare_native else ['B'],'quality_review':False,'format_conversion':False,'figure_extraction':False}
    shared=[PACKAGE.parent/'llm_client.py',PACKAGE.parent/'prompt_loader.py',PACKAGE.parent/'config/polymer_schema.yaml']
    shared += [p for directory in ('stages','schema','prompts') for p in (PACKAGE.parent/directory).rglob('*')
               if p.is_file() and p.suffix in ('.py','.json','.yaml','.md')]
    contract['shared_runtime']={str(p):sha(p) for p in sorted(set(shared))}
    path=output_root/'production_contract.json'
    if path.exists():
        if read(path)!=contract:raise ValueError('Existing output has a different contract; use a new output directory')
        return contract
    if output_root.exists() and any(output_root.iterdir()):raise ValueError('New production run requires an empty output directory')
    output_root.mkdir(parents=True,exist_ok=True)
    for name in ('target_catalog.json','condition_roles.json','pricing_reference.json'):
        shutil.copy2(PACKAGE/'assets'/name,output_root/name)
    settings=read(PACKAGE/'assets/workflow_config.json')
    settings.update(scheme='agent1.production.v1',papers=contract['papers'],pipeline_config=str(config_path))
    write(output_root/'workflow_config.json',settings)
    for paper,raw,bundle in prepared:
        dest=output_root/'inputs'/('reference_no_'+paper)
        write(dest/'stage0_blocks.json',raw);write(dest/'table_evidence.json',{})
        for name in REQUIRED:shutil.copy2(bundle/name,dest/name)
    write(path,contract)
    files=[p for p in output_root.rglob('*') if p.is_file()]+[Path(p) for p in sources]+[PACKAGE/p for p in contract['code']]+shared
    write(output_root/'frozen_manifest.json',{'files':[{'path':str(p),'sha256':sha(p)} for p in files]})
    return contract

def execute(output_root,*,workers=4):
    root=Path(output_root).resolve();contract=read(root/'production_contract.json')
    if contract['arms']!=['B']:raise ValueError('Agent1-only contract required')
    for item in read(root/'frozen_manifest.json')['files']:
        if not Path(item['path']).is_file() or sha(item['path'])!=item['sha256']:raise ValueError('Frozen input/code changed: '+item['path'])
    if not 1<=workers<=4:raise ValueError('Concurrency must be between 1 and 4')
    env=dict(os.environ,POLYMER_AGENT1_RUN_ROOT=str(root),PYTHONDONTWRITEBYTECODE='1')
    def branch(paper,arm):
        dest=root/'runs'/arm/('reference_no_'+paper);dest.mkdir(parents=True,exist_ok=True)
        with (dest/'runner.log').open('a',encoding='utf-8') as log:
            result=subprocess.run([sys.executable,'-B','-X','utf8',str(PACKAGE/'worker.py'),'--paper',paper,'--arm',arm],env=env,stdout=log,stderr=subprocess.STDOUT)
        return {'paper':paper,'arm':arm,'exit_code':result.returncode,'status':state(dest),'output':str(dest)}
    from .run_lifecycle import Lease,state
    rows=[];lease=Lease(root/'dispatcher.lock').acquire()
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures=[pool.submit(branch,p,a) for p in contract['papers'] for a in contract['arms']]
            for future in as_completed(futures):
                row=future.result();rows.append(row)
                write(root/'production_status.json',{'workers':workers,'branches':rows,'completed':False})
                print(row,flush=True)
        summary={'workers':workers,'branches':rows,'completed':all(r['exit_code']==0 and r['status']=='completed' for r in rows)}
        write(root/'production_status.json',summary)
        return summary
    finally:lease.release()

def status(output_root):
    from .run_lifecycle import state,active
    root=Path(output_root).resolve();contract=read(root/'production_contract.json')
    rows=[{'paper':p,'arm':'B','status':state(root/'runs/B'/('reference_no_'+p))} for p in contract['papers']]
    return {'dispatcher_active':active(root/'dispatcher.lock'),'branches':rows,'completed':all(x['status']=='completed' for x in rows)}

def run_from_batch(args,documents,output_dir,config_path):
    if args.agent1_compare_native:raise ValueError('Agent1-only entry; A/B is disabled')
    if not args.agent1_bundle_root:raise ValueError('--directory-source agent1 requires --agent1-bundle-root')
    if args.source_workflow or args.source_workflow_only or args.validate_existing or args.retry_api_failures or args.force:
        raise ValueError('Agent1 mode cannot combine legacy post-workflow, legacy validation/retry or force overwrite')
    if args.state_db or args.summary_out or args.recheck_completed or args.stage4t_retry_failed_tables:
        raise ValueError('Agent1 mode uses production_status.json and task checkpoints; legacy state/summary/recheck options are unsupported')
    if args.dry_run:
        print(json.dumps({'directory_source':'agent1','documents':[str(p) for p in documents],
                          'bundle_root':str(args.agent1_bundle_root),'output':str(output_dir),'model_calls':0},ensure_ascii=False))
        return 0
    prepare(documents,args.agent1_bundle_root,output_dir,config_path,compare_native=args.agent1_compare_native)
    result=execute(output_dir,workers=min(args.workers or 4,args.llm_workers or 4,4))
    return 0 if result['completed'] else 1
