"""Standalone V0.9 acceptance: real Axiom + GCC, isolated workspace."""
import json,shutil,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'studio'))
import server
from hashlib import sha256
with tempfile.TemporaryDirectory(prefix='axiom-v09-real-') as td:
    root=Path(td);work=root/'workspace'/'p';work.mkdir(parents=True)
    for f in (ROOT/'studio'/'templates'/'cpp-ledger').iterdir():
        if f.is_file():shutil.copy2(f,work/f.name)
    server.WORKSPACE=root/'workspace';server.ROOT=root;server.EVIDENCE=root/'.studio-data'/'evidence'
    studio=server.Studio()
    start=time.monotonic()
    wo=studio.workorders.create('p/project.json','p/ledger.cpp','编译测试有效账户转账行为')
    mode='bad' if '--bad' in sys.argv else 'good'
    code=(work/'ledger.cpp').read_text('utf-8')+'\n// V0.9 candidate reviewed for testing\n'
    if mode=='bad':code=code.replace('from -= amount;', 'from += amount;')
    wo=studio.workorders.submit(wo['id'],code)
    wo=studio.workorders.review(wo['id'],sha256(code.encode()).hexdigest(),True)
    wo=studio.workorders.apply(wo['id'],'human_authorized_apply')
    wo=studio.workorders.verify(wo['id'],True)
    deadline=time.monotonic()+105
    while time.monotonic()<deadline:
        wo=studio.workorders.poll(wo['id'])
        if wo['state']!='validating':break
        time.sleep(.5)
    print(json.dumps({'mode':mode,'state':wo['state'],'elapsed_s':round(time.monotonic()-start,2),
                      'job':wo['job_id'],'attempts':len(wo['attempts']),
                      'event_chain_len':len(wo['events']), 'assurance':wo['assurance']},ensure_ascii=False,indent=2))
    if wo['state']=='validating':raise SystemExit('validation did not finish within accepted budget')
    if wo['state']!=('blocked' if mode=='bad' else 'passed'):
        raise SystemExit('unexpected independent verification outcome')
    studio.executor.shutdown(wait=True,cancel_futures=True)
