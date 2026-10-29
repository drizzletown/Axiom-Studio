'use strict';
// Axiom Studio 1.7 — task dependencies, never an autonomous code runner.
(function () {
  const el=id=>document.getElementById(id), token=()=>new URLSearchParams(location.search).get('token')||'';
  let current=null;
  const node=(tag,txt,cls)=>{const n=document.createElement(tag);if(txt!==undefined)n.textContent=String(txt);if(cls)n.className=cls;return n};
  async function api(path,body){const resp=await fetch(path,{method:body===undefined?'GET':'POST',headers:{'X-Axiom-Token':token(),...(body===undefined?{}:{'Content-Type':'application/json'})},body:body===undefined?undefined:JSON.stringify(body)});const r=await resp.json();if(!resp.ok)throw Error(r.error||'请求失败');return r;}
  function error(e){el('taskGraphBody').replaceChildren(node('p','任务暂不能继续：'+e.message,'assembly-error'));}
  async function load(){
    const projects=(await api('/api/projects')).projects||[];
    const sel=el('taskGraphProject'),prev=sel.value;
    sel.replaceChildren(new Option('请选择项目…',''));
    projects.filter(x=>x.manifest).forEach(x=>sel.add(new Option(x.name,x.id)));
    if(projects.some(x=>x.id===prev))sel.value=prev;
    else if(sel.options.length>1)sel.selectedIndex=1;
    await show();
  }
  async function show(){
    const pid=el('taskGraphProject').value;
    if(!pid){el('taskGraphBody').textContent='先创建或选择具有 C++ 工程的项目。';return}
    const list=await api('/api/task-graph/list?project_id='+encodeURIComponent(pid));
    if(!list.graphs.length){current=null;el('taskGraphBody').textContent='尚无生产计划。确认并冻结验收规则后，点击“创建跨模块生产计划”。';return}
    current=list.graphs[0];render(current);
  }
  function render(v){
    current=v;const root=el('taskGraphBody');root.replaceChildren();
    root.append(node('h3','已独立验证 '+v.completed+' / '+v.total+' 个模块'));
    root.append(node('p',v.next,v.current?'assembly-status':'assembly-error'));
    if(!v.current)root.append(node('p','阻断原因：'+v.blocker,'assembly-error'));
    const list=node('div',undefined,'graph-items');
    const names={ready:'可以开始',waiting:'等待依赖',active:'正在构造',passed:'测试已通过'};
    for(const t of v.tasks){
      const item=node('div',undefined,'graph-module');
      const label=node('div');label.append(node('strong',t.target.split('/').pop()));
      label.append(node('p',(names[t.display_state]||t.display_state)+(t.waiting_for.length?' · 等待 '+t.waiting_for.map(x=>x.split('/').pop()).join('、'):''),'assembly-muted'));
      item.append(label);
      if(t.can_start){const b=node('button','开始这个模块','tool primary');b.onclick=async()=>{try{const r=await api('/api/task-graph/start',{id:v.id,target:t.target});render(r);if(window.AxiomAssemblyOpen)await window.AxiomAssemblyOpen(v.project_id,t.target)}catch(e){error(e)}};item.append(b)}
      if(t.state==='active'){
        const b=node('button','进入构造生产线','tool secondary');b.onclick=()=>window.AxiomAssemblyOpen?.(v.project_id);item.append(b);
      }
      if(t.state==='passed')item.append(node('span','✓ 独立 C++ 测试级通过','assembly-status'));
      list.append(item);
    }
    root.append(list);
    const fleetSection=node('section',undefined,'fleet-section'); fleetSection.id='fleetSection';
    const fleetHead=node('h3','并行准备候选 · 安全串行集成');fleetSection.append(fleetHead);
    fleetSection.append(node('p','多个模块的 AI / VS Code 构造任务可同时准备，但候选只暂存；每次应用、C++ 验证与 Gate 仍需人工授权。','assembly-muted'));
    const prepBtn=node('button','并行生成各模块构造任务','tool primary');prepBtn.onclick=async()=>{try{const data=await api('/api/fleet/prepare',{id:v.id,parallelism:3});await renderFleet(v,data)}catch(e){fleetSection.append(node('p',e.message,'assembly-error'))}};fleetSection.append(prepBtn);
    const fleetBody=node('div'); fleetBody.id='fleetBody';fleetSection.append(fleetBody);root.append(fleetSection);
    api('/api/fleet/get?id='+encodeURIComponent(v.id)).then(data=>renderFleet(v,data)).catch(()=>{});
    const ops=node('div',undefined,'assembly-actions');
    const refresh=node('button','同步各模块验证结果','tool secondary');refresh.onclick=async()=>{try{render(await api('/api/task-graph/sync',{id:v.id}))}catch(e){error(e)}};ops.append(refresh);
    const exportBtn=node('button','导出生产计划与证据摘要','tool secondary');exportBtn.onclick=async()=>{try{const h=await api('/api/task-graph/handoff?id='+encodeURIComponent(v.id));const url=URL.createObjectURL(new Blob([JSON.stringify(h,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=h.filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}catch(e){error(e)}};ops.append(exportBtn);root.append(ops);
    root.append(node('p','每个模块先审查候选，再单独授权运行 C++。任务图的全部测试通过也不是正式生产发布批准。','assembly-muted'));
  }

  async function renderFleet(graph,fleet){
    const root=el('fleetBody');if(!root||!graph||current?.id!==graph.id)return;
    root.replaceChildren();
    if(!fleet.current)root.append(node('p','工程输入已变化：'+fleet.blocker,'assembly-error'));
    for(const packet of fleet.packets){
      const wrap=node('div',undefined,'fleet-packet');
      const title=node('h4',packet.target.split('/').pop()+' · '+(packet.candidate_sha256?'候选已暂存':'待准备候选'));
      wrap.append(title);
      const badge=node('p','依赖：'+(packet.depends_on.length?packet.depends_on.map(x=>x.split('/').pop()).join('、'):'无')+' · 任务包 '+packet.packet_digest.slice(0,12),'assembly-muted');wrap.append(badge);
      const details=node('details');const summary=node('summary','查看构造任务说明（可交给 AI / VS Code）');details.append(summary);
      const prompt=node('textarea');prompt.readOnly=true;prompt.value=packet.prompt;prompt.rows=7;prompt.className='fleet-text';details.append(prompt);
      const copy=node('button','复制 AI 构造任务','tool secondary');copy.onclick=()=>navigator.clipboard.writeText(packet.prompt).then(()=>copy.textContent='已复制').catch(()=>{prompt.select();document.execCommand('copy')});details.append(copy);wrap.append(details);
      const agentActions=node('div',undefined,'assembly-actions');
      const aiButton=node('button','AI 起草 + AI 复核','tool secondary');
      const impactButton=node('button','查看变更影响','tool secondary');
      const aiBody=node('div',undefined,'fleet-agent-result');
      agentActions.append(aiButton,impactButton);wrap.append(agentActions);wrap.append(aiBody);
      impactButton.onclick=async()=>{try{const result=await api('/api/agents/impact',{graph_id:graph.id,targets:[packet.target]});
        aiBody.replaceChildren(node('p','预计影响 '+result.affected.length+' 个模块：'+result.affected.map(t=>t.split('/').pop()).join('、')),
          node('p','需重做全局规格 Gate 和 C++ 集成检查；不会自动复用旧证据。','assembly-muted'));
      }catch(e){aiBody.textContent=e.message}};
      aiButton.disabled=!fleet.current;
      aiButton.onclick=async()=>{
        if(!confirm('将此模块的规格、源代码和项目目标发送给已配置的模型。AI 仅生成待审查候选，不会执行或应用源码。是否授权本次传输？'))return;
        aiButton.disabled=true;aiBody.textContent='正在生成代码并进行 AI 建议性复核…';
        try{const result=await api('/api/agents/run',{graph_id:graph.id,target:packet.target,consent:true,rounds:1});
          aiBody.replaceChildren(node('h4','AI 候选与建议性复核'));
          const suggestion=node('p',result.review||'模型未提供复核意见','assembly-muted');aiBody.append(suggestion);
          const code=node('textarea');code.readOnly=true;code.value=result.code;code.rows=9;code.className='fleet-text';aiBody.append(code);
          const digest=node('p','待审查摘要：'+result.candidate_sha256,'assembly-muted');aiBody.append(digest);
          const stageAI=node('button','我已阅读源码：仅暂存候选','tool secondary');aiBody.append(stageAI);
          stageAI.onclick=async()=>{try{
            const yes=confirm('确认已经审阅完整候选，暂存后仍须独立人工批准应用和授权 C++ 测试？');if(!yes)return;
            const staged=await api('/api/agents/stage',{id:result.id,candidate_sha256:result.candidate_sha256,acknowledge:true});
            await renderFleet(graph,staged.fleet);
          }catch(e){aiBody.append(node('p',e.message,'assembly-error'))}};
        }catch(e){aiBody.replaceChildren(node('p',e.message,'assembly-error'))}
        finally{aiButton.disabled=false}
      };
      const edit=node('textarea');edit.className='fleet-text';edit.rows=5;edit.placeholder='可选：在这里粘贴 AI / VS Code 返回的单文件 C++ 实现候选。暂存不会改动工程文件。';wrap.append(edit);
      const actions=node('div',undefined,'assembly-actions');
      const stage=node('button','只暂存候选，不修改工程','tool secondary');stage.disabled=!fleet.current;actions.append(stage);
      const promote=node('button','提交人工审查','tool primary');promote.disabled=!packet.can_promote;actions.append(promote);
      const note=node('p',packet.candidate_sha256?'候选摘要：'+packet.candidate_sha256.slice(0,18)+'…':'还没有暂存候选','assembly-muted');wrap.append(actions);wrap.append(note);
      edit.addEventListener('input',()=>{promote.disabled=true});
      stage.onclick=async()=>{try{if(!edit.value.trim())throw Error('先粘贴完整的候选源码');const next=await api('/api/fleet/stage',{id:graph.id,target:packet.target,packet_digest:packet.packet_digest,code:edit.value});await renderFleet(graph,next)}catch(e){note.textContent=e.message;note.className='assembly-error'}};
      promote.onclick=async()=>{try{const result=await api('/api/fleet/promote',{id:graph.id,target:packet.target,candidate_sha256:packet.candidate_sha256,acknowledge_rebase:packet.requires_rebase_ack?confirm('已有前置模块通过验证并发生变化。请在 VS Code 中复核其接口与当前候选的兼容性；确认已完成这项审查？'):false});render(result.graph);window.AxiomAssemblyOpen?.(graph.project_id,packet.target)}catch(e){note.textContent=e.message;note.className='assembly-error'}};
      root.append(wrap);
    }
    const batchAgentButton=node('button','AI 并行起草与复核（最多 3 个模块）','tool secondary');
    const batchOutput=node('div',undefined,'fleet-agent-batch');
    batchAgentButton.disabled=!fleet.current;
    batchAgentButton.onclick=async()=>{
      const tasks=fleet.packets.slice(0,3).map(p=>p.target);
      if(!tasks.length)return;
      if(!confirm('授权向已配置 AI 模型发送 '+tasks.length+' 个模块的源代码与规格？生成结果仅供人工审查，不会自动修改或执行工程。'))return;
      batchAgentButton.disabled=true;batchOutput.replaceChildren(node('p','AI 正在并行生成候选与复核建议…'));
      try{
        const result=await api('/api/agents/batch',{graph_id:graph.id,targets:tasks,consent:true,rounds:1,concurrency:2});
        batchOutput.replaceChildren(node('p','已生成 '+result.passed+'/'+result.total+' 个候选；请逐个阅读与确认。'));
        for(const item of result.results){
          const section=node('div',undefined,'fleet-packet');
          section.append(node('h4',item.target.split('/').pop()+' · '+(item.ok?'候选生成完成':'生成失败')));
          if(!item.ok){section.append(node('p',item.error,'assembly-error'));batchOutput.append(section);continue}
          const view=await api('/api/agents/get?id='+encodeURIComponent(item.id));
          section.append(node('p',view.review,'assembly-muted'));
          const code=node('textarea');code.className='fleet-text';code.readOnly=true;code.rows=8;code.value=view.code;section.append(code);
          section.append(node('p','摘要：'+view.candidate_sha256,'assembly-muted'));
          const save=node('button','已阅读完整代码，仅暂存','tool secondary');section.append(save);
          save.onclick=async()=>{
            if(!confirm('确认已阅读完整源码与复核意见？暂存后仍然需要人工批准、独立验证。'))return;
            try{const r=await api('/api/agents/stage',{id:item.id,candidate_sha256:view.candidate_sha256,acknowledge:true});
              await renderFleet(graph,r.fleet);
            }catch(e){section.append(node('p',e.message,'assembly-error'))}
          };
          batchOutput.append(section);
        }
      }catch(e){batchOutput.replaceChildren(node('p',e.message,'assembly-error'))}
      finally{batchAgentButton.disabled=false}
    };
    root.append(batchAgentButton,batchOutput);
    const exportBtn=node('button','导出并行构造任务与摘要','tool secondary');exportBtn.onclick=async()=>{try{const h=await api('/api/fleet/handoff?id='+encodeURIComponent(graph.id));const u=URL.createObjectURL(new Blob([JSON.stringify(h,null,2)],{type:'application/json'}));const a=node('a');a.href=u;a.download=h.filename;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000)}catch(e){root.append(node('p',e.message,'assembly-error'))}};root.append(exportBtn);
  }

  document.addEventListener('DOMContentLoaded',()=>{
    if(!el('taskGraphHome'))return;
    el('taskGraphRefresh').onclick=()=>load().catch(error);
    el('taskGraphProject').onchange=()=>show().catch(error);
    el('taskGraphCreate').onclick=async()=>{try{const pid=el('taskGraphProject').value;if(!pid)throw Error('请选择工程');render(await api('/api/task-graph/create',{project_id:pid}))}catch(e){error(e)}};
    load().catch(error);
  });
})();
