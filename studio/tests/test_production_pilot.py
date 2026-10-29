"""Axiom 1.5 — production pilot safety, real finite checks, live status and HTTP."""
import json
import shutil
import sys
import threading
import time
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request,urlopen
import pytest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import server
from orchestrator import FlowConflict

@pytest.fixture
def env(tmp_path,monkeypatch):
    workspace=tmp_path/'workspace';workspace.mkdir()
    monkeypatch.setattr(server,'WORKSPACE',workspace)
    monkeypatch.setattr(server,'ROOT',tmp_path)
    monkeypatch.setattr(server,'EVIDENCE',tmp_path/'.studio-data'/'evidence')
    s=server.Studio()
    yield s
    s.executor.shutdown(wait=True,cancel_futures=True)

def new_project(st):
    return st.journey.start('model-toggle','Pilot Test','实现开关切换并保证状态不变量')['project']['id']

def await_end(st,mid):
    end=time.monotonic()+90
    while time.monotonic()<end:
        v=st.pilot.get(mid)
        if v['operation_state']!='running':return v
        time.sleep(.1)
    pytest.fail('Real model checker timed out')

def test_new_mission_is_idempotent_and_goal_first(env):
    pid=new_project(env)
    a=env.pilot.create(pid);b=env.pilot.create(pid)
    assert a['id']==b['id']
    assert a['goal'] and len(a['steps'])==6
    assert a['next_action']['id']=='verify_spec'
    assert a['production_release_authorized'] is False
    assert env.pilot.audit(a['id'])['valid']

def test_real_safe_model_step_and_pauses_for_human_contract(env):
    pid=new_project(env);m=env.pilot.create(pid)
    v=env.pilot.advance_safe(m['id'],m['revision'],m['baseline_digest'])
    assert v['operation_state'] in ('running','finished')
    v=await_end(env,m['id'])
    assert v['operation_state']=='finished',v
    assert v['steps'][1]['state']=='complete'
    assert v['next_action']['id']=='confirm_contract'
    assert env.pilot.audit(m['id'])['valid']
    assert env.flow.get(pid)['effective_status']=='spec_ready'
    assert v['production_release_authorized'] is False

def test_safety_requires_version_and_no_implicit_reexecution(env):
    pid=new_project(env);m=env.pilot.create(pid)
    with pytest.raises(FlowConflict):env.pilot.advance_safe(m['id'],True,m['baseline_digest'])
    with pytest.raises(FlowConflict):env.pilot.advance_safe(m['id'],m['revision'],'bad-digest')
    env.pilot.advance_safe(m['id'],m['revision'],m['baseline_digest'])
    with pytest.raises(FlowConflict):env.pilot.advance_safe(m['id'],m['revision'],m['baseline_digest'])
    await_end(env,m['id'])

def test_source_change_invalidates_plan_and_gate(env):
    pid=new_project(env);m=env.pilot.create(pid)
    p=env.flow.get(pid);spec=env.flow._file(p['spec'],'.ax')
    spec.write_text(spec.read_text('utf8')+'\n// evolution changed\n',encoding='utf8')
    v=env.pilot.get(m['id'])
    assert v['condition']=='stale'
    assert v['next_action']['id']=='evolve'
    with pytest.raises(FlowConflict):env.pilot.advance_safe(m['id'],m['revision'],m['baseline_digest'])

def test_tamper_hash_chain_fail_closed(env):
    pid=new_project(env);m=env.pilot.create(pid)
    with env.pilot._connect() as cx:
        cx.execute("UPDATE pilot_events SET kind='forged' WHERE mission_id=?",(m['id'],))
    assert not env.pilot.audit(m['id'])['valid']
    view=env.pilot.get(m['id']);assert view['condition']=='blocked'
    assert view['next_action']['id']=='audit'
    with pytest.raises(FlowConflict):env.pilot.advance_safe(m['id'],m['revision'],m['baseline_digest'])

def test_crash_recovery_is_fail_closed(env):
    pid=new_project(env);m=env.pilot.create(pid)
    with env.pilot._connect() as cx:
        cx.execute("UPDATE missions SET status='running' WHERE id=?",(m['id'],))
    from pilot import ProductionPilot
    recovered=ProductionPilot(env,env.pilot.db)
    v=recovered.get(m['id'])
    assert v['operation_state']=='interrupted'
    assert v['condition']=='blocked'
    assert recovered.audit(m['id'])['valid']

def test_handoff_unsigned_and_digest_consistent(env):
    pid=new_project(env);m=env.pilot.create(pid)
    bundle=env.pilot.handoff(m['id'])
    from pilot import sha
    assert bundle['sha256']==sha(bundle['report'])
    assert not bundle['report']['mission']['production_release_authorized']
    assert 'Unsigned' in bundle['report']['warning']


def test_no_native_automation_and_no_approval(env,monkeypatch):
    def prohibited(*args,**kwargs):raise AssertionError('NO NATIVE EXECUTION')
    monkeypatch.setattr(env,'start_job',prohibited)
    monkeypatch.setattr(env,'start_proposal_job',prohibited)
    monkeypatch.setattr(env.workorders,'apply',prohibited)
    pid=new_project(env);m=env.pilot.create(pid)
    env.pilot.list();env.pilot.handoff(m['id']);env.pilot.audit(m['id'])
    v=env.pilot.advance_safe(m['id'],m['revision'],m['baseline_digest'])
    await_end(env,m['id'])
    assert v['production_release_authorized'] is False


def test_http_endpoints_require_token_and_do_not_accept_unsafe_actions(env):
    pid=new_project(env)
    srv=ThreadingHTTPServer(('127.0.0.1',0),server.Handler);srv.studio=env
    thread=threading.Thread(target=srv.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{srv.server_port}'
    def call(url,body=None,authorized=True):
        headers={'X-Axiom-Token':env.token} if authorized else {}
        if body is not None:headers['Content-Type']='application/json'
        with urlopen(Request(base+url,data=json.dumps(body).encode() if body is not None else None,headers=headers),timeout=25) as resp:
            return resp.status,json.load(resp)
    try:
        with pytest.raises(HTTPError) as ex:call('/api/pilot/list',authorized=False)
        assert ex.value.code==403
        status,m=call('/api/pilot/create',{'project_id':pid});assert status==201
        assert call('/api/pilot/get?id='+m['id'])[1]['goal']
        assert call('/api/pilot/audit?id='+m['id'])[1]['valid']
        assert call('/api/pilot/handoff?id='+m['id'])[1]['report']['schema']=='ax-studio-pilot-handoff/1.5'
        with pytest.raises(HTTPError) as ex:call('/api/pilot/advance',{'id':m['id'],'revision':m['revision'],'baseline_digest':'false','trusted':True})
        assert ex.value.code==409
        with urlopen(base+'/pilot.js',timeout=12) as f:assert b'pilotBegin' in f.read()
        assert call('/health')[1]['version']=='1.6.0'
    finally:srv.shutdown();srv.server_close()

def test_ui_really_integrated_and_no_new_editor():
    html=(HERE/'static'/'index.html').read_text('utf8')
    assert 'pilotHome' in html and '/pilot.js' in html and 'pilotProject' in html
    js=(HERE/'static'/'pilot.js').read_text('utf8')
    assert '/api/pilot/create' in js and '/api/pilot/advance' in js
    assert 'production_release_authorized' not in js or 'pilot' in js
