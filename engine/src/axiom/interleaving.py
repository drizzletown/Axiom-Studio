"""P2d: mixed rendezvous + interleaving for two *finite abstract* Axiom models.

Scheduler explores every enabled one-component atomic step and every declared
rendezvous atomic step. State predicates are checked after *each* global step.
The checker does not infer causal links, progress/fairness, C++ refinement or
network semantics. All actions must be declared exactly once in the manifest.
"""
from __future__ import annotations

from collections import deque
import itertools
import json
from pathlib import Path
import time

from .lang import AxError, assignments, canonical_bytes, digest, domain, evaluate, parse, validate
from .product import _domain_type, _eval_expr, _successors, _typed_expr, _valid_id

SCHEMA = 'ax-interleaving-composition/0.1'
POLICY = 'ax-interleaving-bounded-gate/0.1'


def _models_from_manifest(path, raw):
    components = raw['components']
    if not isinstance(components,list) or len(components)!=2:
        raise AxError('E_INTER_COMPONENTS','expected exactly two components')
    models={}
    root=Path(path).resolve().parent
    for component in components:
        if not isinstance(component,dict) or set(component)!={'id','spec'}:
            raise AxError('E_INTER_SCHEMA','invalid component')
        cid=_valid_id(component['id'])
        if cid in models:
            raise AxError('E_INTER_DUPLICATE',cid)
        rel=component['spec']
        if not isinstance(rel,str) or not rel.endswith('.ax') or Path(rel).is_absolute():
            raise AxError('E_INTER_PATH','invalid spec path')
        target=root/rel
        resolved=target.resolve()
        if target.is_symlink() or not resolved.is_relative_to(root):
            raise AxError('E_INTER_PATH','spec path escapes composition directory')
        ir=validate(parse(resolved.read_text(encoding='utf8')))
        if ir['model']!=cid:raise AxError('E_INTER_MODEL',cid)
        models[cid]=ir
    return models


def _check_bound(models,bound):
    """Complete validation even for direct Python API calls with forged manifests."""
    if not isinstance(bound,dict) or set(bound)!={'schema','components','sync','independent','properties'} or bound['schema']!=SCHEMA:
        raise AxError('E_INTER_BINDING','schema mismatch')
    if len(models)!=2 or bound['components']!=[{'id':cid,'spec_digest':digest(ir)} for cid,ir in sorted(models.items())]:
        raise AxError('E_INTER_BINDING','model digest mismatch')
    actions={f'{cid}.{a["name"]}':(cid,a) for cid,ir in models.items() for a in ir['actions']}
    if not isinstance(bound['sync'],list) or len(bound['sync'])>16 or not isinstance(bound['independent'],list):
        raise AxError('E_INTER_BINDING','invalid action declarations')
    used=[]
    for p in bound['sync']:
        if not isinstance(p,dict) or set(p)!={'left','right','output_relation'} or p['output_relation']!='equal':
            raise AxError('E_INTER_SYNC','rendezvous requires equal output')
        left,right=p['left'],p['right']
        if not isinstance(left,str) or not isinstance(right,str) or left not in actions or right not in actions:
            raise AxError('E_INTER_REFERENCE','unknown action')
        lc,la=actions[left];rc,ra=actions[right]
        if lc==rc:raise AxError('E_INTER_SYNC','rendezvous within same component')
        inputs_l={k:_domain_type(models[lc],t) for k,t in la['inputs'].items()}
        inputs_r={k:_domain_type(models[rc],t) for k,t in ra['inputs'].items()}
        if inputs_l!=inputs_r or _domain_type(models[lc],la['output'])!=_domain_type(models[rc],ra['output']):
            raise AxError('E_INTER_DOMAIN','rendezvous domains differ')
        used.extend((left,right))
    for ref in bound['independent']:
        if not isinstance(ref,str) or ref not in actions:
            raise AxError('E_INTER_REFERENCE','unknown independent action')
        used.append(ref)
    if len(used)!=len(set(used)) or set(used)!=set(actions):
        raise AxError('E_INTER_UNPAIRED','actions must appear exactly once across sync and independent')
    if not isinstance(bound['properties'],list) or not 1<=len(bound['properties'])<=32:
        raise AxError('E_INTER_PROPERTY','expected 1..32 properties')
    state_types={f'{cid}.{key}':_domain_type(ir,ty)['kind'] for cid,ir in models.items() for key,ty in ir['state'].items()}
    prop_names=[]
    for p in bound['properties']:
        if not isinstance(p,dict) or set(p)!={'name','expr'}:
            raise AxError('E_INTER_PROPERTY','invalid property')
        prop_names.append(_valid_id(p['name']))
        if _typed_expr(p['expr'],state_types)!='Bool':
            raise AxError('E_INTER_PROPERTY','property must be Boolean')
    if len(prop_names)!=len(set(prop_names)):
        raise AxError('E_INTER_DUPLICATE','duplicate property name')


def load_interleaving(path):
    raw=json.loads(Path(path).read_text(encoding='utf8'))
    if not isinstance(raw,dict) or set(raw)!={'schema','components','sync','independent','properties'} or raw['schema']!=SCHEMA:
        raise AxError('E_INTER_SCHEMA','invalid interleaving manifest')
    models=_models_from_manifest(path,raw)
    bound={'schema':SCHEMA,
           'components':[{'id':cid,'spec_digest':digest(ir)} for cid,ir in sorted(models.items())],
           'sync':sorted(raw['sync'],key=lambda s: (str(s.get('left')),str(s.get('right'))) if isinstance(s,dict) else ('','')) if isinstance(raw['sync'],list) else raw['sync'],
           'independent':sorted(raw['independent']) if isinstance(raw['independent'],list) and all(isinstance(x,str) for x in raw['independent']) else raw['independent'],
           'properties':sorted(raw['properties'],key=lambda p: str(p.get('name'))) if isinstance(raw['properties'],list) and all(isinstance(p,dict) for p in raw['properties']) else raw['properties']}
    _check_bound(models,bound)
    return models,bound


def verify_interleaving(models,bound,*,max_states=10000,max_transitions=100000,timeout_s=20):
    _check_bound(models,bound)
    scope={'target':'two-component-mixed-interleaving-abstract-product','semantics':SCHEMA,
           'finite_reachable_exhaustion':False,'max_states':max_states,'max_transitions':max_transitions,
           'timeout_seconds':timeout_s,'scheduler':'all-atomic-independent-steps-and-declared-rendezvous',
           'property_check':'every-reachable-post-step-state',
           'unsupported':['nonatomic steps','message queues','fairness','liveness','C++ refinement','network failures']}
    if not (type(max_states) is int and 1<=max_states<=100000 and
            type(max_transitions) is int and 1<=max_transitions<=1000000 and
            type(timeout_s) in (int,float) and 0<timeout_s<=120):
        return {'outcome':'Unknown','reason':'E_INTER_BUDGET','scope':scope}
    start=time.monotonic()
    ids=sorted(models)
    types={cid:{'Bool':{'kind':'Bool'},**ir['types']} for cid,ir in models.items()}
    fields=[f'{cid}.{field}' for cid in ids for field in models[cid]['state']]
    def flatten(parts):return {f'{cid}.{key}':v for cid,state in parts.items() for key,v in state.items()}
    def signature(parts):
        flat=flatten(parts)
        return tuple(flat[f] for f in fields)
    init={cid:[a for a in assignments(ir['state'],types[cid]) if evaluate(ir['init'],a)] for cid,ir in models.items()}
    if any(not v for v in init.values()):
        return {'outcome':'Violated','reason':'E_INTER_INIT_UNSAT','scope':scope,'counterexample':[]}
    init_count=1
    for cid in ids:init_count*=len(init[cid])
    if init_count>max_states:
        return {'outcome':'Unknown','reason':'E_INTER_LIMIT_STATES','scope':scope,'statistics':{'initial_states':init_count}}
    initial=(dict(zip(ids,values)) for values in itertools.product(*(init[cid] for cid in ids)))
    q=deque();seen=set()
    for parts in initial:
        key=signature(parts)
        seen.add(key)
        q.append((parts,[{'kind':'initial','state':flatten(parts)}]))
    actions={f'{cid}.{a["name"]}':(cid,a) for cid,ir in models.items() for a in ir['actions']}
    budget=0
    def fail(outcome,reason,trace,detail=None):
        return {'outcome':outcome,'reason':reason,'detail':detail,'counterexample':trace,'scope':scope,
                'statistics':{'initial_states':init_count,'reachable_states':len(seen),'checked_transitions':budget}}
    while q:
        if time.monotonic()-start>timeout_s:return fail('Unknown','E_INTER_TIMEOUT',[])
        parts,trace=q.popleft()
        flat=flatten(parts)
        for prop in bound['properties']:
            if not _eval_expr(prop['expr'],flat):
                return fail('Violated','E_INTER_PROPERTY',trace,prop['name'])
        # Generator labels preserve the exact scheduling event in the counterexample.
        def successors():
            nonlocal budget
            for ref in bound['independent']:
                cid,action=actions[ref]
                for inp in assignments(action['inputs'],types[cid]):
                    result,count=_successors(models[cid],action,parts[cid],inp,max_checks=max_transitions-budget)
                    budget+=count
                    for after,out in result:
                        budget+=1
                        if budget>max_transitions:raise AxError('E_PRODUCT_BUDGET','transition budget')
                        nxt={**parts,cid:after}
                        yield nxt,{'kind':'independent','action':ref,'input':inp,'output':out,'state':flatten(nxt)}
            for pair in bound['sync']:
                lc,la=actions[pair['left']];rc,ra=actions[pair['right']]
                for inp in assignments(la['inputs'],types[lc]):
                    left,nl=_successors(models[lc],la,parts[lc],inp,max_checks=max_transitions-budget)
                    budget+=nl
                    right,nr=_successors(models[rc],ra,parts[rc],inp,max_checks=max_transitions-budget)
                    budget+=nr
                    for ls,lo in left:
                        for rs,ro in right:
                            budget+=1
                            if budget>max_transitions:raise AxError('E_PRODUCT_BUDGET','transition budget')
                            nxt={**parts,lc:ls,rc:rs}
                            step={'kind':'rendezvous','sync':[pair['left'],pair['right']],
                                  'input':inp,'outputs':{lc:lo,rc:ro},'state':flatten(nxt)}
                            if lo!=ro:
                                raise _OutputMismatch(step)
                            yield nxt,step
        try:
            for nxt,step in successors():
                key=signature(nxt)
                if key not in seen:
                    if len(seen)>=max_states:return fail('Unknown','E_INTER_LIMIT_STATES',trace+[step])
                    seen.add(key)
                    q.append((nxt,trace+[step]))
        except _OutputMismatch as mismatch:
            return fail('Violated','E_INTER_OUTPUT',trace+[mismatch.step])
        except AxError as exc:
            if exc.code=='E_PRODUCT_BUDGET':return fail('Unknown','E_INTER_LIMIT_TRANSITIONS',[])
            return fail('Violated',exc.code,trace,exc.detail)
    scope['finite_reachable_exhaustion']=True
    return {'outcome':'Bounded','reason':'FINITE_MIXED_INTERLEAVING_EXHAUSTED','counterexample':None,
            'scope':scope,'statistics':{'initial_states':init_count,'reachable_states':len(seen),'checked_transitions':budget},
            'verified_properties':[p['name'] for p in bound['properties']]}


class _OutputMismatch(Exception):
    def __init__(self,step):self.step=step
