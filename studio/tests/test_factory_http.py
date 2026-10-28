"""V0.5 real loopback API and mandatory authorization checks."""
import json
import sys
import threading
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server

BASE=Path(__file__).resolve().parents[2]

@pytest.fixture
def srv(tmp_path,monkeypatch):
    w=tmp_path/'workspace'/'p';w.mkdir(parents=True)
    for name in ('ledger.ax','project.json','ledger.hpp','ledger.cpp','format.hpp','format.cpp','test_ledger.cpp','test_format.cpp','test_integration.cpp'):
        (w/name).write_bytes((BASE/'workspace'/'cpp_project'/name).read_bytes())
    monkeypatch.setattr(server,'WORKSPACE',tmp_path/'workspace')
    monkeypatch.setattr(server,'ROOT',tmp_path)
    monkeypatch.setattr(server,'EVIDENCE',tmp_path/'.studio-data'/'evidence')
    x=server.create_server(0);t=threading.Thread(target=x.serve_forever,daemon=True);t.start()
    yield x
    x.shutdown();x.server_close();t.join(timeout=4);x.studio.executor.shutdown(wait=True,cancel_futures=True)

def req(srv,path,data=None,authorized=True):
    h={'X-Axiom-Token':srv.studio.token} if authorized else {}
    if data is not None:h['Content-Type']='application/json'
    raw=json.dumps(data,ensure_ascii=False).encode() if data is not None else None
    try:
        with urlopen(Request('http://127.0.0.1:'+str(srv.server_port)+path,
            data=raw,headers=h,method='POST' if raw is not None else 'GET'),timeout=40) as x:
            return x.status,json.loads(x.read())
    except HTTPError as e:return e.code,json.loads(e.read())

def test_authorized_factory_http_and_contract_dag(srv):
    _,p=req(srv,'/api/project/create',{'name':'Production Factory','goal':'具有明确生产契约的 C++ 程序构造',
       'spec':'p/ledger.ax','manifest':'p/project.json'})
    pid=p['id'];_,draft=req(srv,'/api/production/draft?id='+pid)
    reqs=[{**item,'text':'确认 '+item['property']+' 的需求应由当前规格约束'} for item in draft['suggested']]
    assert req(srv,'/api/factory/list?project_id='+pid,authorized=False)[0]==403
    assert req(srv,'/api/production/freeze',{'id':pid,'requirements':reqs,'baseline':p['baseline']})[0]==201
    assert req(srv,'/api/factory/create',{'project_id':pid,'target':'p/test_ledger.cpp'})[0]==400
    status,c=req(srv,'/api/factory/create',{'project_id':pid,'target':'p/ledger.cpp'})
    assert status==201 and len(c['task_dag'])==6
    status,reused=req(srv,'/api/factory/create',{'project_id':pid,'target':'p/ledger.cpp'})
    assert status==201 and reused['id']==c['id']
    assert req(srv,'/api/factory/candidate',{'id':c['id'],'code':'// nope'})[0]==409
    status,done=req(srv,'/api/factory/verify-spec',{'id':c['id']})
    assert status==200 and done['state']=='candidate_pending'
    assert req(srv,'/api/factory/decide',{'id':c['id'],'sha256':'x','confirmation':'approve_test_only'})[0]==409
    assert req(srv,'/api/factory/validate',{'id':c['id'],'trusted':False})[0]==400
    status,events=req(srv,'/api/factory/events?id='+c['id'])
    assert status==200 and events['valid']
    assert req(srv,'/api/meta')[1]['version']=='0.8.0'
