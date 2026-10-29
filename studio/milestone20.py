"""Axiom Studio 2.0 milestone: replayable, fail-closed, evidence-bound release verification.

Local trusted C++ only: no sandbox security guarantee or production certification.
The bundled Axiom P2h engine makes the authoritative incremental evidence decision.
This layer calculates a *conservative explanation*, never self-certifies cached tests.
"""
from __future__ import annotations
import json, os, secrets, signal, subprocess, sys, threading, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from proposals import atomic, sha
from workorders import canonical

class MilestoneError(ValueError): pass

class Milestone20:
    def __init__(self, studio):
        self.studio=studio
        self.home=studio.proposals.home.parent/'milestone20'
        self.home.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock()
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='axiom-release-verify')

    @staticmethod
    def digest(obj): return sha(canonical(obj))

    def _path(self,rid):
        if not isinstance(rid,str) or len(rid)!=19 or not rid.startswith('m2-') or any(c not in '0123456789abcdef' for c in rid[3:]):
            raise MilestoneError('验证批次编号非法')
        return self.home/(rid+'.json')

    def _event(self,r,kind,detail=None):
        e={'index':len(r['events']),'previous':r['head'],'time':time.time(),'kind':kind,
           'detail':detail or {},'state':r['state'],'result_digest':self.digest(r['result'])}
        e['hash']=self.digest(e);r['events'].append(e);r['head']=e['hash']

    def _audit(self,r):
        head='0'*64
        for i,e in enumerate(r['events']):
            data={k:v for k,v in e.items() if k!='hash'}
            if e.get('index')!=i or e.get('previous')!=head or self.digest(data)!=e.get('hash'):
                raise MilestoneError('验证批次审计链异常')
            head=e['hash']
        if not r['events'] or r['head']!=head:raise MilestoneError('验证批次事件摘要异常')
        first=r['events'][0]
        if first.get('kind')!='created' or first['detail'].get('plan_digest')!=self.digest(r['plan']):
            raise MilestoneError('冻结验证计划已被篡改')
        last=r['events'][-1]
        if r['state']!=last['state'] or self.digest(r['result'])!=last['result_digest']:
            raise MilestoneError('验证结果或状态与审计记录不一致')

    def _load(self,rid):
        f=self._path(rid)
        if not f.is_file():raise MilestoneError('验证批次不存在')
        r=json.loads(f.read_text('utf8'))
        if r.get('id')!=rid:raise MilestoneError('验证批次编号不符')
        self._audit(r)
        return r

    def _save(self,r):
        self._audit(r)
        atomic(self._path(r['id']),json.dumps(r,indent=2,ensure_ascii=False,sort_keys=True).encode('utf8'))

    def _snapshot(self,manifest):
        mf=self.studio.proposals.file_guard(manifest)
        try:data=json.loads(mf.read_text('utf8'))
        except (ValueError,UnicodeError) as exc:raise MilestoneError('工程清单无效') from exc
        if data.get('schema')!='ax-cpp-project/0.1':raise MilestoneError('工程清单格式不受支持')
        spec=(Path(manifest).parent/data['spec']).as_posix()
        files=data['files']
        if not isinstance(files,list) or not files or len(files)>120 or len(set(files))!=len(files):
            raise MilestoneError('清单源文件非法或超限')
        names={manifest,spec}
        for f in files:
            if not isinstance(f,str) or '\\' in f or Path(f).is_absolute() or '..' in Path(f).parts:
                raise MilestoneError('工程清单存在不安全路径')
            names.add((Path(manifest).parent/f).as_posix())
        if len(names)>125:raise MilestoneError('工程文件过多')
        hashes={p:sha(self.studio.proposals.file_guard(p).read_bytes()) for p in sorted(names)}
        tests=[]
        for t in data.get('tests',[]):
            if not isinstance(t,dict) or not isinstance(t.get('id'),str) or not isinstance(t.get('files'),list):
                raise MilestoneError('工程测试声明无效')
            dependencies={(Path(manifest).parent/f).as_posix() for f in t['files']}
            if not dependencies.issubset(names):raise MilestoneError('测试依赖超出工程清单')
            tests.append({'id':t['id'],'files':sorted(dependencies)})
        return hashes,tests,spec

    def _project(self,project_id,graph_id=None):
        p=self.studio.flow.get(project_id)
        prod=self.studio.production.overview(project_id)
        if p.get('stale') or not p.get('manifest') or not prod.get('contract_digest'):
            raise MilestoneError('项目尚未具备当前有效的冻结规格与验收契约')
        if not p.get('last_verification') or p['last_verification'].get('passed') is not True:
            raise MilestoneError('当前规格尚未通过真实模型验证')
        if self.studio.flow.audit(project_id).get('chain_valid') is not True:
            raise MilestoneError('工程审计未通过')
        blockers=[x for x in prod.get('blockers',[]) if x!='HUMAN_ACCEPTANCE_AND_CPP_GATE_REQUIRED']
        if blockers:raise MilestoneError('工程验收存在未解决的问题：'+', '.join(blockers[:5]))
        if graph_id:
            g=self.studio.task_graphs.get(graph_id)
            if g['project_id']!=project_id or not g['current'] or not g['complete']:
                raise MilestoneError('所选模块任务图尚未完成或已失效')
        return p,prod

    def _live(self,plan):
        p,prod=self._project(plan['project_id'],plan.get('graph_id'))
        if p['revision']!=plan['revision'] or p['baseline']!=plan['baseline'] or p['manifest']!=plan['manifest'] or prod['contract_digest']!=plan['contract_digest']:
            return False,'规格、验收契约或工程版本发生变化'
        try:hashes,_,_=self._snapshot(plan['manifest'])
        except (OSError,KeyError,ValueError,MilestoneError) as e:return False,'工程文件不可读：'+str(e)[:120]
        if hashes!=plan['inputs']:return False,'工程文件摘要发生变化'
        return True,''

    def _view(self,r):
        live=False;why=''
        try:live,why=self._live(r['plan'])
        except Exception as e:why='当前输入无效：'+str(e)[:150]
        return {'schema':'ax-milestone20/2.0','id':r['id'],'project_id':r['plan']['project_id'],
                'state':r['state'],'current':live,'blocker':why,'plan':r['plan'],
                'result':r['result'],'head':r['head'],'audit_valid':True,
                'needs_native_execution_consent':True,'production_release_authorized':False,
                'scope':'trusted local C++ tests, engine-authoritative evidence; not a sandbox or production certification'}

    def create(self,project_id,graph_id=None,previous_id=None):
        with self.lock:
            p,prod=self._project(project_id,graph_id)
            hashes,tests,spec=self._snapshot(p['manifest'])
            changed=set(hashes)
            prev=None
            if previous_id:
                prev=self._load(previous_id)
                if prev['plan']['project_id']!=project_id or prev['state']!='passed':
                    raise MilestoneError('比较基线必须是同一项目的已通过验证批次')
                old=prev['plan']['inputs']
                changed={f for f in set(hashes)|set(old) if hashes.get(f)!=old.get(f)}
            manifest_changed=p['manifest'] in changed
            spec_changed=spec in changed
            impacted=[t['id'] for t in tests if manifest_changed or spec_changed or set(t['files'])&changed]
            # Integration can span hidden ABIs; conservative global check on *every* run.
            integration=json.loads(self.studio.proposals.file_guard(p['manifest']).read_text('utf8')).get('integration')
            if integration and integration not in impacted:impacted.append(integration)
            plan={'schema':'ax-milestone20-plan/2.0','project_id':project_id,'graph_id':graph_id,
                  'revision':p['revision'],'baseline':p['baseline'], 'contract_digest':prod['contract_digest'],
                  'manifest':p['manifest'],'spec':spec,'inputs':hashes,'tests':tests,
                  'previous_id':previous_id,'changed_files':sorted(changed),'impacted_tests':sorted(set(impacted)),
                  'global_checks':['model-verify','model-gate','cpp-project-verify','cpp-project-gate'],
                  'reuse_policy':'Only the Axiom P2h verifier may reuse evidence after dependency and toolchain checks.'}
            r={'id':'m2-'+secrets.token_hex(8),'plan':plan,'state':'planned', 'result':{'checks':[]},
               'head':'0'*64,'events':[]}
            self._event(r,'created',{'plan_digest':self.digest(plan)})
            self._save(r)
            return self._view(r)

    def get(self,rid):
        with self.lock:return self._view(self._load(rid))

    def list(self,project_id=None):
        out=[]
        with self.lock:
            for f in self.home.glob('m2-*.json'):
                try:
                    r=self._load(f.stem)
                    if project_id and r['plan']['project_id']!=project_id:continue
                    out.append(self._view(r))
                except (ValueError,KeyError,OSError,MilestoneError):continue
        return {'campaigns':sorted(out,key=lambda v:v['id'],reverse=True)[:50]}

    def start(self,rid,trusted=False):
        if trusted is not True:raise MilestoneError('运行工程 C++ 前必须单独确认已人工审查源码及其依赖')
        with self.lock:
            r=self._load(rid)
            if r['state']!='planned':raise MilestoneError('同一批次只允许执行一次；请创建新验证批次')
            live,why=self._live(r['plan'])
            if not live:raise MilestoneError('拒绝执行过期生产计划：'+why)
            r['state']='running';self._event(r,'started',{'trusted_local_approval':True});self._save(r)
            self.pool.submit(self._execute,rid)
        return self.get(rid)

    def _run_cmd(self,rid,action,path,extra,timeout):
        args=[sys.executable,'-m','axiom','--workspace',str(self.home/'engine-evidence'/sha(self._load(rid)['plan']['project_id'].encode('utf8'))),action,
              str(self.studio.proposals.file_guard(path)),*extra]
        env=dict(os.environ);env['PYTHONPATH']=str(self.studio.proposals.engine/'src')
        p=subprocess.Popen(args,cwd=self.studio.proposals.workspace,env=env,
            stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            start_new_session=(os.name=='posix'))
        try:out,err=p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name=='posix':os.killpg(p.pid,signal.SIGKILL)
            else:p.kill()
            p.communicate();raise MilestoneError('验证工具超时，已尝试终止子进程；不颁发证据：'+action)
        try:report=json.loads(out)
        except ValueError:report={'error':'验证工具未输出规范 JSON','stdout':out[:1000].decode('utf8','replace')}
        decision=report.get('decision') or report.get('report',{}).get('outcome') or report.get('verification',{}).get('outcome') or report.get('outcome')
        ok=p.returncode==0 and (not action.endswith('gate') or decision=='Approved')
        return {'action':action,'returncode':p.returncode,'outcome':decision,
                'ok':ok,'result_digest':self.digest(report),
                'report':report,'stderr':err[:2000].decode('utf8','replace')}

    def _execute(self,rid):
        checks=[];problem='';state='blocked';started=time.monotonic()
        try:
            with self.lock:r=self._load(rid);plan=r['plan']
            # The verifier still does actual source-bound evidence checks; impact is explanatory only.
            tasks=[('verify',plan['spec'],[],35),('gate',plan['spec'],['--target','model'],25),
                   ('cpp-project-verify',plan['manifest'],[],130),('cpp-project-gate',plan['manifest'],[],30)]
            for action,path,extra,timeout in tasks:
                live,why=self._live(plan)
                if not live:raise MilestoneError('检查期间工程输入发生变化：'+why)
                check=self._run_cmd(rid,action,path,extra,timeout)
                checks.append(check)
                with self.lock:
                    r=self._load(rid);r['result']={'checks':checks,'elapsed':round(time.monotonic()-started,2)}
                    self._event(r,'check_completed',{'action':action,'ok':check['ok']});self._save(r)
                if not check['ok']:raise MilestoneError(action+' 未通过，验证批次阻断')
            live,why=self._live(plan)
            if not live:raise MilestoneError('验证完成时输入发生变化：'+why)
            state='passed'
        except Exception as exc:
            problem=str(exc)[:1200]
        with self.lock:
            r=self._load(rid)
            r['state']=state
            r['result']={'checks':checks,'elapsed':round(time.monotonic()-started,2),
                         'decision':'Tested' if state=='passed' else 'Blocked',
                         'error':problem,'assurance':'local test-level only, no production release'}
            self._event(r,'finished',{'decision':r['result']['decision']});self._save(r)

    def handoff(self,rid):
        with self.lock:
            r=self._load(rid);v=self._view(r)
            report={'schema':'ax-milestone20-handoff/2.0','plan':r['plan'],'result':r['result'],
                    'events':r['events'],'current':v['current'],'audit_valid':True,
                    'production_release_authorized':False,
                    'limits':'Local hash-chain is not a signature. C++ executed with trusted-local consent, not a production-grade sandbox.'}
            return {'filename':rid+'-verification.json','report':report,'sha256':self.digest(report)}
