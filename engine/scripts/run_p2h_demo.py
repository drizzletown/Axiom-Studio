"""End-to-end real C++ incremental build/test demonstration; no hypothetical timings."""
import json
from pathlib import Path
import sys,shutil,tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from axiom.cpp_project import run_project,project_gate
from axiom.store import Workspace

root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='ax-p2h-demo-') as d:
    tmp=Path(d);project=tmp/'project'
    shutil.copytree(root/'examples/cpp_project',project)
    ws=Workspace(tmp/'store'); mp=project/'project.json'
    first=run_project(ws,mp)
    target=project/'format.cpp';original=target.read_text()
    target.write_text(original+'\n// harmless but versioned source change\n')
    stale=project_gate(ws,mp)['decision']
    partial=run_project(ws,mp)
    target.write_text(target.read_text().replace(' + ":" + ', ' + "-" + '))
    defect=run_project(ws,mp)
    blocked=project_gate(ws,mp)['decision']
    result={
        'version':'1.0.0','schema':'ax-p2h-demo/0.1',
        'first':{k:first['report'][k] for k in ('outcome','executed_targets','cache_hits','elapsed_seconds')},
        'changed_format':{'gate_before':stale,'outcome':partial['report']['outcome'],
              'executed':partial['report']['executed_targets'],'reused':partial['report']['cache_hits'],
              'elapsed_seconds':partial['report']['elapsed_seconds'],
              'target_reused':{k:v['reused'] for k,v in partial['report']['targets'].items()}},
        'injected_wrong_receipt':{'outcome':defect['report']['outcome'],'gate':blocked,
                   'failed_targets':defect['report']['failed_targets']},
        'release_authorized':False,
        'limits':'source+transitive-header-bound local test cache, not C++ proof; integration always re-executed; sandbox is research-only'
    }
    assert result['first']['outcome']=='Tested'
    assert result['changed_format']['reused']==1
    assert result['injected_wrong_receipt']['gate']=='Blocked'
    print(json.dumps(result,ensure_ascii=False,indent=2))
