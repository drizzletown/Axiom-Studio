"""P1 real C++ compilation and observed finite-input differential checking.

NOT a C++ proof or secure untrusted-code sandbox. One translation unit, single pure
transition function, finite synchronous observations only. Target restrictions
are validated and recorded. Compiler/test logs are retained as evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time

from .checker import verify
from .lang import AxError, assignments, canonical_bytes, digest, domain, evaluate, validate

BINDING_VERSION='ax-cpp-binding/0.1'
RUNNER_VERSION='ax-p1-cpp-runner/0.1'
POLICY_VERSION='ax-p1-cpp-gate/0.1'
COMMON=['-std=c++20', '-Wall','-Wextra','-Werror','-pedantic','-g','-fno-omit-frame-pointer']
SAN_FLAGS=['-fsanitize=address,undefined','-fno-sanitize-recover=all']


def _file_hash(path):
    return digest(Path(path).read_bytes())


def compiler_context(compiler='g++', optimization='1'):
    if optimization not in ('0','1','2'): raise AxError('E_CPP_CONFIG','invalid optimization')
    resolved=shutil.which(compiler)
    if resolved is None: raise AxError('E_CPP_COMPILER',compiler)
    path=str(Path(resolved).resolve())
    try:
        result=subprocess.run([path,'--version'],capture_output=True,text=True,timeout=5)
        target=subprocess.run([path,'-dumpmachine'],capture_output=True,text=True,timeout=5)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise AxError('E_CPP_COMPILER',str(exc)) from exc
    if result.returncode!=0 or target.returncode!=0:
        raise AxError('E_CPP_COMPILER','toolchain query failed')
    return {'compiler':path,'compiler_hash':_file_hash(path),'compiler_version':result.stdout.splitlines()[0],
            'target':target.stdout.strip(),'common_flags':COMMON+['-O'+optimization],
            'sanitizer_flags':SAN_FLAGS,'runner_version':RUNNER_VERSION,
            'binding_version':BINDING_VERSION}


def load_binding(path,ir):
    b=json.loads(Path(path).read_text(encoding='utf-8'))
    # Strict support boundary. No guessing a mapping for other models.
    required={'binding_schema','model','action','entrypoint','protocol','state_map','input_map','output_map',
              'assumptions','known_gaps'}
    if set(b)!=required: raise AxError('E_CPP_BINDING','missing/unknown binding keys')
    if b['binding_schema']!=BINDING_VERSION or b['model']!=ir['model']:
        raise AxError('E_CPP_BINDING','schema or model mismatch')
    if b['protocol']!='ax-line-i64-bool/1' or b['action']!='move' or b['entrypoint']!='axiom_move':
        raise AxError('E_CPP_BINDING','P1 supports move/axiom_move only')
    if len(ir['actions'])!=1 or ir['actions'][0]['name']!='move' or ir['actions'][0]['output']!='Bool':
        raise AxError('E_CPP_UNSUPPORTED','P1 supports one move action returning Bool')
    if list(ir['state'])!=['a','b'] or list(ir['actions'][0]['inputs'])!=['m']:
        raise AxError('E_CPP_UNSUPPORTED','P1 two accounts plus m only')
    if ir['observe']!=['move.input','move.output'] and set(ir['observe'])!={'move.input','move.output'}:
        raise AxError('E_CPP_UNSUPPORTED','P1 cannot project hidden events')
    types={'Bool':{'kind':'Bool'},**ir['types']}
    if any(types[t]['kind']!='Int' for t in [*ir['state'].values(),*ir['actions'][0]['inputs'].values()]):
        raise AxError('E_CPP_UNSUPPORTED','only finite integer fields')
    for t in [*ir['state'].values(),*ir['actions'][0]['inputs'].values()]:
        ty=types[t]
        if ty['min'] < -(2**63) or ty['max'] > 2**63-1:
            raise AxError('E_CPP_RANGE','not representable as int64')
    if set(b['state_map'])!={'a','b'} or set(b['state_map'].values())!={'a','b'} or len(set(b['state_map'].values()))!=2:
        raise AxError('E_CPP_BINDING','state mapping must be bijective a,b')
    if b['input_map']!={'m':'m'} or b['output_map']!='success':
        raise AxError('E_CPP_BINDING','input/output bindings unsupported')
    if not isinstance(b['assumptions'],list) or not isinstance(b['known_gaps'],list):
        raise AxError('E_CPP_BINDING','assumptions/gaps should be lists')
    return b


def _harness(binding):
    a,b=binding['state_map']['a'],binding['state_map']['b']
    # No interpolation of free-form identifiers: both names are strictly validated.
    return r'''#include <cstdint>
#include <iostream>
#include <limits>
struct AxMove { std::int64_t a; std::int64_t b; bool success; };
#include "candidate.cpp"
int main() {
    std::int64_t a,b,m;
    while (std::cin >> a >> b >> m) {
        AxMove out = axiom_move(a,b,m);
        std::cout << out.''' + a + ' << " " << out.' + b + ''' << " " << (out.success ? 1 : 0) << "\\n";
    }
    if (!std::cin.eof()) return 33;
    return 0;
}
'''.replace('"\\\\n"','"\\n"')


def _cases(ir, *, limit=10000):
    """Reconstruct all model-reachable state/input pairs with a relational oracle."""
    checked=verify(ir,max_states=50000,max_transitions=250000,timeout_s=30)
    if checked['outcome']!='Bounded' or not checked['scope'].get('finite_reachable_exhaustion'):
        raise AxError('E_CPP_MODEL','model has no qualifying finite verification: '+str(checked['reason']))
    types={'Bool':{'kind':'Bool'},**ir['types']}
    action=ir['actions'][0]
    queue=[]; visited=set(); names=list(ir['state'])
    for state in assignments(ir['state'],types):
        if evaluate(ir['init'],state):
            k=tuple(state[n] for n in names)
            if k not in visited:visited.add(k);queue.append(state)
    cases=[]
    for state in queue:
        for inp in assignments(action['inputs'],types):
            matches=[c for c in action['cases'] if not c.get('default') and evaluate(c['guard'],state,inp)]
            if not matches:matches=[c for c in action['cases'] if c.get('default')]
            if len(matches)!=1: raise AxError('E_CPP_MODEL','ambiguous/absent branch')
            case=matches[0]
            allowed=[]
            changes={n:ir['state'][n] for n in case['modifies']}
            for delta in assignments(changes,types):
                after={**state,**delta}
                for result in domain(types[action['output']]):
                    if evaluate(case['ensures'],state,inp,after=after,result=result):
                        allowed.append((after,result))
                        key=tuple(after[n] for n in names)
                        if key not in visited: visited.add(key);queue.append(after)
            if not allowed: raise AxError('E_CPP_MODEL','no abstract successor')
            cases.append({'state':state,'input':inp,'allowed':allowed})
            if len(cases)>limit:raise AxError('E_CPP_LIMIT','too many test pairs')
    return cases,checked


def _run_process(argv, *, input_text=None, cwd=None, timeout_s=15, memory_mb=2048):
    """Bounded-output process supervision; mitigations, NOT an isolation sandbox.

    Capture to capped regular files rather than unbounded subprocess pipes.
    Start a fresh process group and kill descendants when a timeout occurs.
    """
    def limits():
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_CPU,(max(1,int(timeout_s)+1),max(2,int(timeout_s)+2)))
            resource.setrlimit(resource.RLIMIT_CORE,(0,0))
            resource.setrlimit(resource.RLIMIT_FSIZE,(1<<20,1<<20))
            resource.setrlimit(resource.RLIMIT_NOFILE,(64,64))
            # Sanitizers reserve huge virtual memory: don't impose RLIMIT_AS.
        except (ImportError,OSError,ValueError):pass
    with tempfile.TemporaryFile(mode='w+b') as stdout, tempfile.TemporaryFile(mode='w+b') as stderr:
        try:
            proc=subprocess.Popen(argv,stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
                                  stdout=stdout,stderr=stderr,cwd=cwd,
                                  start_new_session=(os.name=='posix'),
                                  env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'LC_ALL':'C'},
                                  preexec_fn=limits if os.name=='posix' else None)
            timed_out=False
            try:
                proc.communicate(input=input_text.encode() if input_text is not None else None,timeout=timeout_s)
            except subprocess.TimeoutExpired:
                timed_out=True
                try:
                    if os.name=='posix':os.killpg(proc.pid,signal.SIGKILL)
                    else:proc.kill()
                except ProcessLookupError:pass
                proc.communicate()
            stdout.seek(0);stderr.seek(0)
            return {'returncode':proc.returncode if not timed_out else None,
                    'stdout':stdout.read(100000).decode('utf-8',errors='replace'),
                    'stderr':stderr.read(100000).decode('utf-8',errors='replace'),
                    'timed_out':timed_out}
        except OSError as exc:
            return {'returncode':None,'stdout':'','stderr':str(exc),'timed_out':False}


def _parse_output(raw,rows):
    parts=raw.splitlines()
    if len(parts)!=len(rows):return {'reason':'E_CPP_OUTPUT_COUNT','expected':len(rows),'observed':len(parts)}
    parsed=[]
    for i,line in enumerate(parts):
        fields=line.split()
        if len(fields)!=3 or not all(re.fullmatch(r'-?[0-9]+',x) for x in fields):
            return {'reason':'E_CPP_OUTPUT_FORMAT','case':i,'output':line[:150]}
        a,b,r=(int(x) for x in fields)
        if r not in (0,1) or not all(-(2**63)<=x<=2**63-1 for x in (a,b)):
            return {'reason':'E_CPP_OUTPUT_TYPE','case':i,'output':line}
        actual=({'a':a,'b':b},bool(r))
        allowed=rows[i]['allowed']
        if actual not in allowed:
            return {'reason':'E_CPP_REFINEMENT_MISMATCH','case':i,'state':rows[i]['state'],
                    'input':rows[i]['input'],'actual':{'state':actual[0],'result':actual[1]},
                    'allowed':[{'state':s,'result':v} for s,v in allowed]}
        parsed.append(actual)
    return None


def run_cpp(ir, candidate, binding_path, *, compiler='g++',optimization='1',timeout_s=15):
    """Produce actual runner/compile/test report and artifacts, no database writes."""
    validate(ir)
    binding=load_binding(binding_path,ir)
    candidate=Path(candidate)
    if candidate.is_symlink() or not candidate.is_file() or candidate.suffix!='.cpp':
        raise AxError('E_CPP_SOURCE','regular .cpp file required (no symbolic links)')
    src=candidate.read_bytes()
    if len(src)>200000: raise AxError('E_CPP_SOURCE','candidate too large for P1')
    if re.search(rb'^\s*#\s*include\s*"',src,re.MULTILINE):
        raise AxError('E_CPP_SOURCE','P1 forbids local quoted includes outside trusted harness')
    context=compiler_context(compiler,optimization)
    harness=_harness(binding)
    config_digest=digest(context)
    cases,model_report=_cases(ir)
    replay_cases=cases+list(reversed(cases))
    inputs=''.join(f"{c['state']['a']} {c['state']['b']} {c['input']['m']}\n" for c in replay_cases)
    summary={'runner_version':RUNNER_VERSION,'model_digest':digest(ir),
             'source_digest':digest(src),'binding_digest':digest(binding),
             'config_digest':config_digest,'harness_digest':digest(harness.encode()),
             'model_outcome':model_report['outcome'],'scope':{
                 'model':ir['model'],'action':'move','tested_pairs':len(cases),
                 'all_model_reachable_state_input_pairs':True,
                 'observed_calls_per_variant':len(replay_cases),
                 'each_model_pair_repeated':True,
                 'only_fixed_order_synchronous_observations':True,
                 'no_concurrency':True,'no_persistence':True,'no_arbitrary_cpp_correctness_proof':True,
                 'execution_is_not_securely_sandboxed':True,
                 'process_group_timeout_kill':True, 'output_capture_max_bytes':100000,
                 'input_trust_requirement':'trusted-local-only'},
             'assumptions':binding['assumptions'],'known_gaps':binding['known_gaps'],
             'variants':{},'outcome':'Unknown','reason':'NOT_EXECUTED','counterexample':None}
    artifacts={'source':src,'binding':canonical_bytes(binding),
               'harness':harness.encode('utf-8'),'context':canonical_bytes(context)}
    with tempfile.TemporaryDirectory(prefix='axiom-cpp-') as td:
        td=Path(td)
        (td/'candidate.cpp').write_bytes(src)
        (td/'harness.cpp').write_text(harness)
        binaries={}
        for mode in ('normal','sanitized'):
            out=td/('binary-'+mode)
            flags=context['common_flags']+(SAN_FLAGS if mode=='sanitized' else [])
            command=[context['compiler'],*flags,str(td/'harness.cpp'),'-o',str(out)]
            built=_run_process(command,cwd=td,timeout_s=45)
            variant={'compiler_exit':built['returncode'],'compile_log':built['stderr'],
                     'compile_stdout':built['stdout'],'compile_timeout':built['timed_out'],
                     'flags':flags,'binary_digest':_file_hash(out) if out.exists() and built['returncode']==0 else None}
            summary['variants'][mode]=variant
            if built['returncode']!=0 or built['timed_out']:
                summary['reason']='E_CPP_BUILD';return summary,{**artifacts,**binaries}
            binaries[mode]=out.read_bytes()
            ran=_run_process([str(out)],input_text=inputs,cwd=td,timeout_s=timeout_s)
            variant['execution_exit']=ran['returncode']
            variant['runtime_stderr']=ran['stderr']
            variant['runtime_stdout_digest']=digest(ran['stdout'].encode())
            variant['execution_timeout']=ran['timed_out']
            if ran['timed_out']:
                summary['reason']='E_CPP_TIMEOUT';return summary,{**artifacts,**binaries}
            if ran['returncode']!=0:
                summary['outcome']='Violated' if ran['returncode'] is not None else 'Unknown'
                summary['reason']='E_CPP_SANITIZER_OR_CRASH' if mode=='sanitized' else 'E_CPP_RUNTIME'
                summary['counterexample']={'mode':mode,'stderr':ran['stderr'][-4000:]}
                return summary,{**artifacts,**binaries}
            mismatch=_parse_output(ran['stdout'],replay_cases)
            if mismatch:
                summary['outcome']='Violated'
                summary['reason']=mismatch['reason']
                summary['counterexample']={'mode':mode,**mismatch}
                return summary,{**artifacts,**binaries}
        summary['outcome']='Tested'
        summary['reason']='P1_FINITE_TRANSITION_DIFFERENTIAL_AND_SANITIZERS_PASS'
    return summary,{**artifacts,**binaries}
