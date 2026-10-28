"""P2e immutable local *test* evidence; not a cryptographic trust boundary."""
from __future__ import annotations
from pathlib import Path
import time
import uuid
from .cpp_trace import TRACE_VERSION, CONTRACT_VERSION, HARNESS, COMMON, verify_cpp_trace,check_abi
from .interleaving_store import interleaving_gate
from .lang import digest
from .store import Workspace


def _tool_digest():
    from . import cpp_trace,sandbox,interleaving,product,lang,trace_store
    return digest(b''.join(Path(mod.__file__).read_bytes() for mod in
          (cpp_trace,sandbox,interleaving,product,lang,trace_store)))


def _init(ws):
    with ws._db() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS cpp_trace_runs (
        run_id TEXT PRIMARY KEY,manifest_digest TEXT NOT NULL,
        source_digest TEXT NOT NULL,evidence_digest TEXT NOT NULL,
        outcome TEXT NOT NULL,created_at TEXT NOT NULL)''')


def record_trace(ws:Workspace,models,bound,candidate,*,depth=4):
    check_abi(models,bound)
    report=verify_cpp_trace(models,bound,candidate,depth=depth)
    mh=ws.put(bound)
    raw=Path(candidate).read_bytes()
    sh=ws.put_bytes(raw)
    rh=ws.put(report)
    evidence={
        'schema':'ax-cpp-trace-evidence/0.1','manifest_digest':mh,
        'source_digest':sh,'report_digest':rh,'model_digests':report.get('model_digests'),
        'tool_digest':_tool_digest(),'abi':CONTRACT_VERSION,
        'outcome':report['outcome'],'assurance':'Tested' if report['outcome']=='Tested' else 'None',
        'scope':report.get('scope',{}),'harness_digest':digest(HARNESS.encode()),
        'limits':['not generic C++ refinement','no OS kernel sandbox audit','no real thread concurrency']}
    eh=ws.put(evidence)
    rid='cpptrace-'+uuid.uuid4().hex
    _init(ws)
    with ws._db() as db:
        db.execute('INSERT INTO cpp_trace_runs VALUES (?,?,?,?,?,?)',(
            rid,mh,sh,eh,report['outcome'],time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())))
    return {'run_id':rid,'manifest_digest':mh,'source_digest':sh,
            'evidence_digest':eh,'report_digest':rh,'outcome':report['outcome'],'report':report}


def trace_gate(ws:Workspace,models,bound,candidate,*,depth=4):
    check_abi(models,bound)
    reasons=[]
    abstract=interleaving_gate(ws,models,bound)
    if abstract['decision']!='Approved':reasons.append('ABSTRACT_INTERLEAVING_GATE_BLOCKED')
    mh=digest(bound);sh=digest(Path(candidate).read_bytes())
    _init(ws)
    with ws._db() as db:
        rows=[dict(r) for r in db.execute('SELECT * FROM cpp_trace_runs WHERE manifest_digest=? AND source_digest=? ORDER BY created_at DESC, run_id DESC',(mh,sh))]
    accepted=None
    for row in rows:
        try:
            ev=ws.get(row['evidence_digest'])
            report=ws.get(ev['report_digest'])
            scope=report['scope']
            variants=report['variants']
            is_ok=(row['outcome']==ev['outcome']==report['outcome']=='Tested'
                and ev['assurance']=='Tested' and ev['schema']=='ax-cpp-trace-evidence/0.1'
                and ev['manifest_digest']==mh and ev['source_digest']==sh
                and ev['model_digests']=={cid:digest(ir) for cid,ir in models.items()}
                and ev['abi']==CONTRACT_VERSION and ev['tool_digest']==_tool_digest()
                and ev['harness_digest']==digest(HARNESS.encode())
                and report['schema']==TRACE_VERSION and report['manifest_digest']==mh
                and report['subject_digest']==sh and scope['depth']==depth
                and scope['scenarios']>0 and scope['observations']>=scope['scenarios']
                and scope['not_formal_refinement_proof'] is True
                and set(variants)=={'normal','ubsan'}
                and all(v['compile_exit']==0 and v['run_exit']==0 and
                        v['compile_status']=='Finished' and v['run_status']=='Finished'
                        and isinstance(v['binary_digest'],str) and
                        v['binary_digest'].startswith('sha256:') for v in variants.values()))
            if is_ok:
                # A local stored report can be replayed at acceptance time, but this
                # gate only authenticates local immutable-record *consistency*.
                accepted=row['run_id'];break
        except (KeyError,TypeError,ValueError,OSError):
            pass
    if accepted is None: reasons.append('NO_CURRENT_CPP_TRACE_TEST_EVIDENCE')
    return {'schema':'ax-cpp-trace-gate/0.1',
            'decision':'Approved' if not reasons else 'Blocked',
            'target':'cpp-deterministic-schedule-tested-prototype',
            'manifest_digest':mh,'source_digest':sh,'selected_run':accepted,'depth':depth,
            'reasons':reasons,'assurance':'Tested' if not reasons else 'None',
            'release_authorized':False,
            'scope_note':'C++ finite trace tests with rootless namespace isolation; no generic refinement theorem or production security guarantee'}
