'use strict';
// AI work-order UI. Requests are review gated. No automatic native execution.
function woEsc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function woSection(project,all){
  const jobs=(all||[]).filter(x=>x.manifest===project.manifest);
  const w=jobs[0];
  let h='<div class="project-production"><h3>AI 软件生产工单 · V0.9</h3><p class="project-assurance">目标绑定 → AI 生成或粘贴代码 → 人工核对摘要 → 受控应用 → 独立验证 → 失败诊断 → 人工回退与再构造。可复用 VS Code；不会自动编译未审查的代码。</p>';
  if(!project.manifest){h+='<p class="project-assurance">此项目尚无 C++ 工程清单，先完成行为规格及实现工程配置。</p></div>';return h;}
  if(!w){h+='<div class="project-action-row"><button class="tool primary" data-wo="create">建立 AI 构造工单</button></div></div>';return h;}
  h+=`<div class="project-kv"><span>工单</span><code>${woEsc(w.id)}</code></div><div class="project-kv"><span>状态</span><code>${woEsc(w.state)} · ${w.current?'版本匹配':'版本变更，需重建'}</code></div><div class="project-kv"><span>迭代</span><code>${w.attempts.length}/${w.max_attempts}</code></div><div class="project-kv"><span>目标</span><code>${woEsc(w.target)}</code></div>`;
  if(w.diagnostic?.reason)h+=`<div class="project-blockers">${woEsc(w.diagnostic.reason)}</div>`;
  h+='<div class="project-action-row">';
  if(['ready','reverted'].includes(w.state))h+='<button class="tool primary" data-wo="generate">调用 AI 生成候选</button><button class="tool secondary" data-wo="submit">粘贴外部候选</button>';
  if(w.state==='proposed')h+='<button class="tool primary" data-wo="review">核对候选并人工审批</button>';
  if(w.state==='reviewed')h+='<button class="tool primary" data-wo="apply">人工授权应用</button>';
  if(w.state==='applied')h+='<button class="tool primary" data-wo="verify">执行独立 C++ 验证</button>';
  if(w.state==='validating')h+='<button class="tool primary" data-wo="poll">获取验证结果</button>';
  if(['blocked','interrupted'].includes(w.state))h+='<button class="tool secondary" data-wo="feedback">查看失败诊断</button><button class="tool primary" data-wo="revert">人工回退后重构</button>';
  h+='<button class="tool secondary" data-wo="detail">查看工单记录</button></div>';
  if(w.state==='passed')h+='<div class="project-verdict">✓ 受限 C++ 测试级验证通过。仍需独立生产契约审查和发布 Gate；本结果不是生产许可。</div>';
  h+='</div>';return h;
}
async function woAction(action){
  try{
    let w=(wf.workorders||[]).filter(x=>x.manifest===wf.detail.manifest)[0];let result;
    if(action==='create'){
      const manifest=await wfApi('/api/file?path='+encodeURIComponent(wf.detail.manifest));
      const obj=JSON.parse(manifest.content);
      const folder=wf.detail.manifest.includes('/')?wf.detail.manifest.slice(0,wf.detail.manifest.lastIndexOf('/')+1):'';
      const choices=(obj.files||[]).filter(x=>/\.(cpp|cc)$/.test(x)&&!/(^|\/)test[_-]/.test(x)).map(x=>folder+x);
      const target=prompt('选择工单实现目标（须在项目清单内）',choices[0]||'');if(!target)return;
      const goal=prompt('本次软件构造目标（至少 3 字）',wf.detail.goal||'实现当前行为规格');if(!goal)return;
      result=await wfApi('/api/workorder/create','POST',{manifest:wf.detail.manifest,target,goal,max_attempts:3});
    }else{
      if(!w)throw new Error('工单不存在');
      const id=w.id;
      if(action==='generate'){
        if(!confirm('将向已配置的 AI 模型发送当前 Axiom 规格、C++ 实现和失败诊断。仅暂存生成结果，不自动应用或编译。是否同意？'))return;
        result=await wfApi('/api/workorder/generate','POST',{id,consent:true});
      }else if(action==='submit'){
        const code=prompt('粘贴完整 C++ 候选源码；只暂存，不会执行','');if(!code)return;
        result=await wfApi('/api/workorder/submit','POST',{id,code});
      }else if(action==='review'){
        const proposal=await wfApi('/api/proposal?id='+encodeURIComponent(w.active_proposal));
        const digest=proposal.code_sha256;
        const ok=prompt('请在候选工作台审读全部代码。输入 SHA-256 前 12 位以批准：'+digest,'');
        if(ok!==digest.slice(0,12))throw new Error('摘要不一致，审批取消');
        result=await wfApi('/api/workorder/review','POST',{id,digest,approved:true});
      }else if(action==='apply'){
        if(!confirm('代码将覆盖目标文件，系统保留内容寻址备份。确认是人工审核过的受信任候选？'))return;
        result=await wfApi('/api/workorder/apply','POST',{id,confirmation:'human_authorized_apply'});
      }else if(action==='verify'){
        if(!confirm('将实际编译并执行 C++。确认源码可信，且接受本机实验性执行隔离不等于生产安全沙箱？'))return;
        result=await wfApi('/api/workorder/verify','POST',{id,trusted:true});
      }else if(action==='poll')result=await wfApi('/api/workorder/poll?id='+encodeURIComponent(id));
      else if(action==='revert'){
        if(!confirm('当前验证失败/中断。确认人工回退当前源码并保留失败记录？'))return;
        result=await wfApi('/api/workorder/revert','POST',{id,confirmation:'human_reject_and_revert'});
      }else if(action==='feedback'){result=await wfApi('/api/workorder/feedback?id='+encodeURIComponent(id));alert(JSON.stringify(result,null,2));return;}
      else if(action==='detail'){result=await wfApi('/api/workorder?id='+encodeURIComponent(id));alert(JSON.stringify(result,null,2));return;}
    }
    wfNotify('工单操作完成：'+(result.state||'更新'));await selectProject(wf.detail.id);
  }catch(e){wfNotify('工单受控阻断：'+e.message)}
}
