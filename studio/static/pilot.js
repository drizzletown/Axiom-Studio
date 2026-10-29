'use strict';
/* Production pilot: the UI never treats candidate AI output as independent evidence. */
(function(){
  const el=id=>document.getElementById(id);
  const token=()=>new URLSearchParams(location.search).get('token')||'';
  let active=null,projectRows=[];
  async function api(path,data){
    const res=await fetch(path,{method:data?'POST':'GET',headers:{'X-Axiom-Token':token(),...(data?{'Content-Type':'application/json'}:{})},body:data?JSON.stringify(data):undefined});
    const obj=await res.json();if(!res.ok)throw Error(obj.error||('HTTP '+res.status));return obj;
  }
  function span(tag,value,klass){const n=document.createElement(tag);if(value!==undefined)n.textContent=String(value);if(klass)n.className=klass;return n}
  function showError(ex){el('pilotContent').textContent='无法读取当前生产状态：'+ex.message+'。请检查项目与证据，不得绕过阻断。'}
  async function loadProjects(){
    try{
      const data=await api('/api/projects');
      projectRows=data.projects||data.items||data.workflows||[];
      if(!Array.isArray(projectRows))projectRows=[];
      const select=el('pilotProject');const original=select.value;
      select.replaceChildren();select.append(new Option('选择项目…',''));
      projectRows.forEach(p=>select.append(new Option((p.name||p.id),p.id)));
      if(projectRows.some(p=>p.id===original))select.value=original;
      else if(projectRows.length)select.value=projectRows[0].id;
    }catch(e){showError(e)}
  }
  function show(p){
    active=p;const root=el('pilotContent');root.replaceChildren();
    const banner=span('div',undefined,'pilot-summary');
    banner.append(span('strong',p.project_name+' · '+p.goal));
    banner.append(span('p',p.stale?'当前输入已改变，原生产计划失效。':'从目标到结果：下方显示真实工作流状态和责任边界。'));
    const steps=span('div',undefined,'pilot-steps');
    p.steps.forEach((s,i)=>{const c=span('div',undefined,'pilot-step '+s.state);
      c.append(span('span',String(i+1).padStart(2,'0'),'pilot-num'));
      const t=span('div');t.append(span('b',s.label),span('small',s.question));c.append(t);
      c.title='责任：'+({human:'用户',safe:'独立模型引擎',ai_human:'AI + 用户',trusted:'人工确认后独立工具'}[s.owner]||s.owner);
      steps.append(c);
    });
    const next=span('section',undefined,'pilot-next');next.append(span('small','当前最重要的一步'));
    next.append(span('h3',p.next_action.label));next.append(span('p',p.next_action.help));
    const buttons=span('div',undefined,'pilot-actions');
    if(p.next_action.id==='verify_spec'){
      const go=span('button','执行安全的规格检查','tool primary');go.type='button';
      go.onclick=async()=>{go.disabled=true;try{
        const reply=await api('/api/pilot/advance',{id:p.id,revision:p.revision,baseline_digest:p.baseline_digest});show(reply);poll(reply.id);
      }catch(e){showError(e)}};
      buttons.append(go);
    }
    if(p.next_action.id==='confirm_contract'||p.next_action.id==='construct'||p.next_action.id==='review_implementation'||p.next_action.id==='repair_spec'||p.next_action.id==='evolve'){
      const go=span('button','进入项目，处理这一步','tool primary');go.type='button';
      go.onclick=()=>{if(p.next_action.id==='confirm_contract'&&typeof window.axiomJourneyOpenReview==='function')window.axiomJourneyOpenReview(p.project_id).catch(showError);else if(typeof window.AxiomFlowSetStage==='function' && ['construct','review_implementation'].includes(p.next_action.id))window.AxiomFlowSetStage(2);else if(typeof window.AxiomFlowSetStage==='function'&&p.next_action.id==='evolve')window.AxiomFlowSetStage(4);else if(typeof selectProject==='function')selectProject(p.project_id);};buttons.append(go);
    }
    const trace=span('button','下载过程交接摘要','tool secondary');trace.type='button';
    trace.onclick=async()=>{try{const data=await api('/api/pilot/handoff?id='+encodeURIComponent(p.id));
      const body=JSON.stringify(data,null,2);const blob=new Blob([body],{type:'application/json;charset=utf-8'});
      const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=data.filename||'pilot-handoff.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),500);
    }catch(e){showError(e)}};
    buttons.append(trace);next.append(buttons);
    const foot=span('p','保障范围：有限模型检查与经审查的本地测试；不会自动批准 AI 候选、运行 C++ 或签发正式发布许可。','pilot-warning');
    root.append(banner,steps,next,foot);
    window.dispatchEvent(new CustomEvent('axiom:pilot-updated',{detail:{project_id:p.project_id,operation_state:p.operation_state}}));
  }
  async function poll(mid){for(let i=0;i<60;i++){
    await new Promise(resolve=>setTimeout(resolve,1200));
    try{const current=await api('/api/pilot/get?id='+encodeURIComponent(mid));show(current);
      if(current.operation_state!=='running')break;
    }catch(e){showError(e);break}
  }}
  async function start(){const pid=el('pilotProject').value;if(!pid){el('pilotContent').textContent='请先新建或选择一个软件项目。';return;}
    el('pilotContent').textContent='正在读取目标、规则、证据与下一步…';
    try{const data=await api('/api/pilot/create',{project_id:pid});show(data);if(data.operation_state==='running')poll(data.id)}catch(e){showError(e)}
  }
  document.addEventListener('DOMContentLoaded',()=>{
    if(!el('pilotProject'))return;
    el('pilotRefresh').addEventListener('click',loadProjects);
    el('pilotBegin').addEventListener('click',start);
    loadProjects();
  });
  window.AxiomPilotRefresh=loadProjects;
  window.AxiomPilotOpen=async pid=>{await loadProjects();el('pilotProject').value=pid;await start();};
})();
