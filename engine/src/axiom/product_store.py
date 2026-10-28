"""P2c content-addressed abstract product evidence and fail-closed gate.

Trust boundary is explicitly local only. This is not a signature service, and
cannot defend against an actor able to change checker source + SQLite + records.
"""
from __future__ import annotations
import time
import uuid
from pathlib import Path
from .lang import digest,canonical_bytes
from .checker import obligations
from .store import Workspace
from .product import SCHEMA,POLICY,verify_product,_check_bound


def product_tool_digest():
    from . import product,lang,checker,product_store
    return digest(b''.join(Path(mod.__file__).read_bytes() for mod in (product,lang,checker,product_store)))


def record_product(workspace: Workspace,models,bound,report):
    _check_bound(models,bound)
    if report.get('outcome')=='Bounded':
        opts=report['scope']
        again=verify_product(models,bound,max_states=opts['max_states'],
                             max_transitions=opts['max_transitions'],timeout_s=opts['timeout_seconds'])
        if canonical_bytes(report)!=canonical_bytes(again):
            raise ValueError('E_PRODUCT_REPORT_FORGERY: replay does not match claimed bounded result')
    elif report.get('outcome') not in ('Violated','Unknown'):
        raise ValueError('E_PRODUCT_REPORT: unsupported outcome')
    bound_hash=workspace.put(bound)
    report_hash=workspace.put(report)
    provenance={'schema':'ax-product-evidence/0.1','manifest_digest':bound_hash,
                'report_digest':report_hash,'tool_digest':product_tool_digest(),
                'assurance':'Bounded' if report['outcome']=='Bounded' else 'None',
                'outcome':report['outcome'],
                'subject':'two-component-atomic-synchronous-abstract-product',
                'scope':report.get('scope',{}),
                'model_digests':{cid:digest(ir) for cid,ir in models.items()}}
    provenance_hash=workspace.put(provenance)
    run_id='product-'+uuid.uuid4().hex
    with workspace._db() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS product_runs
                      (run_id TEXT PRIMARY KEY, manifest_digest TEXT NOT NULL,
                       evidence_digest TEXT NOT NULL, outcome TEXT NOT NULL,
                       created_at TEXT NOT NULL)''')
        db.execute('INSERT INTO product_runs VALUES(?,?,?,?,?)',
                   (run_id,bound_hash,provenance_hash,report['outcome'],
                    time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())))
    return {'run_id':run_id,'manifest_digest':bound_hash,'evidence_digest':provenance_hash,
            'report_digest':report_hash,'outcome':report['outcome']}


def product_gate(workspace: Workspace,models,bound):
    _check_bound(models,bound)
    manifest_digest=workspace.put(bound)
    reasons=[]; local={}
    for cid,ir in sorted(models.items()):
        # Reuse P2 strict evidence checking; not a proof of refinement or wiring.
        outcome=workspace.gate_model_evolved(ir)
        local[cid]=outcome['decision']
        if outcome['decision']!='Approved':
            reasons.append({'code':'MISSING_LOCAL_MODEL_EVIDENCE','component':cid})
    with workspace._db() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS product_runs
                      (run_id TEXT PRIMARY KEY, manifest_digest TEXT NOT NULL,
                       evidence_digest TEXT NOT NULL, outcome TEXT NOT NULL,
                       created_at TEXT NOT NULL)''')
        rows=list(db.execute('SELECT * FROM product_runs WHERE manifest_digest=? ORDER BY created_at DESC,run_id DESC',
                             (manifest_digest,)))
    accepted=None
    for row in rows:
        try:
            ev=workspace.get(row['evidence_digest'])
            report=workspace.get(ev['report_digest'])
            eligible=(ev['schema']=='ax-product-evidence/0.1' and
                      ev['manifest_digest']==manifest_digest and
                      ev['model_digests']=={cid:digest(ir) for cid,ir in models.items()} and
                      ev['tool_digest']==product_tool_digest() and
                      ev['outcome']=='Bounded' and row['outcome']=='Bounded' and
                      report['outcome']=='Bounded' and report['scope']['finite_reachable_exhaustion'] is True and
                      report['scope']['target']=='two-component-synchronous-abstract-product' and
                      set(report['verified_properties'])=={p['name'] for p in bound['properties']})
            if eligible:
                accepted={'run_id':row['run_id'],'evidence_digest':row['evidence_digest']}
                break
        except (KeyError,ValueError,TypeError,OSError):
            continue
    if accepted is None:reasons.append({'code':'MISSING_CURRENT_PRODUCT_EVIDENCE'})
    return {'schema':'ax-product-gate/0.1','policy':POLICY,'manifest_digest':manifest_digest,
            'decision':'Approved' if not reasons else 'Blocked',
            'target':'finite-abstract-product-integration-check',
            'scope':'Bounded synchronized atomic product only. No asynchronous/interleaved components, '
                    'no C++ refinement, no untrusted-code sandbox or production approval.',
            'local_model_gates':local,'selected_product_evidence':accepted,'reasons':reasons}
