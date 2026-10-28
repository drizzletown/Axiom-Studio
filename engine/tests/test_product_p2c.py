import copy
import json
from pathlib import Path
import pytest

from axiom.lang import AxError,parse,validate
from axiom.checker import verify
from axiom.store import Workspace
from axiom.product import load_product,verify_product
from axiom.product_store import record_product,product_gate

ROOT=Path(__file__).parents[1]/'examples'/'product'


def load(name='product.json'):
    return load_product(ROOT/name)


def seeded(ws,models):
    for ir in models.values():
        r=verify(ir)
        assert r['outcome']=='Bounded'
        ws.record(ir,r)


def test_synchronized_product_and_gates(tmp_path):
    models,bound=load();ws=Workspace(tmp_path/'w')
    assert product_gate(ws,models,bound)['decision']=='Blocked'
    report=verify_product(models,bound)
    assert report['outcome']=='Bounded' and report['statistics']['reachable_states']==2
    record_product(ws,models,bound,report)
    assert product_gate(ws,models,bound)['decision']=='Blocked'  # also requires local evidence
    seeded(ws,models)
    gate=product_gate(ws,models,bound)
    assert gate['decision']=='Approved' and gate['selected_product_evidence']
    assert gate['target']=='finite-abstract-product-integration-check'
    assert 'no C++ refinement' in gate['scope']


def test_cross_property_fails_despite_local_models_passing(tmp_path):
    models,bound=load('product_broken.json')
    assert all(verify(ir)['outcome']=='Bounded' for ir in models.values())
    report=verify_product(models,bound)
    assert report['outcome']=='Violated' and report['reason']=='E_PRODUCT_PROPERTY'
    assert len(report['counterexample'])>=2
    ws=Workspace(tmp_path/'w')
    seeded(ws,models);record_product(ws,models,bound,report)
    assert product_gate(ws,models,bound)['decision']=='Blocked'


def test_output_mismatch_detected_even_if_states_agree(tmp_path):
    manifest=json.loads((ROOT/'product.json').read_text())
    for c in manifest['components']:
        if c['id']=='Mirror':c['spec']='MirrorOutputBroken.ax'
    path=tmp_path/'product.json'
    for file in ('Source.ax','MirrorOutputBroken.ax'):
        (tmp_path/file).write_bytes((ROOT/file).read_bytes())
    path.write_text(json.dumps(manifest))
    models,bound=load_product(path)
    r=verify_product(models,bound)
    assert r['outcome']=='Violated' and r['reason']=='E_PRODUCT_OUTPUT'


def test_resource_bounds_are_unknown_and_no_gate(tmp_path):
    models,bound=load();ws=Workspace(tmp_path/'w')
    report=verify_product(models,bound,max_transitions=1)
    assert report['outcome']=='Unknown'
    record_product(ws,models,bound,report)
    seeded(ws,models)
    assert product_gate(ws,models,bound)['decision']=='Blocked'
    assert verify_product(models,bound,max_states=1)['outcome']=='Unknown'


def test_stale_product_evidence_not_accepted(tmp_path):
    models,bound=load();ws=Workspace(tmp_path/'w')
    seeded(ws,models);record_product(ws,models,bound,verify_product(models,bound))
    assert product_gate(ws,models,bound)['decision']=='Approved'
    changed=copy.deepcopy(bound)
    changed['properties'][0]['name']='NewVersion'
    assert product_gate(ws,models,changed)['decision']=='Blocked'
    changed_models=copy.deepcopy(models)
    changed_models['Mirror']['properties'][0]['name']='NewLocalVersion'
    changed_bound=copy.deepcopy(bound)
    from axiom.lang import digest
    changed_bound['components']=[{'id':cid,'spec_digest':digest(ir)} for cid,ir in sorted(changed_models.items())]
    assert product_gate(ws,changed_models,changed_bound)['decision']=='Blocked'


def test_replay_rejects_fabricated_bounded_report(tmp_path):
    models,bound=load()
    rep=verify_product(models,bound)
    rep['statistics']['reachable_states']=999
    with pytest.raises(ValueError,match='FORGERY'):
        record_product(Workspace(tmp_path/'w'),models,bound,rep)


def test_object_corruption_fails_closed(tmp_path):
    models,bound=load();ws=Workspace(tmp_path/'w')
    seeded(ws,models);rec=record_product(ws,models,bound,verify_product(models,bound))
    ws.object_path(rec['evidence_digest']).write_bytes(b'{"forged":true}')
    assert product_gate(ws,models,bound)['decision']=='Blocked'


@pytest.mark.parametrize('mutate,code',[
    (lambda m:m.update(sync=[]),'E_PRODUCT_SYNC'),
    (lambda m:m['sync'][0].update(left='Source.not_exist'),'E_PRODUCT_REFERENCE'),
    (lambda m:m['sync'][0].update(output_relation='any'),'E_PRODUCT_SYNC'),
    (lambda m:m['components'][1].update(spec='../outside.ax'),'E_PRODUCT_PATH'),
    (lambda m:m['properties'][0].update(expr={'ref':'Source.unknown'}),'E_PRODUCT_REFERENCE'),
    (lambda m:m['properties'][0].update(expr={'op':'eval','args':[]}),'E_PRODUCT_OPERATOR'),
    (lambda m:m['properties'][0].update(expr={'lit':123}),'E_PRODUCT_TYPE'),
])
def test_manifest_malformed_fails_closed(tmp_path,mutate,code):
    m=json.loads((ROOT/'product.json').read_text())
    mutate(m)
    for file in ('Source.ax','Mirror.ax'):
        (tmp_path/file).write_bytes((ROOT/file).read_bytes())
    p=tmp_path/'manifest.json';p.write_text(json.dumps(m))
    with pytest.raises(AxError) as exc: load_product(p)
    assert exc.value.code==code


def test_duplicate_and_unknown_fields_rejected(tmp_path):
    m=json.loads((ROOT/'product.json').read_text());m['sync'][0]['extra']='value'
    for file in ('Source.ax','Mirror.ax'): (tmp_path/file).write_bytes((ROOT/file).read_bytes())
    p=tmp_path/'manifest.json';p.write_text(json.dumps(m))
    with pytest.raises(AxError,match='E_PRODUCT_SCHEMA'):load_product(p)


def test_symlink_is_not_accepted(tmp_path):
    m=json.loads((ROOT/'product.json').read_text())
    (tmp_path/'Source.ax').symlink_to(ROOT/'Source.ax')
    (tmp_path/'Mirror.ax').write_bytes((ROOT/'Mirror.ax').read_bytes())
    p=tmp_path/'manifest.json';p.write_text(json.dumps(m))
    with pytest.raises(AxError,match='E_PRODUCT_PATH'):load_product(p)

def test_direct_api_cannot_substitute_model_without_rebinding():
    models,bound=load()
    tampered=copy.deepcopy(models)
    tampered['Mirror']['properties'][0]['name']='Changed'
    with pytest.raises(AxError,match='E_PRODUCT_BINDING'):
        verify_product(tampered,bound)


def test_initial_cartesian_budget_rejected_before_allocation():
    models,bound=load()
    for ir in models.values():
        ir['init']={'op':'lit','value':True}
    rebound=copy.deepcopy(bound)
    rebound['components']=[{'id':cid,'spec_digest':__import__('axiom.lang',fromlist=['digest']).digest(ir)} for cid,ir in sorted(models.items())]
    r=verify_product(models,rebound,max_states=3)
    assert r['outcome']=='Unknown' and r['reason']=='E_PRODUCT_LIMIT_STATES'

def test_audit_recognizes_product_and_reports_tamper(tmp_path):
    from axiom.audit import audit_workspace
    models,bound=load();ws=Workspace(tmp_path/'w')
    seeded(ws,models)
    record=record_product(ws,models,bound,verify_product(models,bound))
    assert audit_workspace(ws)['status']=='Consistent'
    ws.object_path(record['report_digest']).write_text('bad-content')
    rep=audit_workspace(ws)
    assert rep['status']=='Findings'
    assert any(x['code'] in ('PRODUCT_ARTIFACT_UNREADABLE','OBJECT_DIGEST_MISMATCH') for x in rep['findings'])
