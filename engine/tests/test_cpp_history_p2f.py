"""P2f regression: native threading, linearizability, scoped evidence, invalidation."""
from __future__ import annotations
from pathlib import Path
import copy
import pytest
from axiom.cpp_history import parse_history,linearizable,trials,verify_cpp_history, HARNESS
from axiom.history_store import record_history,history_gate
from axiom.interleaving import load_interleaving,verify_interleaving
from axiom.interleaving_store import record_interleaving
from axiom.checker import verify
from axiom.store import Workspace
from axiom.sandbox import available
from axiom.lang import AxError
from axiom.audit import audit_workspace

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def models_bound():return load_interleaving(ROOT/'examples/interleaving/product_safe.json')

def entry(thread,slot,op,desired,start,end,result):
    return dict(worker=thread,slot=slot,opcode=op,desired=desired,start=start,finish=end,result=result)

def test_trials_count_and_scope():
    assert len(trials(1))==12
    assert len(trials(8))==96
    for number in (-1,0,17,1.0):
        with pytest.raises(AxError):trials(number)

def test_parser_accepts_observed_out_of_order_completion():
    sch=((((0,1),),((2,0),)),)
    raw='H 0 2 1 1\nO 0 0 0 1 0 3 1\nO 1 0 2 0 1 2 0\n'
    parsed=parse_history(raw,sch)
    assert parsed[0]['ops'][0]['finish']==3
    assert parsed[0]['final']==(1,1)

def test_parser_rejects_spoofed_operations():
    sch=((((0,1),),((2,0),)),)
    for invalid in [
        'H 0 2 1 1\nO 0 0 0 0 0 3 1\nO 1 0 2 0 1 2 0\n',
        'H 0 2 1 1\nO 0 0 0 1 0 3 1\nO 0 0 0 1 1 2 1\n',
        'H 0 2 1 1\nO 0 0 0 1 0 3 1\nO 1 0 2 0 1 8 0\n',
        'H 0 2 1 1\nO 0 0 0 1 0 3 1\nO 1 0 2 0 1 2 0\nEXTRA\n',
    ]:
        with pytest.raises(ValueError):parse_history(invalid,sch)

def test_linearizable_respects_completed_real_time_order(models_bound):
    models,_=models_bound
    # set(true) finishes before Source.peek returns false: impossible.
    obs={'ops':[entry(0,0,0,1,0,1,1),entry(1,0,1,0,2,3,0)],'final':(1,1)}
    ok,_=linearizable(models,obs)
    assert ok is False
    # With overlap, peek(false) can linearize before set(true).
    obs['ops'][0]['finish']=3;obs['ops'][1]['start']=1;obs['ops'][1]['finish']=2
    ok,order=linearizable(models,obs)
    assert ok is True and order==[1,0]

def test_linearizable_checks_final_quiescent_observation(models_bound):
    models,_=models_bound
    obs={'ops':[entry(0,0,0,1,0,3,1),entry(1,0,0,0,1,2,1)],'final':(1,0)}
    assert linearizable(models,obs)[0] is False
    obs['final']=(0,0)
    assert linearizable(models,obs)[0] is True

def test_linearizable_never_extrapolates_search_budget(models_bound):
    models,_=models_bound
    obs={'ops':[entry(0,0,0,1,0,3,1),entry(1,0,0,0,1,2,1)],'final':(0,0)}
    assert linearizable(models,obs,max_nodes=1)[0] is None

@pytest.fixture(scope='module')
def native_results(models_bound):
    if not available():pytest.skip('P2f sandbox namespace unavailable')
    models,bound=models_bound
    return {name:verify_cpp_history(models,bound,ROOT/f'cpp/history/{name}.cpp',repeats=1)
            for name in ('correct','broken_one_side','broken_overlap')}

def test_correct_native_thread_history(native_results):
    report=native_results['correct']
    assert report['outcome']=='Tested'
    assert report['scope']['trials']==12
    assert report['scope']['not_exhaustive_native_schedules'] is True
    assert report['scope']['not_formal_refinement_proof'] is True
    assert all(v['checked_histories']==12 for v in report['variants'].values())

def test_one_sided_update_rejected(native_results):
    report=native_results['broken_one_side']
    assert report['outcome']=='Violated'
    assert report['reason']=='E_HISTORY_NOT_LINEARIZABLE'
    assert report['counterexample']['history']['ops']

def test_concurrency_specific_bug_rejected(native_results):
    report=native_results['broken_overlap']
    assert report['outcome']=='Violated'
    assert report['reason']=='E_HISTORY_NOT_LINEARIZABLE'

def test_unknown_when_no_isolation(models_bound,monkeypatch):
    from axiom import cpp_history
    models,bound=models_bound
    monkeypatch.setattr(cpp_history,'available',lambda:False)
    report=verify_cpp_history(models,bound,ROOT/'cpp/history/correct.cpp',repeats=1)
    assert report['outcome']=='Unknown' and report['reason']=='E_NAMESPACE_UNAVAILABLE'

def test_gate_prototype_and_source_revision(models_bound,native_results,tmp_path,monkeypatch):
    models,bound=models_bound
    ws=Workspace(tmp_path/'evidence')
    src=tmp_path/'correct.cpp';src.write_bytes((ROOT/'cpp/history/correct.cpp').read_bytes())
    assert history_gate(ws,models,bound,src,repeats=1)['decision']=='Blocked'
    for ir in models.values():ws.record(ir,verify(ir))
    record_interleaving(ws,models,bound,verify_interleaving(models,bound))
    assert history_gate(ws,models,bound,src,repeats=1)['decision']=='Blocked'
    # Insert the real native observation result, using the same record procedure.
    # The fixture report avoids extra compilation; save it as a current immutable object.
    from axiom.history_store import history_tool_digest,ensure_table,EVIDENCE_VERSION,ABI_VERSION
    from axiom.lang import digest
    import uuid
    report=native_results['correct']
    raw=src.read_bytes();mh=ws.put(bound);sh=ws.put_bytes(raw);rh=ws.put(report)
    ev={'schema':EVIDENCE_VERSION,'manifest_digest':mh,'source_digest':sh,
        'report_digest':rh,'tool_digest':history_tool_digest(),
        'model_digests':{cid:digest(ir) for cid,ir in models.items()},
        'abi_version':ABI_VERSION,'harness_digest':digest(HARNESS.encode()),
        'outcome':report['outcome'],'assurance':'Tested','scope':report['scope']}
    eh=ws.put(ev);ensure_table(ws)
    with ws._db() as db:
        db.execute('INSERT INTO cpp_history_runs VALUES (?,?,?,?,?,?)',(
            'test-'+uuid.uuid4().hex,mh,sh,eh,'Tested','2026-10-25T00:00:00Z'))
    accepted=history_gate(ws,models,bound,src,repeats=1)
    assert accepted['decision']=='Approved'
    assert accepted['release_authorized'] is False
    assert history_gate(ws,models,bound,src,repeats=2)['decision']=='Blocked'
    src.write_bytes(src.read_bytes()+b'\n// changed implementation\n')
    assert history_gate(ws,models,bound,src,repeats=1)['decision']=='Blocked'
    src.write_bytes(raw)
    from axiom import history_store
    monkeypatch.setattr(history_store,'history_tool_digest',lambda:'sha256:'+'0'*64)
    assert history_gate(ws,models,bound,src,repeats=1)['decision']=='Blocked'

def test_audit_rejects_corrupted_history_evidence(models_bound,native_results,tmp_path):
    models,bound=models_bound
    ws=Workspace(tmp_path/'evidence')
    from axiom.history_store import history_tool_digest,ensure_table,EVIDENCE_VERSION,ABI_VERSION
    from axiom.lang import digest
    report=copy.deepcopy(native_results['correct'])
    report['variants']['normal']['checked_histories']=0
    mh=ws.put(bound);sh=ws.put_bytes((ROOT/'cpp/history/correct.cpp').read_bytes());rh=ws.put(report)
    ev={'schema':EVIDENCE_VERSION,'manifest_digest':mh,'source_digest':sh,'report_digest':rh,
        'tool_digest':history_tool_digest(),'model_digests':{cid:digest(ir) for cid,ir in models.items()},
        'abi_version':ABI_VERSION,'harness_digest':digest(HARNESS.encode()),
        'outcome':'Tested','assurance':'Tested','scope':report['scope']}
    eh=ws.put(ev);ensure_table(ws)
    with ws._db() as db:
        db.execute('INSERT INTO cpp_history_runs VALUES (?,?,?,?,?,?)',(
            'fake',mh,sh,eh,'Tested','2026-10-25T00:00:00Z'))
    from axiom.audit import audit_workspace
    result=audit_workspace(ws)
    assert result['status']=='Findings'
    assert any(x['table']=='cpp_history_runs' for x in result['findings'])
