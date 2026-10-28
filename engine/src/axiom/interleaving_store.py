"""Local P2d evidence. Every claimed exhaustive run is independently replayed.

Hashes prevent accidental bit corruption but are NOT an external trust anchor.
"""
from __future__ import annotations
import time
import uuid
from pathlib import Path
from .lang import canonical_bytes,digest
from .interleaving import SCHEMA,POLICY,_check_bound,verify_interleaving
from .store import Workspace


def interleaving_tool_digest():
    from . import interleaving,product,lang,checker,interleaving_store
    return digest(b''.join(Path(mod.__file__).read_bytes() for mod in
        (interleaving,product,lang,checker,interleaving_store)))


def _init(ws):
    with ws._db() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS interleaving_runs(
            run_id TEXT PRIMARY KEY,manifest_digest TEXT NOT NULL,
            evidence_digest TEXT NOT NULL,outcome TEXT NOT NULL,
            created_at TEXT NOT NULL)''')


def record_interleaving(ws:Workspace,models,bound,report):
    _check_bound(models,bound)
    outcome=report.get('outcome')
    if outcome=='Bounded':
        scope=report.get('scope',{})
        if scope.get('semantics')!=SCHEMA:
            raise ValueError('E_INTER_REPORT: invalid semantics')
        again=verify_interleaving(models,bound,max_states=scope['max_states'],
                  max_transitions=scope['max_transitions'],timeout_s=scope['timeout_seconds'])
        if canonical_bytes(again)!=canonical_bytes(report):
            raise ValueError('E_INTER_REPORT_FORGERY: checker replay mismatch')
    elif outcome not in ('Violated','Unknown'):
        raise ValueError('E_INTER_REPORT: unsupported outcome')
    manifest_hash=ws.put(bound)
    report_hash=ws.put(report)
    ev={'schema':'ax-interleaving-evidence/0.1','manifest_digest':manifest_hash,
        'report_digest':report_hash,'tool_digest':interleaving_tool_digest(),
        'assurance':'Bounded' if outcome=='Bounded' else 'None',
        'outcome':outcome,'subject':'two-component-mixed-interleaving-abstract-product',
        'scope':report.get('scope',{}),
        'model_digests':{cid:digest(ir) for cid,ir in models.items()}}
    ev_hash=ws.put(ev)
    rid='inter-'+uuid.uuid4().hex
    _init(ws)
    with ws._db() as db:
        db.execute('INSERT INTO interleaving_runs VALUES(?,?,?,?,?)',
            (rid,manifest_hash,ev_hash,outcome,time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())))
    return {'run_id':rid,'manifest_digest':manifest_hash,'evidence_digest':ev_hash,
            'report_digest':report_hash,'outcome':outcome}


def interleaving_gate(ws:Workspace,models,bound):
    _check_bound(models,bound)
    mh=digest(bound)
    local={};reasons=[]
    for cid,ir in sorted(models.items()):
        outcome=ws.gate_model_evolved(ir)
        local[cid]=outcome['decision']
        if outcome['decision']!='Approved':
            reasons.append({'code':'MISSING_LOCAL_MODEL_EVIDENCE','component':cid})
    _init(ws)
    with ws._db() as db:
        rows=list(db.execute('SELECT * FROM interleaving_runs WHERE manifest_digest=? ORDER BY created_at DESC,run_id DESC',(mh,)))
    accepted=None
    for row in rows:
        try:
            ev=ws.get(row['evidence_digest'])
            report=ws.get(ev['report_digest'])
            if (ev['schema']=='ax-interleaving-evidence/0.1' and
                ev['manifest_digest']==mh and ev['model_digests']=={cid:digest(ir) for cid,ir in models.items()} and
                ev['tool_digest']==interleaving_tool_digest() and
                row['outcome']==ev['outcome']==report['outcome']=='Bounded' and
                ev['assurance']=='Bounded' and
                report['scope']['semantics']==SCHEMA and
                report['scope']['finite_reachable_exhaustion'] is True and
                report['scope']['target']=='two-component-mixed-interleaving-abstract-product' and
                report['scope']['scheduler']=='all-atomic-independent-steps-and-declared-rendezvous' and
                set(report['verified_properties'])=={p['name'] for p in bound['properties']}):
                accepted={'run_id':row['run_id'],'evidence_digest':row['evidence_digest']}
                break
        except (OSError,KeyError,TypeError,ValueError):
            continue
    if accepted is None:
        reasons.append({'code':'MISSING_CURRENT_INTERLEAVING_EVIDENCE'})
    return {'schema':POLICY,'target':'finite-abstract-mixed-interleaving-product',
            'decision':'Approved' if not reasons else 'Blocked','reasons':reasons,
            'manifest_digest':mh,'local_model_gates':local,
            'selected_interleaving_evidence':accepted,
            'scope':['finite abstract states only','independent atomic actions or declared rendezvous',
                     'no C++ refinement','no fairness or liveness','not production release']}
