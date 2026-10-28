"""Reproducible small-model microbenchmark: full vs contract-safe per-property recheck.

No proof of general speedups: this only measures this fixed finite model; a
contract-preserving reuse opportunity is assumed from prior completed checks.
"""
import argparse, copy, json, statistics, sys, time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from axiom.lang import parse,validate
from axiom.checker import verify
from axiom.evolution import impact

ROOT=Path(__file__).resolve().parents[1]
args=argparse.ArgumentParser()
args.add_argument('--state-bits',type=int,choices=[1,9],default=1)
config=args.parse_args()
if config.state_bits==1:
    base=validate(parse((ROOT/'examples/interleaving/Source.ax').read_text()))
else:
    fields=' '.join(f'b{i}: Bool' for i in range(config.state_bits))
    source=f'''model ScaledBench {{
      state {{ {fields} }}
      init {{ true }}
      action noop() -> Bool {{ case true {{ modifies {{ }} ensures result == true }} }}
      property AlwaysValid {{ always b0 == true || b0 == false }}
      observe {{ noop.input,noop.output }}
    }}'''
    base=validate(parse(source))
revisions=[copy.deepcopy(base)]
for step in range(1,9):
    cur=copy.deepcopy(revisions[-1])
    prop=copy.deepcopy(base['properties'][0]);prop['name']=f'Invariant_{step:02d}'
    cur['properties'].append(prop)
    revisions.append(validate(cur))

# Build a legitimate historical baseline before attempting any reuse.
base_evidence=verify(base)
assert base_evidence['outcome']=='Bounded'
full_total=0.;inc_total=0.;reuse_obligations=0;new_obligations=0;records=[]
for step in range(1,len(revisions)):
    old,new=revisions[step-1],revisions[step]
    delta=impact(old,new)
    assert delta['behavior_unchanged'] and delta['potentially_reusable_properties']
    new_names=set(delta['requires_new_property_evidence'])
    assert new_names=={f'Invariant_{step:02d}'}
    subset=copy.deepcopy(new)
    subset['properties']=[p for p in new['properties'] if p['name'] in new_names]
    # Full: validate/check all properties. Incremental: validate/check new property;
    # previous ones were verified and must have identical fingerprint AND behavior core.
    # Include impact graph overhead in the incremental measurements.
    def measure(full):
        start=time.perf_counter()
        if not full:
            again=impact(old,new)
            if again['requires_new_property_evidence']!=delta['requires_new_property_evidence']:
                raise RuntimeError('unstable change analysis')
        result=verify(new if full else subset)
        elapsed=time.perf_counter()-start
        if result['outcome']!='Bounded':raise RuntimeError('unexpected unsuccessful verification')
        return elapsed,result
    # Alternating order dampens warming and frequency bias.
    f_times=[];i_times=[]
    for rep in range(9):
        jobs=('full','inc') if rep%2 else ('inc','full')
        for job in jobs:
            t,_=measure(job=='full')
            (f_times if job=='full' else i_times).append(t)
    full_ms=statistics.median(f_times)*1000
    inc_ms=statistics.median(i_times)*1000
    full_total+=full_ms;inc_total+=inc_ms
    reuse_obligations+=len(delta['potentially_reusable_properties'])
    new_obligations+=len(new_names)
    records.append({'revision':step,'properties_total':len(new['properties']),
        'properties_reused':len(delta['potentially_reusable_properties']),
        'properties_rechecked':len(new_names),
        'full_median_ms':round(full_ms,3),'incremental_median_ms':round(inc_ms,3)})
result={'schema':'ax-p2g-model-benchmark/0.1','experimental':True,
 'measurement':'9 repeats per path, median wall-clock, impact computation included in incremental',
 'model':base['model'],'state_bits':config.state_bits,
 'reachable_states':base_evidence['statistics']['reachable_states'],'version_changes':'add-only safety invariants; transition core unchanged',
 'revisions':len(records),'model_property_positions_reused':reuse_obligations,
 'model_property_positions_newly_checked':new_obligations,
 'full_total_median_ms':round(full_total,3),
 'incremental_total_median_ms':round(inc_total,3),
 'ratio_full_over_incremental':round(full_total/inc_total,3) if inc_total else None,
 'conclusion_scope':'microbenchmark only, not C++ test speedup nor general verification acceleration',
 'data':records}
print(json.dumps(result,indent=2,ensure_ascii=False))
