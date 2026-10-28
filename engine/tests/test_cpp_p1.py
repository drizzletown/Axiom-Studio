"""P1 acceptance: actual compiled C++ candidates and immutable evidence linkage."""
import json
from pathlib import Path

import pytest

from axiom.cpp import run_cpp, load_binding
from axiom.lang import AxError, parse, validate
from axiom.checker import verify
from axiom.store import Workspace

ROOT=Path(__file__).parents[1]
CPP=ROOT/'cpp'
SPEC=ROOT/'examples'/'two_account.ax'

@pytest.fixture(scope='module')
def ir(): return validate(parse(SPEC.read_text()))

@pytest.fixture(scope='module')
def correct(ir): return run_cpp(ir,CPP/'correct.cpp',CPP/'binding.json')

@pytest.fixture
def recorded(tmp_path,ir,correct):
    w=Workspace(tmp_path)
    w.record(ir,verify(ir))
    w.record_cpp(ir,*correct)
    return w


def test_compiled_correct_implemented_observations(ir,correct):
    report,artifacts=correct
    assert report['outcome']=='Tested'
    assert report['scope']['tested_pairs']==16
    assert report['scope']['observed_calls_per_variant']==32
    assert report['variants']['normal']['execution_exit']==0
    assert report['variants']['sanitized']['execution_exit']==0
    assert report['variants']['normal']['binary_digest']!=report['variants']['sanitized']['binary_digest']
    assert set(artifacts)=={'source','binding','harness','context','normal','sanitized'}


def test_cpp_gate_requires_separately_recorded_model_evidence(tmp_path,ir,correct):
    w=Workspace(tmp_path)
    w.record_cpp(ir,*correct)
    g=w.gate_cpp(ir,CPP/'correct.cpp',CPP/'binding.json')
    assert g['decision']=='Blocked'
    assert 'MISSING_CURRENT_MODEL_EVIDENCE' in g['reasons']


def test_cpp_gate_approves_observed_prototype_only(recorded,ir):
    gate=recorded.gate_cpp(ir,CPP/'correct.cpp',CPP/'binding.json')
    assert gate['decision']=='Approved'
    assert gate['target']=='cpp-tested-prototype' and gate['assurance']=='Tested'
    assert 'not a refinement proof' in gate['scope_note']


@pytest.mark.parametrize('name,reason',[
    ('broken_mapping.cpp','E_CPP_REFINEMENT_MISMATCH'),
    ('broken_boundary.cpp','E_CPP_REFINEMENT_MISMATCH'),
    ('broken_frozen_input.cpp','E_CPP_REFINEMENT_MISMATCH'),
    ('broken_overflow.cpp','E_CPP_SANITIZER_OR_CRASH'),
])
def test_real_cpp_defects_rejected(ir,name,reason):
    report,_=run_cpp(ir,CPP/name,CPP/'binding.json')
    assert report['outcome']=='Violated'
    assert report['reason']==reason
    assert report['counterexample'] is not None


def test_compile_failure_yields_unknown(ir):
    report,_=run_cpp(ir,CPP/'broken_compile.cpp',CPP/'binding.json')
    assert report['outcome']=='Unknown'
    assert report['reason']=='E_CPP_BUILD'


def test_changed_candidate_blocks_old_evidence(recorded,ir,tmp_path):
    path=tmp_path/'candidate.cpp'
    path.write_bytes((CPP/'correct.cpp').read_bytes()+b'\n// added change')
    assert recorded.gate_cpp(ir,path,CPP/'binding.json')['decision']=='Blocked'


def test_changed_binding_blocks_old_evidence(recorded,ir,tmp_path):
    b=json.loads((CPP/'binding.json').read_text())
    b['assumptions'].append('extra assumption')
    p=tmp_path/'binding.json';p.write_text(json.dumps(b))
    assert recorded.gate_cpp(ir,CPP/'correct.cpp',p)['decision']=='Blocked'


def test_changed_compiler_optimization_blocks_old_evidence(recorded,ir):
    assert recorded.gate_cpp(ir,CPP/'correct.cpp',CPP/'binding.json',optimization='2')['decision']=='Blocked'


def test_changed_spec_blocks_old_evidence(recorded,ir):
    src=SPEC.read_text().replace('case m > 0','case m >= 0')
    changed=validate(parse(src))
    assert recorded.gate_cpp(changed,CPP/'correct.cpp',CPP/'binding.json')['decision']=='Blocked'


def test_binary_content_tamper_blocks_gate(recorded,ir):
    runs=recorded.cpp_runs()
    ev=recorded.get(runs[0]['evidence_digest'])
    binary=ev['binary_digests']['normal']
    (recorded.objects/binary.split(':',1)[1]).write_bytes(b'tampered')
    assert recorded.gate_cpp(ir,CPP/'correct.cpp',CPP/'binding.json')['decision']=='Blocked'


def test_binding_unrecognized_state_map_rejected(ir,tmp_path):
    b=json.loads((CPP/'binding.json').read_text());b['state_map']={'a':'a','b':'x'}
    p=tmp_path/'binding.json';p.write_text(json.dumps(b))
    with pytest.raises(AxError,match='E_CPP_BINDING'):
        load_binding(p,ir)


def test_unknown_model_cannot_gain_implementation_claim(ir,tmp_path):
    broken=validate(parse((ROOT/'examples'/'broken_conservation.ax').read_text().replace('BrokenLedger','TwoAccount')))
    # Deliberately wrong abstract model is rejected before generating tests.
    with pytest.raises(AxError,match='E_CPP_MODEL'):
        run_cpp(broken,CPP/'correct.cpp',CPP/'binding.json')


def test_cpp_record_contains_sources_and_compiler_context(recorded):
    ev=recorded.get(recorded.cpp_runs()[0]['evidence_digest'])
    keys=set(ev['artifact_digests'])
    assert keys=={'source','binding','harness','context','normal','sanitized'}
    for h in ev['artifact_digests'].values():
        assert (recorded.objects/h.split(':',1)[1]).exists()
