"""V0.9 work-order contract, anti-tamper and independent-verifier gating tests."""
import hashlib,json,os,shutil,sys,threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import pytest
STUDIO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(STUDIO))
import server
from workorders import WorkOrderError
from proposals import ProposalError,ConflictError

@pytest.fixture
def s(tmp_path,monkeypatch):
    w=tmp_path/'workspace'/'p';w.mkdir(parents=True)
    for f in (STUDIO/'templates'/'cpp-ledger').iterdir():
        if f.is_file():shutil.copy2(f,w/f.name)
    monkeypatch.setattr(server,'WORKSPACE',tmp_path/'workspace')
    monkeypatch.setattr(server,'ROOT',tmp_path)
    monkeypatch.setattr(server,'EVIDENCE',tmp_path/'.studio-data'/'evidence')
    studio=server.Studio()
    yield studio,w
    studio.executor.shutdown(wait=True,cancel_futures=True)

def create(s):return s.workorders.create('p/project.json','p/ledger.cpp','保证账户资金守恒',max_attempts=2)

def stub_job(studio,passed):
    """Mimic a completed independent verifier but still use the real candidate evidence lifecycle."""
    def launch(pid,trusted):
        p=studio.proposals.check_validation(pid)
        checks=[{'step':'spec-model','returncode':0}, {'step':'spec-gate','returncode':0},
                {'step':'cpp-full','returncode':0 if passed else 2},
                {'step':'cpp-gate','returncode':0 if passed else 2}]
        studio.proposals.finish_validation(pid,passed,checks)
        studio.jobs['job-test-000']={'status':'finished' if passed else 'failed','returncode':0 if passed else 2,
                                    'result':{'decision':'Approved' if passed else 'Blocked','checks':checks}}
        return {'job_id':'job-test-000'}
    studio.start_proposal_job=launch

def stage(s,code):
    r=create(s)
    r=s.workorders.submit(r['id'],code)
    return r

def apply(s,r):
    p=s.proposals.get(r['active_proposal'])
    r=s.workorders.review(r['id'],p['code_sha256'],True)
    return s.workorders.apply(r['id'],'human_authorized_apply')

def test_manual_stage_review_apply_no_auto_run(s):
    st,w=s;before=(w/'ledger.cpp').read_text()
    r=stage(st,before+'\n// candidate\n')
    assert (w/'ledger.cpp').read_text()==before
    assert r['state']=='proposed' and r['current']
    with pytest.raises(ProposalError):st.workorders.apply(r['id'],'human_authorized_apply')
    with pytest.raises(ConflictError):st.workorders.review(r['id'],'invalid',True)
    r=apply(st,r)
    assert r['state']=='applied' and r['current'] and len(r['attempts'])==1
    assert (w/'ledger.cpp').read_text().endswith('// candidate\n')
    with pytest.raises(WorkOrderError):st.workorders.verify(r['id'],False)


def test_blocked_revert_feedback_and_second_attempt(s):
    st,w=s;original=(w/'ledger.cpp').read_text()
    r=apply(st,stage(st,original.replace('from -= amount;','from += amount;')))
    stub_job(st,False)
    r=st.workorders.verify(r['id'],True)
    assert r['state']=='validating'
    r=st.workorders.poll(r['id']);assert r['state']=='blocked'
    packet=st.workorders.feedback(r['id']);assert packet['attempts_remaining']==1
    with pytest.raises(WorkOrderError):st.workorders.revert(r['id'],'not-authorized')
    r=st.workorders.revert(r['id'],'human_reject_and_revert')
    assert r['current'] and (w/'ledger.cpp').read_text()==original
    r=st.workorders.submit(r['id'],original+'\n// fixed\n')
    assert r['state']=='proposed' and len(r['attempts'])==2
    with pytest.raises(WorkOrderError):st.workorders.submit(r['id'],original)
    r=apply(st,r)
    stub_job(st,True)
    st.workorders.verify(r['id'],True)
    r=st.workorders.poll(r['id'])
    assert r['state']=='passed' and r['current']
    assert st.workorders.get(r['id'])['events'][-1]['kind']=='independent_passed'


def test_changed_tests_block_action(s):
    st,w=s;r=stage(st,(w/'ledger.cpp').read_text())
    (w/'test_ledger.cpp').write_text((w/'test_ledger.cpp').read_text()+'\n// changed\n')
    with pytest.raises(ConflictError):st.workorders.review(r['id'],r['attempts'][-1]['code_sha256'],True)
    assert not st.workorders.get(r['id'])['current']


def test_invalid_target_limits_and_generation_no_consent(s):
    st,w=s
    with pytest.raises(ProposalError):st.workorders.create('p/project.json','p/test_ledger.cpp','hello')
    with pytest.raises(WorkOrderError):st.workorders.create('p/project.json','p/ledger.cpp','hi')
    with pytest.raises(WorkOrderError):st.workorders.create('p/project.json','p/ledger.cpp','goal',max_attempts=9)
    r=create(st)
    with pytest.raises(WorkOrderError):st.workorders.generate(r['id'],False)
    assert st.workorders.get(r['id'])['state']=='ready'


def test_record_tamper_and_restart_interrupted(s):
    st,w=s;r=stage(st,(w/'ledger.cpp').read_text())
    f=st.workorders.home/(r['id']+'.json')
    record=json.loads(f.read_text());record['events'][0]['kind']='fake';f.write_text(json.dumps(record))
    with pytest.raises(WorkOrderError):st.workorders.get(r['id'])
    # On a separate legitimate work order, an in-flight verifier is never assumed to pass.
    other=apply(st,stage(st,(w/'ledger.cpp').read_text()))
    stub_job(st,False);st.workorders.verify(other['id'],True)
    from workorders import WorkOrders
    restored=WorkOrders(st)
    assert restored.get(other['id'])['state']=='interrupted'


def test_remote_model_stub_requires_consent_and_cannot_edit_files(s,monkeypatch):
    st,w=s;initial=(w/'ledger.cpp').read_bytes()
    class Fake(BaseHTTPRequestHandler):
        sent=[]
        def log_message(self,*args):pass
        def do_POST(self):
            data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            self.sent.append(data)
            raw=json.dumps({'choices':[{'message':{'content':initial.decode()+'\n// AI proposal\n'}}]}).encode()
            self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    srv=ThreadingHTTPServer(('127.0.0.1',0),Fake);thread=threading.Thread(target=srv.serve_forever,daemon=True);thread.start()
    monkeypatch.setenv('AXIOM_STUDIO_LLM_ENDPOINT',f'http://127.0.0.1:{srv.server_port}/v1/chat/completions')
    monkeypatch.setenv('AXIOM_STUDIO_LLM_MODEL','stub-local')
    monkeypatch.delenv('AXIOM_STUDIO_LLM_API_KEY',raising=False)
    try:
        r=create(st)
        r=st.workorders.generate(r['id'],True)
        assert r['state']=='proposed' and r['attempts'][0]['source']=='model'
        assert Fake.sent and 'Axiom spec:' in Fake.sent[-1]['messages'][0]['content']
        assert '保证账户资金守恒' in Fake.sent[-1]['messages'][0]['content']
        assert (w/'ledger.cpp').read_bytes()==initial
    finally:srv.shutdown();srv.server_close()


def test_http_auth_and_workorder_lifecycle(s):
    st,w=s
    handler=server.Handler
    srv=ThreadingHTTPServer(('127.0.0.1',0),handler);srv.studio=st
    thread=threading.Thread(target=srv.serve_forever,daemon=True);thread.start()
    url=f'http://127.0.0.1:{srv.server_port}'
    def req(path,data=None,auth=True):
        headers={'X-Axiom-Token':st.token} if auth else {}
        if data is not None:headers['Content-Type']='application/json'
        try:
            with urlopen(Request(url+path,data=json.dumps(data).encode() if data is not None else None,headers=headers),timeout=30) as r:
                return r.status,json.loads(r.read())
        except HTTPError as e:return e.code,json.loads(e.read())
    try:
        assert req('/api/workorders',auth=False)[0]==403
        a,r=req('/api/workorder/create',{'manifest':'p/project.json','target':'p/ledger.cpp','goal':'实现账户守恒'})
        assert a==201,r
        assert req('/api/workorders')[1]['workorders'][0]['id']==r['id']
        assert req('/api/workorder/generate',{'id':r['id'],'consent':False})[0]==400
        assert req('/api/workorder?id='+r['id'])[0]==200
        assert req('/api/workorder/verify',{'id':r['id'],'trusted':True})[0]==400
    finally:srv.shutdown();srv.server_close()


def test_revert_detects_external_modify(s):
    st,w=s;original=(w/'ledger.cpp').read_text();r=apply(st,stage(st,original+'\n// new\n'))
    stub_job(st,False);st.workorders.verify(r['id'],True);st.workorders.poll(r['id'])
    (w/'ledger.cpp').write_text(original+'\n// independent edit\n')
    with pytest.raises(ConflictError):st.workorders.revert(r['id'],'human_reject_and_revert')
