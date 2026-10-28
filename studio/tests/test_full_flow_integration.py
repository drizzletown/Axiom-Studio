"""Optional slower end-to-end test with real C++ compilation and a workflow decision.

Runs only explicitly in the release checklist; not part of the fast suite.
"""
import hashlib,shutil,sys,time
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'studio'))
from server import Studio, WORKSPACE

def test_real_full_construction_workflow():
    stamp=hashlib.sha256(str(time.time_ns()).encode()).hexdigest()[:8]
    dest=WORKSPACE/('v03_flow_acceptance_'+stamp)
    shutil.copytree(WORKSPACE/'cpp_project',dest)
    rel=dest.name
    studio=Studio();flow=studio.flow
    try:
        p=flow.create('真实 C++ 全链路验收 '+stamp,'对真实 C++ 候选执行审查、构建验证与原型准入',
                       rel+'/ledger.ax',rel+'/project.json')
        assert flow.verify_spec(p['id'])['status']=='spec_ready'
        code=(dest/'ledger.cpp').read_text('utf-8')+'\n// Axiom Studio V0.3 workflow acceptance candidate\n'
        proposal=studio.proposals.create(rel+'/project.json',rel+'/ledger.cpp',code)
        assert flow.attach_candidate(p['id'],proposal['id'])['status']=='candidate_review'
        studio.proposals.review(proposal['id'],proposal['code_sha256'],True)
        assert flow.sync(p['id'])['status']=='candidate_apply'
        studio.proposals.apply(proposal['id'])
        assert flow.sync(p['id'])['status']=='candidate_validate'
        job=studio.start_proposal_job(proposal['id'],trusted=True)
        end=time.monotonic()+160
        while time.monotonic()<end:
            record=studio.job(job['job_id'])
            if record['status'] not in ('queued','running'):break
            time.sleep(.3)
        assert record['status']=='finished',record['output'][-1400:]
        assert record['result']['decision']=='Approved',record['output'][-1400:]
        assert flow.sync(p['id'])['status']=='decision_pending'
        decision=flow.decide(p['id'],'approve_test_only',proposal['code_sha256'])
        assert decision['status']=='accepted_test_only'
        assert decision['decision']['production_release'] is False
        assert flow.audit(p['id'])['chain_valid']
    finally:
        shutil.rmtree(dest,ignore_errors=True)
