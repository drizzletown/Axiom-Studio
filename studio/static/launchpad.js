'use strict';
// Practical project intake + work queue. Does not execute C++ or authorize releases.
let launchTemplates=[];
const lx=id=>document.getElementById(id);
async function loadLaunchQueue(){
  try{
    const data=await wfApi('/api/launch/queue');
    const root=lx('launchQueue');if(!root)return;
    root.replaceChildren();
    if(!data.items.length){root.innerHTML='<div class="launch-empty">尚无生产任务。点击「新建可运行项目」，创建独立工作区和第一条可信构造流程。</div>';return}
    data.items.forEach(item=>{
      const row=document.createElement('div');row.className='launch-item';
      row.innerHTML=`<div><b>${wfEsc(item.name)}</b><small>${wfEsc(item.reason)}</small></div><span class="launch-state ${wfEsc(item.category)}">${wfEsc(item.state)}</span>`;
      const group=document.createElement('div');group.className='launch-actions';
      const next=document.createElement('button');next.className='tool secondary';next.textContent=item.label;
      next.onclick=async()=>{
        try{
          await selectProject(item.project_id);
          if(item.next_action==='batch')return wfBatchAction('create');
          if(['verify','freeze','fork','task','passport','candidate'].includes(item.next_action))return wfAction(item.next_action);
          wfNotify('已选中项目；查看阻断诊断与下一步要求');
        }catch(e){wfNotify('工作项无法继续：'+e.message)}
      };
      const exportButton=document.createElement('button');exportButton.className='tool secondary';exportButton.textContent='导出交接包';
      exportButton.onclick=()=>downloadLaunchPackage(item.project_id);
      group.append(next,exportButton);row.appendChild(group);root.appendChild(row);
    });
  }catch(e){const node=lx('launchQueue');if(node)node.textContent='待办加载失败：'+e.message}
}
async function downloadLaunchPackage(id){
  try{
    const token=new URLSearchParams(location.search).get('token')||'';
    const r=await fetch('/api/launch/export?id='+encodeURIComponent(id),{headers:{'X-Axiom-Token':token}});
    if(!r.ok){const x=await r.json();throw new Error(x.error||'打包失败')}
    const blob=await r.blob(), url=URL.createObjectURL(blob), a=document.createElement('a');
    a.href=url;a.download=`Axiom-Handoff-${id}.zip`;document.body.append(a);a.click();a.remove();
    setTimeout(()=>URL.revokeObjectURL(url),30000);
    wfNotify('已导出可交接的工作区与生产快照。注意：未签名，接收方仍需重新验证。');
  }catch(e){wfNotify('交接失败：'+e.message)}
}
async function launchOpen(){
  try{
    const data=await wfApi('/api/launch/templates');launchTemplates=data.templates;
    const chooser=lx('launchTemplate');chooser.replaceChildren();
    launchTemplates.forEach(t=>{const o=document.createElement('option');o.value=t.id;o.textContent=t.label;chooser.appendChild(o)});
    launchUpdateTemplate();lx('launchOverlay').classList.remove('hidden');
  }catch(e){wfNotify('载入模板失败：'+e.message)}
}
function launchUpdateTemplate(){
  const t=launchTemplates.find(x=>x.id===lx('launchTemplate').value);
  if(t){lx('launchHint').textContent=t.description+(t.native?' · C++ 代码执行需要另行人工确认。':' · 不会启动编译器。');lx('launchForm').elements.goal.value=t.default_goal;}
}
let activeRunId=null;
async function loadProductionBatch(){
  const root=lx('launchBatch');if(!root)return;
  try{
    const listing=await wfApi('/api/runner/list');
    const run=listing.runs[0];if(!run){root.replaceChildren();return}
    root.replaceChildren();
    const row=document.createElement('div');row.className='batch-info';
    const title=document.createElement('strong');
    const count=run.items.filter(i=>['passed','blocked','failed','stale','interrupted'].includes(i.status)).length;
    title.textContent=`最近生产批次：${run.status} · ${count}/${run.requested}`;
    const retry=document.createElement('button');retry.className='tool secondary';retry.textContent='显式重试失败项';
    retry.disabled=!['needs_attention','interrupted'].includes(run.status);
    retry.onclick=async()=>{
      if(!confirm('仅重新执行规格模型验证，不执行 C++，原失败证据保留。确认重新规划？'))return;
      try{const r=await wfApi('/api/runner/retry','POST',{id:run.id});await wfApi('/api/runner/start','POST',{id:r.id});activeRunId=r.id;await loadProductionBatch()}
      catch(e){wfNotify(e.message)}
    };
    const download=document.createElement('button');download.className='tool secondary';
    download.textContent='导出批次与有效项目';download.disabled=['running','queued'].includes(run.status);
    download.onclick=async()=>{
      try{
        const token=new URLSearchParams(location.search).get('token')||'';
        const res=await fetch('/api/runner/export?id='+encodeURIComponent(run.id),{headers:{'X-Axiom-Token':token}});
        if(!res.ok)throw new Error((await res.json()).error||'下载失败');
        const url=URL.createObjectURL(await res.blob()),a=document.createElement('a');
        a.href=url;a.download=`Axiom-Model-Batch-${run.id}.zip`;document.body.append(a);a.click();a.remove();
        setTimeout(()=>URL.revokeObjectURL(url),30000);
      }catch(e){wfNotify('导出失败：'+e.message)}
    };
    row.append(title,retry,download);root.append(row);
    const prog=document.createElement('div');prog.className='batch-progress';
    const fill=document.createElement('div');fill.className='batch-fill';fill.style.width=`${100*count/Math.max(1,run.requested)}%`;
    prog.append(fill);root.append(prog);
    const summary=document.createElement('div');summary.className='batch-warning';
    summary.textContent=`通过 ${run.items.filter(i=>i.status==='passed').length} · 阻断 ${run.items.filter(i=>i.status==='blocked').length} · 失败/中断 ${run.items.filter(i=>['failed','interrupted','stale'].includes(i.status)).length}。不触发 AI、不执行 C++、不自动批准发布。`;
    root.append(summary);
    if(['running','queued'].includes(run.status)){
      activeRunId=run.id;
      setTimeout(async()=>{await loadProductionBatch();await loadLaunchQueue();},1500);
    }else if(activeRunId===run.id){activeRunId=null;await loadProjects();await loadLaunchQueue()}
  }catch(e){root.textContent='批次状态载入失败：'+e.message}
}
async function launchSafeBatch(){
  const button=lx('launchAutoVerify');button.disabled=true;
  try{
    const data=await wfApi('/api/launch/queue');
    const eligible=data.items.filter(i=>i.next_action==='verify' && i.state==='draft').map(i=>i.project_id).slice(0,20);
    if(!eligible.length){wfNotify('没有尚未验证的安全规格任务。');return}
    if(!confirm(`将自动执行 ${eligible.length} 个项目的规格模型检查和模型 Gate。不会运行 C++ 或修改需求。继续？`))return;
    const run=await wfApi('/api/runner/plan','POST',{project_ids:eligible,retry_failed:false});
    await wfApi('/api/runner/start','POST',{id:run.id});activeRunId=run.id;
    await loadProductionBatch();wfNotify('已创建持久化批次；人工审批阶段仍须手动操作。');
  }catch(e){wfNotify('批量验证启动失败：'+e.message)}finally{button.disabled=false}
}
function initLaunchpad(){
  lx('launchOpen').onclick=launchOpen;
  lx('launchAutoVerify').onclick=launchSafeBatch;
  lx('launchRefresh').onclick=async()=>{await loadProjects();await loadLaunchQueue()};
  lx('launchClose').onclick=lx('launchCancel').onclick=()=>lx('launchOverlay').classList.add('hidden');
  lx('launchTemplate').onchange=launchUpdateTemplate;
  lx('launchForm').onsubmit=async event=>{
    event.preventDefault();const button=lx('launchForm').querySelector('[type="submit"]');button.disabled=true;
    try{
      const fields=Object.fromEntries(new FormData(lx('launchForm')).entries());
      const created=await wfApi('/api/launch/create','POST',fields);
      lx('launchOverlay').classList.add('hidden');wf.selected=created.project.id;
      await loadProjects();wfNotify('独立项目创建成功。下一步：验证 Axiom 行为规格。');
    }catch(e){wfNotify('项目创建失败：'+e.message)}finally{button.disabled=false}
  };
  loadLaunchQueue();loadProductionBatch();
}
initLaunchpad();
