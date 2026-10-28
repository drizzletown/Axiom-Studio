"""P2g: seeded schedule perturbation + C++ ThreadSanitizer for bounded histories.

The outcome Tested means only these particular executions matched the abstract
oracle and TSAN emitted no finding.  It is not a proof of race freedom, sequential
consistency for arbitrary executions, or general C++ refinement.
"""
from __future__ import annotations
from collections import Counter
from pathlib import Path
from .lang import AxError, digest
from .cpp_history import HARNESS, COMMON, parse_history, linearizable, check_abi, trials
from .interleaving import verify_interleaving
from .sandbox import available, execute, MAX_INPUT

SCHEMA = 'ax-cpp-stress/0.1'
ABI = 'ax-cpp-history-abi/0.1'
STRESS_INSERT = r'''
#include <chrono>
static void perturb(unsigned seed,int trial,int worker,int slot,int phase) {
    unsigned x=seed ^ (unsigned(trial+1)*747796405u)
        ^ (unsigned(worker+1)*2891336453u)
        ^ (unsigned(slot+1)*277803737u)
        ^ (unsigned(phase+1)*0x9e3779b9u);
    x^=x>>16;x*=0x7feb352du;x^=x>>15;
    switch(x%4u) {
      case 0: std::this_thread::yield();break;
      case 1: std::this_thread::sleep_for(std::chrono::microseconds(10u+x%70u));break;
      case 2: {
          for(unsigned k=0;k<48u+x%64u;++k) {
            std::atomic_signal_fence(std::memory_order_seq_cst);
          }
          break;
      }
      default: break;
    }
}
'''

def make_harness():
    original=HARNESS
    markers=(
        ('#include <cstdint>', '#include <cstdint>\n'+STRESS_INSERT),
        ('if (!(std::cin >> n0 >> n1) || n0<1 || n1<1 || n0>3 || n1>3)',
         'unsigned seed;\n        if (!(std::cin >> n0 >> n1 >> seed) || n0<1 || n1<1 || n0>3 || n1>3)'),
        ('int begin=clock.fetch_add(1,std::memory_order_seq_cst);',
         'perturb(seed,trial,t,j,0);\n                int begin=clock.fetch_add(1,std::memory_order_seq_cst);\n                perturb(seed,trial,t,j,1);'),
        ('int result=axiom_call(op.opcode,op.desired);',
         'int result=axiom_call(op.opcode,op.desired);\n                perturb(seed,trial,t,j,2);'),
    )
    for needle,replacement in markers:
        if original.count(needle)!=1:
            raise AxError('E_STRESS_HARNESS','upstream native history harness unexpectedly changed')
        original=original.replace(needle,replacement)
    return original

STRESS_HARNESS=make_harness()

def scenarios_for(repeats:int, seed:int, seed_count:int):
    if type(repeats) is not int or not 1<=repeats<=4:
        raise AxError('E_STRESS_SCOPE','repeats must be 1..4')
    if type(seed) is not int or not 0<=seed<=1_000_000:
        raise AxError('E_STRESS_SCOPE','seed must be 0..1000000')
    if type(seed_count) is not int or not 1<=seed_count<=8:
        raise AxError('E_STRESS_SCOPE','seed_count must be 1..8')
    seeded=[]
    for i in range(seed_count):
        s=(seed + i*2654435761) % (2**32)
        for pattern in trials(repeats):
            seeded.append((pattern,s))
    return seeded

def seeded_payload(scenarios):
    lines=[str(len(scenarios))]
    for ((a,b),seed) in scenarios:
        lines.append(f'{len(a)} {len(b)} {seed}')
        lines.extend(f'{op} {desired}' for op,desired in (*a,*b))
    result=('\n'.join(lines)+'\n').encode()
    if len(result)>MAX_INPUT:raise AxError('E_STRESS_INPUT','input exceeds sandbox bound')
    return result


def verify_cpp_stress(models,bound,candidate,*,repeats=1,seed=104729,seed_count=2,timeout_s=45):
    check_abi(models,bound)
    scenarios=scenarios_for(repeats,seed,seed_count)
    source=Path(candidate)
    if source.suffix!='.cpp' or source.is_symlink() or not source.is_file():
        raise AxError('E_STRESS_SOURCE','regular .cpp required')
    raw=source.read_bytes()
    if len(raw)>200_000 or b'\0' in raw:raise AxError('E_STRESS_SOURCE','bad candidate bytes')
    requested=[p for p,s in scenarios]
    input_data=seeded_payload(scenarios)
    scope={'repeats':repeats,'seed':seed,'seed_count':seed_count,
           'seed_values':[(seed+i*2654435761)%(2**32) for i in range(seed_count)],
           'trials':len(requested),'two_native_threads':True,
           'scheduling':'seeded yield/sleep/spin around operations',
           'tsan_required':True,'not_exhaustive':True,
           'not_formal_refinement_proof':True,'not_production_release':True,
           'isolation':'experimental-linux-namespaces-no-seccomp'}
    report={'schema':SCHEMA,'outcome':'Unknown','reason':'NOT_EXECUTED',
            'manifest_digest':digest(bound),'source_digest':digest(raw),
            'model_digests':{cid:digest(ir) for cid,ir in models.items()},
            'harness_digest':digest(STRESS_HARNESS.encode()),
            'scope':scope,'variants':{},'counterexample':None}
    if not available():report['reason']='E_NAMESPACE_UNAVAILABLE';return report
    if verify_interleaving(models,bound)['outcome']!='Bounded':
        report['reason']='E_ABSTRACT_NOT_VERIFIED';return report
    # Mandatory TSAN: an unsupported runtime is Unknown, never treated as a pass.
    for mode,extra in (
        ('normal',[]),
        ('ubsan',['-fsanitize=undefined','-fno-sanitize-recover=all']),
        ('tsan',['-fsanitize=thread','-fno-sanitize-recover=all']),
    ):
        flags=COMMON+extra
        build=execute({'candidate.cpp':raw,'harness.cpp':STRESS_HARNESS.encode()},
            ['/usr/bin/g++',*flags,'/work/harness.cpp','-o','/work/a.out'],
            timeout_s=80,output_file='a.out')
        item={'flags':flags,'compile_status':build.get('status'),'compile_exit':build.get('exit'),
              'compile_stderr':build.get('stderr','')[-1200:]}
        report['variants'][mode]=item
        if build.get('status')!='Finished' or build.get('exit')!=0 or build.get('output') is None:
            report['reason']='E_STRESS_COMPILER_UNAVAILABLE';return report
        binary=build['output'];item['binary_digest']=digest(binary)
        run=execute({'a.out':binary},['/work/a.out'],input_data=input_data,timeout_s=timeout_s)
        stderr=run.get('stderr','')
        item.update({'run_status':run.get('status'),'run_exit':run.get('exit'),
                     'stderr':stderr[-1600:],'stdout_digest':digest(run.get('stdout','').encode()),
                     'stdout_truncated':run.get('stdout_truncated'),
                     'stderr_truncated':run.get('stderr_truncated')})
        if run.get('status')!='Finished' or run.get('stdout_truncated') or run.get('stderr_truncated'):
            report['reason']='E_STRESS_RUNTIME_UNKNOWN';return report
        if run.get('exit')!=0:
            if mode=='tsan' and ('ThreadSanitizer: data race' in stderr or
                                 'WARNING: ThreadSanitizer' in stderr and 'data race' in stderr):
                report.update({'outcome':'Violated','reason':'E_STRESS_DATA_RACE',
                  'counterexample':{'mode':'tsan','diagnostic':stderr[-1300:]}})
            elif mode=='tsan' and ('FATAL: ThreadSanitizer' in stderr or 'unexpected memory mapping' in stderr):
                report['reason']='E_STRESS_TSAN_RUNTIME_UNAVAILABLE'
            else:
                report.update({'outcome':'Violated','reason':'E_STRESS_NONZERO_EXIT',
                   'counterexample':{'mode':mode,'exit':run.get('exit'),'stderr':stderr[-1200:]}})
            return report
        try:histories=parse_history(run.get('stdout',''),requested)
        except (ValueError,TypeError) as exc:
            report.update({'outcome':'Violated','reason':'E_STRESS_PROTOCOL',
                  'counterexample':{'mode':mode,'detail':str(exc)[:180]}})
            return report
        shape_counts=Counter()
        for i,h in enumerate(histories):
            # Record observed event ordering, distinct from seeded *requested* schedules.
            event_order=tuple((o['worker'],o['slot'],kind) for _,o,kind in sorted(
                [(o['start'],o,'begin') for o in h['ops']]+[(o['finish'],o,'end') for o in h['ops']],
                key=lambda x:x[0]))
            shape_counts[str(event_order)]+=1
            good,order=linearizable(models,h)
            if good is None:
                report['reason']='E_STRESS_SEARCH_BUDGET';return report
            if not good:
                report.update({'outcome':'Violated','reason':'E_STRESS_NONLINEARIZABLE',
                    'counterexample':{'mode':mode,'trial':i,'seed':scenarios[i][1],
                                      'observed':h,'requested':requested[i]}})
                return report
        item['checked_histories']=len(histories)
        item['distinct_event_orders']=len(shape_counts)
        item['event_order_fingerprint']=digest(sorted(shape_counts.items()))
    report.update({'outcome':'Tested','reason':'SEEDED_NATIVE_THREAD_AND_TSAN_SAMPLE_PASS'})
    return report
