"""One agent1-only entry. Resume uses the same frozen manifest and checkpoints."""
from pathlib import Path
import argparse,json,sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'extraction'))
from agent1_workflow.api import prepare,execute,status
def main():
    parser=argparse.ArgumentParser(description='agent1 单路正式入口：prepare / run / resume / status')
    sub=parser.add_subparsers(dest='command',required=True)
    prep=sub.add_parser('prepare');prep.add_argument('--documents',nargs='+',type=Path,required=True);prep.add_argument('--bundle-root',type=Path,required=True);prep.add_argument('--config',type=Path,required=True);prep.add_argument('--output',type=Path,required=True)
    for cmd in ('run','resume','status'):
        p=sub.add_parser(cmd);p.add_argument('--output',type=Path,required=True)
        if cmd!='status':p.add_argument('--workers',type=int,default=3,choices=range(1,5))
    args=parser.parse_args()
    if args.command=='prepare':
        prepare(args.documents,args.bundle_root,args.output,args.config,compare_native=False);print('Prepared agent1-only run');return 0
    if args.command=='status':print(json.dumps(status(args.output),ensure_ascii=False,indent=2));return 0
    result=execute(args.output,workers=args.workers);print(json.dumps(status(args.output),ensure_ascii=False,indent=2))
    return 0 if result['completed'] else 1
if __name__=='__main__':raise SystemExit(main())
