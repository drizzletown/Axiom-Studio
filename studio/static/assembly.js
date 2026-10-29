'use strict';
// Axiom 1.6: one user-facing lane, authoritative WorkOrders + Axiom engines.
(function(){
 const el=id=>document.getElementById(id), tok=()=>new URLSearchParams(location.search).get('token')||'';
 let active=null, projects=[], validationPolls=0;
 async function api(path,body){
   const r=await fetch(path,{method:body===undefined?'GET':'POST',headers:{'X-Axiom-Token':tok(),...(body===undefined?{}:{'Content-Type':'application/json'})},body:body===undefined?undefined:JSON.stringify(body)});
   const o=await r.json();if(!r.ok)throw Error(o.error||`HTTP ${r.status}`);return o;
 }
 const node=(tag,content,cl)=>{let e=document.createElement(tag);if(content!==undefined)e.textContent=String(content);if(cl)e.className=cl;return e};
 function error(e){el('assemblyBody').replaceChildren(node('p','生产步骤被阻断：'+e.message,'assembly-error'));}
 async function list(){
   const r=await api('/api/projects');projects=r.projects||[];
   let s=el('assemblyProject'),before=s.value;s.replaceChildren(new Option('请选择项目…',''));
   projects.forEach(x=>s.add(new Option(x.name,x.id)));
   if(projects.some(p=>p.id===before))s.value=before;
   else if(projects.length)s.value=projects[0].id;
   if(s.value){
     const t=await api('/api/assembly/targets?project_id='+encodeURIComponent(s.value));
     const targetSelect=el('assemblyTarget'),previous=targetSelect.value;
     targetSelect.replaceChildren(new Option('请选择实现模块…',''));
     (t.targets||[]).forEach(x=>targetSelect.add(new Option(x.split('/').pop(),x)));
     if((t.targets||[]).includes(previous))targetSelect.value=previous;
     else if((t.targets||[]).length)targetSelect.value=t.targets[0];
     let x=await api('/api/assembly/list?project_id='+encodeURIComponent(s.value));
     if(x.sessions.length)render(x.sessions[0]); else {active=null;el('assemblyBody').textContent='未建立构造轨迹。项目需先通过模型检查、冻结全部需求映射，并有 C++ 工程清单。';}}
 }
 async function start(){try{
   if(!el('assemblyProject').value)throw Error('请选择项目');
   let id=el('assemblyProject').value;
   const target=el('assemblyTarget').value;if(!target)throw Error('当前项目缺少可构造的实现模块，请先创建 C++ 工程');const data=await api('/api/assembly/create',{project_id:id,target});render(data);
 }catch(e){error(e)}}
 function render(v){
   active=v;const root=el('assemblyBody');root.replaceChildren();
   root.append(node('strong',v.project_name+' · '+v.goal));
   root.append(node('p','目标文件：'+v.target+' · 尝试 '+v.attempts_used+'/'+v.attempts_limit,'assembly-muted'));
   root.append(node('p',v.current?'当前规格、验收契约与候选绑定有效。':'输入已变化或证据异常，本生产线暂停。','assembly-status '+(v.current?'':'assembly-error')));
   const lane=node('div',undefined,'assembly-stages');
   ['描述软件目标','确认验收规则','AI 提出实现','人工审核和应用','独立测试','接受或演化'].forEach((s,i)=>lane.append(node('span',String(i+1)+' '+s, 'assembly-stage'+(i===(v.state==='passed'?5:v.state==='validating'?4:['reviewed','applied'].includes(v.state)?3:2)?' current':''))));
   root.append(lane);
   const next=node('section',undefined,'assembly-next');next.append(node('small','当前应该做什么'));
   next.append(node('h3',v.action.label));next.append(node('p','责任：'+v.action.owner));
   const actions=node('div',undefined,'assembly-actions');
   function b(label,fn){let btn=node('button',label,'tool primary');btn.type='button';btn.disabled=!v.current;btn.onclick=fn;actions.append(btn)}
   if(v.action.id==='propose'){
     b('连接 AI 生成候选',async()=>{if(!confirm('将发送行为规格、源码及必要的失败诊断到已配置的模型；AI 无权应用、编译或裁决。确认？'))return;await perform('/api/assembly/candidate',{id:v.id,consent:true})});
     b('导入外部 AI / VS Code 候选',()=>showPaste(v));
   }
   if(v.action.id==='review')b('审查候选与摘要',()=>showReview(v));
   if(v.action.id==='apply')b('批准应用候选',async()=>{if(!confirm('已人工审阅完整候选，将写入目标源码并保留备份。确认应用？'))return;await perform('/api/assembly/apply',{id:v.id,confirmation:'human_authorized_apply'})});
   if(v.action.id==='verify')b('授权独立 C++ 测试',async()=>{if(!confirm('将真实编译和运行本地 C++，实验性隔离不能保证不可信代码安全。确认代码已审查并可信？'))return;await perform('/api/assembly/verify',{id:v.id,trusted:true})});
   if(v.action.id==='poll')b('刷新独立验证结果',()=>perform('/api/assembly/poll?id='+encodeURIComponent(v.id)));
   if(v.action.id==='repair')b('人工回退，准备下一轮构造',async()=>{if(!confirm('恢复本次应用前的源文件（先核验摘要），并保留失败证据？'))return;await perform('/api/assembly/revert',{id:v.id,confirmation:'human_reject_and_revert'})});
   const handoff=node('button','导出本次生产过程','tool secondary');handoff.type='button';handoff.onclick=async()=>{try{let d=await api('/api/assembly/handoff?id='+encodeURIComponent(v.id));const url=URL.createObjectURL(new Blob([JSON.stringify(d,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=d.filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}catch(e){error(e)}};actions.append(handoff);
   next.append(actions);root.append(next);
   if(v.diagnostic?.reason){const fault=node('details',undefined,'assembly-diagnostic');fault.append(node('summary','查看失败原因与修复约束'));fault.append(node('pre',JSON.stringify(v.diagnostic,null,2)));root.append(fault)}
   root.append(node('p','AI 输出只是候选。测试级通过不是生产发布许可；最终准入需回到项目 Gate 和人工裁决。','assembly-muted'));
   if(v.action.id==='poll' && validationPolls++<30)setTimeout(()=>refresh(v.id).catch(error),1500);
   if(v.action.id!=='poll')validationPolls=0;
 }
 async function refresh(id){let r=await api('/api/assembly/poll?id='+encodeURIComponent(id));render(r)}
 async function perform(path,data){try{let r=await api(path,data);render(r)}catch(e){error(e)}}
 function showPaste(v){
   let panel=node('div',undefined,'assembly-paste');let label=node('label','把外部 AI 生成的完整 C++ 文件粘贴到这里');
   let t=node('textarea');t.rows=10;t.placeholder='仅暂存候选，系统不会自动执行';label.append(t);panel.append(label);
   const btn=node('button','暂存候选，进入人工审查','tool primary');btn.onclick=()=>perform('/api/assembly/candidate',{id:v.id,code:t.value});panel.append(btn);el('assemblyBody').append(panel);
 }
 async function showReview(v){try{
   let proposal=await api('/api/proposal?id='+encodeURIComponent(v.candidate_id));
   const root=el('assemblyBody'),panel=node('section',undefined,'assembly-review');panel.append(node('h3','请完整阅读此候选，再决定是否批准'));
   let digest=node('p','候选 SHA-256：'+proposal.code_sha256,'assembly-muted');panel.append(digest);
   let code=node('pre',proposal.code,'assembly-code');panel.append(code);
   const label=node('label','输入 SHA-256 前 12 位表示已人工审查');let inp=node('input');inp.placeholder=proposal.code_sha256.slice(0,12);label.append(inp);panel.append(label);
   const btn=node('button','人工确认并批准摘要','tool primary');btn.onclick=async()=>{if(inp.value!==proposal.code_sha256.slice(0,12))return error(Error('摘要确认不匹配'));if(!confirm('确认已审阅完整候选，且保留全部原始测试与验收规则？'))return;await perform('/api/assembly/review',{id:v.id,digest:proposal.code_sha256,approved:true})};panel.append(btn);root.append(panel);
 }catch(e){error(e)}}
 document.addEventListener('DOMContentLoaded',()=>{if(!el('assemblyHome'))return;
  el('assemblyRefresh').onclick=()=>list().catch(error);el('assemblyProject').onchange=()=>list().catch(error);el('assemblyStart').onclick=start;
  list().catch(error);
 });
 window.AxiomAssemblyOpen=async (pid,target)=>{await list();el('assemblyProject').value=pid;await list();if(target){const opts=[...el('assemblyTarget').options].map(o=>o.value);if(!opts.includes(target))throw Error('目标文件不在当前构造范围');el('assemblyTarget').value=target;}await start();el('assemblyHome').scrollIntoView({behavior:'smooth'})};
})();
