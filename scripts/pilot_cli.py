#!/usr/bin/env python3
"""Axiom Studio 1.5: intent-first production pilot CLI.

All candidate review, C++ execution, human decisions and releases remain outside
this command; --advance only starts finite-model validation with explicit consent.
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'studio'))
from server import Studio

def main(argv=None):
    parser=argparse.ArgumentParser(description='Axiom Studio production navigator (test-only)')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('list',help='List production missions')
    new=sub.add_parser('new',help='Create a new software project and its production mission')
    new.add_argument('--template',default='model-toggle',choices=['model-toggle','model-ledger','cpp-ledger'])
    new.add_argument('--slug',required=True);new.add_argument('--name',required=True);new.add_argument('--goal',required=True)
    start=sub.add_parser('start',help='Start/resume a goal-centric plan for an existing project')
    start.add_argument('project_id')
    info=sub.add_parser('show',help='Recompute current production state')
    info.add_argument('mission_id')
    go=sub.add_parser('verify',help='Explicitly start SAFE bounded model validation only')
    go.add_argument('mission_id');go.add_argument('--wait',action='store_true')
    history=sub.add_parser('audit',help='Check local unsigned audit hash chain')
    history.add_argument('mission_id')
    handoff=sub.add_parser('handoff',help='Write an unsigned production-process JSON handoff')
    handoff.add_argument('mission_id');handoff.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    studio=Studio()
    try:
        pilot=studio.pilot
        if args.command=='list':data=pilot.list()
        elif args.command=='new':
            created=studio.launchpad.create(args.template,args.slug,args.name,args.goal)
            data={'project':created['project'],'mission':pilot.create(created['project']['id'])}
        elif args.command=='start':data=pilot.create(args.project_id)
        elif args.command=='show':data=pilot.get(args.mission_id)
        elif args.command=='audit':data=pilot.audit(args.mission_id)
        elif args.command=='handoff':
            data=pilot.handoff(args.mission_id)
            target=args.output.resolve()
            with target.open('x',encoding='utf8') as output:
                json.dump(data,output,ensure_ascii=False,indent=2)
            data={'file':str(target),'sha256':data['sha256'],'assurance':'unsigned handoff; not release evidence'}
        elif args.command=='verify':
            view=pilot.get(args.mission_id)
            data=pilot.advance_safe(args.mission_id,view['revision'],view['baseline_digest'])
            if args.wait:
                for _ in range(900):
                    if data['operation_state']!='running':break
                    time.sleep(.1);data=pilot.get(args.mission_id)
        print(json.dumps(data,ensure_ascii=False,indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({'error':type(exc).__name__+': '+str(exc),'completed':False},ensure_ascii=False))
        return 2
    finally:studio.executor.shutdown(wait=False,cancel_futures=True)

if __name__=='__main__':raise SystemExit(main())
