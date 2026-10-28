import copy
import json
from pathlib import Path
import pytest

from axiom.audit import audit_workspace
from axiom.checker import verify
from axiom.interleaving import load_interleaving,verify_interleaving
from axiom.interleaving_store import record_interleaving,interleaving_gate
from axiom.lang import AxError,digest
from axiom.store import Workspace

ROOT=Path(__file__).resolve().parents[1]/'examples'/'interleaving'


def load(name='product_safe.json'):
    return load_interleaving(ROOT/name)


def seeded(ws,models):
    for ir in models.values():
        report=verify(ir)
        assert report['outcome']=='Bounded'
        ws.record(ir,report)


def test_safe_interleaving_and_gate(tmp_path):
    models,bound=load();ws=Workspace(tmp_path/'ws')
    assert interleaving_gate(ws,models,bound)['decision']=='Blocked'
    report=verify_interleaving(models,bound)
    assert report['outcome']=='Bounded'
    assert report['statistics']['reachable_states']==2
    assert report['statistics']['checked_transitions']>0
    record_interleaving(ws,models,bound,report)
    assert interleaving_gate(ws,models,bound)['decision']=='Blocked'
    seeded(ws,models)
    gate=interleaving_gate(ws,models,bound)
    assert gate['decision']=='Approved'
    assert 'no C++ refinement' in gate['scope']
    assert audit_workspace(ws)['status']=='Consistent'


def test_locally_correct_components_can_fail_interleaving(tmp_path):
    models,bound=load('product_broken.json')
    assert all(verify(ir)['outcome']=='Bounded' for ir in models.values())
    report=verify_interleaving(models,bound)
    assert report['outcome']=='Violated' and report['reason']=='E_INTER_PROPERTY'
    assert report['counterexample'][1]['kind']=='independent'
    assert len(report['counterexample'])==2
    ws=Workspace(tmp_path/'ws');seeded(ws,models)
    record_interleaving(ws,models,bound,report)
    assert interleaving_gate(ws,models,bound)['decision']=='Blocked'


def test_output_disagreement(tmp_path):
    models,bound=load()
    bad=copy.deepcopy(models)
    # Make Mirror.set report false, independent from both unchanged state logic.
    a=next(a for a in bad['Mirror']['actions'] if a['name']=='set')
    a['cases'][0]['ensures']={'op':'and','args':[{'op':'eq','left':{'op':'ref','name':'on','prime':True},'right':{'op':'ref','name':'desired'}},
                                         {'op':'eq','left':{'op':'ref','name':'result'},'right':{'op':'lit','value':False}}]}
    # Use actual IR expression schema via replacing a known parsed fragment.
    a['cases'][0]['ensures']=copy.deepcopy(next(a for a in bad['Source']['actions'] if a['name']=='set')['cases'][0]['ensures'])
    def flip(e):
        if isinstance(e,dict):
            if e.get('op')=='lit' and e.get('value') is True:e['value']=False
            for v in e.values():flip(v)
        elif isinstance(e,list):
            for v in e:flip(v)
    flip(a['cases'][0]['ensures'])
    rebound=copy.deepcopy(bound)
    rebound['components']=[{'id':cid,'spec_digest':digest(ir)} for cid,ir in sorted(bad.items())]
    report=verify_interleaving(bad,rebound)
    assert report['outcome']=='Violated' and report['reason']=='E_INTER_OUTPUT'


def test_budget_exhaustion_fail_closed(tmp_path):
    models,bound=load();ws=Workspace(tmp_path/'ws');seeded(ws,models)
    r=verify_interleaving(models,bound,max_transitions=1)
    assert r['outcome']=='Unknown'
    record_interleaving(ws,models,bound,r)
    assert interleaving_gate(ws,models,bound)['decision']=='Blocked'
    assert verify_interleaving(models,bound,max_states=1)['outcome']=='Unknown'
    assert verify_interleaving(models,bound,max_states=0)['outcome']=='Unknown'


def test_stale_property_or_model_prevents_reuse(tmp_path):
    models,bound=load();ws=Workspace(tmp_path/'ws')
    seeded(ws,models);record_interleaving(ws,models,bound,verify_interleaving(models,bound))
    assert interleaving_gate(ws,models,bound)['decision']=='Approved'
    changed=copy.deepcopy(bound);changed['properties'][0]['name']='Changed'
    assert interleaving_gate(ws,models,changed)['decision']=='Blocked'
    bad_models=copy.deepcopy(models)
    bad_models['Mirror']['properties'][0]['name']='Changed'
    rebound=copy.deepcopy(bound)
    rebound['components']=[{'id':cid,'spec_digest':digest(ir)} for cid,ir in sorted(bad_models.items())]
    assert interleaving_gate(ws,bad_models,rebound)['decision']=='Blocked'


def test_tampered_evidence_and_replay(tmp_path):
    models,bound=load();ws=Workspace(tmp_path/'ws');seeded(ws,models)
    r=verify_interleaving(models,bound)
    fake=copy.deepcopy(r);fake['statistics']['reachable_states']=10000
    with pytest.raises(ValueError,match='FORGERY'):
        record_interleaving(ws,models,bound,fake)
    saved=record_interleaving(ws,models,bound,r)
    ws.object_path(saved['report_digest']).write_bytes(b'{"altered":true}')
    assert interleaving_gate(ws,models,bound)['decision']=='Blocked'
    assert audit_workspace(ws)['status']=='Findings'


@pytest.mark.parametrize('modifier,expected',[ 
    (lambda m:m.update(independent=[]),'E_INTER_UNPAIRED'),
    (lambda m:m['independent'].append('Source.set'),'E_INTER_UNPAIRED'),
    (lambda m:m['sync'][0].update(output_relation='any'),'E_INTER_SYNC'),
    (lambda m:m['sync'][0].update(left='Source.unknown'),'E_INTER_REFERENCE'),
    (lambda m:m['components'][0].update(spec='../outside.ax'),'E_INTER_PATH'),
    (lambda m:m['properties'][0].update(expr={'ref':'Source.missing'}),'E_PRODUCT_REFERENCE'),
    (lambda m:m['properties'][0].update(expr={'lit':123}),'E_INTER_PROPERTY'),
    (lambda m:m.update(other='unexpected'),'E_INTER_SCHEMA'),
])
def test_malformed_manifest(tmp_path,modifier,expected):
    manifest=json.loads((ROOT/'product_safe.json').read_text())
    modifier(manifest)
    for file in ('Source.ax','Mirror.ax'):(tmp_path/file).write_bytes((ROOT/file).read_bytes())
    path=tmp_path/'manifest.json';path.write_text(json.dumps(manifest))
    with pytest.raises(AxError) as exc:load_interleaving(path)
    assert exc.value.code==expected


def test_spec_symlink_escape(tmp_path):
    manifest=json.loads((ROOT/'product_safe.json').read_text())
    (tmp_path/'Source.ax').symlink_to(ROOT/'Source.ax')
    (tmp_path/'Mirror.ax').write_bytes((ROOT/'Mirror.ax').read_bytes())
    p=tmp_path/'manifest.json';p.write_text(json.dumps(manifest))
    with pytest.raises(AxError,match='E_INTER_PATH'):load_interleaving(p)


def test_direct_api_manifest_or_model_forgery():
    models,bound=load()
    tampered=copy.deepcopy(models);tampered['Mirror']['properties'][0]['name']='Different'
    with pytest.raises(AxError,match='E_INTER_BINDING'):
        verify_interleaving(tampered,bound)
    forged=copy.deepcopy(bound);forged['independent'].append('Source.set')
    with pytest.raises(AxError,match='E_INTER_UNPAIRED'):
        verify_interleaving(models,forged)


def test_cli_full_interleaving_cycle(tmp_path):
    """Exercise the installed-style -m CLI, not just direct Python APIs."""
    import os,subprocess,sys
    root=Path(__file__).resolve().parents[1]
    ws=tmp_path/'cli-workspace'
    env={**os.environ,'PYTHONPATH':str(root/'src')}
    def run(*args):
        proc=subprocess.run([sys.executable,'-m','axiom','--workspace',str(ws),*args],
                            cwd=root,env=env,text=True,capture_output=True,timeout=20)
        return proc.returncode,json.loads(proc.stdout)
    manifest='examples/interleaving/product_safe.json'
    code,gate=run('interleave-gate',manifest)
    assert code==4 and gate['decision']=='Blocked'
    for model in ('Source.ax','Mirror.ax'):
        code,_=run('verify',f'examples/interleaving/{model}')
        assert code==0
    code,report=run('interleave-verify',manifest)
    assert code==0 and report['verification']['outcome']=='Bounded'
    code,gate=run('interleave-gate',manifest)
    assert code==0 and gate['decision']=='Approved'
    code,audit=run('audit')
    assert code==0 and audit['status']=='Consistent' and audit['examined']['interleaving_runs']==1
    code,wrong=run('interleave-verify','examples/interleaving/product_broken.json')
    assert code==2 and wrong['verification']['reason']=='E_INTER_PROPERTY'
