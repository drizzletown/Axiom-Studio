from pathlib import Path
import sqlite3
from axiom.audit import audit_workspace
from axiom.lang import parse,validate
from axiom.checker import verify
from axiom.store import Workspace

ROOT=Path(__file__).resolve().parents[1]

def sample():return validate(parse((ROOT/'examples/two_account.ax').read_text()))

def test_audit_clean(tmp_path):
    w=Workspace(tmp_path);ir=sample();w.record(ir,verify(ir))
    a=audit_workspace(w)
    assert a['status']=='Consistent'
    assert a['examined']['model_runs']==1
    assert not a['findings']
    assert 'Local integrity' in a['trust_boundary']

def test_audit_detects_object_tampering(tmp_path):
    w=Workspace(tmp_path);ir=sample();r=w.record(ir,verify(ir))
    (w.objects/r['evidence_digest'].split(':',1)[1]).write_bytes(b'{}')
    a=audit_workspace(w)
    assert a['status']=='Findings'
    assert any(f['code']=='OBJECT_DIGEST_MISMATCH' for f in a['findings'])
    assert any(f['code']=='MODEL_ARTIFACT_UNREADABLE' for f in a['findings'])

def test_audit_detects_malformed_db_reference(tmp_path):
    w=Workspace(tmp_path);ir=sample();r=w.record(ir,verify(ir))
    with sqlite3.connect(w.db_path) as db:
        db.execute('UPDATE runs SET outcome=? WHERE run_id=?',('Proved',r['run_id']))
    a=audit_workspace(w)
    assert any(f['code']=='MODEL_OUTCOME_MISMATCH' for f in a['findings'])

def test_audit_detects_missing_object(tmp_path):
    w=Workspace(tmp_path);ir=sample();r=w.record(ir,verify(ir))
    (w.objects/r['report_digest'].split(':',1)[1]).unlink()
    a=audit_workspace(w)
    assert any(f['code']=='MODEL_ARTIFACT_UNREADABLE' for f in a['findings'])

def test_audit_unknown_result_remains_consistent(tmp_path):
    w=Workspace(tmp_path);ir=sample();rep=verify(ir,max_transitions=1)
    assert rep['outcome']=='Unknown'
    w.record(ir,rep)
    assert audit_workspace(w)['status']=='Consistent'

def test_audit_cpp_binary_integrity(tmp_path):
    from axiom.cpp import run_cpp
    w=Workspace(tmp_path);ir=sample()
    report,artifacts=run_cpp(ir,ROOT/'cpp/correct.cpp',ROOT/'cpp/binding.json')
    assert report['outcome']=='Tested'
    r=w.record_cpp(ir,report,artifacts)
    assert audit_workspace(w)['status']=='Consistent'
    (w.objects/r['binary_digests']['normal'].split(':',1)[1]).write_bytes(b'corrupted')
    a=audit_workspace(w)
    assert any(f['code']=='CPP_OBJECT_INTEGRITY_FAILED' for f in a['findings'])

def test_content_digest_path_rejects_path_traversal(tmp_path):
    import pytest
    w=Workspace(tmp_path)
    with pytest.raises(ValueError,match='invalid content'):
        w.get('sha256:../../secret')


def test_cannot_store_fabricated_bounded_report(tmp_path):
    import copy
    import pytest
    ir=sample();w=Workspace(tmp_path)
    report=verify(ir)
    forged=copy.deepcopy(report)
    forged['statistics']['reachable_states']=999
    with pytest.raises(ValueError,match='checker replay'):
        w.record(ir,forged)
    assert not w.runs()


def test_audit_detects_forged_gate_index(tmp_path):
    w=Workspace(tmp_path);ir=sample();w.record(ir,verify(ir));g=w.gate(ir,target='model')
    assert g['decision']=='Approved'
    with sqlite3.connect(w.db_path) as db:
        db.execute('UPDATE gates SET decision=? WHERE gate_id=?',('Blocked',g['gate_id']))
    a=audit_workspace(w)
    assert any(f['code']=='GATE_INDEX_MISMATCH' for f in a['findings'])


def test_audit_detects_false_current_assessment(tmp_path):
    w=Workspace(tmp_path);ir=sample();r=w.record(ir,verify(ir))
    w.assess(r['run_id'],'sha256:'+'a'*64)
    with sqlite3.connect(w.db_path) as db:
        db.execute('UPDATE assessments SET freshness=?',('Current',))
    a=audit_workspace(w)
    assert any(f['code']=='UNSUPPORTED_CURRENT_ASSERTION' for f in a['findings'])
