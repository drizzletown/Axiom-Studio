"""P2g scope, fail-closed evidence and actual ThreadSanitizer fault injection."""
from __future__ import annotations
from pathlib import Path
import copy
import pytest
from axiom.cpp_stress import scenarios_for,seeded_payload,verify_cpp_stress,STRESS_HARNESS,SCHEMA
from axiom.stress_store import stress_gate,record_stress,ensure_table,EVIDENCE,tool_digest
from axiom.interleaving import load_interleaving,verify_interleaving
from axiom.interleaving_store import record_interleaving
from axiom.checker import verify
from axiom.store import Workspace
from axiom.lang import AxError,digest
from axiom.sandbox import available
from axiom.audit import audit_workspace

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def models_bound():return load_interleaving(ROOT/'examples/interleaving/product_safe.json')

def test_stress_input_scope_validation():
    for args in ((0,0,1),(5,1,1),(1,-1,1),(1,10,0),(1,10,9),(True,0,1)):
        with pytest.raises(AxError):scenarios_for(*args)
    items=scenarios_for(1,42,2)
    assert len(items)==24 and items[0][1]==42 and items[12][1]!=42
    assert seeded_payload(items).startswith(b'24\n')
    assert 'perturb(seed,trial,t,j,1)' in STRESS_HARNESS

def test_unknown_without_namespace(models_bound,monkeypatch):
    from axiom import cpp_stress
    monkeypatch.setattr(cpp_stress,'available',lambda:False)
    m,b=models_bound
    r=verify_cpp_stress(m,b,ROOT/'cpp/history/correct.cpp')
    assert r['outcome']=='Unknown' and r['reason']=='E_NAMESPACE_UNAVAILABLE'

@pytest.fixture(scope='module')
def actual_reports(models_bound):
    if not available():pytest.skip('required Linux namespace unavailable')
    m,b=models_bound
    return {name:verify_cpp_stress(m,b,ROOT/f'cpp/history/{name}.cpp',seed_count=2)
            for name in ('correct','racy_auxiliary')}

def test_actual_correct_tsan_and_seeded_histories(actual_reports):
    r=actual_reports['correct']
    assert r['outcome']=='Tested'
    assert r['schema']==SCHEMA and r['scope']['trials']==24
    assert set(r['variants'])=={'normal','ubsan','tsan'}
    assert all(v['checked_histories']==24 for v in r['variants'].values())
    assert all(v['distinct_event_orders']>1 for v in r['variants'].values())

def test_tsan_detects_behaviorally_correct_but_racy_code(actual_reports):
    r=actual_reports['racy_auxiliary']
    assert r['outcome']=='Violated' and r['reason']=='E_STRESS_DATA_RACE'
    assert r['variants']['normal']['checked_histories']==24
    assert r['variants']['ubsan']['checked_histories']==24
    assert 'tsan' in r['variants']

def test_gate_checks_current_source_seed_and_no_release(models_bound,actual_reports,tmp_path,monkeypatch):
    m,b=models_bound
    ws=Workspace(tmp_path/'w')
    src=tmp_path/'correct.cpp';src.write_bytes((ROOT/'cpp/history/correct.cpp').read_bytes())
    assert stress_gate(ws,m,b,src)['decision']=='Blocked'
    for ir in m.values():ws.record(ir,verify(ir))
    record_interleaving(ws,m,b,verify_interleaving(m,b))
    # Reuse a real independently produced report, without running a second compiler.
    report=actual_reports['correct']
    mh=ws.put(b);sh=ws.put_bytes(src.read_bytes());rh=ws.put(report)
    ev={'schema':EVIDENCE,'manifest_digest':mh,'source_digest':sh,
        'report_digest':rh,'tool_digest':tool_digest(),
        'model_digests':{cid:digest(ir) for cid,ir in m.items()},
        'abi':'ax-cpp-history-abi/0.1','harness_digest':digest(STRESS_HARNESS.encode()),
        'outcome':'Tested','assurance':'Tested','scope':report['scope']}
    eh=ws.put(ev);ensure_table(ws)
    with ws._db() as db:
        db.execute('INSERT INTO cpp_stress_runs VALUES (?,?,?,?,?,?)',
                   ('sample',mh,sh,eh,'Tested','2026-10-25T00:00:00Z'))
    ok=stress_gate(ws,m,b,src)
    assert ok['decision']=='Approved' and ok['release_authorized'] is False
    assert stress_gate(ws,m,b,src,seed=10000)['decision']=='Blocked'
    assert stress_gate(ws,m,b,src,seed_count=3)['decision']=='Blocked'
    src.write_bytes(src.read_bytes()+b'\n// source changed\n')
    assert stress_gate(ws,m,b,src)['decision']=='Blocked'
    src.write_bytes((ROOT/'cpp/history/correct.cpp').read_bytes())
    # Corrupted local report must not be accepted by gate or audit.
    altered=copy.deepcopy(report);altered['variants']['tsan']['checked_histories']=0
    badrh=ws.put(altered);bad_ev=copy.deepcopy(ev);bad_ev['report_digest']=badrh
    badeh=ws.put(bad_ev)
    with ws._db() as db:
        db.execute('INSERT INTO cpp_stress_runs VALUES (?,?,?,?,?,?)',
                   ('bad',mh,sh,badeh,'Tested','2026-10-25T00:00:01Z'))
    findings=audit_workspace(ws)
    assert findings['status']=='Findings'
    assert any(x['table']=='cpp_stress_runs' for x in findings['findings'])
    # Audit findings block independent release use; local gate still can select earlier
    # valid test evidence (never claims independent secure storage).
