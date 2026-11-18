"""Single-document process: install compatible receiver, then run full chain."""
import argparse
import traceback
from common import *

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--paper',required=True,choices=PAPERS)
    p.add_argument('--arm',required=True,choices=('B',))
    args=p.parse_args()
    from receipt_gateway import install as gateway
    from rebuild_received import install as receiver
    gateway();receiver()
    from run_trial import extract
    from run_lifecycle import Lease
    lease=Lease(folder(args.paper,args.arm)/'branch.lock').acquire()
    try:
        extract(args.paper,args.arm,worker_lease=lease)
        from publication import publish
        publish(folder(args.paper,args.arm))
        from run_lifecycle import seal_delivery
        seal_delivery(folder(args.paper,args.arm))
    except Exception as exc:
        write(folder(args.paper,args.arm)/'branch_failure.json',{
            'error_type':type(exc).__name__,'traceback':traceback.format_exc(),
            'raw_response_preserved':True})
        return 1
    finally:lease.release()
    return 0

if __name__=='__main__':raise SystemExit(main())
