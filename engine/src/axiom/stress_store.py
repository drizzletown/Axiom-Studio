"""P2g: artifact-bound stress and ThreadSanitizer test evidence (local trust only)."""
from __future__ import annotations
from pathlib import Path
import time,uuid
from .cpp_stress import verify_cpp_stress,SCHEMA,ABI,STRESS_HARNESS,scenarios_for,check_abi
from .interleaving_store import interleaving_gate
from .lang import digest
from .store import Workspace

EVIDENCE='ax-cpp-stress-evidence/0.1'
GATE='ax-cpp-stress-gate/0.1'

def tool_digest():
    from . import cpp_stress,cpp_history,interleaving,product,sandbox,lang,stress_store
    return digest(b''.join(Path(m.__file__).read_bytes() for m in
                  (cpp_stress,cpp_history,interleaving,product,sandbox,lang,stress_store)))

def ensure_table(ws):
    with ws._db() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS cpp_stress_runs (
        run_id TEXT PRIMARY KEY, manifest_digest TEXT NOT NULL,
        source_digest TEXT NOT NULL,evidence_digest TEXT NOT NULL,
        outcome TEXT NOT NULL,created_at TEXT NOT NULL)''')

def record_stress(ws:Workspace,models,bound,candidate,*,repeats=1,seed=104729,seed_count=2):
    check_abi(models,bound)
    report=verify_cpp_stress(models,bound,candidate,repeats=repeats,
                             seed=seed,seed_count=seed_count)
    raw=Path(candidate).read_bytes()
    mh=ws.put(bound);sh=ws.put_bytes(raw);rh=ws.put(report)
    evidence={'schema':EVIDENCE,'manifest_digest':mh,'source_digest':sh,
        'report_digest':rh,'tool_digest':tool_digest(),
        'model_digests':{cid:digest(ir) for cid,ir in models.items()},
        'abi':ABI,'harness_digest':digest(STRESS_HARNESS.encode()),
        'outcome':report['outcome'],'assurance':'Tested' if report['outcome']=='Tested' else 'None',
        'scope':report['scope'],'limits':['sampled schedules','TSAN only observes selected executions',
          'no general C++ refinement proof','not production release']}
    eh=ws.put(evidence);rid='cppstress-'+uuid.uuid4().hex
    ensure_table(ws)
    with ws._db() as db:
        db.execute('INSERT INTO cpp_stress_runs VALUES (?,?,?,?,?,?)',
            (rid,mh,sh,eh,report['outcome'],time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())))
    return {'run_id':rid,'outcome':report['outcome'],'report':report,
            'evidence_digest':eh,'manifest_digest':mh,'source_digest':sh}

def stress_gate(ws:Workspace,models,bound,candidate,*,repeats=1,seed=104729,seed_count=2):
    check_abi(models,bound)
    scenarios=scenarios_for(repeats,seed,seed_count)
    if Path(candidate).is_symlink() or not Path(candidate).is_file():
        raise ValueError('regular .cpp candidate required')
    mh=digest(bound);sh=digest(Path(candidate).read_bytes());reasons=[]
    if interleaving_gate(ws,models,bound)['decision']!='Approved':
        reasons.append('ABSTRACT_INTERLEAVING_GATE_BLOCKED')
    ensure_table(ws)
    with ws._db() as db:
        rows=[dict(r) for r in db.execute('''SELECT * FROM cpp_stress_runs
          WHERE manifest_digest=? AND source_digest=? ORDER BY created_at DESC,run_id DESC''',(mh,sh))]
    selected=None
    for row in rows:
        try:
            ev=ws.get(row['evidence_digest']);report=ws.get(ev['report_digest'])
            scope=report['scope'];variants=report['variants']
            valid=(ev['schema']==EVIDENCE and ev['tool_digest']==tool_digest()
                and ev['manifest_digest']==row['manifest_digest']==mh
                and ev['source_digest']==row['source_digest']==sh
                and ev['model_digests']=={cid:digest(ir) for cid,ir in models.items()}
                and ev['abi']==ABI and ev['harness_digest']==digest(STRESS_HARNESS.encode())
                and report['schema']==SCHEMA and report['source_digest']==sh
                and report['manifest_digest']==mh and report['model_digests']==ev['model_digests']
                and report['harness_digest']==ev['harness_digest']
                and report['outcome']==ev['outcome']==row['outcome']=='Tested'
                and ev['assurance']=='Tested' and scope==ev['scope']
                and scope['repeats']==repeats and scope['seed']==seed
                and scope['seed_count']==seed_count and scope['trials']==len(scenarios)
                and scope['tsan_required'] is True and scope['not_exhaustive'] is True
                and scope['not_formal_refinement_proof'] is True
                and scope['not_production_release'] is True
                and set(variants)=={'normal','ubsan','tsan'}
                and all(v['compile_status']=='Finished' and v['compile_exit']==0
                  and v['run_status']=='Finished' and v['run_exit']==0
                  and v['checked_histories']==len(scenarios)
                  and v['stdout_truncated'] is False and v['stderr_truncated'] is False
                  and isinstance(v['binary_digest'],str) and v['binary_digest'].startswith('sha256:')
                  for v in variants.values()))
            if valid:selected=row['run_id'];break
        except (KeyError,ValueError,TypeError,OSError):pass
    if selected is None:reasons.append('NO_MATCHING_STRESS_TSAN_EVIDENCE')
    return {'schema':GATE,'decision':'Approved' if not reasons else 'Blocked',
        'target':'cpp-native-observed-stress-and-tsan-tested-prototype',
        'source_digest':sh,'manifest_digest':mh,'repeats':repeats,
        'seed':seed,'seed_count':seed_count,'selected_run':selected,
        'reasons':reasons,'assurance':'Tested' if not reasons else 'None',
        'release_authorized':False,
        'scope_note':'sampled native executions and TSAN; not exhaustive and not production ready'}
