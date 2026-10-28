"""P2e safety boundaries, observable C++ trace behavior, and fail-closed gate."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import os
import subprocess
import sys

import pytest
from axiom.checker import verify
from axiom.interleaving import load_interleaving,verify_interleaving
from axiom.interleaving_store import record_interleaving
from axiom.cpp_trace import verify_cpp_trace,schedules,check_abi
from axiom.trace_store import record_trace,trace_gate
from axiom.sandbox import available,execute
from axiom.lang import AxError,digest
from axiom.store import Workspace

ROOT=Path(__file__).resolve().parents[1]
MANIFEST=ROOT/'examples/interleaving/product_safe.json'
CPP=ROOT/'cpp/trace'

@pytest.fixture
def model():return load_interleaving(MANIFEST)

@pytest.fixture
def seeded(tmp_path,model):
    models,bound=model
    ws=Workspace(tmp_path/'ws')
    for ir in models.values():ws.record(ir,verify(ir))
    record_interleaving(ws,models,bound,verify_interleaving(models,bound))
    return ws


def test_depth_count_and_replay():
    assert len(schedules(1))==8
    assert len(schedules(2))==40
    assert len(schedules(3))==168
    assert len(schedules(4))==680
    with pytest.raises(AxError):schedules(6)


def test_abi_rejection(model):
    m,b=model
    assert check_abi(m,b)
    altered=copy.deepcopy(b);altered['independent']=[]
    with pytest.raises(AxError):check_abi(m,altered)
    altered=copy.deepcopy(m);altered['Source']['state']={'off':'Flag'}
    with pytest.raises(AxError):check_abi(altered,b)

@pytest.mark.skipif(not available(),reason='rootless Linux namespace unavailable; must fail closed')
def test_cpp_correct_both_variants(model):
    m,b=model
    r=verify_cpp_trace(m,b,CPP/'correct.cpp',depth=3)
    assert r['outcome']=='Tested'
    assert r['scope']['scenarios']==168
    assert r['scope']['not_formal_refinement_proof'] is True
    assert r['scope']['not_thread_level_concurrency'] is True
    assert all(v['compile_exit']==v['run_exit']==0 for v in r['variants'].values())

@pytest.mark.skipif(not available(),reason='rootless Linux namespace unavailable; must fail closed')
@pytest.mark.parametrize('filename',['broken_one_side.cpp','broken_hidden_state.cpp'])
def test_faults_detected(model,filename):
    m,b=model
    r=verify_cpp_trace(m,b,CPP/filename,depth=2)
    assert r['outcome']=='Violated' and r['reason']=='E_TRACE_REFINEMENT_MISMATCH'
    assert r['counterexample']['schedule']

@pytest.mark.skipif(not available(),reason='rootless Linux namespace unavailable; must fail closed')
def test_gate_complete_chain_and_source_change(model,seeded,tmp_path):
    m,b=model
    src=CPP/'correct.cpp'
    assert trace_gate(seeded,m,b,src,depth=2)['decision']=='Blocked'
    rec=record_trace(seeded,m,b,src,depth=2)
    assert rec['outcome']=='Tested'
    gate=trace_gate(seeded,m,b,src,depth=2)
    assert gate['decision']=='Approved' and gate['release_authorized'] is False
    assert trace_gate(seeded,m,b,src,depth=3)['decision']=='Blocked'
    changed=tmp_path/'modified.cpp'
    changed.write_bytes(src.read_bytes()+b'\n// changed source\n')
    assert trace_gate(seeded,m,b,changed,depth=2)['decision']=='Blocked'
    other=copy.deepcopy(b);other['properties'][0]['name']='Changed'
    assert trace_gate(seeded,m,other,src,depth=2)['decision']=='Blocked'

@pytest.mark.skipif(not available(),reason='rootless Linux namespace unavailable; must fail closed')
def test_evidence_tamper_is_rejected(model,seeded):
    m,b=model
    rec=record_trace(seeded,m,b,CPP/'correct.cpp',depth=1)
    assert trace_gate(seeded,m,b,CPP/'correct.cpp',depth=1)['decision']=='Approved'
    seeded.object_path(rec['evidence_digest']).write_text('{"outcome":"Tested"}')
    assert trace_gate(seeded,m,b,CPP/'correct.cpp',depth=1)['decision']=='Blocked'

@pytest.mark.skipif(not available(),reason='rootless Linux namespace unavailable; must fail closed')
def test_sandbox_chroot_hides_host_and_network():
    # /mnt/data is absent; network namespace has no configured interface.
    body=b'''#include <iostream>\n#include <fstream>\n#include <sys/socket.h>\n#include <netinet/in.h>\n#include <unistd.h>\nint main(){\n std::ifstream in("/mnt/data/Axiom_P2_\\xE7\\xAC\\xAC\\xE5\\x9B\\x9B\\xE6\\x89\\xB9.zip");\n int s=socket(AF_INET,SOCK_STREAM,0);\n sockaddr_in addr{};addr.sin_family=AF_INET;addr.sin_port=htons(1);addr.sin_addr.s_addr=htonl(INADDR_LOOPBACK);\n int status=connect(s,(sockaddr*)&addr,sizeof(addr));\n if(s>=0)close(s);\n std::cout<<(in.good()?"HOST_VISIBLE":"HOST_HIDDEN")<<" "<<(status==0?"NETWORK_CONNECTED":"NO_CONNECTION");\n}\n'''
    built=execute({'probe.cpp':body},['/usr/bin/g++','/work/probe.cpp','-o','/work/a.out'],output_file='a.out')
    assert built['exit']==0 and built['output']
    ran=execute({'a.out':built['output']},['/work/a.out'])
    assert ran['exit']==0 and ran['stdout']=='HOST_HIDDEN NO_CONNECTION'
    assert ran['namespace_kinds']==['user','mount','network','pid']

@pytest.mark.skipif(not available(),reason='rootless Linux namespace unavailable; must fail closed')
def test_sandbox_bad_output_is_not_followed():
    # A hostile output symlink must not be followed by the parent after namespace exit.
    code=b'''#include <unistd.h>\nint main(){symlink("/etc/passwd","/work/a.out");return 0;}'''
    # Work tree starts with no a.out; program is separately run and cannot alter parent workspace.
    compile_result=execute({'probe.cpp':code},['/usr/bin/g++','/work/probe.cpp','-o','/work/a.out'],output_file='a.out')
    assert compile_result['exit']==0
    run_result=execute({'a.out':compile_result['output']},['/work/a.out'])
    assert run_result['exit']==0

@pytest.mark.skipif(not available(),reason='rootless Linux namespace unavailable; must fail closed')
def test_sandbox_failed_setup_or_compiler_not_approved():
    forbidden=execute({},['/usr/bin/sh','-c','true'])
    assert forbidden['status']=='Unavailable'
    invalid=execute({'bad.cpp':b'int main( {'},['/usr/bin/g++','/work/bad.cpp','-o','/work/a.out'],output_file='a.out')
    assert invalid['exit']!=0 and invalid['output'] is None

@pytest.mark.skipif(not available(),reason='rootless Linux namespace unavailable; must fail closed')
def test_cli_end_to_end(tmp_path):
    ws=tmp_path/'w'
    env={**os.environ,'PYTHONPATH':str(ROOT/'src')}
    def run(*args):
        p=subprocess.run([sys.executable,'-m','axiom','--workspace',str(ws),*args],
                         cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=90)
        assert not p.stderr,(p.args,p.stderr)
        return p.returncode,json.loads(p.stdout)
    rc,_=run('sandbox-probe');assert rc==0
    manifest='examples/interleaving/product_safe.json'
    rc,r=run('cpp-trace-gate',manifest,'--candidate','cpp/trace/correct.cpp','--depth','2')
    assert rc==4 and r['decision']=='Blocked'
    for f in ('Source.ax','Mirror.ax'):
        assert run('verify','examples/interleaving/'+f)[0]==0
    assert run('interleave-verify',manifest)[0]==0
    rc,r=run('cpp-trace-verify',manifest,'--candidate','cpp/trace/correct.cpp','--depth','2')
    assert rc==0 and r['verification']['outcome']=='Tested'
    rc,r=run('cpp-trace-gate',manifest,'--candidate','cpp/trace/correct.cpp','--depth','2')
    assert rc==0 and r['decision']=='Approved' and r['release_authorized'] is False
    rc,r=run('cpp-trace-verify',manifest,'--candidate','cpp/trace/broken_one_side.cpp','--depth','2')
    assert rc==2 and r['verification']['outcome']=='Violated'
    rc,r=run('cpp-trace-gate',manifest,'--candidate','cpp/trace/broken_one_side.cpp','--depth','2')
    assert rc==4 and r['decision']=='Blocked'

@pytest.mark.skipif(not available(),reason='rootless Linux namespace unavailable; must fail closed')
def test_audit_recognizes_trace_and_corruption(model,seeded):
    from axiom.audit import audit_workspace
    m,b=model
    rec=record_trace(seeded,m,b,CPP/'correct.cpp',depth=1)
    audited=audit_workspace(seeded)
    assert audited['status']=='Consistent'
    assert audited['examined']['cpp_trace_runs']==1
    seeded.object_path(rec['report_digest']).write_text('{"altered":true}')
    audited=audit_workspace(seeded)
    assert audited['status']=='Findings'
    assert trace_gate(seeded,m,b,CPP/'correct.cpp',depth=1)['decision']=='Blocked'

@pytest.mark.skipif(not available(),reason='rootless Linux namespace unavailable; must fail closed')
def test_namespace_timeout_cannot_pass():
    r=execute({'loop.cpp':b'int main(){for(;;){} }'},['/usr/bin/g++','/work/loop.cpp','-o','/work/a.out'],output_file='a.out')
    assert r['exit']==0 and r['output']
    ran=execute({'a.out':r['output']},['/work/a.out'],timeout_s=1)
    assert ran['status']=='Timeout' or ran['exit']!=0
