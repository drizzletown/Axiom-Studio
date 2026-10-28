"""Finite-state exhaustive, reachable-state verifier for Axiom P0.

A bounded result means all reachable states in the explicitly finite P0 domain
were enumerated subject to the declared resource limits. This is NOT evidence
about a generated C++ executable, an unbounded system, or omitted environment.
"""
from __future__ import annotations

from collections import deque
import itertools
import time

from .lang import AxError, assignments, domain, evaluate, validate


def obligations(ir):
    d=[]
    for prop in ir['properties']:
        d.append({"id":f"{ir['model']}/model/property/{prop['name']}",
                  "subject":"abstract-model", "property":prop['name'],"assurance":"Bounded"})
    for a in ir['actions']:
        for name in ('cases','transition_total','type_frame'):
            d.append({"id":f"{ir['model']}/model/action/{a['name']}/{name}",
                      "subject":"abstract-model","property":name,"assurance":"Bounded"})
    return d


def _to_tuple(state,keys): return tuple(state[k] for k in keys)


def verify(ir, *, max_states=50000, max_transitions=250000, timeout_s=30):
    start=time.monotonic()
    try: validate(ir,max_state_product=max_states)
    except AxError as exc:
        return {"outcome":"Unknown","reason":exc.code,"detail":exc.detail,"scope":{"stage":"semantic-validation"}}
    types={'Bool':{'kind':'Bool'},**ir['types']}
    state_fields=ir['state']; keys=tuple(state_fields)
    scope={"semantics":ir['semantics_version'],"state_domain":{k:types[t] for k,t in state_fields.items()},
           "input_domains":{a['name']:{k:types[t] for k,t in a['inputs'].items()} for a in ir['actions']},
           "max_states":max_states,"max_transitions":max_transitions,"timeout_seconds":timeout_s,
           "finite_reachable_exhaustion":False,"execution_model":"synchronous-action-boundaries"}
    def fail(reason, trace, *, detail=None, outcome='Violated'):
        return {"outcome":outcome,"reason":reason,"detail":detail,"counterexample":trace,
                "scope":scope,"statistics":{"reachable_states":len(seen),"checked_transitions":checked}}
    try:
        initial=[s for s in assignments(state_fields,types) if evaluate(ir['init'],s)]
    except (KeyError,ValueError,TypeError,AxError) as exc:
        return {"outcome":"Unknown","reason":"E_EVAL","detail":str(exc),"scope":scope}
    if not initial:
        return {"outcome":"Violated","reason":"E_INIT_UNSAT","counterexample":[],"scope":scope}
    queue=deque((s,[{"kind":"initial","state":s}]) for s in initial)
    seen={_to_tuple(s,keys) for s in initial}
    checked=0
    while queue:
        if time.monotonic()-start>timeout_s:
            return fail('E_TIMEOUT', [], outcome='Unknown')
        state,trace=queue.popleft()
        for prop in ir['properties']:
            if not evaluate(prop['expr'],state):
                return fail('E_PROPERTY',trace,detail=prop['name'])
        for action in ir['actions']:
            for inp in assignments(action['inputs'],types):
                guards=[i for i,c in enumerate(action['cases']) if not c.get('default') and evaluate(c['guard'],state,inp)]
                if len(guards)>1:
                    return fail('E_CASE_OVERLAP',trace+[{'action':action['name'],'input':inp}],detail=guards)
                if guards:
                    idx=guards[0]
                else:
                    defaults=[i for i,c in enumerate(action['cases']) if c.get('default')]
                    if not defaults:
                        return fail('E_CASE_UNCOVERED',trace+[{'action':action['name'],'input':inp}])
                    idx=defaults[0]
                case=action['cases'][idx]
                modified=set(case['modifies'])
                next_fields={k:state_fields[k] for k in keys if k in modified}
                matches=[]
                for delta in assignments(next_fields,types):
                    after={**state,**delta}
                    for result in domain(types[action['output']]):
                        checked+=1
                        if checked>max_transitions:
                            return fail('E_LIMIT_TRANSITIONS',trace,outcome='Unknown')
                        if evaluate(case['ensures'],state,inp,after=after,result=result):
                            matches.append((after,result))
                if not matches:
                    return fail('E_NO_SUCCESSOR',trace+[{'action':action['name'],'input':inp,'case':idx}])
                for next_state,result in matches:
                    step={'action':action['name'],'input':inp,'result':result,'state':next_state}
                    signature=_to_tuple(next_state,keys)
                    if signature not in seen:
                        seen.add(signature)
                        if len(seen)>max_states:
                            return fail('E_LIMIT_STATES',trace+[step],outcome='Unknown')
                        queue.append((next_state,trace+[step]))
    scope['finite_reachable_exhaustion']=True
    return {"outcome":"Bounded","reason":"FINITE_DOMAIN_EXHAUSTED","scope":scope,
            "statistics":{"reachable_states":len(seen),"checked_transitions":checked,
                          "initial_states":len(initial)},"counterexample":None,
            "verified_obligation_ids":[o['id'] for o in obligations(ir)]}
