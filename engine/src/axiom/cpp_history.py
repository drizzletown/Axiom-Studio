"""P2f: observed *native-thread* C++ histories vs Axiom's atomic API semantics.

A completed history is linearizable iff there is a sequential order preserving
real-time precedence of nonoverlapping calls, the return values agree with
abstract transitions, and the final state matches the exposed snapshot.
Observed executions only: no exhaustive native interleaving or memory-model proof.
"""
from __future__ import annotations
import json
from pathlib import Path
import re
from .lang import AxError, digest
from .cpp_trace import check_abi
from .interleaving import verify_interleaving
from .product import _successors
from .sandbox import available, execute, MAX_INPUT, MAX_OUTPUT

HISTORY_VERSION = 'ax-cpp-thread-history/0.1'
ABI_VERSION = 'ax-cpp-history-abi/0.1'
COMMON = ['-std=c++20','-pthread','-Wall','-Wextra','-Werror','-pedantic','-O1','-fno-omit-frame-pointer']

# Unlike P2e, the C++ ABI returns no internal state at each operation boundary;
# the linearizability oracle sees only externally visible operation I/O and one
# optional final state snapshot, after all concurrent calls have completed.
HARNESS = r'''#include <atomic>
#include <iostream>
#include <thread>
#include <vector>
#include <array>
#include <cstdint>
extern "C" void axiom_reset(int left, int right);
extern "C" int axiom_call(int opcode, int desired);
extern "C" void axiom_snapshot(int* left, int* right);
#include "candidate.cpp"
struct Op { int opcode, desired; };
struct Log { int worker, slot, opcode, desired, begin, end, result; };
int main() {
    int trials;
    if (!(std::cin >> trials) || trials < 0 || trials > 200) return 40;
    for(int trial=0; trial<trials; ++trial) {
        int n0,n1;
        if (!(std::cin >> n0 >> n1) || n0<1 || n1<1 || n0>3 || n1>3) return 41;
        std::array<std::vector<Op>,2> work;
        for(int t=0;t<2;++t) for(int j=0;j<(t==0?n0:n1);++j) {
            Op op;
            if(!(std::cin >> op.opcode >> op.desired)) return 42;
            if(op.opcode<0 || op.opcode>2 || op.desired<0 || op.desired>1) return 43;
            work[t].push_back(op);
        }
        axiom_reset(0,0);
        std::atomic<int> ready{0},clock{0};
        std::atomic<bool> go{false};
        std::array<std::vector<Log>,2> logs;
        auto worker=[&](int t) {
            ready.fetch_add(1,std::memory_order_seq_cst);
            while (!go.load(std::memory_order_seq_cst)) std::this_thread::yield();
            for (int j=0;j<(int)work[t].size();++j) {
                const Op& op=work[t][j];
                int begin=clock.fetch_add(1,std::memory_order_seq_cst);
                int result=axiom_call(op.opcode,op.desired);
                int end=clock.fetch_add(1,std::memory_order_seq_cst);
                logs[t].push_back(Log{t,j,op.opcode,op.desired,begin,end,result});
            }
        };
        std::thread a(worker,0), b(worker,1);
        while(ready.load(std::memory_order_seq_cst)!=2) std::this_thread::yield();
        go.store(true,std::memory_order_seq_cst);
        a.join();b.join();
        int left=0,right=0;
        axiom_snapshot(&left,&right);
        std::cout << "H " << trial << ' ' << (n0+n1) << ' ' << left << ' ' << right << '\n';
        for(int t=0;t<2;++t) for(auto r:logs[t])
            std::cout << "O " << r.worker << ' ' << r.slot << ' ' << r.opcode
             << ' ' << r.desired << ' ' << r.begin << ' ' << r.end << ' ' << r.result << '\n';
    }
    std::cin >> std::ws;
    return std::cin.eof()?0:44;
}
'''

# All experiments start with false/false. More patterns could be added only after
# changing the versioned checker and gate scope.
PATTERNS = (
    (((0,1),), ((0,0),)),
    (((0,0),), ((0,1),)),
    (((0,1),(1,0)), ((0,0),(2,0))),
    (((0,0),(2,0)), ((0,1),(1,0))),
    (((0,1),(0,0)), ((0,0),(0,1))),
    (((1,0),(2,0)), ((0,1),(2,0))),
)

def trials(repeats):
    if type(repeats) is not int or repeats < 1 or repeats > 16:
        raise AxError('E_HISTORY_SCOPE','repeats must be between 1 and 16')
    # Reverse the order at the end to expose persistence across resets.
    first=list(PATTERNS)*repeats
    return first + list(reversed(first))

def _payload(items):
    lines=[str(len(items))]
    for a,b in items:
        lines.append(f'{len(a)} {len(b)}')
        lines.extend(f'{op} {desired}' for op,desired in (*a,*b))
    return ('\n'.join(lines)+'\n').encode()

HLINE=re.compile(r'^H (\d+) ([2-6]) ([01]) ([01])$')
OLINE=re.compile(r'^O ([01]) ([0-2]) ([012]) ([01]) (\d+) (\d+) ([01])$')

def parse_history(raw, scenarios):
    """Strictly parse and bind each observed C++ event to its requested input."""
    lines=raw.splitlines();at=0;out=[]
    for scenario_idx,(a,b) in enumerate(scenarios):
        if at >= len(lines):raise ValueError('missing trial header')
        m=HLINE.fullmatch(lines[at]);at+=1
        if not m:raise ValueError('invalid trial header')
        number,n,left,right=map(int,m.groups())
        if number!=scenario_idx or n!=len(a)+len(b):raise ValueError('trial mismatch')
        ops=[];clock_values=[]
        for _ in range(n):
            if at>=len(lines):raise ValueError('missing event')
            m=OLINE.fullmatch(lines[at]);at+=1
            if not m:raise ValueError('invalid operation event')
            worker,slot,opcode,desired,start,finish,result=map(int,m.groups())
            expected=(a,b)[worker]
            if slot>=len(expected) or (opcode,desired)!=expected[slot]:
                raise ValueError('history operation does not match trial input')
            if finish<=start or start>100 or finish>100:
                raise ValueError('invalid history clock')
            if any(o['worker']==worker and o['slot']==slot for o in ops):
                raise ValueError('duplicate operation')
            ops.append({'worker':worker,'slot':slot,'opcode':opcode,'desired':desired,
                        'start':start,'finish':finish,'result':result})
            clock_values.extend((start,finish))
        if sorted(clock_values)!=list(range(2*n)):
            raise ValueError('event timestamps are not a permutation')
        # A worker must observe program order, including non-overlapping calls.
        for worker,expected in enumerate((a,b)):
            w=sorted((o for o in ops if o['worker']==worker),key=lambda o:o['slot'])
            if len(w)!=len(expected) or any(w[i]['finish']>=w[i+1]['start'] for i in range(len(w)-1)):
                raise ValueError('broken per-worker ordering')
        out.append({'ops':ops,'final':(left,right)})
    if at != len(lines):raise ValueError('unexpected trailing output')
    return out


def _step(models,state,op):
    """Generate true abstract successors, not a duplicated hardcoded oracle."""
    cid='Source' if op['opcode']==1 else 'Mirror' if op['opcode']==2 else None
    acts={c:{a['name']:a for a in ir['actions']} for c,ir in models.items()}
    if cid is None:
        choices_left,_=_successors(models['Source'],acts['Source']['set'],state['Source'],
                                  {'desired':bool(op['desired'])},max_checks=10000)
        choices_right,_=_successors(models['Mirror'],acts['Mirror']['set'],state['Mirror'],
                                   {'desired':bool(op['desired'])},max_checks=10000)
        return [({'Source':l,'Mirror':r},int(lo)) for l,lo in choices_left for r,ro in choices_right if lo==ro]
    choices,_=_successors(models[cid],acts[cid]['peek'],state[cid],{},max_checks=10000)
    return [(dict(state,**{cid:after}),int(result)) for after,result in choices]


def linearizable(models, observed, *, max_nodes=30000):
    """Backtracking finite checker respecting interval real-time precedence.

    Returns (decision, witness_order). No linearization claims beyond provided
    completed operations and optional trusted final-state adapter snapshot.
    """
    ops=observed['ops'];n=len(ops)
    if n>6:return None,[]
    predecessors=[]
    for j,op in enumerate(ops):
        predecessors.append(sum(1<<i for i,o in enumerate(ops) if i!=j and o['finish']<op['start']))
    start_state={'Source':{'on':False},'Mirror':{'on':False}}
    seen=set();count=0
    def walk(mask,state,order):
        nonlocal count
        count+=1
        if count>max_nodes:raise OverflowError('search budget exceeded')
        signature=(mask,bool(state['Source']['on']),bool(state['Mirror']['on']))
        if signature in seen:return None
        if mask==(1<<n)-1:
            return order if (int(state['Source']['on']),int(state['Mirror']['on']))==observed['final'] else None
        seen.add(signature)
        for i,op in enumerate(ops):
            if mask & (1<<i) or predecessors[i]&~mask:continue
            for next_state,out in _step(models,state,op):
                if out==op['result']:
                    witness=walk(mask|(1<<i),next_state,order+[i])
                    if witness is not None:return witness
        return None
    try:found=walk(0,start_state,[])
    except OverflowError:return None,[]
    return (found is not None),found or []


def verify_cpp_history(models,bound,candidate,*,repeats=8,timeout_s=25):
    check_abi(models,bound)
    source=Path(candidate)
    if source.is_symlink() or not source.is_file() or source.suffix!='.cpp':
        raise AxError('E_HISTORY_SOURCE','regular .cpp file required')
    raw=source.read_bytes()
    if len(raw)>200_000 or b'\0' in raw:raise AxError('E_HISTORY_SOURCE','invalid candidate size or NUL')
    scenarios=trials(repeats)
    input_bytes=_payload(scenarios)
    if len(input_bytes)>MAX_INPUT:raise AxError('E_HISTORY_INPUT','test input too large')
    scope={'target':'native-thread-cpp-finite-observed-linearizability',
           'scheduling':'two-real-std-threads-simultaneous-start',
           'trials':len(scenarios),'total_operations':sum(len(a)+len(b) for a,b in scenarios),
           'patterns':len(PATTERNS),'repeats':repeats,'oracle':'axiom-synchronized-set-and-independent-peek',
           'observes':'public-return-values-plus-post-quiescence-snapshot',
           'not_exhaustive_native_schedules':True,'not_formal_refinement_proof':True,
           'not_thread_sanitized':True,'not_production_release':True,
           'sandbox':'experimental-rootless-linux-namespaces'}
    report={'schema':HISTORY_VERSION,'outcome':'Unknown','reason':'NOT_EXECUTED',
            'subject_digest':digest(raw),'manifest_digest':digest(bound),
            'model_digests':{cid:digest(ir) for cid,ir in models.items()},
            'harness_digest':digest(HARNESS.encode()),'scope':scope,'variants':{},'counterexample':None}
    if not available():report['reason']='E_NAMESPACE_UNAVAILABLE';return report
    abstract=verify_interleaving(models,bound)
    if abstract['outcome']!='Bounded':
        report['reason']='E_ABSTRACT_NOT_VERIFIED';return report
    for mode in ('normal','ubsan'):
        flags=COMMON+(['-fsanitize=undefined','-fno-sanitize-recover=all'] if mode=='ubsan' else [])
        build=execute({'candidate.cpp':raw,'harness.cpp':HARNESS.encode()},
          ['/usr/bin/g++',*flags,'/work/harness.cpp','-o','/work/a.out'],timeout_s=80,output_file='a.out')
        variant={'flags':flags,'compile_status':build.get('status'),
                 'compile_exit':build.get('exit'),'compile_stderr':build.get('stderr','')[-1500:]}
        report['variants'][mode]=variant
        if build.get('status')!='Finished' or build.get('exit')!=0 or build.get('output') is None:
            report['reason']='E_HISTORY_BUILD';return report
        binary=build['output'];variant['binary_digest']=digest(binary)
        ran=execute({'a.out':binary},['/work/a.out'],input_data=input_bytes,timeout_s=timeout_s)
        variant.update({'run_status':ran.get('status'),'run_exit':ran.get('exit'),
                        'stdout_digest':digest(ran.get('stdout','').encode()),
                        'stderr':ran.get('stderr','')[-1500:],
                        'stdout_truncated':ran.get('stdout_truncated'),
                        'stderr_truncated':ran.get('stderr_truncated')})
        if ran.get('status')!='Finished' or ran.get('stdout_truncated') or ran.get('stderr_truncated'):
            report['reason']='E_HISTORY_RUNTIME_UNKNOWN';return report
        if ran.get('exit')!=0:
            report.update({'outcome':'Violated','reason':'E_HISTORY_CRASH_OR_UBSAN',
              'counterexample':{'mode':mode,'exit':ran.get('exit'),'stderr':ran.get('stderr','')[-900:]}})
            return report
        try:histories=parse_history(ran.get('stdout',''),scenarios)
        except (ValueError,TypeError) as exc:
            report.update({'outcome':'Violated','reason':'E_HISTORY_PROTOCOL',
                           'counterexample':{'mode':mode,'detail':str(exc)[:200]}})
            return report
        for i,h in enumerate(histories):
            try:good,witness=linearizable(models,h)
            except AxError as exc:
                report['reason']='E_HISTORY_ORACLE';report['detail']=exc.code;return report
            if good is None:report['reason']='E_HISTORY_SEARCH_BUDGET';return report
            if not good:
                report.update({'outcome':'Violated','reason':'E_HISTORY_NOT_LINEARIZABLE',
                    'counterexample':{'mode':mode,'trial':i,'requested':scenarios[i],
                     'history':h,'note':'no total order respecting real-time and Axiom API behavior'}})
                return report
        variant['checked_histories']=len(histories)
    report.update({'outcome':'Tested','reason':'FINITE_OBSERVED_NATIVE_THREAD_HISTORIES_PASS'})
    return report
