"""P2c explicitly synchronized, finite two-component *abstract* behavior checker.

Supports exactly two finite Axiom models, complete action pairing, same input/output
value domains, atomic simultaneous action steps and cross-state invariants. This
checks an explicitly constructed abstract product, NOT real C++ composition,
assume-guarantee refinement, arbitrary async interleaving or OS sandboxes.

Fail closed: incomplete action wiring, mismatched domains, unknown expression
operators, exhausted budgets, stale evidence and mismatched artifacts never pass.
"""
from __future__ import annotations
import itertools
import json
import re
import time
from collections import deque
from pathlib import Path
from .lang import AxError, parse, validate, digest, domain, assignments, evaluate

SCHEMA = 'ax-product-composition/0.1'
POLICY = 'ax-product-bounded-gate/0.1'
NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,79}$')
OPS_BINARY = {'eq','ne','lt','le','gt','ge','add','sub','and','or'}


def _valid_id(s):
    if not isinstance(s,str) or not NAME.fullmatch(s):
        raise AxError('E_PRODUCT_ID','invalid identifier')
    return s


def _domain_type(model, type_name):
    return ({'Bool': {'kind':'Bool'},**model['types']})[type_name]


def _typed_expr(e, state_types):
    if not isinstance(e,dict): raise AxError('E_PRODUCT_EXPR','expected structured expression')
    if set(e)=={'ref'}:
        if not isinstance(e['ref'],str) or e['ref'] not in state_types:
            raise AxError('E_PRODUCT_REFERENCE',str(e.get('ref')))
        return state_types[e['ref']]
    if set(e)=={'lit'}:
        if type(e['lit']) is bool: return 'Bool'
        if type(e['lit']) is int: return 'Int'
        raise AxError('E_PRODUCT_LITERAL','only bounded integer and boolean literals')
    if set(e)!={'op','args'} or not isinstance(e['args'],list):
        raise AxError('E_PRODUCT_EXPR','unexpected structure')
    op=e['op']; args=e['args']
    if op=='not':
        if len(args)!=1 or _typed_expr(args[0],state_types)!='Bool':
            raise AxError('E_PRODUCT_TYPE','not expects one boolean')
        return 'Bool'
    if op not in OPS_BINARY or len(args)!=2:
        raise AxError('E_PRODUCT_OPERATOR',str(op))
    ts=[_typed_expr(x,state_types) for x in args]
    if op in ('and','or'):
        if ts!=['Bool','Bool']:raise AxError('E_PRODUCT_TYPE',str(op))
        return 'Bool'
    if op in ('add','sub'):
        if ts!=['Int','Int']: raise AxError('E_PRODUCT_TYPE',str(op))
        return 'Int'
    if op in ('lt','le','gt','ge'):
        if ts!=['Int','Int']:raise AxError('E_PRODUCT_TYPE',str(op))
        return 'Bool'
    if ts[0]!=ts[1]:raise AxError('E_PRODUCT_TYPE','different equality operand types')
    return 'Bool'


def _eval_expr(e, state):
    if 'ref' in e:return state[e['ref']]
    if 'lit' in e:return e['lit']
    op=e['op'];args=[_eval_expr(x,state) for x in e['args']]
    return {'not': lambda:not args[0],
            'and':lambda:args[0] and args[1], 'or':lambda:args[0] or args[1],
            'add':lambda:args[0]+args[1], 'sub':lambda:args[0]-args[1],
            'eq':lambda:args[0]==args[1], 'ne':lambda:args[0]!=args[1],
            'lt':lambda:args[0]<args[1], 'le':lambda:args[0]<=args[1],
            'gt':lambda:args[0]>args[1], 'ge':lambda:args[0]>=args[1]}[op]()


def load_product(path):
    """Validate manifest + .ax files and return canonical bound product specification."""
    p=Path(path); raw=json.loads(p.read_text(encoding='utf-8'))
    if not isinstance(raw,dict) or set(raw)!={'schema','components','sync','properties'} or raw['schema']!=SCHEMA:
        raise AxError('E_PRODUCT_SCHEMA','incorrect product manifest')
    comp=raw['components']
    if not isinstance(comp,list) or len(comp)!=2:
        raise AxError('E_PRODUCT_COMPONENTS','only two components in P2c')
    root=p.resolve().parent
    models={}
    for c in comp:
        if not isinstance(c,dict) or set(c)!={'id','spec'}:
            raise AxError('E_PRODUCT_SCHEMA','invalid component')
        cid=_valid_id(c['id'])
        if cid in models: raise AxError('E_PRODUCT_DUPLICATE',cid)
        rel=c['spec']
        if not isinstance(rel,str) or not rel.endswith('.ax') or Path(rel).is_absolute():
            raise AxError('E_PRODUCT_PATH','only relative .ax files')
        target=root/rel
        resolved=target.resolve()
        if not resolved.is_relative_to(root) or target.is_symlink():
            raise AxError('E_PRODUCT_PATH','spec outside manifest directory')
        ir=validate(parse(resolved.read_text(encoding='utf-8')))
        if ir['model']!=cid: raise AxError('E_PRODUCT_MODEL','model id does not match')
        models[cid]=ir
    sync=raw['sync']
    if not isinstance(sync,list) or not 1<=len(sync)<=16:
        raise AxError('E_PRODUCT_SYNC','expected 1..16 action pairs')
    used=set(); pairs=[]; names=set(models)
    for item in sync:
        if not isinstance(item,dict) or set(item)!={'left','right','output_relation'}:
            raise AxError('E_PRODUCT_SCHEMA','incorrect sync fields')
        if item['output_relation'] != 'equal':
            raise AxError('E_PRODUCT_SYNC','P2c requires explicitly equal outputs')
        def action_at(ref):
            if not isinstance(ref,str) or ref.count('.')!=1:
                raise AxError('E_PRODUCT_REFERENCE','action must be Component.action')
            cid,aname=ref.split('.')
            if cid not in models:raise AxError('E_PRODUCT_REFERENCE',ref)
            found=next((a for a in models[cid]['actions'] if a['name']==aname),None)
            if found is None:raise AxError('E_PRODUCT_REFERENCE',ref)
            if ref in used:raise AxError('E_PRODUCT_SYNC','duplicate action pairing')
            used.add(ref)
            return cid,found
        lc,la=action_at(item['left']);rc,ra=action_at(item['right'])
        if lc==rc:raise AxError('E_PRODUCT_SYNC','self synchronization unsupported')
        # Require identical input field names and exact finite domains (not just cardinality).
        left_domains={k:_domain_type(models[lc],t) for k,t in la['inputs'].items()}
        right_domains={k:_domain_type(models[rc],t) for k,t in ra['inputs'].items()}
        if left_domains!=right_domains or _domain_type(models[lc],la['output'])!=_domain_type(models[rc],ra['output']):
            raise AxError('E_PRODUCT_DOMAIN','input or output domains do not match')
        pairs.append({'left':item['left'],'right':item['right'],'output_relation':'equal'})
    required={f'{cid}.{a["name"]}' for cid,ir in models.items() for a in ir['actions']}
    if required!=used:
        raise AxError('E_PRODUCT_UNPAIRED',f'unpaired actions: {sorted(required-used)}')
    props=raw['properties']
    if not isinstance(props,list) or not 1<=len(props)<=32:
        raise AxError('E_PRODUCT_PROPERTIES','expected 1..32 relational properties')
    state_types={f'{cid}.{key}':_domain_type(ir,ty)['kind'] for cid,ir in models.items() for key,ty in ir['state'].items()}
    propnames=set()
    for prop in props:
        if not isinstance(prop,dict) or set(prop)!={'name','expr'}:
            raise AxError('E_PRODUCT_SCHEMA','incorrect property fields')
        pname=_valid_id(prop['name'])
        if pname in propnames:raise AxError('E_PRODUCT_DUPLICATE','duplicate property')
        propnames.add(pname)
        if _typed_expr(prop['expr'],state_types)!='Bool':
            raise AxError('E_PRODUCT_TYPE','relational property must be Boolean')
    bound={'schema':SCHEMA,'components':[{'id':cid,'spec_digest':digest(ir)} for cid,ir in sorted(models.items())],
           'sync':sorted(pairs,key=lambda x:x['left']),
           'properties':sorted(props,key=lambda x:x['name'])}
    return models,bound


def _check_bound(models,bound):
    if (not isinstance(bound,dict) or bound.get('schema')!=SCHEMA or
        set(bound)!={'schema','components','sync','properties'}):
        raise AxError('E_PRODUCT_BINDING','invalid bound manifest')
    expected=[{'id':cid,'spec_digest':digest(ir)} for cid,ir in sorted(models.items())]
    if bound['components']!=expected or len(models)!=2:
        raise AxError('E_PRODUCT_BINDING','model bytes differ from bound digest')
    # Loading the manifest performs complete pairing/domain/expression checks.
    # For direct API use, reject untrusted structures rather than assuming they
    # came from the loader.
    if not isinstance(bound['sync'],list) or not bound['sync'] or not isinstance(bound['properties'],list):
        raise AxError('E_PRODUCT_BINDING','empty or invalid synchronization/properties')
    required={f'{cid}.{a["name"]}' for cid,ir in models.items() for a in ir['actions']}
    used=[]
    for pair in bound['sync']:
        if not isinstance(pair,dict) or set(pair)!={'left','right','output_relation'} or pair['output_relation']!='equal':
            raise AxError('E_PRODUCT_BINDING','invalid synchronization')
        for label in ('left','right'):
            ref=pair[label]
            if not isinstance(ref,str) or ref.count('.')!=1:
                raise AxError('E_PRODUCT_BINDING','invalid action reference')
            used.append(ref)
        lc,ln=pair['left'].split('.');rc,rn=pair['right'].split('.')
        if lc==rc or lc not in models or rc not in models:
            raise AxError('E_PRODUCT_BINDING','invalid pair components')
        la=next((a for a in models[lc]['actions'] if a['name']==ln),None)
        ra=next((a for a in models[rc]['actions'] if a['name']==rn),None)
        if la is None or ra is None:
            raise AxError('E_PRODUCT_BINDING','missing action')
        left_domains={k:_domain_type(models[lc],t) for k,t in la['inputs'].items()}
        right_domains={k:_domain_type(models[rc],t) for k,t in ra['inputs'].items()}
        if left_domains!=right_domains or _domain_type(models[lc],la['output'])!=_domain_type(models[rc],ra['output']):
            raise AxError('E_PRODUCT_BINDING','action domain mismatch')
    if len(used)!=len(set(used)) or set(used)!=required:
        raise AxError('E_PRODUCT_BINDING','not all actions paired exactly once')
    kinds={f'{cid}.{field}':_domain_type(ir,ty)['kind'] for cid,ir in models.items() for field,ty in ir['state'].items()}
    names=[]
    for prop in bound['properties']:
        if not isinstance(prop,dict) or set(prop)!={'name','expr'}:
            raise AxError('E_PRODUCT_BINDING','invalid property')
        names.append(_valid_id(prop['name']))
        if _typed_expr(prop['expr'],kinds)!='Bool':
            raise AxError('E_PRODUCT_BINDING','non-boolean property')
    if not names or len(names)!=len(set(names)) or len(names)>32:
        raise AxError('E_PRODUCT_BINDING','invalid property list')


def _successors(ir,action,state,inp,*,max_checks):
    """Atomic abstract successor set; raise on invalid/ambiguous/incomplete relation."""
    types={'Bool':{'kind':'Bool'},**ir['types']}
    guards=[i for i,c in enumerate(action['cases']) if not c.get('default') and evaluate(c['guard'],state,inp)]
    if len(guards)>1:raise AxError('E_CASE_OVERLAP',action['name'])
    if guards: idx=guards[0]
    else:
        defaults=[i for i,c in enumerate(action['cases']) if c.get('default')]
        if not defaults:raise AxError('E_CASE_UNCOVERED',action['name'])
        idx=defaults[0]
    case=action['cases'][idx]
    changes={k:ir['state'][k] for k in case['modifies']}
    matches=[];checks=0
    for delta in assignments(changes,types):
        after={**state,**delta}
        for result in domain(types[action['output']]):
            checks+=1
            if checks>max_checks:raise AxError('E_PRODUCT_BUDGET','successor budget exhausted')
            if evaluate(case['ensures'],state,inp,after=after,result=result):
                matches.append((after,result))
    if not matches:raise AxError('E_NO_SUCCESSOR',action['name'])
    return matches,checks


def verify_product(models,bound,*,max_states=10000,max_transitions=100000,timeout_s=20):
    """Exhaust finite synchronous product and cross-state invariants.

    Reports Bounded ONLY after complete exhaustion. Exhaustion of budgets gives
    Unknown. Component models are independently complete but no C++ claim follows.
    """
    st=time.monotonic()
    _check_bound(models,bound)
    scope={'target':'two-component-synchronous-abstract-product','semantics':SCHEMA,
           'finite_reachable_exhaustion':False,'max_states':max_states,
           'max_transitions':max_transitions,'timeout_seconds':timeout_s,
           'synchronization':'atomic-paired-step','unsupported':['unpaired actions','async interleavings','C++ refinement']}
    if not (type(max_states) is int and 1<=max_states<=100000 and
            type(max_transitions) is int and 1<=max_transitions<=1000000 and
            type(timeout_s) in (int,float) and 0<timeout_s<=120):
        return {'outcome':'Unknown','reason':'E_PRODUCT_BUDGET','scope':scope}
    ids=sorted(models)
    keyorder=[f'{cid}.{f}' for cid in ids for f in models[cid]['state']]
    def flatten(parts):return {f'{cid}.{field}':v for cid,values in parts.items() for field,v in values.items()}
    def signature(parts):return tuple(flatten(parts)[k] for k in keyorder)
    types={cid:{'Bool':{'kind':'Bool'},**ir['types']} for cid,ir in models.items()}
    initials={cid:[x for x in assignments(ir['state'],types[cid]) if evaluate(ir['init'],x)]
              for cid,ir in models.items()}
    if any(not arr for arr in initials.values()):
        return {'outcome':'Violated','reason':'E_PRODUCT_INIT_UNSAT','counterexample':[],'scope':scope}
    initial_count=1
    for cid in ids: initial_count*=len(initials[cid])
    if initial_count>max_states:
        return {'outcome':'Unknown','reason':'E_PRODUCT_LIMIT_STATES','scope':scope,
                'statistics':{'initial_states':initial_count,'checked_transitions':0}}
    seed=[dict(zip(ids,parts)) for parts in itertools.product(*(initials[c] for c in ids))]
    queue=deque((parts,[{'kind':'initial','state':flatten(parts)}]) for parts in seed)
    seen={signature(parts) for parts in seed}
    count=0
    def fail(outcome,reason,trace,detail=None):
        return {'outcome':outcome,'reason':reason,'detail':detail,'counterexample':trace,'scope':scope,
                'statistics':{'reachable_states':len(seen),'checked_transitions':count,'initial_states':len(seed)}}
    prepared=[]
    for pair in bound['sync']:
        lc,ln=pair['left'].split('.');rc,rn=pair['right'].split('.')
        la=next(a for a in models[lc]['actions'] if a['name']==ln)
        ra=next(a for a in models[rc]['actions'] if a['name']==rn)
        prepared.append((pair,lc,la,rc,ra))
    try:
        while queue:
            if time.monotonic()-st>timeout_s:
                return fail('Unknown','E_PRODUCT_TIMEOUT',[])
            parts,trace=queue.popleft()
            state=flatten(parts)
            for prop in bound['properties']:
                if not _eval_expr(prop['expr'],state):
                    return fail('Violated','E_PRODUCT_PROPERTY',trace,prop['name'])
            for pair,lc,la,rc,ra in prepared:
                for inp in assignments(la['inputs'],types[lc]):
                    left,nleft=_successors(models[lc],la,parts[lc],inp,max_checks=max_transitions-count)
                    count+=nleft
                    right,nright=_successors(models[rc],ra,parts[rc],inp,max_checks=max_transitions-count)
                    count+=nright
                    for lnext,lout in left:
                        for rnext,rout in right:
                            count+=1
                            if count>max_transitions:raise AxError('E_PRODUCT_BUDGET','transition budget exhausted')
                            step={'sync':[pair['left'],pair['right']],'input':inp,
                                  'outputs':{lc:lout,rc:rout},
                                  'state':flatten({**parts,lc:lnext,rc:rnext})}
                            if lout!=rout:
                                return fail('Violated','E_PRODUCT_OUTPUT',trace+[step],pair['left']+' != '+pair['right'])
                            nxt={**parts,lc:lnext,rc:rnext}
                            key=signature(nxt)
                            if key not in seen:
                                seen.add(key)
                                if len(seen)>max_states:
                                    return fail('Unknown','E_PRODUCT_LIMIT_STATES',trace+[step])
                                queue.append((nxt,trace+[step]))
    except AxError as exc:
        if exc.code=='E_PRODUCT_BUDGET':return fail('Unknown','E_PRODUCT_LIMIT_TRANSITIONS',[])
        return fail('Violated',exc.code,trace,exc.detail)
    scope['finite_reachable_exhaustion']=True
    return {'outcome':'Bounded','reason':'FINITE_SYNCHRONIZED_PRODUCT_EXHAUSTED',
            'counterexample':None,'statistics':{'reachable_states':len(seen),
                'checked_transitions':count,'initial_states':len(seed)},'scope':scope,
            'verified_properties':[p['name'] for p in bound['properties']]}
