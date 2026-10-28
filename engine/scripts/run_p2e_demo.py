"""Reproducible P2e demo: model evidence + three C++ candidates + proto-gate."""
from __future__ import annotations
import json
from pathlib import Path
import sys
import tempfile
from axiom.interleaving import load_interleaving,verify_interleaving
from axiom.interleaving_store import record_interleaving
from axiom.checker import verify
from axiom.store import Workspace
from axiom.trace_store import record_trace,trace_gate
from axiom.sandbox import available

ROOT=Path(__file__).resolve().parents[1]
MODELS,BOUND=load_interleaving(ROOT/'examples/interleaving/product_safe.json')
if not available():
    print(json.dumps({'status':'Unsupported','reason':'Linux user/mount/net/pid namespaces unavailable'}))
    sys.exit(3)
with tempfile.TemporaryDirectory() as temp:
    ws=Workspace(Path(temp)/'evidence')
    initial=trace_gate(ws,MODELS,BOUND,ROOT/'cpp/trace/correct.cpp',depth=4)
    for ir in MODELS.values():ws.record(ir,verify(ir))
    record_interleaving(ws,MODELS,BOUND,verify_interleaving(MODELS,BOUND))
    results={}
    for name in ('correct','broken_one_side','broken_hidden_state'):
        path=ROOT/f'cpp/trace/{name}.cpp'
        record=record_trace(ws,MODELS,BOUND,path,depth=4)
        result=record['report']
        gate=trace_gate(ws,MODELS,BOUND,path,depth=4)
        results[name]={'outcome':result['outcome'],'reason':result['reason'],
                       'scenarios':result.get('scope',{}).get('scenarios'),
                       'counterexample':result.get('counterexample'),
                       'gate':gate['decision'],'release_authorized':gate['release_authorized']}
    from axiom.audit import audit_workspace
    audit=audit_workspace(ws)
    payload={'schema':'ax-p2e-demo/0.1','initial_gate':initial['decision'],
             'results':results,'audit':audit['status'],
             'evidence_records':audit['examined'].get('cpp_trace_runs',0),
             'scope':'C++ deterministic atomic API schedules; not concurrent C++ proof'}
    print(json.dumps(payload,indent=2,ensure_ascii=False))
    assert initial['decision']=='Blocked'
    assert results['correct']['outcome']=='Tested' and results['correct']['gate']=='Approved'
    for key in ('broken_one_side','broken_hidden_state'):
        assert results[key]['outcome']=='Violated' and results[key]['gate']=='Blocked'
    assert audit['status']=='Consistent'
