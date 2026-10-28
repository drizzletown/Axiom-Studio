"""Release 1.0: real service, status, tamper, API and trust boundary."""
import json
from pathlib import Path
import shutil
import sys
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import pytest

STUDIO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(STUDIO))
import server

@pytest.fixture
def local(tmp_path,monkeypatch):
    w=tmp_path/'workspace'/'projects'/'sample'
    w.mkdir(parents=True)
    for f in (STUDIO/'templates'/'cpp-ledger').iterdir():
        if f.is_file(): shutil.copy2(f,w/f.name)
    monkeypatch.setattr(server,'WORKSPACE',tmp_path/'workspace')
    monkeypatch.setattr(server,'ROOT',tmp_path)
    monkeypatch.setattr(server,'EVIDENCE',tmp_path/'.studio-data'/'evidence')
    st=server.Studio()
    yield st,w
    st.executor.shutdown(wait=True,cancel_futures=True)

def project(st):
    return st.flow.create('Sample C++ project','验证受约束的软件构造流程',
                          'projects/sample/ledger.ax','projects/sample/project.json')

def test_empty_cockpit_and_environment_cannot_auto_release(local):
    st,_=local
    view=st.cockpit.snapshot()
    assert view['counts']['total']==0 and view['projects']==[]
    assert view['counts']['production_release_authorized']==0
    env=st.cockpit.doctor()
    assert env['model_engine_present'] and env['native_run_requires_consent']
    assert not env['sandbox_guaranteed'] and not env['production_release_authorized']

def test_project_stages_and_live_model_verification(local):
    st,_=local;p=project(st)
    view=st.cockpit.snapshot();r=view['projects'][0]
    assert r['id']==p['id'] and r['steps'][0]['state']=='pending'
    assert view['next_actions'][0]['next_action']=='verify'
    actual=st.flow.verify_spec(p['id'])
    assert st.flow.get(p['id'])['effective_status']=='spec_ready'
    view=st.cockpit.snapshot();r=view['projects'][0]
    assert r['steps'][0]['state']=='passed' and r['steps'][1]['state']=='pending'
    assert 'PRODUCTION_CONTRACT_MISSING' in r['blockers']
    assert not r['production_release_authorized']

def test_human_frozen_contract_must_not_allow_release(local):
    st,_=local;p=project(st);st.flow.verify_spec(p['id'])
    draft=st.production.draft(p['id'])
    requirements=[{**req,'text':('核查 '+req['property']+' 对应的状态约束与不变量')} for req in draft['suggested']]
    st.production.freeze(p['id'],requirements,p['baseline'])
    r=st.cockpit.snapshot()['projects'][0]
    assert r['steps'][0]['state']=='passed' and r['steps'][1]['state']=='passed'
    assert r['steps'][3]['state']=='pending'
    assert r['production_release_authorized'] is False

def test_spec_change_and_unreliable_audit_fail_closed(local):
    st,w=local;p=project(st);st.flow.verify_spec(p['id'])
    (w/'ledger.ax').write_text((w/'ledger.ax').read_text()+'\n// changed\n')
    x=st.cockpit.snapshot()['projects'][0]
    assert x['stale'] and 'INPUTS_STALE' in x['blockers']
    assert x['steps'][0]['state']!='passed'
    assert not x['production_release_authorized']

def test_unavailable_project_assessment_is_not_silently_approved(local,monkeypatch):
    st,_=local;project(st)
    def broken(_):raise RuntimeError('simulated audit failure')
    monkeypatch.setattr(st.production,'overview',broken)
    view=st.cockpit.snapshot()
    assert view['counts']['total']==1 and view['errors']
    assert view['projects'][0]['state']=='unknown'
    assert view['projects'][0]['blockers']==['PROJECT_STATUS_UNAVAILABLE']
    assert view['counts']['production_release_authorized']==0

def test_cockpit_does_not_invoke_native_execution(local,monkeypatch):
    st,_=local;project(st)
    def unexpected(*args,**kwargs):raise AssertionError('unsafe native code execution')
    monkeypatch.setattr(st,'start_job',unexpected)
    monkeypatch.setattr(st,'start_proposal_job',unexpected)
    st.cockpit.snapshot();st.cockpit.doctor()

def test_authenticated_http_cockpit_and_doctor(local):
    st,_=local;project(st)
    srv=ThreadingHTTPServer(('127.0.0.1',0),server.Handler);srv.studio=st
    thread=threading.Thread(target=srv.serve_forever,daemon=True);thread.start()
    url=f'http://127.0.0.1:{srv.server_port}'
    try:
        with pytest.raises(HTTPError) as e:urlopen(url+'/api/cockpit',timeout=8)
        assert e.value.code==403
        for route,expect in (('/api/cockpit','ax-studio-cockpit/1.0'),('/api/doctor','ax-studio-doctor/1.0')):
            with urlopen(Request(url+route,headers={'X-Axiom-Token':st.token}),timeout=8) as resp:
                data=json.load(resp)
            assert data['schema']==expect and data['version']=='1.0.0'
            assert data.get('production_release_authorized',False) is False
    finally:srv.shutdown();srv.server_close()

def test_html_cockpit_bound_to_release_api():
    html=(STUDIO/'static'/'index.html').read_text()
    js=(STUDIO/'static'/'cockpit.js').read_text()
    assert 'cockpitSummary' in html and '/cockpit.js' in html
    assert '/api/cockpit' in js and 'selectProject' in js
