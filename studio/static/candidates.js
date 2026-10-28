'use strict';
// Standalone workbench controller; reuses the token-based API, toast and review dialog in app.js.
const candidateState={selected:null,list:[],running:false};
const candidateQ=id=>document.getElementById(id);
const candidateSafe=s=>String(s).slice(0,200);
async function candidateRefresh(){
  try{
    const [list,provider]=await Promise.all([api('/api/proposals'),api('/api/providers')]);
    candidateState.list=list.proposals;
    candidateQ('providerInfo').textContent=provider.configured?`模型已配置：${provider.model}。仅在主动确认后发送规格和代码。`:'模型未连接。仍可粘贴外部 AI 候选，完成全部审查验证。';
    const el=candidateQ('candidateList'),mini=candidateQ('candidateMiniList');el.replaceChildren();mini.replaceChildren();
    list.proposals.forEach(p=>{
      const btn=document.createElement('button');btn.className='candidate-item'+(p.id===candidateState.selected?' selected':'');
      const a=document.createElement('strong');a.textContent=p.status+(p.current?'':' · 失效');btn.appendChild(a);
      const b=document.createElement('span');b.textContent=p.id.slice(0,12)+' · '+p.target.split('/').at(-1);btn.appendChild(b);
      btn.onclick=()=>candidateSelect(p.id);el.appendChild(btn);
      const m=document.createElement('div');m.textContent=p.status+' · '+p.id.slice(0,11);m.onclick=()=>{candidateOpen();candidateSelect(p.id)};mini.appendChild(m);
    });
    if(!list.proposals.length)el.textContent='还没有候选。';
  }catch(e){toast('读取候选失败：'+e.message)}
}
async function candidateSelect(id){
  try{
    const p=await api('/api/proposal?id='+encodeURIComponent(id));candidateState.selected=id;
    candidateQ('candidateDetails').textContent=`状态: ${p.status} ${p.current?'':'(已失效)'}\n规格: ${p.spec}\n语义: ${p.spec_digest}\n源码 SHA-256: ${p.code_sha256}\n来源: ${p.source}${p.model?' / '+p.model:''}\n义务: ${p.obligations} · ${new Date(p.created_at*1000).toLocaleString()}`;
    candidateQ('candidateAfter').textContent=p.code;
    try{const f=await api('/api/file?path='+encodeURIComponent(p.target));candidateQ('candidateBefore').textContent=f.content}catch{candidateQ('candidateBefore').textContent='[当前源码不可读取]'}
    candidateQ('candidateReview').disabled=p.status!=='proposed'||!p.current;
    candidateQ('candidateApply').disabled=p.status!=='reviewed'||!p.current;
    candidateQ('candidateValidate').disabled=!['applied','blocked','verified'].includes(p.status)||!p.current;
    candidateQ('candidateOutcome').textContent=p.validation?`最近验证：${p.validation.passed?'Approved (测试级)':'Blocked'}；生产发布未获授权。`:'尚无对该候选完成的独立验证。';
    await candidateRefresh();
  }catch(e){toast('候选读取失败：'+e.message)}
}
function candidateOpen(){candidateQ('candidateOverlay').classList.remove('hidden');candidateRefresh()}
async function projectCandidateLink(p){
  // Project collaboration never bypasses the existing proposal approval boundary.
  if(typeof wf==='undefined'||!wf.detail||wf.detail.effective_status!=='spec_ready')return;
  if(p.manifest!==wf.detail.manifest||p.spec!==wf.detail.spec)return;
  try{await wfApi('/api/project/attach','POST',{id:wf.detail.id,candidate_id:p.id});await loadProjects()}
  catch(e){toast('候选已暂存；项目自动绑定失败：'+e.message)}
}
async function projectCandidateSync(id){
  if(typeof wf==='undefined'||wf.detail?.candidate_id!==id)return;
  try{await wfApi('/api/project/sync','POST',{id:wf.detail.id});await loadProjects()}
  catch(e){toast('候选状态变化，请检查项目全景：'+e.message)}
}
async function candidateStage(){
  try{
    const manifest=candidateQ('candidateManifest').value.trim(),target=candidateQ('candidateTarget').value.trim(),code=candidateQ('candidateCode').value;
    const ret=await api('/api/proposal/create','POST',{manifest,target,code});candidateQ('candidateCode').value='';await candidateSelect(ret.id);await projectCandidateLink(ret);toast('候选已隔离暂存；尚未写入工作区')
  }catch(e){toast('暂存失败：'+e.message)}
}
async function candidateGenerate(){
  const provider=await api('/api/providers');if(!provider.configured){toast('未配置模型；可先将候选 C++ 代码粘贴到左侧。');return}
  if(!confirm(`将当前 Axiom 规格及目标 C++ 代码发送到配置模型 ${candidateSafe(provider.model)}。继续吗？`))return;
  candidateQ('candidateGenerate').disabled=true;
  try{const p=await api('/api/proposal/generate','POST',{manifest:candidateQ('candidateManifest').value.trim(),target:candidateQ('candidateTarget').value.trim(),consent:true});await candidateSelect(p.id);await projectCandidateLink(p);toast('模型候选已暂存，请仔细人工审查；代码未运行')}
  catch(e){toast('模型调用失败：'+e.message)}finally{candidateQ('candidateGenerate').disabled=false}
}
async function candidateReview(){
  const p=await api('/api/proposal?id='+encodeURIComponent(candidateState.selected));
  if(!confirm(`确认已逐行审查候选 C++ 源码及其行为边界？\n${p.target}\nSHA-256 ${p.code_sha256}\n本操作不会写入源码或启动编译。`))return;
  try{await api('/api/proposal/review','POST',{id:p.id,digest:p.code_sha256,approved:true});await candidateSelect(p.id);await projectCandidateSync(p.id);toast('人工审查批准，尚未应用源码')}
  catch(e){toast('批准失败：'+e.message)}
}
async function candidateApply(){
  const p=await api('/api/proposal?id='+encodeURIComponent(candidateState.selected));
  const doc=state.docs.get(p.target);if(doc?.dirty){toast('编辑器中目标文件尚未保存，请先保存或关闭编辑再应用');return}
  if(!confirm(`应用候选将改写 ${p.target}。会保留原始内容的 SHA-256 快照；不会自动编译或运行。是否继续？`))return;
  try{
    await api('/api/proposal/apply','POST',{id:p.id});
    if(state.docs.has(p.target)){
      const f=await api('/api/file?path='+encodeURIComponent(p.target));
      state.docs.set(p.target,{content:f.content,original:f.content,sha256:f.sha256,dirty:false});if(state.active===p.target)renderFile();
    }
    await candidateSelect(p.id);await projectCandidateSync(p.id);toast('候选已写入工作区；需单独确认后才能验证')
  }catch(e){toast('应用失败：'+e.message)}
}
async function candidateValidate(){
  if(candidateState.running)return;
  const ok=await askTrust('cpp-project-full');if(!ok)return;
  candidateState.running=true;candidateQ('candidateValidate').disabled=true;
  try{
    const r=await api('/api/proposal/validate','POST',{id:candidateState.selected,trusted:true});
    const id=candidateState.selected;toast('已开始独立验证与 Gate 检查');appendLog(`候选 ${id} · 独立验证开始`);
    for(let i=0;i<190;i++){
      await new Promise(resolve=>setTimeout(resolve,750));
      const j=await api('/api/job?id='+encodeURIComponent(r.job_id));
      if(j.status!=='queued'&&j.status!=='running'){
        if(j.result){inspectOutcome(j.result,'candidate-validate',j.elapsed);q('#consoleJson').textContent=JSON.stringify(j.result,null,2)}
        appendLog(`${id}: ${j.result?.decision||'Blocked'} / ${j.elapsed}s`,j.returncode===0?'success':'error');
        candidateQ('candidateOutcome').textContent=j.result?.decision==='Approved'?'✓ 测试级 Approved。未授权生产发布。':'× Blocked。请检查完整报告和错误详情。';
        await candidateSelect(id);await candidateRefresh();await projectCandidateSync(id);toast('验证完成：'+(j.result?.decision||'Blocked'));return;
      }
    }
    toast('验证仍在运行，请查看任务历史')
  }catch(e){toast('验证失败：'+e.message)}finally{candidateState.running=false;candidateQ('candidateValidate').disabled=false}
}
function initCandidates(){
  candidateQ('candidateOpen').onclick=candidateOpen;candidateQ('btnCandidate').onclick=candidateOpen;
  candidateQ('candidateClose').onclick=()=>candidateQ('candidateOverlay').classList.add('hidden');
  candidateQ('candidateRefresh').onclick=candidateRefresh;candidateQ('candidateReload').onclick=candidateRefresh;
  candidateQ('candidateLoad').onclick=async()=>{try{const f=await api('/api/file?path='+encodeURIComponent(candidateQ('candidateTarget').value.trim()));candidateQ('candidateCode').value=f.content;toast('已载入当前目标代码作为候选草稿')}catch(e){toast('载入失败：'+e.message)}};
  candidateQ('candidateGenerate').onclick=candidateGenerate;candidateQ('candidateStage').onclick=candidateStage;
  candidateQ('candidateReview').onclick=candidateReview;candidateQ('candidateApply').onclick=candidateApply;candidateQ('candidateValidate').onclick=candidateValidate;
  document.addEventListener('keydown',e=>{if(e.key==='Escape')candidateQ('candidateOverlay').classList.add('hidden')});
}
