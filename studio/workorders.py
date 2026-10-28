"""V0.9 review-gated AI production work orders.

Bounded proposal/rework cycles; generation never edits/executes a workspace file.
The independent verifier remains the existing Axiom CLI (no AI self-approval).
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import secrets
import threading
import time
from proposals import ProposalError, ConflictError, atomic, sha

class WorkOrderError(ProposalError):
    pass


def canonical(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')

class WorkOrders:
    def __init__(self, studio):
        self.studio=studio
        self.home=studio.proposals.home.parent/'workorders'
        self.home.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock()
        # Fail closed after a restart. No in-flight worker can be trusted as completed.
        for file in self.home.glob('wo-*.json'):
            try:
                r=json.loads(file.read_text('utf-8'))
                self._audit(r)
                if r['state']=='validating':
                    r['state']='interrupted'
                    self._event(r,'verification_interrupted_after_restart')
                    self._save(r)
            except (OSError, ValueError, KeyError, WorkOrderError):
                pass  # A corrupted record stays inaccessible; never auto-repaired.

    def _audit(self,r):
        chain='0'*64
        for i,e in enumerate(r['events']):
            if e['index']!=i or e['prev']!=chain or e['hash']!=sha(canonical({k:v for k,v in e.items() if k!='hash'})):
                raise WorkOrderError('工单事件链不一致，拒绝操作')
            chain=e['hash']
        if chain!=r['last_hash']:raise WorkOrderError('工单记录摘要不一致')

    def _event(self,r,kind,**fields):
        e={'index':len(r['events']), 'time':time.time(), 'kind':kind, 'prev':r.get('last_hash','0'*64), **fields}
        e['hash']=sha(canonical(e));r['events'].append(e);r['last_hash']=e['hash']

    def _save(self,r):
        atomic(self.home/(r['id']+'.json'),json.dumps(r,sort_keys=True,ensure_ascii=False,indent=2).encode())

    def _load(self,id):
        if not isinstance(id,str) or len(id)!=19 or not id.startswith('wo-') or any(c not in '0123456789abcdef' for c in id[3:]):
            raise WorkOrderError('工单编号非法')
        f=self.home/(id+'.json')
        if not f.is_file():raise WorkOrderError('工单不存在')
        r=json.loads(f.read_text('utf-8'));self._audit(r)
        return r

    def _baseline(self,r,expect_original=False):
        p=self.studio.proposals
        m,spec,target=p._manifest(r['manifest'],r['target'])
        for file,digest in r['baseline'].items():
            if (file==r['target'] and not expect_original and r['state'] in
                ('applied','validating','passed','blocked','interrupted') and r['active_proposal']):
                digest=r['attempts'][-1]['code_sha256']
            ref=p.file_guard(file)
            if sha(ref.read_bytes())!=digest:raise ConflictError('工单受保护输入已变化，必须重新创建工单: '+file)
        return target

    def _public(self,r,include_diagnostics=False):
        view={k:v for k,v in r.items() if k not in ('baseline',)}
        view['baseline_digest']=sha(canonical(r['baseline']))
        try:
            self._baseline(r)
            view['current']=True
        except (OSError,ProposalError,ValueError):view['current']=False
        if not include_diagnostics:
            view['diagnostic']=r.get('diagnostic',{}) and {
                'blocked':True,'reason':r['diagnostic'].get('reason',''),
                'steps':[{'step':x.get('step'),'returncode':x.get('returncode')} for x in r['diagnostic'].get('steps',[])]}
        return view

    def create(self,manifest,target,goal,max_attempts=3):
        if not isinstance(goal,str) or not (3<=len(goal.strip())<=700):raise WorkOrderError('目标描述须为3—700字')
        if not isinstance(max_attempts,int) or isinstance(max_attempts,bool) or not 1<=max_attempts<=3:raise WorkOrderError('最多尝试 1—3 次')
        with self.lock:
            p=self.studio.proposals
            m,spec,dest=p._manifest(manifest,target)
            plan=p._plan(spec)
            data=json.loads(m.read_text('utf-8'))
            refs={m,spec,dest}
            refs.update((m.parent/name).resolve() for name in data['files'])
            base={x.relative_to(p.workspace).as_posix():sha(x.read_bytes()) for x in refs}
            r={'id':'wo-'+secrets.token_hex(8),'manifest':manifest,'target':target,
               'goal':goal.strip(),'spec_digest':plan['spec_digest'],'baseline':base,
               'state':'ready','attempts':[],'active_proposal':None,'job_id':None,
               'max_attempts':max_attempts,'diagnostic':None,'created':time.time(),
               'events':[],'last_hash':'0'*64,'assurance':'review-gated prototype; no production approval'}
            self._event(r,'created',spec_digest=r['spec_digest']);self._save(r)
            return self._public(r)

    def get(self,id):
        with self.lock:return self._public(self._load(id),True)

    def list(self):
        with self.lock:
            result=[]
            for f in self.home.glob('wo-*.json'):
                try:result.append(self._public(self._load(f.stem)))
                except (OSError,ValueError,KeyError,WorkOrderError):continue
            return sorted(result,key=lambda a:a['created'],reverse=True)[:60]

    def _ready(self,r):
        if r['state'] not in ('ready','reverted'):raise WorkOrderError('此阶段不能提交新候选')
        if len(r['attempts'])>=r['max_attempts']:raise WorkOrderError('已达到最大尝试次数，须人工重新规划')
        self._baseline(r)

    def submit(self,id,code):
        with self.lock:
            r=self._load(id);self._ready(r)
            prop=self.studio.proposals.create(r['manifest'],r['target'],code)
            self._new_attempt(r,prop)
            return self._public(r)

    def generate(self,id,consent):
        if consent is not True:raise WorkOrderError('发送规格及源码给外部模型必须明确同意')
        with self.lock:
            r=self._load(id);self._ready(r)
            # Diagnostics are provided as bounded *data*, never as instructions to change tests or policy.
            diagnostic=r.get('diagnostic') or {}
            feedback=''
            if diagnostic:
                feedback=('Prior attempt failed independently. Use these diagnostics only to repair the '
                          'same implementation target. Keep specification/tests/gate untouched.\n'
                          +json.dumps(diagnostic,ensure_ascii=False)[:6000])
            prop=self.studio.proposals.generate(r['manifest'],r['target'],consent,feedback=feedback,goal=r['goal'])
            self._new_attempt(r,prop)
            return self._public(r)

    def _new_attempt(self,r,prop):
        r['active_proposal']=prop['id'];r['state']='proposed';r['job_id']=None
        r['attempts'].append({'number':len(r['attempts'])+1,'proposal_id':prop['id'],
                              'code_sha256':prop['code_sha256'],'source':prop['source'],'status':'proposed'})
        self._event(r,'candidate_staged',proposal_id=prop['id'],digest=prop['code_sha256'])
        self._save(r)

    def review(self,id,digest,approved):
        with self.lock:
            r=self._load(id)
            if r['state']!='proposed':raise WorkOrderError('仅可审查待审候选')
            self._baseline(r)
            p=self.studio.proposals.review(r['active_proposal'],digest,approved)
            r['state']='reviewed';r['attempts'][-1]['status']='reviewed'
            self._event(r,'human_review',digest=p['code_sha256']);self._save(r)
            return self._public(r)

    def apply(self,id,confirmation):
        if confirmation!='human_authorized_apply':raise WorkOrderError('应用候选必须由人工明确批准')
        with self.lock:
            r=self._load(id)
            if r['state']!='reviewed':raise WorkOrderError('候选尚未审查')
            self._baseline(r)
            self.studio.proposals.apply(r['active_proposal'])
            r['state']='applied';r['attempts'][-1]['status']='applied'
            self._event(r,'human_applied',proposal_id=r['active_proposal']);self._save(r)
            return self._public(r)

    def verify(self,id,trusted):
        if trusted is not True:raise WorkOrderError('真实 C++ 执行需要单独人工授权')
        with self.lock:
            r=self._load(id)
            if r['state']!='applied':raise WorkOrderError('需要已应用且未验证的候选')
            self.studio.proposals.check_validation(r['active_proposal'])
            job=self.studio.start_proposal_job(r['active_proposal'],trusted=True)
            r['job_id']=job['job_id'];r['state']='validating'
            self._event(r,'independent_verification_started',job_id=job['job_id'])
            self._save(r)
            return self._public(r)

    def poll(self,id):
        with self.lock:
            r=self._load(id)
            if r['state']!='validating':return self._public(r)
            try:job=self.studio.job(r['job_id'])
            except Exception:
                # e.g. process restarted; the result no longer exists, never approve.
                r['state']='interrupted';self._event(r,'verification_lost');self._save(r)
                return self._public(r)
            if job['status'] in ('queued','running'):return self._public(r)
            success=(job['status']=='finished' and job['returncode']==0 and
                     isinstance(job['result'],dict) and job['result'].get('decision')=='Approved')
            # Confirm the same proposal is current and independently recorded as verified.
            p=self.studio.proposals.get(r['active_proposal'])
            success=success and p['status']=='verified' and p['current']
            r['state']='passed' if success else 'blocked'
            r['attempts'][-1]['status']=r['state']
            steps=(job.get('result') or {}).get('checks',[]) if isinstance(job.get('result'),dict) else []
            r['diagnostic']=None if success else {'reason':'独立验证未通过，或证据/源码与候选不匹配',
                'steps':[{'step':x.get('step'),'returncode':x.get('returncode'),
                          'outcome':x.get('outcome'),'detail':str(x.get('result',''))[:800]}
                         for x in steps[:4]]}
            self._event(r,'independent_passed' if success else 'independent_blocked',job_id=r['job_id'],
                        code_sha256=p['code_sha256'])
            self._save(r)
            return self._public(r)

    def revert(self,id,confirmation):
        if confirmation!='human_reject_and_revert':raise WorkOrderError('需要明确人工回退授权')
        with self.lock:
            r=self._load(id)
            if r['state'] not in ('blocked','interrupted'):
                raise WorkOrderError('只有验证失败或中断后才允许回退')
            p=self.studio.proposals
            proposal=p._load(r['active_proposal']);target,_=p._current(proposal)
            if sha(target.read_bytes())!=proposal['code_sha256']:
                raise ConflictError('源码已被外部修改；拒绝覆盖，需人工处理')
            backup=proposal.get('backup_sha256')
            if not backup:raise WorkOrderError('未找到可验证的原始备份')
            raw=(p.home/'objects'/backup).read_bytes()
            if sha(raw)!=backup:raise WorkOrderError('原始备份校验失败')
            atomic(target,raw)
            self._baseline(r,expect_original=True)
            r['state']='reverted';r['active_proposal']=None;r['job_id']=None
            self._event(r,'human_reverted',restored_sha256=backup)
            self._save(r)
            return self._public(r)

    def feedback(self,id):
        with self.lock:
            r=self._load(id)
            if r['state'] not in ('blocked','reverted','interrupted'):
                raise WorkOrderError('尚无失败诊断')
            return {'id':id,'spec_digest':r['spec_digest'],'target':r['target'],
                'attempts_used':len(r['attempts']),'attempts_remaining':r['max_attempts']-len(r['attempts']),
                'diagnostic':r.get('diagnostic'),
                'constraints':['不得更改 Axiom 规格','不得更改独立测试或 Gate','只修复绑定的 C++ 实现文件',
                               '新候选必须人工审查，并再次进行独立验证']}
