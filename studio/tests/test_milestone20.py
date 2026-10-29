"""2.0 evidence campaign: real integration and deliberate failure injection."""
import copy,json,shutil,sys,time
from pathlib import Path
from types import SimpleNamespace
import pytest
STUDIO=Path(__file__).resolve().parents[1]
ROOT=STUDIO.parent
sys.path.insert(0,str(STUDIO))
from milestone20 import Milestone20,MilestoneError
from proposals import sha

@pytest.fixture
def kit(tmp_path):
    w=tmp_path/'workspace';w.mkdir()
    shutil.copytree(ROOT/'workspace'/'cpp_project',w/'cpp_project')
    def guard(name):
        p=(w/name).resolve()
        if not p.is_relative_to(w) or not p.is_file():raise MilestoneError('unsafe path')
        return p
    p={'id':'p-demo','revision':1,'baseline':{'spec_digest':'a'*64},'manifest':'cpp_project/project.json',
       'stale':False,'last_verification':{'passed':True}}
    prod={'contract_digest':'c'*64,'blockers':['HUMAN_ACCEPTANCE_AND_CPP_GATE_REQUIRED']}
    g={'project_id':'p-demo','current':True,'complete':True}
    st=SimpleNamespace(proposals=SimpleNamespace(home=tmp_path/'proposals',workspace=w,engine=ROOT/'engine',file_guard=guard),
      flow=SimpleNamespace(get=lambda id:p,audit=lambda id:{'chain_valid':True}),
      production=SimpleNamespace(overview=lambda id:prod),task_graphs=SimpleNamespace(get=lambda id:g))
    c=Milestone20(st)
    yield c,p,prod,g,w
    c.pool.shutdown(wait=True,cancel_futures=True)

def wait(c,rid,timeout=90):
    started=time.monotonic()
    while time.monotonic()-started<timeout:
        v=c.get(rid)
        if v['state']!='running':return v
        time.sleep(.25)
    pytest.fail('milestone campaign did not finish')

def test_plan_coverage_and_global_integration(kit):
    c,p,prod,g,w=kit
    a=c.create('p-demo')
    assert a['audit_valid'] and a['current'] and a['state']=='planned'
    assert set(a['plan']['impacted_tests'])=={'ledger','format','integration'}
    assert len(a['plan']['inputs'])>=9
    assert c.get(a['id'])['production_release_authorized'] is False
    assert c.handoff(a['id'])['sha256']

def test_exact_input_incremental_explanation_never_auto_certifies(kit):
    c,p,prod,g,w=kit
    a=c.create('p-demo');r=c._load(a['id'])
    r['state']='passed';r['result']={'checks':[{'action':'cpp-project-gate','ok':True}]}
    c._event(r,'finished',{'decision':'Tested'});c._save(r)
    b=c.create('p-demo',previous_id=a['id'])
    assert b['plan']['changed_files']==[]
    assert b['plan']['impacted_tests']==['integration']
    assert b['state']=='planned' and b['result']['checks']==[]
    (w/'cpp_project'/'format.cpp').write_text('// new implementation\n')
    nextplan=c.create('p-demo',previous_id=a['id'])
    assert nextplan['plan']['changed_files']==['cpp_project/format.cpp']
    assert set(nextplan['plan']['impacted_tests'])=={'format','integration'}
    assert not c.get(a['id'])['current']

def test_no_contract_or_bad_graph_blocks(kit):
    c,p,prod,g,w=kit
    prod['contract_digest']=None
    with pytest.raises(MilestoneError):c.create('p-demo')
    prod['contract_digest']='c'*64;g['complete']=False
    with pytest.raises(MilestoneError):c.create('p-demo',graph_id='tg-fake')

def test_native_consent_and_file_drift(kit):
    c,p,prod,g,w=kit
    a=c.create('p-demo')
    with pytest.raises(MilestoneError,match='人工审查'):c.start(a['id'])
    (w/'cpp_project'/'ledger.cpp').write_text('// drift\n')
    with pytest.raises(MilestoneError,match='过期'):c.start(a['id'],trusted=True)
    assert c.get(a['id'])['state']=='planned'

def test_plan_and_result_tampering_detected(kit):
    c,p,prod,g,w=kit
    a=c.create('p-demo');f=c._path(a['id'])
    original=json.loads(f.read_text())
    wrong=copy.deepcopy(original);wrong['plan']['contract_digest']='0'*64
    f.write_text(json.dumps(wrong))
    with pytest.raises(MilestoneError,match='篡改'):c.get(a['id'])
    f.write_text(json.dumps(original));wrong=copy.deepcopy(original)
    wrong['result']['checks']=[{'fake':'approved'}]
    f.write_text(json.dumps(wrong))
    with pytest.raises(MilestoneError,match='不一致'):c.get(a['id'])

def test_gate_failure_fails_closed(kit,monkeypatch):
    c,p,prod,g,w=kit
    def fail(rid,action,path,extra,timeout):
        return {'action':action,'returncode':2,'outcome':'Violated','ok':False,'result_digest':'a'*64,'report':{},'stderr':''}
    monkeypatch.setattr(c,'_run_cmd',fail)
    a=c.create('p-demo');c.start(a['id'],trusted=True)
    r=wait(c,a['id'])
    assert r['state']=='blocked' and r['result']['decision']=='Blocked'
    assert len(r['result']['checks'])==1
    with pytest.raises(MilestoneError,match='只允许执行一次'):c.start(a['id'],trusted=True)

def test_drift_during_verification_prevents_approval(kit,monkeypatch):
    c,p,prod,g,w=kit
    def drift(rid,action,path,extra,timeout):
        (w/'cpp_project'/'test_format.cpp').write_text('tampered')
        return {'action':action,'returncode':0,'outcome':'Bounded','ok':True,'result_digest':'a'*64,'report':{},'stderr':''}
    monkeypatch.setattr(c,'_run_cmd',drift)
    a=c.create('p-demo');c.start(a['id'],trusted=True)
    r=wait(c,a['id'])
    assert r['state']=='blocked' and not r['current']
    assert len(r['result']['checks'])==1

def test_real_axiom_model_and_cpp_project_gate(kit):
    c,p,prod,g,w=kit
    a=c.create('p-demo')
    c.start(a['id'],trusted=True)
    r=wait(c,a['id'],timeout=200)
    assert r['state']=='passed',r['result']
    checks=r['result']['checks']
    assert [x['action'] for x in checks]==['verify','gate','cpp-project-verify','cpp-project-gate']
    assert all(x['ok'] for x in checks)
    assert checks[-1]['outcome']=='Approved'
    assert c.get(a['id'])['production_release_authorized'] is False
    # Real cross-campaign evidence reuse: unchanged unit targets are verified from
    # source/toolchain-bound Axiom P2h cache, while integration runs again.
    b=c.create('p-demo',previous_id=a['id']);c.start(b['id'],trusted=True)
    second=wait(c,b['id'],timeout=200)
    assert second['state']=='passed',second['result']
    report=second['result']['checks'][2]['report']['report']
    assert report['cache_hits']>=2 and report['integration_reexecuted'] is True,report
    assert report['executed_targets']>=1
    # Change just one module: only its test and the always-fresh integration
    # target execute. The unaffected unit target must be evidence-reused.
    src=w/'cpp_project'/'format.cpp'
    src.write_text(src.read_text()+'\n// 2.0 benign evolution\n')
    d=c.create('p-demo',previous_id=b['id'])
    assert d['plan']['impacted_tests']==['format','integration']
    c.start(d['id'],trusted=True)
    evolved=wait(c,d['id'],timeout=200)
    assert evolved['state']=='passed',evolved['result']
    e_report=evolved['result']['checks'][2]['report']['report']
    assert e_report['cache_hits']==1 and e_report['executed_targets']==2,e_report
    assert e_report['integration_reexecuted'] is True
    from milestone20 import Milestone20
    assert Milestone20(c.studio).get(a['id'])['state']=='passed'

def test_http_token_and_scope(kit):
    from http.server import ThreadingHTTPServer
    from urllib.request import Request,urlopen
    from urllib.error import HTTPError
    import threading
    import server
    c,p,prod,g,w=kit
    http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
    http.studio=SimpleNamespace(token='secret-test-token',milestone20=c)
    t=threading.Thread(target=http.serve_forever,daemon=True);t.start()
    base=f'http://127.0.0.1:{http.server_port}'
    def request(path,body=None,token=None):
        data=json.dumps(body).encode() if body is not None else None
        headers={'X-Axiom-Token':token} if token else {}
        if data is not None:headers['Content-Type']='application/json'
        try:
            with urlopen(Request(base+path,data,headers=headers),timeout=5) as f:
                return f.status,json.loads(f.read())
        except HTTPError as e:return e.code,json.loads(e.read())
    try:
        assert request('/api/milestone20/list')[0]==403
        assert request('/api/milestone20/create',{'project_id':'p-demo'})[0]==403
        code,plan=request('/api/milestone20/create',{'project_id':'p-demo'},'secret-test-token')
        assert code==201 and plan['state']=='planned'
        assert request('/api/milestone20/start',{'id':plan['id']},'secret-test-token')[0]==400
        assert request('/api/milestone20/get?id='+plan['id'],token='secret-test-token')[1]['plan']==plan['plan']
        with urlopen(base+'/milestone20.js',timeout=5) as resp:
            assert resp.status==200 and b'milestone20' in resp.read().lower()
    finally:http.shutdown();http.server_close()
