"""1.6 goal/contract-bound production lane; live model and C++ toolchain boundaries."""
import json,shutil,sys,time,threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import pytest
STUDIO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(STUDIO))
import server
from assembly import Assembly,AssemblyError
from orchestrator import FlowConflict
from proposals import ConflictError
from workorders import WorkOrderError

@pytest.fixture
def prepared(tmp_path,monkeypatch):
    workspace=tmp_path/'workspace';workspace.mkdir()
    monkeypatch.setattr(server,'WORKSPACE',workspace)
    monkeypatch.setattr(server,'ROOT',tmp_path)
    monkeypatch.setattr(server,'EVIDENCE',tmp_path/'.studio-data'/'evidence')
    st=server.Studio()
    # Project is generated from existing verified starter; use real Axiom finite checking.
    p=st.journey.start('cpp-ledger','1.6 ledger','保证两账户的资金总额在转账后守恒')['project']
    pid=p['id']
    checked=st.flow.verify_spec(pid)
    assert checked['last_verification']['passed'],checked
    draft=st.production.draft(pid)
    requirements=draft['suggested']
    assert requirements
    st.production.freeze(pid,requirements,checked['baseline'])
    yield st,pid,workspace
    st.executor.shutdown(wait=True,cancel_futures=True)

@pytest.fixture
def session(prepared):
    st,pid,w=prepared
    # template has two legitimate .cpp implementation targets, so explicit selection.
    manifest=st.flow.get(pid)['manifest']
    folder=str(Path(manifest).parent)
    target=(Path(folder)/'ledger.cpp').as_posix()
    return st,st.assembly.create(pid,target),w

def test_start_requires_human_contract(prepared):
    st,pid,w=prepared
    # create another verified but uncontracted project
    new=st.journey.start('cpp-ledger','Uncontracted','不允许凭模型检查自动批准软件')['project']
    st.flow.verify_spec(new['id'])
    with pytest.raises(FlowConflict):st.assembly.create(new['id'],'anything.cpp')

def test_auto_target_rejects_ambiguous_project(prepared):
    st,pid,w=prepared
    with pytest.raises(AssemblyError,match='多个实现目标'):st.assembly.create(pid)
    with pytest.raises(Exception):st.assembly.create(pid,'workspace/evil.cpp')

def test_resume_and_immutable_audit(session):
    st,s,w=session
    again=st.assembly.create(s['project_id'],s['target'])
    assert again['id']==s['id']
    assert s['action']['id']=='propose' and s['audit_valid']
    from assembly import Assembly
    reopened=Assembly(st)
    assert reopened.get(s['id'])['current']
    report=reopened.handoff(s['id'])
    from proposals import sha
    from workorders import canonical
    assert sha(canonical(report['report']))==report['sha256']
    assert report['report']['session']['production_release_authorized'] is False


def test_review_gate_does_not_execute(session,monkeypatch):
    st,s,w=session
    f=st.proposals.file_guard(s['target']);before=f.read_text()
    generated=st.assembly.candidate(s['id'],code=before+'\n// candidate\n')
    assert f.read_text()==before and generated['action']['id']=='review'
    with pytest.raises((ConflictError,WorkOrderError)):
        st.assembly.review(s['id'],'wrong',True)
    with pytest.raises(AssemblyError):st.assembly.verify(s['id'],True)
    good=st.assembly.review(s['id'],generated['candidate_digest'],True)
    assert good['action']['id']=='apply'
    with pytest.raises(WorkOrderError):st.assembly.apply(s['id'],'ai_approved')
    applied=st.assembly.apply(s['id'],'human_authorized_apply')
    assert applied['state']=='applied'
    with pytest.raises(WorkOrderError):st.assembly.verify(s['id'],False)


def test_real_cpp_correct_candidate(session):
    st,s,w=session
    f=st.proposals.file_guard(s['target'])
    start=st.assembly.candidate(s['id'],code=f.read_text()+'\n// reviewed version 1.6\n')
    st.assembly.review(s['id'],start['candidate_digest'],True)
    st.assembly.apply(s['id'],'human_authorized_apply')
    st.assembly.verify(s['id'],True)
    end=time.monotonic()+180
    while time.monotonic()<end:
        v=st.assembly.poll(s['id'])
        if v['state']!='validating':break
        time.sleep(.2)
    assert v['state']=='passed',v
    assert v['action']['id']=='complete'
    assert not v['production_release_authorized']


def test_failed_candidate_manual_repair(session):
    st,s,w=session
    f=st.proposals.file_guard(s['target'])
    initial=f.read_text();assert 'from -= amount;' in initial
    v=st.assembly.candidate(s['id'],code=initial.replace('from -= amount;','from += amount;'))
    st.assembly.review(s['id'],v['candidate_digest'],True)
    st.assembly.apply(s['id'],'human_authorized_apply')
    # Test decision boundary with a simulated verifier result. Real correctness is covered separately.
    def fake_run(proposal_id,trusted):
        st.proposals.check_validation(proposal_id)
        st.proposals.finish_validation(proposal_id,False,[{'step':'cpp-full','returncode':2}])
        st.jobs['test_job']={'status':'failed','returncode':2,'result':{'decision':'Blocked','checks':[{'step':'cpp-full','returncode':2}]}}
        return {'job_id':'test_job'}
    st.start_proposal_job=fake_run
    st.assembly.verify(s['id'],True)
    blocked=st.assembly.poll(s['id']);assert blocked['state']=='blocked'
    assert blocked['diagnostic'] and blocked['action']['id']=='repair'
    with pytest.raises(WorkOrderError):st.assembly.revert(s['id'],'invalid')
    restored=st.assembly.revert(s['id'],'human_reject_and_revert')
    assert restored['action']['id']=='propose' and f.read_text()==initial
    assert restored['attempts_used']==1


def test_stale_inputs_and_audit_fail_closed(session):
    st,s,w=session
    spec=st.proposals.file_guard(st.flow.get(s['project_id'])['spec'])
    spec.write_text(spec.read_text()+'\n// changed\n')
    assert st.assembly.get(s['id'])['action']['id']=='blocked'
    with pytest.raises(FlowConflict):st.assembly.candidate(s['id'],code='hello')
    path=st.assembly.home/(s['id']+'.json')
    record=json.loads(path.read_text());record['events'][0]['kind']='tampered'
    path.write_text(json.dumps(record))
    with pytest.raises(AssemblyError):st.assembly.get(s['id'])


def test_tampered_test_source_blocks(session):
    st,s,w=session
    p=st.flow.get(s['project_id'])
    name=st.proposals.file_guard(s['target']);code=name.read_text()
    st.assembly.candidate(s['id'],code=code+'\n// accepted\n')
    tests=name.with_name('test_ledger.cpp')
    tests.write_text(tests.read_text()+'\n// modified test\n')
    assert not st.assembly.get(s['id'])['current']
    with pytest.raises(FlowConflict):st.assembly.review(s['id'],st.assembly.get(s['id'])['candidate_digest'],True)


def test_http_authorized_bridge(session):
    st,s,w=session
    class Bridge(ThreadingHTTPServer):pass
    http=Bridge(('127.0.0.1',0),server.Handler);http.studio=st
    thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{http.server_port}'
    try:
        with pytest.raises(HTTPError) as e:urlopen(base+'/api/assembly/get?id='+s['id'],timeout=5)
        assert e.value.code==403
        req=Request(base+'/api/assembly/get?id='+s['id'],headers={'X-Axiom-Token':st.token})
        with urlopen(req,timeout=8) as stream:result=json.load(stream)
        assert result['action']['id']=='propose'
        req=Request(base+'/api/assembly/candidate',data=json.dumps({'id':s['id'],'code':st.proposals.file_guard(s['target']).read_text()}).encode(),headers={'X-Axiom-Token':st.token,'Content-Type':'application/json'})
        with urlopen(req,timeout=25) as stream:candidate=json.load(stream)
        assert candidate['state']=='proposed'
        req=Request(base+'/api/assembly/verify',data=json.dumps({'id':s['id'],'trusted':True}).encode(),headers={'X-Axiom-Token':st.token,'Content-Type':'application/json'})
        with pytest.raises(HTTPError) as e:urlopen(req,timeout=8)
        assert e.value.code==400
    finally:http.shutdown();http.server_close();thread.join(timeout=2)


def test_no_model_consent(session,monkeypatch):
    st,s,w=session
    monkeypatch.setattr(st.proposals,'generate',lambda *a,**kw: (_ for _ in ()).throw(AssertionError('MODEL CALLED')))
    with pytest.raises(WorkOrderError):st.assembly.candidate(s['id'],consent=False)
    assert st.assembly.get(s['id'])['state']=='ready'

def test_selectable_targets_are_manifest_limited(prepared):
    st,pid,w=prepared
    targets=st.assembly.targets(pid)['targets']
    assert len(targets)==2
    assert any(x.endswith('/ledger.cpp') for x in targets)
    assert any(x.endswith('/format.cpp') for x in targets)
    assert all('test_' not in x for x in targets)
    assert all(st.assembly._allowed_target(st.flow.get(pid)['manifest'],x) for x in targets)
