"""Restricted .ax parser, typed expression AST and canonical serialization.

Design limitation: P0 has no integers outside explicitly finite domains, no unbounded
loops or fairness, and does not interpret C++ source code.
"""
from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import dataclass
from typing import Any

from lark import Lark, Transformer, UnexpectedInput

from . import SCHEMA_VERSION, SEMANTICS_VERSION

GRAMMAR = r'''
start: "model" NAME "{" type_decl* state_decl init_decl action_decl+ property_decl+ observe_decl "}"
type_decl: "type" NAME "=" type_expr
type_expr: "Int" "[" SIGNED_INT ".." SIGNED_INT "]" -> finite_int
         | "Bool"                                   -> boolean_type
state_decl: "state" "{" field_decl+ "}"
field_decl: NAME ":" NAME
init_decl: "init" "{" expr "}"
action_decl: "action" NAME "(" [field_decl ("," field_decl)*] ")" "->" NAME "{" case_decl+ "}"
case_decl: "case" case_guard "{" "modifies" "{" [names] "}" "ensures" expr "}"
case_guard: "otherwise" -> default_guard
          | expr        -> expression_guard
names: NAME ("," NAME)*
property_decl: "property" NAME "{" "always" expr "}"
observe_decl: "observe" "{" obs_item ("," obs_item)* "}"
obs_item: NAME "." obs_kind
obs_kind: "input"  -> input_kind
        | "output" -> output_kind
?expr: disjunction
?disjunction: conjunction ("||" conjunction)* -> or_group
?conjunction: comparison ("&&" comparison)* -> and_group
?comparison: addition (COMP_OP addition)?    -> comparison
?addition: multiplication (("+"|"-") multiplication)* -> addition
?multiplication: unary ("*" unary)* -> multiplication
?unary: "!" unary -> negation
      | "-" unary -> negative
      | atom
?atom: SIGNED_INT  -> number
     | "true"      -> true
     | "false"     -> false
     | NAME "'"    -> post_ref
     | NAME        -> ref
     | "(" expr ")"
COMP_OP: "==" | "!=" | "<=" | ">=" | "<" | ">"
NAME: /[a-zA-Z_][a-zA-Z0-9_]*/
%import common.SIGNED_INT
%import common.WS
%ignore WS
%ignore /\/\/[^\n]*/
'''

# For additive operator tokens, declare explicit terminals to preserve operator choice.
GRAMMAR = GRAMMAR.replace('(("+"|"-") multiplication)*', '((PLUS|MINUS) multiplication)*')
GRAMMAR = GRAMMAR.replace('("*" unary)*', '(STAR unary)*')
GRAMMAR += '\nPLUS: "+"\nMINUS: "-"\nSTAR: "*"\n'

_parser = Lark(GRAMMAR, parser="lalr", maybe_placeholders=False)

class AxError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail

class Build(Transformer):
    def NAME(self, token): return str(token)
    def SIGNED_INT(self, token): return int(token)
    def COMP_OP(self, token): return str(token)
    def PLUS(self, token): return str(token)
    def MINUS(self, token): return str(token)
    def number(self, args): return {"op":"lit", "value":args[0]}
    def true(self, _): return {"op":"lit", "value":True}
    def false(self, _): return {"op":"lit", "value":False}
    def ref(self, args): return {"op":"ref", "name":args[0]}
    def post_ref(self, args): return {"op":"post", "name":args[0]}
    def negation(self, args): return {"op":"not", "args":args}
    def negative(self, args): return {"op":"neg", "args":args}
    def _fold(self, args, operator):
        if len(args)==1: return args[0]
        return {"op":operator,"args":args}
    def or_group(self, args): return self._fold(args, "or")
    def and_group(self, args): return self._fold(args, "and")
    def comparison(self, args):
        if len(args)==1: return args[0]
        return {"op":args[1], "args":[args[0],args[2]]}
    def addition(self, args):
        x=args[0]
        for i in range(1,len(args),2): x={"op":"add" if args[i]=='+' else "sub", "args":[x,args[i+1]]}
        return x
    def multiplication(self, args):
        x=args[0]
        for i in range(1,len(args),2): x={"op":"mul", "args":[x,args[i+1]]}
        return x
    def finite_int(self, args): return {"kind":"Int", "min":args[0],"max":args[1]}
    def boolean_type(self, _): return {"kind":"Bool"}
    def type_expr(self, args): return args[0]
    def type_decl(self, args): return (args[0],args[1])
    def field_decl(self, args): return (args[0], args[1])
    def state_decl(self, args):
        keys=[name for name,_ in args]
        if len(keys)!=len(set(keys)): raise AxError('E_DUP_STATE','duplicate state field')
        return {"tag":"state","fields":dict(args)}
    def init_decl(self, args): return {"tag":"init","expr":args[0]}
    def names(self, args): return list(args)
    def default_guard(self, _): return {"default":True}
    def expression_guard(self, args): return {"guard":args[0]}
    def case_guard(self, args): return args[0]
    def case_decl(self, args):
        guard=args[0]
        # Distinguish empty modifies from absent optional list.
        if len(args)==2:
            changes=[]; ensures=args[1]
        else:
            changes=args[1]; ensures=args[2]
        return {**guard, "modifies":changes, "ensures":ensures}
    def action_decl(self, args):
        name=args[0]
        fields=[a for a in args[1:-1] if isinstance(a,tuple)]
        cases=[a for a in args[1:] if isinstance(a,dict) and 'ensures' in a]
        if len(fields)!=len(set(k for k,v in fields)):
            raise AxError('E_DUP_INPUT',name)
        # last occurrence of string other than action name is output type
        out=[a for a in args[1:] if isinstance(a,str)]
        return {"name":name, "inputs":dict(fields), "output":out[0], "cases":cases}
    def property_decl(self, args): return {"name":args[0],"kind":"invariant","expr":args[1]}
    def input_kind(self,_): return "input"
    def output_kind(self,_): return "output"
    def obs_item(self,args): return ".".join(args)
    def observe_decl(self,args): return list(args)
    def start(self,args):
        name=args[0]; types={}; actions=[]; props=[]
        for a in args[1:]:
            if isinstance(a,tuple):
                if a[0] in types: raise AxError("E_DUP_TYPE",a[0])
                types[a[0]]=a[1]
            elif isinstance(a,dict) and a.get('tag')=='state': state=a['fields']
            elif isinstance(a,dict) and a.get('tag')=='init': init=a['expr']
            elif isinstance(a,dict) and "inputs" in a: actions.append(a)
            elif isinstance(a,dict) and "kind" in a: props.append(a)
            elif isinstance(a,list): obs=a
            else: raise AxError("E_AST",f"unexpected node {a}")
        return {"schema_version":SCHEMA_VERSION,"semantics_version":SEMANTICS_VERSION,
                "model":name,"types":types,"state":state,"init":init,
                "actions":actions,"properties":props,"observe":obs}

def canonical_bytes(obj: dict) -> bytes:
    return json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')

def digest(obj: dict|bytes) -> str:
    raw = obj if isinstance(obj,bytes) else canonical_bytes(obj)
    return 'sha256:'+hashlib.sha256(raw).hexdigest()

def parse(source:str)->dict:
    try: return Build().transform(_parser.parse(source))
    except UnexpectedInput as exc:
        raise AxError('E_PARSE',str(exc)) from exc
    except AxError: raise
    except Exception as exc:
        raise AxError('E_AST',str(exc)) from exc

def _check_expr(e, env, *, post=False):
    op=e['op']
    if op=='lit': return 'Bool' if type(e['value']) is bool else 'Int'
    if op in ('ref','post'):
        if op=='post' and not post: raise AxError('E_POST_SCOPE',e['name'])
        if e['name'] not in env: raise AxError('E_UNBOUND',e['name'])
        if op=='post' and e['name'] not in env['__state__']: raise AxError('E_POST_NOT_STATE',e['name'])
        return env[e['name']]
    args=[_check_expr(a,env,post=post) for a in e['args']]
    if op in ('and','or','not'):
        if any(t!='Bool' for t in args): raise AxError('E_TYPE',f'{op} expects Bool, got {args}')
        return 'Bool'
    if op in ('add','sub','mul','neg'):
        if any(t!='Int' for t in args): raise AxError('E_TYPE',f'{op} expects Int, got {args}')
        return 'Int'
    if op in ('<','<=','>','>=','==','!='):
        if args[0]!=args[1]: raise AxError('E_TYPE',f'{op} operands differ: {args}')
        if op not in ('==','!=') and args[0]!='Int': raise AxError('E_TYPE',f'{op} requires Int')
        return 'Bool'
    raise AxError('E_UNSUPPORTED',f'operator {op}')

def validate(ir:dict,*, max_state_product=50000,max_input_product=10000)->dict:
    types={'Bool':{'kind':'Bool'},**ir['types']}
    for n,t in ir['types'].items():
        if n=='Bool': raise AxError('E_DUP_TYPE','Bool is built in')
        if t['kind']=='Int' and t['min']>t['max']: raise AxError('E_DOMAIN',n)
    def known(n):
        if n not in types: raise AxError('E_UNKNOWN_TYPE',n)
    states=ir['state']
    if not states: raise AxError('E_STATE_EMPTY','state must contain fields')
    for n,t in states.items(): known(t)
    env={n:types[t]['kind'] for n,t in states.items()}
    env['__state__']=set(states)
    def require_bool(e,env,post=False):
        if _check_expr(e,env,post=post)!='Bool': raise AxError('E_TYPE','expected Bool expression')
    require_bool(ir['init'],env)
    prop_names=[p['name'] for p in ir['properties']]
    if len(prop_names)!=len(set(prop_names)): raise AxError('E_DUP_PROPERTY','duplicate property')
    for p in ir['properties']: require_bool(p['expr'],env)
    names=[]
    for a in ir['actions']:
        if a['name'] in names: raise AxError('E_DUP_ACTION',a['name'])
        names.append(a['name'])
        known(a['output'])
        aenv=env.copy()
        for n,t in a['inputs'].items():
            known(t)
            if n in env: raise AxError('E_SHADOW',n)
            aenv[n]=types[t]['kind']
        if 'result' in aenv: raise AxError('E_SHADOW','result is reserved')
        aenv['result']=types[a['output']]['kind']
        defaults=0
        for index,c in enumerate(a['cases']):
            if c.get('default'):
                defaults+=1
                if index!=len(a['cases'])-1: raise AxError('E_DEFAULT_ORDER',a['name'])
            else: require_bool(c['guard'],{k:v for k,v in aenv.items() if k!='result'})
            if len(c['modifies'])!=len(set(c['modifies'])): raise AxError('E_FRAME_DUP',a['name'])
            for x in c['modifies']:
                if x not in states: raise AxError('E_FRAME_UNKNOWN',x)
            require_bool(c['ensures'],aenv,post=True)
        if defaults>1: raise AxError('E_MULTI_DEFAULT',a['name'])
    expected={f'{a}.input' for a in names}|{f'{a}.output' for a in names}
    if set(ir['observe'])!=expected or len(ir['observe'])!=len(expected):
        raise AxError('E_OBSERVE',f'P0 requires all action input/output visible, expected {sorted(expected)}')
    def size(t):
        info=types[t]; return 2 if info['kind']=='Bool' else info['max']-info['min']+1
    n=1
    for t in states.values(): n*=size(t)
    if n>max_state_product: raise AxError('E_LIMIT',f'state space {n} > {max_state_product}')
    for a in ir['actions']:
        p=1
        for t in a['inputs'].values(): p*=size(t)
        if p>max_input_product: raise AxError('E_LIMIT',f'input space {p} > {max_input_product}')
    return ir

def domain(t:dict)->list:
    return [False,True] if t['kind']=='Bool' else list(range(t['min'],t['max']+1))

def evaluate(expr:dict, state:dict, inputs=None, *, after=None,result=None)->Any:
    inputs=inputs or {}
    op=expr['op']
    if op=='lit': return expr['value']
    if op=='ref':
        name=expr['name']
        if name=='result': return result
        return state[name] if name in state else inputs[name]
    if op=='post':
        if after is None: raise AxError('E_EVAL','post-state not provided')
        return after[expr['name']]
    args=[evaluate(a,state,inputs,after=after,result=result) for a in expr['args']]
    fn={'and':lambda a:all(a),'or':lambda a:any(a),'not':lambda a:not a[0],
        'neg':lambda a:-a[0], 'add':lambda a:a[0]+a[1], 'sub':lambda a:a[0]-a[1],
        'mul':lambda a:a[0]*a[1],
        '==':lambda a:a[0]==a[1], '!=':lambda a:a[0]!=a[1],
        '<':lambda a:a[0]<a[1],'<=':lambda a:a[0]<=a[1],
        '>':lambda a:a[0]>a[1],'>=':lambda a:a[0]>=a[1]}
    return fn[op](args)

def assignments(fields:dict,types:dict):
    ks=list(fields)
    for vs in itertools.product(*(domain(types[fields[k]]) for k in ks)):
        yield dict(zip(ks,vs))
