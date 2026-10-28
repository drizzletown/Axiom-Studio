"""Real P2 reproducibility demo. Outputs an audit JSON to --out."""
import argparse
import copy
import json
from pathlib import Path
import tempfile
from axiom.lang import parse,validate,digest
from axiom.checker import verify
from axiom.store import Workspace

root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--out',default=str(root/'reports/p2_acceptance.json'))
a=p.parse_args()
base=validate(parse((root/'examples/two_account.ax').read_text()))
with tempfile.TemporaryDirectory(prefix='axiom-p2-check-') as path:
    store=Workspace(path)
    first=store.record(base,verify(base))
    base_gate=store.gate_model_evolved(base)
    extended=copy.deepcopy(base)
    extended['properties'].append({'name':'BalanceBound', 'kind':'invariant',
        'expr':{'op':'<=','args':[{'op':'ref','name':'a'},{'op':'lit','value':3}]}})
    diff=store.record_impact(base,extended)
    before=store.gate_model_evolved(extended)
    new=store.record(extended,verify(extended))
    after=store.gate_model_evolved(extended)
    changed=copy.deepcopy(extended)
    guard=changed['actions'][0]['cases'][0]['guard']
    changed['actions'][0]['cases'][0]['guard']={'op':'and','args':[guard,{'op':'!=','args':[{'op':'ref','name':'m'},{'op':'lit','value':3}]}]}
    invalidate=store.record_impact(extended,changed)
    changed_gate=store.gate_model_evolved(changed)
    # A changed implementation with unchanged abstract spec must still be retested.
    cpp_gate=store.gate_cpp(base,root/'cpp/correct.cpp',root/'cpp/binding.json')
    result={
      'baseline_digest':digest(base),'extended_digest':digest(extended),
      'baseline_run':first['run_id'],'extension_run':new['run_id'],
      'baseline_gate':base_gate['decision'],
      'property_addition':{'behavior_unchanged':diff['behavior_unchanged'],
                           'reusable_properties':diff['potentially_reusable_properties'],
                           'before_decision':before['decision'],
                           'before_missing':before['missing_obligations'],
                           'reused_by_before':before['covered_by_run'],
                           'after_decision':after['decision']},
      'action_change':{'behavior_unchanged':invalidate['behavior_unchanged'],
                       'affected_nodes':invalidate['affected_nodes'],
                       'gate':changed_gate['decision'],
                       'missing':changed_gate['missing_obligations']},
      'cpp_gate_without_cpp_evidence':cpp_gate['decision'],
      'scope':'Only local trusted P2 bounded model-evidence reuse, not verified C++ refinements'
    }
    assert base_gate['decision']=='Approved'
    assert before['decision']=='Blocked' and len(before['missing_obligations'])==1
    assert after['decision']=='Approved'
    assert changed_gate['decision']=='Blocked'
    assert cpp_gate['decision']=='Blocked'
    out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(result,indent=2,ensure_ascii=False))
