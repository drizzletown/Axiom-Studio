"""Axiom Studio 1.6: project-bound AI construction lane.

A single resumable, audit-checked user journey over existing authoritative
WorkOrders, Proposals, Production and Orchestrator. No AI may self-approve,
change a protected file, run native code, or claim production release.
"""
from __future__ import annotations
import json, secrets, threading, time
from pathlib import Path
from proposals import atomic, sha, ProposalError
from workorders import canonical, WorkOrderError
from orchestrator import FlowConflict

class AssemblyError(WorkOrderError): pass

class Assembly:
    def __init__(self,studio):
        self.studio=studio
        self.home=studio.proposals.home.parent/'assembly'
        self.home.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock()

    def _event(self,r,kind,**data):
        e={'index':len(r['events']),'time':time.time(),'kind':kind,
           'prev':r.get('head','0'*64),'data':data}
        e['hash']=sha(canonical(e));r['events'].append(e);r['head']=e['hash']

    def _audit(self,r):
        head='0'*64
        for i,e in enumerate(r['events']):
            if (e.get('index')!=i or e.get('prev')!=head or
                e.get('hash')!=sha(canonical({k:v for k,v in e.items() if k!='hash'}))):
                raise AssemblyError('构造轨迹校验失败；拒绝使用该记录')
            head=e['hash']
        if head!=r['head'] or not r['events']:raise AssemblyError('构造轨迹摘要无效')
        first=r['events'][0]
        fields={'project':r['project_id'],'contract':r['contract_digest'],
                'workorder':r['workorder_id'],'target':r['target'],
                'manifest':r['manifest'],'revision':r['revision'],
                'baseline_sha256':sha(canonical(r['baseline']))}
        if first['kind']!='created' or first['data']!=fields:
            raise AssemblyError('构造轨迹对象字段与签入的事件内容不一致')

    def _load(self,id):
        if not isinstance(id,str) or len(id)!=19 or not id.startswith('as-') or any(c not in '0123456789abcdef' for c in id[3:]):
            raise AssemblyError('构造轨迹编号非法')
        f=self.home/(id+'.json')
        if not f.is_file():raise AssemblyError('构造轨迹不存在')
        r=json.loads(f.read_text('utf-8'));self._audit(r);return r

    def _save(self,r):
        atomic(self.home/(r['id']+'.json'),json.dumps(r,ensure_ascii=False,sort_keys=True,indent=2).encode())

    def _contract_ready(self,pid):
        project=self.studio.flow.get(pid)
        prod=self.studio.production.overview(pid)
        contract=prod.get('contract')
        if project['stale'] or not contract:raise FlowConflict('先完成规格验证，并由用户确认冻结验收契约')
        if not project['last_verification'] or not project['last_verification'].get('passed'):
            raise FlowConflict('当前版本尚未通过独立模型检查')
        blockers=prod.get('blockers',[])
        forbidden=[x for x in blockers if x!='HUMAN_ACCEPTANCE_AND_CPP_GATE_REQUIRED']
        if forbidden:raise FlowConflict('有未解决的验收缺口，不允许开始构造：'+', '.join(forbidden[:5]))
        if not project['manifest']:raise AssemblyError('当前项目尚无 C++ 工程清单，先配置实现项目')
        if not self.studio.flow.audit(pid)['chain_valid']:raise AssemblyError('工程事件审计链无效')
        return project,prod

    def targets(self,project_id):
        p=self.studio.flow.get(project_id)
        if not p.get('manifest'):return {'targets':[], 'message':'当前项目只有抽象模型，还没有 C++ 工程'}
        manifest=p['manifest']
        m=self.studio.proposals.file_guard(manifest)
        data=json.loads(m.read_text('utf-8'))
        items=[]
        for file in data.get('files',[]):
            if not isinstance(file,str):continue
            target=(m.parent/file).relative_to(self.studio.proposals.workspace).as_posix() if \
                (m.parent/file).resolve().is_relative_to(self.studio.proposals.workspace.resolve()) else ''
            if target and self._allowed_target(manifest,target):items.append(target)
        return {'targets':items,'project_id':project_id}

    def create(self,project_id,target=None):
        with self.lock:
            p,prod=self._contract_ready(project_id)
            manifest=p['manifest']
            data=json.loads(self.studio.proposals.file_guard(manifest).read_text('utf8'))
            folder=str(Path(manifest).parent)
            if target is None:
                candidates=[(Path(folder)/f).as_posix() for f in data.get('files',[]) if
                            (f.endswith('.cpp') or f.endswith('.cc')) and
                            not Path(f).name.startswith('test_') and not Path(f).name.endswith('_test.cpp')]
                candidates=[c for c in candidates if self._allowed_target(manifest,c)]
                if len(candidates)!=1:raise AssemblyError('包含多个实现目标，请选择要构造的 C++ 文件：'+', '.join(candidates))
                target=candidates[0]
            self.studio.proposals._manifest(manifest,target)
            for f in self.home.glob('as-*.json'):
                try:
                    existing=self._load(f.stem)
                    if existing['project_id']==project_id and existing['target']==target and \
                       existing['baseline']==p['baseline'] and existing['contract_digest']==prod['contract_digest']:
                        return self._view(existing)
                except (AssemblyError,ValueError,OSError,KeyError):continue
            work=self.studio.workorders.create(manifest,target,p['goal'],max_attempts=3)
            r={'id':'as-'+secrets.token_hex(8),'project_id':project_id,'target':target,
               'manifest':manifest,'workorder_id':work['id'],'revision':p['revision'],
               'baseline':p['baseline'],'contract_digest':prod['contract_digest'],
               'created':time.time(),'events':[],'head':'0'*64}
            self._event(r,'created',project=project_id,contract=prod['contract_digest'],
                        workorder=work['id'],target=target,manifest=manifest,
                        revision=p['revision'],baseline_sha256=sha(canonical(p['baseline'])))
            self._save(r)
            return self._view(r)

    def _allowed_target(self,manifest,target):
        try:self.studio.proposals._manifest(manifest,target);return True
        except (ProposalError,OSError,ValueError):return False

    def _view(self,r):
        self._audit(r)
        p=self.studio.flow.get(r['project_id'])
        work=self.studio.workorders.get(r['workorder_id'])
        if work['manifest']!=r['manifest'] or work['target']!=r['target']:
            raise AssemblyError('构造轨迹和实现工单的目标不一致')
        prod=self.studio.production.overview(r['project_id'])
        current=bool(not p['stale'] and p['revision']==r['revision'] and
                     p['baseline']==r['baseline'] and prod.get('contract_digest')==r['contract_digest'] and
                     self.studio.flow.audit(p['id'])['chain_valid'] and work['current'] and
                     not [b for b in prod.get('blockers',[]) if b!='HUMAN_ACCEPTANCE_AND_CPP_GATE_REQUIRED'])
        steps={
            'ready':('propose','让 AI 生成候选，或导入 VS Code 的结果','AI / 用户'),
            'reverted':('propose','依据失败反馈修订候选','AI / 用户'),
            'proposed':('review','对照原实现审查候选，再确认摘要','用户'),
            'reviewed':('apply','批准将候选应用于工作区','用户'),
            'applied':('verify','授权独立编译、测试和 Gate','用户'),
            'validating':('poll','正在执行独立验证，查看结果','系统'),
            'blocked':('repair','查看诊断，人工回退后重新构造','用户'),
            'interrupted':('repair','验证中断，人工处理再重试','用户'),
            'passed':('complete','本次候选通过限定 C++ 测试；后续由项目 Gate 裁决','用户')}
        action,label,owner=steps.get(work['state'],('inspect','检查工单状态','用户'))
        if not current:action,label,owner='blocked','输入或证据已经变化，须检查并建立演化版本','用户'
        response={'schema':'ax-assembly/1.6','id':r['id'],'project_id':r['project_id'],
                  'project_name':p['name'],'goal':p['goal'],'revision':r['revision'],
                  'contract_digest':r['contract_digest'],'target':r['target'],
                  'workorder_id':r['workorder_id'],'state':work['state'],'current':current,
                  'action':{'id':action,'label':label,'owner':owner},
                  'attempts_used':len(work['attempts']),'attempts_limit':work['max_attempts'],
                  'candidate_id':work['active_proposal'],
                  'candidate_digest':work['attempts'][-1]['code_sha256'] if work['attempts'] else None,
                  'diagnostic':work.get('diagnostic'), 'audit_valid':True,'head':r['head'],
                  'production_release_authorized':False,
                  'assurance':'bounded model evidence and trusted-local C++ tests; not production release'}
        return response

    def get(self,id):
        with self.lock:return self._view(self._load(id))

    def list(self,project_id=None):
        with self.lock:
            out=[]
            for file in self.home.glob('as-*.json'):
                try:
                    r=self._load(file.stem)
                    if project_id and r['project_id']!=project_id:continue
                    out.append(self._view(r))
                except (OSError,ValueError,KeyError,AssemblyError,FlowConflict):continue
            return {'sessions':sorted(out,key=lambda x:x['id'],reverse=True)[:100]}

    def _active(self,id,expected_action):
        r=self._load(id);v=self._view(r)
        if not v['current']:raise FlowConflict('输入发生变化或证据失效，不能沿用旧构造轨迹')
        if v['action']['id']!=expected_action:raise AssemblyError('此阶段不允许该操作，当前需要：'+v['action']['label'])
        return r

    def candidate(self,id,code=None,consent=False):
        with self.lock:
            r=self._active(id,'propose')
            if code is None:
                w=self.studio.workorders.generate(r['workorder_id'],consent)
                kind='ai_candidate_generated'
            else:
                w=self.studio.workorders.submit(r['workorder_id'],code)
                kind='external_candidate_staged'
            self._event(r,kind,proposal=w['active_proposal'],digest=w['attempts'][-1]['code_sha256'])
            self._save(r);return self._view(r)

    def review(self,id,digest,approved):
        with self.lock:
            r=self._active(id,'review')
            w=self.studio.workorders.review(r['workorder_id'],digest,approved)
            self._event(r,'human_reviewed',digest=digest)
            self._save(r);return self._view(r)

    def apply(self,id,confirmation):
        with self.lock:
            r=self._active(id,'apply')
            self.studio.workorders.apply(r['workorder_id'],confirmation)
            self._event(r,'human_applied',confirmation='human_authorized')
            self._save(r);return self._view(r)

    def verify(self,id,trusted):
        with self.lock:
            r=self._active(id,'verify')
            self.studio.workorders.verify(r['workorder_id'],trusted)
            self._event(r,'trusted_local_validation_started')
            self._save(r);return self._view(r)

    def poll(self,id):
        with self.lock:
            r=self._load(id)
            if self._view(r)['state']=='validating':
                w=self.studio.workorders.poll(r['workorder_id'])
                if w['state']!='validating':
                    self._event(r,'independent_validation_finished',outcome=w['state'],
                                candidate=w.get('active_proposal'))
                    self._save(r)
            return self._view(r)

    def revert(self,id,confirmation):
        with self.lock:
            r=self._active(id,'repair')
            self.studio.workorders.revert(r['workorder_id'],confirmation)
            self._event(r,'human_reverted_for_repair')
            self._save(r);return self._view(r)

    def handoff(self,id):
        with self.lock:
            r=self._load(id);view=self._view(r)
            wo=self.studio.workorders.get(r['workorder_id'])
            report={'schema':'ax-assembly-handoff/1.6','session':view,
                    'attempts':wo['attempts'],'events':r['events'],
                    'diagnostic':wo['diagnostic'],
                    'limits':'Unsigned local report. Review actual Axiom evidence and run live Gates.'}
            return {'filename':id+'-construction.json','report':report,'sha256':sha(canonical(report))}
