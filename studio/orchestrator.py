"""Axiom Studio v0.3: durable, fail-closed workflow coordinator.

Trust model: local single-user coordination, NOT a signing authority or a
production release gate. Engine verdicts are independently recomputed; no
AI response is accepted as verification evidence.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
import os
from typing import Any
from contextlib import contextmanager

SCHEMA='ax-studio-workflow/0.3'
STAGES={
 'draft':'待验证规格', 'checking':'正在验证规格', 'spec_blocked':'规格未通过',
 'spec_ready':'规格通过，待构造', 'candidate_review':'等待候选人工审查',
 'candidate_apply':'等待应用已审查候选', 'candidate_validate':'等待独立验证',
 'decision_pending':'等待最终人工裁决', 'blocked':'实现验证未通过',
 'accepted_test_only':'测试级确认（非发布）', 'stale':'依赖变化，证据失效',
}
class FlowError(Exception):pass
class FlowConflict(FlowError):pass

def digest(raw:bytes)->str:return hashlib.sha256(raw).hexdigest()
def canonical(value:Any)->bytes:return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')

class Orchestrator:
    def __init__(self, *, db:Path, workspace:Path, engine:Path, evidence_root:Path, guard, proposals):
        self.db=db;self.workspace=workspace;self.engine=engine
        self.evidence_root=evidence_root;self.guard=guard;self.proposals=proposals
        self.lock=threading.RLock();db.parent.mkdir(parents=True,exist_ok=True)
        with self._connect() as cx:
            cx.executescript('''
              CREATE TABLE IF NOT EXISTS projects(
                id TEXT PRIMARY KEY, name TEXT NOT NULL, goal TEXT NOT NULL,
                spec TEXT NOT NULL, manifest TEXT, baseline TEXT NOT NULL,
                parent_id TEXT, candidate_id TEXT, status TEXT NOT NULL,
                revision INTEGER NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
                last_verification TEXT, decision TEXT);
              CREATE TABLE IF NOT EXISTS events(
                row_id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL,
                kind TEXT NOT NULL, payload TEXT NOT NULL, previous_hash TEXT NOT NULL,
                entry_hash TEXT NOT NULL, timestamp REAL NOT NULL);
              CREATE INDEX IF NOT EXISTS events_project ON events(project_id,row_id);
            ''')

    @contextmanager
    def _connect(self):
        cx=sqlite3.connect(self.db,timeout=10)
        cx.row_factory=sqlite3.Row
        try:
            yield cx
            cx.commit()
        except Exception:
            cx.rollback()
            raise
        finally:
            cx.close()

    def _file(self,rel,suffix):
        try:p=self.guard(rel)
        except Exception as exc:raise FlowError(f'工作区路径不可用：{exc}') from exc
        if p.suffix!=suffix:raise FlowError('文件类型不符合当前流程')
        return p

    def _baseline(self,spec,manifest):
        m={'spec':digest(self._file(spec,'.ax').read_bytes())}
        if manifest:
            mp=self._file(manifest,'.json')
            try:desc=json.loads(mp.read_text('utf-8'))
            except (ValueError,UnicodeError) as exc:raise FlowError('工程清单不可解析') from exc
            if desc.get('schema')!='ax-cpp-project/0.1':raise FlowError('不支持的工程清单协议')
            referenced=(mp.parent/desc.get('spec','')).resolve()
            if referenced!=self._file(spec,'.ax'):raise FlowError('规格与工程清单引用不一致')
            m['manifest']=digest(mp.read_bytes())
        return m

    def _row(self,cx,pid):
        if not isinstance(pid,str) or len(pid)!=24 or not pid.startswith('wf-'):
            raise FlowError('工作流标识无效')
        r=cx.execute('SELECT * FROM projects WHERE id=?',(pid,)).fetchone()
        if r is None:raise FlowError('工作流不存在')
        return dict(r)

    def _write(self,cx,pid,**updates):
        updates['updated']=time.time()
        keys=list(updates)
        cx.execute(f"UPDATE projects SET {','.join(k+'=?' for k in keys)} WHERE id=?",[updates[k] for k in keys]+[pid])

    def _event(self,cx,pid,kind,payload):
        previous=cx.execute('SELECT entry_hash FROM events WHERE project_id=? ORDER BY row_id DESC LIMIT 1',(pid,)).fetchone()
        prev=previous['entry_hash'] if previous else '0'*64
        moment=time.time()
        event={'project_id':pid,'kind':kind,'payload':payload,'previous_hash':prev,'timestamp':moment}
        entry=digest(canonical(event))
        cx.execute('INSERT INTO events(project_id,kind,payload,previous_hash,entry_hash,timestamp) VALUES(?,?,?,?,?,?)',
                   (pid,kind,canonical(payload).decode('utf-8'),prev,entry,moment))
        return entry

    def _changed(self,r):
        try: return self._baseline(r['spec'],r['manifest'])!=json.loads(r['baseline'])
        except (FlowError,OSError,ValueError):return True

    def _public(self,r):
        r=dict(r)
        stale=self._changed(r)
        for f in ('baseline','last_verification','decision'):
            r[f]=json.loads(r[f]) if r[f] else None
        r['stale']=stale
        r['effective_status']='stale' if r['stale'] else r['status']
        r['status_label']=STAGES[r['effective_status']]
        r['assurance']='model-bounded / cpp-tested-prototype only; no production release'
        r['schema']=SCHEMA
        return r

    def create(self,name,goal,spec,manifest=None,parent_id=None):
        if not isinstance(name,str) or not (2<=len(name.strip())<=100):raise FlowError('项目名称须为 2–100 字符')
        if not isinstance(goal,str) or not (4<=len(goal.strip())<=2000):raise FlowError('需要明确描述软件目标与验收意图')
        if manifest=='':manifest=None
        baseline=self._baseline(spec,manifest)
        with self.lock,self._connect() as cx:
            revision=1
            if parent_id:
                parent=self._row(cx,parent_id)
                revision=parent['revision']+1
            pid='wf-'+secrets.token_hex(10)+'0'
            now=time.time()
            cx.execute('INSERT INTO projects VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (pid,name.strip(),goal.strip(),spec,manifest,canonical(baseline).decode(),parent_id,None,'draft',revision,now,now,None,None))
            self._event(cx,pid,'project_created',{'name':name.strip(),'goal':goal.strip(),'spec':spec,
                             'manifest':manifest,'baseline':baseline,'revision':revision,'parent':parent_id})
            return self._public(self._row(cx,pid))

    def get(self,pid):
        with self.lock,self._connect() as cx:return self._public(self._row(cx,pid))

    def list(self):
        with self.lock,self._connect() as cx:
            rows=cx.execute('SELECT * FROM projects ORDER BY updated DESC LIMIT 100').fetchall()
            return [self._public(dict(r)) for r in rows]

    def _assert_not_stale(self,r):
        if self._changed(r):raise FlowConflict('规格或工程清单发生变化。旧流程不可继续；请建立演化分支，重新验证。')

    def _cli(self,evidence,action,path,extra=(),timeout=25):
        env=dict(os.environ);env['PYTHONPATH']=str(self.engine/'src')
        args=[sys.executable,'-m','axiom','--workspace',str(evidence),action,str(path),*extra]
        try:p=subprocess.run(args,cwd=self.workspace,env=env,stdin=subprocess.DEVNULL,capture_output=True,timeout=timeout)
        except subprocess.TimeoutExpired:return {'action':action,'returncode':-1,'outcome':'Unknown','error':'执行超时'}
        try:report=json.loads(p.stdout)
        except ValueError:report={'error':p.stderr.decode('utf-8','replace')[:1200] or p.stdout.decode('utf-8','replace')[:1200]}
        outcome=report.get('decision') or report.get('verification',{}).get('outcome') or report.get('report',{}).get('outcome') or report.get('outcome')
        return {'action':action,'returncode':p.returncode,'outcome':outcome,'report':report}

    def verify_spec(self,pid):
        with self.lock,self._connect() as cx:
            r=self._row(cx,pid);self._assert_not_stale(r)
            if r['status'] not in ('draft','spec_blocked'):
                raise FlowConflict('当前阶段不可重复初始化规格验证；请创建新演化分支')
            self._write(cx,pid,status='checking');self._event(cx,pid,'spec_verification_started',{'baseline':json.loads(r['baseline'])})
        evidence=self.evidence_root/pid;evidence.mkdir(parents=True,exist_ok=True)
        steps=[];passed=True
        try:
            for action,extra in [('check',()),('plan',()),('verify',()),('gate',('--target','model'))]:
                step=self._cli(evidence,action,self._file(r['spec'],'.ax'),extra)
                steps.append(step)
                if step['returncode']!=0 or (action=='gate' and step['outcome']!='Approved'):
                    passed=False;break
        except Exception as exc:
            passed=False;steps.append({'action':'exception','returncode':-1,'error':type(exc).__name__+': '+str(exc)})
        with self.lock,self._connect() as cx:
            current=self._row(cx,pid)
            if self._changed(current):passed=False
            status='spec_ready' if passed else 'spec_blocked'
            result={'passed':passed,'steps':steps,'checked_baseline':json.loads(r['baseline']),
                    'guarantee':'Bounded finite-model check only'}
            self._write(cx,pid,status=status,last_verification=canonical(result).decode())
            self._event(cx,pid,'spec_verification_finished',{'status':status,'steps':[
                 {'action':s['action'],'returncode':s['returncode'],'outcome':s.get('outcome')} for s in steps]})
            return self._public(self._row(cx,pid))

    def interrupt_model_verification(self,pid,expected_baseline):
        """Mark a genuinely interrupted checking stage Unknown and fail-closed.

        Used only on explicit worker recovery after prior runner process exited.
        Does not create positive evidence or authorize a retry automatically.
        """
        with self.lock,self._connect() as cx:
            row=self._row(cx,pid)
            if row['status']!='checking':return self._public(row)
            if json.loads(row['baseline'])!=expected_baseline:
                raise FlowConflict('检测到恢复对象基线不匹配')
            result={'passed':False,'steps':[{'action':'interrupted','returncode':-1,'outcome':'Unknown',
                                            'error':'模型检查中断；原有结果不可用'}],
                    'checked_baseline':expected_baseline,'guarantee':'No evidence accepted'}
            self._write(cx,pid,status='spec_blocked',last_verification=canonical(result).decode('utf-8'))
            self._event(cx,pid,'model_verification_interrupted',{'baseline':expected_baseline,'outcome':'Unknown'})
            return self._public(self._row(cx,pid))

    def attach_candidate(self,pid,candidate_id):
        with self.lock,self._connect() as cx:
            r=self._row(cx,pid);self._assert_not_stale(r)
            if r['status']!='spec_ready':raise FlowConflict('只有规格已通过的项目可以绑定构造候选')
            if not r['manifest']:raise FlowConflict('该工作流没有关联 C++ 工程，不能绑定实现候选')
            proposal=self.proposals.get(candidate_id)
            if proposal['manifest']!=r['manifest'] or proposal['spec']!=r['spec']:
                raise FlowConflict('候选关联的规格或工程与当前项目不一致')
            if not proposal['current']:raise FlowConflict('候选已因依赖变化而失效')
            if proposal['status']!='proposed':raise FlowConflict('只能先绑定未经审查的暂存候选')
            self._write(cx,pid,status='candidate_review',candidate_id=candidate_id)
            self._event(cx,pid,'candidate_attached',{'proposal_id':candidate_id,'code_sha256':proposal['code_sha256']})
            return self._public(self._row(cx,pid))

    def sync(self,pid):
        with self.lock,self._connect() as cx:
            r=self._row(cx,pid);self._assert_not_stale(r)
            if not r['candidate_id']:raise FlowConflict('尚未绑定候选')
            p=self.proposals.get(r['candidate_id'])
            if not p['current']:raise FlowConflict('候选或受保护源码已改变，必须重新建立流程')
            next_stage={'proposed':'candidate_review','reviewed':'candidate_apply',
                'applied':'candidate_validate','verified':'decision_pending','blocked':'blocked'}.get(p['status'])
            if next_stage is None:raise FlowConflict('候选状态无法与流程同步')
            if r['status']=='accepted_test_only':raise FlowConflict('已经裁决的工作流不允许重新同步改变结论')
            if r['status']!=next_stage:
                self._write(cx,pid,status=next_stage)
                self._event(cx,pid,'candidate_status_synchronized',{'proposal_status':p['status'],'next_stage':next_stage})
            return self._public(self._row(cx,pid))

    def decide(self,pid,operator_confirmation,expected_candidate_digest):
        if operator_confirmation!='approve_test_only':raise FlowError('必须明确确认测试级裁决，不得批准生产发布')
        with self.lock,self._connect() as cx:
            r=self._row(cx,pid);self._assert_not_stale(r)
            if r['status']!='decision_pending':raise FlowConflict('尚未达到最终裁决阶段')
            p=self.proposals.get(r['candidate_id'])
            if p['status']!='verified' or not p['current']:
                raise FlowConflict('候选当前不具备有效验证状态')
            if p['code_sha256']!=expected_candidate_digest:
                raise FlowConflict('裁决绑定的候选代码摘要不一致')
            v=p.get('validation') or {}
            checks=v.get('checks') or []
            required={'spec-model','spec-gate','cpp-full','cpp-gate'}
            if not v.get('passed') or {c.get('step') for c in checks}!=required:
                raise FlowConflict('独立验证链缺失，不得批准')
            if any(c.get('returncode')!=0 for c in checks):raise FlowConflict('独立验证存在失败')
            if any(c.get('outcome')!='Approved' for c in checks if c.get('step','').endswith('gate')):
                raise FlowConflict('Gate 未批准')
            # Live engine gate, in the same isolated evidence store used by candidate verification.
            evidence=self.db.parent/'candidate-evidence'/r['candidate_id']
            gate=self._cli(evidence,'cpp-project-gate',self._file(r['manifest'],'.json'),timeout=25)
            if gate['returncode']!=0 or gate['outcome']!='Approved':
                raise FlowConflict('实时实现 Gate 复核失败，不得确认')
            # Candidate may change between start and end of the gate; check again.
            fresh=self.proposals.get(r['candidate_id'])
            if not fresh['current'] or fresh['status']!='verified' or self._changed(r):
                raise FlowConflict('最终裁决前依赖已变化')
            decision={'scope':'cpp-tested-prototype','decision':'AcceptedForPrototypeOnly',
                      'candidate_id':r['candidate_id'],'code_sha256':p['code_sha256'],
                      'gate_decision':gate['outcome'],'at':time.time(),'production_release':False}
            self._write(cx,pid,status='accepted_test_only',decision=canonical(decision).decode())
            self._event(cx,pid,'human_test_only_decision',decision)
            return self._public(self._row(cx,pid))

    def fork(self,pid,name=None,goal=None,spec=None,manifest=None):
        prior=self.get(pid)
        return self.create(name or prior['name'],goal or prior['goal'],spec or prior['spec'],
                           manifest if manifest is not None else prior['manifest'],parent_id=pid)

    def events(self,pid):
        with self.lock,self._connect() as cx:
            self._row(cx,pid)
            return [dict(r) for r in cx.execute('SELECT * FROM events WHERE project_id=? ORDER BY row_id',(pid,))]

    def audit(self,pid):
        events=self.events(pid);previous='0'*64;issues=[]
        for i,e in enumerate(events):
            if e['previous_hash']!=previous:issues.append(f'event[{i}]: broken predecessor')
            try:payload=json.loads(e['payload'])
            except ValueError:issues.append(f'event[{i}]: invalid payload');break
            obj={'project_id':pid,'kind':e['kind'],'payload':payload,'previous_hash':e['previous_hash'],'timestamp':e['timestamp']}
            if digest(canonical(obj))!=e['entry_hash']:issues.append(f'event[{i}]: incorrect digest')
            previous=e['entry_hash']
        return {'project_id':pid,'events':len(events),'chain_valid':not issues,'issues':issues,
                'limitations':'Local unkeyed SHA-256 chain is not an externally anchored signature and does not prevent privileged rewrite.'}

    def overview(self):
        projects=self.list()
        return {'schema':SCHEMA,'projects':projects,
                'counts':{'total':len(projects),'spec_ready':sum(p['effective_status']=='spec_ready' for p in projects),
                          'pending_human':sum(p['effective_status'] in ('candidate_review','decision_pending') for p in projects),
                          'stale':sum(p['stale'] for p in projects),
                          'blocked':sum(p['effective_status'] in ('blocked','spec_blocked') for p in projects),
                          'prototype_accepted':sum(p['effective_status']=='accepted_test_only' for p in projects)},
                'production_releases_enabled':False}
