"""P2 conservative evidence reuse and typed impact regression suite."""
from pathlib import Path
import copy
import pytest
from axiom.lang import parse,validate, digest
from axiom.checker import verify, obligations
from axiom.store import Workspace
from axiom.evolution import impact, typed_graph, behavior_digest

EXAMPLE=Path(__file__).parents[1]/'examples'/'two_account.ax'

def model():return validate(parse(EXAMPLE.read_text()))

def new_property(ir,name='StrictBalance', expr=None):
    ir=copy.deepcopy(ir)
    ir['properties'].append({'name':name,'kind':'invariant',
        'expr':expr or {'op':'>=','args':[{'op':'ref','name':'a'},{'op':'lit','value':0}]}})
    return validate(ir)


def established(workspace,ir):
    r=verify(ir)
    assert r['outcome']=='Bounded'
    return workspace.record(ir,r)


def test_typed_graph_has_action_and_property_dependency():
    ir=model();g=typed_graph(ir)
    assert g['behavior_digest']==behavior_digest(ir)
    assert 'state/a' in g['nodes']
    assert {'source':'action/move','target':'property/Conservation','kind':'may-affect'} in g['edges']


def test_added_property_preserves_old_evidence_but_blocks_until_new_evidence(tmp_path):
    ir=model();new=new_property(ir);w=Workspace(tmp_path)
    old=established(w,ir)
    diff=w.record_impact(ir,new)
    assert diff['behavior_unchanged']
    assert diff['requires_new_property_evidence']==['StrictBalance']
    g=w.gate_model_evolved(new)
    assert g['decision']=='Blocked' and len(g['missing_obligations'])==1
    assert g['missing_obligations'][0].endswith('/StrictBalance')
    assert all(v==old['run_id'] for v in g['covered_by_run'].values())
    established(w,new)
    g=w.gate_model_evolved(new)
    assert g['decision']=='Approved' and not g['missing_obligations']


def test_whitespace_change_does_not_expire_model_evidence(tmp_path):
    ir=model();w=Workspace(tmp_path);established(w,ir)
    fresh=validate(parse('// comment\n'+EXAMPLE.read_text()+'\n'))
    assert w.gate_model_evolved(fresh)['decision']=='Approved'


def test_changed_property_same_name_invalidates_just_property(tmp_path):
    old=model();new=copy.deepcopy(old)
    new['properties'][0]['expr']={'op':'>=', 'args':[{'op':'ref','name':'a'},{'op':'lit','value':1}]}
    w=Workspace(tmp_path);established(w,old)
    result=w.gate_model_evolved(new)
    assert result['missing_obligations']==['TwoAccount/model/property/NonNegative']
    assert any(k.endswith('Conservation') for k in result['covered_by_run'])


def test_changed_action_invalidates_all_old_obligations(tmp_path):
    old=model();new=copy.deepcopy(old)
    # Different allowed transitions but still valid syntax and finite domains.
    new['actions'][0]['cases'][0]['ensures']={'op':'and','args':[
        new['actions'][0]['cases'][0]['ensures'],
        {'op':'==','args':[{'op':'ref','name':'m'},{'op':'lit','value':1}]}
    ]}
    w=Workspace(tmp_path);established(w,old)
    d=impact(old,new)
    assert not d['behavior_unchanged']
    assert not d['potentially_reusable_properties']
    assert 'property/Conservation' in d['affected_nodes']
    g=w.gate_model_evolved(new)
    assert g['decision']=='Blocked' and not g['covered_by_run']
    assert len(g['missing_obligations'])==len(obligations(new))


def test_changed_state_domain_invalidates_all(tmp_path):
    old=model();new=copy.deepcopy(old);new['types']['Amount']['max']=4
    w=Workspace(tmp_path);established(w,old)
    assert not impact(old,new)['behavior_unchanged']
    assert w.gate_model_evolved(new)['decision']=='Blocked'


def test_different_model_name_invalidates(tmp_path):
    old=model();new=copy.deepcopy(old);new['model']='Different'
    w=Workspace(tmp_path);established(w,old)
    assert w.gate_model_evolved(new)['decision']=='Blocked'


def test_corrupt_evidence_fails_closed(tmp_path):
    ir=model();w=Workspace(tmp_path);r=established(w,ir)
    ev=w.objects/r['evidence_digest'].split(':')[1]
    ev.write_bytes(b'{}')
    gate=w.gate_model_evolved(ir)
    assert gate['decision']=='Blocked'
    assert gate['rejected'][0]['reason']=='EVIDENCE_INTEGRITY_OR_FORMAT_ERROR'


def test_unknown_evidence_not_reused(tmp_path):
    ir=model();w=Workspace(tmp_path)
    from axiom.checker import verify
    report=verify(ir,max_transitions=1)
    assert report['outcome']=='Unknown'
    w.record(ir,report)
    assert w.gate_model_evolved(ir)['decision']=='Blocked'


def test_test_evidence_from_cpp_cannot_satisfy_model_gate(tmp_path):
    ir=model();w=Workspace(tmp_path)
    assert w.gate_model_evolved(ir)['decision']=='Blocked'


def test_impact_digest_and_graph_objects_are_stored(tmp_path):
    ir=model();n=new_property(ir);w=Workspace(tmp_path)
    r=w.record_impact(ir,n)
    assert w.get(r['old_graph_digest'])['model']=='TwoAccount'
    assert w.get(r['new_graph_digest'])['model']=='TwoAccount'


def test_no_cpp_gate_from_p2_model_evidence(tmp_path):
    ir=model();w=Workspace(tmp_path);established(w,ir)
    assert w.gate_model_evolved(ir)['decision']=='Approved'
    assert w.gate_cpp(ir,Path(__file__).parents[1]/'cpp'/'correct.cpp',
                      Path(__file__).parents[1]/'cpp'/'binding.json')['decision']=='Blocked'
