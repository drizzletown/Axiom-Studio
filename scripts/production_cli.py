#!/usr/bin/env python3
"""Scriptable Axiom Studio project operations. No native build without an explicit separate workflow."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'studio'))
from server import Studio

def pretty(obj):
    print(json.dumps(obj,ensure_ascii=False,indent=2))

def main(argv=None):
    parser=argparse.ArgumentParser(description='Axiom Studio production workflow CLI (local, test-only)')
    subs=parser.add_subparsers(dest='command',required=True)
    subs.add_parser('templates',help='List starter projects')
    subs.add_parser('cockpit',help='Unified production cockpit snapshot, no native code execution')
    subs.add_parser('doctor',help='Diagnose local tools and fail-closed trust boundaries')
    subs.add_parser('queue',help='List actionable work for every project')
    init=subs.add_parser('init',help='Create isolated project, never overwrite existing sources')
    init.add_argument('--template',required=True,choices=['model-toggle','model-ledger','cpp-ledger'])
    init.add_argument('--slug',required=True)
    init.add_argument('--name',required=True)
    init.add_argument('--goal',required=True)
    init.add_argument('--verify-model',action='store_true',help='Run finite-model verification now; never executes C++')
    imp=subs.add_parser('import',help='Copy explicit local Axiom/C++ project without touching source')
    imp.add_argument('--source',required=True,type=Path)
    imp.add_argument('--slug',required=True);imp.add_argument('--name',required=True);imp.add_argument('--goal',required=True)
    imp.add_argument('--spec',required=True);imp.add_argument('--manifest')
    verify=subs.add_parser('verify-model',help='Run check + plan + bounded verify + model Gate')
    verify.add_argument('project_id')
    draft=subs.add_parser('draft',help='Get property mapping draft for human review')
    draft.add_argument('project_id')
    freeze=subs.add_parser('freeze',help='Freeze HUMAN-REVIEWED requirements JSON file')
    freeze.add_argument('project_id');freeze.add_argument('--file',type=Path,required=True)
    batch=subs.add_parser('batch-model',help='Plan and run safe bounded model verification for draft projects')
    batch.add_argument('--project-id',action='append',dest='project_ids',help='One or more project ids; default all draft projects')
    batch.add_argument('--retry-failed',action='store_true',help='Explicitly permit previously blocked model checks')
    subs.add_parser('runs',help='List persisted model-only batch runs')
    run=subs.add_parser('run-report',help='Read a persisted batch report (not a signed attestation)')
    run.add_argument('run_id')
    batch_export=subs.add_parser('export-run',help='Export a completed batch and verified-project handoffs')
    batch_export.add_argument('run_id');batch_export.add_argument('--output',type=Path,required=True)
    again=subs.add_parser('retry-run',help='Explicit retry only failed/interrupted items in a NEW auditable run')
    again.add_argument('run_id')
    export=subs.add_parser('export',help='Unsigned handoff ZIP, not a release')
    export.add_argument('project_id');export.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    studio=Studio()
    try:
        if args.command=='templates':result=studio.launchpad.templates()
        elif args.command=='cockpit':result=studio.cockpit.snapshot()
        elif args.command=='doctor':result=studio.cockpit.doctor()
        elif args.command=='queue':result=studio.launchpad.queue()
        elif args.command=='init':
            result=studio.launchpad.create(args.template,args.slug,args.name,args.goal)
            if args.verify_model:
                result['verification']=studio.flow.verify_spec(result['project']['id'])
        elif args.command=='import':
            result=studio.launchpad.import_existing(args.source,args.slug,args.name,args.goal,args.spec,args.manifest)
        elif args.command=='verify-model':result=studio.flow.verify_spec(args.project_id)
        elif args.command=='draft':result=studio.production.draft(args.project_id)
        elif args.command=='freeze':
            # No automatic approval of natural-language requirements.
            source=args.file.read_text(encoding='utf-8')
            data=json.loads(source)
            if not isinstance(data,list):parser.error('requirements file must be JSON array')
            project=studio.flow.get(args.project_id)
            result=studio.production.freeze(args.project_id,data,project['baseline'])
        elif args.command=='batch-model':
            planned=studio.production_runner.create(args.project_ids,args.retry_failed)
            result=studio.production_runner.execute(planned['id'])
        elif args.command=='runs':result=studio.production_runner.list()
        elif args.command=='run-report':result=studio.production_runner.report(args.run_id)
        elif args.command=='export-run':
            raw,filename=studio.production_runner.export(args.run_id)
            dest=args.output.resolve()
            with open(dest,'xb') as f:f.write(raw)
            result={'created':str(dest),'size':len(raw),'contains':'unsigned report and passed-model handoffs'}
        elif args.command=='retry-run':
            planned=studio.production_runner.retry(args.run_id)
            result=studio.production_runner.execute(planned['id'])
        elif args.command=='export':
            raw,filename=studio.launchpad.export(args.project_id)
            target=args.output.resolve()
            if target.exists():parser.error('refusing to overwrite existing output file')
            with open(target,'xb') as f:f.write(raw)
            result={'created':str(target),'bytes':len(raw),'assurance':'unsigned; independent revalidation required'}
        else:parser.error('unsupported command')
        pretty(result)
        return 0
    except Exception as exc:
        pretty({'error':type(exc).__name__+': '+str(exc),'completed':False})
        return 2
    finally:
        studio.executor.shutdown(wait=False,cancel_futures=True)

if __name__=='__main__':raise SystemExit(main())
