'use strict';
// Axiom Studio 1.1. A usable, intent-first projection of the existing protected
// workflow. Human approval remains explicit and checks remain server-authoritative.
(function(){
  const $=id=>document.getElementById(id);
  const stepData=[
    ['01','说出目标','明确你想得到什么，什么结果才算成功。','你做决定','目标陈述','自然语言目标先作为意图保存，不会假装 AI 已把它证明。'],
    ['02','明确规则','把关键行为和边界写成能被检查的规则。','人与工具共同','行为规格','这一阶段先检查规则自身；只有被规则覆盖的内容才能获得对应证据。'],
    ['03','生成方案','把规则交给 AI 或现有开发工具，得到实现候选。','AI / VS Code','可审查的候选','AI 可以提出多种方案，不能悄悄改变需求与验收规则。'],
    ['04','独立验证','将候选交给独立模型检查、编译与测试工具。','独立工具','验证报告与失败证据','生成结果不能自己证明自己；运行本地 C++ 前仍需人工确认可信。'],
    ['05','决定与演化','看证据、作出裁决；需求变化后重查受影响部分。','你来裁决','测试级结论 / 新版本','当前实现不签发生产发布许可；证据随规格与代码版本绑定。'],
  ];
  const examples={
    'model-toggle':['我的状态机演示','验证开关切换后始终处于允许的状态。'],
    'model-ledger':['我的账户规则实验','两个账户之间转移金额，任何时候余额总量保持不变。'],
    'cpp-ledger':['我的交易处理软件','两个账户转账需要保持余额守恒，功能实现要经过独立测试。']
  };
  let latest=null, selectedPhase=0, freezeProject=null, freezeDraft=null;
  function el(tag,text,cls){const x=document.createElement(tag);if(text!==undefined)x.textContent=String(text);if(cls)x.className=cls;return x}
  function msg(s){const n=$('journeyError');if(n)n.textContent=s||''}
  async function query(path,method='GET',body){
    if(typeof wfApi!=='function')throw Error('工作流接口未就绪');
    return wfApi(path,method,body);
  }
  function renderParadigm(){
    const root=$('journeyParadigm');if(!root)return;root.replaceChildren();
    stepData.forEach((p,i)=>{
      const b=el('button',undefined,'journey-phase'+(selectedPhase===i?' active':''));b.type='button';
      b.setAttribute('aria-pressed',selectedPhase===i?'true':'false');
      b.append(el('span',p[0],'journey-phase-no'),el('strong',p[1]),el('span',i===stepData.length-1?'✓':'→','journey-phase-arrow'));
      b.addEventListener('click',()=>{selectedPhase=i;renderParadigm();renderExplanation()});root.append(b);
    });renderExplanation();
  }
  function renderExplanation(){
    const n=$('journeyExplain');if(!n)return;
    const p=stepData[selectedPhase];n.replaceChildren();
    const main=el('div');main.append(el('b',p[2]),el('p',p[5]));
    const other=el('div',undefined,'journey-explain-meta');other.append(el('span','责任：'+p[3]),el('span','产出：'+p[4]));
    n.append(main,other);
  }
  function badgeFor(row){
    if(row.stale||row.state==='unknown')return ['需要处理','needs-help'];
    if(row.tested_only)return ['已有测试级裁决','tested'];
    if(row.model_checked)return ['规则已经检查','progress'];
    return ['从这里开始','fresh'];
  }
  async function continueProject(row){
    try{
      // Navigate to actual workflow, never invent a bypass for approval or Gate.
      if(typeof selectProject!=='function')throw Error('项目工作台不可用');
      await selectProject(row.id);
      if(row.next.id==='freeze'){
        await openReview(row.id);return;
      }
      if(row.next.id==='verify'){
        if(typeof wfAction==='function')await wfAction('verify');
        await refresh();return;
      }
      if(row.next.id==='task'){
        if(typeof wfAction==='function')await wfAction('task');return;
      }
      if(row.next.id==='fork'){
        if(typeof wfAction==='function')await wfAction('fork');await refresh();return;
      }
      if(row.next.id==='candidate' && typeof wfAction==='function'){
        await wfAction('candidate');return;
      }
      $('journeyAdvanced').open=true;
      $('projectDetail')?.scrollIntoView({behavior:'smooth',block:'start'});
      if(row.next.id==='batch')typeof wfNotify==='function'&&wfNotify('已打开构造任务。下方可选择多文件方案，或使用 AI 生产工单。');
    }catch(e){const s='无法继续：'+e.message;msg(s);if(typeof wfNotify==='function')wfNotify(s)}
  }
  async function refresh(){
    const root=$('journeyProjects');if(!root)return;
    try{
      const data=await query('/api/journey');latest=data;root.replaceChildren();
      if(data.errors?.length){root.append(el('div','部分项目无法核验，请进入详细记录处理；未知状态不会被视为通过。','journey-alert'))}
      if(!data.projects.length){
        const empty=el('div',undefined,'journey-empty');empty.append(el('strong','还没有软件项目'),el('p','填写上方目标并选择一个起点，系统就会创建独立的项目与下一步任务。'));
        root.append(empty);return;
      }
      data.projects.forEach(row=>{
        const c=el('article',undefined,'journey-project');
        const head=el('div',undefined,'journey-project-heading');const left=el('div');
        left.append(el('small','软件目标'),el('h4',row.name));
        const [status,color]=badgeFor(row);head.append(left,el('span',status,'journey-tag '+color));
        c.append(head,el('p',row.goal||'未设置目标','journey-project-goal'));
        const steps=el('div',undefined,'journey-project-steps');
        // Stable visible result from the six-stage core mapped to user-friendly names.
        row.steps.forEach((st,i)=>{
          const b=el('span',(st.state==='passed'?'✓ ':st.state==='blocked'?'! ':st.state==='recorded'?'✓ ':'○ ')+['目标','规则','验收','构造','验证','决策'][i], 'journey-mini-step '+st.state);
          b.title=st.why;steps.append(b);
        });c.append(steps);
        const next=el('div',undefined,'journey-next');next.append(el('small','下一步建议'),el('b',row.next.label),el('p',row.next.explanation));
        const action=el('button',row.next.id==='inspect'?'查看项目情况':'继续：'+row.next.label,'journey-next-button');
        action.type='button';action.addEventListener('click',()=>continueProject(row));
        next.append(action);c.append(next);
        if(row.stale)c.append(el('div','已检测到文件变更：旧版的验证结论不能直接沿用。','journey-alert'));
        root.append(c);
      });
    }catch(e){root.textContent='项目状态暂时不可用：'+e.message+'。请检查本地服务。'}
  }
  function reviewClose(){ $('journeyReviewOverlay').classList.add('hidden');freezeProject=null;freezeDraft=null; }
  function scenarioRow(item){
    const c=el('div',undefined,'journey-review-item intent-scenario');c.dataset.id=item.id;
    const h=el('div',undefined,'intent-head');h.append(el('strong',item.id+' · 验收场景'));
    const remove=el('button','移除此项','tool secondary intent-remove');remove.type='button';
    remove.addEventListener('click',()=>{c.remove();reviewCoverage()});h.append(remove);c.append(h);
    function field(label,value,kind='input'){
      const wrap=el('label',undefined,'intent-field');wrap.append(el('span',label));
      const input=el(kind);input.value=value||'';input.maxLength=kind==='textarea'?500:300;
      input.required=true;input.setAttribute('aria-label',item.id+' '+label);
      input.dataset.field=({ '这项行为叫什么':'title','在什么情况下':'given','发生什么动作':'when','必须得到什么结果':'then' })[label];
      input.addEventListener('input',reviewCoverage);wrap.append(input);c.append(wrap);
    }
    field('这项行为叫什么',item.title);
    field('在什么情况下',item.given);
    field('发生什么动作',item.when);
    field('必须得到什么结果',item.then,'textarea');
    const label=el('label',undefined,'intent-field');label.append(el('span','用哪条行为规则检查？'));
    const select=el('select');select.dataset.field='property';
    const blank=el('option','暂无对应规则——需要补充规格');blank.value='';select.append(blank);
    (freezeDraft?.properties||[]).forEach(property=>{const opt=el('option',property);opt.value=property;select.append(opt)});
    select.value=item.property||'';select.addEventListener('change',reviewCoverage);label.append(select);c.append(label);
    return c;
  }
  function reviewValues(){
    return [...$('journeyReviewItems').querySelectorAll('.intent-scenario')].map(card=>{
      const row={id:card.dataset.id};
      card.querySelectorAll('[data-field]').forEach(n=>{row[n.dataset.field]=n.value.trim()});
      return row;
    });
  }
  function reviewCoverage(){
    const items=reviewValues(),gaps=items.filter(x=>!x.property).length;
    $('journeyCoverage').textContent=items.length+' 项验收场景 · '+(items.length-gaps)+' 项已关联规格性质 · '+gaps+' 项需要补充规则';
    $('journeyGapWarning').textContent=gaps?'存在 '+gaps+' 项尚未对应可验证规则，冻结后仍会阻断测试级准入。可先将缺口交给 AI 或 VS Code 辅助设计规格。':'关联关系仍需人工判断是否准确；模型检查并不证明文字目标已被完整覆盖。';
    $('journeyReviewSubmit').disabled=!$('journeyReviewChecked').checked||!items.length;
  }
  function populateReview(){
    const list=$('journeyReviewItems');list.replaceChildren();
    freezeDraft.items.forEach(x=>list.append(scenarioRow(x)));
    $('journeyReviewChecked').checked=false;
    $('journeyDesignText').classList.add('hidden');
    $('journeyReviewError').textContent='';reviewCoverage();
  }
  async function openReview(id){
    const draft=await query('/api/intent/plan?id='+encodeURIComponent(id));
    if(draft.stale||draft.frozen)throw Error('当前版本已冻结或发生变化。请创建新的演化版本。');
    freezeProject=id;freezeDraft=draft;populateReview();
    $('journeyReviewGoal').textContent=draft.goal;
    $('journeyReviewOverlay').classList.remove('hidden');
  }
  async function saveReview(){
    if(!freezeProject||!freezeDraft)throw Error('请重新打开验收场景');
    const rows=reviewValues();if(!rows.length)throw Error('至少需要一个验收场景');
    const saved=await query('/api/intent/save','POST',{
      id:freezeProject,items:rows,version:freezeDraft.version,baseline:freezeDraft.baseline});
    freezeDraft=saved;return saved;
  }
  async function reviewSave(){
    const b=$('journeyReviewSave');b.disabled=true;
    try{await saveReview();$('journeyReviewError').textContent='场景已经保存，可继续编辑，或由你人工确认并冻结。';}
    catch(e){$('journeyReviewError').textContent='保存失败：'+e.message}
    finally{b.disabled=false}
  }
  async function reviewDesign(){
    const b=$('journeyReviewDesign');b.disabled=true;
    try{
      await saveReview();const packet=await query('/api/intent/task?id='+encodeURIComponent(freezeProject));
      const area=$('journeyDesignText');area.value=packet.prompt;area.classList.remove('hidden');
      area.focus();area.select();
      $('journeyReviewError').textContent='已形成规格设计任务，包含 '+packet.gaps+' 个缺口。可以复制给 AI/VS Code；不会修改任何工程文件。';
    }catch(e){$('journeyReviewError').textContent='无法生成任务：'+e.message}
    finally{b.disabled=false}
  }
  async function reviewSubmit(){
    const button=$('journeyReviewSubmit');button.disabled=true;
    try{
      if(!freezeProject||!freezeDraft||!$('journeyReviewChecked').checked)throw Error('请先核对每项场景并确认。');
      const saved=await saveReview();
      const result=await query('/api/intent/confirm','POST',{
        id:freezeProject,version:saved.version,digest:saved.digest,
        confirmation:'CONFIRM_HUMAN_ACCEPTANCE'});
      const id=freezeProject;reviewClose();
      if(typeof selectProject==='function')await selectProject(id);
      await refresh();
      if(typeof window.AxiomFlowOpen==='function')await window.AxiomFlowOpen(id);
      if(typeof wfNotify==='function')wfNotify(result.unmapped?'验收规则已冻结，但仍有 '+result.unmapped+' 项没有验证规则，准入将受阻。':'验收场景已冻结；继续构造候选并进行独立验证。');
    }catch(e){$('journeyReviewError').textContent='无法冻结：'+e.message}
    finally{button.disabled=false}
  }
  function reviewAdd(){
    const ids=new Set(reviewValues().map(x=>x.id));let n=1;
    while(ids.has('REQ-'+String(n).padStart(3,'0')))n++;
    if(n>40){$('journeyReviewError').textContent='验收场景最多 40 项';return}
    const item={id:'REQ-'+String(n).padStart(3,'0'),title:'新增业务行为',given:'满足指定前提条件',when:'发生用户操作或系统事件',then:'应当出现明确可检查的结果',property:''};
    $('journeyReviewItems').append(scenarioRow(item));reviewCoverage();
    $('journeyReviewItems').lastElementChild.scrollIntoView({block:'nearest',behavior:'smooth'});
  }
  async function create(e){
    e.preventDefault();const b=$('journeyCreate');b.disabled=true;msg('');
    try{
      const scenario=$('journeyScenario').value,name=$('journeyName').value.trim(),goal=$('journeyGoal').value.trim();
      if(name.length<2||goal.length<4)throw Error('请写下项目名称和至少一句清楚的软件目标。');
      const x=await query('/api/journey/start','POST',{scenario,name,goal});
      await refresh();if(typeof loadProjects==='function')await loadProjects();
      if(typeof window.AxiomPilotOpen==='function')await window.AxiomPilotOpen(x.project.id);
      if(typeof selectProject==='function')await selectProject(x.project.id);
      if(typeof wfNotify==='function')wfNotify('已创建项目。当前先验证模板的行为规则，确认后才能作为正式验收依据。');
      if(typeof window.AxiomFlowOpen==='function')await window.AxiomFlowOpen(x.project.id);else ($('pilotHome')||$('journeyProjects')).scrollIntoView({behavior:'smooth',block:'start'});
    }catch(error){msg(error.message)}finally{b.disabled=false}
  }
  document.addEventListener('DOMContentLoaded',()=>{
    if(!$('journeyStartForm'))return;
    renderParadigm();refresh();
    $('journeyStartForm').addEventListener('submit',create);
    $('journeyFillExample').addEventListener('click',()=>{
      const v=examples[$('journeyScenario').value];$('journeyName').value=v[0];$('journeyGoal').value=v[1];msg('');
    });
    $('journeyScenario').addEventListener('change',()=>{ $('journeyExample').textContent='所选案例只验证示例规则，不代表已涵盖你描述的全部软件目标。';});
    $('journeyExisting').addEventListener('click',()=>{typeof wfCreateOpen==='function'&&wfCreateOpen()});
    $('journeySideStart')?.addEventListener('click',()=>{$('projectDashboard').scrollTo({top:0,behavior:'smooth'});$('journeyGoal').focus()});
    $('journeyRefresh').addEventListener('click',refresh);
    $('journeyReviewClose').addEventListener('click',reviewClose);
    $('journeyReviewCancel').addEventListener('click',reviewClose);
    $('journeyReviewChecked').addEventListener('change',reviewCoverage);
    $('journeyReviewAdd').addEventListener('click',reviewAdd);
    $('journeyReviewSave').addEventListener('click',reviewSave);
    $('journeyReviewDesign').addEventListener('click',reviewDesign);
    $('journeySpecWorkshopOpen').addEventListener('click',async()=>{try{await saveReview();window.axiomOpenSpecWorkshop(freezeProject);reviewClose()}catch(e){$('journeyReviewError').textContent=e.message}});
    $('journeyReviewSubmit').addEventListener('click',reviewSubmit);
  });
  window.axiomJourneyRefresh=refresh;
  window.axiomJourneyOpenReview=openReview;
})();
