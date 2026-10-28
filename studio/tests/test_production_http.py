"""Production protocol is exercised through its real local HTTP boundary."""
import json
import sys
import threading
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server

@pytest.fixture
def instance(tmp_path,monkeypatch):
    w=tmp_path/'workspace'/'p';w.mkdir(parents=True)
    for name in ('ledger.ax','project.json'):
        (w/name).write_bytes((Path(__file__).resolve().parents[2]/'workspace'/'cpp_project'/name).read_bytes())
    monkeypatch.setattr(server,'WORKSPACE',tmp_path/'workspace')
    monkeypatch.setattr(server,'ROOT',tmp_path)
    monkeypatch.setattr(server,'EVIDENCE',tmp_path/'.studio-data'/'evidence')
    srv=server.create_server(0)
    t=threading.Thread(target=srv.serve_forever,daemon=True);t.start()
    yield srv
    srv.shutdown();srv.server_close();t.join(timeout=3)

def call(srv,path,data=None,token=True):
    headers={'X-Axiom-Token':srv.studio.token} if token else {}
    raw=json.dumps(data,ensure_ascii=False).encode() if data is not None else None
    if raw is not None:headers['Content-Type']='application/json'
    try:
        with urlopen(Request(f'http://127.0.0.1:{srv.server_port}'+path,
                             headers=headers,data=raw,method='POST' if raw else 'GET'),timeout=35) as x:
            return x.status,json.loads(x.read())
    except HTTPError as x:return x.code,json.loads(x.read())

def test_real_http_contract_and_task(instance):
    status,created=call(instance,'/api/project/create',{'name':'Workflow Production','goal':'软件需求通过形式性质进行检查并形成受保护链','spec':'p/ledger.ax','manifest':'p/project.json'})
    assert status==201;pid=created['id']
    assert call(instance,'/api/production/draft?id='+pid,token=False)[0]==403
    assert call(instance,'/api/production/status?id='+pid)[1]['blockers']
    status,draft=call(instance,'/api/production/draft?id='+pid)
    assert status==200 and len(draft['suggested'])==2
    requirements=[{**v,'text':'对 '+v['property']+' 建立可审查且可验证的行为需求'} for v in draft['suggested']]
    status,contract=call(instance,'/api/production/freeze',{'id':pid,'requirements':requirements,'baseline':created['baseline']})
    assert status==201
    assert call(instance,'/api/production/freeze',{'id':pid,'requirements':requirements})[0]==409
    status,packet=call(instance,'/api/production/task?id='+pid)
    assert status==200 and packet['packet']['contract_digest']==contract['digest']
    graph=call(instance,'/api/production/graph?id='+pid)[1]
    assert any(x['kind']=='mapped_by_human' for x in graph['edges'])
    assert call(instance,'/api/production/passport',{'id':pid,'confirmation':'issue_test_only',
                  'contract_digest':contract['digest']})[0]==409
    assert call(instance,'/api/production/passports?id='+pid)[1]['passports']==[]
    assert call(instance,'/api/meta')[1]['version']=='0.8.0'
