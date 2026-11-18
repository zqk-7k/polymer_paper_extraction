"""Reusable skill entry, with explicit input scope and the existing fixed runner."""
from pathlib import Path
import argparse,json,sys

def main():
    p=argparse.ArgumentParser();p.add_argument('--app',type=Path,default=Path.cwd())
    sub=p.add_subparsers(dest='action',required=True)
    sub.add_parser('preflight');sub.add_parser('collect')
    r=sub.add_parser('run');r.add_argument('--pdf',type=Path);r.add_argument('--text');r.add_argument('--minutes',type=float,default=60)
    a=p.parse_args();app=a.app.resolve()
    if not (app/'identity_app/runner.py').is_file() or not (app/'config/runtime.json').is_file():
        p.error('Pass --app with the Polymer Identity App directory')
    sys.path.insert(0,str(app))
    from identity_app.storage import read,data_root
    from identity_app.runner import preflight,require_preflight,init_job,run_job
    if a.action=='collect':
        from identity_app.capability_feedback import collect
        result=collect();print(json.dumps(result,ensure_ascii=False));return 0
    for path in (data_root()/'jobs').glob('SC-*/run.json'):
        if read(path).get('status')=='UNDERSTANDING_AND_BUILDING' and not (path.parent/'sealed.json').exists():
            p.error('An existing paper must finish/seal before another run')
    if a.action=='preflight':result=preflight()
    else:
        if bool(a.pdf)==bool(a.text):p.error('Choose exactly one --pdf or --text input')
        require_preflight();job=init_job(pdf=a.pdf,text=a.text,minutes=a.minutes);print(str(job),flush=True);result=run_job(job)
    print(json.dumps(result,ensure_ascii=False));return 0 if result.get('status') in ('PASS','DELIVERED') else 2

if __name__=='__main__':raise SystemExit(main())
