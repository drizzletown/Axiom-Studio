#!/usr/bin/env python3
"""Axiom Studio 1.7 multi-module production CLI; no automatic native execution."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'studio'))
from server import Studio

def main(argv=None):
    parser=argparse.ArgumentParser(description='Axiom 1.7 多模块软件生产任务图')
    sub=parser.add_subparsers(dest='command',required=True)
    x=sub.add_parser('create');x.add_argument('project_id');x.add_argument('--tasks-json',help='可选任务 DAG JSON 文件')
    x=sub.add_parser('list');x.add_argument('--project-id')
    for name in ('status','sync','handoff'):
        x=sub.add_parser(name);x.add_argument('id')
    x=sub.add_parser('start');x.add_argument('id');x.add_argument('target')
    opts=parser.parse_args(argv)
    studio=Studio()
    try:
        graphs=studio.task_graphs
        if opts.command=='create':
            tasks=json.loads(Path(opts.tasks_json).read_text(encoding='utf8')) if opts.tasks_json else None
            result=graphs.create(opts.project_id,tasks)
        elif opts.command=='list':result=graphs.list(opts.project_id)
        elif opts.command=='status':result=graphs.get(opts.id)
        elif opts.command=='sync':result=graphs.sync(opts.id)
        elif opts.command=='handoff':result=graphs.handoff(opts.id)
        elif opts.command=='start':result=graphs.start(opts.id,opts.target)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    except (ValueError,OSError,Exception) as exc:
        print(json.dumps({'error':type(exc).__name__+': '+str(exc)},ensure_ascii=False),file=sys.stderr)
        return 2
    finally:studio.executor.shutdown(wait=False,cancel_futures=True)
if __name__=='__main__':raise SystemExit(main())
