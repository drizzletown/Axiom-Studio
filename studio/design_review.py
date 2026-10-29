"""Axiom Studio 1.4: readable, read-only review of checked specification alternatives.

A comparison describes syntactic/AST deltas, not business equivalence, proof
strength, correctness of an AI proposal, or a ranking of product quality.
No model is contacted, no project files are written, no native code is run.
"""
from __future__ import annotations

from orchestrator import FlowError, FlowConflict, canonical, digest
from production import _load_ax


def _hash(value):
    return 'sha256:' + digest(canonical(value))


def _names(ir, key):
    if key in ('types', 'state'):
        return dict(ir.get(key) or {})
    if key in ('actions', 'properties'):
        return {x['name']: x for x in ir.get(key, [])}
    if key == 'observe':
        return {str(x): str(x) for x in ir.get('observe', [])}
    return {}


def _delta(old, new):
    a, b = set(old), set(new)
    kept = sorted(k for k in a & b if _hash(old[k]) == _hash(new[k]))
    changed = sorted(k for k in a & b if _hash(old[k]) != _hash(new[k]))
    return {'added': sorted(b-a), 'removed': sorted(a-b),
            'changed': changed, 'unchanged': kept}


def _expr(node, depth=0):
    """Display a compact mechanical expression hint. Never claim full translation."""
    if depth > 7:
        return '…'
    if not isinstance(node, dict):
        return str(node)[:60]
    op = node.get('op', '?')
    if op == 'ref':
        return str(node.get('name', '?'))[:100]
    if op == 'lit':
        val = node.get('value')
        if isinstance(val, bool):
            return '真' if val else '假'
        return repr(val)[:100]
    args = node.get('args') or []
    if not isinstance(args, list):
        args = []
    symbols = {'or': '或', 'and': '且', '==': '等于', '!=': '不等于',
               '>': '大于', '<': '小于', '>=': '不小于', '<=': '不大于',
               '+': '加', '-': '减', '*': '乘', 'implies': '蕴含'}
    if op in ('not','!') and len(args)==1:
        return '非（'+_expr(args[0],depth+1)+'）'
    if op in symbols and 1 < len(args) <= 8:
        return '（'+(' '+symbols[op]+' ').join(_expr(a,depth+1) for a in args)+'）'
    return str(op)[:50]+'（'+'，'.join(_expr(a,depth+1) for a in args[:4])+'）'


class DesignReview:
    def __init__(self, studio):
        self.studio = studio
        self.workshop = studio.spec_workshop
        self.flow = studio.flow

    def _context(self, pid):
        project, plan, original = self.workshop._input(pid)
        baseline = _load_ax(self.flow.engine, original.decode('utf-8'))
        return project, plan, baseline

    def _checked(self, pid, cid, plan):
        with self.flow.lock, self.flow._connect() as cx:
            body = self.workshop._load(cx, cid)
        if body['project_id'] != pid:
            raise FlowError('只能评审当前项目的规格候选')
        if body['state'] not in ('checked','promoted') or not (body.get('assessment') or {}).get('passed'):
            raise FlowConflict('候选尚未通过独立模型检查，不能进入通过方案的对比')
        self.workshop._current(body)  # verifies pinned parent, scenario and audit
        if body['scenario_digest'] != plan['digest']:
            raise FlowConflict('验收场景已经变化，需要重新生成候选')
        candidate = _load_ax(self.flow.engine, body['source'])
        props = set(_names(candidate, 'properties'))
        if set(body['assessment'].get('properties', [])) != props:
            raise FlowConflict('模型检查记录与当前规格性质不一致')
        return body, candidate

    def _profile(self, baseline, candidate, plan, body):
        deltas = {key: _delta(_names(baseline,key), _names(candidate,key))
                  for key in ('types','state','actions','properties','observe')}
        previous = _names(baseline,'properties')
        current = _names(candidate,'properties')
        properties = []
        for name in sorted(current):
            item = current[name]
            expr = _expr(item.get('expr'))[:360]
            status = ('new' if name not in previous else
                      'unchanged' if _hash(previous[name])==_hash(item) else 'modified')
            properties.append({'name':name,'status':status,'expression_hint':expr,
                               'caution':'表达式是程序化提示，不能替代对业务含义的人工判断。'})
        checks = body['assessment'].get('checks', [])
        rows = []
        for scene in plan['items']:
            mapped = scene['property']
            state = ('unmapped' if not mapped else
                     'removed' if mapped not in current else
                     'unchanged' if mapped in previous and _hash(previous[mapped])==_hash(current[mapped])
                     else 'changed')
            notes = {'unmapped':'这条需求尚无已确认的形式规则映射。',
                     'removed':'原先关联的规则在此候选中不存在，需要重新确认。',
                     'unchanged':'原关联性质的结构未变；文字需求是否满足仍须人工审查。',
                     'changed':'原关联性质内容已变化，需要重新确认行为含义。'}
            rows.append({'id':scene['id'],'title':scene['title'],'property':mapped,
                         'status':state,'message':notes[state]})
        warnings = []
        if any(deltas[x]['changed'] or deltas[x]['removed'] for x in ('types','state','actions')):
            warnings.append('状态、类型或动作发生修改：需要审查模型行为是否符合原有意图。')
        if deltas['properties']['changed'] or deltas['properties']['removed']:
            warnings.append('原有行为性质被改变或删除：必须重新检查验收场景的关联。')
        if deltas['observe']['added'] or deltas['observe']['removed']:
            warnings.append('外部可观察内容变化：需评估接口及调用方兼容性。')
        if any(r['status']!='unchanged' for r in rows):
            warnings.append('存在未覆盖或需要重新确认的验收场景，不能自动判定满足用户目标。')
        if not warnings:
            warnings.append('当前对比没有发现上述结构性警示；这仍不构成业务正确性保证。')
        return {'id':body['id'],'source_sha256':body['source_sha256'],
                'origin':body['origin'],'notes':body.get('notes',''),
                'model_checked':True,
                'check_outcomes':[{'step':i['step'],'returncode':i['returncode'],
                                   'outcome':i.get('outcome')} for i in checks],
                'deltas':deltas,'properties':properties,'scenarios':rows,
                'warnings':warnings,
                'unresolved_scenarios':sum(x['status']!='unchanged' for x in rows),
                'description': '仅比较模型结构、性质表达式与既有人工追溯关系；不对候选方案作自动质量排名。'}

    def inspect(self, pid, cid):
        with self.flow.lock:
            _,plan,base = self._context(pid)
            body, ir = self._checked(pid,cid,plan)
            result = self._profile(base,ir,plan,body)
            result['schema']='ax-design-review/1.4'
            result['goal']=self.flow.get(pid)['goal']
            result['scenario_digest']=plan['digest']
            result['review_digest']=_hash(result)
            return result

    def compare(self, pid, candidates):
        if not isinstance(candidates,list) or len(candidates)!=2 or not all(isinstance(x,str) for x in candidates) or candidates[0]==candidates[1]:
            raise FlowError('请选择两份不同且已检查的候选方案进行比较')
        with self.flow.lock:
            project,plan,baseline = self._context(pid)
            a_body,a_ir = self._checked(pid,candidates[0],plan)
            b_body,b_ir = self._checked(pid,candidates[1],plan)
            a=self._profile(baseline,a_ir,plan,a_body)
            b=self._profile(baseline,b_ir,plan,b_body)
            between={key:_delta(_names(a_ir,key),_names(b_ir,key))
                     for key in ('types','state','actions','properties','observe')}
            result={'schema':'ax-design-comparison/1.4','project_id':pid,
                    'goal':project['goal'],'scenario_digest':plan['digest'],
                    'candidates':[a,b], 'differences_between_candidates':between,
                    'interpretation':'结构差异和原性质的保持情况仅供人评审；通过模型检查不证明需求已被完整表达。',
                    'no_automatic_winner':True,'approval_performed':False}
            result['comparison_digest']=_hash(result)
            return result
