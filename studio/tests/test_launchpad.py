"""V0.7 verified onboarding and project handoff. Includes real Axiom model Gate."""
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import threading
import urllib.request
import urllib.error
import zipfile

import pytest

STUDIO_DIR=Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:sys.path.insert(0,str(STUDIO_DIR))
import server as mod
from orchestrator import FlowConflict
from launchpad import LaunchError

@pytest.fixture
def isolated(tmp_path, monkeypatch):
    work=tmp_path/'workspace';work.mkdir()
    monkeypatch.setattr(mod,'ROOT',tmp_path)
    monkeypatch.setattr(mod,'WORKSPACE',work)
    monkeypatch.setattr(mod,'EVIDENCE',tmp_path/'.studio-data'/'evidence')
    studio=mod.Studio()
    yield studio
    studio.executor.shutdown(wait=False,cancel_futures=True)


def test_templates_and_create_no_execute(isolated):
    studio=isolated
    assert len(studio.launchpad.templates()['templates'])==3
    created=studio.launchpad.create('cpp-ledger','actual-work','Ledger project','确保守恒性质经过独立验证')
    p=created['project']
    assert p['manifest']=='projects/actual-work/project.json'
    assert p['status']=='draft'
    assert all((studio.flow.workspace/f).exists() for f in created['created_files'])
    assert not studio.recent() # no native build or execution on creation
    assert not studio.flow.get(p['id'])['stale']
    assert studio.launchpad.queue()['items'][0]['next_action']=='verify'
    with pytest.raises(FlowConflict):
        studio.launchpad.create('cpp-ledger','actual-work','Ledger project','重复项目应被禁止')
    assert (studio.flow.workspace/'projects/actual-work/ledger.cpp').exists()


@pytest.mark.parametrize('slug', ['../escape','a/../../out','Aaa','a','abc\\test','abc def'])
def test_reject_bad_slug(isolated,slug):
    with pytest.raises(LaunchError):
        isolated.launchpad.create('model-toggle',slug,'Bad project','应拒绝非法目录名')


def test_failed_invalid_goal_creates_no_files(isolated):
    with pytest.raises(LaunchError):
        isolated.launchpad.create('model-ledger','valid-slug','Bad','no')
    assert not (isolated.flow.workspace/'projects/valid-slug').exists()


def test_real_model_evidence_and_workflow(isolated):
    studio=isolated
    r=studio.launchpad.create('model-toggle','switch-fsm','Switch model','验证开关行为符合约束')
    pid=r['project']['id']
    verify=studio.flow.verify_spec(pid)
    assert verify['last_verification']['passed'] is True,verify['last_verification']
    assert verify['status']=='spec_ready'
    item=next(x for x in studio.launchpad.queue()['items'] if x['project_id']==pid)
    assert item['next_action']=='freeze'
    draft=studio.production.draft(pid)
    assert draft['suggested']
    requirements=[{**v,'text':'确认开关状态在全部可达状态中是合法布尔值'} for v in draft['suggested']]
    contract=studio.production.freeze(pid,requirements,verify['baseline'])
    assert contract['digest'].startswith('sha256:')
    packet=studio.production.task_packet(pid)
    assert packet['packet']['contract_digest']==contract['digest']
    zipraw,_=studio.launchpad.export(pid)
    with zipfile.ZipFile(io.BytesIO(zipraw)) as z:
        project=json.loads(z.read('handoff/project.json'))
        meta=json.loads(z.read('handoff/SHA256.json'))
        assert project['construction_task']['digest']==packet['digest']
        assert project['production']['contract']['digest']==contract['digest']
        assert project['workflow_audit']['chain_valid'] is True
        assert 'workspace/projects/switch-fsm/toggle.ax' in meta['files']
        assert not any('.studio-data' in x or 'key' in x for x in z.namelist())
        for name,sha in meta['files'].items():assert hashlib.sha256(z.read(name)).hexdigest()==sha
        assert project['production']['eligible_for_live_recheck'] is False
        assert 'HUMAN_ACCEPTANCE_AND_CPP_GATE_REQUIRED' in project['production']['blockers']
    assert studio.launchpad.queue()['items'][0]['next_action']=='task'
    # Mutation invalidates original model evidence and contract: no hidden reuse.
    spec=studio.flow.workspace/'projects/switch-fsm/toggle.ax'
    spec.write_text(spec.read_text()+'\n// changed\n')
    item=studio.launchpad.queue()['items'][0]
    assert item['next_action']=='fork'
    zipraw,_=studio.launchpad.export(pid)
    with zipfile.ZipFile(io.BytesIO(zipraw)) as z:
        project=json.loads(z.read('handoff/project.json'))
        assert project['project']['stale'] is True
        assert project['construction_task'] is None


def test_export_cpp_includes_all_files_and_no_evidence(isolated):
    studio=isolated
    p=studio.launchpad.create('cpp-ledger','exchange','Exchange','验证多文件实现行为')['project']
    result,_=studio.launchpad.export(p['id'])
    with zipfile.ZipFile(io.BytesIO(result)) as z:
        names=z.namelist()
        assert 'workspace/projects/exchange/test_integration.cpp' in names
        assert 'workspace/projects/exchange/ledger.cpp' in names
        assert 'workspace/projects/exchange/project.json' in names
        assert 'handoff/SHA256.json' in names
        assert not any(x.endswith('.sqlite3') or 'private' in x for x in names)


def test_http_authorization_and_launch(tmp_path,monkeypatch):
    root=tmp_path;work=root/'workspace';work.mkdir()
    monkeypatch.setattr(mod,'ROOT',root)
    monkeypatch.setattr(mod,'WORKSPACE',work)
    monkeypatch.setattr(mod,'EVIDENCE',root/'.studio-data'/'evidence')
    srv=mod.create_server(port=0)
    t=threading.Thread(target=srv.serve_forever,daemon=True);t.start()
    base=f'http://127.0.0.1:{srv.server_port}'
    def call(path,data=None,token=True):
        headers={}
        if token:headers['X-Axiom-Token']=srv.studio.token
        if data is not None:headers['Content-Type']='application/json';data=json.dumps(data).encode()
        req=urllib.request.Request(base+path,data=data,headers=headers)
        return urllib.request.urlopen(req,timeout=8)
    try:
        with pytest.raises(urllib.error.HTTPError) as e:call('/api/launch/queue',token=False)
        assert e.value.code==403
        with call('/api/launch/templates') as res:
            assert len(json.load(res)['templates'])==3
        with call('/api/launch/create',{'template':'model-ledger','slug':'live-init','name':'Live init',
                    'goal':'验证账户守恒模型'}) as res:
            created=json.load(res)
        pid=created['project']['id']
        with call('/api/launch/queue') as res:
            assert json.load(res)['items'][0]['next_action']=='verify'
        with call('/api/launch/export?id='+pid) as res:
            assert res.headers['Content-Type']=='application/zip'
            with zipfile.ZipFile(io.BytesIO(res.read())) as z:
                assert 'handoff/project.json' in z.namelist()
        with pytest.raises(urllib.error.HTTPError) as e:call('/api/launch/export?id='+pid,token=False)
        assert e.value.code==403
        with pytest.raises(urllib.error.HTTPError) as e:call('/api/launch/create',{'template':'model-toggle',
                    'slug':'../bad','name':'Bad','goal':'不可越过目录限制'})
        assert e.value.code==400
        with call('/launchpad.js') as res:assert b'loadLaunchQueue' in res.read()
    finally:
        srv.shutdown();srv.server_close();t.join(3)
        srv.studio.executor.shutdown(wait=False,cancel_futures=True)


def test_explicit_import_real_existing_project_and_source_unchanged(isolated,tmp_path):
    src=tmp_path/'external';src.mkdir()
    template=STUDIO_DIR/'templates'/'cpp-ledger'
    for entry in template.iterdir():(src/entry.name).write_bytes(entry.read_bytes())
    before={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in src.iterdir()}
    result=isolated.launchpad.import_existing(src,'existing-app','Existing app',
        '将原有源代码导入验证工作流','ledger.ax','project.json')
    assert result['project']['manifest']=='projects/existing-app/project.json'
    assert result['original_untouched'] is True
    assert before=={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in src.iterdir()}
    assert len(result['created_files'])==9
    with pytest.raises(FlowConflict):
        isolated.launchpad.import_existing(src,'existing-app','Existing app','再次导入同样项目','ledger.ax','project.json')


def test_import_rejects_unlisted_outside_and_symlinks(isolated,tmp_path):
    src=tmp_path/'danger';src.mkdir()
    (src/'app.ax').write_bytes((STUDIO_DIR/'templates'/'model-toggle'/'toggle.ax').read_bytes())
    (src/'outside.ax').symlink_to(src/'app.ax')
    with pytest.raises(LaunchError):
        isolated.launchpad.import_existing(src,'danger-app','Danger app','检查符号链接越界','outside.ax')
    with pytest.raises(LaunchError):
        isolated.launchpad.import_existing(src,'danger-app','Danger app','检查绝对路径绕过','/etc/passwd')
    assert not (isolated.flow.workspace/'projects/danger-app').exists()
