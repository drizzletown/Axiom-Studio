#!/usr/bin/env python3
"""Axiom Studio local AI work-order CLI. Does not grant release permission."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'studio'))
from server import Studio

def main():
    p=argparse.ArgumentParser(description='Axiom Studio V0.9 AI work orders')
    sub=p.add_subparsers(dest='cmd',required=True)
    c=sub.add_parser('create');c.add_argument('--manifest',required=True);c.add_argument('--target',required=True);c.add_argument('--goal',required=True)
    sub.add_parser('list')
    for k in ('get','generate','submit-file','review','apply','verify','poll','revert','feedback'):
        s=sub.add_parser(k);s.add_argument('id')
        if k=='submit-file':s.add_argument('--file',required=True)
        if k=='review':s.add_argument('--digest',required=True)
        if k in ('generate','verify'):s.add_argument('--confirm',action='store_true',help='explicit external transfer / native execution consent')
    a=p.parse_args();studio=Studio();w=studio.workorders
    try:
        if a.cmd=='create':out=w.create(a.manifest,a.target,a.goal)
        elif a.cmd=='list':out=w.list()
        elif a.cmd=='get':out=w.get(a.id)
        elif a.cmd=='generate':out=w.generate(a.id,a.confirm)
        elif a.cmd=='submit-file':out=w.submit(a.id,Path(a.file).read_text('utf-8'))
        elif a.cmd=='review':out=w.review(a.id,a.digest,True)
        elif a.cmd=='apply':out=w.apply(a.id,'human_authorized_apply')
        elif a.cmd=='verify':out=w.verify(a.id,a.confirm)
        elif a.cmd=='poll':out=w.poll(a.id)
        elif a.cmd=='revert':out=w.revert(a.id,'human_reject_and_revert')
        elif a.cmd=='feedback':out=w.feedback(a.id)
        print(json.dumps(out,ensure_ascii=False,indent=2))
    finally:studio.executor.shutdown(wait=False,cancel_futures=False)
if __name__=='__main__':main()
