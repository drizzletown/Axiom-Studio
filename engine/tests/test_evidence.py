from pathlib import Path
from axiom.lang import parse,validate,digest
from axiom.checker import verify
from axiom.store import Workspace

EXAMPLES=Path(__file__).parents[1]/'examples'
def model(name):return validate(parse((EXAMPLES/name).read_text()))

def test_gate_is_closed_for_cpp_without_implementation_evidence(tmp_path):
    db=Workspace(tmp_path);ir=model('two_account.ax')
    db.record(ir,verify(ir))
    assert db.gate(ir,target='model')['decision']=='Approved'
    g=db.gate(ir,target='cpp',candidate_digest='sha256:aaa')
    assert g['decision']=='Blocked'
    assert 'MISSING_CPP_BINDING_AND_IMPLEMENTATION_EVIDENCE' in g['reasons']


def test_changed_spec_stales_evidence(tmp_path):
    db=Workspace(tmp_path);old=model('two_account.ax');new=model('broken_conservation.ax')
    rec=db.record(old,verify(old));fresh=db.assess(rec['run_id'],digest(new))
    assert fresh['freshness']=='Stale'
    assert db.gate(new,target='model')['decision']=='Blocked'


def test_same_semantics_evidence_is_reusable(tmp_path):
    db=Workspace(tmp_path);old=model('two_account.ax')
    r=db.record(old,verify(old));a=db.assess(r['run_id'],digest(old))
    assert a['freshness']=='Current'


def test_failed_verification_is_not_qualifying_evidence(tmp_path):
    db=Workspace(tmp_path);bad=model('broken_conservation.ax')
    rec=db.record(bad,verify(bad))
    assert db.assess(rec['run_id'],digest(bad))['freshness']=='Revalidate'
    assert db.gate(bad,target='model')['decision']=='Blocked'


def test_invalid_evidence_blob_cannot_be_accepted(tmp_path):
    db=Workspace(tmp_path);ir=model('two_account.ax')
    record=db.record(ir,verify(ir))
    f=db.objects/record['evidence_digest'].split(':')[1]
    f.write_bytes(b'{}')
    import pytest
    with pytest.raises(ValueError,match='mismatch'):
        db.gate(ir,target='model')
