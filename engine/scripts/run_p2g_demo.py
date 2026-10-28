"""P2g independently repeatable, REAL C++ compilation + gate demonstration."""
import json,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from axiom.interleaving import load_interleaving,verify_interleaving
from axiom.interleaving_store import record_interleaving
from axiom.checker import verify
from axiom.store import Workspace
from axiom.stress_store import record_stress,stress_gate

ROOT=Path(__file__).resolve().parents[1]
models,bound=load_interleaving(ROOT/'examples/interleaving/product_safe.json')
with tempfile.TemporaryDirectory(prefix='axiom-p2g-evidence-') as td:
    ws=Workspace(Path(td)/'workspace')
    for ir in models.values():
        report=verify(ir)
        assert report['outcome']=='Bounded'
        ws.record(ir,report)
    abstract=verify_interleaving(models,bound)
    assert abstract['outcome']=='Bounded'
    record_interleaving(ws,models,bound,abstract)
    correct=ROOT/'cpp/history/correct.cpp'
    r=record_stress(ws,models,bound,correct,seed_count=2,repeats=1)
    gate=stress_gate(ws,models,bound,correct,seed_count=2,repeats=1)
    race=ROOT/'cpp/history/racy_auxiliary.cpp'
    bad=record_stress(ws,models,bound,race,seed_count=2,repeats=1)
    badgate=stress_gate(ws,models,bound,race,seed_count=2,repeats=1)
    outcome={'version':'0.9.0',
             'correct':{'outcome':r['outcome'],'gate':gate['decision'],
                        'tsan_histories':r['report']['variants'].get('tsan',{}).get('checked_histories'),
                        'release_authorized':gate['release_authorized']},
             'data_race':{'outcome':bad['outcome'],'reason':bad['report']['reason'],
                          'gate':badgate['decision']},
             'seed_change_gate':stress_gate(ws,models,bound,correct,seed=17)['decision'],
             'scope':'observed native-thread schedules + TSAN only, not C++ formal proof or production release'}
    assert outcome['correct']['outcome']=='Tested' and gate['decision']=='Approved'
    assert outcome['data_race']['reason']=='E_STRESS_DATA_RACE' and badgate['decision']=='Blocked'
    assert outcome['seed_change_gate']=='Blocked'
    print(json.dumps(outcome,indent=2,ensure_ascii=False))
