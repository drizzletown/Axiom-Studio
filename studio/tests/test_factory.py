"""V0.5 production campaign acceptance: real Axiom workflow, real proposals, fail closed."""
import json
import sys
from pathlib import Path
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
from factory import Factory
from orchestrator import FlowConflict,FlowError
from proposals import ConflictError, ProposalError

BASE=Path(__file__).resolve().parents[2]

@pytest.fixture
def studio(tmp_path,monkeypatch):
    w=tmp_path/'workspace'/'p';w.mkdir(parents=True)
    source=BASE/'workspace'/'cpp_project'
    for name in ('ledger.ax','project.json','ledger.hpp','ledger.cpp','format.hpp','format.cpp','test_ledger.cpp','test_format.cpp','test_integration.cpp'):
        (w/name).write_bytes((source/name).read_bytes())
    monkeypatch.setattr(server,'WORKSPACE',tmp_path/'workspace')
    monkeypatch.setattr(server,'ROOT',tmp_path)
    monkeypatch.setattr(server,'EVIDENCE',tmp_path/'.studio-data'/'evidence')
    s=server.Studio()
    yield s
    s.executor.shutdown(wait=True,cancel_futures=True)


def prepare(studio):
    f=studio.flow;p=f.create('Production Campaign','以守恒性和边界性质驱动有证据的软件构造',
                              'p/ledger.ax','p/project.json')
    draft=studio.production.draft(p['id'])
    reqs=[{**x,'text':'验证 '+x['property']+' 所代表的业务要求并保留独立证据'} for x in draft['suggested']]
    studio.production.freeze(p['id'],reqs,p['baseline'])
    return p


def test_campaign_construction_review_and_no_autonomy(studio):
    p=prepare(studio)
    factory=studio.factory
    c=factory.create(p['id'],'p/ledger.cpp');cid=c['id']
    assert c['state']=='spec_pending' and len(c['task_dag'])==6
    assert factory.create(p['id'],'p/ledger.cpp')['id']==cid
    with pytest.raises((FlowError,FlowConflict)):factory.candidate(cid,code='// missing model gate')
    assert factory.verify_spec(cid)['state']=='candidate_pending'
    assert factory.events(cid)['valid']
    assert factory.create(p['id'],'p/ledger.cpp')['id']==cid
    with pytest.raises((FlowError,FlowConflict)):factory.candidate(cid)
    with pytest.raises(ProposalError):factory.create(p['id'],'p/test_ledger.cpp')
    target=(server.WORKSPACE/'p'/'ledger.cpp')
    original=target.read_text()
    candidate=factory.candidate(cid,code=original+'\n// candidate source, no changes to protected checks\n')
    assert candidate['state']=='human_review' and target.read_text()==original
    proposal=studio.proposals.get(candidate['candidate_id'])
    with pytest.raises((FlowError,FlowConflict,ConflictError)):factory.review(cid,proposal['code_sha256'],'ai_approved')
    with pytest.raises((FlowError,FlowConflict,ConflictError)):factory.review(cid,'0'*64,'human_review_approved')
    assert factory.review(cid,proposal['code_sha256'],'human_review_approved')['state']=='human_apply'
    assert target.read_text()==original
    with pytest.raises(FlowError):factory.apply(cid,'agent_apply')
    assert factory.apply(cid,'human_apply_approved')['state']=='validation_pending'
    assert target.read_text()!=original
    with pytest.raises(FlowError):factory.validate(cid,False)
    assert factory.events(cid)['valid']
    with pytest.raises(FlowConflict):factory.repair_packet(cid)
    assert studio.production.overview(p['id'])['blockers']
    with pytest.raises(FlowError):factory.decide(cid,proposal['code_sha256'],'release')


def test_fail_closed_spec_mutation_and_audit(studio):
    p=prepare(studio);f=studio.factory
    c=f.create(p['id'],'p/ledger.cpp')
    (server.WORKSPACE/'p/ledger.ax').write_text((server.WORKSPACE/'p/ledger.ax').read_text()+'\n')
    assert f.get(c['id'])['effective_state']=='stale'
    with pytest.raises(FlowConflict):f.verify_spec(c['id'])
    with studio.flow._connect() as cx:
        cx.execute("UPDATE factory_events SET payload=? WHERE campaign_id=?",('{}',c['id']))
    assert f.events(c['id'])['valid'] is False


def test_reject_modified_protected_tests(studio):
    p=prepare(studio);f=studio.factory
    c=f.create(p['id'],'p/ledger.cpp')
    assert f.verify_spec(c['id'])['state']=='candidate_pending'
    original=(server.WORKSPACE/'p/ledger.cpp').read_text()
    c=f.candidate(c['id'],code=original+'\n// candidate\n')
    (server.WORKSPACE/'p/test_ledger.cpp').write_text('// malicious change\n')
    proposal=studio.proposals.get(c['candidate_id'])
    with pytest.raises(ConflictError):f.review(c['id'],proposal['code_sha256'],'human_review_approved')
    assert f.get(c['id'])['state']=='human_review'


def test_lost_job_remains_blocked(studio):
    p=prepare(studio);f=studio.factory
    c=f.create(p['id'],'p/ledger.cpp')
    assert f.verify_spec(c['id'])['state']=='candidate_pending'
    original=(server.WORKSPACE/'p/ledger.cpp').read_text()
    c=f.candidate(c['id'],code=original+'\n// candidate\n')
    sha=studio.proposals.get(c['candidate_id'])['code_sha256']
    f.review(c['id'],sha,'human_review_approved')
    f.apply(c['id'],'human_apply_approved')
    with studio.flow._connect() as cx:
        f._set(cx,c['id'],state='validating',job_id='job-vanished')
    state=f.poll(c['id'])
    assert state['state']=='blocked' and state['diagnostic']['reason']=='INDEPENDENT_VERIFICATION_FAILED'
    pkt=f.repair_packet(c['id'])
    assert pkt['packet']['max_autonomous_retries']==0
    assert 'evolution branch' in pkt['packet']['required_next_action']
    with pytest.raises(FlowConflict):f.decide(c['id'],sha,'approve_test_only')
