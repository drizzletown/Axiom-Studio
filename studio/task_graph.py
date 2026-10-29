"""Axiom Studio 1.7: contract-bound multi-module production task graph.

This is a *serial, review-gated* production scheduler. It composes authoritative
Assembly/WorkOrder flows; it never grants permission to run generated code,
change protected specifications/tests, or accept a production release.
"""
from __future__ import annotations

import json
import secrets
import threading
import time
from pathlib import Path
from proposals import atomic, sha, ProposalError
from workorders import canonical, WorkOrderError
from orchestrator import FlowConflict
from assembly import AssemblyError


class TaskGraphError(WorkOrderError):
    pass


class TaskGraphs:
    def __init__(self, studio):
        self.studio = studio
        self.home = studio.proposals.home.parent / 'task-graphs'
        self.home.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    @staticmethod
    def _hash(obj):
        return sha(canonical(obj))

    def _event(self, record, kind, **details):
        event = {'seq': len(record['events']), 'at': time.time(), 'kind': kind,
                 'prev': record['head'], 'details': details,
                 'nodes_digest': self._hash(record['nodes'])}
        event['hash'] = self._hash(event)
        record['events'].append(event)
        record['head'] = event['hash']

    def _audit(self, record):
        head = '0' * 64
        for idx, event in enumerate(record['events']):
            if event.get('seq') != idx or event.get('prev') != head or \
               event.get('hash') != self._hash({k:v for k,v in event.items() if k != 'hash'}):
                raise TaskGraphError('生产任务审计链已损坏')
            head = event['hash']
        if not record['events'] or head != record['head']:
            raise TaskGraphError('生产任务审计摘要不匹配')
        if record['events'][0]['kind'] != 'created' or \
           record['events'][0]['details'].get('plan_digest') != self._hash(record['plan']):
            raise TaskGraphError('生产计划与创建事件不一致')
        if record['events'][-1]['nodes_digest'] != self._hash(record['nodes']):
            raise TaskGraphError('任务状态与审计事件不一致')
        plan_targets = {x['target'] for x in record['plan']['tasks']}
        if set(record['nodes']) != plan_targets:
            raise TaskGraphError('任务列表被修改')
        for x in record['plan']['tasks']:
            n = record['nodes'][x['target']]
            if n['depends_on'] != x['depends_on'] or n['target'] != x['target']:
                raise TaskGraphError('任务依赖关系被修改')

    def _load(self, graph_id):
        if not isinstance(graph_id, str) or len(graph_id) != 19 or \
           not graph_id.startswith('tg-') or any(c not in '0123456789abcdef' for c in graph_id[3:]):
            raise TaskGraphError('非法任务图编号')
        f = self.home / (graph_id + '.json')
        if not f.is_file():
            raise TaskGraphError('任务图不存在')
        r = json.loads(f.read_text(encoding='utf-8'))
        self._audit(r)
        return r

    def _save(self, record):
        self._audit(record)
        atomic(self.home / (record['id'] + '.json'),
               json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2).encode())

    def _inputs(self, pid):
        project, production = self.studio.assembly._contract_ready(pid)
        manifest = project['manifest']
        info = self.studio.assembly.targets(pid)
        targets = info['targets']
        if not targets:
            raise TaskGraphError('项目还没有允许构造的 C++ 模块')
        data = json.loads(self.studio.proposals.file_guard(manifest).read_text('utf-8'))
        base = Path(manifest).parent
        inputs = {}
        files = [manifest, project['spec']]
        files.extend((base / f).as_posix() for f in data['files'])
        for f in set(files):
            inputs[f] = sha(self.studio.proposals.file_guard(f).read_bytes())
        return project, production, sorted(set(targets)), inputs

    def create(self, project_id, tasks=None):
        """Create immutable, acyclic task DAG. Defaults to a serial sequence.

        Tasks are [{target, depends_on:[target,...]}]; all candidates remain
        manual-review gated, and native tests require a separate trust grant.
        """
        with self.lock:
            project, prod, eligible, inputs = self._inputs(project_id)
            if tasks is None:
                tasks = [{'target':t, 'depends_on':eligible[i-1:i]} for i,t in enumerate(eligible)]
            if not isinstance(tasks, list) or not 1 <= len(tasks) <= 12:
                raise TaskGraphError('请指定 1—12 个构造任务')
            known = set(eligible)
            selected = set()
            normalized = []
            for task in tasks:
                if not isinstance(task, dict) or set(task) != {'target', 'depends_on'}:
                    raise TaskGraphError('任务必须包含模块和前置依赖')
                target = task['target']; deps = task['depends_on']
                if target not in known or target in selected:
                    raise TaskGraphError('模块不在受保护项目允许的实现列表内，或重复使用')
                if not isinstance(deps, list) or len(deps) != len(set(deps)) or \
                   target in deps or not all(isinstance(d,str) for d in deps):
                    raise TaskGraphError('模块依赖关系非法')
                selected.add(target)
                normalized.append({'target':target, 'depends_on':list(deps)})
            for node in normalized:
                if not set(node['depends_on']).issubset(selected):
                    raise TaskGraphError('前置依赖必须属于同一生产计划')
            # Kahn: reject cyclic graph, preserving the user's explicit order.
            pending = {n['target']:set(n['depends_on']) for n in normalized}
            while pending:
                ready = [t for t,deps in pending.items() if not deps]
                if not ready: raise TaskGraphError('任务依赖包含环，无法启动')
                for target in ready: pending.pop(target)
                for deps in pending.values(): deps.difference_update(ready)
            plan = {'schema':'ax-production-dag/1.7', 'project_id':project_id,
                    'revision':project['revision'], 'baseline':project['baseline'],
                    'contract_digest':prod['contract_digest'], 'manifest':project['manifest'],
                    'tasks':normalized,'inputs':inputs}
            for f in self.home.glob('tg-*.json'):
                try:
                    existing = self._load(f.stem)
                    if existing['plan'] == plan:
                        return self._view(existing)
                except (ValueError,KeyError,OSError,TaskGraphError):
                    continue
            nodes = {n['target']:{'target':n['target'],'depends_on':n['depends_on'],
                                  'state':'pending','assembly_id':None,
                                  'accepted_sha256':None,'proposal_id':None}
                     for n in normalized}
            r = {'id':'tg-'+secrets.token_hex(8),'plan':plan,'nodes':nodes,
                 'created':time.time(),'events':[], 'head':'0'*64}
            self._event(r,'created',plan_digest=self._hash(plan))
            self._save(r)
            return self._view(r)

    def _current(self, record):
        plan = record['plan'];pid=plan['project_id']
        try:
            p=self.studio.flow.get(pid)
            prod=self.studio.production.overview(pid)
            if p['stale'] or p['revision']!=plan['revision'] or p['baseline']!=plan['baseline'] or \
               prod.get('contract_digest') != plan['contract_digest'] or \
               not self.studio.flow.audit(pid)['chain_valid']:
                return False, '规格、契约或审计链已变化'
            for path,original_digest in plan['inputs'].items():
                n=record['nodes'].get(path)
                expected=original_digest
                if n and n['state']=='passed':
                    expected=n['accepted_sha256']
                elif n and n['state']=='active':
                    assembly=self.studio.assembly.get(n['assembly_id'])
                    if not assembly['current']:
                        return False, '活动候选或证据失效：'+path
                    if assembly['state'] in ('applied','validating','passed','blocked','interrupted'):
                        expected=assembly.get('candidate_digest')
                if not expected or sha(self.studio.proposals.file_guard(path).read_bytes()) != expected:
                    return False, '工程文件被外部修改：'+path
            return True, ''
        except (OSError,KeyError,ValueError,TaskGraphError,FlowConflict,AssemblyError,ProposalError,WorkOrderError) as exc:
            return False, '生产输入无法确认：'+str(exc)[:160]

    def _view(self,record):
        self._audit(record)
        current,reason=self._current(record)
        nodes=[];active=[]
        for task in record['plan']['tasks']:
            n=record['nodes'][task['target']]
            blocked=[dep for dep in task['depends_on'] if record['nodes'][dep]['state']!='passed']
            status=n['state']
            if status=='pending':
                status='waiting' if blocked else 'ready'
            elif status=='active':active.append(n['target'])
            nodes.append({**n,'display_state':status,'waiting_for':blocked,
                          'can_start':bool(current and status=='ready' and not active)})
        # Re-evaluate after collecting active nodes (including later positions).
        active_count=sum(n['state']=='active' for n in record['nodes'].values())
        for n in nodes:
            n['can_start']=bool(current and n['display_state']=='ready' and active_count==0)
        completed=sum(n['state']=='passed' for n in nodes)
        action='已完成全部模块的限定验证，需返回项目 Gate 作人工裁决' if completed==len(nodes) else \
               ('处理当前模块的候选审查及验证' if active_count else '启动下一个已就绪模块')
        if not current: action='生产输入已变化，暂停并建立演化版本'
        return {'schema':'ax-production-dag-view/1.7','id':record['id'],
                'project_id':record['plan']['project_id'], 'current':current,'blocker':reason,
                'tasks':nodes,'complete':completed==len(nodes), 'completed':completed,
                'total':len(nodes),'active_count':active_count,'next':action,
                'head':record['head'],'audit_valid':True,
                'assurance':'independent local C++ tests only; no production release',
                'production_release_authorized':False}

    def get(self,graph_id):
        with self.lock:return self._view(self._load(graph_id))

    def list(self,project_id=None):
        with self.lock:
            result=[]
            for f in self.home.glob('tg-*.json'):
                try:
                    r=self._load(f.stem)
                    if project_id and r['plan']['project_id']!=project_id:continue
                    result.append(self._view(r))
                except (OSError,ValueError,KeyError,TaskGraphError):continue
            return {'graphs':sorted(result,key=lambda g:g['id'],reverse=True)[:60]}

    def start(self,graph_id,target):
        with self.lock:
            r=self._load(graph_id)
            view=self._view(r)
            if not view['current']:raise FlowConflict(view['blocker'])
            match=[n for n in view['tasks'] if n['target']==target]
            if not match or not match[0]['can_start']:
                raise TaskGraphError('模块尚未就绪，存在未通过的前置模块或正在执行的任务')
            session=self.studio.assembly.create(r['plan']['project_id'],target)
            r['nodes'][target]['state']='active'
            r['nodes'][target]['assembly_id']=session['id']
            self._event(r,'module_started',target=target,assembly_id=session['id'])
            self._save(r)
            return self._view(r)

    def sync(self,graph_id):
        with self.lock:
            r=self._load(graph_id)
            view=self._view(r)
            if not view['current']:raise FlowConflict(view['blocker'])
            for target,node in r['nodes'].items():
                if node['state']!='active':continue
                session=self.studio.assembly.poll(node['assembly_id'])
                if not session['current']:raise FlowConflict('正在构造的模块证据失效')
                if session['state']=='passed':
                    proposal=self.studio.proposals.get(session['candidate_id'])
                    if proposal['status']!='verified' or not proposal['current'] or \
                       proposal['code_sha256']!=session['candidate_digest']:
                        raise TaskGraphError('候选证据未完成真实验证，拒绝标记模块完成')
                    node['state']='passed'
                    node['accepted_sha256']=session['candidate_digest']
                    node['proposal_id']=session['candidate_id']
                    self._event(r,'module_tested',target=target,
                                sha256=node['accepted_sha256'],proposal_id=node['proposal_id'])
                    self._save(r)
                elif session['state'] in ('blocked','interrupted'):
                    # Keep the node active, but expose repair in underlying Assembly.
                    pass
            return self._view(r)

    def handoff(self,graph_id):
        with self.lock:
            r=self._load(graph_id)
            view=self._view(r)
            packet={'schema':'ax-task-graph-handoff/1.7','plan':r['plan'],
                    'status':view,'events':r['events'],
                    'notice':'Local hash chain is not a digital signature. ' 
                             'Test-level evidence, not production authorization.'}
            return {'filename':graph_id+'-handoff.json','report':packet,
                    'sha256':self._hash(packet)}
