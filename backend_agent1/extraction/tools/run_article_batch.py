"""Bounded article concurrency: one isolated run and at most one call per article."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path

from llm_client import DEFAULT_CONFIG_PATH
from tools.run_source_workflow import run, write, workflow_rule_hashes


def execute(source_root, output_root, documents=None, exclude=(), workers=5,
            model='deepseek-v4.1-flash',config_path=DEFAULT_CONFIG_PATH,asset_roots=(),workflow=run):
    if not 1<=workers<=5: raise ValueError('workers must be between 1 and 5')
    source_root,output_root=Path(source_root).resolve(),Path(output_root).resolve()
    paths={p.parent.name:p for p in source_root.glob('reference_no_*/stage0_blocks.json')}
    selected=sorted((set(documents) if documents else set(paths))-set(exclude))
    if not selected or set(selected)-set(paths): raise ValueError('Missing or empty article selection')
    output_root.mkdir(parents=True,exist_ok=True)
    manifest={'documents':selected,'workers':workers,'model':model,'input_root':str(source_root),
              'input_hashes':{d:hashlib.sha256(paths[d].read_bytes()).hexdigest() for d in selected},
              'config_hash':hashlib.sha256(Path(config_path).read_bytes()).hexdigest(),
              'rules':workflow_rule_hashes(), 'context_mode':'article_once',
              'asset_roots':[str(Path(p).resolve()) for p in asset_roots]}
    manifest_path=output_root/'manifest.json'
    if manifest_path.exists() and json.loads(manifest_path.read_text(encoding='utf8'))!=manifest:
        raise ValueError('Batch contract changed; select a new output directory')
    write(manifest_path,manifest)
    results={}
    def one(doc):
        out=output_root/'runs'/doc
        summary=workflow(source_root,out,model=model,documents=[doc],input_kind='stage0',
                         context_mode='article_once',max_requests=1,resume=(out/'contract.json').is_file(),
                         config_path=config_path,asset_roots=asset_roots)
        return {'document_id':doc,'status':summary['status'],'pending_packets':summary['pending_packets'],
                'api_requests_this_run':summary['api_requests_this_run'],'summary_path':str(out/'summary.json'),
                'export_dir':summary['export_dir'],'model_rows':summary['export_counts'].get('model_extractions',0)}
    def save():
        result={'planned_documents':len(selected),'finished_documents':len(results),'workers':workers,
                'successful_documents':sum(r.get('pending_packets')==0 for r in results.values()),
                'api_requests_this_run':sum(r.get('api_requests_this_run',0) for r in results.values()),
                'documents':[results[d] for d in sorted(results)]}
        write(output_root/'summary.json',result)
        return result
    save()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures={pool.submit(one,doc):doc for doc in selected}
        for future in as_completed(futures):
            doc=futures[future]
            try: results[doc]=future.result()
            except Exception as exc: results[doc]={'document_id':doc,'status':'failed','error_type':type(exc).__name__}
            save()
            print(json.dumps({'finished':len(results),'planned':len(selected),**results[doc]}),flush=True)
    if any(hashlib.sha256(paths[d].read_bytes()).hexdigest()!=h for d,h in manifest['input_hashes'].items()):
        raise ValueError('Batch input changed')
    return save()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--output-root',type=Path,required=True)
    parser.add_argument('--documents',nargs='+')
    parser.add_argument('--exclude',nargs='*',default=[])
    parser.add_argument('--workers',type=int,default=5)
    parser.add_argument('--model',default='deepseek-v4.1-flash')
    parser.add_argument('--config-path',type=Path,default=DEFAULT_CONFIG_PATH)
    parser.add_argument('--asset-roots',type=Path,nargs='*',default=[])
    execute(**vars(parser.parse_args()))
