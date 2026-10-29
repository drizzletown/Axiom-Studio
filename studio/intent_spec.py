"""Axiom Studio 1.2: human-owned acceptance scenarios to pinned Axiom properties.

A property *link* is traceability only. It cannot be treated as semantic
implication or verification, even if a bounded model check has passed.
AI receives design task packets; it cannot revise a frozen contract.
"""
from __future__ import annotations
import json
import time
from orchestrator import FlowError, FlowConflict, canonical, digest

SCHEMA = 'ax-intent-scenarios/1.2'
MAX_ITEMS = 40


def _digest(v):
    return 'sha256:'+digest(canonical(v))


def _field(value, label, minimum=2, maximum=500):
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise FlowError(f'{label}长度必须在 {minimum}–{maximum} 字符之间')
    return value.strip()


class IntentSpec:
    def __init__(self, studio):
        self.studio = studio
        self.flow = studio.flow
        self.production = studio.production
        with self.flow.lock, self.flow._connect() as cx:
            cx.executescript('''
                CREATE TABLE IF NOT EXISTS intent_scenario_plans(
                    project_id TEXT PRIMARY KEY, version INTEGER NOT NULL,
                    body TEXT NOT NULL, digest TEXT NOT NULL, updated REAL NOT NULL
                );
            ''')

    def _current(self, cx, pid):
        row = cx.execute('SELECT * FROM intent_scenario_plans WHERE project_id=?', (pid,)).fetchone()
        if not row:
            return None
        body = json.loads(row['body'])
        if _digest(body) != row['digest']:
            raise FlowConflict('验收场景记录摘要不一致；拒绝继续使用可疑草稿')
        if body.get('schema') != SCHEMA or body.get('project_id') != pid or body.get('version') != row['version']:
            raise FlowConflict('验收场景记录结构不一致；拒绝继续')
        return body

    def _properties(self, pid):
        draft = self.production.draft(pid)
        return draft, {x['property'] for x in draft['suggested']}

    def _default(self, pid, baseline):
        raw, _ = self._properties(pid)
        items = []
        for i, r in enumerate(raw['suggested']):
            name = r['property']
            items.append({'id': 'REQ-'+str(i+1).zfill(3),
                          'title': '确认模型性质 '+name,
                          'given': '系统处于规格允许的状态',
                          'when': '执行模型定义的状态转换',
                          'then': '需要检查性质 '+name+' 是否始终满足',
                          'property': name})
        return {'schema':SCHEMA, 'project_id':pid, 'version':0,
                'baseline':baseline, 'items':items, 'origin':'template_suggestion'}

    def _normalize(self, items, props):
        if not isinstance(items, list) or not 1 <= len(items) <= MAX_ITEMS:
            raise FlowError(f'请提供 1–{MAX_ITEMS} 个验收场景')
        out = []; seen = set()
        for i, row in enumerate(items):
            if not isinstance(row,dict):raise FlowError('验收场景必须是对象')
            rid = row.get('id') or 'REQ-'+str(i+1).zfill(3)
            if not isinstance(rid,str) or not rid.startswith('REQ-') or len(rid)>55 or not rid[4:].replace('-','').replace('_','').isalnum() or rid in seen:
                raise FlowError('需求标识无效或重复')
            seen.add(rid)
            value = {'id':rid,
                     'title':_field(row.get('title'),'场景名称',4,120),
                     'given':_field(row.get('given'),'前提条件',3,300),
                     'when':_field(row.get('when'),'触发事件',3,300),
                     'then':_field(row.get('then'),'预期结果',4,500)}
            prop = row.get('property') or None
            if prop is not None and (not isinstance(prop,str) or prop not in props):
                raise FlowError(f'验收场景 {rid} 关联了不存在的规格性质')
            value['property']=prop
            out.append(value)
        return out

    def _output(self,body,p):
        linked = sum(bool(x['property']) for x in body['items'])
        status = self.production.overview(p['id'])
        return {'schema':SCHEMA,'project_id':p['id'], 'goal':p['goal'],
                'version':body['version'], 'digest':_digest(body), 'baseline':body['baseline'],
                'items':body['items'], 'properties':[x['property'] for x in self.production.draft(p['id'])['suggested']],
                'saved':bool(body['version']), 'stale':bool(p['stale']),
                'frozen':bool(status.get('contract')), 'linked_count':linked,
                'gap_count':len(body['items'])-linked,
                'link_notice':'关联仅代表人工定义的追溯关系，不证明文字需求已被形式性质完整表达。',
                'gap_notice':'未关联规格性质的验收场景将阻断最终测试级准入。',
                'verified_scope':'仅当前 Axiom 模型的有限检查；不是完整业务目标证明。'}

    def get(self,pid):
        p=self.flow.get(pid)
        with self.flow.lock,self.flow._connect() as cx:
            saved=self._current(cx,pid)
        body=saved or self._default(pid,p['baseline'])
        if body['baseline']!=p['baseline'] or p['stale']:
            result=self._output(body,p);result['stale']=True;return result
        return self._output(body,p)

    def save(self,pid,items,version,baseline):
        if type(version) is not int or version<0:raise FlowError('验收草稿版本无效')
        with self.flow.lock:
            p=self.flow.get(pid)
            if p['stale'] or p['baseline']!=baseline:
                raise FlowConflict('规格已变化；先建立演化分支，不能沿用旧验收场景')
            status=self.production.overview(pid)
            if status.get('contract'):raise FlowConflict('验收契约已经冻结，必须建立新的演化项目')
            _,props=self._properties(pid)
            clean=self._normalize(items,props)
            with self.flow._connect() as cx:
                old=self._current(cx,pid)
                if (old['version'] if old else 0)!=version:
                    raise FlowConflict('另一个窗口更新了验收场景，请刷新后重试')
                body={'schema':SCHEMA,'project_id':pid,'version':version+1,
                      'baseline':p['baseline'],'items':clean,'origin':'human_edited'}
                cx.execute('INSERT INTO intent_scenario_plans VALUES(?,?,?,?,?) '
                           'ON CONFLICT(project_id) DO UPDATE SET version=excluded.version,body=excluded.body,digest=excluded.digest,updated=excluded.updated',
                           (pid,version+1,canonical(body).decode('utf-8'),_digest(body),time.time()))
                self.flow._event(cx,pid,'intent_scenarios_saved',
                    {'version':version+1,'digest':_digest(body),
                     'linked':sum(bool(x['property']) for x in clean),'total':len(clean)})
            return self.get(pid)

    def confirm(self,pid,version,draft_digest,confirmation):
        if confirmation!='CONFIRM_HUMAN_ACCEPTANCE':raise FlowError('必须明确人工确认验收场景')
        with self.flow.lock:
            p=self.flow.get(pid)
            if p['stale']:raise FlowConflict('规格已变化；不能冻结旧验收场景')
            if p['effective_status']!='spec_ready' or not (p.get('last_verification') or {}).get('passed'):
                raise FlowConflict('请先通过当前规格的独立模型验证')
            if not self.flow.audit(pid)['chain_valid']:
                raise FlowConflict('工作流审计链异常，不能冻结需求')
            with self.flow._connect() as cx:
                body=self._current(cx,pid)
                if not body or body['version']!=version or _digest(body)!=draft_digest:
                    raise FlowConflict('验收草稿已变化，请重新审核')
            if body['baseline']!=p['baseline']:
                raise FlowConflict('验收草稿已失效')
            requirements=[]
            for item in body['items']:
                statement=(item['title']+'；前提：'+item['given']+'；当：'+item['when']+'；应当：'+item['then'])
                requirements.append({'id':item['id'],'text':statement,
                                     'kind':'invariant' if item['property'] else 'unverified',
                                     'property':item['property']})
            result=self.production.freeze(pid,requirements,p['baseline'],draft_digest)
            return {'schema':SCHEMA,'contract_digest':result['digest'],
                    'requirements':len(requirements),
                    'unmapped':sum(not x['property'] for x in body['items']),
                    'status':'frozen_with_gaps' if any(not x['property'] for x in body['items']) else 'frozen_mapped',
                    'warning':'冻结不等于证明需求满足。未关联性质的需求仍将阻断准入。'}

    def design_task(self,pid):
        """Create a copyable spec-design request, never overwrite .ax or claim evidence."""
        plan=self.get(pid)
        if plan['stale']:raise FlowConflict('规格已变化，请先建立演化分支')
        if not plan['saved']:raise FlowError('请先保存你的验收场景')
        p=self.flow.get(pid)
        gaps=[x for x in plan['items'] if not x['property']]
        task={'schema':'ax-intent-design-task/1.2','project_id':pid,
              'goal':p['goal'], 'spec':p['spec'],'spec_baseline':p['baseline'],
              'current_spec_source':self.flow._file(p['spec'],'.ax').read_text('utf-8')[:262144],
              'draft_digest':plan['digest'],'scenarios':plan['items'],
              'gaps':[x['id'] for x in gaps],
              'deliverables':['请提出行为规格的候选修订，明确状态、动作与性质',
                              '为每条验收场景给出对应性质或说明无法表达的原因',
                              '列出假设、反例、边界情况和需要人工澄清的问题'],
              'constraints':['这是一份供人工审查的设计任务，不是经过证明的行为规格',
                             '不可修改原始规格、工程文件、测试、证据或 Gate',
                             '人工审查新规格后，必须在新版本重新验证与确认契约']}
        packet='Axiom Studio / 软件意图到行为规格设计任务（未获得执行或发布授权）\n'+json.dumps(task,ensure_ascii=False,indent=2)
        return {'task':task,'prompt':packet,'digest':_digest(task),'gaps':len(gaps),'executed':False}
