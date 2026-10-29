'use strict';
// V1.0 authoritative project cockpit. Presentation only; every action uses existing protected API.
(function(){
  const el=id=>document.getElementById(id);
  async function call(path){
    const token=new URLSearchParams(location.search).get('token')||'';
    const res=await fetch(path,{headers:{'X-Axiom-Token':token}});
    const data=await res.json();
    if(!res.ok)throw Error(data.error||('HTTP '+res.status));
    return data;
  }
  function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=String(text);if(cls)e.className=cls;return e}
  function metric(parent,value,label){const c=node('div',undefined,'cockpit-metric');c.append(node('b',value),node('small',label));parent.append(c)}
  async function refresh(){
    const root=el('cockpitSummary'),list=el('cockpitProjects'),actions=el('cockpitActions');
    if(!root||!list||!actions)return;
    root.textContent='正在核对当前项目、审计与证据…';list.replaceChildren();actions.replaceChildren();
    try{
      const data=await call('/api/cockpit');root.replaceChildren();
      metric(root,data.counts.total,'已登记项目');
      metric(root,data.counts.model_verified,'模型验证通过');
      metric(root,data.counts.awaiting_human,'待人工决策');
      metric(root,data.counts.blocked_or_stale,'阻断 / 过期');
      metric(root,data.counts.tested_only,'限定测试级裁决');
      data.projects.forEach(p=>{
        const card=node('div',undefined,'cockpit-project');
        const head=node('div',undefined,'cockpit-project-head');
        head.append(node('strong',p.name||p.id),node('span',p.state,'cockpit-state'));
        const step=node('div',undefined,'cockpit-steps');
        (p.steps||[]).forEach(s=>{const c=node('span',s.title,s.state);c.title=s.responsibility+' / '+s.state;step.append(c)});
        const bottom=node('div',undefined,'cockpit-actionline');
        const btn=node('button','进入项目','tool secondary');btn.type='button';
        btn.onclick=()=>typeof selectProject==='function'?selectProject(p.id):null;
        bottom.append(btn);
        if(p.blockers.length)bottom.append(node('small','阻断：'+p.blockers.slice(0,2).join('、')));
        else bottom.append(node('small','当前证据须经实时 Gate 检查，未授权生产发布'));
        card.append(head,step,bottom);list.append(card);
      });
      data.next_actions.slice(0,5).forEach(task=>{
        const btn=node('button',(task.category==='blocked'?'需要处理 · ':'')+task.name+' — '+task.label,'cockpit-next');
        btn.type='button';btn.title=task.reason;btn.onclick=()=>typeof selectProject==='function'?selectProject(task.project_id):null;
        actions.append(btn);
      });
      if(data.errors.length){const x=node('p','部分项目状态无法核验，默认阻断。','cockpit-warning');list.prepend(x)}
      if(!data.projects.length)list.append(node('p','还没有项目。请使用下方“新建可运行项目”开始。','cockpit-empty'));
    }catch(e){root.textContent='项目核对失败：'+e.message+'；所有未知状态均不得视为准入。'}
  }
  async function doctor(){
    try{const d=await call('/api/doctor');
      const comp=Object.entries(d.compilers).map(([k,v])=>k+': '+(v?'已找到':'未找到')).join('\n');
      alert('Axiom Studio '+(d.studio_version||d.version)+'\nPython '+d.python+'\n模型引擎：'+(d.model_engine_present?'已检测':'缺失')+'\n'+comp+'\n生产发布授权：禁用\n原生代码沙箱保证：未建立');
    }catch(e){alert('环境诊断失败：'+e.message)}
  }
  document.addEventListener('DOMContentLoaded',()=>{
    el('cockpitRefresh')?.addEventListener('click',refresh);
    el('cockpitDoctor')?.addEventListener('click',doctor);
    refresh();
  });
})();
