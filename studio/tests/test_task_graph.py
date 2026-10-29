"""1.7 dependency-aware software construction acceptance tests."""
from __future__ import annotations
import json, sys, time, shutil, threading
from pathlib import Path
from urllib.request import urlopen,Request
from urllib.error import HTTPError
import pytest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import server
from task_graph import TaskGraphs,TaskGraphError
from orchestrator import FlowConflict
from test_assembly import prepared


def build(st,pid):
    g=st.task_graphs.create(pid)
    assert g['total']==2
    return g


def test_two_modules_and_idempotent_plan(prepared):
    st,pid,w=prepared
    g=build(st,pid)
    assert g['completed']==0 and g['current']
    assert [x['display_state'] for x in g['tasks']]==['ready','waiting']
    assert g['tasks'][1]['waiting_for']==[g['tasks'][0]['target']]
    assert st.task_graphs.create(pid)['id']==g['id']
    assert len(st.task_graphs.list(pid)['graphs'])==1
    assert g['production_release_authorized'] is False


def test_dependency_validation_rejects_cycle_and_escape(prepared):
    st,pid,_=prepared
    targets=st.assembly.targets(pid)['targets']
    with pytest.raises(TaskGraphError,match='环'):
        st.task_graphs.create(pid,[{'target':targets[0],'depends_on':[targets[1]]},
                                  {'target':targets[1],'depends_on':[targets[0]]}])
    with pytest.raises(TaskGraphError):
        st.task_graphs.create(pid,[{'target':'../../../evil.cpp','depends_on':[]}])
    with pytest.raises(TaskGraphError):
        st.task_graphs.create(pid,[{'target':targets[0],'depends_on':['not-present']}])


def test_safe_serial_activation(prepared):
    st,pid,_=prepared
    g=build(st,pid);first,second=[x['target'] for x in g['tasks']]
    with pytest.raises(TaskGraphError):st.task_graphs.start(g['id'],second)
    opened=st.task_graphs.start(g['id'],first)
    assert opened['active_count']==1 and opened['tasks'][0]['assembly_id']
    assert not opened['tasks'][1]['can_start']
    with pytest.raises(TaskGraphError):st.task_graphs.start(g['id'],second)
    assert st.assembly.get(opened['tasks'][0]['assembly_id'])['action']['id']=='propose'
    assert not st.task_graphs.sync(g['id'])['complete']


def test_project_inputs_drift_fail_closed(prepared):
    st,pid,w=prepared
    g=build(st,pid)
    target=st.proposals.file_guard(g['tasks'][0]['target'])
    target.write_bytes(target.read_bytes()+b'\n// outside modification\n')
    view=st.task_graphs.get(g['id'])
    assert not view['current'] and '外部修改' in view['blocker']
    with pytest.raises(FlowConflict):st.task_graphs.start(g['id'],g['tasks'][0]['target'])


def test_spec_drift_and_test_protection(prepared):
    st,pid,_=prepared
    g=build(st,pid)
    spec=st.proposals.file_guard(st.flow.get(pid)['spec'])
    spec.write_bytes(spec.read_bytes()+b'\n// changed by outside tool\n')
    assert not st.task_graphs.get(g['id'])['current']
    with pytest.raises(FlowConflict):st.task_graphs.sync(g['id'])


def test_test_file_drift_is_detected(prepared):
    st,pid,_=prepared
    g=build(st,pid)
    manifest=st.flow.get(pid)['manifest'];f=Path(manifest).parent/'test_integration.cpp'
    p=st.proposals.file_guard(f.as_posix())
    p.write_bytes(p.read_bytes()+b'\n// changed tests\n')
    assert not st.task_graphs.get(g['id'])['current']


def test_audit_and_plan_tamper_detected(prepared):
    st,pid,_=prepared
    g=build(st,pid)
    f=st.task_graphs.home/(g['id']+'.json')
    r=json.loads(f.read_text());r['nodes'][g['tasks'][1]['target']]['state']='passed'
    f.write_text(json.dumps(r))
    with pytest.raises(TaskGraphError,match='审计'):st.task_graphs.get(g['id'])
    with pytest.raises(TaskGraphError):st.task_graphs.sync(g['id'])


def test_no_contract_no_schedule(prepared):
    st,_,_=prepared
    project=st.journey.start('cpp-ledger','No contract graph','这个项目并没有人工冻结规则')['project']
    with pytest.raises(FlowConflict):st.task_graphs.create(project['id'])


def test_candidate_staging_does_not_auto_run(prepared):
    st,pid,_=prepared
    g=build(st,pid);first=g['tasks'][0]['target']
    session=st.task_graphs.start(g['id'],first)['tasks'][0]['assembly_id']
    current=st.proposals.file_guard(first)
    old=current.read_bytes()
    work=st.assembly.candidate(session,code=old.decode()+'\n// staged only\n')
    assert work['action']['id']=='review'
    assert current.read_bytes()==old
    assert st.task_graphs.sync(g['id'])['tasks'][0]['state']=='active'


def test_handoff_and_restart(prepared):
    st,pid,_=prepared
    g=build(st,pid)
    h=st.task_graphs.handoff(g['id'])
    from proposals import sha
    from workorders import canonical
    assert sha(canonical(h['report']))==h['sha256']
    assert TaskGraphs(st).get(g['id'])['head']==g['head']
    assert h['report']['status']['production_release_authorized'] is False


def test_http_auth_and_graph_dispatch(prepared):
    st,pid,_=prepared
    srv=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
    srv.studio=st
    worker=threading.Thread(target=srv.serve_forever,daemon=True);worker.start()
    root=f'http://127.0.0.1:{srv.server_port}'
    try:
        with pytest.raises(HTTPError) as err:urlopen(root+'/api/task-graph/list')
        assert err.value.code==403
        def send(path,payload):
            req=Request(root+path,data=json.dumps(payload).encode(),headers={'X-Axiom-Token':st.token,'Content-Type':'application/json'})
            return json.load(urlopen(req,timeout=20))
        g=send('/api/task-graph/create',{'project_id':pid})
        assert g['total']==2
        result=json.load(urlopen(Request(root+'/api/task-graph/get?id='+g['id'],headers={'X-Axiom-Token':st.token})))
        assert result['id']==g['id']
        with pytest.raises(HTTPError) as err:send('/api/task-graph/start',{'id':g['id'],'target':'../../unsafe.cpp'})
        assert err.value.code==400
    finally:srv.shutdown();srv.server_close();worker.join(timeout=3)


def test_real_cpp_check_passes_first_module_then_unblocks_second(prepared):
    st,pid,_=prepared
    g=build(st,pid);first,second=[x['target'] for x in g['tasks']]
    session=st.task_graphs.start(g['id'],first)['tasks'][0]['assembly_id']
    original=st.proposals.file_guard(first).read_text()
    proposal=st.assembly.candidate(session,code=original+'\n// Axiom 1.7 validated candidate\n')
    st.assembly.review(session,proposal['candidate_digest'],True)
    st.assembly.apply(session,'human_authorized_apply')
    st.assembly.verify(session,True)
    deadline=time.monotonic()+100
    while time.monotonic()<deadline:
        res=st.assembly.poll(session)
        if res['state']!='validating':break
        time.sleep(.2)
    assert res['state']=='passed',res
    after=st.task_graphs.sync(g['id'])
    assert after['completed']==1 and after['current'] and after['tasks'][1]['can_start']
    assert after['tasks'][0]['accepted_sha256']==proposal['candidate_digest']
    next_state=st.task_graphs.start(g['id'],second)
    assert next_state['active_count']==1 and next_state['completed']==1
    assert not next_state['complete'] and not next_state['production_release_authorized']
