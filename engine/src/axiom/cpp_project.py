"""P2h: source/ABI/scenario-bound multi-file C++ regression evidence.

Research-only: scoped tests of trusted C++ programs under experimental sandbox;
NOT arbitrary-code safety, general refinement proof or production release.
All file paths are flat, manifest-allowlisted and non-symlink files.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid
from .checker import verify
from .lang import AxError, digest, parse, validate
from .sandbox import execute, available
from .store import Workspace

SCHEMA = 'ax-cpp-project/0.1'
EVIDENCE = 'ax-cpp-project-evidence/0.1'
REPORT = 'ax-cpp-project-report/0.1'
FLAGS = ['-std=c++20', '-O1', '-Wall','-Wextra','-Werror','-pedantic','-fno-omit-frame-pointer']
MODES = ('normal','ubsan')
SAFE_NAME = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]*\.(?:cpp|hpp|ax)$')
SAFE_ID = re.compile(r'^[a-z][a-z0-9_]{0,31}$')


def module_digest():
    from . import cpp_project,sandbox,checker,lang
    return digest(b''.join(Path(m.__file__).read_bytes() for m in (cpp_project,sandbox,checker,lang)))


def compiler_identity():
    compiler = Path('/usr/bin/g++').resolve(strict=True)
    binary_hash = digest(compiler.read_bytes())
    result = subprocess.run(['/usr/bin/g++','-dumpfullversion','-dumpversion'], capture_output=True,
                            text=True, timeout=10, check=True)
    return {'binary_digest': binary_hash, 'version':result.stdout.strip(),
            'compiler_path':'/usr/bin/g++', 'platform':sys.platform}


def _get_files(project_dir, filenames):
    out={}
    for name in filenames:
        p=project_dir/name
        if p.is_symlink() or not p.is_file(): raise AxError('E_PROJECT_FILE',f'missing, symlink or non-file: {name}')
        raw=p.read_bytes()
        if len(raw)>200_000 or b'\0' in raw: raise AxError('E_PROJECT_FILE',f'unsupported file: {name}')
        out[name]=raw
    return out


def load_project(path):
    manifest_path=Path(path)
    if manifest_path.is_symlink():raise AxError('E_PROJECT_MANIFEST','no symlink manifest')
    manifest_path=manifest_path.resolve(strict=True)
    root=manifest_path.parent
    manifest=json.loads(manifest_path.read_text('utf-8'))
    if not isinstance(manifest,dict) or set(manifest)!={'schema','spec','files','tests','integration'} or manifest['schema']!=SCHEMA:
        raise AxError('E_PROJECT_SCHEMA','unsupported project schema or fields')
    names=manifest['files']
    if not isinstance(names,list) or not 1<=len(names)<=25 or len(set(names))!=len(names) or any(not isinstance(n,str) or not SAFE_NAME.fullmatch(n) or not n.endswith(('.cpp','.hpp')) for n in names):
        raise AxError('E_PROJECT_SCHEMA','unsafe/duplicate source names')
    if not isinstance(manifest['spec'],str) or not SAFE_NAME.fullmatch(manifest['spec']) or not manifest['spec'].endswith('.ax'):
        raise AxError('E_PROJECT_SCHEMA','spec must be a flat .ax filename')
    if manifest['spec'] in names:raise AxError('E_PROJECT_SCHEMA','spec cannot be a C++ source file')
    tracked={p.name for p in root.iterdir() if p.suffix in ('.cpp','.hpp')}
    if tracked!=set(names):raise AxError('E_PROJECT_UNTRACKED','unlisted C++ source or header detected')
    raw=_get_files(root,names+[manifest['spec']])
    tests=manifest['tests']
    if not isinstance(tests,list) or not 1<=len(tests)<=10:
        raise AxError('E_PROJECT_SCHEMA','1..10 tests required')
    ids=set();covered=set()
    for t in tests:
        if not isinstance(t,dict) or set(t)!={'id','files','sources','expect'} or not isinstance(t['id'],str) or not SAFE_ID.fullmatch(t['id']) or t['id'] in ids:
            raise AxError('E_PROJECT_TEST','invalid/duplicate test ID')
        ids.add(t['id'])
        f=t['files'];s=t['sources']
        if not isinstance(f,list) or not f or len(set(f))!=len(f) or not set(f).issubset(names) or not isinstance(s,list) or not s or not set(s).issubset(f) or not all(n.endswith('.cpp') for n in s):
            raise AxError('E_PROJECT_TEST','invalid declared compile sources')
        if not isinstance(t['expect'],str) or not t['expect'].startswith('PASS ') or not t['expect'].endswith('\n') or len(t['expect'])>150:
            raise AxError('E_PROJECT_TEST','invalid expected test output')
        covered.update(f)
    if covered!=set(names) or manifest['integration'] not in ids:
        raise AxError('E_PROJECT_TEST','each file must be covered; integration test required')
    return manifest,raw,validate(parse(raw[manifest['spec']].decode('utf-8')))


def _dependency_hashes(root, t, files):
    """Track compiler-reported transitive project + system header bytes.
    The compiler dependency scanner itself is in the local trust base.
    Reject undeclared local headers; no optional implicit include resolution.
    """
    dep_paths=set()
    for source in t['sources']:
        result=subprocess.run(['/usr/bin/g++',*FLAGS,'-M','-I'+str(root),source],
                              cwd=root, capture_output=True,text=True,timeout=15)
        if result.returncode or not result.stdout or result.stderr:
            raise AxError('E_PROJECT_DEP_SCAN',f'dependency scan failed: {source} {result.stderr[:200]}')
        tokens=result.stdout.replace('\\\n',' ').split(':',1)
        if len(tokens)!=2:raise AxError('E_PROJECT_DEP_SCAN','invalid compiler dependency output')
        for part in tokens[1].split():
            if '\\' in part or ':' in part:raise AxError('E_PROJECT_DEP_SCAN','unsupported dependency path')
            p=Path(part)
            if not p.is_absolute():p=root/p
            p=p.resolve(strict=True)
            if p.is_relative_to(root):
                if p.name not in t['files'] or p.parent!=root:
                    raise AxError('E_PROJECT_DEP_UNDECLARED',str(p))
            elif not (str(p).startswith('/usr/')):
                raise AxError('E_PROJECT_DEP_EXTERNAL',str(p))
            if not p.is_file():raise AxError('E_PROJECT_DEP_SCAN',str(p))
            dep_paths.add(p)
    return {str(p):digest(p.read_bytes()) for p in sorted(dep_paths)}


def _target_key(t, project_dir, raw, spec_digest, tool, compiler):
    deps=_dependency_hashes(project_dir,t,raw)
    inputs={name:digest(raw[name]) for name in t['files']}
    payload={'spec_digest':spec_digest, 'id':t['id'], 'files':inputs,
             'sources':t['sources'],'expect':t['expect'], 'flags':FLAGS,
             'modes':list(MODES),'tool_digest':tool,'compiler':compiler,'transitive_deps':deps}
    return digest(payload),payload


def _build_test(t, raw):
    scoped={name:raw[name] for name in t['files']}
    variants={}
    for mode in MODES:
        args=['/usr/bin/g++',*FLAGS]
        if mode=='ubsan':args+=['-fsanitize=undefined','-fno-sanitize-recover=all']
        args += ['/work/'+f for f in t['sources']]+['-o','/work/a.out']
        built=execute(scoped,args,timeout_s=50,output_file='a.out')
        item={'compile_status':built.get('status'),'compile_exit':built.get('exit'),
              'compile_stderr':built.get('stderr','')[-400:]}
        variants[mode]=item
        if built.get('status')!='Finished' or built.get('exit')!=0 or not built.get('output'):
            return 'Unknown',variants
        binary=built['output'];item['binary_digest']=digest(binary)
        ran=execute({'a.out':binary}, ['/work/a.out'],timeout_s=15)
        item.update({'run_status':ran.get('status'),'run_exit':ran.get('exit'),
                     'stdout_digest':digest(ran.get('stdout','').encode()),
                     'stderr':ran.get('stderr','')[-400:],
                     'stdout_truncated':ran.get('stdout_truncated'),
                     'stderr_truncated':ran.get('stderr_truncated')})
        if ran.get('status')!='Finished' or ran.get('stdout_truncated') or ran.get('stderr_truncated'):
            return 'Unknown',variants
        if ran.get('exit')!=0 or ran.get('stdout')!=t['expect'] or ran.get('stderr'):
            return 'Violated',variants
    return 'Tested',variants


def ensure_table(ws):
    with ws._db() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS cpp_project_targets (
          key TEXT PRIMARY KEY, evidence_digest TEXT NOT NULL,created_at TEXT NOT NULL)''')
        db.execute('''CREATE TABLE IF NOT EXISTS cpp_project_runs (
          run_id TEXT PRIMARY KEY, evidence_digest TEXT NOT NULL,created_at TEXT NOT NULL)''')


def run_project(ws:Workspace, manifest_path, *, reuse=True):
    start=time.perf_counter()
    manifest,raw,ir=load_project(manifest_path)
    spec_digest=digest(ir)
    abstract=verify(ir,max_states=5000,max_transitions=15000,timeout_s=10)
    compiled={'spec_digest':spec_digest,'outcome':abstract['outcome'],
              'scope':abstract.get('scope',{})}
    tool=module_digest();compiler=compiler_identity(); project_dir=Path(manifest_path).resolve().parent
    ensure_table(ws)
    items={};hits=0;runs=0;failures=[]
    for t in manifest['tests']:
        key,inputs=_target_key(t,project_dir,raw,spec_digest,tool,compiler)
        cached=None
        if reuse and t['id']!=manifest['integration']:
            with ws._db() as db:
                row=db.execute('SELECT evidence_digest FROM cpp_project_targets WHERE key=?',(key,)).fetchone()
            if row:
                try:
                    old=ws.get(row['evidence_digest'])
                    if old['schema']=='ax-cpp-project-target/0.1' and old['key']==key and old['inputs']==inputs and old['outcome']=='Tested' and set(old['variants'])==set(MODES) and all(
                        v.get('compile_status')=='Finished' and v.get('compile_exit')==0 and
                        v.get('run_status')=='Finished' and v.get('run_exit')==0 and
                        v.get('stdout_digest')==digest(t['expect'].encode()) and
                        v.get('stdout_truncated') is False and v.get('stderr_truncated') is False
                        for v in old['variants'].values()):
                        cached=old
                except (KeyError,TypeError,ValueError,OSError):pass
        if cached is not None:
            hits+=1;ev=cached; reused=True
        else:
            outcome,variants=_build_test(t,raw)
            ev={'schema':'ax-cpp-project-target/0.1','id':t['id'],'key':key,
                'inputs':inputs,'outcome':outcome,'variants':variants,
                'scope':'trusted-local-C++-bounded-unit-and-integration-tests'}
            # Even failure reports stored content-addressed for diagnostics; never reused.
            eh=ws.put(ev);runs+=1;reused=False
            with ws._db() as db:
                db.execute('INSERT OR REPLACE INTO cpp_project_targets VALUES (?,?,?)',
                           (key,eh,time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())))
        items[t['id']]={'outcome':ev['outcome'],'reused':reused,'key':key,
                        'evidence_digest':digest(ev)}
        if ev['outcome']!='Tested':failures.append(t['id'])
    outcome=('Tested' if not failures and abstract['outcome']=='Bounded'
             else 'Violated' if any(items[k]['outcome']=='Violated' for k in failures)
             else 'Unknown')
    report={'schema':REPORT,'outcome':outcome,'abstract':compiled,'manifest_digest':digest(manifest),
            'spec_digest':spec_digest,'source_digests':{n:digest(raw[n]) for n in manifest['files']},
            'tool_digest':tool,'compiler':compiler,'targets':items,
            'integration_reexecuted':True,'cache_hits':hits,'executed_targets':runs,
            'failed_targets':failures,'elapsed_seconds':round(time.perf_counter()-start,6),
            'assurance':'Tested' if outcome=='Tested' else 'None',
            'scope':'tested project targets; abstract model separately bounded; NO refinement proof',
            'release_authorized':False}
    rh=ws.put(report)
    evidence={'schema':EVIDENCE,'report_digest':rh,'manifest_digest':report['manifest_digest'],
              'spec_digest':spec_digest,'source_digests':report['source_digests'],'tool_digest':tool,
              'outcome':outcome,'assurance':report['assurance'],'release_authorized':False}
    eh=ws.put(evidence);rid='p2h-'+uuid.uuid4().hex
    with ws._db() as db:
        db.execute('INSERT INTO cpp_project_runs VALUES (?,?,?)',
                   (rid,eh,time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())))
    return {'run_id':rid,'report':report,'report_digest':rh,'evidence_digest':eh}


def project_gate(ws:Workspace, manifest_path):
    """Read-only gate; conservative fingerprint audit, no implicit execution."""
    manifest,raw,ir=load_project(manifest_path)
    mh=digest(manifest);sd=digest(ir);compiler=compiler_identity();tool=module_digest()
    if verify(ir,max_states=5000,max_transitions=15000,timeout_s=10)['outcome']!='Bounded':
        return {'schema':'ax-cpp-project-gate/0.1','decision':'Blocked',
                'reasons':['ABSTRACT_NOT_BOUNDED'],'release_authorized':False}
    ensure_table(ws)
    keys={t['id']:_target_key(t,Path(manifest_path).resolve().parent,raw,sd,tool,compiler)
          for t in manifest['tests']}
    with ws._db() as db:
        rows=db.execute('SELECT * FROM cpp_project_runs ORDER BY created_at DESC,run_id DESC').fetchall()
    selected=None
    for row in rows:
        try:
            evid=ws.get(row['evidence_digest']);report=ws.get(evid['report_digest'])
            if (evid['schema']!=EVIDENCE or report['schema']!=REPORT or
                report['outcome']!='Tested' or evid['outcome']!='Tested' or
                report['manifest_digest']!=mh or evid['manifest_digest']!=mh or
                report['spec_digest']!=sd or evid['spec_digest']!=sd or
                report['source_digests']!={n:digest(raw[n]) for n in manifest['files']} or
                evid['source_digests']!=report['source_digests'] or
                report['tool_digest']!=tool or evid['tool_digest']!=tool or
                report['compiler']!=compiler or report['integration_reexecuted'] is not True or
                report['abstract']['outcome']!='Bounded' or
                set(report['targets'])!=set(keys) or
                any(report['targets'][name]['key']!=pair[0] or report['targets'][name]['outcome']!='Tested'
                    for name,pair in keys.items()) or
                report['targets'][manifest['integration']]['reused'] is not False or
                evid['release_authorized'] is not False):
                continue
            # Every target must point to the current immutable evidence object and its key.
            for name,item in report['targets'].items():
                te=ws.get(item['evidence_digest'])
                if (te['schema']!='ax-cpp-project-target/0.1' or te['key']!=item['key']
                    or te['inputs']!=keys[name][1] or te['outcome']!='Tested'
                    or set(te['variants'])!=set(MODES) or any(
                      v.get('compile_status')!='Finished' or v.get('compile_exit')!=0
                      or v.get('run_status')!='Finished' or v.get('run_exit')!=0
                      or v.get('stdout_digest')!=digest(next(t['expect'] for t in manifest['tests'] if t['id']==name).encode())
                      or v.get('stdout_truncated') is not False or v.get('stderr_truncated') is not False
                      for v in te['variants'].values())):
                    raise ValueError('target record mismatch')
            selected=row['run_id'];break
        except (KeyError,ValueError,TypeError,OSError):pass
    return {'schema':'ax-cpp-project-gate/0.1','decision':'Approved' if selected else 'Blocked',
            'selected_run':selected,'reasons':[] if selected else ['NO_MATCHING_TESTED_PROJECT_EVIDENCE'],
            'assurance':'Tested' if selected else 'None','release_authorized':False,
            'scope':'tested trusted-local multi-file C++ builds, not formal C++ refinement or production' }
