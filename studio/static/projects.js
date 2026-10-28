'use strict';
// Project-centered controller. All transitions are validated by the server.
const wf={projects:[],selected:null,detail:null,factory:[],batches:[],workorders:[]};
const wfE=id=>document.getElementById(id);
const wfEsc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const wfApi=async (path,method='GET',data)=>{
  const headers={'X-Axiom-Token':new URLSearchParams(location.search).get('token')||''};
  if(data!==undefined)headers['Content-Type']='application/json';
  const r=await fetch(path,{method,headers,body:data===undefined?undefined:JSON.stringify(data)});
  const v=await r.json();if(!r.ok)throw new Error(v.error||`HTTP ${r.status}`);return v;
};
function wfNotify(message){if(typeof toast==='function')toast(message);else alert(message)}
function showProjects(){['explorer','verify','evidence','ai','history','help'].forEach(v=>wfE(v+'View').classList.add('hidden'));wfE('projectView').classList.remove('hidden');wfE('sidebar-label').textContent='构造工作台';document.querySelectorAll('.rail-btn').forEach(b=>b.classList.toggle('active',b.id==='projectRail'));wfE('projectDashboard').classList.remove('hidden');wfE('welcome').classList.add('hidden');wfE('editorFrame').classList.add('hidden');wfE('currentName').textContent='Projects';wfE('toolbar-name').textContent='可信软件构造';wfE('projectRail').classList.add('active');loadProjects();if(typeof loadLaunchQueue==='function')loadLaunchQueue()}
function wfMetric(name,n,warn){return `<div class="project-metric"><span>${wfEsc(name)}</span><strong class="${warn?'warn':''}">${wfEsc(n)}</strong></div>`}
async function loadProjects(){try{
  const result=await wfApi('/api/projects');wf.projects=result.projects;
  const c=result.counts;wfE('projectMetrics').innerHTML=wfMetric('构造项目',c.total)+wfMetric('待人工决策',c.pending_human,true)+wfMetric('失效 / 待重新验证',c.stale,true)+wfMetric('测试级确认',c.prototype_accepted);
  const e=wfE('projectList');e.replaceChildren();
  if(!wf.projects.length)e.innerHTML='<div class="project-empty">尚无项目。创建项目后，行为规格、候选、验证、证据和演化将在此统一显示。</div>';
  wf.projects.forEach(p=>{const b=document.createElement('button');b.className='project-list-item'+(wf.selected===p.id?' selected':'');b.innerHTML=`<b>${wfEsc(p.name)}</b><small>R${p.revision} · ${wfEsc(p.status_label)}</small><small>${wfEsc(p.spec)}</small>`;b.onclick=()=>selectProject(p.id);e.appendChild(b)});
  if(wf.selected&&!wf.projects.some(p=>p.id===wf.selected))wf.selected=null;
  if(wf.projects.length)await selectProject(wf.selected||wf.projects[0].id,true);
  else{wf.detail=null;wfE('projectDetail').textContent='创建项目，以行为规格为共同基线组织软件构造与可信演化。';wfE('projectStatusLabel').textContent='未选择项目'}
  if(typeof loadLaunchQueue==='function')loadLaunchQueue()
}catch(e){wfNotify('加载项目失败：'+e.message)}}
async function selectProject(id,noReload=false){try{const [p,ev,prod,fc,ba,workorderResults]=await Promise.all([wfApi('/api/project?id='+encodeURIComponent(id)),wfApi('/api/project/events?id='+encodeURIComponent(id)),wfApi('/api/production/status?id='+encodeURIComponent(id)),wfApi('/api/factory/list?project_id='+encodeURIComponent(id)),wfApi('/api/batch/list?project_id='+encodeURIComponent(id)),wfApi('/api/workorders')]);wf.selected=id;wf.detail=p;wf.production=prod;wf.factory=fc.campaigns;wf.batches=ba.batches;wf.workorders=workorderResults.workorders;
  wfE('projectStatusLabel').textContent=p.status_label;
  const flow=['需求 / 规格','模型验证','AI 实现候选','独立检查','证据 / 裁决'];
  const mapping={draft:0,checking:1,spec_blocked:1,spec_ready:2,candidate_review:2,candidate_apply:2,candidate_validate:3,decision_pending:4,blocked:3,accepted_test_only:4,stale:0};
  const index=mapping[p.effective_status]||0;
  let h=`<div class="project-detail-body"><p class="project-goal">${wfEsc(p.goal)}</p><div class="project-flow-steps">${flow.map((f,i)=>`<span class="${i===index?'current':i<index?'complete':''}">${wfEsc(f)}</span>`).join('')}</div>`;
  h+=`<div class="project-kv"><span>行为规格</span><code>${wfEsc(p.spec)}</code></div><div class="project-kv"><span>项目清单</span><code>${wfEsc(p.manifest||'仅抽象模型')}</code></div><div class="project-kv"><span>当前阶段</span><code>${wfEsc(p.status_label)}</code></div><div class="project-kv"><span>实现候选</span><code>${wfEsc(p.candidate_id||'未绑定')}</code></div>`;
  if(p.parent_id)h+=`<div class="project-kv"><span>演化源</span><code>${wfEsc(p.parent_id)}</code></div>`;
  if(p.last_verification){const checks=p.last_verification.steps||[];h+=`<div class="project-verdict">模型验证：${wfEsc(p.last_verification.passed?'Bounded / Approved（限定模型）':'Blocked')}${checks.length?' · '+checks.map(s=>wfEsc(s.action)+': '+wfEsc(s.outcome||s.returncode)).join(' / '):''}</div>`}
  if(p.decision)h+=`<div class="project-verdict">✓ ${wfEsc(p.decision.decision)} · 非生产发布<br>候选 SHA-256：${wfEsc(p.decision.code_sha256)}</div>`;
  // Axiom V0.4: production contract is a first-class workflow artifact.
  h+=`<div class="project-production"><h3>生产契约 · 需求到证据</h3>`;
  if(!prod.contract){h+=`<p>尚未冻结需求—性质映射。模型 Gate 不能替代用户明确的验收意图。</p>`;
    h+=`<button class="tool primary" data-wfa="freeze">从规格建立并确认生产契约</button>`;}
  else{
    h+=`<div class="project-kv"><span>不可变契约 SHA-256</span><code title="${wfEsc(prod.contract_digest)}">${wfEsc(prod.contract_digest.slice(0,32))}…</code></div>`;
    h+=`<div class="project-requirements">${prod.links.map(l=>`<div class="project-req"><b>${wfEsc(l.requirement_id)}</b><span>${wfEsc(l.property||'尚无形式性质')}</span><small>${wfEsc(l.status==='property-linked'?'已映射 · 待验证链支撑':'不可作为自动满足证据')}</small></div>`).join('')}</div>`;
    h+=`<div class="project-action-row"><button class="tool secondary" data-wfa="task">生成约束式 AI 构造任务</button><button class="tool secondary" data-wfa="graph">查看追溯关系图</button><button class="tool secondary" data-wfa="passports">历史生产护照</button>`;
    if(prod.eligible_for_live_recheck)h+=`<button class="tool primary" data-wfa="passport">实时复核并签发测试级护照</button>`;
    h+=`</div>`;
  }
  if(prod.blockers?.length)h+=`<div class="project-blockers"><b>当前生产准入阻断</b>${prod.blockers.map(b=>`<div>• ${wfEsc(b)}</div>`).join('')}</div>`;
  else h+=`<div class="project-verdict">已满足签发前置条件；签发时仍将重新执行实现 Gate。</div>`;
  h+=`<p class="project-assurance">只进行标识级需求—性质映射；不能据此证明自然语言需求与公式语义等价。所有准入仅限测试级原型。</p></div>`;
  h+=`<div class="project-production"><h3>多目标构造与方案比较 · V0.6</h3><p class="project-assurance">冻结契约 → 整套实现方案暂存 → 独立影子验证 → 人工比较 → 多文件受控应用 → 工作区重验 → 测试级人工裁决。复用 VS Code 编辑器，不重复建设代码编辑功能。</p>`;
  if(wf.batches.length){const b=wf.batches[0];
    h+=`<div class="project-kv"><span>生产事务</span><code>${wfEsc(b.id)}</code></div>`;
    h+=`<div class="project-kv"><span>状态</span><code>${wfEsc(b.state)} · ${b.current?'内容仍匹配':'内容需复核'}</code></div>`;
    h+=`<div class="project-req">${b.options.map(o=>`<div><b>${wfEsc(o.name)}</b> · ${wfEsc(o.state)} · <code title="${wfEsc(o.digest)}">${wfEsc(o.digest.slice(0,16))}…</code></div>`).join('')||'暂无方案；提交 AI 或外部工具生成的完整多文件候选 JSON'}</div>`;
    const stage=b.state==='staging';
    h+='<div class="project-action-row">';
    if(stage)h+='<button class="tool primary" data-batch="stage">暂存完整方案</button><button class="tool secondary" data-batch="evaluate">真实验证方案</button><button class="tool secondary" data-batch="select">比较并选择</button>';
    if(b.state==='human_apply')h+='<button class="tool primary" data-batch="apply">人工应用多文件方案</button>';
    if(b.state==='deployed_unverified')h+='<button class="tool primary" data-batch="verify-live">对实际工程重新独立验证</button>';
    if(b.state==='decision_pending')h+='<button class="tool primary" data-batch="decide">人工测试级裁决</button>';
    if(['deployed_unverified','decision_pending','needs_recovery'].includes(b.state))h+='<button class="tool secondary" data-batch="rollback">拒绝方案并回滚</button>';
    h+='<button class="tool secondary" data-batch="compare">方案比较结果</button><button class="tool secondary" data-batch="repair">失败诊断反馈</button><button class="tool secondary" data-batch="audit">事务审计</button></div>';
  }else if(p.status==='spec_ready'&&prod.contract&&p.manifest){h+='<button class="tool primary" data-batch="create">创建多目标构造事务</button>'}
  else h+='<p class="project-assurance">需先冻结契约并通过模型 Gate，方可建立多目标构造任务。</p>';
  h+='</div>';
  h+=`<div class="project-production"><h3>软件生产编排 · V0.5</h3><p class="project-assurance">冻结契约 → 受约束候选 → 人工审查 → 独立验证 → 人工测试级裁决。验证失败不会自动修改规格、测试或 Gate。</p>`;
  if(wf.factory.length){const fc=wf.factory[0];
    h+=`<div class="project-kv"><span>构造任务</span><code>${wfEsc(fc.id)}</code></div><div class="project-verdict">${wfEsc(fc.label)} · ${wfEsc(fc.snapshot.target)}</div>`;
    h+=`<div class="project-flow-steps" style="grid-template-columns:repeat(6,1fr)">${fc.task_dag.map(t=>`<span>${wfEsc(t.id)}</span>`).join('')}</div>`;
    if(fc.diagnostic)h+=`<div class="project-blockers">阻断诊断：${wfEsc(fc.diagnostic.reason)}</div>`;
    h+=`<div class="project-action-row">`;
    const labels={spec_pending:['spec','实际验证规格'],candidate_pending:['candidate','提交 AI 候选'],human_review:['review','人工审查候选'],human_apply:['apply','人工批准应用'],validation_pending:['validate','执行独立验证'],validating:['poll','获取验证结果'],human_decision:['decide','人工原型裁决'],blocked:['repair','导出修复诊断']};
    const next=labels[fc.effective_state];if(next)h+=`<button class="tool primary" data-factory="${next[0]}">${wfEsc(next[1])}</button>`;
    if(fc.effective_state==='validating')h+=`<small class="project-assurance">仅轮询查看状态，不自动重复执行编译。</small>`;
    h+=`<button class="tool secondary" data-factory="events">生产审计</button></div>`;
  }else if(p.manifest&&prod.contract&&!p.stale){h+=`<button class="tool primary" data-factory="create">建立受约束构造活动</button>`;}
  else h+=`<p class="project-assurance">创建活动之前需要 C++ 工程及冻结的生产契约。</p>`;
  h+=`</div>`;
  h+=woSection(p,wf.workorders);
  h+='<div class="project-action-row">';
  if(!p.stale&&['draft','spec_blocked'].includes(p.status))h+=`<button class="tool primary" data-wfa="verify">验证规格 → Gate</button>`;
  if(!p.stale&&p.status==='spec_ready'&&p.manifest)h+=`<button class="tool primary" data-wfa="attach">绑定候选</button>`;
  if(!p.stale&&['candidate_review','candidate_apply','candidate_validate','blocked'].includes(p.status))h+=`<button class="tool primary" data-wfa="candidate">打开候选审查台</button><button class="tool secondary" data-wfa="sync">同步验证状态</button>`;
  if(!p.stale&&p.status==='decision_pending')h+=`<button class="tool primary" data-wfa="decide">人工确认测试级准入</button>`;
  h+=`<button class="tool secondary" data-wfa="fork">建立演化分支</button><button class="tool secondary" data-wfa="audit">审计证据链</button></div>`;
  if(p.stale)h+='<div class="project-verdict">检测到受保护的规格或工程清单变化。旧证据不再作为当前版本准入依据，请创建新演化分支。</div>';
  h+=`<div class="project-events"><h3>流程事件 · ${ev.events.length}</h3>${ev.events.slice(-7).reverse().map(e=>`<div>${wfEsc(e.kind)}<br>${wfEsc(new Date(e.timestamp*1000).toLocaleString())}</div>`).join('')}</div></div>`;
  wfE('projectDetail').innerHTML=h;
  wfE('projectDetail').querySelectorAll('[data-wfa]').forEach(b=>b.onclick=()=>wfAction(b.dataset.wfa));
  wfE('projectDetail').querySelectorAll('[data-factory]').forEach(b=>b.onclick=()=>wfFactoryAction(b.dataset.factory));
  wfE('projectDetail').querySelectorAll('[data-batch]').forEach(b=>b.onclick=()=>wfBatchAction(b.dataset.batch));
  wfE('projectDetail').querySelectorAll('[data-wo]').forEach(b=>b.onclick=()=>woAction(b.dataset.wo));
  if(!noReload)wfE('projectList').querySelectorAll('.project-list-item').forEach((b,i)=>b.classList.toggle('selected',wf.projects[i].id===id));
}catch(e){wfNotify('项目读取失败：'+e.message)}}
async function wfBatchAction(action){
  try{
    const project=wf.detail,b=wf.batches[0];let v;
    if(action==='create'){
      const definition=await wfApi('/api/file?path='+encodeURIComponent(project.manifest));
      const desc=JSON.parse(definition.content);
      const folder=project.manifest.includes('/')?project.manifest.slice(0,project.manifest.lastIndexOf('/')+1):'';
      const targets=(desc.files||[]).filter(x=>/\.(cpp|cc)$/.test(x)&&!/(^|\/)test[_-]/.test(x)).map(x=>folder+x);
      const entered=prompt('输入此构造事务涉及的实现文件（工作区相对路径，用逗号分隔）',targets.join(','));
      if(!entered)return;
      v=await wfApi('/api/batch/create','POST',{project_id:project.id,targets:entered.split(',').map(x=>x.trim())});
    }else if(action==='stage'){
      const name=prompt('此方案的名称','AI 候选 A');if(!name)return;
      const raw=prompt('粘贴由 AI/VS Code 或外部工具准备的 JSON 对象，键为被修改文件名称（例如 ledger.cpp、format.cpp），值为完整源码。此操作仅暂存，不会编译或修改工作区。','{}');if(!raw)return;
      v=await wfApi('/api/batch/stage','POST',{id:b.id,name,replacements:JSON.parse(raw)});
    }else if(action==='evaluate'){
      const options=b.options.filter(o=>o.state==='staged');if(!options.length)throw new Error('没有待验证的方案');
      const option=options.find(x=>x.id===prompt('输入需验证的方案 ID：\n'+options.map(o=>o.name+' → '+o.id).join('\n'),options[0].id));if(!option)return;
      if(!confirm('将从受保护的输入构造临时工程并实际编译、运行 C++。确认方案源码可信、已人工审查且本机不是恶意代码执行环境？'))return;
      wfNotify('正在对 '+option.name+' 进行实际独立验证');
      v=await wfApi('/api/batch/evaluate','POST',{id:b.id,option_id:option.id,trusted:true});
    }else if(action==='select'){
      const c=await wfApi('/api/batch/compare?id='+encodeURIComponent(b.id));
      alert(JSON.stringify(c.comparison.map(o=>({name:o.name,id:o.id,passed:o.passed,checks:o.checks})),null,2));
      const options=b.options.filter(o=>o.state==='tested');if(!options.length)throw new Error('目前无通过独立验证的方案');
      const oid=prompt('输入选择方案 ID（必须人工比较后指定）',options[0].id);
      const option=options.find(o=>o.id===oid);if(!option)return;
      const digest=prompt('核验候选摘要，输入前12位：'+option.digest,'');if(digest!==option.digest.slice(0,12))throw new Error('方案摘要核验失败');
      v=await wfApi('/api/batch/select','POST',{id:b.id,option_id:option.id,digest:option.digest,confirmation:'human_selected_after_comparison'});
    }else if(action==='apply'){
      const option=b.options.find(o=>o.id===b.selected);
      if(!option||!confirm('将整体应用 '+option.name+'，并创建可恢复备份。此阶段不能宣称已通过工作区验证。确认？'))return;
      v=await wfApi('/api/batch/apply','POST',{id:b.id,digest:option.digest,confirmation:'human_authorized_multi_file_apply'});
    }else if(action==='verify-live'){
      if(!confirm('执行真实工作区全量 C++ 与 Axiom 模型验证。必须确认本地工程代码可信。'))return;
      wfNotify('独立重新验证当前工程…');v=await wfApi('/api/batch/verify-live','POST',{id:b.id,trusted:true});
    }else if(action==='decide'){
      const option=b.options.find(o=>o.id===b.selected);
      const part=prompt('核对已通过实际 Gate 的候选 SHA-256 前12位：'+option.digest,'');if(part!==option.digest.slice(0,12))return;
      v=await wfApi('/api/batch/decide','POST',{id:b.id,digest:option.digest,confirmation:'human_approve_test_only'});
    }else if(action==='rollback'){
      if(!confirm('回滚整个多文件事务？若源码已被外部修改，系统会阻断自动覆盖。'))return;
      v=await wfApi('/api/batch/rollback','POST',{id:b.id,confirmation:'human_reject_and_rollback'});
    }else if(action==='compare'){
      v=await wfApi('/api/batch/compare?id='+encodeURIComponent(b.id));alert(JSON.stringify(v,null,2));return;
    }else if(action==='repair'){
      const errors=b.options.filter(o=>o.state==='blocked');if(!errors.length)throw new Error('尚无已验证失败的方案');
      const pick=errors.find(o=>o.id===prompt('选择失败方案 ID',errors[0].id));if(!pick)return;
      v=await wfApi('/api/batch/repair?id='+encodeURIComponent(b.id)+'&option_id='+encodeURIComponent(pick.id));
      const dump=JSON.stringify(v,null,2);if(navigator.clipboard?.writeText)await navigator.clipboard.writeText(dump);else prompt('修复任务：',dump);
      wfNotify('失败诊断任务已导出；请在人工审查后提交新候选');return;
    }else if(action==='audit'){
      v=await wfApi('/api/batch/audit?id='+encodeURIComponent(b.id));alert(JSON.stringify(v,null,2));return;
    }
    wfNotify('多目标生产事务：'+(v?.state||'已更新'));await selectProject(project.id);
  }catch(e){wfNotify('多目标生产流程阻断：'+e.message)}
}
async function wfFactoryAction(action){
  try{
    const project=wf.detail,fc=wf.factory[0];let result;
    if(action==='create'){
      const target=prompt('本次受控构造的 C++ 实现目标（工作区相对路径），一次仅允许一个文件','cpp_project/ledger.cpp');
      if(!target)return;
      result=await wfApi('/api/factory/create','POST',{project_id:project.id,target});
    }else if(action==='spec'){
      if(!confirm('执行真实 Axiom 模型检查与规格 Gate？'))return;
      result=await wfApi('/api/factory/verify-spec','POST',{id:fc.id});
    }else if(action==='candidate'){
      const choice=confirm('确定向已配置 AI 模型发送当前规格和目标源码？取消则改为手动粘贴候选（不会发送网络请求）。');
      if(choice){result=await wfApi('/api/factory/candidate','POST',{id:fc.id,consent:true});}
      else{const code=prompt('粘贴候选 C++ 完整文件内容（仅暂存、不会覆盖源码）');if(!code)return;
        result=await wfApi('/api/factory/candidate','POST',{id:fc.id,code});}
    }else if(action==='review'){
      const proposal=await wfApi('/api/proposal?id='+encodeURIComponent(fc.candidate_id));
      const code=proposal.code||'';
      const entered=prompt('人工审查完整代码（可先复制到 VS Code 比较），并输入 SHA-256 前 12 位确认：\n'+proposal.code_sha256+'\n\n'+code.slice(0,6000),'');
      if(entered!==proposal.code_sha256.slice(0,12))throw new Error('审查摘要不匹配');
      result=await wfApi('/api/factory/review','POST',{id:fc.id,sha256:proposal.code_sha256,confirmation:'human_review_approved'});
    }else if(action==='apply'){
      if(!confirm('将已经审查的完整候选文件应用于工作区并保存备份？请确认已审查文件差异。'))return;
      result=await wfApi('/api/factory/apply','POST',{id:fc.id,confirmation:'human_apply_approved'});
    }else if(action==='validate'){
      if(!confirm('确认这份 C++ 源码来自可信本地工作区，已人工审查。即将实际编译、运行和验证；本系统不是生产级安全沙箱。'))return;
      result=await wfApi('/api/factory/validate','POST',{id:fc.id,trusted:true});
    }else if(action==='poll'){
      result=await wfApi('/api/factory/poll?id='+encodeURIComponent(fc.id));
    }else if(action==='decide'){
      const proposal=await wfApi('/api/proposal?id='+encodeURIComponent(fc.candidate_id));
      const entered=prompt('仅确认测试级原型，通过实时 Gate 后记录人工裁决。输入候选 SHA-256 前 12 位：\n'+proposal.code_sha256,'');
      if(entered!==proposal.code_sha256.slice(0,12))throw new Error('裁决摘要不匹配');
      result=await wfApi('/api/factory/decide','POST',{id:fc.id,sha256:proposal.code_sha256,confirmation:'approve_test_only'});
    }else if(action==='repair'){
      const pkt=await wfApi('/api/factory/repair?id='+encodeURIComponent(fc.id));
      if(navigator.clipboard?.writeText){await navigator.clipboard.writeText(JSON.stringify(pkt,null,2));wfNotify('失败诊断已复制；请新建演化分支和生产契约');}
      else prompt('修复任务（需人工建立演化分支）',JSON.stringify(pkt,null,2));return;
    }else if(action==='events'){
      const ev=await wfApi('/api/factory/events?id='+encodeURIComponent(fc.id));alert(JSON.stringify({valid:ev.valid,issues:ev.issues,events:ev.events.map(x=>({kind:x.kind,payload:x.payload,timestamp:x.timestamp}))},null,2));return;
    }
    wfNotify('生产编排：'+(result.label||result.state||'已更新'));await selectProject(project.id);
  }catch(e){wfNotify('生产工作流阻断：'+e.message)}
}
async function wfAction(action){if(!wf.detail)return;const p=wf.detail;try{
  let result;
  if(action==='freeze'){
    const draft=await wfApi('/api/production/draft?id='+encodeURIComponent(p.id));
    if(!draft.suggested.length)throw new Error('规格尚无可映射性质');
    if(!confirm('为当前规格建立一次性不可变生产契约。请逐条确认性质与需求含义；修改需新建演化分支。'))return;
    const reqs=[];
    for(const item of draft.suggested){
      const statement=prompt(`确认 ${item.property} 对应的业务需求（至少8字）`,item.text);
      if(statement===null)return;
      reqs.push({...item,text:statement});
    }
    result=await wfApi('/api/production/freeze','POST',{id:p.id,requirements:reqs,baseline:p.baseline});
    wfNotify('生产契约已冻结 '+result.digest.slice(0,26));await selectProject(p.id);return;
  }else if(action==='task'){
    const task=await wfApi('/api/production/task?id='+encodeURIComponent(p.id));
    const str=JSON.stringify(task,null,2);
    if(navigator.clipboard?.writeText){await navigator.clipboard.writeText(str);wfNotify('构造任务包已复制到剪贴板；约束摘要 '+task.digest.slice(0,24));}
    else prompt('复制受约束构造任务 JSON',str);
    return;
  }else if(action==='graph'){
    const graph=await wfApi('/api/production/graph?id='+encodeURIComponent(p.id));
    alert('追溯关系（有向边）：\n'+graph.edges.map(e=>e.from+' —'+e.kind+'→ '+e.to).join('\n'));return;
  }else if(action==='passports'){
    const items=await wfApi('/api/production/passports?id='+encodeURIComponent(p.id));
    alert(items.passports.length?items.passports.map(v=>v.id+' / '+(v.snapshot_matches_current?'摘要仍匹配':'已失效')+' / 未重新执行 Gate').join('\n'):'目前没有测试级生产护照');return;
  }else if(action==='passport'){
    if(!confirm('将再次执行当前候选的独立 C++ Gate，并仅签发不可用于生产发布的测试级证据快照。继续？'))return;
    result=await wfApi('/api/production/passport','POST',{id:p.id,contract_digest:wf.production.contract_digest,confirmation:'issue_test_only'});
    wfNotify('测试级生产护照已签发 '+result.id);await selectProject(p.id);return;
  }
  else   if(action==='verify'){
    if(!confirm('调用真实 Axiom 引擎执行规格检查、模型验证及模型 Gate？该操作不执行 C++。'))return;
    result=await wfApi('/api/project/verify-spec','POST',{id:p.id});
  }else if(action==='attach'){
    const list=await wfApi('/api/proposals');
    const existing=list.proposals.filter(c=>c.manifest===p.manifest&&c.spec===p.spec&&c.status==='proposed'&&c.current);
    const candidateId=prompt('请输入该项目的待审查候选 ID（先在候选工作台创建）',existing[0]?.id||'');
    if(!candidateId)return;result=await wfApi('/api/project/attach','POST',{id:p.id,candidate_id:candidateId.trim()});
  }else if(action==='candidate'){
    wfE('candidateManifest').value=p.manifest||'';
    if(p.manifest){
      const manifest=await wfApi('/api/file?path='+encodeURIComponent(p.manifest));
      const desc=JSON.parse(manifest.content);
      const folder=p.manifest.includes('/')?p.manifest.slice(0,p.manifest.lastIndexOf('/')+1):'';
      const target=(desc.files||[]).find(x=>/\.(cpp|cc)$/.test(x)&&!/(^|\/)test[_-]/.test(x));
      if(target)wfE('candidateTarget').value=folder+target;
    }
    candidateOpen();return;
  }else if(action==='sync')result=await wfApi('/api/project/sync','POST',{id:p.id});
  else if(action==='decide'){
    const c=await wfApi('/api/proposal?id='+encodeURIComponent(p.candidate_id));
    if(!confirm('本操作只确认独立验证通过的原型候选，并不授权生产发布。请确认已审核 Gate 证据。'))return;
    const typed=prompt('输入候选 SHA-256 的前 12 位，以确认裁决对象：\n'+c.code_sha256,'');
    if(typed!==c.code_sha256.slice(0,12))throw new Error('候选摘要确认不一致');
    result=await wfApi('/api/project/decide','POST',{id:p.id,candidate_digest:c.code_sha256,confirmation:'approve_test_only'});
  }else if(action==='fork'){
    const name=prompt('新演化版本的名称',p.name+' · R'+(p.revision+1));if(!name)return;
    result=await wfApi('/api/project/fork','POST',{id:p.id,name});
  }else if(action==='audit'){
    const report=await wfApi('/api/project/audit?id='+encodeURIComponent(p.id));alert(JSON.stringify(report,null,2));return;
  }
  wfNotify('流程已更新：'+(result.status_label||result.status));wf.selected=result.id;await loadProjects();
}catch(e){wfNotify('操作被阻断：'+e.message)}}
function wfCreateOpen(){wfE('projectCreateOverlay').classList.remove('hidden')}
function wfCreateClose(){wfE('projectCreateOverlay').classList.add('hidden')}
function initProjects(){
  wfE('projectRail').onclick=showProjects;wfE('navProjects').onclick=showProjects;
  wfE('projectNew').onclick=wfCreateOpen;wfE('projectSidebarCreate').onclick=wfCreateOpen;wfE('projectSidebarOverview').onclick=showProjects;wfE('projectRefresh').onclick=loadProjects;
  wfE('projectCreateClose').onclick=wfCreateClose;wfE('projectCreateCancel').onclick=wfCreateClose;
  wfE('projectCreateForm').onsubmit=async ev=>{ev.preventDefault();const form=new FormData(ev.currentTarget);
    try{const data=Object.fromEntries(form.entries());const p=await wfApi('/api/project/create','POST',data);
      wf.selected=p.id;wfCreateClose();showProjects();wfNotify('构造项目已创建；请验证规格后再绑定实现候选');
    }catch(e){wfNotify('创建失败：'+e.message)}};
  loadProjects();
}
initProjects();
