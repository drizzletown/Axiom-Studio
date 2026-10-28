from pathlib import Path
import pytest
from axiom.lang import AxError,canonical_bytes,digest,parse,validate
from axiom.checker import verify, obligations

EXAMPLES=Path(__file__).parents[1]/'examples'
def model(name='two_account.ax'):
    return validate(parse((EXAMPLES/name).read_text()))

def test_valid_two_account():
    m=model();r=verify(m)
    assert r['outcome']=='Bounded'
    assert r['scope']['finite_reachable_exhaustion']
    assert r['statistics']['reachable_states']==4
    assert len(obligations(m))==5


def test_toggle():
    assert verify(model('toggle.ax'))['outcome']=='Bounded'


def test_conservation_counterexample():
    r=verify(model('broken_conservation.ax'))
    assert r['outcome']=='Violated' and r['reason']=='E_PROPERTY'
    assert r['counterexample'][0]['state']=={'a':3,'b':0}
    assert r['counterexample'][-1]['state']['a']+r['counterexample'][-1]['state']['b']!=3


def test_semantic_hash_ignores_comments_whitespace():
    s=(EXAMPLES/'two_account.ax').read_text()
    m1=model();m2=validate(parse('\n\n// header\n'+s.replace('case otherwise','case    otherwise')))
    assert digest(m1)==digest(m2)
    assert canonical_bytes(m1)==canonical_bytes(m2)


def test_semantic_hash_changes_on_behavior_change():
    s=(EXAMPLES/'two_account.ax').read_text()
    m1=model();m2=validate(parse(s.replace("b' == b + m", "b' == b")))
    assert digest(m1)!=digest(m2)


def test_guards_overlap_detected():
    src=(EXAMPLES/'toggle.ax').read_text().replace('case true','case true { modifies { enabled } ensures enabled\' == desired && result == true }\n    case true')
    r=verify(validate(parse(src)))
    assert r['outcome']=='Violated' and r['reason']=='E_CASE_OVERLAP'


def test_missing_case_detected():
    src=(EXAMPLES/'two_account.ax').read_text()
    i=src.index('    case otherwise');j=src.index('\n  }\n  property',i)
    r=verify(validate(parse(src[:i]+src[j:])))
    assert r['outcome']=='Violated' and r['reason']=='E_CASE_UNCOVERED'


def test_no_successor_detected():
    src=(EXAMPLES/'two_account.ax').read_text().replace("a' == a - m","a' == a + m")
    r=verify(validate(parse(src)))
    assert r['outcome']=='Violated' and r['reason']=='E_NO_SUCCESSOR'


def test_missing_state_field_rejected():
    src=(EXAMPLES/'two_account.ax').read_text().replace('a >= 0', 'missing >= 0')
    with pytest.raises(AxError,match='E_UNBOUND'):validate(parse(src))


def test_wrong_type_rejected():
    src=(EXAMPLES/'toggle.ax').read_text().replace('enabled == false','enabled + false == false')
    with pytest.raises(AxError,match='E_TYPE'):validate(parse(src))


def test_invalid_frame_rejected():
    src=(EXAMPLES/'two_account.ax').read_text().replace('modifies { a, b }','modifies { a, unknown }')
    with pytest.raises(AxError,match='E_FRAME_UNKNOWN'):validate(parse(src))


def test_duplicate_property_rejected():
    src=(EXAMPLES/'toggle.ax').read_text().replace('  observe', '  property StableType { always true }\n  observe')
    with pytest.raises(AxError,match='E_DUP_PROPERTY'):validate(parse(src))


def test_quota_yields_unknown_not_success():
    r=verify(model(),max_transitions=5)
    assert r['outcome']=='Unknown'
    assert not r['scope']['finite_reachable_exhaustion']


def test_init_unsat():
    src=(EXAMPLES/'two_account.ax').read_text().replace('a == 3 && b == 0','a == 3 && a == 0')
    r=verify(validate(parse(src)))
    assert r['outcome']=='Violated' and r['reason']=='E_INIT_UNSAT'


def test_non_exhaustive_observe_rejected():
    src=(EXAMPLES/'two_account.ax').read_text().replace('move.input, move.output','move.input')
    with pytest.raises(AxError,match='E_OBSERVE'):validate(parse(src))
