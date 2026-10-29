"""1.9 contract-bound multi-role candidate creation / impact scope acceptance."""
import json, os, threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import pytest
from test_assembly import prepared
import server
from agent_forge import AgentForge,AgentForgeError
from orchestrator import FlowConflict
from proposals import sha


def prepare(st,pid):
    targets=st.assembly.targets(pid)['targets']
    tasks=[{'target':targets[0],'depends_on':[]}, {'target':targets[1],'depends_on':[targets[0]]}]
    g=st.task_graphs.create(pid,tasks)
    f=st.fleet.prepare(g['id'],2)
    return g, f, targets

@pytest.fixture
def fake_provider(monkeypatch):
    calls=[]
    class Provider(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def do_POST(self):
            size=int(self.headers.get('Content-Length',0))
            data=json.loads(self.rfile.read(size));calls.append(data)
            role=data['messages'][0]['content']
            if 'builder' in role:
                value='// AI proposed implementation (untrusted)\nint example(){return 1;}\n'
            else:value='ADVISORY ONLY: check overflow and integration behavior.'
            raw=json.dumps({'choices':[{'message':{'content':value}}]}).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    srv=ThreadingHTTPServer(('127.0.0.1',0),Provider)
    thread=threading.Thread(target=srv.serve_forever,daemon=True);thread.start()
    monkeypatch.setenv('AXIOM_STUDIO_LLM_ENDPOINT','http://127.0.0.1:'+str(srv.server_port)+'/v1/chat/completions')
    monkeypatch.setenv('AXIOM_STUDIO_LLM_MODEL','local-test-agent')
    yield calls
    srv.shutdown();srv.server_close()


def test_multi_role_real_local_protocol_and_no_source_mutation(prepared,fake_provider):
    st,pid,_=prepared;g,f,targets=prepare(st,pid)
    t=targets[0];src=st.proposals.file_guard(t).read_bytes()
    with pytest.raises(AgentForgeError,match='明确同意'):st.agent_forge.run(g['id'],t)
    record=st.agent_forge.run(g['id'],t,True)
    assert len(fake_provider)==2
    assert record['current'] and record['audit_valid'] and record['requires_human_review']
    assert record['native_execution_authorized'] is False
    assert record['production_release_authorized'] is False
    assert 'ADVISORY' in record['review']
    assert record['candidate_sha256']==sha(record['code'].encode())
    assert st.proposals.file_guard(t).read_bytes()==src
    assert st.jobs=={}
    assert AgentForge(st).get(record['id'])['code']==record['code']


def test_two_rounds_bounded_and_stage_requires_human(prepared,fake_provider):
    st,pid,_=prepared;g,f,targets=prepare(st,pid);t=targets[0]
    orig=st.proposals.file_guard(t).read_bytes()
    a=st.agent_forge.run(g['id'],t,True,2)
    assert len(fake_provider)==4
    with pytest.raises(AgentForgeError):st.agent_forge.run(g['id'],t,True,3)
    with pytest.raises(AgentForgeError):st.agent_forge.stage(a['id'],a['candidate_sha256'])
    with pytest.raises(AgentForgeError):st.agent_forge.stage(a['id'],'0'*64,True)
    result=st.agent_forge.stage(a['id'],a['candidate_sha256'],True)
    assert result['candidate']['staged']
    packet=next(p for p in result['fleet']['packets'] if p['target']==t)
    assert packet['candidate_sha256']==a['candidate_sha256']
    assert st.proposals.file_guard(t).read_bytes()==orig
    assert not st.task_graphs.get(g['id'])['active_count']
    with pytest.raises(AgentForgeError):st.agent_forge.stage(a['id'],a['candidate_sha256'],True)


def test_impact_closure_and_no_evidence_reuse(prepared):
    st,pid,_=prepared;g,f,targets=prepare(st,pid)
    a=st.agent_forge.impact(g['id'],[targets[0]])
    assert set(a['affected'])==set(targets)
    assert not a['automatic_evidence_reuse']
    assert a['global_checks']
    b=st.agent_forge.impact(g['id'],[targets[1]])
    assert b['affected']==[targets[1]] and b['unaffected']==[targets[0]]
    with pytest.raises(AgentForgeError):st.agent_forge.impact(g['id'],['../spec.ax'])


def test_spec_drift_fail_closed(prepared,fake_provider):
    st,pid,_=prepared;g,f,targets=prepare(st,pid)
    a=st.agent_forge.run(g['id'],targets[0],True)
    spec=st.proposals.file_guard(st.flow.get(pid)['spec'])
    spec.write_text(spec.read_text()+'\n// drift\n')
    assert st.agent_forge.get(a['id'])['current'] is False
    assert not st.agent_forge.impact(g['id'],[targets[0]])['current']
    with pytest.raises(FlowConflict):st.agent_forge.stage(a['id'],a['candidate_sha256'],True)
    with pytest.raises(FlowConflict):st.agent_forge.run(g['id'],targets[0],True)


def test_audit_and_object_tamper(prepared,fake_provider):
    st,pid,_=prepared;g,f,targets=prepare(st,pid)
    a=st.agent_forge.run(g['id'],targets[0],True)
    record=st.agent_forge._path(a['id'])
    raw=json.loads(record.read_text());raw['review']='falsified'
    record.write_text(json.dumps(raw))
    with pytest.raises(AgentForgeError,match='成果|审计'):st.agent_forge.get(a['id'])


def test_object_tamper(prepared,fake_provider):
    st,pid,_=prepared;g,f,targets=prepare(st,pid)
    a=st.agent_forge.run(g['id'],targets[0],True)
    (st.agent_forge.home/'objects'/a['candidate_sha256']).write_text('tampered')
    with pytest.raises(AgentForgeError,match='对象'):st.agent_forge.get(a['id'])


def test_http_authorization_and_impact(prepared,fake_provider):
    st,pid,_=prepared;g,f,targets=prepare(st,pid)
    srv=ThreadingHTTPServer(('127.0.0.1',0),server.Handler);srv.studio=st
    threading.Thread(target=srv.serve_forever,daemon=True).start()
    uri='http://127.0.0.1:'+str(srv.server_port)
    def request(path,body=None,authorized=True):
        headers={'Content-Type':'application/json'}
        if authorized:headers['X-Axiom-Token']=st.token
        req=Request(uri+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        with urlopen(req,timeout=30) as stream:return json.load(stream)
    try:
        with pytest.raises(HTTPError) as err:request('/api/agents/list?graph_id='+g['id'],authorized=False)
        assert err.value.code==403
        result=request('/api/agents/run',{'graph_id':g['id'],'target':targets[0],'consent':True})
        assert result['current']
        assert request('/api/agents/get?id='+result['id'])['code']==result['code']
        assert len(request('/api/agents/list?graph_id='+g['id'])['records'])==1
        impact=request('/api/agents/impact',{'graph_id':g['id'],'targets':[targets[0]]})
        assert len(impact['affected'])==2
        with pytest.raises(HTTPError) as err:request('/api/agents/stage',{'id':result['id'],'candidate_sha256':result['candidate_sha256']})
        assert err.value.code==400
        assert request('/api/agents/stage',{'id':result['id'],'candidate_sha256':result['candidate_sha256'],'acknowledge':True})['candidate']['staged']
    finally:srv.shutdown();srv.server_close()


def test_unconfigured_model_and_unsupported_url(prepared,monkeypatch):
    st,pid,_=prepared;g,f,targets=prepare(st,pid)
    monkeypatch.delenv('AXIOM_STUDIO_LLM_ENDPOINT',raising=False)
    monkeypatch.delenv('AXIOM_STUDIO_LLM_MODEL',raising=False)
    with pytest.raises(AgentForgeError,match='未配置'):st.agent_forge.run(g['id'],targets[0],True)
    monkeypatch.setenv('AXIOM_STUDIO_LLM_MODEL','m')
    monkeypatch.setenv('AXIOM_STUDIO_LLM_ENDPOINT','http://example.org/llm')
    with pytest.raises(AgentForgeError,match='HTTPS'):st.agent_forge.run(g['id'],targets[0],True)


def test_batch_two_modules_with_real_mock_provider(prepared,fake_provider):
    st,pid,_=prepared;g,f,targets=prepare(st,pid)
    originals={t:st.proposals.file_guard(t).read_bytes() for t in targets}
    with pytest.raises(AgentForgeError):st.agent_forge.run_many(g['id'],targets)
    batch=st.agent_forge.run_many(g['id'],targets,True,1,2)
    assert batch['total']==2 and batch['passed']==2 and len(fake_provider)==4
    assert len(st.agent_forge.list(g['id'])['records'])==2
    assert all(st.proposals.file_guard(t).read_bytes()==originals[t] for t in targets)
    assert batch['candidate_auto_staged'] is False and not batch['native_execution_authorized']


def test_batch_invalid_input_does_not_contact_provider(prepared,fake_provider):
    st,pid,_=prepared;g,f,targets=prepare(st,pid)
    with pytest.raises(AgentForgeError):st.agent_forge.run_many(g['id'],targets+targets,True)
    with pytest.raises(AgentForgeError):st.agent_forge.run_many(g['id'],['../unsafe.cpp'],True)
    with pytest.raises(AgentForgeError):st.agent_forge.run_many(g['id'],targets,True,concurrency=4)
    assert not fake_provider


def test_parallel_agent_threads_are_distinct(prepared,monkeypatch):
    st,pid,_=prepared;g,f,targets=prepare(st,pid)
    monkeypatch.setenv('AXIOM_STUDIO_LLM_MODEL','fake-local')
    monkeypatch.setenv('AXIOM_STUDIO_LLM_ENDPOINT','http://localhost:12345/chat/completions')
    arrival=threading.Barrier(2,timeout=12)
    workers=[]
    def provider(prompt,role,url,model):
        if 'builder' in role:
            workers.append(threading.current_thread().name)
            arrival.wait()
            return 'int demo() { return 1; }'
        return 'Advisory note only.'
    monkeypatch.setattr(st.agent_forge,'_call',provider)
    r=st.agent_forge.run_many(g['id'],targets,True,concurrency=2)
    assert r['passed']==2 and len(set(workers))==2
    assert all('axiom-agents' in w for w in workers)


def test_real_cpp_agent_to_independent_gate(prepared,monkeypatch):
    """A candidate from the agent lane still needs manual review & a real C++ Gate."""
    import time
    st,pid,_=prepared;g,f,targets=prepare(st,pid)
    target=targets[0]
    original=st.proposals.file_guard(target).read_text('utf8')
    monkeypatch.setenv('AXIOM_STUDIO_LLM_ENDPOINT','http://127.0.0.1:12345/v1/chat/completions')
    monkeypatch.setenv('AXIOM_STUDIO_LLM_MODEL','local-stub-not-a-real-model')
    def fake_call(prompt,role,url,model):
        return original+'\n// accepted reviewer-bounded test\n' if 'builder' in role else 'Advisory: test integration, balances, and overflow.'
    monkeypatch.setattr(st.agent_forge,'_call',fake_call)
    agent=st.agent_forge.run(g['id'],target,True)
    staged=st.agent_forge.stage(agent['id'],agent['candidate_sha256'],True)
    assert staged['fleet']['packets'][0]['candidate_sha256']==agent['candidate_sha256']
    imported=st.fleet.promote(g['id'],target,agent['candidate_sha256'])
    lane=imported['assembly']
    assert lane['action']['id']=='review'
    st.assembly.review(lane['id'],lane['candidate_digest'],True)
    st.assembly.apply(lane['id'],'human_authorized_apply')
    st.assembly.verify(lane['id'],True)
    end=time.monotonic()+100
    while time.monotonic()<end:
        state=st.assembly.poll(lane['id'])
        if state['state']!='validating':break
        time.sleep(.2)
    assert state['state']=='passed',state
    final=st.task_graphs.sync(g['id'])
    assert final['completed']==1 and final['tasks'][0]['state']=='passed'
    assert final['production_release_authorized'] is False
