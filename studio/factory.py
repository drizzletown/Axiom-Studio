"""Axiom Studio V0.5: durable, fail-closed AI software production campaigns.

Production is *orchestration*, not AI's authority to modify protected artifacts.
State is reconstructed against Axiom workflow/proposal and frozen production
contract. All candidate edits require explicit human review and apply; running
local C++ requires separate human trusted-code confirmation. No release Gate.

The local token is not a multi-user identity system. A restarted server cannot
silently finish an interrupted validation job. Validation and Gate results are
supplied only by the pre-existing independent Axiom engine path.
"""
from __future__ import annotations
import json
import secrets
import time
from pathlib import Path
from orchestrator import FlowConflict, FlowError, canonical, digest
from production import _sha

STATES={
 'spec_pending':'规格验证待执行', 'candidate_pending':'等待 AI / 人工候选',
 'human_review':'候选等待人工审查', 'human_apply':'等待人工确认应用',
 'validation_pending':'等待可信执行授权', 'validating':'独立验证进行中',
 'human_decision':'等待人工准入裁决', 'completed_test_only':'仅原型测试级确认',
 'blocked':'验证失败或需重新建立演化分支', 'stale':'已失效',
}

class Factory:
    def __init__(self,studio):
        self.studio=studio; self.flow=studio.flow; self.production=studio.production
        with self.flow.lock,self.flow._connect() as cx:
            cx.executescript('''
            CREATE TABLE IF NOT EXISTS factory_campaigns(
              id TEXT PRIMARY KEY, project_id TEXT NOT NULL, snapshot TEXT NOT NULL,
              state TEXT NOT NULL, candidate_id TEXT, job_id TEXT,
              diagnostic TEXT, created REAL NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS factory_events(
              seq INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id TEXT NOT NULL,
              kind TEXT NOT NULL, payload TEXT NOT NULL, previous_hash TEXT NOT NULL,
              entry_hash TEXT NOT NULL, timestamp REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS factory_events_campaign ON factory_events(campaign_id,seq);
            ''')

    def _row(self,cx,cid):
        if not isinstance(cid,str) or not cid.startswith('factory-') or len(cid)!=25:
            raise FlowError('非法生产任务标识')
        r=cx.execute('SELECT * FROM factory_campaigns WHERE id=?',(cid,)).fetchone()
        if r is None:raise FlowError('生产任务不存在')
        return dict(r)

    def _event(self,cx,cid,kind,payload):
        r=cx.execute('SELECT entry_hash FROM factory_events WHERE campaign_id=? ORDER BY seq DESC LIMIT 1',(cid,)).fetchone()
        previous=r['entry_hash'] if r else '0'*64
        at=time.time()
        obj={'campaign_id':cid,'kind':kind,'payload':payload,'previous_hash':previous,'timestamp':at}
        entry=digest(canonical(obj))
        cx.execute('INSERT INTO factory_events(campaign_id,kind,payload,previous_hash,entry_hash,timestamp) VALUES(?,?,?,?,?,?)',
                   (cid,kind,canonical(payload).decode(),previous,entry,at))

    def _set(self,cx,cid,**kw):
        kw['updated']=time.time()
        cols=list(kw)
        cx.execute('UPDATE factory_campaigns SET '+','.join(k+'=?' for k in cols)+' WHERE id=?',
                   [kw[k] for k in cols]+[cid])

    def _fresh(self,r):
        snap=json.loads(r['snapshot']);p=self.flow.get(r['project_id'])
        if p['stale'] or p['baseline']!=snap['baseline']:return False
        if not self.flow.audit(p['id'])['chain_valid']:return False
        assess=self.production.overview(p['id'])
        if not assess.get('contract') or assess['contract_digest']!=snap['contract_digest']:return False
        # Contract and task packet are both immutable, but recalculate to
        # detect file drift and any changes in task-packet semantics.
        try:
            pkt=self.production.task_packet(p['id'])
            return pkt['digest']==snap['task_digest']
        except (FlowError,ValueError,OSError):return False

    def _effective(self,r):
        if not self._fresh(r):return 'stale'
        return r['state']

    def _public(self,r):
        data=dict(r);data['snapshot']=json.loads(r['snapshot'])
        data['diagnostic']=json.loads(r['diagnostic']) if r['diagnostic'] else None
        data['effective_state']=self._effective(r)
        data['label']=STATES[data['effective_state']]
        data['task_dag']=[
          {'id':'spec','type':'independent-model-check','depends_on':[]},
          {'id':'construct','type':'ai-or-human-candidate','depends_on':['spec']},
          {'id':'review','type':'human-review','depends_on':['construct']},
          {'id':'apply','type':'human-apply','depends_on':['review']},
          {'id':'verify','type':'independent-implementation-verification','depends_on':['apply']},
          {'id':'decision','type':'human-test-only-decision','depends_on':['verify']}]
        data['production_release']=False
        data['security_scope']='trusted local workspace; no autonomous code execution, no production release'
        return data

    def create(self,pid,target):
        """Pin contract/spec/manifest/target and create an idempotent campaign."""
        p=self.flow.get(pid)
        if not p['manifest']:raise FlowConflict('必须关联 C++ 工程清单')
        pkt=self.production.task_packet(pid)
        if not self.flow.audit(pid)['chain_valid']:raise FlowConflict('流程审计失败')
        if p['status'] not in ('draft','spec_ready','spec_blocked'):
            raise FlowConflict('候选流程已启动，请先完成现有流程或创建演化分支')
        for item in self.studio.batches.list(pid)['batches']:
            if item['state'] not in ('blocked','rolled_back','accepted_test_only'):
                raise FlowConflict('同一项目已存在多目标构造事务，禁止并行创建单目标任务')
        # Validate editable target through the existing protected source/manifest policy.
        self.studio.proposals._manifest(p['manifest'],target)
        snapshot={'schema':'ax-factory-campaign/0.5','project_id':pid,'baseline':p['baseline'],
                  'contract_digest':pkt['packet']['contract_digest'],
                  'task_digest':pkt['digest'],'target':target,'manifest':p['manifest'],
                  'specification':p['spec'],'max_automatic_repairs':0}
        now=time.time()
        with self.flow.lock,self.flow._connect() as cx:
            old=cx.execute('SELECT * FROM factory_campaigns WHERE project_id=? ORDER BY created DESC',(pid,)).fetchall()
            for r in old:
                if r['state'] not in ('blocked','completed_test_only'):
                    if r['snapshot']==canonical(snapshot).decode():
                        return self._public(dict(r))
                    raise FlowConflict('同一项目已有未完成的构造活动；一次只能由一条受审查的候选链修改工作区')
            cid='factory-'+secrets.token_hex(8)+'x'
            state='spec_pending' if p['status']!='spec_ready' else 'candidate_pending'
            cx.execute('INSERT INTO factory_campaigns VALUES(?,?,?,?,?,?,?,?,?)',
                       (cid,pid,canonical(snapshot).decode(),state,None,None,None,now,now))
            self._event(cx,cid,'campaign_created',{'snapshot_digest':_sha(snapshot),'state':state})
            return self._public(self._row(cx,cid))

    def get(self,cid):
        with self.flow.lock,self.flow._connect() as cx:r=self._public(self._row(cx,cid))
        if not self.events(cid)['valid']:
            r['effective_state']='stale';r['label']=STATES['stale']
        return r

    def list(self,pid):
        self.flow.get(pid)
        with self.flow.lock,self.flow._connect() as cx:
            rows=cx.execute('SELECT * FROM factory_campaigns WHERE project_id=? ORDER BY created DESC',(pid,)).fetchall()
            return {'campaigns':[self._public(dict(r)) for r in rows]}

    def _guard(self,cx,cid,allowed):
        r=self._row(cx,cid)
        if not self._fresh(r) or not self.events(cid)['valid']:
            raise FlowConflict('生产契约/规格/流程审计已失效，禁止继续操作')
        if r['state'] not in allowed:raise FlowConflict('当前状态禁止该操作：'+r['state'])
        return r

    def verify_spec(self,cid):
        with self.flow.lock,self.flow._connect() as cx:r=self._guard(cx,cid,{'spec_pending'})
        try:result=self.flow.verify_spec(r['project_id'])
        except (FlowError,ValueError) as exc:
            result={'status':'spec_blocked','error':str(exc)}
        new='candidate_pending' if result.get('status')=='spec_ready' else 'blocked'
        with self.flow.lock,self.flow._connect() as cx:
            self._guard(cx,cid,{'spec_pending'})
            diagnostic=None if new!='blocked' else canonical({'reason':'SPEC_MODEL_FAILED','details':result.get('error')}).decode()
            self._set(cx,cid,state=new,diagnostic=diagnostic)
            self._event(cx,cid,'model_gate_completed',{'state':new})
            return self._public(self._row(cx,cid))

    def candidate(self,cid,code=None,model_consent=False):
        with self.flow.lock,self.flow._connect() as cx:r=self._guard(cx,cid,{'candidate_pending'})
        s=json.loads(r['snapshot'])
        if self.flow.get(r['project_id'])['status']!='spec_ready':raise FlowConflict('模型 Gate 尚未通过')
        if code is None:
            if model_consent is not True:raise FlowError('外部模型传输需要单独确认')
            proposal=self.studio.proposals.generate(s['manifest'],s['target'],True)
        else:
            if model_consent:raise FlowError('手工候选不可同时要求调用模型')
            proposal=self.studio.proposals.create(s['manifest'],s['target'],code,origin='pasted')
        # Enforce use of the already verified workflow rather than standalone proposals.
        try:self.flow.attach_candidate(r['project_id'],proposal['id'])
        except Exception:
            # Orphaned staged candidate stays unapproved; fail-closed.
            raise
        with self.flow.lock,self.flow._connect() as cx:
            self._guard(cx,cid,{'candidate_pending'})
            self._set(cx,cid,state='human_review',candidate_id=proposal['id'])
            self._event(cx,cid,'candidate_staged',{'proposal_id':proposal['id'],'sha256':proposal['code_sha256'],
                                                 'source':proposal['source']})
            return self._public(self._row(cx,cid))

    def review(self,cid,expected_sha,confirmation):
        if confirmation!='human_review_approved':raise FlowError('需人工明确批准候选摘要')
        with self.flow.lock,self.flow._connect() as cx:r=self._guard(cx,cid,{'human_review'})
        p=self.studio.proposals.review(r['candidate_id'],expected_sha,True)
        self.flow.sync(r['project_id'])
        with self.flow.lock,self.flow._connect() as cx:
            self._set(cx,cid,state='human_apply');self._event(cx,cid,'candidate_human_reviewed',{'sha256':p['code_sha256']})
            return self._public(self._row(cx,cid))

    def apply(self,cid,confirmation):
        if confirmation!='human_apply_approved':raise FlowError('应用前需人工明确授权')
        with self.flow.lock,self.flow._connect() as cx:r=self._guard(cx,cid,{'human_apply'})
        self.studio.proposals.apply(r['candidate_id'])
        self.flow.sync(r['project_id'])
        with self.flow.lock,self.flow._connect() as cx:
            self._set(cx,cid,state='validation_pending')
            self._event(cx,cid,'candidate_applied',{'proposal_id':r['candidate_id']})
            return self._public(self._row(cx,cid))

    def validate(self,cid,trusted):
        if trusted is not True:raise FlowError('执行 C++ 前必须独立确认可信本地代码')
        with self.flow.lock,self.flow._connect() as cx:r=self._guard(cx,cid,{'validation_pending'})
        job=self.studio.start_proposal_job(r['candidate_id'],trusted=True)
        with self.flow.lock,self.flow._connect() as cx:
            self._set(cx,cid,state='validating',job_id=job['job_id'])
            self._event(cx,cid,'independent_verification_started',{'job_id':job['job_id']})
            return self._public(self._row(cx,cid))

    def poll(self,cid):
        with self.flow.lock,self.flow._connect() as cx:r=self._row(cx,cid)
        if r['state']!='validating':return self._public(r)
        # Background jobs live only in the server process. Restart must never
        # manufacture a successful verdict from a stale job identifier.
        try:job=self.studio.job(r['job_id'])
        except Exception:job={'status':'lost','error':'VERIFICATION_JOB_LOST_ON_RESTART'}
        if job['status'] in ('queued','running'):return self.get(cid)
        passed=job['status']=='finished' and job.get('returncode')==0
        if not self._fresh(r):passed=False
        try:
            state=self.flow.sync(r['project_id'])
            passed=passed and state['status']=='decision_pending'
        except (FlowError,ValueError):passed=False
        next_state='human_decision' if passed else 'blocked'
        diag=None if passed else {'reason':'INDEPENDENT_VERIFICATION_FAILED',
                'job_status':job.get('status'),'error':job.get('error'),
                'returncode':job.get('returncode'),
                'checks':(job.get('result') or {}).get('checks',[])[:5]}
        with self.flow.lock,self.flow._connect() as cx:
            latest=self._row(cx,cid)
            if latest['state']!='validating':return self._public(latest)
            self._set(cx,cid,state=next_state,diagnostic=canonical(diag).decode() if diag else None)
            self._event(cx,cid,'independent_verification_finished',{'state':next_state,
                                                                  'job_status':job.get('status')})
            return self._public(self._row(cx,cid))

    def decide(self,cid,expected_sha,confirmation):
        if confirmation!='approve_test_only':raise FlowError('只允许人工确认测试级原型，不允许生产发布')
        with self.flow.lock,self.flow._connect() as cx:r=self._guard(cx,cid,{'human_decision'})
        accepted=self.flow.decide(r['project_id'],confirmation,expected_sha)
        if accepted['status']!='accepted_test_only':raise FlowConflict('测试级决策失败')
        with self.flow.lock,self.flow._connect() as cx:
            self._set(cx,cid,state='completed_test_only')
            self._event(cx,cid,'human_test_only_decision',{'candidate_sha256':expected_sha})
            return self._public(self._row(cx,cid))

    def repair_packet(self,cid):
        r=self.get(cid)
        if r['effective_state']!='blocked':raise FlowConflict('只有阻断的生产任务可以生成修复任务')
        # No automatic retries, edits to tests/specifications, weakening Gate,
        # or silent reconstruction of the previously approved campaign.
        pkt={'schema':'ax-factory-repair-task/0.5','failed_campaign':cid,
             'project_id':r['project_id'],'baseline':r['snapshot']['baseline'],
             'contract_digest':r['snapshot']['contract_digest'],
             'candidate_id':r['candidate_id'],'failure':r['diagnostic'],
             'required_next_action':'human creates evolution branch and re-freezes contract',
             'restrictions':['no change to specification without new approval','no edit tests',
                             'no edit evidence or Gate policy','no automatic approval'],
             'max_autonomous_retries':0}
        return {'packet':pkt,'digest':_sha(pkt)}

    def events(self,cid):
        with self.flow.lock,self.flow._connect() as cx:
            self._row(cx,cid)
            rows=cx.execute('SELECT * FROM factory_events WHERE campaign_id=? ORDER BY seq',(cid,)).fetchall()
        previous='0'*64;issues=[];events=[]
        for i,x in enumerate(rows):
            e=dict(x)
            try:payload=json.loads(e['payload'])
            except ValueError:issues.append('event payload corrupted');break
            obj={'campaign_id':cid,'kind':e['kind'],'payload':payload,'previous_hash':e['previous_hash'],'timestamp':e['timestamp']}
            if e['previous_hash']!=previous or digest(canonical(obj))!=e['entry_hash']:
                issues.append('broken chain at '+str(i))
            previous=e['entry_hash'];events.append({**e,'payload':payload})
        return {'events':events,'valid':not issues,'issues':issues,
                'limitation':'Local unkeyed hash chain, not an external tamper-proof log.'}
