#!/usr/bin/env python3
"""Demonstrate real model verification -> contract -> AI packet -> fail-closed Gate.

No C++ candidate is generated or executed. Outputs observable facts, not fabricated releases.
"""
from pathlib import Path
import argparse
import json
import sys
import tempfile

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'studio'))
from orchestrator import Orchestrator,FlowConflict
from production import Production

class NoCandidates:
    def get(self,_):raise KeyError('no candidate is proposed')

def run():
    with tempfile.TemporaryDirectory(prefix='axiom-production-demo-') as td:
        root=Path(td);w=root/'workspace';w.mkdir()
        (w/'ledger.ax').write_bytes((BASE/'workspace'/'cpp_project'/'ledger.ax').read_bytes())
        src=json.loads((BASE/'workspace'/'cpp_project'/'project.json').read_text())
        src['spec']='ledger.ax'
        (w/'project.json').write_text(json.dumps(src,ensure_ascii=False),encoding='utf-8')
        def guard(r):
            p=(w/r).resolve()
            if not p.is_relative_to(w) or not p.is_file():raise ValueError('not a workspace file')
            return p
        f=Orchestrator(db=root/'flow.db',workspace=w,engine=BASE/'engine',
             evidence_root=root/'model-evidence',guard=guard,proposals=NoCandidates())
        prod=Production(f)
        p=f.create('Axiom Production Example','保持账户余额守恒并生成可追溯的受约束构造任务','ledger.ax','project.json')
        specs=prod.draft(p['id'])
        reqs=[{**item,'text':'账户业务要求 '+item['property']+' 性质持续成立并由独立模型检查'} for item in specs['suggested']]
        contract=prod.freeze(p['id'],reqs,p['baseline'])
        checked=f.verify_spec(p['id'])
        assess=prod.overview(p['id'])
        task=prod.task_packet(p['id'])
        graph=prod.graph(p['id'])
        blocked=False
        try:prod.issue_passport(p['id'],'issue_test_only',contract['digest'])
        except FlowConflict:blocked=True
        report={'schema':'ax-production-demo/0.4','contract_digest':contract['digest'],
            'model_gate':checked['last_verification']['steps'][-1]['outcome'],
            'model_checked':checked['last_verification']['passed'],
            'requirements':len(reqs),'trace_edges':len(graph['edges']),
            'task_digest':task['digest'],'blocked_without_cpp_evidence':blocked,
            'blockers':assess['blockers'],'audit_valid':f.audit(p['id'])['chain_valid'],
            'production_release':False}
        assert report['model_gate']=='Approved' and blocked and report['audit_valid']
        return report

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output');a=ap.parse_args()
    result=run();formatted=json.dumps(result,ensure_ascii=False,indent=2)
    if a.output:Path(a.output).write_text(formatted+'\n',encoding='utf-8')
    print(formatted)
