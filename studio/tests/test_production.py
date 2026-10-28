"""V0.4 production protocol: guarantees and fail-closed regression tests."""
from pathlib import Path
import copy
import json
import sqlite3
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from orchestrator import Orchestrator,FlowConflict,FlowError
from production import Production

ROOT=Path(__file__).resolve().parents[2]

class Proposals:
    def __init__(self):self.data={}
    def get(self,k):return dict(self.data[k])

@pytest.fixture
def kit(tmp_path):
    w=tmp_path/'workspace';w.mkdir();(w/'p').mkdir()
    source=ROOT/'workspace'/'cpp_project'
    for fn in ('ledger.ax','project.json'):(w/'p'/fn).write_bytes((source/fn).read_bytes())
    def guard(name):
        p=(w/name).resolve()
        if not p.is_relative_to(w) or not p.is_file():raise ValueError('invalid file')
        return p
    ps=Proposals()
    f=Orchestrator(db=tmp_path/'store'/'flow.sqlite',workspace=w,engine=ROOT/'engine',
        evidence_root=tmp_path/'store'/'model',guard=guard,proposals=ps)
    prod=Production(f)
    p=f.create('Production Test','需要两个账户的有限状态余额守恒','p/ledger.ax','p/project.json')
    return prod,f,p,w,ps

def reqs(prod,p):
    d=prod.draft(p['id'])
    return [{**r,'text':'要求 '+r['property']+' 能够被模型验证并保持为安全不变量'} for r in d['suggested']]

def freeze(prod,p):return prod.freeze(p['id'],reqs(prod,p),p['baseline'])

def accepted(kit,monkeypatch):
    prod,f,p,w,ps=kit
    f.verify_spec(p['id'])
    k='p-'+'a'*22
    ps.data[k]={'id':k,'status':'proposed','manifest':'p/project.json','spec':'p/ledger.ax',
        'current':True,'code_sha256':'fa'*32,'validation':None}
    f.attach_candidate(p['id'],k)
    ps.data[k]['status']='verified'
    ps.data[k]['validation']={'passed':True,'checks':[
        {'step':'spec-model','returncode':0,'outcome':'Bounded'},
        {'step':'spec-gate','returncode':0,'outcome':'Approved'},
        {'step':'cpp-full','returncode':0,'outcome':'Tested'},
        {'step':'cpp-gate','returncode':0,'outcome':'Approved'}]}
    f.sync(p['id'])
    monkeypatch.setattr(f,'_cli',lambda *a,**k:{'returncode':0,'outcome':'Approved'})
    f.decide(p['id'],'approve_test_only','fa'*32)
    return k

def test_draft_parses_actual_model(kit):
    prod,_,p,_,_=kit
    draft=prod.draft(p['id'])
    assert {r['property'] for r in draft['suggested']}=={'NonNegative','Conservation'}
    assert draft['schema']=='ax-production/0.4'

def test_freeze_contract_idempotence_rejected(kit):
    prod,_,p,_,_=kit
    c=freeze(prod,p)
    assert len(c['body']['requirements'])==2
    assert prod.overview(p['id'])['contract_digest']==c['digest']
    with pytest.raises(FlowConflict):freeze(prod,p)

def test_unverified_requirement_blocks_production(kit):
    prod,_,p,_,_=kit
    rs=reqs(prod,p)
    rs.append({'id':'REQ-999','kind':'unverified','text':'每秒至少完成若干次交易且按 SLA 进行验证'})
    prod.freeze(p['id'],rs,p['baseline'])
    status=prod.overview(p['id'])
    assert 'REQUIREMENT_NOT_MODEL_SUPPORTED:REQ-999' in status['blockers']
    assert status['eligible_for_live_recheck'] is False

def test_wrong_property_and_duplicate_rejected(kit):
    prod,_,p,_,_=kit
    rs=reqs(prod,p)
    rs[0]['property']='Missing'
    with pytest.raises(FlowError):prod.freeze(p['id'],rs,p['baseline'])
    rs=reqs(prod,p)
    rs[1]['id']=rs[0]['id']
    with pytest.raises(FlowError):prod.freeze(p['id'],rs,p['baseline'])

def test_stale_and_evolution_separation(kit):
    prod,f,p,w,_=kit
    c=freeze(prod,p)
    task=prod.task_packet(p['id'])
    assert task['packet']['contract_digest']==c['digest']
    assert 'test sources' in task['packet']['prohibited_changes']
    assert task['digest']==prod.task_packet(p['id'])['digest']
    (w/'p/ledger.ax').write_text((w/'p/ledger.ax').read_text()+'\n// changed\n')
    assert 'SPEC_OR_MANIFEST_STALE' in prod.overview(p['id'])['blockers']
    with pytest.raises(FlowConflict):prod.task_packet(p['id'])
    child=f.fork(p['id'])
    assert prod.overview(child['id'])['contract_digest'] is None
    assert 'PRODUCTION_CONTRACT_MISSING' in prod.overview(child['id'])['blockers']

def test_graph_has_explicit_provenance(kit):
    prod,_,p,_,_=kit
    freeze(prod,p)
    graph=prod.graph(p['id'])
    assert any(e['from']=='requirement:REQ-001' and e['kind']=='mapped_by_human' for e in graph['edges'])
    assert any(n['id']=='property:Conservation' for n in graph['nodes'])

def test_issue_requires_human_verification_and_digest(kit):
    prod,_,p,_,_=kit
    c=freeze(prod,p)
    with pytest.raises(FlowError):prod.issue_passport(p['id'],'ship-to-production',c['digest'])
    with pytest.raises(FlowConflict):prod.issue_passport(p['id'],'issue_test_only',c['digest'])

def test_successful_passport_is_only_proto(kit,monkeypatch):
    prod,f,p,_,_=kit
    c=freeze(prod,p);accepted(kit,monkeypatch)
    status=prod.overview(p['id'])
    assert status['eligible_for_live_recheck']
    passpt=prod.issue_passport(p['id'],'issue_test_only',c['digest'])
    assert passpt['passport']['scope']=='cpp-tested-prototype'
    assert passpt['passport']['production_release'] is False
    rows=prod.passports(p['id'])['passports']
    assert len(rows)==1 and rows[0]['record_integrity'] and rows[0]['snapshot_matches_current']
    assert not rows[0]['live_gate_rechecked']

def test_failed_live_gate_blocks_issue(kit,monkeypatch):
    prod,f,p,_,_=kit
    c=freeze(prod,p);accepted(kit,monkeypatch)
    monkeypatch.setattr(f,'_cli',lambda *a,**k:{'returncode':2,'outcome':'Blocked'})
    with pytest.raises(FlowConflict):prod.issue_passport(p['id'],'issue_test_only',c['digest'])
    assert prod.passports(p['id'])['passports']==[]

def test_audit_chain_tamper_blocks_issue(kit,monkeypatch):
    prod,f,p,_,_=kit
    c=freeze(prod,p);accepted(kit,monkeypatch)
    with sqlite3.connect(f.db) as cx:
        cx.execute("UPDATE events SET kind='forged' WHERE project_id=? AND kind='project_created'",(p['id'],))
    assert 'PROCESS_AUDIT_CHAIN_INVALID' in prod.overview(p['id'])['blockers']
    with pytest.raises(FlowConflict):prod.issue_passport(p['id'],'issue_test_only',c['digest'])

def test_contract_database_tamper_detected(kit):
    prod,f,p,_,_=kit
    freeze(prod,p)
    with sqlite3.connect(f.db) as cx:
        cx.execute("UPDATE production_contracts SET body='{}' WHERE project_id=?",(p['id'],))
    with pytest.raises(FlowConflict):prod.overview(p['id'])

def test_old_passport_after_spec_change_not_fresh(kit,monkeypatch):
    prod,_,p,w,_=kit
    c=freeze(prod,p);accepted(kit,monkeypatch)
    prod.issue_passport(p['id'],'issue_test_only',c['digest'])
    (w/'p/ledger.ax').write_text((w/'p/ledger.ax').read_text()+'\n// drift')
    assert prod.passports(p['id'])['passports'][0]['snapshot_matches_current'] is False
    assert 'SPEC_OR_MANIFEST_STALE' in prod.overview(p['id'])['blockers']
