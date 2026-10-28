"""V0.6 real loopback API contract checks; never claims native validation from mocks."""
import json,sys,threading
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
BASE=Path(__file__).resolve().parents[2]
FILES=('ledger.ax','project.json','ledger.hpp','ledger.cpp','format.hpp','format.cpp',
       'test_ledger.cpp','test_format.cpp','test_integration.cpp')

@pytest.fixture
def srv(tmp_path,monkeypatch):
    d=tmp_path/'workspace'/'p';d.mkdir(parents=True)
    for n in FILES:(d/n).write_bytes((BASE/'workspace'/'cpp_project'/n).read_bytes())
    monkeypatch.setattr(server,'ROOT',tmp_path)
    monkeypatch.setattr(server,'WORKSPACE',tmp_path/'workspace')
    monkeypatch.setattr(server,'EVIDENCE',tmp_path/'.studio-data'/'evidence')
    x=server.create_server(0);th=threading.Thread(target=x.serve_forever,daemon=True);th.start()
    yield x
    x.shutdown();x.server_close();th.join(timeout=4);x.studio.executor.shutdown(wait=True,cancel_futures=True)

def req(s,path,data=None,auth=True):
    headers={'X-Axiom-Token':s.studio.token} if auth else {}
    if data is not None:headers['Content-Type']='application/json'
    raw=json.dumps(data).encode() if data is not None else None
    try:
        with urlopen(Request(f'http://127.0.0.1:{s.server_port}'+path,headers=headers,data=raw,
                method='POST' if data is not None else 'GET'),timeout=20) as r:
            return r.status,json.loads(r.read())
    except HTTPError as r:return r.code,json.loads(r.read())

def test_http_guard_and_production_contract(srv):
    _,p=req(srv,'/api/project/create',{'name':'multi','goal':'规范控制与候选比较',
                                  'spec':'p/ledger.ax','manifest':'p/project.json'})
    pid=p['id'];_,draft=req(srv,'/api/production/draft?id='+pid)
    requirements=[{**x,'text':'确保 '+x['property']+' 的设计约束满足'} for x in draft['suggested']]
    req(srv,'/api/production/freeze',{'id':pid,'baseline':p['baseline'],'requirements':requirements})
    assert req(srv,'/api/batch/create',{'project_id':pid,'targets':['p/ledger.cpp','p/format.cpp']})[0]==409
    assert req(srv,'/api/batch/list?project_id='+pid,auth=False)[0]==403
    assert req(srv,'/api/project/verify-spec',{'id':pid})[0]==200
    code,b=req(srv,'/api/batch/create',{'project_id':pid,'targets':['p/ledger.cpp','p/format.cpp']})
    assert code==201 and b['state']=='staging'
    assert req(srv,'/api/factory/create',{'project_id':pid,'target':'p/ledger.cpp'})[0]==409
    assert req(srv,'/api/batch/stage',{'id':b['id'],'name':'bad','replacements':{
        'ledger.cpp':'x','test_ledger.cpp':'y'}})[0]==400
    assert req(srv,'/api/batch/evaluate',{'id':b['id'],'option_id':'x','trusted':False})[0]==400
    assert req(srv,'/api/batch/decide',{'id':b['id'],'digest':'x','confirmation':'human_approve_test_only'})[0]==409
    assert req(srv,'/api/batch/audit?id='+b['id'])[1]['valid'] is True
    assert req(srv,'/api/meta')[1]['version']=='0.8.0'
