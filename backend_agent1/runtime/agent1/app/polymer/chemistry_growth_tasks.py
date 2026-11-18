"""Read-only worker observations; a persisted waiting label is not proof of liveness."""
import json,re
from pathlib import Path
TERMINAL={'DRAFTS_READY','FAILED','CANCELLED','EXPIRED'}


def observe(root,tasks):
    rows=[]
    for task in tasks:
        item=dict(task);identity=item.get('id','')
        if not re.fullmatch(r'CG-[0-9TZ]+-[a-f0-9]{8}',str(identity)):
            rows.append(item);continue
        folder=Path(root)/'runs/chemistry-growth'/identity
        try:
            state=json.loads((folder/'run.json').read_text(encoding='utf8'))
            worker=json.loads((folder/'worker.json').read_text(encoding='utf8'))
            item.update(status=state['status'],persisted_status=state['status'])
            import psutil
            try:
                proc=psutil.Process(worker['pid'])
                stamp=worker.get('create_time',worker.get('worker_create_time'))
                alive=proc.is_running() and (stamp is None or abs(proc.create_time()-stamp)<.05)
                command=proc.cmdline()
                alive=alive and identity in command and any(str(a).endswith('chemistry_growth.py') for a in command)
            except (psutil.NoSuchProcess,psutil.AccessDenied,KeyError,TypeError):alive=False
            item['worker_alive']=bool(alive)
            item['execution_state']=state['status'] if alive or state['status'] in TERMINAL else 'INTERRUPTED'
        except (OSError,ValueError,TypeError,KeyError):
            item['execution_state']='STATE_UNAVAILABLE'
        rows.append(item)
    return rows
