"""Clean-workspace P2c end-to-end product validation, mutation and audit demo."""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from axiom.audit import audit_workspace
from axiom.checker import verify
from axiom.product import load_product,verify_product
from axiom.product_store import product_gate,record_product
from axiom.store import Workspace


def run():
    with tempfile.TemporaryDirectory(prefix='axiom-p2c-') as tmp:
        ws=Workspace(Path(tmp)/'.axiom')
        good,bound=load_product(ROOT/'examples/product/product.json')
        before=product_gate(ws,good,bound)
        assert before['decision']=='Blocked'
        for ir in good.values():
            r=verify(ir)
            assert r['outcome']=='Bounded'
            ws.record(ir,r)
        middle=product_gate(ws,good,bound)
        assert middle['decision']=='Blocked'
        checked=verify_product(good,bound)
        assert checked['outcome']=='Bounded'
        product_rec=record_product(ws,good,bound,checked)
        after=product_gate(ws,good,bound)
        assert after['decision']=='Approved'
        bad,bad_bound=load_product(ROOT/'examples/product/product_broken.json')
        independent={k:verify(ir)['outcome'] for k,ir in bad.items()}
        assert set(independent.values())=={'Bounded'}
        broken=verify_product(bad,bad_bound)
        assert broken['outcome']=='Violated' and broken['reason']=='E_PRODUCT_PROPERTY'
        blocked=product_gate(ws,bad,bad_bound)
        assert blocked['decision']=='Blocked'
        record_product(ws,bad,bad_bound,broken)
        audit=audit_workspace(ws)
        assert audit['status']=='Consistent' and audit['examined']['product_runs']==2
        return {
            'project':'Axiom P2c','stage':'finite synchronized abstract products',
            'good':{'initial_gate':before['decision'],'local_only_gate':middle['decision'],
                    'product_evidence':product_rec['evidence_digest'],
                    'product_outcome':checked['outcome'],'product_gate':after['decision'],
                    'reachable_product_states':checked['statistics']['reachable_states']},
            'broken':{'isolated_models':independent,'product_outcome':broken['outcome'],
                      'reason':broken['reason'],'counterexample':broken['counterexample'],
                      'gate':blocked['decision']},
            'integrity_audit':audit['status'],'audited_product_runs':audit['examined']['product_runs'],
            'claim_boundary':'Finite two-component synchronized abstract behavior only. '
                             'No arbitrary interleavings, C++ composition proof or secure untrusted-code execution.'}

if __name__=='__main__':
    print(json.dumps(run(),ensure_ascii=False,indent=2))
