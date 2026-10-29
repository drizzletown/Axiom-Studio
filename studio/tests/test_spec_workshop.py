"""V1.3: real spec-check engine, detached revision and fail-closed review."""
import json
import os
import sys
import threading
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from unittest.mock import patch
import pytest

STUDIO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(STUDIO))
import server
from orchestrator import FlowError,FlowConflict

@pytest.fixture
def env(tmp_path,monkeypatch):
    w=tmp_path/'workspace';w.mkdir()
    monkeypatch.setattr(server,'ROOT',tmp_path)
    monkeypatch.setattr(server,'WORKSPACE',w)
    monkeypatch.setattr(server,'EVIDENCE',tmp_path/'.studio-data'/'evidence')
    s=server.Studio()
    yield s
    s.executor.shutdown(wait=False,cancel_futures=True)

def prepared(s):
    pid=s.journey.start('model-toggle','业务意图实验','开关改变后应该保持正确的状态')['project']['id']
    plan=s.intent_spec.get(pid)
    s.intent_spec.save(pid,plan['items'],0,plan['baseline'])
    original=s.flow._file(s.flow.get(pid)['spec'],'.ax').read_text('utf-8')
    candidate=original.replace('  observe {','  property AlwaysBool { always enabled == true || enabled == false }\n  observe {')
    return pid,original,candidate

def test_prompt_explicitly_unverified_and_no_project_mutation(env):
    pid,orig,_=prepared(env)
    task=env.spec_workshop.task(pid)
    assert 'scenarios' in task['prompt'] and 'source_digest' in task['prompt']
    assert '完整的 Axiom' in task['prompt']
    assert not env.spec_workshop.list(pid)
    assert not env.flow.get(pid)['last_verification']
    assert env.flow._file(env.flow.get(pid)['spec'],'.ax').read_text('utf-8')==orig

def test_real_model_check_and_human_fork_no_proof_laundering(env):
    pid,orig,source=prepared(env)
    staged=env.spec_workshop.create(pid,source,notes='尝试明确模型性质')
    with pytest.raises(FlowConflict):env.spec_workshop.promote(staged['id'],staged['source_sha256'],{'REQ-001':'AlwaysBool'},'I_REVIEWED_SPEC_AND_MAPPINGS')
    result=env.spec_workshop.assess(staged['id'])
    assert result['state']=='checked' and result['assessment']['passed'] is True
    assert len(result['assessment']['checks'])==4
    assert result['assessment']['checks'][-1]['outcome']=='Approved'
    assert 'AlwaysBool' in result['assessment']['properties']
    with pytest.raises(FlowError):env.spec_workshop.promote(staged['id'],staged['source_sha256'],{'REQ-001':'AlwaysBool'},'')
    with pytest.raises(FlowError):env.spec_workshop.promote(staged['id'],staged['source_sha256'],{'REQ-001':'Invented'},'I_REVIEWED_SPEC_AND_MAPPINGS')
    x=env.spec_workshop.promote(staged['id'],staged['source_sha256'],{'REQ-001':'AlwaysBool'},'I_REVIEWED_SPEC_AND_MAPPINGS')
    child=x['child'];new=env.flow._file(child['spec'],'.ax')
    assert new.read_text('utf-8')==source
    assert env.flow._file(env.flow.get(pid)['spec'],'.ax').read_text('utf-8')==orig
    assert child['parent_id']==pid and child['effective_status']=='draft'
    assert x['scenarios']['items'][0]['property']=='AlwaysBool'
    assert x['scenarios']['saved'] and not x['scenarios']['frozen']
    assert env.production.overview(child['id'])['contract'] is None
    assert child['last_verification'] is None and child['decision'] is None
    assert not x['proposal']['lineage']['contract_carried_over']
    with pytest.raises(FlowConflict):env.spec_workshop.promote(staged['id'],staged['source_sha256'],{'REQ-001':'AlwaysBool'},'I_REVIEWED_SPEC_AND_MAPPINGS')

def test_invalid_candidate_does_not_fork(env):
    pid,orig,_=prepared(env)
    b=env.spec_workshop.create(pid,'model Broken { please this is not valid }')
    outcome=env.spec_workshop.assess(b['id'])
    assert outcome['state']=='rejected_by_model' and not outcome['assessment']['passed']
    with pytest.raises(FlowConflict):env.spec_workshop.promote(b['id'],b['source_sha256'],{'REQ-001':None},'I_REVIEWED_SPEC_AND_MAPPINGS')
    assert len(env.flow.list())==1
    assert env.flow._file(env.flow.get(pid)['spec'],'.ax').read_text('utf-8')==orig

def test_unmapped_gap_remains_open_in_child(env):
    pid,_,source=prepared(env)
    plan=env.intent_spec.get(pid)
    items=plan['items']+[{'id':'REQ-002','title':'失败应明确提示','given':'业务请求出现失败条件',
         'when':'发起未满足前提的操作','then':'应当返回一条可审查的具体错误信息','property':None}]
    env.intent_spec.save(pid,items,plan['version'],plan['baseline'])
    proposal=env.spec_workshop.create(pid,source)
    env.spec_workshop.assess(proposal['id'])
    x=env.spec_workshop.promote(proposal['id'],proposal['source_sha256'],
                {'REQ-001':'StableType','REQ-002':None},'I_REVIEWED_SPEC_AND_MAPPINGS')
    assert x['scenarios']['gap_count']==1
    assert x['scenarios']['items'][1]['property'] is None
    assert x['child']['status']=='draft'

def test_changed_parent_or_scenarios_invalidates_proposal(env):
    pid,_,source=prepared(env)
    proposal=env.spec_workshop.create(pid,source)
    plan=env.intent_spec.get(pid)
    items=plan['items'];items[0]['then']='修改后的预期结果仍需人工审查'
    env.intent_spec.save(pid,items,plan['version'],plan['baseline'])
    with pytest.raises(FlowConflict):env.spec_workshop.assess(proposal['id'])
    assert not env.spec_workshop.get(proposal['id'])['current']
    assert env.spec_workshop.list(pid)[0]['state']=='proposed'


def test_tampered_persisted_proposal_detected(env):
    pid,_,source=prepared(env)
    p=env.spec_workshop.create(pid,source)
    with env.flow._connect() as cx:
        cx.execute('UPDATE spec_workshop_proposals SET body=? WHERE id=?',('{}',p['id']))
    with pytest.raises(FlowConflict):env.spec_workshop.get(p['id'])


def test_no_saved_scenarios_cannot_start_workshop(env):
    pid=env.journey.start('model-toggle','最初的想法','实现开关系统并考虑边界')['project']['id']
    with pytest.raises(FlowConflict):env.spec_workshop.task(pid)
    with pytest.raises(FlowConflict):env.spec_workshop.create(pid,'model Foo {}')


def test_model_call_requires_consent_no_fallback(env):
    pid,_,_=prepared(env)
    with pytest.raises(FlowError):env.spec_workshop.generate(pid,False)
    with pytest.raises(FlowError):env.spec_workshop.generate(pid,True)


def test_real_stubbed_model_endpoint_generates_only_proposal(env,monkeypatch):
    pid,orig,source=prepared(env)
    class ModelHandler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            raw=self.rfile.read(int(self.headers['Content-Length']));req=json.loads(raw)
            assert '完整的 Axiom' in req['messages'][0]['content']
            body=json.dumps({'choices':[{'message':{'content':source}}]}).encode('utf-8')
            self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    model=ThreadingHTTPServer(('127.0.0.1',0),ModelHandler)
    t=threading.Thread(target=model.serve_forever,daemon=True);t.start()
    try:
        monkeypatch.setenv('AXIOM_STUDIO_LLM_ENDPOINT',f'http://127.0.0.1:{model.server_port}/v1/chat/completions')
        monkeypatch.setenv('AXIOM_STUDIO_LLM_MODEL','fixture-local-llm')
        p=env.spec_workshop.generate(pid,True)
        assert p['origin']=='model' and p['state']=='proposed' and p['assessment'] is None
        assert env.flow._file(env.flow.get(pid)['spec'],'.ax').read_text('utf-8')==orig
    finally:model.shutdown();model.server_close()


def test_http_review_boundaries(env):
    pid,orig,source=prepared(env)
    app=ThreadingHTTPServer(('127.0.0.1',0),server.Handler);app.studio=env
    worker=threading.Thread(target=app.serve_forever,daemon=True);worker.start()
    base=f'http://127.0.0.1:{app.server_port}'
    def call(route,data=None,with_token=True):
        headers={'Content-Type':'application/json'}
        if with_token:headers['X-Axiom-Token']=env.token
        req=Request(base+route,data=json.dumps(data).encode() if data else None,
            method='POST' if data else 'GET',headers=headers)
        with urlopen(req,timeout=70) as r:return r.status,json.load(r)
    try:
        with pytest.raises(HTTPError) as exc:call('/api/spec-workshop/task?id='+pid,with_token=False)
        assert exc.value.code==403
        assert call('/health')[1]['version']=='1.6.0'
        with urlopen(base+'/spec_workshop.js',timeout=15) as page:
            assert b'specWorkshopPromote' in page.read()
        assert call('/api/spec-workshop/task?id='+pid)[0]==200
        status,c=call('/api/spec-workshop/create',{'id':pid,'source':source})
        assert status==201 and c['current']
        with pytest.raises(HTTPError) as exc:call('/api/spec-workshop/promote',{'candidate':c['id'],'digest':c['source_sha256'],
          'mappings':{'REQ-001':'AlwaysBool'},'confirmation':'I_REVIEWED_SPEC_AND_MAPPINGS'})
        assert exc.value.code==409
        assert call('/api/spec-workshop/check',{'candidate':c['id']})[1]['assessment']['passed']
        status,result=call('/api/spec-workshop/promote',{'candidate':c['id'],'digest':c['source_sha256'],
          'mappings':{'REQ-001':'AlwaysBool'},'confirmation':'I_REVIEWED_SPEC_AND_MAPPINGS'})
        assert status==201 and result['child']['parent_id']==pid
    finally:app.shutdown();app.server_close()


def test_ui_exposes_no_training_workflow_and_real_actions():
    html=(STUDIO/'static'/'index.html').read_text('utf-8')
    js=(STUDIO/'static'/'spec_workshop.js').read_text('utf-8')
    for x in ('specWorkshopGoal','specWorkshopMappings','specWorkshopPromote','specWorkshopDiff'):
        assert x in html
    assert '/api/spec-workshop/promote' in js and 'I_REVIEWED_SPEC_AND_MAPPINGS' in js
    assert 'journeyStartForm' in html and 'software' not in ''


def test_cpp_manifest_branch_preserves_original_and_rebinds_spec(env,monkeypatch):
    pid=env.journey.start('cpp-ledger','真实交易构造','需要正确实现双账户转账并验证守恒')['project']['id']
    initial=env.intent_spec.get(pid)
    env.intent_spec.save(pid,initial['items'],0,initial['baseline'])
    parent=env.flow.get(pid)
    original=env.flow._file(parent['spec'],'.ax').read_text('utf-8')
    candidate=original+'\n// An audited proposed revision, without changing the original file.\n'
    from production import _load_ax
    properties=[x['name'] for x in _load_ax(env.flow.engine, candidate)['properties']]
    monkeypatch.setattr(env.spec_workshop,'_evaluate',lambda text:{'passed':True,'checks':[{'step':'mocked-for-structure','returncode':0}],
         'properties':properties,'scope':'structure-only fixture, not real model verification'})
    sp=env.spec_workshop.create(pid,candidate)
    checked=env.spec_workshop.assess(sp['id'])
    assert checked['assessment']['passed']
    links={x['id']:x['property'] for x in initial['items']}
    child=env.spec_workshop.promote(sp['id'],sp['source_sha256'],links,'I_REVIEWED_SPEC_AND_MAPPINGS')['child']
    assert child['manifest'] and child['manifest']!=parent['manifest']
    m=env.flow._file(child['manifest'],'.json')
    info=json.loads(m.read_text('utf-8'))
    assert (m.parent/info['spec']).resolve()==env.flow._file(child['spec'],'.ax')
    assert env.flow._file(parent['spec'],'.ax').read_text('utf-8')==original
    assert env.flow._file(parent['manifest'],'.json')!=m
    assert child['effective_status']=='draft'
