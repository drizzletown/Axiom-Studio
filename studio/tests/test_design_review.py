"""1.4 read-only side-by-side model review; verification is not intent proof."""
import json
import sys
import threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import pytest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import server
from orchestrator import FlowConflict,FlowError


@pytest.fixture
def env(tmp_path,monkeypatch):
    w=tmp_path/'workspace';w.mkdir()
    monkeypatch.setattr(server,'ROOT',tmp_path)
    monkeypatch.setattr(server,'WORKSPACE',w)
    monkeypatch.setattr(server,'EVIDENCE',tmp_path/'.studio-data'/'evidence')
    s=server.Studio()
    yield s
    s.executor.shutdown(wait=False,cancel_futures=True)


def setup(s):
    pid=s.journey.start('model-toggle','意图对照','一个开关系统应在改变状态之后保持合理行为')['project']['id']
    plan=s.intent_spec.get(pid)
    s.intent_spec.save(pid,plan['items'],0,plan['baseline'])
    original=s.flow._file(s.flow.get(pid)['spec'],'.ax').read_text('utf-8')
    a=original.replace('  observe {','  property AlwaysBoolean { always enabled == true || enabled == false }\n  observe {')
    b=original.replace('  observe {','  property NeverInvalid { always enabled == false || enabled == true }\n  observe {')
    return pid,original,a,b


def check(s,pid,source):
    p=s.spec_workshop.create(pid,source)
    result=s.spec_workshop.assess(p['id'])
    assert result['assessment']['passed'] is True, result['assessment']
    return p['id']


def test_real_two_model_checks_and_explain_compare(env):
    pid,original,a,b=setup(env)
    aid=check(env,pid,a)
    bid=check(env,pid,b)
    before=env.flow.get(pid)
    note=env.design_review.inspect(pid,aid)
    assert note['model_checked'] is True
    assert note['deltas']['properties']['added']==['AlwaysBoolean']
    assert note['properties'][0]['name']=='AlwaysBoolean'
    assert note['review_digest'].startswith('sha256:')
    report=env.design_review.compare(pid,[aid,bid])
    assert report['no_automatic_winner'] and not report['approval_performed']
    assert report['differences_between_candidates']['properties']['added']==['NeverInvalid']
    assert report['differences_between_candidates']['properties']['removed']==['AlwaysBoolean']
    assert report['candidates'][0]['unresolved_scenarios']==0
    assert report['comparison_digest'].startswith('sha256:')
    assert env.flow.get(pid)['baseline']==before['baseline']
    assert env.flow._file(before['spec'],'.ax').read_text('utf-8')==original
    assert not env.spec_workshop.get(aid)['lineage']


def test_unchecked_rejected_and_invalid_ids_fail_closed(env):
    pid,_,a,_=setup(env)
    candidate=env.spec_workshop.create(pid,a)
    with pytest.raises(FlowConflict):env.design_review.inspect(pid,candidate['id'])
    with pytest.raises(FlowError):env.design_review.compare(pid,[candidate['id']])
    with pytest.raises(FlowError):env.design_review.compare(pid,[candidate['id'],candidate['id']])
    failed=env.spec_workshop.create(pid,'model Bad { nonsense nonsense nonsense }')
    env.spec_workshop.assess(failed['id'])
    with pytest.raises(FlowConflict):env.design_review.inspect(pid,failed['id'])


def test_unmapped_scenarios_are_not_assumed_covered(env):
    pid,_,a,_=setup(env)
    plan=env.intent_spec.get(pid)
    items=plan['items']+[{'id':'REQ-200','title':'发生错误时给出解释',
           'given':'遇到用户请求无法执行的业务情况','when':'发生拒绝执行的情况',
           'then':'返回可以理解并可以恢复的原因', 'property':None}]
    env.intent_spec.save(pid,items,plan['version'],plan['baseline'])
    aid=check(env,pid,a)
    result=env.design_review.inspect(pid,aid)
    assert result['unresolved_scenarios']==1
    assert result['scenarios'][1]['status']=='unmapped'
    assert any('尚无' in x for x in [result['scenarios'][1]['message']])


def test_changed_property_requires_reaffirmation(env):
    pid,original,_,_=setup(env)
    assert 'enabled == true || enabled == false' in original
    changed=original.replace('enabled == true || enabled == false','enabled == false || enabled == true')
    cid=check(env,pid,changed)
    data=env.design_review.inspect(pid,cid)
    assert data['deltas']['properties']['changed']==['StableType']
    assert data['scenarios'][0]['status']=='changed'
    assert data['unresolved_scenarios']==1
    assert not any('业务已验证' in x for x in data['warnings'])


def test_parent_change_makes_checked_candidate_unreviewable(env):
    pid,_,a,_=setup(env)
    aid=check(env,pid,a)
    plan=env.intent_spec.get(pid)
    items=plan['items'];items[0]['then']='修改了业务期望，必须重新评审'
    env.intent_spec.save(pid,items,plan['version'],plan['baseline'])
    with pytest.raises(FlowConflict):env.design_review.inspect(pid,aid)


def test_cross_project_candidate_fails(env):
    pid,_,a,_=setup(env)
    aid=check(env,pid,a)
    other,_,_,_=setup(env)
    with pytest.raises(FlowError):env.design_review.inspect(other,aid)


def test_tampered_stored_source_fails_digest(env):
    pid,_,a,_=setup(env)
    aid=check(env,pid,a)
    with env.flow._connect() as cx:
        cx.execute('UPDATE spec_workshop_proposals SET body=? WHERE id=?',('{}',aid))
    with pytest.raises(FlowConflict):env.design_review.inspect(pid,aid)


def test_http_authenticated_review_and_static_ui(env):
    pid,_,a,_=setup(env);aid=check(env,pid,a)
    srv=ThreadingHTTPServer(('127.0.0.1',0),server.Handler);srv.studio=env
    worker=threading.Thread(target=srv.serve_forever,daemon=True);worker.start()
    base='http://127.0.0.1:'+str(srv.server_port)
    def call(path,auth=True):
        req=Request(base+path,headers={'X-Axiom-Token':env.token} if auth else {})
        with urlopen(req,timeout=25) as resp:return resp.status,json.load(resp)
    try:
        assert call('/health')[1]['version']=='1.6.0'
        with pytest.raises(HTTPError) as exc:call('/api/design-review/inspect?id='+pid+'&candidate='+aid,False)
        assert exc.value.code==403
        assert call('/api/design-review/inspect?id='+pid+'&candidate='+aid)[1]['model_checked']
        with urlopen(base+'/design_review.js',timeout=10) as f:assert b'designReviewCompare' in f.read()
        with urlopen(base+'/index.html?token='+env.token,timeout=10) as f:
            html=f.read();assert b'designReviewComparison' in html and b'design_review.js' in html
    finally:srv.shutdown();srv.server_close()


def test_no_hidden_approval_or_native_execution_in_review_code():
    code=(HERE/'design_review.py').read_text('utf-8')
    assert 'subprocess.run(' not in code and 'urllib.request' not in code
    assert 'def promote(' not in code and 'approval_performed' in code
