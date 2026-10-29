"""Intent-first onboarding must be usable and fail closed. No fake goal coverage."""
import json
from pathlib import Path
import shutil
import sys
import threading
from http.server import ThreadingHTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError

import pytest

STUDIO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(STUDIO))
import server
from launchpad import LaunchError

@pytest.fixture
def local(tmp_path,monkeypatch):
    w=tmp_path/'workspace';w.mkdir()
    monkeypatch.setattr(server,'ROOT',tmp_path)
    monkeypatch.setattr(server,'WORKSPACE',w)
    monkeypatch.setattr(server,'EVIDENCE',tmp_path/'.studio-data'/'evidence')
    st=server.Studio()
    yield st
    st.executor.shutdown(wait=False,cancel_futures=True)

def test_empty_journey_explains_product_and_does_not_approve(local):
    state=local.journey.snapshot()
    assert state['schema']=='ax-studio-journey/1.1'
    assert state['projects']==[] and state['production_release_authorized'] is False
    assert len(state['steps'])==6
    assert '不会自动' in state['important_notice']

def test_natural_goal_creates_project_without_execution_or_false_coverage(local):
    r=local.journey.start('model-toggle','我的智能家居','开灯后应保持允许的工作状态')
    p=r['project']
    assert r['goal_status']=='recorded_unverified'
    assert '不是从您输入的目标自动推导' in r['important_notice']
    assert p['name']=='我的智能家居' and p['status']=='draft'
    assert p['goal']=='开灯后应保持允许的工作状态'
    assert p['spec'].startswith('projects/idea-')
    assert not local.recent()
    state=local.journey.snapshot()['projects'][0]
    assert state['next']['id']=='verify' and not state['model_checked']
    assert not state['release_authorized']

def test_unique_projects_and_invalid_input(local):
    a=local.journey.start('model-ledger','第一套账户软件','保证余额之和不变')['project']
    b=local.journey.start('model-ledger','第二套账户软件','增加异常行为限制')['project']
    assert a['spec']!=b['spec']
    with pytest.raises(LaunchError):local.journey.start('not-a-template','合法项目','目标描述')
    with pytest.raises(LaunchError):local.journey.start('model-toggle','x','目标描述')
    with pytest.raises(LaunchError):local.journey.start('model-toggle','合法项目','ab')
    assert local.journey.snapshot()['total']==2

def test_real_model_progress_and_contract_human_required(local):
    r=local.journey.start('model-toggle','开关规则','确保开关转换满足行为性质')
    p=r['project']
    local.flow.verify_spec(p['id'])
    step=local.journey.snapshot()['projects'][0]
    assert step['model_checked'] and step['next']['id']=='freeze'
    assert step['steps'][1]['state']=='passed'
    assert not step['tested_only'] and not step['release_authorized']
    draft=local.production.draft(p['id'])
    assert draft['suggested']
    req=[{**x,'text':'人工确认开关状态符合规格要求'} for x in draft['suggested']]
    local.production.freeze(p['id'],req,local.flow.get(p['id'])['baseline'])
    step=local.journey.snapshot()['projects'][0]
    assert step['next']['id']=='task'
    assert step['steps'][2]['state']=='passed'
    assert not step['release_authorized']

def test_change_stales_journey_and_cannot_reuse_evidence(local):
    r=local.journey.start('model-toggle','状态状态机','任何时候状态转换合法');pid=r['project']['id']
    local.flow.verify_spec(pid)
    spec=local.flow.workspace/r['project']['spec']
    spec.write_text(spec.read_text()+'\n// changed after model check\n')
    st=local.journey.snapshot()['projects'][0]
    assert st['stale'] and not st['model_checked'] and st['next']['id']=='fork'
    assert not st['release_authorized']

def test_audit_failure_does_not_claim_success(local,monkeypatch):
    local.journey.start('model-toggle','监控工程','监控开关变化')
    def broken(_):raise RuntimeError('audit not available')
    monkeypatch.setattr(local.production,'overview',broken)
    result=local.journey.snapshot()
    assert result['errors'] and result['projects'][0]['next']['id']=='inspect'
    assert not result['projects'][0]['release_authorized']

def test_authenticated_http_and_onboarding(local):
    srv=ThreadingHTTPServer(('127.0.0.1',0),server.Handler);srv.studio=local
    th=threading.Thread(target=srv.serve_forever,daemon=True);th.start()
    root='http://127.0.0.1:'+str(srv.server_port)
    def get(route):
        with urlopen(Request(root+route,headers={'X-Axiom-Token':local.token}),timeout=15) as res:return json.load(res)
    try:
        with pytest.raises(HTTPError) as unauthorized:urlopen(root+'/api/journey',timeout=6)
        assert unauthorized.value.code==403
        assert get('/api/journey')['total']==0
        data=json.dumps({'scenario':'cpp-ledger','name':'真正的软件工作流','goal':'软件应满足账户守恒性质'}).encode('utf-8')
        with urlopen(Request(root+'/api/journey/start',data=data,headers={'X-Axiom-Token':local.token,'Content-Type':'application/json'},method='POST'),timeout=15) as r:
            created=json.load(r);assert r.status==201
        assert created['goal_status']=='recorded_unverified'
        assert get('/api/journey')['projects'][0]['next']['risk']=='model_only'
        assert get('/health')['version']=='1.6.0'
        with urlopen(root+'/journey.js',timeout=15) as r:
            assert b'journeyStartForm' in r.read()
    finally:srv.shutdown();srv.server_close()

def test_new_ui_exposes_real_actions_and_paradigm():
    html=(STUDIO/'static'/'index.html').read_text()
    js=(STUDIO/'static'/'journey.js').read_text()
    assert 'journeyStartForm' in html and 'journeyParadigm' in html
    assert '/journey.js' in html and '/api/journey/start' in js
    assert '/api/intent/confirm' in js and '/api/intent/save' in js
    assert 'production_release_authorized' in (STUDIO/'journey.py').read_text()
    assert 'VS Code' in html
