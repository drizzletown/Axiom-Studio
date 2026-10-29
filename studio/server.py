"""Axiom Studio local software-production orchestration service (not a multi-user production server).

Uses the real Axiom P0-P2h CLI. Designed for loopback and trusted local workspaces.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from proposals import Proposals, ProposalError, ConflictError
from orchestrator import Orchestrator, FlowError, FlowConflict
from production import Production
from factory import Factory
from batches import Batches
from launchpad import Launchpad, LaunchError
from production_runner import ProductionRunner, RunnerError
from workorders import WorkOrders, WorkOrderError
from cockpit import Cockpit
from journey import Journey
from intent_spec import IntentSpec
from spec_workshop import SpecWorkshop
from design_review import DesignReview
from pilot import ProductionPilot, PilotError, PilotConflict
from assembly import Assembly, AssemblyError
from task_graph import TaskGraphs, TaskGraphError
from fleet import ProductionFleet, FleetError
from agent_forge import AgentForge, AgentForgeError
from milestone20 import Milestone20, MilestoneError

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
ENGINE=ROOT/'engine'
WORKSPACE=ROOT/'workspace'
EVIDENCE=ROOT/'.studio-data'/'evidence'
STATIC=HERE/'static'
MAX_FILE=1024*1024
MAX_JSON=2*1024*1024
ALLOWED_EXT={'.ax','.cpp','.hpp','.h','.cc','.c','.json','.md','.txt'}
MODEL_ACTIONS={'check','plan','verify','gate','evolve-gate','cpp-verify','cpp-gate'}
MANIFEST_ACTIONS={'compose-gate','product-verify','product-gate','interleave-verify','interleave-gate','cpp-project-verify','cpp-project-full','cpp-project-gate','cpp-trace-verify','cpp-trace-gate','cpp-history-verify','cpp-history-gate','cpp-stress-verify','cpp-stress-gate'}
RUN_ACTIONS=MODEL_ACTIONS|MANIFEST_ACTIONS|{'evolve-impact','audit','evidence','sandbox-probe'}
NATIVE_ACTIONS={'cpp-project-verify','cpp-project-full','cpp-trace-verify','cpp-history-verify','cpp-stress-verify','cpp-verify'}
NATIVE_GATE_ACTIONS={'cpp-project-gate','cpp-trace-gate','cpp-history-gate','cpp-stress-gate'}
ACTION_LIMITS={'cpp-project-verify':120,'cpp-project-full':120,'cpp-trace-verify':120,'cpp-history-verify':120,'cpp-stress-verify':150}

class GuardError(Exception):
    pass

def allowed_file(relative: str) -> Path:
    if not isinstance(relative,str) or not relative or len(relative)>350 or '\\' in relative:
        raise GuardError('无效文件路径')
    name=Path(relative)
    if name.is_absolute() or '..' in name.parts or name.suffix.lower() not in ALLOWED_EXT:
        raise GuardError('文件路径超出工作区或类型不允许')
    resolved=(WORKSPACE/name).resolve()
    if not resolved.is_relative_to(WORKSPACE.resolve()) or not resolved.is_file():
        raise GuardError('只能访问现有工作区文件')
    if resolved.stat().st_size>MAX_FILE:
        raise GuardError('文件超过 1 MiB 限额')
    return resolved

def tree():
    result=[]
    for p in sorted(WORKSPACE.rglob('*')):
        if p.is_file() and p.suffix.lower() in ALLOWED_EXT and p.stat().st_size<=MAX_FILE and not p.is_symlink():
            result.append({'path':p.relative_to(WORKSPACE).as_posix(),'size':p.stat().st_size,'ext':p.suffix.lower()})
    return result

class Studio:
    def __init__(self):
        self.token=secrets.token_urlsafe(32)
        self.executor=ThreadPoolExecutor(max_workers=2,thread_name_prefix='axiom-job')
        self.jobs={}
        self.job_lock=threading.Lock()
        self.history=[]
        EVIDENCE.mkdir(parents=True,exist_ok=True)
        self.proposals=Proposals(workspace=WORKSPACE,engine=ENGINE,evidence=EVIDENCE,home=ROOT/'.studio-data'/'proposals',file_guard=allowed_file)
        self.flow=Orchestrator(db=ROOT/'.studio-data'/'flow.sqlite3',workspace=WORKSPACE,engine=ENGINE,
                 evidence_root=ROOT/'.studio-data'/'workflow-evidence',guard=allowed_file,proposals=self.proposals)
        self.production=Production(self.flow)
        self.factory=Factory(self)
        self.batches=Batches(self)
        self.launchpad=Launchpad(self)
        self.production_runner=ProductionRunner(self)
        self.workorders=WorkOrders(self)
        self.cockpit=Cockpit(self)
        self.journey=Journey(self)
        self.intent_spec=IntentSpec(self)
        self.spec_workshop=SpecWorkshop(self)
        self.design_review=DesignReview(self)
        self.pilot=ProductionPilot(self)
        self.assembly=Assembly(self)
        self.task_graphs=TaskGraphs(self)
        self.fleet=ProductionFleet(self)
        self.agent_forge=AgentForge(self)
        self.milestone20=Milestone20(self)

    def start_job(self, action, relative=None, other=None, trusted=False, candidate=None):
        if action not in RUN_ACTIONS:raise GuardError('操作不在 IDE 白名单内')
        if action in MODEL_ACTIONS|{'evolve-impact'} and (not relative or not relative.endswith('.ax')):
            raise GuardError('当前操作要求选择 .ax 规格')
        if action in MANIFEST_ACTIONS and (not relative or not relative.endswith('.json')):
            raise GuardError('当前操作要求选择 .json 清单')
        path=allowed_file(relative) if relative else None
        if action in NATIVE_ACTIONS and not trusted:
            raise GuardError('执行 C++ 前必须明确确认：工作区源代码可信且已审查。')
        if action in {'evolve-impact'}:
            older=allowed_file(other)
            if older.suffix.lower()!='.ax':raise GuardError('对比文件需要 .ax')
        if action in {'cpp-verify','cpp-gate','cpp-trace-verify','cpp-trace-gate','cpp-history-verify','cpp-history-gate','cpp-stress-verify','cpp-stress-gate'}:
            cpath=allowed_file(candidate or 'cpp/correct.cpp')
            if cpath.suffix.lower() not in {'.cpp','.cc'}:raise GuardError('候选实现需要 .cpp')
        cli='cpp-project-verify' if action=='cpp-project-full' else action
        args=[sys.executable,'-m','axiom','--workspace',str(EVIDENCE),cli]
        if path is not None:args.append(str(path))
        if action=='gate':args+=['--target','model']
        if action=='cpp-project-full':args.append('--full')
        if action=='evolve-impact':args=[''+a for a in args[:-1]]+['--from-spec',str(older),'--to-spec',str(path)]
        if action in {'cpp-verify','cpp-gate'}:
            bpath=allowed_file('cpp/binding.json')
            args+=['--candidate',str(cpath),'--binding',str(bpath)]
            if action=='cpp-verify':args.append('--trusted-local')
        if action in {'cpp-trace-verify','cpp-trace-gate','cpp-history-verify','cpp-history-gate','cpp-stress-verify','cpp-stress-gate'}:
            args+=['--candidate',str(cpath)]
            if action.startswith('cpp-history'):args+=['--repeats','2']
            if action.startswith('cpp-stress'):args+=['--repeats','1','--seed','104729','--seed-count','2']
            if action.startswith('cpp-trace'):args+=['--depth','3']
        job_id='job-'+secrets.token_hex(8)
        job={'id':job_id,'action':action,'path':relative,'status':'queued','created':time.time(),'returncode':None,'elapsed':None,'result':None,'output':''}
        with self.job_lock:
            self.jobs[job_id]=job
            self.history.insert(0,job_id)
            self.history=self.history[:100]
        self.executor.submit(self._execute,job_id,args,action)
        return {'job_id':job_id,'status':'queued'}

    def start_proposal_job(self,proposal_id,trusted=False):
        if trusted is not True:raise GuardError('运行生成的 C++ 候选前，必须单独确认源码已人工审查且可信')
        candidate=self.proposals.check_validation(proposal_id)
        job_id='job-'+secrets.token_hex(8)
        job={'id':job_id,'action':'candidate-validate','path':candidate['manifest'],
             'proposal_id':proposal_id,'status':'queued','created':time.time(),
             'returncode':None,'elapsed':None,'result':None,'output':''}
        with self.job_lock:
            self.jobs[job_id]=job
            self.history.insert(0,job_id);self.history=self.history[:100]
        self.executor.submit(self._execute_proposal,job_id,proposal_id)
        return {'job_id':job_id,'status':'queued'}

    def _execute_proposal(self,job_id,proposal_id):
        with self.job_lock:self.jobs[job_id]['status']='running'
        started=time.monotonic();checks=[];passed=True
        try:
            proposal=self.proposals.check_validation(proposal_id)
            proposal_evidence=ROOT/'.studio-data'/'candidate-evidence'/proposal_id
            proposal_evidence.mkdir(parents=True,exist_ok=True)
            for label,action,path,extra in [
                ('spec-model','verify',proposal['spec'],[]),
                ('spec-gate','gate',proposal['spec'],['--target','model']),
                ('cpp-full','cpp-project-verify',proposal['manifest'],['--full']),
                ('cpp-gate','cpp-project-gate',proposal['manifest'],[])]:
                self.proposals.check_validation(proposal_id)
                args=[sys.executable,'-m','axiom','--workspace',str(proposal_evidence),action,
                      str(allowed_file(path)),*extra]
                env=dict(os.environ);env['PYTHONPATH']=str(ENGINE/'src')
                proc=subprocess.Popen(args,cwd=WORKSPACE,env=env,stdin=subprocess.DEVNULL,
                      stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=(os.name=='posix'))
                try:out,err=proc.communicate(timeout=120 if action=='cpp-project-verify' else 45)
                except subprocess.TimeoutExpired:
                    if os.name=='posix':os.killpg(proc.pid,signal.SIGKILL)
                    else:proc.kill()
                    out,err=proc.communicate()
                    raise ProposalError('验证阶段超时: '+label)
                try:result=json.loads(out)
                except ValueError:result={'raw_output':out[:6000].decode('utf-8','replace')}
                check={'step':label,'returncode':proc.returncode,
                       'outcome':result.get('decision') or result.get('verification',{}).get('outcome')
                                 or result.get('report',{}).get('outcome') or result.get('outcome'),
                       'result':result}
                checks.append(check)
                if proc.returncode!=0 or (label.endswith('gate') and result.get('decision')!='Approved'):
                    passed=False;break
            final=self.proposals.finish_validation(proposal_id,passed,checks)
            result={'proposal_id':proposal_id,'decision':'Approved' if passed and final['status']=='verified' else 'Blocked',
                    'assurance':'cpp-tested-prototype','checks':checks,'proposal_status':final['status'],
                    'note':'测试级准入；不代表通用正确性证明或生产发布许可'}
            passed=passed and result['decision']=='Approved'
            output=json.dumps(result,ensure_ascii=False,indent=2)
            rc=0 if passed else 2
        except Exception as exc:
            passed=False;rc=-1
            output=f'{type(exc).__name__}: {exc}'
            try:self.proposals.finish_validation(proposal_id,False,checks)
            except ProposalError:pass
            result={'decision':'Blocked','error':str(exc),'checks':checks}
        with self.job_lock:
            self.jobs[job_id].update(status='finished' if passed else 'failed',returncode=rc,
                  elapsed=round(time.monotonic()-started,3),result=result,output=output[:2*MAX_JSON])

    def _execute(self,job_id,args,action):
        with self.job_lock:self.jobs[job_id]['status']='running'
        started=time.monotonic()
        env=dict(os.environ)
        env['PYTHONPATH']=str(ENGINE/'src')
        env['PYTHONUNBUFFERED']='1'
        try:
            # Separate session allows terminating descendant compilers on timeout.
            p=subprocess.Popen(args,cwd=WORKSPACE,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=(os.name=='posix'))
            try:
                out,err=p.communicate(timeout=ACTION_LIMITS.get(action,55))
            except subprocess.TimeoutExpired:
                if os.name=='posix':os.killpg(p.pid,signal.SIGKILL)
                else:p.kill()
                out,err=p.communicate()
                raise TimeoutError('操作超过资源时间预算，已终止进程组')
            raw=out[:2*MAX_JSON].decode('utf-8','replace')
            stderr=err[:20000].decode('utf-8','replace')
            try:result=json.loads(raw)
            except (ValueError,TypeError):result=None
            result_out=raw+(('\n\n[stderr]\n'+stderr) if stderr else '')
            stat='finished' if p.returncode==0 else 'failed'
            rc=p.returncode
        except Exception as exc:
            result=None;result_out=f'{type(exc).__name__}: {exc}';stat='failed';rc=-1
        with self.job_lock:
            job=self.jobs[job_id]
            job.update(status=stat,returncode=rc,elapsed=round(time.monotonic()-started,3),result=result,output=result_out[:2*MAX_JSON])

    def job(self,id):
        with self.job_lock:
            if id not in self.jobs:raise GuardError('未知任务 ID')
            return dict(self.jobs[id])

    def recent(self):
        with self.job_lock:
            return [dict(self.jobs[x]) for x in self.history[:30]]

    def evidence(self):
        from sqlite3 import connect
        db=EVIDENCE/'index.sqlite3'
        if not db.exists():return {'runs':[],'gates':[]}
        with connect(f'file:{db}?mode=ro',uri=True,timeout=2) as cx:
            cx.row_factory=__import__('sqlite3').Row
            runs=[dict(x) for x in cx.execute('SELECT run_id,spec_digest,outcome,created_at FROM runs ORDER BY created_at DESC LIMIT 60')]
            gates=[dict(x) for x in cx.execute('SELECT gate_id,target,decision,created_at FROM gates ORDER BY created_at DESC LIMIT 40')]
        return {'runs':runs,'gates':gates}

class Handler(BaseHTTPRequestHandler):
    server_version='AxiomStudio/2.0'
    def log_message(self,fmt,*args):
        pass
    def _json(self,status,obj):
        raw=json.dumps(obj,ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Length',str(len(raw)))
        self.end_headers();self.wfile.write(raw)
    def _send_file(self,path,ctype):
        raw=path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type',ctype)
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'")
        self.send_header('Content-Length',str(len(raw)))
        self.end_headers();self.wfile.write(raw)
    def _authorized(self):
        qs=urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        return secrets.compare_digest(self.headers.get('X-Axiom-Token','') or (qs.get('token',[''])[0]),self.server.studio.token)
    def do_GET(self):
        path=urllib.parse.urlparse(self.path).path
        try:
            if path=='/health':return self._json(200,{'service':'Axiom Studio','version':'2.0.1','local_only':True})
            if path in ['/app.js','/candidates.js','/projects.js','/launchpad.js','/workorders.js','/cockpit.js','/journey.js','/spec_workshop.js','/design_review.js','/pilot.js','/assembly.js','/task_graph.js','/milestone20.js','/styles.css','/light.css']:
                return self._send_file(STATIC/path[1:],'text/javascript; charset=utf-8' if path.endswith('.js') else 'text/css; charset=utf-8')
            if not self._authorized():return self._json(403,{'error':'请从启动终端给出的安全访问链接打开 IDE。'})
            if path in ['/','/index.html']:return self._send_file(STATIC/'index.html','text/html; charset=utf-8')
            if path in ['/app.js','/candidates.js','/projects.js','/launchpad.js','/workorders.js','/cockpit.js','/journey.js','/spec_workshop.js','/design_review.js','/pilot.js','/assembly.js','/task_graph.js','/milestone20.js','/styles.css','/light.css']:
                return self._send_file(STATIC/path[1:],'text/javascript; charset=utf-8' if path.endswith('.js') else 'text/css; charset=utf-8')
            q=urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if path=='/api/runner/export':
                raw,filename=self.server.studio.production_runner.export(q.get('id',[''])[0])
                self.send_response(200)
                self.send_header('Content-Type','application/zip')
                self.send_header('Cache-Control','no-store')
                self.send_header('X-Content-Type-Options','nosniff')
                self.send_header('Content-Disposition',f'attachment; filename={filename}')
                self.send_header('Content-Length',str(len(raw)))
                self.end_headers();self.wfile.write(raw);return
            if path=='/api/milestone20/list':return self._json(200,self.server.studio.milestone20.list(q.get('project_id',[''])[0] or None))
            if path=='/api/milestone20/get':return self._json(200,self.server.studio.milestone20.get(q.get('id',[''])[0]))
            if path=='/api/milestone20/handoff':return self._json(200,self.server.studio.milestone20.handoff(q.get('id',[''])[0]))
            if path=='/api/agents/get':return self._json(200,self.server.studio.agent_forge.get(q.get('id',[''])[0]))
            if path=='/api/agents/list':return self._json(200,self.server.studio.agent_forge.list(q.get('graph_id',[''])[0]))
            if path=='/api/fleet/get':return self._json(200,self.server.studio.fleet.get(q.get('id',[''])[0]))
            if path=='/api/fleet/handoff':return self._json(200,self.server.studio.fleet.handoff(q.get('id',[''])[0]))
            if path=='/api/task-graph/targets':return self._json(200,self.server.studio.assembly.targets(q.get('project_id',[''])[0]))
            if path=='/api/task-graph/list':return self._json(200,self.server.studio.task_graphs.list(q.get('project_id',[''])[0] or None))
            if path=='/api/task-graph/get':return self._json(200,self.server.studio.task_graphs.get(q.get('id',[''])[0]))
            if path=='/api/task-graph/handoff':return self._json(200,self.server.studio.task_graphs.handoff(q.get('id',[''])[0]))
            if path=='/api/assembly/targets':return self._json(200,self.server.studio.assembly.targets(q.get('project_id',[''])[0]))
            if path=='/api/assembly/list':return self._json(200,self.server.studio.assembly.list(q.get('project_id',[''])[0] or None))
            if path=='/api/assembly/get':return self._json(200,self.server.studio.assembly.get(q.get('id',[''])[0]))
            if path=='/api/assembly/poll':return self._json(200,self.server.studio.assembly.poll(q.get('id',[''])[0]))
            if path=='/api/assembly/handoff':return self._json(200,self.server.studio.assembly.handoff(q.get('id',[''])[0]))
            if path=='/api/pilot/list':return self._json(200,self.server.studio.pilot.list())
            if path=='/api/pilot/get':return self._json(200,self.server.studio.pilot.get(q.get('id',[''])[0]))
            if path=='/api/pilot/audit':return self._json(200,self.server.studio.pilot.audit(q.get('id',[''])[0]))
            if path=='/api/pilot/handoff':return self._json(200,self.server.studio.pilot.handoff(q.get('id',[''])[0]))
            if path=='/api/cockpit':return self._json(200,self.server.studio.cockpit.snapshot())
            if path=='/api/design-review/inspect':return self._json(200,self.server.studio.design_review.inspect(q.get('id',[''])[0],q.get('candidate',[''])[0]))
            if path=='/api/design-review/compare':return self._json(200,self.server.studio.design_review.compare(q.get('id',[''])[0],q.get('candidate',[])))
            if path=='/api/spec-workshop/task':return self._json(200,self.server.studio.spec_workshop.task(q.get('id',[''])[0]))
            if path=='/api/spec-workshop/list':return self._json(200,{'candidates':self.server.studio.spec_workshop.list(q.get('id',[''])[0])})
            if path=='/api/spec-workshop/get':return self._json(200,self.server.studio.spec_workshop.get(q.get('candidate',[''])[0]))
            if path=='/api/intent/plan':return self._json(200,self.server.studio.intent_spec.get(q.get('id',[''])[0]))
            if path=='/api/intent/task':return self._json(200,self.server.studio.intent_spec.design_task(q.get('id',[''])[0]))
            if path=='/api/journey':return self._json(200,self.server.studio.journey.snapshot())
            if path=='/api/doctor':return self._json(200,self.server.studio.cockpit.doctor())
            if path=='/api/workorders':return self._json(200,{'workorders':self.server.studio.workorders.list()})
            if path=='/api/workorder':return self._json(200,self.server.studio.workorders.get(q.get('id',[''])[0]))
            if path=='/api/workorder/poll':return self._json(200,self.server.studio.workorders.poll(q.get('id',[''])[0]))
            if path=='/api/workorder/feedback':return self._json(200,self.server.studio.workorders.feedback(q.get('id',[''])[0]))
            if path=='/api/runner/list':return self._json(200,self.server.studio.production_runner.list())
            if path=='/api/runner/get':return self._json(200,self.server.studio.production_runner.report(q.get('id',[''])[0]))
            if path=='/api/launch/templates':return self._json(200,self.server.studio.launchpad.templates())
            if path=='/api/launch/queue':return self._json(200,self.server.studio.launchpad.queue())
            if path=='/api/launch/export':
                raw,filename=self.server.studio.launchpad.export(q.get('id',[''])[0])
                self.send_response(200)
                self.send_header('Content-Type','application/zip')
                self.send_header('Cache-Control','no-store')
                self.send_header('X-Content-Type-Options','nosniff')
                self.send_header('Content-Disposition',f'attachment; filename={filename}')
                self.send_header('Content-Length',str(len(raw)))
                self.end_headers();self.wfile.write(raw);return
            if path=='/api/projects':return self._json(200,self.server.studio.flow.overview())
            if path=='/api/project':return self._json(200,self.server.studio.flow.get(q.get('id',[''])[0]))
            if path=='/api/project/events':return self._json(200,{'events':self.server.studio.flow.events(q.get('id',[''])[0])})
            if path=='/api/project/audit':return self._json(200,self.server.studio.flow.audit(q.get('id',[''])[0]))
            if path=='/api/batch/list':return self._json(200,self.server.studio.batches.list(q.get('project_id',[''])[0]))
            if path=='/api/batch/get':return self._json(200,self.server.studio.batches.get(q.get('id',[''])[0]))
            if path=='/api/batch/compare':return self._json(200,self.server.studio.batches.compare(q.get('id',[''])[0]))
            if path=='/api/batch/repair':return self._json(200,self.server.studio.batches.repair_packet(q.get('id',[''])[0],q.get('option_id',[''])[0]))
            if path=='/api/batch/audit':return self._json(200,self.server.studio.batches.audit(q.get('id',[''])[0]))
            if path=='/api/factory/campaign':return self._json(200,self.server.studio.factory.get(q.get('id',[''])[0]))
            if path=='/api/factory/list':return self._json(200,self.server.studio.factory.list(q.get('project_id',[''])[0]))
            if path=='/api/factory/poll':return self._json(200,self.server.studio.factory.poll(q.get('id',[''])[0]))
            if path=='/api/factory/repair':return self._json(200,self.server.studio.factory.repair_packet(q.get('id',[''])[0]))
            if path=='/api/factory/events':return self._json(200,self.server.studio.factory.events(q.get('id',[''])[0]))
            if path=='/api/production/draft':return self._json(200,self.server.studio.production.draft(q.get('id',[''])[0]))
            if path=='/api/production/status':return self._json(200,self.server.studio.production.overview(q.get('id',[''])[0]))
            if path=='/api/production/graph':return self._json(200,self.server.studio.production.graph(q.get('id',[''])[0]))
            if path=='/api/production/task':return self._json(200,self.server.studio.production.task_packet(q.get('id',[''])[0]))
            if path=='/api/production/passports':return self._json(200,self.server.studio.production.passports(q.get('id',[''])[0]))
            if path=='/api/providers':return self._json(200,self.server.studio.proposals.model_config())
            if path=='/api/proposals':return self._json(200,{'proposals':self.server.studio.proposals.list()})
            if path=='/api/proposal':return self._json(200,self.server.studio.proposals.get(q.get('id',[''])[0]))
            if path=='/api/tree':return self._json(200,{'files':tree()})
            if path=='/api/file':
                file=allowed_file(q.get('path',[''])[0]);val=file.read_text('utf-8')
                return self._json(200,{'path':file.relative_to(WORKSPACE).as_posix(),'content':val,'sha256':hashlib.sha256(val.encode()).hexdigest()})
            if path=='/api/job':return self._json(200,self.server.studio.job(q.get('id',[''])[0]))
            if path=='/api/history':return self._json(200,{'jobs':self.server.studio.recent()})
            if path=='/api/evidence':return self._json(200,self.server.studio.evidence())
            if path=='/api/ai-task':
                rel=q.get('path',[''])[0]
                source=allowed_file(rel)
                if source.suffix!='.ax':raise GuardError('AI 构造任务仅支持 .ax 规格')
                env=dict(os.environ);env['PYTHONPATH']=str(ENGINE/'src')
                cmd=[sys.executable,'-m','axiom','--workspace',str(EVIDENCE),'plan',str(source)]
                proc=subprocess.run(cmd,cwd=WORKSPACE,env=env,capture_output=True,text=True,timeout=15)
                if proc.returncode!=0:raise GuardError('规格尚未通过语义检查，无法生成候选任务包')
                plan=json.loads(proc.stdout)
                raw=source.read_text(encoding='utf-8')
                prompt=('Axiom Studio / AI 构造任务（人工批准范围内）\n'
                  +'目标：根据以下 Axiom 行为规格，生成一个可审阅的 C++20 候选实现。\n'
                  +'禁止：修改规格、不变量、验证器、证据或 Gate 策略；伪造验证结果；声称测试等于形式化证明。\n'
                  +'请给出：C++ 代码、状态和输入输出映射、边界条件、可能未覆盖的情况、建议验证步骤。\n'
                  +'所有候选均须先人工审查，再交由独立的 Axiom 验证器检查。\n'
                  +f"规格路径：{rel}\n规格摘要：{plan['spec_digest']}\n"
                  +'\n验证义务：\n'+json.dumps(plan['obligations'],ensure_ascii=False,indent=2)
                  +'\n\n行为规格：\n'+raw)
                return self._json(200,{'prompt':prompt,'spec_digest':plan['spec_digest'],'obligations':len(plan['obligations']),
                                       'generator_connected':False,'note':'仅生成审核任务包；未连接任何外部 AI 模型，也不会自动改写项目文件。'})
            if path=='/api/meta':return self._json(200,{'version':'2.0.1','architecture':'workflow-first','engine_version':'1.0.0','workspace':str(WORKSPACE),'safe_cxx_execution':False,'files_count':len(tree())})
            return self._json(404,{'error':'Not found'})
        except (ConflictError,FlowConflict) as exc:return self._json(409,{'error':str(exc)})
        except (GuardError,ProposalError,FlowError,LaunchError,RunnerError,WorkOrderError,AssemblyError,TaskGraphError,FleetError,AgentForgeError,MilestoneError,ValueError,UnicodeError,OSError) as exc:return self._json(400,{'error':str(exc)})
    def do_POST(self):
        try:
            if not self._authorized():return self._json(403,{'error':'Unauthorized'})
            n=int(self.headers.get('Content-Length','0'))
            if n<=0 or n>MAX_JSON:raise GuardError('请求长度超限')
            data=json.loads(self.rfile.read(n))
            path=urllib.parse.urlparse(self.path).path
            if path=='/api/milestone20/create':return self._json(201,self.server.studio.milestone20.create(data.get('project_id'),data.get('graph_id'),data.get('previous_id')))
            if path=='/api/milestone20/start':return self._json(202,self.server.studio.milestone20.start(data.get('id'),data.get('trusted') is True))
            if path=='/api/agents/batch':return self._json(201,self.server.studio.agent_forge.run_many(data.get('graph_id'),data.get('targets'),data.get('consent') is True,data.get('rounds',1),data.get('concurrency',2)))
            if path=='/api/agents/run':return self._json(201,self.server.studio.agent_forge.run(data.get('graph_id'),data.get('target'),data.get('consent') is True,data.get('rounds',1),data.get('feedback')))
            if path=='/api/agents/stage':return self._json(200,self.server.studio.agent_forge.stage(data.get('id'),data.get('candidate_sha256'),data.get('acknowledge') is True))
            if path=='/api/agents/impact':return self._json(200,self.server.studio.agent_forge.impact(data.get('graph_id'),data.get('targets')))
            if path=='/api/fleet/prepare':return self._json(201,self.server.studio.fleet.prepare(data.get('id'),data.get('parallelism',3)))
            if path=='/api/fleet/stage':return self._json(201,self.server.studio.fleet.stage(data.get('id'),data.get('target'),data.get('code'),data.get('packet_digest')))
            if path=='/api/fleet/promote':return self._json(200,self.server.studio.fleet.promote(data.get('id'),data.get('target'),data.get('candidate_sha256'),data.get('acknowledge_rebase') is True))
            if path=='/api/fleet/feedback':return self._json(200,self.server.studio.fleet.feedback(data.get('id'),data.get('target')))
            if path=='/api/task-graph/create':return self._json(201,self.server.studio.task_graphs.create(data.get('project_id'),data.get('tasks')))
            if path=='/api/task-graph/start':return self._json(200,self.server.studio.task_graphs.start(data.get('id'),data.get('target')))
            if path=='/api/task-graph/sync':return self._json(200,self.server.studio.task_graphs.sync(data.get('id')))
            if path=='/api/assembly/create':return self._json(201,self.server.studio.assembly.create(data.get('project_id'),data.get('target')))
            if path=='/api/assembly/candidate':return self._json(201,self.server.studio.assembly.candidate(data.get('id'),data.get('code'),data.get('consent') is True))
            if path=='/api/assembly/review':return self._json(200,self.server.studio.assembly.review(data.get('id'),data.get('digest'),data.get('approved') is True))
            if path=='/api/assembly/apply':return self._json(200,self.server.studio.assembly.apply(data.get('id'),data.get('confirmation')))
            if path=='/api/assembly/verify':return self._json(202,self.server.studio.assembly.verify(data.get('id'),data.get('trusted') is True))
            if path=='/api/assembly/revert':return self._json(200,self.server.studio.assembly.revert(data.get('id'),data.get('confirmation')))
            if path=='/api/pilot/create':return self._json(201,self.server.studio.pilot.create(data.get('project_id')))
            if path=='/api/pilot/advance':return self._json(202,self.server.studio.pilot.advance_safe(data.get('id'),data.get('revision'),data.get('baseline_digest')))
            if path=='/api/workorder/create':return self._json(201,self.server.studio.workorders.create(data.get('manifest'),data.get('target'),data.get('goal'),data.get('max_attempts',3)))
            if path=='/api/workorder/generate':return self._json(201,self.server.studio.workorders.generate(data.get('id'),data.get('consent')))
            if path=='/api/workorder/submit':return self._json(201,self.server.studio.workorders.submit(data.get('id'),data.get('code')))
            if path=='/api/workorder/review':return self._json(200,self.server.studio.workorders.review(data.get('id'),data.get('digest'),data.get('approved')))
            if path=='/api/workorder/apply':return self._json(200,self.server.studio.workorders.apply(data.get('id'),data.get('confirmation')))
            if path=='/api/workorder/verify':return self._json(202,self.server.studio.workorders.verify(data.get('id'),data.get('trusted')))
            if path=='/api/workorder/revert':return self._json(200,self.server.studio.workorders.revert(data.get('id'),data.get('confirmation')))
            if path=='/api/runner/plan':
                return self._json(201,self.server.studio.production_runner.create(data.get('project_ids'),data.get('retry_failed',False)))
            if path=='/api/runner/retry':
                return self._json(201,self.server.studio.production_runner.retry(data.get('id')))
            if path=='/api/runner/start':
                return self._json(202,self.server.studio.production_runner.start(data.get('id')))
            if path=='/api/spec-workshop/create':return self._json(201,self.server.studio.spec_workshop.create(data.get('id'),data.get('source'),data.get('notes','')))
            if path=='/api/spec-workshop/generate':return self._json(201,self.server.studio.spec_workshop.generate(data.get('id'),data.get('consent')))
            if path=='/api/spec-workshop/check':return self._json(200,self.server.studio.spec_workshop.assess(data.get('candidate')))
            if path=='/api/spec-workshop/promote':return self._json(201,self.server.studio.spec_workshop.promote(data.get('candidate'),data.get('digest'),data.get('mappings'),data.get('confirmation')))
            if path=='/api/intent/save':return self._json(200,self.server.studio.intent_spec.save(data.get('id'),data.get('items'),data.get('version'),data.get('baseline')))
            if path=='/api/intent/confirm':return self._json(201,self.server.studio.intent_spec.confirm(data.get('id'),data.get('version'),data.get('digest'),data.get('confirmation')))
            if path=='/api/journey/start':
                return self._json(201,self.server.studio.journey.start(data.get('scenario'),data.get('name'),data.get('goal')))
            if path=='/api/launch/create':
                return self._json(201,self.server.studio.launchpad.create(data.get('template'),data.get('slug'),data.get('name'),data.get('goal')))
            if path=='/api/batch/create':return self._json(201,self.server.studio.batches.create(data.get('project_id'),data.get('targets')))
            if path=='/api/batch/stage':return self._json(201,self.server.studio.batches.stage(data.get('id'),data.get('name'),data.get('replacements')))
            if path=='/api/batch/evaluate':return self._json(200,self.server.studio.batches.evaluate(data.get('id'),data.get('option_id'),data.get('trusted') is True))
            if path=='/api/batch/select':return self._json(200,self.server.studio.batches.select(data.get('id'),data.get('option_id'),data.get('digest'),data.get('confirmation')))
            if path=='/api/batch/apply':return self._json(200,self.server.studio.batches.apply(data.get('id'),data.get('digest'),data.get('confirmation')))
            if path=='/api/batch/verify-live':return self._json(200,self.server.studio.batches.verify_live(data.get('id'),data.get('trusted') is True))
            if path=='/api/batch/decide':return self._json(200,self.server.studio.batches.decide(data.get('id'),data.get('digest'),data.get('confirmation')))
            if path=='/api/batch/rollback':return self._json(200,self.server.studio.batches.rollback(data.get('id'),data.get('confirmation')))
            if path=='/api/factory/create':
                return self._json(201,self.server.studio.factory.create(data.get('project_id'),data.get('target')))
            if path=='/api/factory/verify-spec':
                return self._json(200,self.server.studio.factory.verify_spec(data.get('id')))
            if path=='/api/factory/candidate':
                return self._json(201,self.server.studio.factory.candidate(data.get('id'),data.get('code'),data.get('consent') is True))
            if path=='/api/factory/review':
                return self._json(200,self.server.studio.factory.review(data.get('id'),data.get('sha256'),data.get('confirmation')))
            if path=='/api/factory/apply':
                return self._json(200,self.server.studio.factory.apply(data.get('id'),data.get('confirmation')))
            if path=='/api/factory/validate':
                return self._json(202,self.server.studio.factory.validate(data.get('id'),data.get('trusted') is True))
            if path=='/api/factory/decide':
                return self._json(200,self.server.studio.factory.decide(data.get('id'),data.get('sha256'),data.get('confirmation')))
            if path=='/api/production/freeze':
                return self._json(201,self.server.studio.production.freeze(data.get('id'),data.get('requirements'),data.get('baseline')))
            if path=='/api/production/passport':
                return self._json(201,self.server.studio.production.issue_passport(data.get('id'),data.get('confirmation'),data.get('contract_digest')))
            if path=='/api/project/create':
                return self._json(201,self.server.studio.flow.create(data.get('name'),data.get('goal'),data.get('spec'),data.get('manifest')))
            if path=='/api/project/fork':
                return self._json(201,self.server.studio.flow.fork(data.get('id'),data.get('name'),data.get('goal'),data.get('spec'),data.get('manifest')))
            if path=='/api/project/verify-spec':
                return self._json(200,self.server.studio.flow.verify_spec(data.get('id')))
            if path=='/api/project/attach':
                return self._json(200,self.server.studio.flow.attach_candidate(data.get('id'),data.get('candidate_id')))
            if path=='/api/project/sync':
                return self._json(200,self.server.studio.flow.sync(data.get('id')))
            if path=='/api/project/decide':
                return self._json(200,self.server.studio.flow.decide(data.get('id'),data.get('confirmation'),data.get('candidate_digest')))
            if path=='/api/proposal/create':
                return self._json(201,self.server.studio.proposals.create(
                    data.get('manifest'),data.get('target'),data.get('code')))
            if path=='/api/proposal/generate':
                return self._json(201,self.server.studio.proposals.generate(
                    data.get('manifest'),data.get('target'),data.get('consent')))
            if path=='/api/proposal/review':
                return self._json(200,self.server.studio.proposals.review(
                    data.get('id'),data.get('digest'),data.get('approved')))
            if path=='/api/proposal/apply':
                return self._json(200,self.server.studio.proposals.apply(data.get('id')))
            if path=='/api/proposal/validate':
                return self._json(202,self.server.studio.start_proposal_job(data.get('id'),data.get('trusted')))
            if path=='/api/create':
                rel=data.get('path')
                if not isinstance(rel,str) or len(rel)>180 or '\\' in rel:raise GuardError('无效文件名')
                name=Path(rel)
                if name.is_absolute() or '..' in name.parts or name.suffix.lower() not in ALLOWED_EXT:raise GuardError('不允许的文件名/后缀')
                target=(WORKSPACE/name).resolve(strict=False)
                if not target.is_relative_to(WORKSPACE.resolve()) or not target.parent.is_dir():
                    raise GuardError('新文件只能放在现有工作区文件夹内')
                if name.suffix=='.ax':
                    initial=('model NewModel {\n  type Flag = Bool\n  state { on: Flag }\n'
                      '  init { on == false }\n  action toggle() -> Bool {\n'
                      '    case otherwise {\n      modifies { on }\n'
                      "      ensures on' == !on && result == on'\n"
                      '    }\n  }\n  property Valid { always on == true || on == false }\n'
                      '  observe { toggle.input, toggle.output }\n}\n')
                elif name.suffix in ('.cpp','.hpp','.cc','.h','.c'):initial='// Axiom Studio · trusted candidate (review before execution)\n'
                elif name.suffix=='.json':initial='{}\n'
                elif name.suffix=='.md':initial=f'# {name.stem}\n'
                else:initial=''
                try:
                    with open(target,'xb') as f:f.write(initial.encode('utf-8'))
                except FileExistsError:raise GuardError('文件已存在，请选择其他文件名')
                return self._json(201,{'created':True,'path':name.as_posix()})
            if path=='/api/save':
                dest=allowed_file(data.get('path'))
                content=data.get('content')
                if not isinstance(content,str) or len(content.encode('utf-8'))>MAX_FILE:raise GuardError('内容超过 1 MiB 限额')
                orig=hashlib.sha256(dest.read_bytes()).hexdigest()
                if data.get('sha256')!=orig: return self._json(409,{'error':'文件已经被其他操作修改；请重新读取后再保存。'})
                import tempfile
                fd,tmp=tempfile.mkstemp(prefix='.ax-edit-',dir=dest.parent)
                try:
                    with os.fdopen(fd,'wb') as f:
                        f.write(content.encode('utf-8'));f.flush();os.fsync(f.fileno())
                    os.replace(tmp,dest)
                finally:
                    if os.path.exists(tmp):os.unlink(tmp)
                return self._json(200,{'saved':True,'sha256':hashlib.sha256(content.encode()).hexdigest()})
            if path=='/api/run':return self._json(202,self.server.studio.start_job(data.get('action'),data.get('path'),data.get('other'),data.get('trusted',False) is True,data.get('candidate')))
            return self._json(404,{'error':'Not found'})
        except (ConflictError,FlowConflict) as exc:return self._json(409,{'error':str(exc)})
        except (GuardError,ProposalError,FlowError,LaunchError,RunnerError,WorkOrderError,AssemblyError,TaskGraphError,FleetError,AgentForgeError,MilestoneError,ValueError,TypeError,KeyError,UnicodeError,OSError) as exc:return self._json(400,{'error':str(exc)})

def create_server(port=8765):
    studio=Studio()
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.studio=studio
    return server

def main():
    arg=argparse.ArgumentParser(description='Axiom Studio — local IDE')
    arg.add_argument('--port',type=int,default=8765)
    arg.add_argument('--no-browser',action='store_true')
    args=arg.parse_args()
    server=create_server(args.port)
    url=f'http://127.0.0.1:{server.server_port}/?token={server.studio.token}'
    print('Axiom Studio running on loopback (trusted local IDE).',flush=True)
    print('Open:',url,flush=True)
    if not args.no_browser:webbrowser.open(url)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.shutdown();server.server_close()

if __name__=='__main__':main()
