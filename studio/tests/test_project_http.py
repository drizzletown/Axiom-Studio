"""Live loopback HTTP contract tests of the project-centric orchestration API."""
import json,sys,threading,time
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server

@pytest.fixture(scope='module')
def instance():
    srv=server.create_server(0)
    thread=threading.Thread(target=srv.serve_forever,daemon=True);thread.start()
    yield srv
    srv.shutdown();srv.server_close();thread.join(timeout=5)

def call(srv,path,data=None,authorized=True):
    headers={'X-Axiom-Token':srv.studio.token} if authorized else {}
    raw=json.dumps(data).encode() if data is not None else None
    if raw is not None:headers['Content-Type']='application/json'
    req=Request('http://127.0.0.1:'+str(srv.server_port)+path,headers=headers,data=raw,method='POST' if raw else 'GET')
    try:
        with urlopen(req,timeout=40) as f:return f.status,json.loads(f.read())
    except HTTPError as err:return err.code,json.loads(err.read())

def test_project_api_auth(instance):
    assert call(instance,'/api/projects',authorized=False)[0]==403
    assert call(instance,'/api/projects')[0]==200
    assert call(instance,'/api/meta')[1]['architecture']=='workflow-first'

def test_project_http_real_verifier_and_event_chain(instance):
    code,p=call(instance,'/api/project/create',{'name':'HTTP 实际构造项目','goal':'检查模型状态转换与性质','spec':'two_account.ax','manifest':''})
    assert code==201;p_id=p['id']
    assert p['status']=='draft'
    code,p=call(instance,'/api/project/verify-spec',{'id':p_id})
    assert code==200 and p['status']=='spec_ready'
    assert p['last_verification']['steps'][-1]['outcome']=='Approved'
    code,v=call(instance,'/api/project/audit?id='+p_id)
    assert code==200 and v['chain_valid'] and v['events']==3
    code,v=call(instance,'/api/project/events?id='+p_id)
    assert code==200 and v['events'][1]['kind']=='spec_verification_started'

def test_cannot_jump_to_model_or_production_gate(instance):
    code,p=call(instance,'/api/project/create',{'name':'越级阻断案例','goal':'拒绝不经过模型验证的准入','spec':'two_account.ax'})
    assert code==201
    assert call(instance,'/api/project/attach',{'id':p['id'],'candidate_id':'p-'+'a'*22})[0]==409
    assert call(instance,'/api/project/decide',{'id':p['id'],'confirmation':'release-production','candidate_digest':'a'*64})[0]==400

def test_project_fork_and_stale_state(instance):
    _,p=call(instance,'/api/project/create',{'name':'演化原版','goal':'从原版本形成不继承证据的演化分支','spec':'two_account.ax'})
    _,new=call(instance,'/api/project/fork',{'id':p['id'],'name':'演化后版本'})
    assert new['parent_id']==p['id'] and new['revision']==2 and new['status']=='draft'
    assert new['last_verification'] is None and new['decision'] is None
    _,overview=call(instance,'/api/projects')
    assert 'counts' in overview and overview['counts']['total']>=2
