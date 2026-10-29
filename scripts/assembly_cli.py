#!/usr/bin/env python3
"""Axiom Studio 1.6 headless construction lane.

Human authorization is always a separate explicit command, never implicit in
`start`, `submit`, `generate`, `status`, or `handoff`.
"""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'studio'))
from server import Studio

def main(argv=None):
    p=argparse.ArgumentParser(description='Axiom 1.6: 目标驱动 AI 构造生产线')
    sub=p.add_subparsers(dest='command',required=True)
    x=sub.add_parser('list');x.add_argument('--project')
    x=sub.add_parser('start');x.add_argument('project_id');x.add_argument('--target',default=None)
    for name in ('status','poll','handoff'):
        x=sub.add_parser(name);x.add_argument('id')
    x=sub.add_parser('submit');x.add_argument('id');x.add_argument('--file',required=True)
    x=sub.add_parser('generate');x.add_argument('id');x.add_argument('--allow-send-to-model',action='store_true',required=True)
    x=sub.add_parser('review');x.add_argument('id');x.add_argument('--sha256',required=True);x.add_argument('--approve',action='store_true',required=True)
    x=sub.add_parser('apply');x.add_argument('id');x.add_argument('--human-authorized-apply',action='store_true',required=True)
    x=sub.add_parser('verify');x.add_argument('id');x.add_argument('--trusted-local-cpp',action='store_true',required=True)
    x=sub.add_parser('revert');x.add_argument('id');x.add_argument('--human-reject-and-revert',action='store_true',required=True)
    a=p.parse_args(argv)
    s=Studio()
    try:
        assembly=s.assembly
        if a.command=='list':r=assembly.list(a.project)
        elif a.command=='start':r=assembly.create(a.project_id,a.target)
        elif a.command=='status':r=assembly.get(a.id)
        elif a.command=='poll':r=assembly.poll(a.id)
        elif a.command=='handoff':r=assembly.handoff(a.id)
        elif a.command=='submit':r=assembly.candidate(a.id,code=Path(a.file).read_text(encoding='utf-8'))
        elif a.command=='generate':r=assembly.candidate(a.id,consent=a.allow_send_to_model)
        elif a.command=='review':r=assembly.review(a.id,a.sha256,a.approve)
        elif a.command=='apply':r=assembly.apply(a.id,'human_authorized_apply' if a.human_authorized_apply else '')
        elif a.command=='verify':r=assembly.verify(a.id,a.trusted_local_cpp)
        elif a.command=='revert':r=assembly.revert(a.id,'human_reject_and_revert' if a.human_reject_and_revert else '')
        print(json.dumps(r,ensure_ascii=False,indent=2))
        return 0
    except Exception as e:
        print(json.dumps({'error':type(e).__name__+': '+str(e)},ensure_ascii=False),file=sys.stderr)
        return 2
    finally:
        s.executor.shutdown(wait=False,cancel_futures=True)
if __name__=='__main__':sys.exit(main())
