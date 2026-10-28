#!/usr/bin/env python3
"""Real end-to-end model-only batch, isolated temp workspace, no AI/C++ execution."""
import json
from pathlib import Path
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'studio'),str(ROOT/'engine'/'src')]
import server as srv

def main():
    with tempfile.TemporaryDirectory(prefix='axiom-v08-demo-') as tmp:
        base=Path(tmp)
        srv.ROOT=base;srv.WORKSPACE=base/'workspace';srv.WORKSPACE.mkdir()
        srv.EVIDENCE=base/'.studio-data'/'evidence'
        app=srv.Studio()
        try:
            p1=app.launchpad.create('model-toggle','example-one','Example one','验证系统基本行为')['project']
            p2=app.launchpad.create('model-ledger','example-two','Example two','验证守恒性质')['project']
            # An intentionally broken but syntactically valid model should block the batch.
            broken=srv.WORKSPACE/'broken.ax'
            broken.write_bytes((ROOT/'engine'/'examples'/'broken_conservation.ax').read_bytes())
            bad=app.flow.create('Broken model','故意检出不变量错误并阻断交付','broken.ax')
            planned=app.production_runner.create([p1['id'],p2['id'],bad['id']])
            end=app.production_runner.execute(planned['id'])
            report=app.production_runner.report(planned['id'])
            out={'run_id':end['id'],'status':end['status'],'summary':end['result'],
                 'items':[{'project_id':r['project_id'],'status':r['status'],
                          'steps':r['result'].get('steps',[])} for r in report['items']],
                 'assurance':'model-bounded/test-level only',
                 'require_human_review':True,'cpp_executed':False}
            print(json.dumps(out,ensure_ascii=False,indent=2))
            if [r['status'] for r in report['items']]!=['passed','passed','blocked']:
                return 2
            return 0
        finally:
            app.executor.shutdown(wait=False,cancel_futures=True)
if __name__=='__main__':raise SystemExit(main())
