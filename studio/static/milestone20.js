'use strict';
// Milestone 2.0: text-first verification & evidence navigation. Never auto-executes native code.
(() => {
  const el=id=>document.getElementById(id), token=()=>new URLSearchParams(location.search).get('token')||'';
  const node=(tag,text,cls)=>{let x=document.createElement(tag);if(text!==undefined)x.textContent=String(text);if(cls)x.className=cls;return x};
  const api=async(path,body)=>{let res=await fetch(path,{method:body===undefined?'GET':'POST',headers:{'X-Axiom-Token':token(),...(body===undefined?{}:{'Content-Type':'application/json'})},body:body===undefined?undefined:JSON.stringify(body)});let data=await res.json();if(!res.ok)throw Error(data.error||'操作失败');return data};
  let current=null,poller=null;
  async function refresh(){
    const list=await api('/api/projects'),sel=el('m20Project'),old=sel.value;
    sel.replaceChildren(new Option('请选择具有 C++ 工程的项目',''));
    (list.projects||[]).filter(p=>p.manifest).forEach(p=>sel.add(new Option(p.name,p.id)));
    if([...sel.options].some(x=>x.value===old))sel.value=old;else if(sel.options.length>1)sel.selectedIndex=1;
    await show();
  }
  async function show(){
    const pid=el('m20Project').value;
    if(!pid){el('m20Body').textContent='请先选择一个已关联 C++ 工程的项目。';return}
    const list=await api('/api/milestone20/list?project_id='+encodeURIComponent(pid));
    if(!list.campaigns.length){el('m20Body').textContent='尚无验证批次。点击「创建验证批次」，系统会冻结验证输入并分析影响范围。';current=null;return}
    render(list.campaigns[0]);
  }
  function render(v){
    current=v;const root=el('m20Body');root.replaceChildren();
    root.append(node('h3','交付验证 · '+({planned:'待执行',running:'验证中',passed:'测试级通过',blocked:'已阻断'}[v.state]||v.state)));
    root.append(node('p',v.current?'输入与冻结契约仍一致':'当前批次已失效：'+v.blocker,v.current?'assembly-status':'assembly-error'));
    const p=v.plan;
    const impact=node('div',undefined,'graph-module');
    impact.append(node('strong','本次变更 '+p.changed_files.length+' 个文件，预计影响 '+p.impacted_tests.length+' 项测试'));
    impact.append(node('p',p.impacted_tests.length?p.impacted_tests.join('、'):'无直接受影响测试；全局集成检查仍然必做','assembly-muted'));
    impact.append(node('p','独立检查：规格验证、模型 Gate、C++ 工程回归、工程 Gate','assembly-muted'));
    root.append(impact);
    if(v.state==='planned' && v.current){
      let b=node('button','确认代码可信并开始实际验证','tool primary');
      b.onclick=async()=>{if(!confirm('本次将编译并执行工程中的 C++ 程序。仅适用于已经人工审查并可信的本地源码；这不是安全沙箱。是否授权？'))return;
        try{render(await api('/api/milestone20/start',{id:v.id,trusted:true}));watch(v.id)}catch(e){root.append(node('p',e.message,'assembly-error'))}};
      root.append(b);
    }
    for(const c of (v.result?.checks||[])){
      let row=node('p',(c.ok?'✓ ':'✗ ')+c.action+' · '+(c.outcome||c.returncode),c.ok?'assembly-status':'assembly-error');root.append(row);
    }
    if(v.result?.error)root.append(node('p',v.result.error,'assembly-error'));
    let exp=node('button','导出本次验证与证据摘要','tool secondary');exp.onclick=async()=>{try{let h=await api('/api/milestone20/handoff?id='+encodeURIComponent(v.id));let url=URL.createObjectURL(new Blob([JSON.stringify(h.report,null,2)],{type:'application/json'}));let a=node('a');a.href=url;a.download=h.filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}catch(e){root.append(node('p',e.message,'assembly-error'))}};root.append(exp);
    root.append(node('p','这里的通过只代表绑定输入的本地模型和 C++ 测试级结论，不是产品发布授权。','assembly-muted'));
    if(v.state==='running' && !poller)watch(v.id);
  }
  function watch(id){
    if(poller)clearInterval(poller);
    let count=0;poller=setInterval(async()=>{
      if(++count>80){clearInterval(poller);poller=null;return}
      try{let v=await api('/api/milestone20/get?id='+encodeURIComponent(id));render(v);
           if(v.state!=='running'){clearInterval(poller);poller=null}}
      catch(e){clearInterval(poller);poller=null}
    },2500);
  }
  async function create(){try{
      const project_id=el('m20Project').value;if(!project_id)return;
      const list=await api('/api/milestone20/list?project_id='+encodeURIComponent(project_id));
      const previous=(list.campaigns||[]).find(c=>c.state==='passed');
      const v=await api('/api/milestone20/create',{project_id,previous_id:previous?.id||null});render(v);
    }catch(e){el('m20Body').replaceChildren(node('p','无法创建验证批次：'+e.message,'assembly-error'))}}
  function boot(){el('m20Refresh')?.addEventListener('click',()=>refresh().catch(e=>el('m20Body').textContent=e.message));
    el('m20Create')?.addEventListener('click',create);
    el('m20Project')?.addEventListener('change',()=>show().catch(e=>el('m20Body').textContent=e.message));
    refresh().catch(e=>el('m20Body').textContent=e.message)}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();
