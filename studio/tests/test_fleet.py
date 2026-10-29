"""1.8 parallel preparation + review-gated integration acceptance tests."""
import json
import sys
import threading
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
from test_assembly import prepared
import server
from fleet import FleetError,ProductionFleet
from orchestrator import FlowConflict


def setup(st,pid,parallel=True):
    targets=st.assembly.targets(pid)['targets']
    tasks=[{'target':t,'depends_on':[]} for t in targets] if parallel else None
    graph=st.task_graphs.create(pid,tasks)
    return graph, st.fleet.prepare(graph['id'], parallelism=2)


def test_parallel_packet_and_restart(prepared):
    st,pid,_=prepared
    graph,fleet=setup(st,pid)
    assert len(fleet['packets'])==2 and fleet['current']
    assert 'Frozen contract digest' in fleet['packets'][0]['prompt']
    assert all(p['state']=='ready' for p in fleet['packets'])
    assert st.fleet.prepare(graph['id'])['head']==fleet['head']
    assert ProductionFleet(st).get(graph['id'])['head']==fleet['head']
    assert fleet['production_release_authorized'] is False


def test_stage_no_exec_and_promote_review(prepared):
    st,pid,w=prepared
    graph,fleet=setup(st,pid)
    a=fleet['packets'][0];target=a['target']
    before=st.proposals.file_guard(target).read_text()
    draft=st.fleet.stage(graph['id'],target,before+'\n// proposed in parallel preparation\n',a['packet_digest'])
    assert st.proposals.file_guard(target).read_text()==before
    digest=next(x['candidate_sha256'] for x in draft['packets'] if x['target']==target)
    promoted=st.fleet.promote(graph['id'],target,digest)
    assert promoted['requires_human_review'] and not promoted['native_execution_authorized']
    assert promoted['assembly']['action']['id']=='review'
    assert st.proposals.file_guard(target).read_text()==before
    with pytest.raises(Exception):st.fleet.promote(graph['id'],target,digest)


def test_no_approval_no_execution(prepared):
    st,pid,w=prepared
    graph,fleet=setup(st,pid)
    t=fleet['packets'][0];original=st.proposals.file_guard(t['target']).read_text()
    staged=st.fleet.stage(graph['id'],t['target'],original+'\n// staged only\n',t['packet_digest'])
    sha=staged['packets'][0]['candidate_sha256']
    st.fleet.promote(graph['id'],t['target'],sha)
    assert st.jobs=={}
    assert st.proposals.file_guard(t['target']).read_text()==original


def test_packet_input_guard(prepared):
    st,pid,w=prepared
    graph,fleet=setup(st,pid)
    t=fleet['packets'][0]
    with pytest.raises(FleetError):st.fleet.stage(graph['id'],t['target'],'int main(){}','0'*64)
    p=st.proposals.file_guard(st.flow.get(pid)['spec'])
    p.write_text(p.read_text()+'\n// externally changed\n')
    with pytest.raises(FlowConflict):st.fleet.stage(graph['id'],t['target'],'code',t['packet_digest'])
    assert not st.fleet.get(graph['id'])['current']


def test_audit_and_draft_tamper(prepared):
    st,pid,_=prepared
    graph,fleet=setup(st,pid)
    t=fleet['packets'][0]
    st.fleet.stage(graph['id'],t['target'],'// harmless candidate',t['packet_digest'])
    f=st.fleet.home/'records'/(graph['id']+'.json')
    record=json.loads(f.read_text());record['packets'][t['target']]['prompt']='forged'
    f.write_text(json.dumps(record))
    with pytest.raises(FleetError,match='篡改|无效'):st.fleet.get(graph['id'])


def test_object_tamper(prepared):
    st,pid,_=prepared
    graph,fleet=setup(st,pid)
    t=fleet['packets'][0]
    staged=st.fleet.stage(graph['id'],t['target'],'// code',t['packet_digest'])
    sha=next(x['candidate_sha256'] for x in staged['packets'] if x['target']==t['target'])
    (st.fleet.home/'objects'/sha).write_text('modified')
    with pytest.raises(FleetError,match='篡改'):st.fleet.get(graph['id'])


def test_explicit_rebase_ack_required(prepared):
    st,pid,_=prepared
    targets=st.assembly.targets(pid)['targets']
    graph=st.task_graphs.create(pid,[{'target':targets[0],'depends_on':[]},
                                       {'target':targets[1],'depends_on':[targets[0]]}])
    fleet=st.fleet.prepare(graph['id'],2)
    second=fleet['packets'][1]
    original=st.proposals.file_guard(second['target']).read_text()
    staged=st.fleet.stage(graph['id'],second['target'],original+'\n// ready for later integration\n',second['packet_digest'])
    digest=next(x['candidate_sha256'] for x in staged['packets'] if x['target']==second['target'])
    with pytest.raises(FleetError):st.fleet.promote(graph['id'],second['target'],digest,True)
    assert st.proposals.file_guard(second['target']).read_text()==original


def test_parallel_workers_are_genuine(prepared,monkeypatch):
    st,pid,_=prepared
    original=st.fleet._packet
    meeting=threading.Barrier(2,timeout=20)
    names=[]
    def blocking(*args):
        names.append(threading.current_thread().name)
        meeting.wait()
        return original(*args)
    monkeypatch.setattr(st.fleet,'_packet',blocking)
    graph,fleet=setup(st,pid)
    assert len(names)==2 and len(set(names))==2 and len(fleet['packets'])==2


def test_http_auth_and_boundaries(prepared):
    st,pid,_=prepared
    srv=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
    srv.studio=st
    threading.Thread(target=srv.serve_forever,daemon=True).start()
    root='http://127.0.0.1:'+str(srv.server_port)
    def req(path,obj=None,auth=True):
        headers={'Content-Type':'application/json'}
        if auth:headers['X-Axiom-Token']=st.token
        r=Request(root+path,data=json.dumps(obj).encode() if obj is not None else None,headers=headers)
        return json.load(urlopen(r,timeout=30))
    try:
        with pytest.raises(HTTPError) as bad:req('/api/fleet/get?id=fake',auth=False)
        assert bad.value.code==403
        g=st.task_graphs.create(pid,[{'target':t,'depends_on':[]} for t in st.assembly.targets(pid)['targets']])
        f=req('/api/fleet/prepare',{'id':g['id'],'parallelism':2})
        assert len(f['packets'])==2
        assert req('/api/fleet/get?id='+g['id'])['audit_valid']
        page=urlopen(root+'/task_graph.js',timeout=15);assert page.status==200 and b'renderFleet' in page.read()
        assert req('/api/fleet/handoff?id='+g['id'])['report']['view']['production_release_authorized'] is False
    finally:srv.shutdown();srv.server_close()


def test_feedback_requires_real_failure(prepared):
    st,pid,_=prepared
    graph,fleet=setup(st,pid)
    target=fleet['packets'][0]['target']
    with pytest.raises(FleetError):st.fleet.feedback(graph['id'],target)
    st.task_graphs.start(graph['id'],target)
    with pytest.raises(FleetError):st.fleet.feedback(graph['id'],target)


def test_real_cpp_dependency_rebase_with_human_ack(prepared):
    """First module really passes Gate, then precomputed downstream draft is integrated."""
    import time
    st,pid,_=prepared
    targets=st.assembly.targets(pid)['targets']
    graph=st.task_graphs.create(pid,[{'target':targets[0],'depends_on':[]},
                                       {'target':targets[1],'depends_on':[targets[0]]}])
    fleet=st.fleet.prepare(graph['id'],parallelism=2)
    drafts={}
    for packet in fleet['packets']:
        target=packet['target'];original=st.proposals.file_guard(target).read_text()
        staged=st.fleet.stage(graph['id'],target,original+'\n// reviewed v1.8 construction draft\n',packet['packet_digest'])
        drafts[target]=next(p['candidate_sha256'] for p in staged['packets'] if p['target']==target)
    first=targets[0]
    imported=st.fleet.promote(graph['id'],first,drafts[first])
    session=imported['assembly']
    assert session['action']['id']=='review'
    st.assembly.review(session['id'],session['candidate_digest'],True)
    st.assembly.apply(session['id'],'human_authorized_apply')
    st.assembly.verify(session['id'],True)
    end=time.monotonic()+140
    while time.monotonic()<end:
        step=st.assembly.poll(session['id'])
        if step['state']!='validating':break
        time.sleep(0.25)
    assert step['state']=='passed',step
    synced=st.task_graphs.sync(graph['id'])
    assert synced['completed']==1
    second=targets[1]
    assert st.fleet.get(graph['id'])['packets'][1]['requires_rebase_ack']
    with pytest.raises(FleetError,match='审查依赖'):
        st.fleet.promote(graph['id'],second,drafts[second])
    imported2=st.fleet.promote(graph['id'],second,drafts[second],True)
    assert imported2['assembly']['action']['id']=='review'
    assert st.proposals.file_guard(second).read_text().find('reviewed v1.8')<0
