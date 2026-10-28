#!/usr/bin/env python3
"""V0.6 real dual-source competing options and protected cross-target tests."""
import argparse,json,shutil,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'studio'))
import server

FILES=('ledger.ax','project.json','ledger.cpp','ledger.hpp','format.cpp','format.hpp',
       'test_ledger.cpp','test_format.cpp','test_integration.cpp')

def run():
    with tempfile.TemporaryDirectory(prefix='axiom-v06-real-') as tmp:
        base=Path(tmp)
        server.ROOT=base;server.WORKSPACE=base/'workspace';server.WORKSPACE.mkdir()
        server.EVIDENCE=base/'.studio-data'/'evidence'
        src=ROOT/'workspace'/'cpp_project';dest=server.WORKSPACE/'p';dest.mkdir()
        for f in FILES:shutil.copy2(src/f,dest/f)
        s=server.Studio()
        try:
            p=s.flow.create('V0.6 multiple alternatives','在同一受保护规格下比较真实 C++ 组合实现',
                            'p/ledger.ax','p/project.json')
            suggested=s.production.draft(p['id'])['suggested']
            req=[{**x,'text':'验证需求 '+x['property']+' 在多文件 C++ 候选中成立'} for x in suggested]
            s.production.freeze(p['id'],req,p['baseline'])
            model=s.flow.verify_spec(p['id'])
            if model['status']!='spec_ready':return {'status':'blocked_model','result':model}
            b=s.batches
            c=b.create(p['id'],['p/ledger.cpp','p/format.cpp']);bid=c['id']
            old={n:(dest/n).read_bytes() for n in FILES}
            correct={'ledger.cpp':old['ledger.cpp'].decode()+'\n// alternative A: reviewed C++ ledger\n',
                     'format.cpp':old['format.cpp'].decode()+'\n// alternative A: reviewed C++ formatter\n'}
            broken={'ledger.cpp':old['ledger.cpp'].decode()+'\n// alternative B: ledger unchanged\n',
                    'format.cpp':old['format.cpp'].decode().replace('std::to_string(from) + ":" + std::to_string(to)',
                                  'std::to_string(to) + ":" + std::to_string(from)')}
            b.stage(bid,'correct',correct);b.stage(bid,'wrong-receipt',broken)
            opts=b.get(bid)['options']
            evaluations={}
            for o in opts:
                started=time.monotonic();result=b.evaluate(bid,o['id'],trusted=True)
                current=next(x for x in result['options'] if x['id']==o['id'])
                evaluations[o['name']]={'state':current['state'],
                    'failed_at':current['verification']['result']['failed_at'],
                    'duration_s':round(time.monotonic()-started,3)}
            good=opts[0]
            b.select(bid,good['id'],good['digest'],'human_selected_after_comparison')
            after_install=b.apply(bid,good['digest'],'human_authorized_multi_file_apply')
            after_verify=b.verify_live(bid,trusted=True)
            if after_verify['state']=='decision_pending':
                finished=b.decide(bid,good['digest'],'human_approve_test_only')
            else:finished=after_verify
            return {'schema':'ax-v06-demonstration/0.6','id':bid,'state':finished['state'],
                    'independent_model_gate':model['status'], 'evaluation':evaluations,
                    'comparison':b.compare(bid),'audit_valid':b.audit(bid)['valid'],
                    'changed_targets':list(correct),
                    'protected_sources_unchanged':all((dest/n).read_bytes()==old[n] for n in
                        ('ledger.ax','project.json','test_ledger.cpp','test_format.cpp','test_integration.cpp')),
                    'production_release':False}
        finally:s.executor.shutdown(wait=False,cancel_futures=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path);a=ap.parse_args()
    result=run();raw=json.dumps(result,ensure_ascii=False,indent=2)
    if a.output:a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(raw+'\n')
    print(raw)
