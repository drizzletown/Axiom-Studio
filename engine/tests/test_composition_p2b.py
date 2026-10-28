"""Conservative P2b integration-readiness gates, not composition proof."""
import copy
import json
from pathlib import Path
import pytest
from axiom.composition import load_manifest, assess_composition
from axiom.lang import AxError, parse, validate
from axiom.checker import verify
from axiom.store import Workspace

ROOT=Path(__file__).resolve().parents[1]

def setup(tmp_path):
    (tmp_path/'account.ax').write_text((ROOT/'examples/two_account.ax').read_text())
    (tmp_path/'flag.ax').write_text((ROOT/'examples/toggle.ax').read_text())
    obj={'schema':'ax-evidence-dependencies/0.1',
        'components':[{'id':'TwoAccount','spec':'account.ax','exports':['Conservation','NonNegative']},
                      {'id':'Toggle','spec':'flag.ax','exports':['StableType']}],
        'dependencies':[{'consumer':'Toggle','provider':'TwoAccount','property':'Conservation'}]}
    p=tmp_path/'composition.json'
    p.write_text(json.dumps(obj))
    return p,obj

def register(workspace,path):
    specs,_=load_manifest(path)
    for ir in specs.values():
        report=verify(ir)
        assert report['outcome']=='Bounded'
        workspace.record(ir,report)

def test_compose_unverified_is_blocked(tmp_path):
    p,_=setup(tmp_path)
    report=assess_composition(Workspace(tmp_path/'w'),p)
    assert report['decision']=='Blocked'
    assert len(report['reasons'])>=2
    assert report['target']=='abstract-model-evidence-integration-readiness'

def test_compose_ready_only_after_independent_evidence(tmp_path):
    p,_=setup(tmp_path);w=Workspace(tmp_path/'w')
    register(w,p)
    r=assess_composition(w,p)
    assert r['decision']=='Ready'
    assert len(r['components'])==2
    assert w.get(r['assessment_digest'])['decision']=='Ready'
    assert 'no assume-guarantee proof' in r['scope']

def test_missing_guarantee_blocks(tmp_path):
    p,manifest=setup(tmp_path)
    manifest['dependencies'][0]['property']='Nonexistent'
    p.write_text(json.dumps(manifest))
    with pytest.raises(AxError,match='E_COMPOSE_EXPORT'):load_manifest(p)

def test_cyclic_assumptions_block(tmp_path):
    p,obj=setup(tmp_path)
    obj['dependencies'].append({'consumer':'TwoAccount','provider':'Toggle','property':'StableType'})
    p.write_text(json.dumps(obj))
    with pytest.raises(AxError,match='E_COMPOSE_CYCLE'):load_manifest(p)

def test_self_dependency_block(tmp_path):
    p,obj=setup(tmp_path)
    obj['dependencies']=[{'consumer':'Toggle','provider':'Toggle','property':'StableType'}]
    p.write_text(json.dumps(obj))
    with pytest.raises(AxError,match='E_COMPOSE_CYCLE'):load_manifest(p)

def test_duplicate_dependency_block(tmp_path):
    p,obj=setup(tmp_path)
    obj['dependencies'].append(obj['dependencies'][0])
    p.write_text(json.dumps(obj))
    with pytest.raises(AxError,match='E_COMPOSE_DUPLICATE'):load_manifest(p)

def test_duplicate_component_block(tmp_path):
    p,obj=setup(tmp_path)
    obj['components'].append(obj['components'][0])
    p.write_text(json.dumps(obj))
    with pytest.raises(AxError,match='E_COMPOSE_DUPLICATE'):load_manifest(p)

def test_unexpected_manifest_field_block(tmp_path):
    p,obj=setup(tmp_path);obj['approved']=True;p.write_text(json.dumps(obj))
    with pytest.raises(AxError,match='E_COMPOSE_SCHEMA'):load_manifest(p)

def test_symlink_or_path_escape_block(tmp_path):
    p,obj=setup(tmp_path)
    obj['components'][0]['spec']='../outside.ax'
    p.write_text(json.dumps(obj))
    with pytest.raises(AxError,match='E_COMPOSE_PATH'):load_manifest(p)

def test_changed_guarantee_invalidates_provider_only(tmp_path):
    p,_=setup(tmp_path);w=Workspace(tmp_path/'w');register(w,p)
    assert assess_composition(w,p)['decision']=='Ready'
    s=(tmp_path/'account.ax').read_text().replace('a + b == 3','a + b == 2')
    assert s!=(tmp_path/'account.ax').read_text()
    (tmp_path/'account.ax').write_text(s)
    result=assess_composition(w,p)
    assert result['decision']=='Blocked'
    assert result['components']['Toggle']['local_gate_decision']=='Approved'
    assert result['components']['TwoAccount']['local_gate_decision']=='Blocked'
    assert any('Conservation' in x for x in result['components']['TwoAccount']['missing_obligations'])

def test_changed_action_invalidates_all_provider_obligations(tmp_path):
    p,_=setup(tmp_path);w=Workspace(tmp_path/'w');register(w,p)
    s=(tmp_path/'account.ax').read_text().replace("a' == a - m", "a' == a")
    assert s!=(tmp_path/'account.ax').read_text()
    (tmp_path/'account.ax').write_text(s)
    r=assess_composition(w,p)
    assert r['decision']=='Blocked'
    assert len(r['components']['TwoAccount']['missing_obligations']) == r['components']['TwoAccount']['required_obligation_count']

def test_unmodified_provider_evidence_reused_after_unrelated_property(tmp_path):
    p,_=setup(tmp_path);w=Workspace(tmp_path/'w');register(w,p)
    s=(tmp_path/'account.ax').read_text().replace('  observe {', '  property Additional { always a >= 0 }\n  observe {')
    (tmp_path/'account.ax').write_text(s)
    first=assess_composition(w,p)
    assert first['decision']=='Blocked'
    missing=first['components']['TwoAccount']['missing_obligations']
    assert len(missing)==1 and missing[0].endswith('/Additional')
    ir=load_manifest(p)[0]['TwoAccount'];r=verify(ir)
    assert r['outcome']=='Bounded';w.record(ir,r)
    second=assess_composition(w,p)
    assert second['decision']=='Ready'

def test_changed_model_finite_domain_requires_fresh_verification(tmp_path):
    p,_=setup(tmp_path);w=Workspace(tmp_path/'w');register(w,p)
    original=(tmp_path/'account.ax').read_text()
    altered=original.replace('Int[0..3]','Int[0..4]')
    assert altered!=original
    (tmp_path/'account.ax').write_text(altered)
    assert assess_composition(w,p)['decision']=='Blocked'

def test_manifest_digest_binds_spec_digest(tmp_path):
    p,_=setup(tmp_path);w=Workspace(tmp_path/'w');register(w,p)
    a=assess_composition(w,p)
    t=(tmp_path/'flag.ax').read_text()
    (tmp_path/'flag.ax').write_text(t.replace('property StableType { always enabled == true || enabled == false }',
                                           'property StableType { always enabled != true || enabled == true }'))
    b=assess_composition(w,p)
    assert a['manifest_digest']!=b['manifest_digest']


def test_local_symlink_manifest_path_block(tmp_path):
    p,obj=setup(tmp_path)
    (tmp_path/'linked.ax').symlink_to(tmp_path/'account.ax')
    obj['components'][0]['spec']='linked.ax'
    p.write_text(json.dumps(obj))
    with pytest.raises(AxError,match='E_COMPOSE_PATH'):load_manifest(p)
