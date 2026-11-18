"""OS-owned leases survive stale metadata and release on process death."""
from pathlib import Path
import json,os,hashlib,uuid

class BusyError(RuntimeError):pass

class Lease:
    def __init__(self,path):self.path=Path(path);self.handle=None;self.token=uuid.uuid4().hex
    def acquire(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        f=open(str(self.path)+'.lease','a+b');f.seek(0,2)
        if f.tell()==0:f.write(b'0');f.flush()
        f.seek(0)
        try:
            if os.name=='nt':
                import msvcrt;msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl;fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:f.close();raise BusyError('An active process owns '+str(self.path))
        self.handle=f
        try:
            if self.path.exists():
                archive=self.path.parent/'recovery_history';archive.mkdir(exist_ok=True)
                (archive/(self.path.name+'.'+self.token+'.json')).write_bytes(self.path.read_bytes())
            self.path.write_text(json.dumps({'pid':os.getpid(),'token':self.token}),'utf8')
        except BaseException:self.release();raise
        return self
    def release(self):
        if self.handle is None:return
        try:
            try:
                if json.loads(self.path.read_text('utf8')).get('token')==self.token:self.path.unlink()
            except (FileNotFoundError,ValueError):pass
        finally:
            self.handle.close();self.handle=None

def active(path):
    """Probe the kernel lease, never trust a PID/metadata file alone."""
    p=Path(str(path)+'.lease')
    if not p.exists():return False
    f=open(p,'r+b');f.seek(0)
    try:
        if os.name=='nt':
            import msvcrt;msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl;fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return False
    except OSError:return True
    finally:f.close()

DELIVERABLES=('final.json','all_records.json','stage6_validation.json','report.html','candidate_ledger.json')
def has_failures(dest):
    p=Path(dest)/'task_failures.json'
    return p.exists() and bool(json.loads(p.read_text('utf8')))
def seal_delivery(dest):
    dest=Path(dest)
    if json.loads((dest/'run_result.json').read_text('utf8')).get('status')!='completed':raise ValueError('Incomplete extraction cannot be published complete')
    if has_failures(dest):raise ValueError('Unfinished tasks prohibit complete delivery')
    data={n:hashlib.sha256((dest/n).read_bytes()).hexdigest() for n in DELIVERABLES}
    temp=dest/'delivery_status.writing';temp.write_text(json.dumps({'status':'completed','files':data}),'utf8');temp.replace(dest/'delivery_status.json')

def state(dest):
    dest=Path(dest)
    if active(dest/'branch.lock'):return 'running'
    if has_failures(dest):return 'incomplete'
    marker=dest/'delivery_status.json'
    if marker.exists():
        try:
            saved=json.loads(marker.read_text('utf8'))
            valid=set(saved['files'])==set(DELIVERABLES) and all(hashlib.sha256((dest/n).read_bytes()).hexdigest()==h for n,h in saved['files'].items())
            if valid and json.loads((dest/'run_result.json').read_text('utf8')).get('status')=='completed':return 'completed'
        except (OSError,ValueError,KeyError):pass
        return 'delivery_incomplete'
    if (dest/'branch.lock').exists():return 'interrupted'
    if (dest/'run_result.json').exists():
        result=json.loads((dest/'run_result.json').read_text('utf8'))
        return 'delivery_incomplete' if result.get('status')=='completed' else 'incomplete'
    if (dest/'branch_failure.json').exists():return 'failed'
    return 'interrupted' if (dest/'calls.jsonl').exists() else 'pending'
