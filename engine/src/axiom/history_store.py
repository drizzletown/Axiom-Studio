"""P2f current-artifact-bound local C++ history TEST evidence, not a proof."""
from __future__ import annotations
from pathlib import Path
import time
import uuid
from .cpp_history import HISTORY_VERSION,ABI_VERSION,HARNESS,verify_cpp_history,check_abi
from .lang import digest
from .interleaving_store import interleaving_gate
from .store import Workspace

EVIDENCE_VERSION = 'ax-cpp-native-history-evidence/0.1'
GATE_VERSION = 'ax-cpp-native-history-gate/0.1'

def history_tool_digest():
    from . import cpp_history,sandbox,interleaving,product,lang,history_store
    return digest(b''.join(Path(mod.__file__).read_bytes() for mod in
        (cpp_history,sandbox,interleaving,product,lang,history_store)))

def ensure_table(ws):
    with ws._db() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS cpp_history_runs (
            run_id TEXT PRIMARY KEY,
            manifest_digest TEXT NOT NULL,
            source_digest TEXT NOT NULL,
            evidence_digest TEXT NOT NULL,
            outcome TEXT NOT NULL,
            created_at TEXT NOT NULL)''')

def record_history(ws:Workspace,models,bound,candidate,*,repeats=8):
    check_abi(models,bound)
    report=verify_cpp_history(models,bound,candidate,repeats=repeats)
    raw=Path(candidate).read_bytes()
    mh=ws.put(bound);sh=ws.put_bytes(raw);rh=ws.put(report)
    evidence={'schema':EVIDENCE_VERSION,'manifest_digest':mh,'source_digest':sh,
        'report_digest':rh,'tool_digest':history_tool_digest(),
        'model_digests':{cid:digest(ir) for cid,ir in models.items()},
        'abi_version':ABI_VERSION,'harness_digest':digest(HARNESS.encode()),
        'outcome':report['outcome'],
        'assurance':'Tested' if report['outcome']=='Tested' else 'None',
        'scope':report['scope'],
        'limits':['observed threads only','no full C++ linearizability proof',
                  'no TSAN guarantee','experimental sandbox','not production release']}
    eh=ws.put(evidence);rid='cpphistory-'+uuid.uuid4().hex
    ensure_table(ws)
    with ws._db() as db:
        db.execute('INSERT INTO cpp_history_runs VALUES (?,?,?,?,?,?)',(
            rid,mh,sh,eh,report['outcome'],time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())))
    return {'run_id':rid,'evidence_digest':eh,'manifest_digest':mh,
            'source_digest':sh,'report_digest':rh,'outcome':report['outcome'],'report':report}

def history_gate(ws:Workspace,models,bound,candidate,*,repeats=8):
    check_abi(models,bound)
    from .cpp_history import trials
    n=len(trials(repeats))
    reasons=[]
    if interleaving_gate(ws,models,bound)['decision']!='Approved':
        reasons.append('ABSTRACT_INTERLEAVING_GATE_BLOCKED')
    source=Path(candidate)
    if source.is_symlink() or not source.is_file():
        raise ValueError('regular source file required')
    mh=digest(bound);sh=digest(source.read_bytes())
    ensure_table(ws)
    with ws._db() as db:
        rows=[dict(r) for r in db.execute(
            'SELECT * FROM cpp_history_runs WHERE manifest_digest=? AND source_digest=? ORDER BY created_at DESC,run_id DESC',
            (mh,sh))]
    selected=None
    for row in rows:
        try:
            ev=ws.get(row['evidence_digest']);report=ws.get(ev['report_digest'])
            scope=report['scope'];variants=report['variants']
            valid=(
                ev['schema']==EVIDENCE_VERSION and ev['manifest_digest']==mh
                and ev['source_digest']==sh and ev['tool_digest']==history_tool_digest()
                and ev['model_digests']=={cid:digest(ir) for cid,ir in models.items()}
                and ev['abi_version']==ABI_VERSION
                and ev['harness_digest']==digest(HARNESS.encode())
                and row['outcome']==ev['outcome']==report['outcome']=='Tested'
                and ev['assurance']=='Tested'
                and report['schema']==HISTORY_VERSION
                and report['manifest_digest']==mh and report['subject_digest']==sh
                and report['model_digests']==ev['model_digests']
                and report['harness_digest']==digest(HARNESS.encode())
                and scope['repeats']==repeats and scope['trials']==n
                and scope['not_exhaustive_native_schedules'] is True
                and scope['not_formal_refinement_proof'] is True
                and scope['not_production_release'] is True
                and set(variants)=={'normal','ubsan'}
                and all(v.get('compile_status')=='Finished' and v.get('compile_exit')==0
                        and v.get('run_status')=='Finished' and v.get('run_exit')==0
                        and v.get('checked_histories')==n
                        and isinstance(v.get('binary_digest'),str) and
                         v['binary_digest'].startswith('sha256:')
                        and v.get('stdout_truncated') is False and
                         v.get('stderr_truncated') is False
                        for v in variants.values())
            )
            if valid:selected=row['run_id'];break
        except (KeyError,TypeError,ValueError,OSError):pass
    if selected is None:reasons.append('NO_CURRENT_NATIVE_HISTORY_EVIDENCE')
    return {'schema':GATE_VERSION,'decision':'Approved' if not reasons else 'Blocked',
            'target':'cpp-native-threads-observed-linearizability-tested-prototype',
            'manifest_digest':mh,'source_digest':sh,'repeats':repeats,
            'selected_run':selected,'reasons':reasons,
            'assurance':'Tested' if not reasons else 'None',
            'release_authorized':False,
            'scope_note':'observed completed histories, abstract linearizability oracle; not exhaustive, not production release'}
