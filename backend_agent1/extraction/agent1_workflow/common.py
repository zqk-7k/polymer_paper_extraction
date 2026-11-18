"""Explicit per-run storage; no historical report-directory dependencies."""
from pathlib import Path
import hashlib,json,os,sys
sys.dont_write_bytecode=True
CODE=Path(__file__).resolve().parents[1]
OUT=Path(os.environ['POLYMER_AGENT1_RUN_ROOT']).resolve()
sys.path.insert(0,str(CODE))
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def digest(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def config():return read(OUT/'workflow_config.json')
PAPERS=tuple(config()['papers'])
def write(p,v):
    p=Path(p).resolve()
    if not p.is_relative_to(OUT) or p==OUT:raise ValueError('Output must remain inside run root')
    p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_name(p.name+'.writing')
    tmp.write_text(json.dumps(v,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8');tmp.replace(p)
def folder(p,a):
    if p not in PAPERS or a not in ('A','B'):raise ValueError('Unknown document or directory source')
    return OUT/'runs'/a/('reference_no_'+p)
def check_manifest(name):
    files=read(OUT/name)['files']
    bad=[x['path'] for x in files if not Path(x['path']).is_file() or sha(x['path'])!=x['sha256']]
    if bad:raise ValueError('Run inputs or code changed; use a new run directory: '+str(bad))
    return len(files)
def check_frozen():return check_manifest('frozen_manifest.json')
def check_protected():return check_frozen()
