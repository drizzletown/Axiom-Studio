"""V1.2 intent editor: real persistence, fail-closed version and Gate, no evidence laundering."""
from __future__ import annotations
import json
import sys
import threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import pytest

STUDIO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(STUDIO))
import server
from orchestrator import FlowConflict, FlowError

@pytest.fixture
def env(tmp_path,monkeypatch):
    w=tmp_path/'workspace';w.mkdir()
    monkeypatch.setattr(server,'ROOT',tmp_path)
    monkeypatch.setattr(server,'WORKSPACE',w)
    monkeypatch.setattr(server,'EVIDENCE',tmp_path/'.studio-data'/'evidence')
    s=server.Studio()
    yield s
    s.executor.shutdown(wait=False,cancel_futures=True)

def setup_project(s,verify=False):
    x=s.journey.start('model-toggle','验收场景实验','从具体目标出发记录行为与异常处理')
    pid=x['project']['id']
    if verify:s.flow.verify_spec(pid)
    return pid

def filled(s,pid):
    draft=s.intent_spec.get(pid)
    draft['items'][0]['title']='开关只在有限状态内切换'
    draft['items'][0]['then']='切换后的状态总是合法的布尔值'
    return draft

def test_template_is_only_suggested_and_does_not_claim_goal_coverage(env):
    pid=setup_project(env)
    draft=env.intent_spec.get(pid)
    assert not draft['saved'] and draft['version']==0
    assert draft['properties'] and draft['linked_count']==len(draft['items'])
    assert '不证明' in draft['link_notice']
    assert env.production.overview(pid)['contract'] is None

def test_save_persists_version_across_restart_and_blocks_concurrent_stale_write(env):
    pid=setup_project(env);initial=filled(env,pid)
    saved=env.intent_spec.save(pid,initial['items'],0,initial['baseline'])
    assert saved['version']==1 and saved['saved']
    assert env.intent_spec.get(pid)['digest']==saved['digest']
    other=server.Studio()
    assert other.intent_spec.get(pid)['items']==saved['items']
    other.executor.shutdown(wait=False,cancel_futures=True)
    with pytest.raises(FlowConflict):env.intent_spec.save(pid,initial['items'],0,initial['baseline'])

def test_add_unmapped_requirement_visible_and_blocks_passport(env):
    pid=setup_project(env,True);raw=filled(env,pid)
    raw['items'].append({'id':'REQ-002','title':'交易失败时给出清晰错误','given':'出现拒绝条件',
                         'when':'用户提交失败请求','then':'必须给出可定位的错误信息','property':None})
    saved=env.intent_spec.save(pid,raw['items'],0,raw['baseline'])
    assert saved['gap_count']==1
    with pytest.raises(FlowError):env.intent_spec.confirm(pid,saved['version'],saved['digest'],'')
    result=env.intent_spec.confirm(pid,saved['version'],saved['digest'],'CONFIRM_HUMAN_ACCEPTANCE')
    assert result['status']=='frozen_with_gaps' and result['unmapped']==1
    overview=env.production.overview(pid)
    assert 'REQUIREMENT_NOT_MODEL_SUPPORTED:REQ-002' in overview['blockers']
    assert overview['contract']['body']['requirements'][1]['kind']=='unverified'
    assert overview['contract']['body']['human_review_source']==saved['digest']
    with pytest.raises(FlowConflict):env.intent_spec.save(pid,raw['items'],saved['version'],raw['baseline'])

def test_freeze_requires_real_spec_check_and_unchanged_version(env):
    pid=setup_project(env);raw=filled(env,pid)
    saved=env.intent_spec.save(pid,raw['items'],0,raw['baseline'])
    with pytest.raises(FlowConflict,match='模型验证'):env.intent_spec.confirm(pid,saved['version'],saved['digest'],'CONFIRM_HUMAN_ACCEPTANCE')
    env.flow.verify_spec(pid)
    with pytest.raises(FlowConflict,match='草稿'):env.intent_spec.confirm(pid,0,saved['digest'],'CONFIRM_HUMAN_ACCEPTANCE')
    assert env.intent_spec.confirm(pid,saved['version'],saved['digest'],'CONFIRM_HUMAN_ACCEPTANCE')['status']=='frozen_mapped'
    assert not env.production.overview(pid)['eligible_for_live_recheck']

def test_changing_spec_invalidates_plan_and_prevents_reuse(env):
    pid=setup_project(env);raw=filled(env,pid)
    saved=env.intent_spec.save(pid,raw['items'],0,raw['baseline'])
    spec=env.flow._file(env.flow.get(pid)['spec'],'.ax')
    spec.write_text(spec.read_text()+'\n// changed baseline\n')
    assert env.intent_spec.get(pid)['stale']
    with pytest.raises(FlowConflict):env.intent_spec.save(pid,raw['items'],saved['version'],saved['baseline'])
    with pytest.raises(FlowConflict):env.intent_spec.design_task(pid)
    with pytest.raises(FlowConflict):env.intent_spec.confirm(pid,saved['version'],saved['digest'],'CONFIRM_HUMAN_ACCEPTANCE')

def test_rejects_fabricated_property_and_invalid_scenario(env):
    pid=setup_project(env);raw=filled(env,pid)
    raw['items'][0]['property']='FakeProperty'
    with pytest.raises(FlowError,match='不存在'):env.intent_spec.save(pid,raw['items'],0,raw['baseline'])
    raw['items'][0]['property']=None
    raw['items'][0]['then']='x'
    with pytest.raises(FlowError,match='预期结果'):env.intent_spec.save(pid,raw['items'],0,raw['baseline'])

def test_rejects_data_tampering(env):
    pid=setup_project(env);raw=filled(env,pid)
    env.intent_spec.save(pid,raw['items'],0,raw['baseline'])
    with env.flow._connect() as cx:
        cx.execute('UPDATE intent_scenario_plans SET body=? WHERE project_id=?', ('{}',pid))
    with pytest.raises(FlowConflict,match='摘要'):env.intent_spec.get(pid)

def test_design_task_contains_gaps_spec_and_prohibits_auto_edits(env):
    pid=setup_project(env);raw=filled(env,pid)
    raw['items'][0]['property']=None
    env.intent_spec.save(pid,raw['items'],0,raw['baseline'])
    packet=env.intent_spec.design_task(pid)
    assert packet['executed'] is False and packet['gaps']==1
    assert 'model' in packet['prompt'].lower() and 'current_spec_source' in packet['prompt']
    assert '不可修改原始规格' in packet['prompt']

def test_http_authorization_save_and_freeze(env):
    pid=setup_project(env,True)
    app=ThreadingHTTPServer(('127.0.0.1',0),server.Handler);app.studio=env
    t=threading.Thread(target=app.serve_forever,daemon=True);t.start()
    root='http://127.0.0.1:'+str(app.server_port)
    def request(route,data=None,token=True):
        headers={'Content-Type':'application/json'}
        if token:headers['X-Axiom-Token']=env.token
        raw=json.dumps(data).encode('utf-8') if data is not None else None
        with urlopen(Request(root+route,data=raw,method='POST' if raw else 'GET',headers=headers),timeout=25) as response:
            return response.status,json.load(response)
    try:
        with pytest.raises(HTTPError) as ex:request('/api/intent/plan?id='+pid,token=False)
        assert ex.value.code==403
        assert request('/health')[1]['version']=='1.6.0'
        data=request('/api/intent/plan?id='+pid)[1]
        data['items'][0]['then']='完成切换后状态始终为允许的值'
        status,saved=request('/api/intent/save',{'id':pid,'items':data['items'],'version':0,'baseline':data['baseline']})
        assert status==200 and saved['version']==1
        _,task=request('/api/intent/task?id='+pid)
        assert task['executed']==False
        status,result=request('/api/intent/confirm',{'id':pid,'version':1,'digest':saved['digest'],'confirmation':'CONFIRM_HUMAN_ACCEPTANCE'})
        assert status==201 and result['status']=='frozen_mapped'
        with pytest.raises(HTTPError) as err:request('/api/intent/save',{'id':pid,'items':data['items'],'version':1,'baseline':data['baseline']})
        assert err.value.code==409
    finally:app.shutdown();app.server_close()

def test_ui_has_understandable_scenarios_not_programming_entry():
    js=(STUDIO/'static'/'journey.js').read_text('utf-8')
    html=(STUDIO/'static'/'index.html').read_text('utf-8')
    assert '在什么情况下' in js and '必须得到什么结果' in js
    assert 'journeyReviewAdd' in html and 'journeyCoverage' in html
    assert '/api/intent/confirm' in js and '/api/intent/task' in js
    assert '代码编辑不是' not in html # implementation remains integrated, not presented as the starting point
