"""Research-only Linux user/mount/net/pid namespace launcher for C++ build and run.

Fail-closed when namespaces or read-only bind mounts are not available.
Do NOT advertise as production-grade arbitrary-code sandbox: no mandatory seccomp,
Landlock, resource accounting cgroup or kernel attack protection is provided.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import resource
import shutil
import signal
import stat
import subprocess
import sys
import tempfile

MAX_INPUT = 2_000_000
MAX_OUTPUT = 1_000_000


def available():
    if sys.platform != 'linux' or not shutil.which('unshare') or not shutil.which('mount'):
        return False
    try:
        r=subprocess.run(['unshare','--user','--map-root-user','--mount','--net','--pid','--fork',
              '/bin/true'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5)
        return r.returncode==0
    except (OSError,subprocess.TimeoutExpired):
        return False


def _mount(*cmd):
    p=subprocess.run(['/usr/bin/mount',*cmd], stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=10)
    if p.returncode:
        raise RuntimeError('namespace mount failed: '+p.stderr.decode(errors='replace')[:250])


def child(root:str, command:list[str]):
    """Runs after unshare, creating new *private* chroot mount layout."""
    try:
        root=Path(root).resolve()
        _mount('--make-rprivate','/')
        (root/'usr').mkdir(exist_ok=True)
        _mount('--bind','/usr',str(root/'usr'))
        _mount('-o','remount,bind,ro',str(root/'usr'))
        (root/'proc').mkdir(exist_ok=True)
        # A new procfs may be prohibited by kernel exposure policy. Keep /proc empty.
        # No host procfs bind: that would weaken namespace isolation.
        (root/'dev').mkdir(exist_ok=True)
        for item in ('null','zero','urandom'):
            path=root/'dev'/item
            path.touch(exist_ok=True)
            _mount('--bind',f'/dev/{item}',str(path))
        for link,target in [('bin','usr/bin'),('lib','usr/lib'),('lib64','usr/lib64')]:
            p=root/link
            if not p.exists() and not p.is_symlink():p.symlink_to(target)
        (root/'tmp').mkdir(mode=0o1777,exist_ok=True)
        os.chroot(root)
        os.chdir('/work')
        os.environ.clear()
        os.environ.update({'PATH':'/usr/bin:/bin','LANG':'C','LC_ALL':'C',
                           'TMPDIR':'/tmp','HOME':'/work'})
        os.execv(command[0],command)
    except BaseException as exc:
        print('E_NAMESPACE_SETUP: '+repr(exc),file=sys.stderr)
        os._exit(125)


def _limits(cpu_seconds:int, file_bytes:int):
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    resource.setrlimit(resource.RLIMIT_CPU,(cpu_seconds,cpu_seconds+1))
    resource.setrlimit(resource.RLIMIT_FSIZE,(file_bytes,file_bytes))
    resource.setrlimit(resource.RLIMIT_NOFILE,(64,64))


def execute(files:dict[str,bytes], command:list[str], *, input_data:bytes=b'',timeout_s:int=20,output_file:str|None=None):
    if not available():
        return {'status':'Unavailable','reason':'E_NAMESPACE_UNAVAILABLE'}
    if (not isinstance(timeout_s,int) or not 1<=timeout_s<=120 or
        len(input_data)>MAX_INPUT or not isinstance(command,list) or not command or
        command[0] not in ('/usr/bin/g++','/usr/bin/g++-14','/usr/bin/x86_64-linux-gnu-g++-14','/work/a.out')):
        return {'status':'Unavailable','reason':'E_NAMESPACE_POLICY'}
    for name,raw in files.items():
        if not isinstance(name,str) or not name or '/' in name or name in ('.','..') or not isinstance(raw,bytes) or len(raw)>2_000_000:
            return {'status':'Unavailable','reason':'E_NAMESPACE_INPUT'}
    if output_file is not None and (not output_file or '/' in output_file or output_file in ('.','..')):
        return {'status':'Unavailable','reason':'E_NAMESPACE_INPUT'}
    with tempfile.TemporaryDirectory(prefix='ax-p2e-ns-') as td:
        root=Path(td)/'root';work=root/'work';work.mkdir(parents=True)
        for name,raw in files.items():
            (work/name).write_bytes(raw)
            if name=='a.out':(work/name).chmod(0o700)
        (root/'tmp').mkdir(mode=0o1777)
        python_script='from axiom.sandbox import child; import json,sys; child(sys.argv[1],json.loads(sys.argv[2]))'
        args=['unshare','--user','--map-root-user','--mount','--net','--pid','--fork','--kill-child',
              sys.executable,'-c',python_script,str(root),json.dumps(command)]
        def limits():_limits(timeout_s+2,10_000_000)
        try:
            out_file = tempfile.TemporaryFile(mode='w+b')
            err_file = tempfile.TemporaryFile(mode='w+b')
            proc=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=out_file,stderr=err_file,
                 env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1]),'LC_ALL':'C'},
                 start_new_session=True,preexec_fn=limits)
            try:
                proc.communicate(input=input_data,timeout=timeout_s)
                timed=False
            except subprocess.TimeoutExpired:
                timed=True
                try:os.killpg(proc.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                # Avoid an unbounded second communicate() on a timed-out
                # namespace process: a descendant may retain the stdin pipe.
                try:
                    if proc.stdin and not proc.stdin.closed: proc.stdin.close()
                    proc.stdin=None
                except (OSError,ValueError): pass
                try: proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    return {'status':'Timeout','reason':'E_NAMESPACE_REAP_TIMEOUT',
                            'stdout':'','stderr':'','stdout_truncated':False,
                            'stderr_truncated':False,'output':None}
            out_file.seek(0);err_file.seek(0)
            out=out_file.read(MAX_OUTPUT+1);err=err_file.read(MAX_OUTPUT+1)
            out_truncated=len(out)>MAX_OUTPUT;err_truncated=len(err)>MAX_OUTPUT
            out=out[:MAX_OUTPUT];err=err[:MAX_OUTPUT]
            out_file.close();err_file.close()
            saved=None
            if output_file:
                candidate=work/output_file
                try:
                    st=candidate.lstat()
                    if not stat.S_ISREG(st.st_mode) or st.st_size>10_000_000:
                        raise ValueError('unsafe output type or size')
                    fd=os.open(candidate,os.O_RDONLY|os.O_NOFOLLOW)
                    with os.fdopen(fd,'rb') as f:saved=f.read(10_000_001)
                    if len(saved)>10_000_000:raise ValueError('output limit')
                except (OSError,ValueError):
                    saved=None
            return {'status':'Timeout' if timed else 'Finished','exit':proc.returncode if not timed else None,
                   'stdout':out.decode(errors='replace'),'stderr':err.decode(errors='replace'),
                   'stdout_truncated':out_truncated,'stderr_truncated':err_truncated,
                   'output':saved,'isolated':True,'namespace_kinds':['user','mount','network','pid'],
                   'sysroot_readonly':True,'workspace_scope':'private-chroot-workdir'}
        except (OSError,ValueError) as exc:
            return {'status':'Unavailable','reason':'E_NAMESPACE_EXEC','detail':str(exc)[:500]}
