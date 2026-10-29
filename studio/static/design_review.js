'use strict';
// Present model deltas and risk clues; never turn these clues into an approval.
(function(){
  const $=id=>document.getElementById(id);
  const el=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=String(text);if(cls)e.className=cls;return e};
  let pid=null, options=[];
  const labels={types:'数据类型',state:'系统状态',actions:'可执行动作',properties:'行为约束',observe:'对外可观察结果'};
  const keys=['types','state','actions','properties','observe'];
  function card(parent,title,description,cls){const box=el('div',undefined,cls||'design-review-card');box.append(el('strong',title));if(description)box.append(el('div',description,'design-review-hint'));parent.append(box);return box;}
  function err(text,target){const n=$(target);if(n)n.textContent=text;}
  function summary(d,root){
    const s=Object.entries(d.deltas).filter(([,v])=>v.added.length||v.removed.length||v.changed.length);
    const head=card(root,`已独立检查 · ${d.properties.length} 项行为约束`,
      '以下变化来自规格结构比对。模型验证通过，并不意味着现实需求已经全部满足。');
    for(const [key,v] of s){
      const parts=[];if(v.added.length)parts.push('新增：'+v.added.join('、'));
      if(v.removed.length)parts.push('移除：'+v.removed.join('、'));
      if(v.changed.length)parts.push('修改：'+v.changed.join('、'));
      head.append(el('div',`${labels[key]} · ${parts.join('；')}`,'design-review-hint'));
    }
    if(!s.length)head.append(el('div','没有发现结构或性质表达式的变化。','design-review-hint'));
    const risks=card(root,'需要你留意的地方');
    for(const warning of d.warnings)risks.append(el('p',warning,'design-review-warn'));
    const missing=d.scenarios.filter(x=>x.status!=='unchanged');
    card(root,`验收场景 · ${d.scenarios.length-missing.length}/${d.scenarios.length} 条保留了原性质表达式`,
      '这里的数字只是原性质结构保持情况，不是业务需求覆盖率。');
    for(const r of d.scenarios){const row=el('div',undefined,'design-review-hint');
      row.append(el('span',r.id+' · '+r.title+' · '));
      row.append(el('span',r.message,'design-review-tag'));root.append(row)}
    if(d.properties.length){
      const detail=el('details');detail.append(el('summary','查看模型规则的可读提示（需人工核对）'));
      for(const p of d.properties)card(detail,p.name+ ' · '+({new:'新增',modified:'修改',unchanged:'原样保留'}[p.status]||p.status),p.expression_hint);
      root.append(detail);
    }
  }
  async function inspect(projectId,candidateId){
    const root=$('designReviewExplanation');if(!root||!projectId)return;
    pid=projectId;root.textContent='正在读取独立检查结果…';
    try{
      const data=await wfApi('/api/design-review/inspect?id='+encodeURIComponent(projectId)+'&candidate='+encodeURIComponent(candidateId));
      if(pid!==projectId)return;
      root.replaceChildren();summary(data,root);
    }catch(e){err('只有当前、已通过模型检查的候选才能生成评审：'+e.message,'designReviewExplanation')}
  }
  function refresh(projectId,candidates){
    pid=projectId;options=(candidates||[]).filter(x=>x.current&&['checked','promoted'].includes(x.state)&&x.assessment_passed);
    for(const id of ['designReviewA','designReviewB']){
      const select=$(id);if(!select)continue;
      const selected=select.value;select.replaceChildren();
      for(const c of options){const o=el('option',c.id.slice(0,18)+' · '+(c.origin==='model'?'AI 候选':'手动候选'));o.value=c.id;select.append(o)}
      if(options.some(x=>x.id===selected))select.value=selected;
    }
    if(options.length>1&&$('designReviewA').value===$('designReviewB').value)$('designReviewB').value=options[1].id;
    $('designReviewCompare').disabled=options.length<2;
    $('designReviewComparison').textContent=options.length<2?'先完成两份候选的独立检查，才能进行方案比较。':'可比较两份候选。对比不自动决定哪份更适合业务目标。';
    if(!options.length)$('designReviewExplanation').textContent='先独立检查候选，系统再解释规则变化、验收缺口与需人工评审的风险。';
  }
  async function compare(){
    const a=$('designReviewA').value,b=$('designReviewB').value,root=$('designReviewComparison');
    if(a===b){root.textContent='请选择两份不同的候选。';return}
    root.textContent='正在比较模型结构和验收场景…';
    try{
      const data=await wfApi('/api/design-review/compare?id='+encodeURIComponent(pid)+'&candidate='+encodeURIComponent(a)+'&candidate='+encodeURIComponent(b));
      root.replaceChildren();
      const [A,B]=data.candidates;
      card(root,'没有自动胜出者','两份候选均通过限定的模型检查。选择需要依据业务意图、未覆盖的需求和人工审查；结构变化少不代表质量更好。');
      card(root,'方案 A · '+A.id.slice(0,16),`有 ${A.unresolved_scenarios} 条场景需要重新确认。`);
      card(root,'方案 B · '+B.id.slice(0,16),`有 ${B.unresolved_scenarios} 条场景需要重新确认。`);
      for(const key of keys){const d=data.differences_between_candidates[key];if(!d.added.length&&!d.removed.length&&!d.changed.length)continue;
        const lines=[];if(d.added.length)lines.push('B 独有：'+d.added.join('、'));
        if(d.removed.length)lines.push('A 独有：'+d.removed.join('、'));
        if(d.changed.length)lines.push('两份定义不同：'+d.changed.join('、'));
        card(root,labels[key],lines.join('；'));
      }
      for(let i=0;i<A.scenarios.length;i++){
        const ar=A.scenarios[i],br=B.scenarios[i];
        if(ar.status==='unchanged'&&br.status==='unchanged')continue;
        card(root,ar.id+' · '+ar.title,`方案 A：${ar.message} 方案 B：${br.message}`);
      }
      root.append(el('p',data.interpretation,'design-review-warn'));
    }catch(e){root.textContent='对比未完成：'+e.message}
  }
  document.addEventListener('DOMContentLoaded',()=>{
    if($('designReviewCompare'))$('designReviewCompare').onclick=compare;
  });
  window.axiomDesignReviewInspect=inspect;
  window.axiomDesignReviewRefresh=refresh;
})();
