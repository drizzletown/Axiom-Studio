"""Axiom Studio 1.5 — outcome-oriented production pilot.

The pilot coordinates EXISTING authoritative Axiom workflows. Its only executable
operation is an explicitly requested finite-model check; AI, C++, approvals,
Gate policy, production release and protected specs are never changed here.

A pilot is NOT an alternative source of verification truth. Every presentation
is recomputed against current project state, inputs and the underlying audit.
"""
from __future__ import annotations
import hashlib
import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from contextlib import contextmanager

from orchestrator import FlowError, FlowConflict, canonical


class PilotError(FlowError):
    pass


class PilotConflict(FlowConflict):
    pass


def sha(value):
    return hashlib.sha256(canonical(value)).hexdigest()


class ProductionPilot:
    STEPS=(
        ('intent','明确软件目标','你希望软件做到什么？','human'),
        ('model','验证行为规则','这些行为规则自身是否一致？','safe'),
        ('contract','确认验收条件','哪些规则真正表达了你的业务需求？','human'),
        ('construct','提出实现方案','让 AI 或现有工具形成可以审查的实现','ai_human'),
        ('verify','独立检查实现','实际实现是否通过独立测试？','trusted'),
        ('decide','决定是否接受','检查证据后，由你决定是否接受','human'),
    )

    def __init__(self,studio,db=None):
        self.studio=studio
        self.db=Path(db) if db else studio.flow.db.parent/'pilot.sqlite3'
        self.db.parent.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock()
        self.inflight=set()
        with self._connect() as cx:
            cx.executescript('''
                CREATE TABLE IF NOT EXISTS missions(
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                    baseline_digest TEXT NOT NULL, revision INTEGER NOT NULL,
                    status TEXT NOT NULL, started REAL NOT NULL, updated REAL NOT NULL,
                    result TEXT);
                CREATE INDEX IF NOT EXISTS mission_project ON missions(project_id,updated);
                CREATE TABLE IF NOT EXISTS pilot_events(
                    row_id INTEGER PRIMARY KEY AUTOINCREMENT, mission_id TEXT NOT NULL,
                    kind TEXT NOT NULL, payload TEXT NOT NULL,
                    previous_hash TEXT NOT NULL, entry_hash TEXT NOT NULL,
                    created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS pilot_events_mission ON pilot_events(mission_id,row_id);
            ''')
            # A process crash must never silently resume an action requiring authorization.
            interrupted=cx.execute("SELECT * FROM missions WHERE status='running'").fetchall()
            for row in interrupted:
                cx.execute("UPDATE missions SET status='interrupted',updated=? WHERE id=?",(time.time(),row['id']))
                self._event(cx,row['id'],'interrupted',{'reason':'previous process ended while operation was running'})
        # The authoritative workflow can be stranded in checking after a hard crash.
        for row in interrupted:
            try:
                project=self.studio.flow.get(row['project_id'])
                if project['effective_status']=='checking':
                    self.studio.flow.interrupt_model_verification(row['project_id'],project['baseline'])
            except (FlowError,OSError,KeyError,ValueError):
                # Do not convert unknown state to success; the UI shows interruption.
                pass

    @contextmanager
    def _connect(self):
        cx=sqlite3.connect(self.db,timeout=8)
        cx.row_factory=sqlite3.Row
        try:
            yield cx
            cx.commit()
        except Exception:
            cx.rollback();raise
        finally:
            cx.close()

    def _event(self,cx,mid,kind,payload):
        prev=cx.execute('SELECT entry_hash FROM pilot_events WHERE mission_id=? ORDER BY row_id DESC LIMIT 1',(mid,)).fetchone()
        prevhash=prev['entry_hash'] if prev else '0'*64
        when=time.time()
        body={'mission_id':mid,'kind':kind,'payload':payload,'previous_hash':prevhash,'created':when}
        digest=sha(body)
        cx.execute('INSERT INTO pilot_events(mission_id,kind,payload,previous_hash,entry_hash,created) VALUES(?,?,?,?,?,?)',
                   (mid,kind,canonical(payload).decode('utf-8'),prevhash,digest,when))

    def _row(self,cx,mid):
        if not isinstance(mid,str) or len(mid)>90:raise PilotError('无效生产任务编号')
        row=cx.execute('SELECT * FROM missions WHERE id=?',(mid,)).fetchone()
        if row is None:raise PilotError('生产任务不存在')
        return dict(row)

    def create(self,project_id):
        p=self.studio.flow.get(project_id)
        if p['stale']:raise PilotConflict('输入发生变化，必须先建立演化项目')
        with self.lock,self._connect() as cx:
            existing=cx.execute('SELECT id FROM missions WHERE project_id=? ORDER BY started DESC LIMIT 1',(project_id,)).fetchone()
            if existing:
                v=self.get(existing['id'])
                if v['baseline_digest']==sha(p['baseline']) and v['revision']==p['revision']:
                    return v
            mid='mission-'+secrets.token_hex(10)
            now=time.time()
            cx.execute('INSERT INTO missions VALUES(?,?,?,?,?,?,?,?)',
                       (mid,project_id,sha(p['baseline']),p['revision'],'ready',now,now,None))
            self._event(cx,mid,'created',{'project_id':project_id,'revision':p['revision'],'baseline_digest':sha(p['baseline'])})
        return self.get(mid)

    def audit(self,mid):
        with self.lock,self._connect() as cx:
            self._row(cx,mid)
            rows=cx.execute('SELECT * FROM pilot_events WHERE mission_id=? ORDER BY row_id',(mid,)).fetchall()
        prev='0'*64;ok=bool(rows);events=[]
        for r in rows:
            try:payload=json.loads(r['payload'])
            except (ValueError,TypeError):payload=None;ok=False
            body={'mission_id':mid,'kind':r['kind'],'payload':payload,'previous_hash':r['previous_hash'],'created':r['created']}
            valid=r['previous_hash']==prev and r['entry_hash']==sha(body)
            ok=ok and valid
            prev=r['entry_hash']
            events.append({'kind':r['kind'],'created':r['created'],'valid':valid,'payload':payload})
        return {'valid':ok,'events':events,'head':prev,'scope':'Unsigned local hash chain; not a cryptographic signature'}

    def _view(self,row):
        p=self.studio.flow.get(row['project_id'])
        prod=self.studio.production.overview(row['project_id'])
        flow_audit=self.studio.flow.audit(row['project_id'])
        pilot_audit=self.audit(row['id'])
        baseline_current=(sha(p['baseline'])==row['baseline_digest'] and p['revision']==row['revision']
                          and not p['stale'])
        trusted=bool(flow_audit.get('chain_valid')) and pilot_audit['valid']
        source_ok=bool(baseline_current and trusted)
        is_model_ok=bool(source_ok and p.get('last_verification') and p['last_verification'].get('passed')
                         and p['effective_status']!='checking')
        blockers=prod.get('blockers') or []
        contract=prod.get('contract')
        contract_ok=bool(is_model_ok and contract and not any(
            x=='PRODUCTION_CONTRACT_STALE' or x.startswith('REQUIREMENT_NOT_MODEL_SUPPORTED:') for x in blockers))
        # The independent verification and the decision are authoritative workflow facts.
        state=p['effective_status']
        impl_stage=state in ('candidate_review','candidate_apply','candidate_validate','decision_pending','accepted_test_only','blocked')
        implementation_ok=bool(contract_ok and impl_stage)
        independent_ok=bool(contract_ok and state in ('decision_pending','accepted_test_only'))
        accepted=bool(contract_ok and state=='accepted_test_only' and p.get('decision'))
        passed=[source_ok,is_model_ok,contract_ok,implementation_ok,independent_ok,accepted]
        tasks=[]
        for (id_,label,question,owner),done in zip(self.STEPS,passed):
            tasks.append({'id':id_,'label':label,'question':question,'owner':owner,
                          'state':'complete' if done else 'pending'})
        if not baseline_current:
            condition='stale';action={'id':'evolve','label':'建立新版本','help':'输入已变化；旧证据不再适用','mode':'human'}
        elif not trusted:
            condition='blocked';action={'id':'audit','label':'检查证据完整性','help':'项目或任务审计链异常，所有准入保持阻断','mode':'blocked'}
        elif row['status']=='running':
            condition='running';action={'id':'poll','label':'正在独立检查','help':'可刷新查看检查结果；不会运行 C++','mode':'wait'}
        elif row['status'] in ('interrupted','blocked'):
            condition='blocked';action={'id':'inspect','label':'检查意外中断','help':'运行异常中断；不自动重试、不自动继承结果','mode':'blocked'}
        elif state=='spec_blocked':
            condition='blocked';action={'id':'repair_spec','label':'查看规格失败原因','help':'检查反例并修改规格；修改后建立新版本','mode':'human'}
        elif not is_model_ok:
            condition='actionable';action={'id':'verify_spec','label':'检查行为规则','help':'一键执行安全的规格检查和模型 Gate，不运行本地 C++','mode':'safe'}
        elif not contract_ok:
            condition='needs_human';action={'id':'confirm_contract','label':'确认软件验收规则','help':'人工核对需求是否真正由已验证规则表达','mode':'human'}
        elif state=='accepted_test_only':
            condition='tested_only';action={'id':'evolve','label':'查看结果并规划新版本','help':'已获得限定测试级裁决；不是生产发布许可','mode':'human'}
        elif state in ('candidate_review','candidate_apply','candidate_validate','decision_pending','blocked'):
            condition='needs_human';action={'id':'review_implementation','label':'处理候选和独立验证','help':'审查、授权测试与裁决均须在原受保护流程完成','mode':'human'}
        else:
            condition='needs_human';action={'id':'construct','label':'让 AI 提出实现方案','help':'从冻结规则产生受约束任务，候选须由人工审核','mode':'human'}
        if not source_ok:
            tasks[0]['state']='blocked'
        if state=='spec_blocked':tasks[1]['state']='blocked'
        if row['status'] in ('interrupted','blocked'):tasks[1]['state']='blocked'
        if row['status']=='running':tasks[1]['state']='running'
        return {'schema':'ax-studio-production-pilot/1.5','id':row['id'],'project_id':row['project_id'],
                'project_name':p['name'],'goal':p['goal'],'revision':row['revision'],
                'baseline_digest':row['baseline_digest'],'condition':condition,
                'current_workflow_state':state,'operation_state':row['status'],
                'stale':not baseline_current,'audit_valid':trusted,
                'steps':tasks,'next_action':action,'blockers':blockers,
                'last_result':json.loads(row['result']) if row['result'] else None,
                'guarantee':'Bounded finite-model checks and reviewed trusted-local tests only',
                'production_release_authorized':False}

    def get(self,mid):
        with self.lock,self._connect() as cx:row=self._row(cx,mid)
        return self._view(row)

    def list(self):
        with self.lock,self._connect() as cx:
            ids=[r['id'] for r in cx.execute('SELECT id FROM missions ORDER BY updated DESC LIMIT 100').fetchall()]
        out=[]
        for mid in ids:
            try:out.append(self.get(mid))
            except (FlowError,KeyError,OSError,ValueError) as exc:
                out.append({'id':mid,'condition':'blocked','error':str(exc)[:200],
                            'production_release_authorized':False})
        return {'missions':out}

    def advance_safe(self,mid,revision,baseline_digest):
        """Only authorized operation: explicitly run original model validation.

        Native execution, code generation, policy edits and human approvals have
        no pilot API, even if a caller supplies arbitrary JSON.
        """
        with self.lock:
            view=self.get(mid)
            if view['condition']!='actionable' or view['next_action']['id']!='verify_spec':
                raise PilotConflict('当前生产阶段不允许自动推进；请处理相应人工步骤或阻断原因')
            if type(revision) is not int or revision!=view['revision'] or baseline_digest!=view['baseline_digest']:
                raise PilotConflict('构造计划与当前项目版本不一致，请刷新')
            with self._connect() as cx:
                row=self._row(cx,mid)
                if row['status']!='ready':raise PilotConflict('生产步骤已经启动或已经终止')
                cx.execute('UPDATE missions SET status=?,updated=? WHERE id=?',('running',time.time(),mid))
                self._event(cx,mid,'safe_model_requested',{'revision':revision,'baseline_digest':baseline_digest})
            self.inflight.add(mid)
            try:self.studio.executor.submit(self._run_safe,mid,view['project_id'])
            except Exception:
                self.inflight.discard(mid)
                with self._connect() as cx:
                    cx.execute('UPDATE missions SET status=?,updated=? WHERE id=?',('interrupted',time.time(),mid))
                    self._event(cx,mid,'dispatch_failed',{})
                raise
        return self.get(mid)

    def _run_safe(self,mid,pid):
        try:
            result=self.studio.flow.verify_spec(pid)
            passed=bool(result.get('last_verification') and result['last_verification'].get('passed')
                        and not result['stale'])
            summary={'outcome':'model_approved' if passed else 'blocked','revision':result['revision'],
                     'workflow_state':result['effective_status'],'scope':'bounded-model'}
        except Exception as exc:
            passed=False
            summary={'outcome':'unknown','error':type(exc).__name__+': '+str(exc)[:500]}
        with self.lock:
            with self._connect() as cx:
                cx.execute('UPDATE missions SET status=?,updated=?,result=? WHERE id=?',
                           ('finished' if passed else 'blocked',time.time(),canonical(summary).decode(),mid))
                self._event(cx,mid,'safe_model_finished',summary)
            self.inflight.discard(mid)

    def handoff(self,mid):
        """Untrusted summary for human/AI handoff: not a signed evidence certificate."""
        view=self.get(mid)
        history=self.audit(mid)
        report={'schema':'ax-studio-pilot-handoff/1.5','mission':view,'audit':history,
                'warning':'Unsigned summary. Use Axiom source evidence and live Gates for any decision.'}
        return {'report':report,'sha256':sha(report),'filename':mid+'-handoff.json'}
