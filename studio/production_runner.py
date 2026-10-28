"""V0.8: persistent, bounded, fail-closed model-verification task runner.

A productivity-oriented batch executor, not a general autonomous AI agent.
It NEVER generates, changes, compiles, or executes C++ and NEVER approves a Gate itself.
The project's original independent Axiom model Gate is invoked by Orchestrator.
"""
from __future__ import annotations
import json
import io
import hashlib
import zipfile
import secrets
from contextlib import contextmanager
import sqlite3
import threading
import time
from pathlib import Path

from orchestrator import FlowError, FlowConflict

class RunnerError(FlowError):
    pass


def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


class ProductionRunner:
    def __init__(self, studio, db=None):
        self.studio = studio
        self.db = Path(db or studio.flow.db.parent/'production-runs.sqlite3')
        self.db.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.worker = None
        interrupted=[]
        with self._db() as cx:
            cx.executescript('''
            CREATE TABLE IF NOT EXISTS runs (
              id TEXT PRIMARY KEY, status TEXT NOT NULL, created REAL NOT NULL,
              ended REAL, requested INTEGER NOT NULL, result TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS items (
              run_id TEXT NOT NULL, position INTEGER NOT NULL, project_id TEXT NOT NULL,
              baseline TEXT NOT NULL, status TEXT NOT NULL, result TEXT,
              started REAL, ended REAL, PRIMARY KEY (run_id,project_id),
              FOREIGN KEY(run_id) REFERENCES runs(id)
            );
            CREATE INDEX IF NOT EXISTS run_items ON items(run_id,position);
            ''')
            # Kill/restart can interrupt work. No automatic resumed execution or false success.
            interrupted=[(r['project_id'],json.loads(r['baseline'])) for r in cx.execute(
                "SELECT project_id,baseline FROM items WHERE status='running'")]
            cx.execute("UPDATE items SET status='interrupted',ended=? WHERE status='running'", (time.time(),))
            cx.execute("UPDATE runs SET status='interrupted',ended=? WHERE status IN ('running','queued')", (time.time(),))
            cx.execute("UPDATE items SET status='interrupted',ended=? WHERE status='queued' AND run_id IN (SELECT id FROM runs WHERE status='interrupted')", (time.time(),))
        for pid,baseline in interrupted:
            try:self.studio.flow.interrupt_model_verification(pid,baseline)
            except (FlowError,ValueError,OSError):pass

    @contextmanager
    def _db(self):
        cx=sqlite3.connect(self.db,timeout=6)
        try:
            cx.row_factory=sqlite3.Row
            cx.execute('PRAGMA foreign_keys=ON')
            cx.execute('PRAGMA busy_timeout=6000')
            with cx:yield cx
        finally:
            cx.close()

    def _get(self,run_id):
        if not isinstance(run_id,str) or not run_id.startswith('batch-') or len(run_id)!=22:
            raise RunnerError('非法批次编号')
        with self._db() as cx:
            run=cx.execute('SELECT * FROM runs WHERE id=?',(run_id,)).fetchone()
            if run is None:raise RunnerError('未找到批次')
            items=cx.execute('SELECT * FROM items WHERE run_id=? ORDER BY position',(run_id,)).fetchall()
        record=dict(run);record['result']=json.loads(record['result']);record['items']=[]
        for item in items:
            i=dict(item);i['baseline']=json.loads(i['baseline']);i['result']=json.loads(i['result']) if i['result'] else None
            record['items'].append(i)
        return record

    def get(self,run_id):
        return self._get(run_id)

    def list(self,limit=15):
        with self._db() as cx:
            ids=[r['id'] for r in cx.execute('SELECT id FROM runs ORDER BY created DESC LIMIT ?', (min(max(limit,1),50),))]
        return {'runs':[self._get(i) for i in ids], 'scope':'Finite model checks only; no native execution, no automatic acceptance.'}

    def create(self,project_ids=None,retry_failed=False):
        """Plan only. Re-running a previously blocked model needs explicit retry_failed."""
        if project_ids is not None and (not isinstance(project_ids,list) or len(project_ids)>20 or len(set(project_ids))!=len(project_ids)):
            raise RunnerError('项目列表必须是最多 20 项的无重复数组')
        if retry_failed is not True and retry_failed is not False:
            raise RunnerError('retry_failed 必须为布尔值')
        projects=self.studio.flow.list()
        mapping={p['id']:p for p in projects}
        selected=project_ids if project_ids is not None else [p['id'] for p in projects if p['effective_status']=='draft']
        if not selected:raise RunnerError('没有需要自动执行的规格验证任务')
        tasks=[]
        for pid in selected:
            if not isinstance(pid,str) or pid not in mapping:raise RunnerError('项目不存在或不在当前可见范围')
            p=self.studio.flow.get(pid)
            if p['stale']:raise RunnerError('含过期项目；必须先建立演化分支：'+p['name'])
            if p['status'] not in (('draft','spec_blocked') if retry_failed else ('draft',)):
                raise RunnerError('项目不在安全自动验证阶段：'+p['name'])
            tasks.append((pid,p['baseline']))
        with self.lock,self._db() as cx:
            cx.execute('BEGIN IMMEDIATE')
            active=cx.execute("SELECT id FROM runs WHERE status IN ('queued','running') LIMIT 1").fetchone()
            if active:raise RunnerError('已有正在执行的生产批次：'+active['id'])
            run_id='batch-'+secrets.token_hex(8)
            cx.execute('INSERT INTO runs(id,status,created,ended,requested,result) VALUES(?,?,?,?,?,?)',
                       (run_id,'queued',time.time(),None,len(tasks),canonical({'scope':'model-only','completed':0,'passed':0,'blocked':0,'stale':0})))
            for i,(pid,baseline) in enumerate(tasks):
                cx.execute('INSERT INTO items(run_id,position,project_id,baseline,status) VALUES(?,?,?,?,?)',
                           (run_id,i,pid,canonical(baseline),'queued'))
        return self._get(run_id)

    def start(self,run_id):
        with self.lock:
            if self.worker and self.worker.is_alive():raise RunnerError('已有工作线程正在运行')
            record=self._get(run_id)
            if record['status']!='queued':raise RunnerError('批次不能重复启动')
            self.worker=threading.Thread(target=self.execute,args=(run_id,),daemon=True,name='axiom-model-batch')
            self.worker.start()
        return self._get(run_id)

    def execute(self,run_id):
        """Run explicitly queued jobs. Fail-closed on crash, state drift or model failure."""
        with self.lock:
            record=self._get(run_id)
            if record['status']!='queued':raise RunnerError('只能执行尚未运行的批次')
            with self._db() as cx:
                cx.execute('BEGIN IMMEDIATE')
                updated=cx.execute("UPDATE runs SET status='running' WHERE id=? AND status='queued'",(run_id,))
                if updated.rowcount!=1:raise RunnerError('任务已被其他执行者领取')
        for item in record['items']:
            pid=item['project_id'];status='failed';detail={}
            try:
                with self._db() as cx:
                    update=cx.execute("UPDATE items SET status='running',started=? WHERE run_id=? AND project_id=? AND status='queued'",(time.time(),run_id,pid))
                    if update.rowcount!=1:raise RunnerError('任务已被领取或中断，拒绝重复执行')
                p=self.studio.flow.get(pid)
                if p['stale'] or p['baseline']!=item['baseline'] or p['status'] not in ('draft','spec_blocked'):
                    status='stale';detail={'reason':'项目或规格状态在规划后变化，拒绝执行'}
                else:
                    outcome=self.studio.flow.verify_spec(pid)
                    status='passed' if outcome['last_verification'] and outcome['last_verification']['passed'] and not outcome['stale'] else 'blocked'
                    detail={'effective_status':outcome['effective_status'], 'revision':outcome['revision'],
                            'steps':[{'action':s.get('action'),'returncode':s.get('returncode'),'outcome':s.get('outcome'),'error':s.get('error')}
                                     for s in (outcome.get('last_verification') or {}).get('steps',[])],
                            'assurance':'Bounded model Gate; no native execution and no release permission'}
            except Exception as exc:
                status='failed';detail={'error':type(exc).__name__+': '+str(exc)[:350]}
            with self._db() as cx:
                cx.execute('UPDATE items SET status=?,result=?,ended=? WHERE run_id=? AND project_id=?',
                           (status,canonical(detail),time.time(),run_id,pid))
        final=self._get(run_id)
        counts={k:sum(item['status']==k for item in final['items']) for k in ('passed','blocked','stale','failed','interrupted')}
        summary={'scope':'model-only', 'completed':sum(counts.values()),**counts, 'requested':len(final['items']),
                 'release_approved':False,'cpp_executed':False}
        with self._db() as cx:
            cx.execute('UPDATE runs SET status=?,ended=?,result=? WHERE id=?',
                       ('finished' if counts['passed']==len(final['items']) else 'needs_attention',time.time(),canonical(summary),run_id))
        return self._get(run_id)

    def retry(self,run_id):
        """Create a NEW run (not overwrite a historical record) after explicit operator request."""
        original=self._get(run_id)
        if original['status'] in ('running','queued'):raise RunnerError('当前批次仍在执行')
        selected=[]
        for item in original['items']:
            if item['status'] not in ('failed','blocked','interrupted'):continue
            p=self.studio.flow.get(item['project_id'])
            if p['stale'] or p['baseline']!=item['baseline']:
                raise RunnerError('规格已演化；不能复用原批次进行重试')
            if p['status'] not in ('draft','spec_blocked'):
                raise RunnerError('项目状态不能重试：'+p['status'])
            selected.append(item['project_id'])
        if not selected:raise RunnerError('没有可手动重试的项目')
        return self.create(selected,retry_failed=True)

    def report(self,run_id):
        report=self._get(run_id)
        report['ready_for_native_release']=False
        report['next_steps']=[]
        for item in report['items']:
            pid=item['project_id']
            if item['status']=='passed': action='人工核对需求映射，冻结生产契约'
            elif item['status']=='blocked':action='查看反例并修订规格；规格变更后建立新演化版本'
            elif item['status']=='stale':action='检查版本变化，建立演化分支并重新规划'
            else:action='检查故障并手动重试；不能沿用失败证据'
            report['next_steps'].append({'project_id':pid,'action':action,'status':item['status']})
        return report

    def export(self,run_id):
        """Portable unsigned review package: report + handoffs for ONLY passed model tasks.

        Never includes the local evidence DB, tokens, or any keys. Receiver must revalidate.
        """
        report=self.report(run_id)
        if report['status'] in ('queued','running'):
            raise RunnerError('运行中的批次不可导出最终报告')
        members={'report.json':(canonical(report)+'\n').encode('utf-8')}
        for item in report['items']:
            if item['status']!='passed':continue
            data,_name=self.studio.launchpad.export(item['project_id'])
            if len(data)>5*1024*1024:raise RunnerError('单项目交接包超过 5 MiB')
            members['projects/'+item['project_id']+'.zip']=data
        total=sum(map(len,members.values()))
        if total>30*1024*1024:raise RunnerError('汇总交接包超过 30 MiB')
        listing={'schema':'axiom-batch-handoff/0.8','run_id':run_id,
                 'files':{key:hashlib.sha256(data).hexdigest() for key,data in sorted(members.items())},
                 'assurance':'unsigned, not production release; independent re-verification required'}
        members['SHA256.json']=(canonical(listing)+'\n').encode('utf-8')
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            for name,raw in sorted(members.items()):
                zi=zipfile.ZipInfo(name,date_time=(2026,10,28,0,0,0))
                zi.compress_type=zipfile.ZIP_DEFLATED
                z.writestr(zi,raw)
        return stream.getvalue(),f'Axiom-Model-Batch-{run_id}.zip'
