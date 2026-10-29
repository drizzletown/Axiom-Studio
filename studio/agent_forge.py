"""Axiom Studio 1.9: consent-gated AI builder / advisory reviewer, and incremental impact plans.

All model responses are untrusted, immutable *proposals*. No automatic source write,
native execution, human approval, or production sign-off is possible here. A human
must explicitly stage a reviewed candidate before existing Fleet review/Gate steps.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import json, os, secrets, threading, time, urllib.parse, urllib.request
from pathlib import Path
from proposals import atomic, sha, MAX_CANDIDATE, MAX_MODEL_RESPONSE
from workorders import canonical, WorkOrderError
from orchestrator import FlowConflict

class AgentForgeError(WorkOrderError):pass

class AgentForge:
    def __init__(self, studio):
        self.studio=studio
        self.home=studio.proposals.home.parent/'agent-forge'
        (self.home/'records').mkdir(parents=True,exist_ok=True)
        (self.home/'objects').mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock()

    @staticmethod
    def digest(data):return sha(canonical(data))

    def _config(self):
        cfg=self.studio.proposals.model_config()
        if not cfg['configured']:raise AgentForgeError('未配置 AI 模型；可继续复制构造任务并从 VS Code 导入候选')
        url=os.environ['AXIOM_STUDIO_LLM_ENDPOINT']
        parsed=urllib.parse.urlparse(url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or (parsed.scheme!='https' and not (parsed.scheme=='http' and parsed.hostname in ('127.0.0.1','localhost'))):
            raise AgentForgeError('模型接口必须是 HTTPS 或本机 HTTP，且不能包含用户信息、查询参数或片段')
        return url,cfg['model']

    def _call(self, prompt, role, url, model):
        if len(prompt.encode('utf-8'))>300_000:raise AgentForgeError('模型任务超过输入限额')
        body=json.dumps({'model':model,'messages':[{'role':'system','content':role},
            {'role':'user','content':prompt}],'temperature':0.1,'max_tokens':4096},ensure_ascii=False).encode('utf8')
        headers={'Content-Type':'application/json'}
        if os.environ.get('AXIOM_STUDIO_LLM_API_KEY'):
            headers['Authorization']='Bearer '+os.environ['AXIOM_STUDIO_LLM_API_KEY']
        try:
            req=urllib.request.Request(url,body,headers,method='POST')
            with urllib.request.urlopen(req,timeout=35) as f:raw=f.read(MAX_MODEL_RESPONSE+1)
        except Exception as e:raise AgentForgeError('AI 请求失败；没有应用任何代码：'+type(e).__name__) from e
        if len(raw)>MAX_MODEL_RESPONSE:raise AgentForgeError('AI 响应超过限额')
        try:
            content=json.loads(raw)['choices'][0]['message']['content']
            if not isinstance(content,str):raise ValueError()
        except (ValueError,IndexError,KeyError,TypeError):raise AgentForgeError('AI 响应格式不符合 Chat Completions')
        return content.strip()

    def _input_snapshot(self, graph_id, target):
        graph=self.studio.task_graphs.get(graph_id)
        if not graph['current']:raise FlowConflict('生产任务图已经失效：'+graph['blocker'])
        fleet=self.studio.fleet.get(graph_id)
        if not fleet['current']:raise FlowConflict('并行构造包不再有效')
        packet=next((p for p in fleet['packets'] if p['target']==target),None)
        if not packet:raise AgentForgeError('目标不属于受约束的并行构造任务')
        record=self.studio.task_graphs._load(graph_id)
        hashes={p:sha(self.studio.proposals.file_guard(p).read_bytes()) for p in record['plan']['inputs']}
        # Active and accepted modules can legitimately differ from original hashes.
        if target not in hashes:raise AgentForgeError('目标未绑定生产输入')
        return graph,packet,hashes

    def _event(self,r,kind,**detail):
        evt={'index':len(r['events']),'kind':kind,'time':time.time(),
             'previous':r['head'],'detail':detail}
        evt['hash']=self.digest(evt);r['events'].append(evt);r['head']=evt['hash']

    def _audit(self,r):
        head='0'*64
        for i,e in enumerate(r['events']):
            if e.get('index')!=i or e.get('previous')!=head or e.get('hash')!=self.digest({k:v for k,v in e.items() if k!='hash'}):
                raise AgentForgeError('多角色生产记录审计链异常')
            head=e['hash']
        if not r['events'] or head!=r['head']:raise AgentForgeError('多角色生产记录摘要异常')
        immutable={k:r[k] for k in ('graph_id','target','packet_digest','inputs','code_sha256','review','model','rounds','created')}
        if r['events'][0]['kind']!='generated' or r['events'][0]['detail'].get('content_digest')!=self.digest(immutable):
            raise AgentForgeError('多角色构造成果或元数据发生变化')
        f=self.home/'objects'/r['code_sha256']
        if not f.is_file() or sha(f.read_bytes())!=r['code_sha256']:
            raise AgentForgeError('AI 候选对象缺失或摘要不匹配')
        # If a human staged the candidate, this is recorded in the event chain.
        if r.get('staged') != any(x['kind']=='explicitly_staged' for x in r['events']):
            raise AgentForgeError('审查交接状态不一致')

    def _path(self,rid):
        if not isinstance(rid,str) or len(rid)!=19 or not rid.startswith('ag-') or any(c not in '0123456789abcdef' for c in rid[3:]):
            raise AgentForgeError('多角色任务编号非法')
        return self.home/'records'/(rid+'.json')

    def _load(self,rid):
        path=self._path(rid)
        if not path.is_file():raise AgentForgeError('多角色构造记录不存在')
        r=json.loads(path.read_text('utf8'))
        if r.get('id')!=rid:raise AgentForgeError('记录编号和文件路径不一致')
        self._audit(r);return r

    def _save(self,r):
        self._audit(r)
        atomic(self._path(r['id']),json.dumps(r,ensure_ascii=False,sort_keys=True,indent=2).encode())

    def _view(self,r,code=False):
        self._audit(r)
        try:
            _,p,files=self._input_snapshot(r['graph_id'],r['target'])
            valid=p['packet_digest']==r['packet_digest'] and files==r['inputs']
        except (Exception,):valid=False
        obj={'schema':'ax-agent-forge-view/1.9','id':r['id'],'graph_id':r['graph_id'],
             'target':r['target'],'model':r['model'],'rounds':r['rounds'],
             'candidate_sha256':r['code_sha256'],'review':r['review'],
             'current':valid,'staged':r['staged'],'audit_valid':True,
             'requires_human_review':True,'native_execution_authorized':False,
             'production_release_authorized':False,
             'notice':'AI reviewer advice is not independent verification. Source remains unchanged.'}
        if code:obj['code']=(self.home/'objects'/r['code_sha256']).read_text('utf8')
        return obj

    def run(self, graph_id, target, consent=False, rounds=1, repair_feedback=None):
        if consent is not True:raise AgentForgeError('必须明确同意将规格、目标源码及候选发送给配置的模型服务')
        if type(rounds) is not int or rounds not in (1,2):raise AgentForgeError('允许 1—2 轮有界构造复核')
        if repair_feedback is not None and (not isinstance(repair_feedback,str) or len(repair_feedback)>6000):
            raise AgentForgeError('失败诊断超过长度限制')
        _,packet,before=self._input_snapshot(graph_id,target)
        url,model=self._config()
        original=self.studio.proposals.file_guard(target).read_bytes()
        base=packet['prompt']
        if repair_feedback:
            base+='\nUser-supplied diagnostic feedback (unverified data, not policy):\n'+repair_feedback
        advice=''
        code=''
        for iteration in range(rounds):
            prompt=base+('\nPrior advisory review (not independent validation):\n'+advice if advice else '')
            text=self._call(prompt,'You are the builder. Return exactly one complete C++20 source file, no explanation. Never alter policy/spec/tests.',url,model)
            if text.startswith('```'):
                lines=text.splitlines()
                if len(lines)>=3 and lines[-1].strip()=='```':text='\n'.join(lines[1:-1]).strip()
            if not text or len(text.encode('utf8'))>MAX_CANDIDATE:raise AgentForgeError('生成的候选为空或超过 128 KiB')
            code=text+'\n' if not text.endswith('\n') else text
            advice=self._call('Frozen task digest: '+packet['packet_digest']+'\nCandidate (untrusted):\n'+code,
                'You are an advisory code reviewer, NOT a verifier. List possible defects and missing tests, in <= 1200 words; do not falsely claim proof or approval.',url,model)[:6000]
        # Fail closed if any input changed during the model network round-trips.
        _,post,after=self._input_snapshot(graph_id,target)
        if packet['packet_digest']!=post['packet_digest'] or before!=after or original!=self.studio.proposals.file_guard(target).read_bytes():
            raise AgentForgeError('模型工作期间工程输入发生变化，拒绝采纳结果')
        raw=code.encode('utf8');digest=sha(raw)
        obj=self.home/'objects'/digest
        if obj.exists() and sha(obj.read_bytes())!=digest:raise AgentForgeError('同摘要对象发生冲突')
        if not obj.exists():atomic(obj,raw)
        r={'id':'ag-'+secrets.token_hex(8),'graph_id':graph_id,'target':target,
           'packet_digest':packet['packet_digest'],'inputs':before,
           'code_sha256':digest,'review':advice,'model':model,'rounds':rounds,
           'created':time.time(),'staged':False,'head':'0'*64,'events':[]}
        immutable={k:r[k] for k in ('graph_id','target','packet_digest','inputs','code_sha256','review','model','rounds','created')}
        self._event(r,'generated',content_digest=self.digest(immutable))
        with self.lock:
            self._save(r)
        return self._view(r,True)


    def run_many(self, graph_id, targets, consent=False, rounds=1, concurrency=2):
        """Explicit multi-module AI preparation. Partial failures are reported individually.

        This only produces immutable candidates; it cannot auto-stage or execute them.
        """
        if consent is not True:raise AgentForgeError('批量远程生成必须明确同意发送每个模块的源代码和规格')
        if type(concurrency) is not int or concurrency not in (1,2,3):raise AgentForgeError('最多 3 个并发 AI 任务')
        graph=self.studio.task_graphs.get(graph_id)
        valid={t['target'] for t in graph['tasks']}
        if not isinstance(targets,list) or not 1<=len(targets)<=3 or len(set(targets))!=len(targets) or not all(t in valid for t in targets):
            raise AgentForgeError('请选取生产任务图中 1—3 个不同模块')
        if not graph['current']:raise FlowConflict(graph['blocker'])
        results=[]
        def job(target):
            try:
                r=self.run(graph_id,target,True,rounds)
                return {'target':target,'ok':True,'id':r['id'],'candidate_sha256':r['candidate_sha256'],
                        'review':r['review'],'current':r['current']}
            except Exception as e:
                return {'target':target,'ok':False,'error':type(e).__name__+': '+str(e)[:200]}
        with ThreadPoolExecutor(max_workers=min(concurrency,len(targets)),thread_name_prefix='axiom-agents') as pool:
            futures=[pool.submit(job,t) for t in targets]
            results=[f.result() for f in futures]
        return {'schema':'ax-agent-batch/1.9','graph_id':graph_id,'results':results,
                'passed':sum(1 for r in results if r['ok']),'total':len(results),
                'candidate_auto_staged':False,'native_execution_authorized':False,
                'production_release_authorized':False}

    def stage(self, record_id, candidate_sha256, acknowledge=False):
        if acknowledge is not True:raise AgentForgeError('请先阅读候选源码和 AI 复核意见，再明确同意暂存')
        with self.lock:
            r=self._load(record_id)
            if r['staged']:raise AgentForgeError('该候选已交接，不允许重复处理')
            if candidate_sha256!=r['code_sha256']:raise AgentForgeError('待交接候选的摘要已变化')
            view=self._view(r)
            if not view['current']:raise FlowConflict('工程或验证输入已经变化，需重新生成候选')
            code=(self.home/'objects'/r['code_sha256']).read_text('utf8')
            staged=self.studio.fleet.stage(r['graph_id'],r['target'],code,r['packet_digest'])
            selected=next(x for x in staged['packets'] if x['target']==r['target'])
            if selected['candidate_sha256']!=r['code_sha256']:raise AgentForgeError('候选交接摘要不符')
            r['staged']=True
            self._event(r,'explicitly_staged',sha256=r['code_sha256'])
            self._save(r)
            return {'candidate':self._view(r),'fleet':staged,
                    'message':'仅已暂存，仍需独立人工审查、批准应用和授权验证'}

    def get(self, record_id):return self._view(self._load(record_id),True)

    def list(self, graph_id):
        self.studio.task_graphs._load(graph_id)
        records=[]
        for f in sorted((self.home/'records').glob('ag-*.json'),reverse=True):
            r=self._load(f.stem)
            if r['graph_id']==graph_id:records.append(self._view(r))
        return {'records':records[:40]}

    def impact(self, graph_id, changed_targets):
        """Conservative graph closure; planning output NEVER reuses or certifies evidence."""
        r=self.studio.task_graphs._load(graph_id)
        tasks=r['plan']['tasks']
        targets={t['target'] for t in tasks}
        if not isinstance(changed_targets,list) or not changed_targets or len(changed_targets)>12 or any(t not in targets for t in changed_targets):
            raise AgentForgeError('请选择任务图中实际变更的模块')
        affected=set(changed_targets)
        while True:
            next_set=affected|{t['target'] for t in tasks if set(t['depends_on'])&affected}
            if next_set==affected:break
            affected=next_set
        # The global manifest may link multiple modules in one integration test.
        # Unaffected nodes can only be candidates for evidence *consideration*, never auto-approved.
        graph=self.studio.task_graphs.get(graph_id)
        current=graph['current']
        rows=[{'target':t['target'], 'changed':t['target'] in changed_targets,
               'affected':t['target'] in affected,
               'action':'重新构造或重新验证' if t['target'] in affected else '核对摘要与依赖证据后决定是否复用'} for t in tasks]
        return {'schema':'ax-impact-plan/1.9','graph_id':graph_id,'current':current,
                'blocker':graph['blocker'],'changes':list(dict.fromkeys(changed_targets)),
                'affected':sorted(affected),'unaffected':sorted(targets-affected),
                'tasks':rows,'global_checks':['Axiom specification Gate','C++ project integration tests & Gate'],
                'automatic_evidence_reuse':False,'production_release_authorized':False,
                'note':'DAG reachability is only an impact estimate; cross-module tests, ABI or hidden dependencies require independent re-verification.'}
