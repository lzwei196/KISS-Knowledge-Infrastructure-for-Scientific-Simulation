/* Project investigation UI. The host owns reviewer evidence and repair eligibility. */
(function(global){
  "use strict";
  const ACTIVE=new Set(["queued","reviewing","drafting","authoring","verifying","applying"]);
  const escape=value=>String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const text=value=>typeof value==="string"?value:JSON.stringify(value,null,2);
  function create(options){
    const $=options.$,T=(en,zh)=>options.chinese()?zh:en;
    let sessionId=null,job=null,available=false,hostBusy=false,reason="",error="",notice="",pending=false,timer=null,sequence=0,loading=false;
    const issues=new Map();
    let bindingState="";
    const current=()=>options.session()?.id||null;
    const opened=()=>$("#investigationpanel").classList.contains("open");
    const visible=()=>opened()&&!global.document?.hidden;
    const currentBinding=()=>JSON.stringify([!!options.ready(),options.binding()||{}]);
    const busy=()=>!!(sessionId&&options.busy(sessionId));
    const statusName=value=>({queued:T("Queued","已排队"),reviewing:T("Reviewing","正在审查"),reviewed:T("Reviews complete","审查完成"),partial:T("Partial report","部分报告"),cancelled:T("Cancelled","已取消"),drafting:T("Creating draft","正在创建草稿"),draft:T("Repair draft","修复草稿"),authoring:T("Building repair","正在编写修复"),verifying:T("Verifying with KDT","正在用 KDT 验证"),verified:T("Structurally verified","结构验证通过"),applying:T("Applying verified repair","正在应用已验证的修复"),applied:T("Repair applied","已应用修复"),stale:T("Context changed","上下文已变化"),failed:T("Failed","失败"),completed:T("Completed","已完成"),unsupported:T("Unavailable","不可用"),pending:T("Pending","待处理"),running:T("Running","运行中")}[value]||value||T("Pending","待处理"));
    function stopPoll(){if(timer!==null)global.clearTimeout(timer);timer=null;}
    function schedule(){
      stopPoll();
      if(visible()&&sessionId&&current()===sessionId&&(hostBusy||job&&ACTIVE.has(job.status))&&!pending&&!loading)
        timer=global.setTimeout(()=>{timer=null;refresh();},2000);
    }
    function reportHTML(value){
      if(!value||typeof value!=="object"||Array.isArray(value))return `<pre class="investigation-report-text">${escape(text(value))}</pre>`;
      const findings=Array.isArray(value.findings)?value.findings:[];
      const list=(title,items)=>Array.isArray(items)&&items.length?`<h4>${escape(title)}</h4><ul>${items.map(item=>`<li>${escape(text(item))}</li>`).join("")}</ul>`:"";
      let html=value.summary?`<p>${escape(text(value.summary))}</p>`:"";
      html+=findings.map(f=>typeof f==="object"&&f!==null?`<article class="investigation-finding"><b>${escape(f.claim||f.summary||f.title||T("Finding","发现"))}</b><small class="investigation-meta">${escape([f.category,f.severity,f.reviewer||f.role].filter(Boolean).join(" · "))}</small>${f.recommendation?`<p>${escape(text(f.recommendation))}</p>`:""}${list(T("Evidence","证据"),f.evidence)}</article>`:`<p>${escape(text(f))}</p>`).join("");
      html+=list(T("Uncertainties","尚不确定的事项"),value.uncertainties)+list(T("Tests not run","尚未运行的测试"),value.tests_not_run);
      return html?html+`<details><summary>${escape(T("Full report record","完整报告记录"))}</summary><pre class="investigation-report-text">${escape(text(value))}</pre></details>`:`<pre class="investigation-report-text">${escape(text(value))}</pre>`;
    }
    function render(){
      $("#investigation-label").textContent=T("Investigate KI","排查 KI");
      $("#openinvestigation").title=T("Review KI issues with three independent agents","让三位独立 Agent 排查 KI 问题");
      $("#investigation-close").setAttribute("aria-label",T("Close","关闭"));
      $("#investigation-title").textContent=T("KI investigation","KI 问题排查");
      $("#guide-investigation-title").textContent=T("Investigate and repair a KI","排查并修复 KI");
      $("#guide-investigation-steps").textContent=T("Open a project → Investigate KI → describe the issue → start three independent reviews. Read each report and its evidence, then create a repair draft, build it with the agent, and verify it with KDT.","打开项目 → 排查 KI → 描述问题 → 开始三方独立审查。阅读各份报告及其证据，再创建修复草稿、让 Agent 编写修复并用 KDT 验证。");
      $("#guide-investigation-limit").textContent=T("Apply repair and continue is an explicit choice. It returns to a fresh plan review and installation preflight. KDT checks package structure; a scientific pass still requires model-test evidence.","需要你明确点击“应用修复并继续”，随后重新审核计划并检查安装。KDT 检查包结构；科学验证通过仍需模型测试证据。");
      $("#guide-investigation-open").textContent=T("Open this project's investigation","打开此项目的 KI 排查");
      $("#guide-investigation-open").disabled=!sessionId;
      $("#investigation-intro").textContent=T("Three separate reviewers inspect the same frozen project context. Their reports guide a repair draft; model tests remain separate.","三位独立审查者检查同一份冻结的项目上下文。报告用于指导修复草稿；模型测试单独验证。");
      $("#investigation-issue-label").textContent=T("What should they investigate?","需要排查什么问题？");
      $("#investigation-issue").placeholder=T("Describe the failure or result that needs checking…","描述需要检查的故障或结果……");
      $("#investigation-ki-label").textContent=T("KI to repair","要修复的 KI");
      const labels={start:T("Start 3 independent reviews","开始三方独立审查"),cancel:T("Cancel investigation","取消排查"),draft:T("Create repair draft","创建修复草稿"),build:T("Build repair with agent","让 Agent 编写修复"),verify:T("Verify with KDT","用 KDT 验证"),apply:T("Apply repair and continue","应用修复并继续"),refresh:T("Refresh","刷新")};
      for(const [key,label] of Object.entries(labels))$("#investigation-"+key).textContent=label;
      const binding=options.binding()||{};
      $("#investigation-binding").textContent=sessionId?T("Three independent conversations using ","三个独立对话使用 ")+(job?.provider||binding.provider||T("an AI connection is required","请先连接 AI"))+(job?.llm_model||binding.llm_model?" · "+(job?.llm_model||binding.llm_model):""):T("Open a project to investigate its KI.","打开项目后即可排查 KI。");
      const active=!!(job&&ACTIVE.has(job.status)),locked=pending||hostBusy||busy();
      $("#investigation-start").disabled=!sessionId||loading||locked||active||!available||!options.ready();
      $("#investigation-issue").disabled=pending||active;
      $("#investigation-cancel").hidden=!active||job?.status==="applying";
      $("#investigation-cancel").disabled=pending;
      const names=Array.isArray(job?.selected_kis)?job.selected_kis:[];
      const select=$("#investigation-ki"),chosen=select.value;
      select.innerHTML=names.map(name=>`<option value="${escape(name)}">${escape(name)}</option>`).join("");
      select.value=names.includes(chosen)?chosen:(job?.repair?.ki_name||names[0]||"");
      $("#investigation-ki-row").hidden=job?.status!=="reviewed";
      select.disabled=locked||names.length<2;
      const repair=job?.repair||{},draftable=job?.status==="reviewed"&&names.length>0;
      const repairStatus=repair.status||job?.status;
      const repairReady=!!repair.kdt_job_id&&(["draft","verified"].includes(repairStatus)||(repairStatus==="failed"&&repair.retryable===true));
      const canVerify=!!repair.kdt_job_id&&repair.can_verify===true;
      $("#investigation-draft").hidden=!draftable;
      $("#investigation-draft").disabled=locked||!available;
      $("#investigation-build").hidden=!repairReady;
      $("#investigation-build").disabled=locked||active||!options.ready();
      $("#investigation-verify").hidden=!canVerify;
      $("#investigation-verify").disabled=!canVerify||locked||active;
      $("#investigation-apply").hidden=!repair.kdt_job_id;
      $("#investigation-apply").disabled=locked||active||repair.can_apply!==true||!repair.verification_id;
      $("#investigation-refresh").disabled=loading||pending||!sessionId;
      const message=error||notice||(busy()?T("This project is working. Stop or finish its current turn before changing it.","此项目正在工作。请停止或完成当前回合后再进行更改。"):reason||(!options.ready()?T("Connect this project's AI before starting an investigation.","请先连接此项目的 AI，再开始排查。"):""));
      $("#investigation-message").textContent=message||"";
      $("#investigation-message").className=error?"hint investigation-error":"hint";
      if(!job){$("#investigation-report").innerHTML=`<p class="hint">${escape(loading?T("Reading saved investigation…","正在读取已保存的排查……"):T("No investigation saved for this project yet.","此项目尚无排查记录。"))}</p>`;return;}
      const reviewers=Array.isArray(job.reviewers)?job.reviewers:[];
      const done=reviewers.filter(r=>r.status==="completed").length;
      const roles={contract_runtime:T("KI and runtime contract","KI 与运行环境要求"),data_science:T("Data and scientific checks","数据与科学检查"),reproducibility_risks:T("Reproducibility and risks","可复现性与风险")};
      const reportNode=$("#investigation-report");
      const expanded=new Set(Array.from(reportNode.querySelectorAll?.("details[open][data-report-key]")||[],node=>node.dataset.reportKey));
      const block=(title,value,key)=>value?`<details class="investigation-details" data-report-key="${escape(key)}"${expanded.has(key)?" open":""}><summary>${escape(title)}</summary>${key==="coverage"?`<pre>${escape(text(value))}</pre>`:reportHTML(value)}</details>`:"";
      const changes=repair.verification?.changes;
      const changedFiles=changes&&typeof changes==="object"?`<details class="investigation-details" data-report-key="changes"${expanded.has("changes")?" open":""}><summary>${escape(T("Changed files","变更文件"))}</summary>${changes.candidate_digest?`<p class="investigation-meta">${escape(T("Candidate digest","候选版本摘要"))}: ${escape(changes.candidate_digest)}</p>`:""}${changes.truncated?`<p class="hint">${escape(T("File lists are shortened; category counts show the totals.","文件列表已截短；各类数量显示总数。"))}</p>`:""}${changes.complete===false?`<p class="investigation-error">${escape(T("The file comparison is incomplete. Review the unexamined paths before applying.","文件比较不完整。应用前请检查未比较的路径。"))}</p>`:""}${[["added",T("Added","新增")],["modified",T("Modified","修改")],["removed",T("Removed","删除")]].map(([key,label])=>{const files=Array.isArray(changes[key])?changes[key]:[],count=Number.isInteger(changes.counts?.[key])?changes.counts[key]:files.length;return `<h4>${escape(label)} (${count})</h4>${files.length?`<ul>${files.map(path=>`<li><code>${escape(text(path))}</code></li>`).join("")}</ul>`:""}`;}).join("")}${[["uncompared_baseline_paths",T("Uncompared baseline paths","未比较的基线路径")],["uncompared_candidate_paths",T("Uncompared draft paths","未比较的草稿路径")]].map(([key,label])=>Array.isArray(changes[key])&&changes[key].length?`<h4>${escape(label)}</h4><ul>${changes[key].map(path=>`<li><code>${escape(text(path))}</code></li>`).join("")}</ul>`:"").join("")}</details>`:"";
      const authorSummary=block(T("Repair agent summary","修复 Agent 总结"),repair.author_report,"author")+(repair.author_report&&repair.author_report_meta?.truncated?`<p class="hint">${escape(T("The repair agent summary was shortened.","修复 Agent 总结已截短。"))}</p>`:"");
      $("#investigation-report").innerHTML=`<section class="datacard"><b>${escape(statusName(job.status))}</b><small class="investigation-meta">${escape(job.id)} · ${done}/3 ${escape(T("reviewers completed","位审查者完成"))}</small>${job.issue?`<p>${escape(job.issue)}</p>`:""}${job.context_digest?`<small class="investigation-meta">${escape(T("Frozen context","冻结上下文"))}: ${escape(job.context_digest)}</small>`:""}${block(T("Context coverage and exclusions","上下文覆盖与排除项"),job.coverage,"coverage")}${job.error?`<p class="investigation-error">${escape(job.error)}</p>`:""}</section>`+
        reviewers.map(r=>`<section class="datacard"><b>${escape(roles[r.id]||r.label||r.id)}</b><span class="investigation-meta">${escape(statusName(r.status))}</span>${r.summary?`<p>${escape(r.summary)}</p>`:""}${r.error?`<p class="investigation-error">${escape(r.error)}</p>`:""}${block(T("Read independent report","阅读独立报告"),r.report,r.id)}</section>`).join("")+
        (job.report?`<section class="datacard"><h3>${escape(T("Combined report","综合报告"))}</h3>${reportHTML(job.report)}</section>`:"")+
        (repair.kdt_job_id?`<section class="datacard"><h3>${escape(T("KDT repair draft","KDT 修复草稿"))}</h3><p>${escape(repair.ki_name)} · ${escape(statusName(repair.status))}</p>${repair.candidate_path?`<p class="investigation-meta">${escape(T("Repair draft folder","修复草稿目录"))}: <code>${escape(repair.candidate_path)}</code></p>`:""}${authorSummary}<p class="hint">${escape(T("KDT verification checks package structure. Native and scientific tests require their own evidence. Continuing returns to the project's normal plan review.","KDT 验证检查包结构。原生模型与科学测试需要各自的证据。继续后将进入项目正常的计划审核流程。"))}</p>${repair.blocked_reason?`<p class="investigation-error">${escape(repair.blocked_reason)}</p>`:""}${changedFiles}${block(T("KDT verification report","KDT 验证报告"),repair.verification,"verification")}<small class="investigation-meta">${escape(repair.kdt_job_id)}${repair.verification_id?" · "+escape(repair.verification_id):""}</small></section>`:"");
    }
    function sync(){
      const id=current(),binding=currentBinding(),bindingChanged=binding!==bindingState;
      bindingState=binding;
      if(id!==sessionId){
        if(sessionId)issues.set(sessionId,$("#investigation-issue").value);
        stopPoll();sequence++;sessionId=id;job=null;available=false;hostBusy=false;reason="";error="";notice="";pending=false;loading=false;
        $("#investigation-issue").value=issues.get(id)||"";
        if(visible()&&id){refresh();return;}
      }
      if(bindingChanged&&visible()&&id&&!loading&&!pending){refresh();return;}
      render();
      if(timer===null)schedule();
    }
    async function readJSON(url,init){
      const response=await global.fetch(url,init),data=await response.json().catch(()=>({}));
      if(!response.ok)throw new Error(data.error||T("Request failed","请求失败")+` (${response.status})`);
      return data;
    }
    async function refresh(){
      stopPoll();
      const id=current();if(!id||pending)return;
      if(id!==sessionId){sync();return;}
      const token=++sequence;loading=true;render();
      try{
        const data=await readJSON(`/api/session/${encodeURIComponent(id)}/investigation`,{cache:"no-store"});
        if(id!==current()||token!==sequence)return;
        job=data.job||null;available=data.available===true;hostBusy=data.busy===true;reason=data.reason||"";error="";
      }catch(e){if(id===current()&&token===sequence)error=e.message||String(e);}
      finally{if(id===current()&&token===sequence){loading=false;render();schedule();}}
    }
    async function mutate(action){
      const id=current(),captured=job;
      if(!id||id!==sessionId||pending)return;
      if(action!=="cancel"&&(hostBusy||busy()))return;
      const button=$("#investigation-"+action);if(button.disabled||button.hidden)return;
      let payload={},suffix;
      if(action==="start"){
        const issue=$("#investigation-issue").value.trim();
        if(!issue){error=T("Describe the issue before starting the reviews.","请先描述问题，再开始审查。");render();return;}
        payload={issue,...options.binding()};suffix="/start";issues.set(id,issue);
      }else{
        if(!captured?.id)return;
        suffix=`/${encodeURIComponent(captured.id)}/${action}`;
        if(action==="draft")payload={ki_name:$("#investigation-ki").value};
        if(action==="apply"){
          if(captured.repair?.can_apply!==true||!captured.repair.verification_id)return;
          payload={verification_id:captured.repair.verification_id};
        }
      }
      const token=++sequence;stopPoll();pending=true;error="";notice="";render();
      try{
        const data=await readJSON(`/api/session/${encodeURIComponent(id)}/investigation${suffix}`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
        if(id!==current()||token!==sequence)return;
        job=data.job||job;
        if(typeof data.busy==="boolean")hostBusy=data.busy;
        if(typeof data.available==="boolean")available=data.available;
        if(data.reason!==undefined)reason=data.reason;
        if(action==="apply"){
          notice=T("Repair applied. Continuing through the project's normal review flow.","修复已应用。正在通过项目正常的审核流程继续。");render();
          if(data.resume_message)await options.resume(id,String(data.resume_message));
          else notice=T("Repair applied. Continue in chat to review the next step.","修复已应用。请在对话中继续并审核下一步。");
        }
      }catch(e){if(id===current()&&token===sequence)error=(action==="apply"&&job?.status==="applied"?T("Repair applied; continuation needs attention: ","修复已应用；继续操作需要处理： "):"")+(e.message||String(e));}
      finally{if(id===current()&&token===sequence){pending=false;render();schedule();}}
    }
    function showPanel(show){
      const panel=$("#investigationpanel");
      panel.classList[show?"add":"remove"]("open");panel.inert=!show;
      panel.setAttribute("aria-hidden",show?"false":"true");
      $("#openinvestigation").setAttribute("aria-expanded",show?"true":"false");
    }
    function open(){options.beforeOpen?.();showPanel(true);sync();if(!loading)refresh();}
    function close(){stopPoll();showPanel(false);}
    $("#openinvestigation").onclick=open;
    $("#investigation-close").onclick=close;
    $("#investigation-refresh").onclick=refresh;
    $("#guide-investigation-open").onclick=()=>{if(!current())return;$("#guide").classList.remove("open");open();};
    for(const action of ["start","cancel","draft","build","verify","apply"])$("#investigation-"+action).onclick=()=>mutate(action);
    $("#investigation-issue").addEventListener("input",()=>{if(sessionId)issues.set(sessionId,$("#investigation-issue").value);});
    global.addEventListener("geoforge:language",render);
    const reconcile=()=>{if(visible()&&!pending&&!loading)refresh();else if(!visible())stopPoll();};
    global.addEventListener("focus",reconcile);
    global.document?.addEventListener("visibilitychange",reconcile);
    showPanel(false);
    sync();
    return {open,close,sync,refresh};
  }
  global.GeoForgeInvestigation={create};
})(window);
