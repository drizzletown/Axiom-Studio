"""V0.6 policy, protected checks, multi-file install and rollback acceptance."""
import json
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
from orchestrator import FlowError, FlowConflict

BASE=Path(__file__).resolve().parents[2]
FILES=('ledger.ax','project.json','ledger.hpp','ledger.cpp','format.hpp','format.cpp',
       'test_ledger.cpp','test_format.cpp','test_integration.cpp')

@pytest.fixture
def studio(tmp_path,monkeypatch):
    w=tmp_path/'workspace'/'p';w.mkdir(parents=True)
    for n in FILES:(w/n).write_bytes((BASE/'workspace'/'cpp_project'/n).read_bytes())
    monkeypatch.setattr(server,'WORKSPACE',tmp_path/'workspace')
    monkeypatch.setattr(server,'ROOT',tmp_path)
    monkeypatch.setattr(server,'EVIDENCE',tmp_path/'.studio-data'/'evidence')
    s=server.Studio()
    yield s
    s.executor.shutdown(wait=True,cancel_futures=True)

def prepare(s):
    p=s.flow.create('multi-target','可追溯的两目标候选比较','p/ledger.ax','p/project.json')
    draft=s.production.draft(p['id']);r=[{**x,'text':'验证性质 '+x['property']+' 在所有实现候选中得到满足'} for x in draft['suggested']]
    s.production.freeze(p['id'],r,p['baseline'])
    assert s.flow.verify_spec(p['id'])['status']=='spec_ready'
    return p

def replacement(s,tail=''):
    w=server.WORKSPACE/'p'
    return {name:(w/name).read_text()+'\n// '+tail+'\n' for name in ('ledger.cpp','format.cpp')}

def fake_pass(*args):return {'passed':True,'checks':[{'step':'cpp_gate','data':{'decision':'Approved'},'returncode':0}], 'failed_at':None,'scope':'TEST FAKE'}

def test_two_targets_with_two_options_and_rollback(studio,monkeypatch):
    p=prepare(studio);b=studio.batches
    t=['p/ledger.cpp','p/format.cpp']
    txn=b.create(p['id'],t);bid=txn['id']
    a=replacement(studio,'alternative-a');b.stage(bid,'方案 A',a)
    alt_a=b.get(bid)['options'][0]
    c=replacement(studio,'alternative-b');b.stage(bid,'方案 B',c)
    alt_b=b.get(bid)['options'][1]
    # This unit test exercises state policy with a mock. Real engine integration is separate.
    monkeypatch.setattr(b,'_verify',fake_pass)
    with pytest.raises(FlowError):b.evaluate(bid,alt_a['id'],trusted=False)
    assert b.evaluate(bid,alt_a['id'],trusted=True)['options'][0]['state']=='tested'
    assert b.evaluate(bid,alt_b['id'],trusted=True)['options'][1]['state']=='tested'
    compare=b.compare(bid)
    assert len(compare['comparison'])==2 and compare['automatic_selection'] is False
    with pytest.raises(FlowError):b.select(bid,alt_a['id'],alt_a['digest'],'ai_auto_select')
    with pytest.raises(FlowConflict):b.select(bid,alt_a['id'],'0'*64,'human_selected_after_comparison')
    b.select(bid,alt_b['id'],alt_b['digest'],'human_selected_after_comparison')
    originals={n:(server.WORKSPACE/'p'/n).read_bytes() for n in FILES}
    with pytest.raises(FlowError):b.apply(bid,alt_b['digest'],'agent_apply')
    installed=b.apply(bid,alt_b['digest'],'human_authorized_multi_file_apply')
    assert installed['state']=='deployed_unverified'
    assert (server.WORKSPACE/'p/ledger.cpp').read_text()==c['ledger.cpp']
    assert (server.WORKSPACE/'p/format.cpp').read_text()==c['format.cpp']
    for protected in ('ledger.ax','project.json','test_ledger.cpp','test_integration.cpp'):
        assert (server.WORKSPACE/'p'/protected).read_bytes()==originals[protected]
    assert b.audit(bid)['valid']
    with pytest.raises(FlowError):b.decide(bid,alt_b['digest'],'production_release')
    # Human abort returns entire project to exact pre-transaction inputs.
    b.rollback(bid,'human_reject_and_rollback')
    assert b.get(bid)['state']=='rolled_back'
    assert all((server.WORKSPACE/'p'/n).read_bytes()==originals[n] for n in FILES)


def test_fail_closed_stale_tests_and_immutable_options(studio,monkeypatch):
    p=prepare(studio);b=studio.batches
    bid=b.create(p['id'],['p/ledger.cpp','p/format.cpp'])['id']
    with pytest.raises(FlowError):b.stage(bid,'unsafe',{'test_ledger.cpp':'// overwrite','ledger.cpp':'hey'})
    b.stage(bid,'safe',replacement(studio,'safe'))
    oid=b.get(bid)['options'][0]['id']
    (server.WORKSPACE/'p/test_integration.cpp').write_text('// malicious change')
    with pytest.raises(FlowConflict):b.evaluate(bid,oid,True)
    with pytest.raises(FlowConflict):b.compare(bid)


def test_failure_stays_blocked_and_audit_tamper(studio,monkeypatch):
    p=prepare(studio);b=studio.batches
    bid=b.create(p['id'],['p/ledger.cpp','p/format.cpp'])['id']
    b.stage(bid,'broken',replacement(studio,'broken'))
    monkeypatch.setattr(b,'_verify',lambda *a:{'passed':False,'checks':[],'failed_at':'cpp_full','scope':'mock'})
    oid=b.get(bid)['options'][0]['id']
    b.evaluate(bid,oid,True)
    with pytest.raises(FlowConflict):b.select(bid,oid,b.get(bid)['options'][0]['digest'],'human_selected_after_comparison')
    path=b.home/'records'/(bid+'.json');j=json.loads(path.read_text());j['events'][0]['kind']='forged';path.write_text(json.dumps(j))
    assert b.audit(bid)['valid'] is False
    with pytest.raises(FlowConflict):b.stage(bid,'next',replacement(studio,'next'))


def test_restart_can_recover_record_and_old_evidence_never_inherits(studio,monkeypatch):
    p=prepare(studio);b=studio.batches
    bid=b.create(p['id'],['p/ledger.cpp','p/format.cpp'])['id']
    b.stage(bid,'a',replacement(studio,'a'))
    assert server.Studio().batches.get(bid)['id']==bid
    assert not b.get(bid)['release_authorized']

def test_live_verification_failure_auto_rolls_back(studio,monkeypatch):
    p=prepare(studio);b=studio.batches
    bid=b.create(p['id'],['p/ledger.cpp','p/format.cpp'])['id']
    code=replacement(studio,'live-fail')
    b.stage(bid,'candidate',code);opt=b.get(bid)['options'][0]
    monkeypatch.setattr(b,'_verify',fake_pass)
    b.evaluate(bid,opt['id'],True)
    b.select(bid,opt['id'],opt['digest'],'human_selected_after_comparison')
    original=(server.WORKSPACE/'p/ledger.cpp').read_bytes()
    b.apply(bid,opt['digest'],'human_authorized_multi_file_apply')
    monkeypatch.setattr(b,'_verify',lambda *a:{'passed':False,'checks':[],'failed_at':'cpp_gate','scope':'mock'})
    result=b.verify_live(bid,True)
    assert result['state']=='rolled_back'
    assert (server.WORKSPACE/'p/ledger.cpp').read_bytes()==original
    assert not (b.home/'backups'/bid).exists()
    with pytest.raises(FlowConflict):b.decide(bid,opt['digest'],'human_approve_test_only')


def test_failure_repair_packet_and_corrupted_evidence(studio,monkeypatch):
    p=prepare(studio);b=studio.batches
    bid=b.create(p['id'],['p/ledger.cpp','p/format.cpp'])['id']
    b.stage(bid,'broken',replacement(studio,'bug'))
    opt=b.get(bid)['options'][0]
    monkeypatch.setattr(b,'_verify',lambda *a:{'passed':False,'checks':[{
        'step':'cpp_full','returncode':2,'data':{'report':{'failed_targets':['integration']}},'stderr':'bad output'}],
        'failed_at':'cpp_full','scope':'mock'})
    b.evaluate(bid,opt['id'],True)
    packet=b.repair_packet(bid,opt['id'])
    assert packet['packet']['failed_at']=='cpp_full'
    assert packet['packet']['failed_steps'][0]['failed_targets']==['integration']
    # A saved result can't be quietly rewritten to passed: chain includes result digest.
    path=b.home/'records'/(bid+'.json');record=json.loads(path.read_text())
    record['options'][0]['verification']['result']['passed']=True
    path.write_text(json.dumps(record))
    assert b.audit(bid)['valid'] is False
    with pytest.raises(FlowConflict):b.select(bid,opt['id'],opt['digest'],'human_selected_after_comparison')


def test_crash_before_rename_recovery(studio,monkeypatch):
    p=prepare(studio);b=studio.batches
    bid=b.create(p['id'],['p/ledger.cpp','p/format.cpp'])['id']
    b.stage(bid,'candidate',replacement(studio,'recover'))
    opt=b.get(bid)['options'][0]
    monkeypatch.setattr(b,'_verify',fake_pass);b.evaluate(bid,opt['id'],True)
    b.select(bid,opt['id'],opt['digest'],'human_selected_after_comparison')
    path=b.home/'records'/(bid+'.json');obj=json.loads(path.read_text())
    obj['state']='installing';b._event(obj,'installing',{'test':'crash_before_rename'});b._store(obj)
    assert b.rollback(bid,'human_reject_and_rollback')['state']=='rolled_back'
