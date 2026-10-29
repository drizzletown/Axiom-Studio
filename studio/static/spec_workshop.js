'use strict';
// Spec proposals are detached from the parent. Never write specs via the generic editor.
(function(){
  const $=id=>document.getElementById(id);
  let projectId=null, candidate=null, input=null;
  const el=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=String(text);if(cls)e.className=cls;return e;};
  async function request(path,method='GET',body){return wfApi(path,method,body)}
  function error(s){$('specWorkshopError').textContent=s||''}
  function render(){
    const textMatches=!!candidate && $('specWorkshopSource').value===candidate.source;
    const valid=!!candidate&&candidate.current&&textMatches;
    $('specWorkshopCheck').disabled=!valid||candidate.state!=='proposed';
    $('specWorkshopPromote').disabled=!valid||candidate.state!=='checked'||!$('specWorkshopApproved').checked;
    $('specWorkshopStatus').textContent=(candidate&&!textMatches)?'候选文本已修改，请先暂存为新候选再验证或批准':!candidate?'尚未提出候选':
      (candidate.state==='checked'?'候选规则已通过有限模型检查，等待你审查':
      candidate.state==='rejected_by_model'?'候选模型验证失败，不能采用':
      candidate.state==='promoted'?'已建演化项目，旧项目和证据不变':'候选已暂存，等待独立检查');
    $('specWorkshopDiff').textContent=candidate?.diff||'尚无候选';
    $('specWorkshopEvidence').textContent=!candidate?'提交候选后可在这里查看真实验证结果。':
      (candidate.assessment?candidate.assessment.checks.map(x=>x.step+': '+(x.returncode===0?'通过':'失败')+(x.error?' · '+x.error:'')).join('\n')+
      '\n'+candidate.assessment.scope:'这份候选尚未被独立检查。');
    const mappings=$('specWorkshopMappings');mappings.replaceChildren();
    if(candidate?.state==='checked'||candidate?.state==='promoted'){
      for(const item of candidate.scenarios){
        const row=el('label',undefined,'spec-workshop-map');row.append(el('strong',item.id+' · '+item.title));
        const sel=el('select');sel.dataset.scenario=item.id;
        const missing=el('option','暂无对应性质（保留缺口）');missing.value='';sel.append(missing);
        for(const name of candidate.assessment.properties){const o=el('option',name);o.value=name;sel.append(o)}
        if(item.property&&candidate.assessment.properties.includes(item.property))sel.value=item.property;
        row.append(sel);mappings.append(row);
      }
    }else mappings.append(el('p','模型检查通过后才会列出可选择的行为性质。','spec-workshop-hint'));
  }
  async function showCandidate(id){candidate=await request('/api/spec-workshop/get?candidate='+encodeURIComponent(id));
    $('specWorkshopApproved').checked=false;
    $('specWorkshopSource').value=candidate.source;
    $('specWorkshopNotes').value=candidate.notes;
    render();
    if(window.axiomDesignReviewInspect)window.axiomDesignReviewInspect(projectId,candidate.id).catch(x=>error(x.message));}
  async function list(){
    const data=await request('/api/spec-workshop/list?id='+encodeURIComponent(projectId));
    const root=$('specWorkshopList');root.replaceChildren();
    for(const c of data.candidates){const b=el('button',c.id.slice(0,18)+' · '+({proposed:'待检查',checked:'可审查',promoted:'已演化',rejected_by_model:'验证失败'}[c.state]||c.state),'tool secondary');b.type='button';b.onclick=()=>showCandidate(c.id).catch(x=>error(x.message));root.append(b)}
    if(!data.candidates.length)root.append(el('span','尚无候选','spec-workshop-hint'));
    if(window.axiomDesignReviewRefresh)window.axiomDesignReviewRefresh(projectId,data.candidates);
  }
  async function open(id){projectId=id;candidate=null;error('');
    $('specWorkshopApproved').checked=false;$('specWorkshopSource').value='';$('specWorkshopNotes').value='';
    input=await request('/api/spec-workshop/task?id='+encodeURIComponent(id));
    $('specWorkshopGoal').textContent=input.task.goal;
    $('specWorkshopOverlay').classList.remove('hidden');await list();render();
    if(input.provider.configured)$('specWorkshopGenerate').textContent='连接 '+input.provider.model+' 生成候选';
    else $('specWorkshopGenerate').textContent='模型未配置（仍可复制给 VS Code）';
  }
  function close(){$('specWorkshopOverlay').classList.add('hidden')}
  async function busy(id,work){const b=$(id);b.disabled=true;error('');try{await work()}catch(e){error(e.message)}finally{b.disabled=false;render()}}
  document.addEventListener('DOMContentLoaded',()=>{
    if(!$('specWorkshopOverlay'))return;
    $('specWorkshopClose').onclick=close;
    $('specWorkshopApproved').onchange=render;
    $('specWorkshopSource').addEventListener('input',render);
    $('specWorkshopCopyTask').onclick=()=>busy('specWorkshopCopyTask',async()=>{
      const text=input.prompt;
      if(navigator.clipboard?.writeText)await navigator.clipboard.writeText(text);
      else{const t=$('specWorkshopSource');t.value=text;t.select();error('已将设计任务放到输入框，请复制后清空，再粘贴 AI 返回的完整规格。')}
    });
    $('specWorkshopGenerate').onclick=()=>busy('specWorkshopGenerate',async()=>{
      if(!input.provider.configured)throw Error('请先配置模型，或复制任务给 VS Code / AI。');
      if(!confirm('将当前目标、场景和规格发送给已配置的模型？模型只返回候选，不会修改你的项目。'))return;
      const c=await request('/api/spec-workshop/generate','POST',{id:projectId,consent:true});await list();await showCandidate(c.id);
    });
    $('specWorkshopCreate').onclick=()=>busy('specWorkshopCreate',async()=>{
      const c=await request('/api/spec-workshop/create','POST',{
        id:projectId,source:$('specWorkshopSource').value,notes:$('specWorkshopNotes').value});
      await list();await showCandidate(c.id);
    });
    $('specWorkshopCheck').onclick=()=>busy('specWorkshopCheck',async()=>{if(!candidate)throw Error('请选择候选');
      const c=await request('/api/spec-workshop/check','POST',{candidate:candidate.id});await list();await showCandidate(c.id);});
    $('specWorkshopPromote').onclick=()=>busy('specWorkshopPromote',async()=>{
      if(!candidate||!$('specWorkshopApproved').checked)throw Error('请先审查并确认');
      const mappings={};$('specWorkshopMappings').querySelectorAll('[data-scenario]').forEach(sel=>mappings[sel.dataset.scenario]=sel.value||null);
      const result=await request('/api/spec-workshop/promote','POST',{
        candidate:candidate.id,digest:candidate.source_sha256,mappings,confirmation:'I_REVIEWED_SPEC_AND_MAPPINGS'});
      await list();await showCandidate(candidate.id);
      close();if(typeof loadProjects==='function')await loadProjects();
      if(typeof selectProject==='function')await selectProject(result.child.id);
      if(window.axiomJourneyRefresh)await window.axiomJourneyRefresh();
      if(typeof wfNotify==='function')wfNotify('演化项目已创建。先重新验证新规格，再人工确认新的验收契约。');
    });
  });
  window.axiomOpenSpecWorkshop=id=>open(id).catch(e=>error('无法开启规格工作台：'+e.message));
})();
