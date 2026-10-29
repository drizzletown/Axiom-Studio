"""Axiom Studio 1.1: intent-first, truthful guided production journey.

Thin orchestration adapter: never synthesizes a behavioral spec from free text, never
runs code, never approves a Gate, and never recasts template checks as goal coverage.
"""
from __future__ import annotations
import secrets
from launchpad import TEMPLATES, LaunchError

PHASES = (
    ('intent','说清目标','明确软件要做什么、什么情况下算成功'),
    ('spec','明确行为边界','把重要行为与约束写成可以检查的规格'),
    ('contract','确认验收规则','由人逐项确认需求与规格性质的对应关系'),
    ('implementation','组织实现方案','由 AI、VS Code 或人工形成待审查的候选'),
    ('verification','独立检查实现','使用不同于生成者的工具检查规格与实现'),
    ('decision','裁决与持续演化','查看证据，决定是否接受测试级结果及下一次修改'),
)

# From the existing protected production queue, not from optimistic front-end guesses.
ACTIONS = {
    'verify': ('检查行为规则','自动检查当前示例规格；不会执行 C++ 程序', 'model_only'),
    'freeze': ('确认验收标准','逐项阅读规格性质、确认对应需求，再人工冻结', 'human'),
    'batch': ('准备实现方案','进入多文件方案比较，必须人工授权执行代码', 'human'),
    'task': ('获取 AI 开发任务','生成绑定当前规格与验收契约的任务包', 'safe'),
    'candidate': ('检查实现方案','继续候选审查，不能跳过人的批准', 'human'),
    'fork': ('建立新版本','输入变更原因，在新版本中重新验证', 'human'),
    'passport': ('复核测试证据','测试级复核需要实际 Gate 和人工确认', 'trusted_local'),
    'inspect': ('查看证据与当前问题','了解仍然缺少什么，历史记录不是发布许可', 'safe'),
}

class Journey:
    def __init__(self, studio):
        self.studio=studio

    def snapshot(self):
        cockpit=self.studio.cockpit.snapshot()
        items={item['project_id']:item for item in cockpit.get('next_actions',[]) if item.get('project_id')}
        rows=[]
        for p in cockpit['projects']:
            item=items.get(p['id'],{})
            action=item.get('next_action','inspect')
            label, explanation, risk=ACTIONS.get(action,ACTIONS['inspect'])
            steps=[]
            for i,(key,title,why) in enumerate(PHASES):
                if i==0:state='recorded'
                elif i==1:state=p['steps'][0]['state'] if p['steps'] else 'unknown'
                else:state=p['steps'][i-1]['state'] if len(p['steps'])>=i else 'unknown'
                steps.append({'id':key,'title':title,'why':why,'state':state})
            state=p.get('state','unknown')
            if state=='unknown' or not p.get('audit_valid'):
                action='inspect';label='检查项目证据异常';explanation='无法核对当前流程，不能继续构造';risk='blocked'
            rows.append({
                'id':p['id'],'name':p['name'],'goal':p.get('goal',''),
                'state':state,'steps':steps,'next':{'id':action,'label':label,'explanation':explanation,'risk':risk},
                'blockers':p.get('blockers',[]), 'stale':p.get('stale',False),
                'model_checked':bool(p.get('steps') and p['steps'][0]['state']=='passed'),
                'tested_only':bool(p.get('tested_only',False)),
                'release_authorized':False,
            })
        return {
            'schema':'ax-studio-journey/1.1','version':'1.2.0',
            'promise':'从目标出发，先明确可验证的行为规则，再让 AI 实现，并以独立证据作裁决。',
            'steps':[{'id':key,'title':title,'why':why} for key,title,why in PHASES],
            'projects':rows,'errors':cockpit.get('errors',[]),
            'total':len(rows), 'production_release_authorized':False,
            'important_notice':'自然语言目标不会自动变成已验证的规格。示例模板检查只覆盖模板中已写明的性质；不能当作用户全部需求已获证明。',
        }

    def start(self,scenario,name,goal):
        if scenario not in TEMPLATES:raise LaunchError('请选择支持的起点')
        if not isinstance(name,str) or not 2<=len(name.strip())<=100:raise LaunchError('请填写 2–100 字符的项目名称')
        if not isinstance(goal,str) or not 4<=len(goal.strip())<=2000:raise LaunchError('请描述至少 4 字符的软件目标')
        # Generate opaque unique folder identifier server-side; users need not learn path syntax.
        for _ in range(8):
            slug='idea-'+secrets.token_hex(5)
            if not (self.studio.flow.workspace/'projects'/slug).exists():break
        else:raise LaunchError('无法分配新的项目标识')
        created=self.studio.launchpad.create(scenario,slug,name.strip(),goal.strip())
        return {'schema':'ax-studio-journey-start/1.1',**created,
                'goal_status':'recorded_unverified',
                'next_action':'verify',
                'important_notice':'项目已建立；当前行为规格是示例起点，不是从您输入的目标自动推导的。请审核规格与目标的一致性，再确认验收契约。未调用 AI、未执行 C++。'}
