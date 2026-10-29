'use strict';
/* 2.0.2: one visual process, backed by the existing authorized controllers.
 * This is a presentation/orchestration adapter. Never claims evidence or skips Gates.
 */
(function(){
 const $=id=>document.getElementById(id);
 const stages=[
  ['目标','说清楚要做什么'],['规则','明确什么必须正确'],
  ['构造','让 AI 提出实现方案'],['验证','独立检查实际实现'],
  ['交付','看证据，决定下一版']
 ];
 let rows=[],chosen='',viewed=0,forceStage=false,loading=false;
 function announce(t){const n=$('flowError');n.textContent=t||'';n.classList.toggle('hidden',!t)}
 function completed(st){return st==='passed'||st==='recorded'}
 function actualStage(row){
  if(!row)return 0;
  if(row.stale)return 1;
  if(row.tested_only)return 4;
  const next=row.next?.id;
  if(next==='verify'||next==='freeze')return 1;
  if(['task','candidate','batch'].includes(next))return 2;
  if(next==='passport')return 3;
  if(next==='fork')return 4;
  if(!completed(row.steps?.[1]?.state)||!completed(row.steps?.[2]?.state))return 1;
  if(!completed(row.steps?.[3]?.state))return 2;
  if(!completed(row.steps?.[4]?.state))return 3;
  return 4;
 }
 function chooseStage(step){viewed=step;forceStage=true;render();}
 function updateStepbar(row){
  const root=$('flowSteps');root.replaceChildren();
  stages.forEach(([label,help],i)=>{
   const button=document.createElement('button');button.type='button';
   const done=!!row&&!row.stale&&(i===0?completed(row.steps?.[0]?.state):i===1?completed(row.steps?.[1]?.state)&&completed(row.steps?.[2]?.state):completed(row.steps?.[i+1]?.state));
   button.className='flow-step'+(i===viewed?' active':'')+(done?' done':'');
   button.setAttribute('aria-current',i===viewed?'step':'false');
   const prefix=document.createElement('span');prefix.className='flow-step-index';prefix.textContent=done?'✓':String(i+1);
   const title=document.createElement('span');title.className='flow-step-name';title.textContent=label;
   button.append(prefix,title);button.title=help;
   button.addEventListener('click',()=>chooseStage(i));root.append(button);
  });
 }
 function mount(source,target){const s=$(source),t=$(target);if(s&&t)t.appendChild(s)}
 function syncOriginalProject(id){
  const pilot=$('pilotProject');if(pilot&&[...pilot.options].some(o=>o.value===id))pilot.value=id;
  const assembly=$('assemblyProject');if(assembly&&[...assembly.options].some(o=>o.value===id)&&assembly.value!==id){assembly.value=id;assembly.dispatchEvent(new Event('change'))}
  const m20=$('m20Project');if(m20&&[...m20.options].some(o=>o.value===id)&&m20.value!==id){m20.value=id;m20.dispatchEvent(new Event('change'))}
 }
 function render(){
  const row=rows.find(x=>x.id===chosen)||null;
  if(!row)viewed=0;
  updateStepbar(row);
  $('flowProjectPicker').classList.toggle('hidden',rows.length===0);
  const select=$('flowProjectSelect');
  if(select.value!==chosen)select.value=chosen;
  $('flowPhaseNumber').textContent=`第 ${viewed+1} 步 / 共 5 步`;
  $('flowPhaseTitle').textContent=stages[viewed][0];
  $('flowPhaseSubtitle').textContent=row?(viewed===actualStage(row)?row.next?.explanation:stages[viewed][1]):'写下一句话，开始你自己的软件项目。';
  ['flowStartStage','flowGoalStage','flowRulesStage','flowBuildStage','flowVerifyStage','flowDeliveryStage'].forEach(id=>$(id).classList.add('hidden'));
  const stageId=!row?'flowStartStage':['flowGoalStage','flowRulesStage','flowBuildStage','flowVerifyStage','flowDeliveryStage'][viewed];
  $(stageId).classList.remove('hidden');
  if(row){
   $('flowGoalText').textContent=row.goal||'此项目尚未填写目标';
   $('flowDeliveryTitle').textContent=row.tested_only?'本地测试级检查已有记录':row.stale?'输入已改变，旧证据失效':(row.next?.label||'等待形成可信交付证据');
   $('flowDeliveryText').textContent=row.stale?'必须先建立新的演化版本并重新确认规格和证据。':(row.next?.explanation||'独立验证和人工裁决完成后，才可以确认测试级结果。');
   $('flowFootNote').textContent=row.stale?'输入变化已使原流程失效；不能沿用旧批准。':'当前验证结论有明确范围，不代表已获生产发布许可。';
   syncOriginalProject(row.id);
  }else $('flowFootNote').textContent='无需先学习 Axiom 语法。案例仅是起点，不证明全部自然语言目标。';
  $('flowHome').dataset.phase=String(viewed);
 }
 async function refresh(prefer){
  if(loading)return;loading=true;
  try{
   const data=await wfApi('/api/journey');rows=Array.isArray(data.projects)?data.projects:[];
   if(prefer!==undefined){chosen=prefer;forceStage=false}
   else if(chosen&&!rows.some(p=>p.id===chosen))chosen='';
   if(!chosen&&rows.length&&prefer===undefined)chosen=rows[0].id;
   const select=$('flowProjectSelect');select.replaceChildren(new Option('＋ 创建新项目',''));
   rows.forEach(row=>select.add(new Option(row.name,row.id)));
   select.value=chosen;
   const row=rows.find(x=>x.id===chosen);
   if(!forceStage)viewed=actualStage(row);
   render();announce(data.errors?.length?'部分项目状态暂时无法核验。请检查详细记录，未知状态不能作为通过证据。':'');
  }catch(e){announce('无法加载项目生产进度：'+e.message)}finally{loading=false}
  }
 function newProject(){chosen='';viewed=0;forceStage=true;$('flowProjectSelect').value='';render();$('journeyName').focus();}
 function showAdvanced(){
  $('flowAdvanced').open=true;
  $('journeyAdvanced').open=true;
  if(chosen&&typeof selectProject==='function')selectProject(chosen).catch(e=>announce(e.message));
  $('flowAdvanced').scrollIntoView({block:'start',behavior:'smooth'});
 }
 function boot(){
  // Reuse, do not duplicate, the working form, pilot, construction and verification controls.
  mount('journeyStartForm','flowStartFormMount');
  mount('pilotHome','flowPilotMount');
  mount('assemblyHome','flowAssemblyMount');
  mount('milestone20Home','flowVerifyMount');
  mount('productionTools','flowAdvancedMount');
  mount('journeyAdvanced','flowAdvancedMount');
  // The old overview remains available to the legacy code but is no longer the default UI.
  $('flowNewProject').onclick=newProject;
  $('flowProjectSelect').onchange=e=>{chosen=e.target.value;forceStage=false;viewed=actualStage(rows.find(r=>r.id===chosen));render();if(chosen)window.AxiomPilotOpen?.(chosen).catch(e=>announce(e.message))};
  $('flowGoalContinue').onclick=()=>chooseStage(1);
  $('flowDeliveryDetail').onclick=showAdvanced;
  $('flowRefresh').onclick=()=>refresh();
  $('flowToolsToggle').onclick=()=>{const d=$('flowAdvanced');d.open=!d.open;if(d.open)d.scrollIntoView({behavior:'smooth',block:'nearest'})};
  $('flowStartFormMount').classList.add('flow-create-form');
  window.addEventListener('axiom:pilot-updated',ev=>{if(ev.detail?.project_id===chosen && ev.detail?.operation_state!=='running')refresh().catch(e=>announce(e.message))});
  refresh();
 }
 document.addEventListener('DOMContentLoaded',boot);
 window.AxiomFlowSetStage=chooseStage;
 window.AxiomFlowNewProject=newProject;
 window.AxiomFlowRefresh=refresh;
 window.AxiomFlowOpen=async id=>{
  forceStage=false;
  await refresh(id);
  $('projectDashboard').scrollTo({top:0,behavior:'smooth'});
 };
})();
