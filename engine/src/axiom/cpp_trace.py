"""P2e deterministic multi-operation C++ traces checked against Axiom interleaving IR.

Restricted to Source/Mirror Bool demo contract. Uses rootless Linux namespaces to
isolate compiler/candidate from normal user workspace, but is NOT a production
security sandbox nor a formal C++ refinement proof. Every schedule of length <=D
is exercised, reset between schedules. Test-only observational assurance.
"""
from __future__ import annotations
from dataclasses import dataclass
from itertools import product
from pathlib import Path
import copy
import json
import re
import time

from .lang import AxError, assignments, canonical_bytes, digest, evaluate
from .product import _successors
from .interleaving import _check_bound, verify_interleaving, SCHEMA as INTER_SCHEMA
from .sandbox import execute, available

TRACE_VERSION='ax-cpp-trace/0.1'
CONTRACT_VERSION='ax-cpp-trace-bool-abi/0.1'
COMMON=['-std=c++20','-Wall','-Wextra','-Werror','-pedantic','-O1','-fno-omit-frame-pointer']

# The compiled candidate.cpp must provide these exact names. Declared in the harness.
HARNESS=r'''#include <iostream>
#include <cstdint>
extern "C" void axiom_reset(int left,int right);
extern "C" int axiom_step(int opcode,int desired,int* left,int* right);
#include "candidate.cpp"
int main() {
    int count=0;
    if (!(std::cin >> count) || count<0 || count>3000) return 40;
    for (int i=0; i<count; ++i) {
        int left,right,n;
        if (!(std::cin >> left >> right >> n) || n<0 || n>10) return 41;
        axiom_reset(left,right);
        for (int j=0;j<n;++j) {
            int op,desired,out_left,out_right;
            if (!(std::cin >> op >> desired)) return 42;
            int result=axiom_step(op,desired,&out_left,&out_right);
            std::cout << out_left << ' ' << out_right << ' ' << result << '\n';
        }
    }
    if (!std::cin.eof()) {std::cin >> std::ws; if (!std::cin.eof()) return 43;}
    return 0;
}
'''


def check_abi(models,bound):
    _check_bound(models,bound)
    if set(models) != {'Source','Mirror'} or len(bound['sync'])!=1 or (
        bound['sync'][0] != {'left':'Source.set','right':'Mirror.set','output_relation':'equal'}
    ) or bound['independent']!=['Mirror.peek','Source.peek']:
        raise AxError('E_TRACE_ABI','only Source/Mirror {set synchronized, peek independent} is supported')
    for cid,ir in models.items():
        if (ir['state']!={'on':'Flag'} or ir['types'].get('Flag')!={'kind':'Bool'} or
            {a['name'] for a in ir['actions']}!={'set','peek'}):
            raise AxError('E_TRACE_ABI','state must be one Bool Flag on, actions set/peek')
        actions={a['name']:a for a in ir['actions']}
        if actions['set']['inputs']!={'desired':'Flag'} or actions['set']['output']!='Bool' or (
            actions['peek']['inputs'] or actions['peek']['output']!='Bool'
        ):
            raise AxError('E_TRACE_ABI','invalid action signatures')
        initial=[s for s in assignments(ir['state'],{'Bool':{'kind':'Bool'},**ir['types']}) if evaluate(ir['init'],s)]
        if len(initial)!=1 or initial[0]!={'on':False}:
            raise AxError('E_TRACE_ABI','P2e supports unique false initial state only')
    return True


def schedules(depth):
    if type(depth) is not int or depth<1 or depth>5:
        raise AxError('E_TRACE_DEPTH','P2e supports length 1..5')
    options=[(0,0),(0,1),(1,0),(2,0)]
    seqs=[seq for d in range(1,depth+1) for seq in product(options,repeat=d)]
    # Same cases replay in reverse order, detecting some hidden state across resets.
    return seqs+list(reversed(seqs))


def _reference(models,bound,seq):
    actions={cid:{a['name']:a for a in ir['actions']} for cid,ir in models.items()}
    possible=[{'Source':{'on':False},'Mirror':{'on':False}}]
    allowed_steps=[]
    for opcode,desired in seq:
        next_states={}; allowed=set()
        for pre in possible:
            if opcode==0:
                succ_a,_=_successors(models['Source'],actions['Source']['set'],pre['Source'],{'desired':bool(desired)},max_checks=10000)
                succ_b,_=_successors(models['Mirror'],actions['Mirror']['set'],pre['Mirror'],{'desired':bool(desired)},max_checks=10000)
                choices=(({'Source':sa,'Mirror':sb},int(ra)) for sa,ra in succ_a for sb,rb in succ_b if ra==rb)
            else:
                cid='Source' if opcode==1 else 'Mirror'
                succ,_=_successors(models[cid],actions[cid]['peek'],pre[cid],{},max_checks=10000)
                choices=((dict(pre,**{cid:after}),int(result)) for after,result in succ)
            for post,res in choices:
                obs=(int(post['Source']['on']),int(post['Mirror']['on']),res)
                # This tests a state-exposing adapter; its observation is STRONGER than public trace semantics.
                allowed.add(obs)
                next_states[(obs[0],obs[1])]=post
        if not next_states: raise AxError('E_TRACE_MODEL','abstract schedule has no successor')
        allowed_steps.append(allowed)
        possible=list(next_states.values())
    return allowed_steps


def _input_data(seqs):
    lines=[str(len(seqs))]
    for seq in seqs:
        lines.append(f'0 0 {len(seq)}')
        lines.extend(f'{code} {value}' for code,value in seq)
    return ('\n'.join(lines)+'\n').encode()


def _compare_output(raw,seqs,models,bound):
    lines=raw.splitlines()
    n_expected=sum(map(len,seqs))
    if len(lines)!=n_expected:
        return {'reason':'E_TRACE_OUTPUT_COUNT','expected':n_expected,'actual':len(lines)}
    idx=0
    for si,seq in enumerate(seqs):
        # Track all reachable states consistent with *observed prior steps* to avoid
        # accepting a trace whose individual steps have incompatible nondeterministic paths.
        possible=[{'Source':{'on':False},'Mirror':{'on':False}}]
        actions={cid:{a['name']:a for a in ir['actions']} for cid,ir in models.items()}
        for step,(opcode,desired) in enumerate(seq):
            line=lines[idx];idx+=1
            if not re.fullmatch(r'\s*[01]\s+[01]\s+[01]\s*',line):
                return {'reason':'E_TRACE_FORMAT','scenario':si,'step':step,'line':line[:100]}
            observed=tuple(map(int,line.split()))
            following=[]
            for pre in possible:
                if opcode==0:
                    lhs,_=_successors(models['Source'],actions['Source']['set'],pre['Source'],{'desired':bool(desired)},max_checks=10000)
                    rhs,_=_successors(models['Mirror'],actions['Mirror']['set'],pre['Mirror'],{'desired':bool(desired)},max_checks=10000)
                    candidates=(({'Source':l,'Mirror':r},int(lo)) for l,lo in lhs for r,ro in rhs if lo==ro)
                else:
                    cid='Source' if opcode==1 else 'Mirror'
                    options,_=_successors(models[cid],actions[cid]['peek'],pre[cid],{},max_checks=10000)
                    candidates=((dict(pre,**{cid:a}),int(o)) for a,o in options)
                for nxt,res in candidates:
                    if (int(nxt['Source']['on']),int(nxt['Mirror']['on']),res)==observed:
                        following.append(nxt)
            if not following:
                return {'reason':'E_TRACE_REFINEMENT_MISMATCH','scenario':si,'step':step,
                        'schedule':[list(x) for x in seq],'observed':list(observed)}
            possible=following
    return None


def verify_cpp_trace(models,bound,candidate,*,depth=4,timeout_s=30):
    check_abi(models,bound)
    source=Path(candidate)
    if source.is_symlink() or not source.is_file() or source.suffix!='.cpp':
        raise AxError('E_TRACE_SOURCE','regular .cpp required')
    raw=source.read_bytes()
    if len(raw)>200_000: raise AxError('E_TRACE_SOURCE','candidate too large')
    if b'\x00' in raw:raise AxError('E_TRACE_SOURCE','NUL byte')
    from .sandbox import MAX_INPUT
    if not available():
        return {'outcome':'Unknown','reason':'E_NAMESPACE_UNAVAILABLE','scope':{'isolation':'unavailable'}}
    abstract=verify_interleaving(models,bound)
    if abstract['outcome']!='Bounded':
        return {'outcome':'Unknown','reason':'E_TRACE_ABSTRACT_NOT_VERIFIED','abstract':abstract['outcome']}
    seqs=schedules(depth)
    input_bytes=_input_data(seqs)
    if len(input_bytes)>MAX_INPUT:raise AxError('E_TRACE_LIMIT','input too large')
    scope={'target':'two-bool-component-cpp-observational-trace','depth':depth,
           'scenarios':len(seqs),'observations':sum(map(len,seqs)),
           'scheduler':'deterministic-enumeration-of-atomic-operation-sequences',
           'execution_isolation':'experimental-linux-user-mount-net-pid-chroot',
           'security_warning':'not a production-grade arbitrary-code sandbox',
           'not_formal_refinement_proof':True,'not_thread_level_concurrency':True,
           'not_production_release':True}
    report={'schema':TRACE_VERSION,'outcome':'Unknown','reason':'NOT_EXECUTED',
            'subject_digest':digest(raw),'manifest_digest':digest(bound),
            'model_digests':{cid:digest(ir) for cid,ir in models.items()},
            'harness_digest':digest(HARNESS.encode()),'scope':scope,'variants':{},'counterexample':None}
    for mode in ('normal','ubsan'):
        flags=COMMON+(['-fsanitize=undefined','-fno-sanitize-recover=all'] if mode=='ubsan' else [])
        build=execute({'candidate.cpp':raw,'harness.cpp':HARNESS.encode()},
              ['/usr/bin/g++',*flags,'/work/harness.cpp','-o','/work/a.out'],
              timeout_s=min(90,max(20,timeout_s)),output_file='a.out')
        report['variants'][mode]={'compile_exit':build.get('exit'),'compile_status':build.get('status'),
                                   'compile_stderr':build.get('stderr','')[-1000:], 'flags':flags}
        if build.get('status')!='Finished' or build.get('exit')!=0 or build.get('output') is None:
            report['reason']='E_TRACE_BUILD';return report
        binary=build['output'];report['variants'][mode]['binary_digest']=digest(binary)
        ran=execute({'a.out':binary},['/work/a.out'],input_data=input_bytes,timeout_s=timeout_s)
        report['variants'][mode].update({'run_status':ran.get('status'),'run_exit':ran.get('exit'),
                    'stderr':ran.get('stderr','')[-1000:],'stdout_digest':digest(ran.get('stdout','').encode())})
        if ran.get('status')!='Finished' or ran.get('exit') is None:
            report['reason']='E_TRACE_RUNTIME_UNKNOWN';return report
        if ran['exit']!=0:
            report['outcome']='Violated';report['reason']='E_TRACE_CRASH_OR_SANITIZER'
            report['counterexample']={'mode':mode,'exit':ran['exit'],'stderr':ran.get('stderr','')[-1000:]}
            return report
        if len(ran['stdout'].encode())>=1_000_000:
            report['reason']='E_TRACE_OUTPUT_TRUNCATED';return report
        bad=_compare_output(ran['stdout'],seqs,models,bound)
        if bad:
            report['outcome']='Violated';report['reason']=bad['reason']
            report['counterexample']={'mode':mode,**bad};return report
    report['outcome']='Tested';report['reason']='P2E_FINITE_TRACE_AND_UBSAN_PASS'
    return report
