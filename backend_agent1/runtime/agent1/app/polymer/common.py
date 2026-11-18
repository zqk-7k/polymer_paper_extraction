from __future__ import annotations
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent

def stable_json(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def key(scope,obj):return scope+':'+hashlib.sha256(stable_json(obj).encode()).hexdigest()
def sha_file(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def fail(code,status='UNSUPPORTED',**kw):return {'status':status,'reason_code':code,**kw}
