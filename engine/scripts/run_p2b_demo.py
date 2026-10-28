"""Self-contained P2b reproducibility experiment. No C++ execution is required."""
from __future__ import annotations
import copy
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from axiom.checker import obligations,verify
from axiom.composition import load_manifest, assess_composition
from axiom.audit import audit_workspace
from axiom.lang import parse,validate
from axiom.store import Workspace


def run():
    with tempfile.TemporaryDirectory(prefix='axiom-p2b-') as td:
        root=Path(td)
        sample=ROOT/'examples/composition'
        for name in ('account.ax','flag.ax','composition.json'):
            (root/name).write_bytes((sample/name).read_bytes())
        manifest=root/'composition.json'
        w=Workspace(root/'evidence')
        initial=assess_composition(w,manifest)
        assert initial['decision']=='Blocked'
        models=load_manifest(manifest)[0]
        for ir in models.values():
            r=verify(ir)
            assert r['outcome']=='Bounded'
            w.record(ir,r)
        passed=assess_composition(w,manifest)
        assert passed['decision']=='Ready'
        # New invariant preserves prior behavior and contracts, so the old
        # verified obligations can be reused, while the new one blocks.
        source=(root/'account.ax').read_text()
        (root/'account.ax').write_text(source.replace('  observe {',
                               '  property P_Extra { always a >= 0 }\n  observe {'))
        partial=assess_composition(w,manifest)
        assert partial['decision']=='Blocked'
        reused=len(partial['components']['TwoAccount']['covered_by_run'])
        added=len(partial['components']['TwoAccount']['missing_obligations'])
        assert reused==5 and added==1
        new_model=load_manifest(manifest)[0]['TwoAccount']
        assert verify(new_model)['outcome']=='Bounded'
        w.record(new_model,verify(new_model))
        recovered=assess_composition(w,manifest)
        assert recovered['decision']=='Ready'
        altered=(root/'account.ax').read_text().replace("a' == a - m", "a' == a")
        (root/'account.ax').write_text(altered)
        changed=assess_composition(w,manifest)
        assert changed['decision']=='Blocked'
        invalidated=len(changed['components']['TwoAccount']['missing_obligations'])
        assert invalidated==len(obligations(load_manifest(manifest)[0]['TwoAccount']))
        local_audit=audit_workspace(w)
        assert local_audit['status']=='Consistent'
        # 12 successive changes: each adds one independent property, then
        # we verify and record it. The experiment counts reusable obligations,
        # NOT wall-clock savings or proof of inter-module behavior.
        baseline=(ROOT/'examples/two_account.ax').read_text()
        test_ir=validate(parse(baseline))
        sequential=Workspace(root/'sequential')
        r=verify(test_ir);assert r['outcome']=='Bounded';sequential.record(test_ir,r)
        evolution=[]
        for i in range(1,13):
            prior=validate(test_ir)
            test_ir=copy.deepcopy(prior)
            test_ir['properties'].append({'name':f'Safety_{i}', 'kind':'invariant',
                'expr':{'op':'>=', 'args':[{'op':'ref','name':'a'},{'op':'lit','value':0}]}})
            test_ir=validate(test_ir)
            before=sequential.gate_model_evolved(test_ir)
            assert before['decision']=='Blocked'
            assert len(before['missing_obligations'])==1
            total=len(before['required_obligations'])
            report=verify(test_ir)
            assert report['outcome']=='Bounded'
            sequential.record(test_ir,report)
            assert sequential.gate_model_evolved(test_ir)['decision']=='Approved'
            evolution.append({'revision':i,'obligations':total,
                'reused_prior_to_new_check':len(before['covered_by_run']),
                'newly_required':1})
        summary={
            'phase':'P2b',
            'stages':{'unverified':initial['decision'],
                      'two_models_checked':passed['decision'],
                      'new_property':partial['decision'],
                      'new_property_verified':recovered['decision'],
                      'action_changed':changed['decision']},
            'new_property':{'reused_obligations':reused,'newly_required':added},
            'action_change':{'invalidated_obligations':invalidated},
            'workspace_audit':local_audit,
            'sequential':{'revisions':evolution,
                          'total_reused_obligation_slots':sum(x['reused_prior_to_new_check'] for x in evolution),
                          'total_newly_required_slots':sum(x['newly_required'] for x in evolution),
                          'note':'Obligation reuse bookkeeping only: each revision was also fully verified; '
                                 'no measured run-time speedup or cross-module refinement claim.'}
        }
        return summary

if __name__=='__main__':print(json.dumps(run(),indent=2,ensure_ascii=False))
