"""Workflow-first Axiom Studio integration and failure-path tests."""
from pathlib import Path
import hashlib, json, sqlite3, sys, tempfile
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from orchestrator import Orchestrator,FlowConflict,FlowError

ROOT=Path(__file__).resolve().parents[2]
ENGINE=ROOT/'engine'

class FakeProposals:
    def __init__(self):self.p={}
    def get(self,key):return dict(self.p[key])

def flow(tmp):
    w=tmp/'workspace';w.mkdir()
    source=(ROOT/'workspace'/'cpp_project')
    project=w/'project';project.mkdir()
    for fname in ('ledger.ax','project.json','ledger.cpp','ledger.hpp','format.cpp','format.hpp','test_ledger.cpp','test_format.cpp','test_integration.cpp'):
        (project/fname).write_bytes((source/fname).read_bytes())
    def guard(rel):
        if not isinstance(rel,str) or '..' in Path(rel).parts:raise ValueError('traversal')
        candidate=(w/rel).resolve()
        if not candidate.is_relative_to(w) or not candidate.is_file():raise ValueError('not allowed')
        return candidate
    proposals=FakeProposals()
    f=Orchestrator(db=tmp/'data'/'flow.db',workspace=w,engine=ENGINE,evidence_root=tmp/'data'/'models',guard=guard,proposals=proposals)
    return f,w,proposals

@pytest.fixture
def kit(tmp_path):return flow(tmp_path)

def create(kit):
    f,_,_=kit
    return f.create('Two Account Contract','交易应该保证余额守恒与正确收据映射','project/ledger.ax','project/project.json')

def test_real_cli_specs_and_durable_reopen(kit):
    f,_,_=kit;p=create(kit)
    assert p['status']=='draft'
    assert p['stale'] is False
    result=f.verify_spec(p['id'])
    assert result['status']=='spec_ready'
    assert [s['action'] for s in result['last_verification']['steps']]==['check','plan','verify','gate']
    assert result['last_verification']['steps'][-1]['outcome']=='Approved'
    reopened=Orchestrator(db=f.db,workspace=f.workspace,engine=f.engine,evidence_root=f.evidence_root,guard=f.guard,proposals=f.proposals)
    assert reopened.get(p['id'])['status']=='spec_ready'
    assert reopened.audit(p['id'])['chain_valid']

def test_cannot_bind_before_model_gate(kit):
    f,_,ps=kit;p=create(kit)
    with pytest.raises(FlowConflict):f.attach_candidate(p['id'],'p-'+('1'*22))

def test_spec_change_invalidates_and_fork(kit):
    f,w,_=kit;p=create(kit)
    f.verify_spec(p['id'])
    ax=w/'project/ledger.ax';ax.write_text(ax.read_text()+'\n// source revision\n')
    assert f.get(p['id'])['effective_status']=='stale'
    with pytest.raises(FlowConflict):f.verify_spec(p['id'])
    child=f.fork(p['id'],name='Two Account Contract v2')
    assert child['revision']==2 and child['parent_id']==p['id']
    assert child['stale'] is False and child['status']=='draft'
    assert f.audit(p['id'])['chain_valid']

def test_manifest_mismatch_rejected(kit):
    f,w,_=kit
    meta=w/'project/project.json';data=json.loads(meta.read_text())
    data['spec']='../not-real.ax';meta.write_text(json.dumps(data))
    with pytest.raises(FlowError):create(kit)

def test_correct_candidate_progression_no_auto_release(kit):
    f,_,ps=kit;p=f.verify_spec(create(kit)['id']);k='p-'+'f'*22
    candidate={'id':k,'status':'proposed','manifest':p['manifest'],'spec':p['spec'],
      'current':True,'code_sha256':'ab'*32,'validation':None}
    ps.p[k]=candidate
    attach=f.attach_candidate(p['id'],k)
    assert attach['status']=='candidate_review'
    with pytest.raises(FlowConflict):f.decide(p['id'],'approve_test_only','ab'*32)
    candidate['status']='reviewed'
    assert f.sync(p['id'])['status']=='candidate_apply'
    candidate['status']='applied'
    assert f.sync(p['id'])['status']=='candidate_validate'
    candidate['status']='verified'
    candidate['validation']={'passed':True,'checks':[
        {'step':'spec-model','returncode':0,'outcome':'Bounded'},
        {'step':'spec-gate','returncode':0,'outcome':'Approved'},
        {'step':'cpp-full','returncode':0,'outcome':'Tested'},
        {'step':'cpp-gate','returncode':0,'outcome':'Approved'},]}
    assert f.sync(p['id'])['status']=='decision_pending'
    with pytest.raises(FlowError):f.decide(p['id'],'release-production','ab'*32)
    with pytest.raises(FlowConflict):f.decide(p['id'],'approve_test_only','ba'*32)
    f._cli=lambda *args,**kwargs:{'returncode':0,'outcome':'Approved'}
    accepted=f.decide(p['id'],'approve_test_only','ab'*32)
    assert accepted['decision']['production_release'] is False
    assert accepted['status']=='accepted_test_only'
    with pytest.raises(FlowConflict):f.sync(p['id'])
    assert f.audit(p['id'])['chain_valid']

def test_forged_gate_or_stale_candidate_denied(kit):
    f,_,ps=kit;p=f.verify_spec(create(kit)['id']);k='p-'+'a'*22
    ps.p[k]={'id':k,'status':'proposed','manifest':p['manifest'],'spec':p['spec'],
      'current':True,'code_sha256':'cd'*32,'validation':None}
    f.attach_candidate(p['id'],k)
    ps.p[k]['status']='verified';ps.p[k]['validation']={'passed':True,'checks':[
        {'step':'spec-model','returncode':0,'outcome':'Bounded'},
        {'step':'spec-gate','returncode':0,'outcome':'Approved'},
        {'step':'cpp-full','returncode':0,'outcome':'Tested'},
        {'step':'cpp-gate','returncode':0,'outcome':'Blocked'}]}
    f.sync(p['id'])
    with pytest.raises(FlowConflict):f.decide(p['id'],'approve_test_only','cd'*32)
    ps.p[k]['validation']['checks'][-1]['outcome']='Approved'
    ps.p[k]['current']=False
    with pytest.raises(FlowConflict):f.decide(p['id'],'approve_test_only','cd'*32)

def test_event_chain_tamper_detected(kit):
    f,_,_=kit;p=create(kit)
    assert f.audit(p['id'])['chain_valid']
    with sqlite3.connect(f.db) as cx:
        cx.execute("UPDATE events SET payload='{}' WHERE project_id=?",(p['id'],))
    audit=f.audit(p['id'])
    assert not audit['chain_valid']
    assert audit['issues']

def test_model_only_and_stale_decisions(kit):
    f,w,_=kit
    p=f.create('model scope','只验证模型安全性质与可达状态','project/ledger.ax')
    assert f.verify_spec(p['id'])['status']=='spec_ready'
    with pytest.raises(FlowConflict):f.attach_candidate(p['id'],'p-'+'0'*22)
    (w/'project/ledger.ax').write_text('model Empty {}')
    assert f.get(p['id'])['stale']

def test_deny_path_traversal(kit):
    f,_,_=kit
    with pytest.raises(FlowError):f.create('malicious','非法规格引用应当阻断','../outside.ax')
