"""Axiom Studio V0.6 — multi-target production plans, independent comparison,
recoverable application and human-gated test-only decision.

This service deliberately DOES NOT write protected specs, tests, or Gate policy;
plans only replace declared implementation files. Native C++ execution requires
explicit trusted-local authorization; temp snapshots are NOT a secure sandbox.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from orchestrator import FlowError, FlowConflict, canonical
from proposals import ProposalError, ConflictError, atomic


def sha(raw): return hashlib.sha256(raw).hexdigest()
def jd(obj): return sha(canonical(obj))

class Batches:
    def __init__(self,studio):
        self.s=studio;self.lock=threading.RLock()
        self.home=studio.flow.db.parent/'batches'
        for name in ('records','objects','backups'):(self.home/name).mkdir(parents=True,exist_ok=True)

    def _record(self,id):
        if not isinstance(id,str) or not id.startswith('batch-') or len(id)!=22 or not all(c in '0123456789abcdef' for c in id[6:]):
            raise FlowError('非法方案事务编号')
        f=self.home/'records'/(id+'.json')
        if not f.is_file():raise FlowError('方案事务不存在')
        obj=json.loads(f.read_text('utf-8'))
        if obj.get('id')!=id:raise FlowConflict('方案事务记录失效')
        return obj

    def _store(self,obj):
        atomic(self.home/'records'/(obj['id']+'.json'),json.dumps(obj,sort_keys=True,ensure_ascii=False,indent=2).encode())

    def _event(self,obj,kind,data):
        prev=obj['events'][-1]['hash'] if obj['events'] else '0'*64
        e={'kind':kind,'data':data,'previous':prev,'time':time.time()}
        e['hash']=jd(e)
        obj['events'].append(e)

    def _audit(self,obj):
        prev='0'*64
        for e in obj['events']:
            basis={k:e[k] for k in ('kind','data','previous','time')}
            if e['previous']!=prev or jd(basis)!=e['hash']:return False
            prev=e['hash']
        # Bind candidate payloads and evaluation outcomes to the recorded chain.
        staged={e['data']['option_id']:e['data']['digest'] for e in obj['events'] if e['kind']=='option_staged'}
        evaluated={e['data']['option']:e['data'] for e in obj['events'] if e['kind']=='option_evaluated'}
        for option in obj['options']:
            if staged.get(option['id'])!=option['digest']:
                return False
            if jd({'baseline':obj['baseline'],'targets':option['objects'],'manifest':obj['manifest_sha']})!=option['digest']:
                return False
            if option['state'] in ('tested','blocked'):
                if not option['verification'] or option['verification']['option_digest']!=option['digest']:
                    return False
                ev=evaluated.get(option['id'])
                if not ev or ev.get('result_digest')!=jd(option['verification']):return False
        return len(obj['events'])>0

    def _obj(self,raw):
        h=sha(raw);path=self.home/'objects'/h
        if not path.exists():
            try:
                with open(path,'xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
            except FileExistsError:pass
        if path.read_bytes()!=raw:raise FlowConflict('内容寻址对象已损坏')
        return h

    def _read_obj(self,h):
        if not isinstance(h,str) or len(h)!=64 or any(c not in '0123456789abcdef' for c in h):raise FlowConflict('非法对象摘要')
        raw=(self.home/'objects'/h).read_bytes()
        if sha(raw)!=h:raise FlowConflict('内容寻址对象校验失败')
        return raw

    def _manifest(self,manifest,targets):
        # Reuse pre-existing protected-file/manifest policy.
        m,spec,_=self.s.proposals._manifest(manifest)
        data=json.loads(m.read_text('utf-8'))
        if m.parent==self.s.proposals.workspace or m.parent.is_symlink():raise FlowError('必须为独立的项目子目录')
        if not isinstance(targets,list) or not 2<=len(targets)<=6 or len(set(targets))!=len(targets):
            raise FlowError('多目标构造要求 2—6 个不同实现目标')
        files=data['files']
        # Reject symlinks, unlisted native files, and unsafe directories.
        for name in files+[data['spec']]:
            p=m.parent/name
            if '/' in name or '\\' in name or p.is_symlink() or not p.is_file():
                raise FlowError('工程文件必须是清单列出的普通文件')
        tracked={p.name for p in m.parent.iterdir()}
        if tracked!=set(files+[data['spec'],m.name]) or any(p.is_symlink() for p in m.parent.iterdir()):
            raise FlowError('多文件原型仅允许独立的、无符号链接、完全列举的工程目录')
        clean=[]
        for t in targets:
            _,_,dest=self.s.proposals._manifest(manifest, (m.parent/t).relative_to(self.s.proposals.workspace).as_posix() if '/' not in t else t)
            if dest.parent!=m.parent or dest.suffix!='.cpp':raise FlowError('仅支持同一项目的 .cpp 实现目标')
            clean.append(dest.name)
        return m,data,clean

    def _files(self,obj):
        p=self.s.flow.get(obj['project_id'])
        if p['stale'] or p['baseline']!=obj['baseline'] or p['manifest']!=obj['manifest'] or p['spec']!=obj['spec']:
            raise FlowConflict('规格/工程基线已改变，历史方案失效')
        if not self.s.flow.audit(p['id'])['chain_valid']:
            raise FlowConflict('流程事件审计链无效')
        ov=self.s.production.overview(p['id'])
        if ov.get('contract_digest')!=obj['contract_digest']:raise FlowConflict('冻结生产契约已失效')
        if self.s.production.task_packet(p['id'])['digest']!=obj['task_digest']:raise FlowConflict('构造任务包已发生变更')
        m,data,targets=self._manifest(obj['manifest'],obj['targets'])
        if targets!=obj['targets']:raise FlowConflict('目标次序被改变')
        return m,data

    def _check(self,obj,mode='original'):
        if not self._audit(obj):raise FlowConflict('本地方案事件链校验失败')
        m,data=self._files(obj)
        if sha(m.read_bytes())!=obj['manifest_sha']:raise FlowConflict('项目清单变更')
        files={n:sha((m.parent/n).read_bytes()) for n in data['files']+[data['spec']]}
        if mode=='original':expected=obj['sources']
        elif mode=='installed':
            option=self._option(obj,obj['selected'])
            expected=dict(obj['sources']);expected.update(option['objects'])
        else:raise FlowError('非法状态校验模式')
        if files!=expected:raise FlowConflict('项目文件已变化：不能复用候选/证据')
        return m,data

    def _option(self,obj,oid):
        if not isinstance(oid,str):raise FlowError('候选编号无效')
        for x in obj['options']:
            if x['id']==oid:return x
        raise FlowError('未找到方案')

    def _public(self,obj):
        r={k:v for k,v in obj.items() if k!='events'}
        r['audit_valid']=self._audit(obj)
        r['release_authorized']=False
        r['assurance']='trusted-local bounded model + native tested C++; no formal refinement'
        if obj['state'] not in ('installing','needs_recovery'):
            try:
                self._check(obj,'installed' if obj['state'] in ('deployed_unverified','decision_pending','accepted_test_only') else 'original')
                r['current']=True
            except (FlowError,ProposalError,OSError,ValueError):r['current']=False
        else:r['current']=False
        return r

    def create(self,pid,targets):
        with self.lock:
            p=self.s.flow.get(pid)
            if p['status']!='spec_ready' or p['stale']:raise FlowConflict('必须先完成规格模型 Gate，且项目处于待实现状态')
            packet=self.s.production.task_packet(pid)
            if not self.s.flow.audit(pid)['chain_valid']:raise FlowConflict('流程审计失败')
            m,data,clean=self._manifest(p['manifest'],targets)
            # No simultaneously active single-file or multi-target mutation flows.
            with self.s.flow._connect() as cx:
                x=cx.execute("SELECT state FROM factory_campaigns WHERE project_id=? ORDER BY created DESC",(pid,)).fetchall()
            if any(r['state'] not in ('blocked','completed_test_only') for r in x):raise FlowConflict('已有单目标构造任务占用此项目')
            for f in (self.home/'records').glob('batch-*.json'):
                other=json.loads(f.read_text('utf-8'))
                if other['project_id']==pid and other['state'] not in ('blocked','rolled_back','accepted_test_only'):
                    raise FlowConflict('同一项目已有未完成的多目标构造事务')
            sources={n:sha((m.parent/n).read_bytes()) for n in data['files']+[data['spec']]}
            rid='batch-'+secrets.token_hex(8)
            obj={'schema':'ax-batch/0.6','id':rid,'project_id':pid,'baseline':p['baseline'],
                 'manifest':p['manifest'],'spec':p['spec'],'manifest_sha':sha(m.read_bytes()),
                 'contract_digest':packet['packet']['contract_digest'],'task_digest':packet['digest'],
                 'targets':clean,'sources':sources,'state':'staging','options':[],
                 'selected':None,'live_evidence':None,'events':[],'created':time.time()}
            self._event(obj,'created',{'baseline':p['baseline'],'sources':sources,'targets':clean})
            self._store(obj)
            return self._public(obj)

    def get(self,bid):
        with self.lock:return self._public(self._record(bid))

    def list(self,pid):
        self.s.flow.get(pid)
        with self.lock:
            result=[]
            for f in (self.home/'records').glob('batch-*.json'):
                o=json.loads(f.read_text('utf-8'))
                if o['project_id']==pid:result.append(self._public(o))
            return {'batches':sorted(result,key=lambda x:x['created'],reverse=True)}

    def stage(self,bid,name,replacements):
        with self.lock:
            obj=self._record(bid)
            if obj['state']!='staging':raise FlowConflict('只允许在暂存阶段提交方案')
            self._check(obj)
            if not isinstance(name,str) or not 1<=len(name)<=100:raise FlowError('需要方案名')
            if not isinstance(replacements,dict) or set(replacements)!=set(obj['targets']):
                raise FlowError('方案必须提供全部目标的完整源码，且不能包含测试和规格')
            if len(obj['options'])>=6:raise FlowError('一次最多对比 6 个方案')
            replacement={}
            for k,v in replacements.items():
                if not isinstance(v,str) or not v.strip() or len(v.encode())>128*1024:
                    raise FlowError('实现源码不能为空或超过 128 KiB')
                replacement[k]=self._obj(v.encode())
            digest=jd({'baseline':obj['baseline'],'targets':replacement,'manifest':obj['manifest_sha']})
            if any(x['digest']==digest for x in obj['options']):raise FlowConflict('同一份方案已存在')
            op={'id':'opt-'+secrets.token_hex(7),'name':name,'objects':replacement,
                'digest':digest,'state':'staged','verification':None}
            obj['options'].append(op)
            self._event(obj,'option_staged',{'option_id':op['id'],'digest':digest})
            self._store(obj)
            return self._public(obj)

    def _run(self,argv,cwd,seconds):
        env=dict(os.environ);env['PYTHONPATH']=str(self.s.proposals.engine/'src')
        p=subprocess.Popen(argv,cwd=cwd,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE,start_new_session=(os.name=='posix'))
        try:out,err=p.communicate(timeout=seconds)
        except subprocess.TimeoutExpired:
            if os.name=='posix':os.killpg(p.pid,signal.SIGKILL)
            else:p.kill()
            try:
                if p.stdout:p.stdout.close()
                if p.stderr:p.stderr.close()
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:pass
            raise FlowConflict('真实验证超时，不能产生通过证据')
        try:parsed=json.loads(out)
        except (ValueError,UnicodeDecodeError):parsed={'raw':out[:1024].decode('utf-8','replace')}
        return {'command':argv[-2] if len(argv)>2 else argv[-1], 'returncode':p.returncode,
                'data':parsed,'stderr':err[-700:].decode('utf-8','replace')}

    def _verify(self,manifest,evidence):
        # Shared native Axiom engine. Only real results may authorize test-only decisions.
        engine=str(self.s.proposals.engine)
        evidence.mkdir(parents=True,exist_ok=True)
        envcmd=[sys.executable,'-m','axiom','--workspace',str(evidence)]
        spec=manifest.parent/json.loads(manifest.read_text('utf-8'))['spec']
        steps=[('model','verify',spec,[],40),('model_gate','gate',spec,['--target','model'],40),
               ('cpp_full','cpp-project-verify',manifest,['--full'],135),
               ('cpp_gate','cpp-project-gate',manifest,[],45)]
        checks=[]
        for label,command,path,flags,limit in steps:
            result=self._run(envcmd+[command,str(path),*flags],manifest.parent,limit)
            result['step']=label
            checks.append(result)
            if result['returncode']!=0 or (label.endswith('gate') and result['data'].get('decision')!='Approved'):
                return {'passed':False,'checks':checks,'failed_at':label,'scope':'cpp-tested-prototype only'}
        return {'passed':True,'checks':checks,'failed_at':None,'scope':'cpp-tested-prototype only'}

    def evaluate(self,bid,oid,trusted=False):
        if trusted is not True:raise FlowError('编译/运行 C++ 前需单独确认可信本地实现，不适用恶意代码')
        with self.lock:
            obj=self._record(bid)
            if obj['state']!='staging':raise FlowConflict('不能在已部署阶段修改方案比较结果')
            m,data=self._check(obj)
            option=self._option(obj,oid)
            if option['state']!='staged':raise FlowConflict('此方案已经评估，不能重复写入证据')
            code={k:self._read_obj(v) for k,v in option['objects'].items()}
            with tempfile.TemporaryDirectory(prefix='axiom-v06-shadow-') as tmp:
                root=Path(tmp);shadow=root/'project';shadow.mkdir()
                for filename in data['files']+[data['spec']]:
                    src=m.parent/filename
                    (shadow/filename).write_bytes(code.get(filename,src.read_bytes()))
                (shadow/m.name).write_bytes(m.read_bytes())
                shadow_hash={name:sha((shadow/name).read_bytes()) for name in data['files']+[data['spec']]}
                expected=dict(obj['sources']);expected.update(option['objects'])
                if shadow_hash!=expected:raise FlowConflict('影子工程与方案摘要不一致')
                # Each option gets isolated evidence, not shared with other options.
                evidence=self.home/'option-evidence'/bid/oid
                result=self._verify(shadow/m.name,evidence)
            self._check(obj)
            option['verification']={'result':result,'source_digests':expected,
                                    'contract_digest':obj['contract_digest'],
                                    'task_digest':obj['task_digest'],'option_digest':option['digest'],
                                    'recorded':time.time()}
            option['state']='tested' if result['passed'] else 'blocked'
            self._event(obj,'option_evaluated',{'option':oid,'passed':result['passed'],
                 'failed_at':result['failed_at'],'result_digest':jd(option['verification'])})
            self._store(obj)
            return self._public(obj)

    def compare(self,bid):
        with self.lock:
            obj=self._record(bid);self._check(obj,'installed' if obj['state'] in ('deployed_unverified','decision_pending','accepted_test_only') else 'original')
            return {'id':bid,'comparison':[{'id':o['id'],'name':o['name'],'digest':o['digest'],'status':o['state'],
                 'passed':bool(o['verification'] and o['verification']['result']['passed']),
                 'checks':[{ 'step':c['step'],'returncode':c['returncode'],
                     'decision':c['data'].get('decision') if isinstance(c['data'],dict) else None,
                     'outcome':(c['data'].get('report') or {}).get('outcome') if isinstance(c['data'],dict) else None,
                     'failed_targets':(c['data'].get('report') or {}).get('failed_targets',[]) if isinstance(c['data'],dict) else []}
                     for c in (o['verification'] or {}).get('result',{}).get('checks',[])]}
                 for o in obj['options']],
                 'automatic_selection':False,'note':'人工比较; 通过测试不等于形式化精化或生产许可'}

    def repair_packet(self,bid,oid):
        """Candidate-only diagnostic feedback; requires a new staged alternative.

        The packet cannot authorize editing protected files, replacing tests, or
        promoting a failed alternative to verified state.
        """
        with self.lock:
            obj=self._record(bid)
            if obj['state']!='staging':raise FlowConflict('只能对暂存阶段的失败候选生成修复任务')
            self._check(obj)
            op=self._option(obj,oid)
            if op['state']!='blocked' or not op['verification']:
                raise FlowConflict('只能反馈真实失败的候选')
            result=op['verification']['result']
            failed=[{'step':c['step'], 'returncode':c['returncode'],
                     'failed_targets':(c['data'].get('report') or {}).get('failed_targets',[]),
                     'error':c['stderr'][-500:]}
                    for c in result['checks'] if c['returncode']!=0]
            pkt={'schema':'ax-multi-target-repair/0.6','transaction_id':bid,
                 'option_id':oid,'option_digest':op['digest'],
                 'contract_digest':obj['contract_digest'], 'task_digest':obj['task_digest'],
                 'allowed_new_replacements':obj['targets'], 'failed_at':result['failed_at'],
                 'failed_steps':failed,
                 'restrictions':['do not modify the behavior specification',
                                 'do not modify test files or project manifest',
                                 'do not edit evidence or quality Gate policy',
                                 'create a NEW staged option and re-run independent validation',
                                 'no autonomous code execution, selection or approval'],
                 'max_unreviewed_repairs':0}
            return {'packet':pkt,'digest':jd(pkt)}

    def select(self,bid,oid,digest,confirmation):
        if confirmation!='human_selected_after_comparison':raise FlowError('必须显式人工选择方案')
        with self.lock:
            obj=self._record(bid)
            if obj['state']!='staging':raise FlowConflict('事务已经关闭暂存选择')
            self._check(obj)
            op=self._option(obj,oid)
            if op['state']!='tested' or op['digest']!=digest or not op['verification']['result']['passed']:
                raise FlowConflict('未通过真实独立验证或方案摘要不匹配')
            obj['selected']=oid;obj['state']='human_apply'
            self._event(obj,'human_selected',{'option':oid,'digest':digest})
            self._store(obj)
            return self._public(obj)

    def apply(self,bid,digest,confirmation):
        if confirmation!='human_authorized_multi_file_apply':raise FlowError('必须人工确认多文件整体应用')
        with self.lock:
            obj=self._record(bid)
            if obj['state']!='human_apply':raise FlowConflict('事务尚未获得人工方案选择')
            m,data=self._check(obj)
            op=self._option(obj,obj['selected'])
            if op['digest']!=digest:raise FlowConflict('方案内容摘要不匹配')
            parent=m.parent.parent
            tmp=parent/('.ax-batch-stage-'+bid)
            backup=self.home/'backups'/bid
            if tmp.exists() or backup.exists():raise FlowConflict('发现未完成的事务目录; 请先核验和恢复')
            try:
                shutil.copytree(m.parent,tmp,symlinks=False)
                for name,h in op['objects'].items():
                    atomic(tmp/name,self._read_obj(h))
                raw={n:sha((tmp/n).read_bytes()) for n in data['files']+[data['spec']]}
                expected=dict(obj['sources']);expected.update(op['objects'])
                if raw!=expected:raise FlowConflict('暂存项目文件校验失败')
                obj['state']='installing';self._event(obj,'installing',{'target':str(m.parent),'backup':str(backup)})
                self._store(obj)
                os.replace(m.parent,backup)
                os.replace(tmp,m.parent)
                obj['state']='deployed_unverified';self._event(obj,'installed_unverified',{'files':raw})
                self._store(obj)
                return self._public(obj)
            except Exception:
                if backup.exists():
                    if m.parent.exists():shutil.rmtree(m.parent)
                    os.replace(backup,m.parent)
                if tmp.exists():shutil.rmtree(tmp)
                obj['state']='blocked';self._event(obj,'install_failed_rolled_back',{})
                self._store(obj)
                raise

    def _rollback(self,obj,reason):
        mpath=(self.s.proposals.workspace/obj['manifest']).resolve(strict=False)
        if not mpath.is_relative_to(self.s.proposals.workspace.resolve()) or mpath.parent==self.s.proposals.workspace:
            raise FlowConflict('非法备份路径')
        project_dir=mpath.parent
        backup=self.home/'backups'/obj['id']
        if not backup.is_dir():
            # Crash before the first rename: no live file was switched.
            if obj['state']=='installing' and project_dir.is_dir() and all(
                (project_dir/n).is_file() and sha((project_dir/n).read_bytes())==h
                for n,h in obj['sources'].items()):
                stage=project_dir.parent/('.ax-batch-stage-'+obj['id'])
                if stage.is_dir():shutil.rmtree(stage)
                obj['state']='rolled_back';self._event(obj,'rolled_back',{'reason':reason,'before_rename':True})
                self._store(obj);return
            raise FlowConflict('缺少受保护的事务备份，禁止猜测恢复')
        if project_dir.exists():
            for n in obj['sources']:
                actual=sha((project_dir/n).read_bytes()) if (project_dir/n).is_file() else None
                expected=(self._option(obj,obj['selected'])['objects'].get(n) or obj['sources'][n])
                if actual!=expected:raise FlowConflict('应用后文件被外部修改，禁止自动覆盖，请人工恢复')
            shutil.rmtree(project_dir)
        os.replace(backup,project_dir)
        for n,h in obj['sources'].items():
            if sha((project_dir/n).read_bytes())!=h:raise FlowConflict('回滚后校验未通过')
        obj['state']='rolled_back';self._event(obj,'rolled_back',{'reason':reason})
        self._store(obj)

    def verify_live(self,bid,trusted=False):
        if trusted is not True:raise FlowError('实际 C++ 再验证必须确认可信本地代码')
        with self.lock:
            obj=self._record(bid)
            if obj['state']!='deployed_unverified':raise FlowConflict('仅已安装但未验证的方案可复核')
            m,data=self._check(obj,'installed')
            result=self._verify(m,self.home/'live-evidence'/bid)
            if not result['passed']:
                obj['live_evidence']=result
                try:self._rollback(obj,'live_verification_failed')
                except (FlowConflict,OSError):
                    obj['state']='needs_recovery';self._event(obj,'manual_recovery_required',{})
                    self._store(obj)
                return self._public(obj)
            obj['live_evidence']={'result':result,'source_digests':{n:sha((m.parent/n).read_bytes()) for n in obj['sources']},
                                  'option_digest':self._option(obj,obj['selected'])['digest']}
            obj['state']='decision_pending';self._event(obj,'live_verified',{'option':obj['selected']})
            self._store(obj)
            return self._public(obj)

    def decide(self,bid,digest,confirmation):
        if confirmation!='human_approve_test_only':raise FlowError('不允许生成生产发布许可')
        with self.lock:
            obj=self._record(bid)
            if obj['state']!='decision_pending':raise FlowConflict('实际工程 Gate 尚未通过')
            m,_=self._check(obj,'installed')
            op=self._option(obj,obj['selected'])
            if digest!=op['digest'] or not obj['live_evidence'] or not obj['live_evidence']['result']['passed']:
                raise FlowConflict('未获得当前选定实现的有效证据')
            # Re-query independent read-only cpp Gate at the last moment.
            check=self._run([sys.executable,'-m','axiom','--workspace',str(self.home/'live-evidence'/bid),
                             'cpp-project-gate',str(m)],m.parent,45)
            if check['returncode']!=0 or check['data'].get('decision')!='Approved':raise FlowConflict('实时 C++ Gate 阻断')
            self._check(obj,'installed')
            obj['state']='accepted_test_only'
            self._event(obj,'human_test_only_decision',{'digest':digest,'gate':'Approved','production_release':False})
            self._store(obj)
            return self._public(obj)

    def rollback(self,bid,confirmation):
        if confirmation!='human_reject_and_rollback':raise FlowError('回滚需人工确认')
        with self.lock:
            obj=self._record(bid)
            if obj['state'] not in ('installing','deployed_unverified','decision_pending','needs_recovery'):
                raise FlowConflict('当前状态不能回滚')
            self._rollback(obj,'human_reject')
            return self._public(obj)

    def audit(self,bid):
        with self.lock:
            obj=self._record(bid)
            return {'id':bid,'valid':self._audit(obj),'events':obj['events'],
                    'scope':'local SHA-256 chain; NOT externally tamper proof'}
