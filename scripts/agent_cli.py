#!/usr/bin/env python3
"""Local 1.9 multi-role builder/reviewer CLI; consent is explicit."""
import argparse, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'studio'))
from server import Studio

def main(argv=None):
    p=argparse.ArgumentParser(description='Axiom Studio 1.9 多角色 AI 构造（只生成候选）')
    sub=p.add_subparsers(dest='action',required=True)
    x=sub.add_parser('status');x.add_argument('graph_id')
    x=sub.add_parser('get');x.add_argument('record_id')
    x=sub.add_parser('impact');x.add_argument('graph_id');x.add_argument('targets',nargs='+')
    x=sub.add_parser('run');x.add_argument('graph_id');x.add_argument('target');x.add_argument('--consent',action='store_true');x.add_argument('--rounds',type=int,choices=[1,2],default=1)
    x=sub.add_parser('batch');x.add_argument('graph_id');x.add_argument('targets',nargs='+');x.add_argument('--consent',action='store_true');x.add_argument('--rounds',type=int,choices=[1,2],default=1);x.add_argument('--concurrency',type=int,default=2)
    x=sub.add_parser('stage');x.add_argument('record_id');x.add_argument('digest');x.add_argument('--acknowledge',action='store_true')
    args=p.parse_args(argv);st=Studio()
    try:
        a=st.agent_forge
        if args.action=='status':res=a.list(args.graph_id)
        elif args.action=='get':res=a.get(args.record_id)
        elif args.action=='impact':res=a.impact(args.graph_id,args.targets)
        elif args.action=='run':res=a.run(args.graph_id,args.target,args.consent,args.rounds)
        elif args.action=='batch':res=a.run_many(args.graph_id,args.targets,args.consent,args.rounds,args.concurrency)
        else:res=a.stage(args.record_id,args.digest,args.acknowledge)
        print(json.dumps(res,ensure_ascii=False,indent=2));return 0
    except Exception as exc:
        print(json.dumps({'error':str(exc)},ensure_ascii=False),file=sys.stderr);return 2
    finally:st.executor.shutdown(wait=False,cancel_futures=True)

if __name__=='__main__':raise SystemExit(main())
