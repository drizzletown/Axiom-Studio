"""Reproducible P2f native-thread test and source-only evolution experiment."""
from __future__ import annotations
import json
from pathlib import Path
import tempfile
from axiom.interleaving import load_interleaving,verify_interleaving
from axiom.interleaving_store import record_interleaving
from axiom.checker import verify
from axiom.store import Workspace
from axiom.history_store import record_history,history_gate
from axiom.audit import audit_workspace
from axiom.sandbox import available

ROOT=Path(__file__).resolve().parents[1]
if not available():
    print(json.dumps({'outcome':'Unsupported','reason':'namespace sandbox unavailable'}))
    raise SystemExit(3)
models,bound=load_interleaving(ROOT/'examples/interleaving/product_safe.json')
with tempfile.TemporaryDirectory(prefix='axiom-p2f-demo-') as td:
    folder=Path(td)
    ws=Workspace(folder/'workspace')
    source=folder/'candidate.cpp'
    source.write_bytes((ROOT/'cpp/history/correct.cpp').read_bytes())
    initially=history_gate(ws,models,bound,source,repeats=2)
    for ir in models.values():ws.record(ir,verify(ir))
    record_interleaving(ws,models,bound,verify_interleaving(models,bound))
    abstract_gate=history_gate(ws,models,bound,source,repeats=2)
    first=record_history(ws,models,bound,source,repeats=2)
    first_gate=history_gate(ws,models,bound,source,repeats=2)
    source.write_bytes(source.read_bytes()+b'\n// P2f evolution: comment-only source revision\n')
    changed_gate=history_gate(ws,models,bound,source,repeats=2)
    revision=record_history(ws,models,bound,source,repeats=2)
    revised_gate=history_gate(ws,models,bound,source,repeats=2)
    source.write_bytes((ROOT/'cpp/history/broken_one_side.cpp').read_bytes())
    broken1=record_history(ws,models,bound,source,repeats=2)
    broken1_gate=history_gate(ws,models,bound,source,repeats=2)
    source.write_bytes((ROOT/'cpp/history/broken_overlap.cpp').read_bytes())
    broken2=record_history(ws,models,bound,source,repeats=2)
    broken2_gate=history_gate(ws,models,bound,source,repeats=2)
    audit=audit_workspace(ws)
    out={'schema':'ax-p2f-acceptance-demo/0.1','engineering_version':'0.8.0',
         'abstract_model_evidence': 'recorded once, retained across source-only revisions',
         'gates':{'before_model_evidence':initially['decision'],
                  'abstract_only':abstract_gate['decision'],
                  'correct_source':first_gate['decision'],
                  'source_change_before_retest':changed_gate['decision'],
                  'source_change_after_retest':revised_gate['decision'],
                  'one_sided_bug':broken1_gate['decision'],
                  'overlap_bug':broken2_gate['decision']},
         'cases':{'correct':first['report']['outcome'],
                  'comment_only_revision':revision['report']['outcome'],
                  'one_sided_bug':broken1['report']['outcome'],
                  'overlap_bug':broken2['report']['outcome']},
         'trials_per_compiled_mode':first['report']['scope']['trials'],
         'total_operations_per_mode':first['report']['scope']['total_operations'],
         'counterexample_one_sided':broken1['report'].get('counterexample'),
         'counterexample_overlap':broken2['report'].get('counterexample'),
         'local_audit':audit['status'],
         'local_audit_history_records':audit['examined'].get('cpp_history_runs',0),
         'limitations':['native thread scheduling observed, not exhaustively controlled',
                        'not a proof of C++ memory model behavior','no TSAN check',
                        'evidence locally auditable but not externally authenticated',
                        'namespace sandbox experimental','no production release']}
    print(json.dumps(out,ensure_ascii=False,indent=2))
    assert list(out['gates'].values())==['Blocked','Blocked','Approved','Blocked','Approved','Blocked','Blocked']
    assert out['cases']=={'correct':'Tested','comment_only_revision':'Tested',
                          'one_sided_bug':'Violated','overlap_bug':'Violated'}
    assert audit['status']=='Consistent'
