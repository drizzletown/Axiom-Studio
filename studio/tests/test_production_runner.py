"""V0.8 batch production, fault injection, restart recovery, API and real engine."""
from __future__ import annotations
import json
import hashlib
import io
import zipfile
import sqlite3
from pathlib import Path
import sys
import threading
import urllib.error
import urllib.request
import pytest

STUDIO=Path(__file__).resolve().parents[1]
if str(STUDIO) not in sys.path:sys.path.insert(0,str(STUDIO))
import server as mod
from production_runner import RunnerError, ProductionRunner

@pytest.fixture
def env(tmp_path,monkeypatch):
    work=tmp_path/'workspace';work.mkdir()
    monkeypatch.setattr(mod,'ROOT',tmp_path)
    monkeypatch.setattr(mod,'WORKSPACE',work)
    monkeypatch.setattr(mod,'EVIDENCE',tmp_path/'.studio-data'/'evidence')
    studio=mod.Studio()
    yield studio
    studio.executor.shutdown(wait=False,cancel_futures=True)
    if studio.production_runner.worker:studio.production_runner.worker.join(20)


def project(studio,slug,template='model-toggle'):
    return studio.launchpad.create(template,slug,slug,'安全模型验证不允许绕过质量准入')['project']


def test_safe_batch_real_model_engine(env):
    a=project(env,'abc')
    b=project(env,'def','model-ledger')
    run=env.production_runner.create([a['id'],b['id']])
    result=env.production_runner.execute(run['id'])
    assert result['status']=='finished',result
    assert [item['status'] for item in result['items']]==['passed','passed']
    assert result['result']['cpp_executed'] is False
    assert result['result']['release_approved'] is False
    assert all(env.flow.get(x['id'])['effective_status']=='spec_ready' for x in (a,b))
    assert env.production_runner.report(run['id'])['next_steps'][0]['action'].startswith('人工核对')


def test_two_phase_no_execution_on_plan(env):
    p=project(env,'xyz')
    record=env.production_runner.create([p['id']]);assert record['status']=='queued'
    assert env.flow.get(p['id'])['status']=='draft'
    with pytest.raises(RunnerError):env.production_runner.create([p['id']])
    assert not list((env.flow.evidence_root).glob('**/*.sqlite3'))


def test_refuse_native_and_human_work(env):
    p=project(env,'cpp','cpp-ledger')
    record=env.production_runner.create([p['id']])
    assert env.production_runner.execute(record['id'])['items'][0]['status']=='passed'
    assert env.flow.get(p['id'])['status']=='spec_ready'
    with pytest.raises(RunnerError):env.production_runner.create([p['id']])
    assert not (env.flow.workspace/'projects/cpp/build').exists()


def test_stale_after_plan_blocks_without_evidence(env):
    p=project(env,'stale')
    run=env.production_runner.create([p['id']])
    spec=env.flow.workspace/p['spec'];spec.write_text(spec.read_text()+'\n// change\n')
    result=env.production_runner.execute(run['id'])
    assert result['status']=='needs_attention'
    assert result['items'][0]['status']=='stale'
    assert env.flow.get(p['id'])['effective_status']=='stale'
    with pytest.raises(RunnerError):env.production_runner.retry(run['id'])


def test_failure_then_explicit_new_retry(env,monkeypatch):
    p=project(env,'retry')
    original=env.flow.verify_spec
    def fail_once(pid):
        monkeypatch.setattr(env.flow,'verify_spec',original)
        raise RuntimeError('simulated verification crash')
    monkeypatch.setattr(env.flow,'verify_spec',fail_once)
    run=env.production_runner.create([p['id']]);first=env.production_runner.execute(run['id'])
    assert first['items'][0]['status']=='failed'
    new=env.production_runner.retry(run['id']);assert new['id']!=run['id']
    assert env.production_runner.execute(new['id'])['items'][0]['status']=='passed'
    assert env.production_runner.get(run['id'])['items'][0]['status']=='failed'
    with pytest.raises(RunnerError):env.production_runner.retry(new['id'])


def test_reject_duplicate_projects_and_invalid_run(env):
    p=project(env,'dupe')
    with pytest.raises(RunnerError):env.production_runner.create([p['id'],p['id']])
    with pytest.raises(RunnerError):env.production_runner.get('../evil')
    with pytest.raises(RunnerError):env.production_runner.create(['wf-not-found'])


def test_crash_restart_recovers_incomplete_fail_closed(env):
    p=project(env,'recover')
    run=env.production_runner.create([p['id']])
    # Simulate process death after original orchestrator entered checking.
    with env.flow._connect() as cx:
        env.flow._write(cx,p['id'],status='checking')
    with sqlite3.connect(env.production_runner.db) as cx:
        cx.execute("UPDATE runs SET status='running' WHERE id=?",(run['id'],))
        cx.execute("UPDATE items SET status='running' WHERE run_id=?",(run['id'],))
    fresh=ProductionRunner(env,env.production_runner.db)
    assert fresh.get(run['id'])['status']=='interrupted'
    assert fresh.get(run['id'])['items'][0]['status']=='interrupted'
    current=env.flow.get(p['id'])
    assert current['status']=='spec_blocked'
    assert current['last_verification']['passed'] is False
    assert current['last_verification']['steps'][0]['outcome']=='Unknown'
    new=fresh.retry(run['id'])
    assert fresh.execute(new['id'])['items'][0]['status']=='passed'


def test_model_fail_is_blocked(env):
    p=project(env,'invalid')
    spec=env.flow.workspace/p['spec']
    source=spec.read_text()
    assert 'always' in source
    # Change property in-place before planning, using an expression that is always false.
    import re
    spec.write_text(re.sub(r'(?m)(property\s+\w+\s*\{\s*always\s+)[^}]+',r'\g<1>false ',source))
    # Create new flow because original baseline was frozen at create.
    q=env.flow.create('Invalid state','验证模型无法通过时必须阻断',p['spec'])
    result=env.production_runner.execute(env.production_runner.create([q['id']])['id'])
    assert result['status']=='needs_attention'
    assert result['items'][0]['status']=='blocked'
    assert env.flow.get(q['id'])['status']=='spec_blocked'


def test_http_authorization_and_model_batch(env,monkeypatch):
    # Server attaches to its own Studio instance, using the same isolated environment.
    srv=mod.create_server(port=0)
    th=threading.Thread(target=srv.serve_forever,daemon=True);th.start()
    base=f'http://127.0.0.1:{srv.server_port}'
    def call(path,obj=None,auth=True):
        headers={'Content-Type':'application/json'}
        if auth:headers['X-Axiom-Token']=srv.studio.token
        data=json.dumps(obj).encode() if obj is not None else None
        req=urllib.request.Request(base+path,data=data,headers=headers)
        with urllib.request.urlopen(req,timeout=15) as response:return json.load(response)
    try:
        p=project(srv.studio,'httpspec')
        with pytest.raises(urllib.error.HTTPError) as e:call('/api/runner/list',auth=False)
        assert e.value.code==403
        planned=call('/api/runner/plan',{'project_ids':[p['id']]})
        assert planned['status']=='queued'
        call('/api/runner/start',{'id':planned['id']})
        worker=srv.studio.production_runner.worker
        worker.join(35)
        assert not worker.is_alive()
        fetched=call('/api/runner/get?id='+planned['id'])
        assert fetched['items'][0]['status']=='passed',fetched
        assert call('/api/runner/list')['runs'][0]['id']==planned['id']
    finally:
        srv.shutdown();srv.server_close();th.join(5)
        srv.studio.executor.shutdown(wait=False,cancel_futures=True)


def test_batch_export_contains_only_passed_and_sha256(env):
    p=project(env,'package')
    run=env.production_runner.create([p['id']])
    with pytest.raises(RunnerError):env.production_runner.export(run['id'])
    result=env.production_runner.execute(run['id'])
    assert result['status']=='finished'
    raw,_=env.production_runner.export(run['id'])
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        digests=json.loads(z.read('SHA256.json'))
        assert 'report.json' in digests['files']
        assert any(k.startswith('projects/') for k in digests['files'])
        for name,sha in digests['files'].items():assert hashlib.sha256(z.read(name)).hexdigest()==sha
        assert not any('private' in name or 'key' in name for name in z.namelist())
        nested=next(k for k in z.namelist() if k.startswith('projects/'))
        with zipfile.ZipFile(io.BytesIO(z.read(nested))) as child:
            assert 'handoff/project.json' in child.namelist()
