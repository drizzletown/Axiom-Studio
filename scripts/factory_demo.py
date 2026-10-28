#!/usr/bin/env python3
"""End-to-end V0.5 production campaign against the real Axiom C++ engine.
Run with --timeout to cap observed validation; never manufactures a verdict.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'studio'))
import server


def run(timeout:float):
    with tempfile.TemporaryDirectory(prefix='axiom-v05-demo-') as td:
        root=Path(td)
        server.ROOT=root
        server.WORKSPACE=root/'workspace'
        server.WORKSPACE.mkdir()
        server.EVIDENCE=root/'.studio-data'/'evidence'
        source=BASE/'workspace'/'cpp_project'
        dest=server.WORKSPACE/'p';dest.mkdir()
        for fname in ('ledger.ax','project.json','ledger.cpp','ledger.hpp','format.cpp','format.hpp',
                      'test_ledger.cpp','test_format.cpp','test_integration.cpp'):
            shutil.copy2(source/fname,dest/fname)
        s=server.Studio()
        try:
            p=s.flow.create('Axiom V0.5 Factory Demo',
                 '依据账本行为规格组织 AI 候选、人工审查、真实 C++ 验证与原型裁决',
                 'p/ledger.ax','p/project.json')
            draft=s.production.draft(p['id'])
            items=[{**r,'text':'业务要求 '+r['property']+' 可由有限模型中的对应性质表示'}
                   for r in draft['suggested']]
            contract=s.production.freeze(p['id'],items,p['baseline'])
            factory=s.factory
            campaign=factory.create(p['id'],'p/ledger.cpp')
            campaign=factory.verify_spec(campaign['id'])
            assert campaign['state']=='candidate_pending','model Gate was blocked'
            code=(dest/'ledger.cpp').read_text('utf-8')
            campaign=factory.candidate(campaign['id'],code=code+'\n// v0.5 audited candidate\n')
            sha=s.proposals.get(campaign['candidate_id'])['code_sha256']
            factory.review(campaign['id'],sha,'human_review_approved')
            factory.apply(campaign['id'],'human_apply_approved')
            factory.validate(campaign['id'],True)
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                campaign=factory.poll(campaign['id'])
                if campaign['state']!='validating':break
                time.sleep(0.4)
            else:campaign=factory.get(campaign['id'])
            if campaign['state']=='human_decision':
                campaign=factory.decide(campaign['id'],sha,'approve_test_only')
            audit=factory.events(campaign['id'])
            return {'schema':'ax-factory-demo/0.5','campaign_id':campaign['id'],
                    'state':campaign['state'],'effective_state':campaign['effective_state'],
                    'audit_valid':audit['valid'],'events':len(audit['events']),
                    'proposal_id':campaign['candidate_id'],
                    'code_applied':(dest/'ledger.cpp').read_text('utf-8').endswith('// v0.5 audited candidate\n'),
                    'model_gate':'Approved',
                    'cpp_independent_verification':
                    'passed' if campaign['state']=='completed_test_only' else 'not completed / blocked',
                    'production_release':False,
                    'contract_digest':contract['digest'],
                    'diagnostic':campaign['diagnostic']}
        finally:s.executor.shutdown(wait=False,cancel_futures=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--timeout',type=float,default=70)
    ap.add_argument('--output',type=Path)
    a=ap.parse_args()
    result=run(a.timeout)
    blob=json.dumps(result,ensure_ascii=False,indent=2)
    if a.output:a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(blob+'\n',encoding='utf-8')
    print(blob)
