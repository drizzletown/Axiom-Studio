#!/usr/bin/env python3
"""Manage read-only parallel candidate preparation, review handoff and bounded diagnostics."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'studio'))
from server import Studio

def main(argv=None):
    parser=argparse.ArgumentParser(description='Axiom 1.8 并行构造准备（不会执行 AI 代码）')
    subs=parser.add_subparsers(dest='command',required=True)
    a=subs.add_parser('prepare');a.add_argument('graph_id');a.add_argument('--workers',type=int,default=3)
    for cmd in ('status','handoff'):
        a=subs.add_parser(cmd);a.add_argument('graph_id')
    a=subs.add_parser('stage');a.add_argument('graph_id');a.add_argument('target');a.add_argument('code_file');a.add_argument('packet_digest')
    a=subs.add_parser('promote');a.add_argument('graph_id');a.add_argument('target');a.add_argument('candidate_sha256');a.add_argument('--reviewed-dependency-changes',action='store_true')
    a=subs.add_parser('feedback');a.add_argument('graph_id');a.add_argument('target')
    args=parser.parse_args(argv);st=Studio()
    try:
        fleet=st.fleet
        if args.command=='prepare':result=fleet.prepare(args.graph_id,args.workers)
        elif args.command=='status':result=fleet.get(args.graph_id)
        elif args.command=='handoff':result=fleet.handoff(args.graph_id)
        elif args.command=='stage':result=fleet.stage(args.graph_id,args.target,Path(args.code_file).read_text('utf-8'),args.packet_digest)
        elif args.command=='promote':result=fleet.promote(args.graph_id,args.target,args.candidate_sha256,args.reviewed_dependency_changes)
        else:result=fleet.feedback(args.graph_id,args.target)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except Exception as exc:
        print(json.dumps({'error':type(exc).__name__+': '+str(exc)},ensure_ascii=False),file=sys.stderr);return 2
    finally:st.executor.shutdown(wait=False,cancel_futures=True)

if __name__=='__main__':raise SystemExit(main())
