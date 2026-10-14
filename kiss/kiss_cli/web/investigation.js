/* Project investigation UI. The host owns reviewer evidence and repair eligibility. */
(function(global){
  "use strict";
  const ACTIVE=new Set(["queued","reviewing","drafting","authoring","verifying","applying"]);
  const escape=value=>String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const text=value=>typeof value==="string"?value:JSON.stringify(value,null,2);
  function create(options){
    const $=options.$,T=(en,zh)=>options.chinese()?zh:en;
    let sessionId=null,job=null,available=false,hostBusy=false,reason="",error="",notice="",pending=false,timer=null,sequence=0,loading=false,rejectedSources=[];
    const issues=new Map(),authorNotes=new Map();
    let bindingState="";
    const current=()=>options.session()?.id||null;
    const opened=()=>$("#investigationpanel").classList.contains("open");
    const visible=()=>opened()&&!global.document?.hidden;
    const currentBinding=()=>JSON.stringify([!!options.ready(),options.binding()||{}]);
    const busy=()=>!!(sessionId&&options.busy(sessionId));
    const recipeName=value=>({tool_inventory:T("Tool inventory","工具清单"),preflight_reporting:T("Preflight reporting","预检报告"),package_contract:T("Tool inventory + preflight reporting","工具清单 + 预检报告"),wofost_parameter_routing:T("WOFOST soil/site parameter routing","WOFOST 土壤与站点参数传递"),wofost_runtime_paths:T("WOFOST runtime paths","WOFOST 运行环境路径")}[value]||value);
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
      $("#investigation-source-label").textContent=T("KI source to investigate","要排查的 KI 来源");
      const sourceSelect=$("#investigation-source"),sourceValue=sourceSelect.value;
      sourceSelect.innerHTML=`<option value="">${escape(T("Current project","当前项目"))}</option>`+rejectedSources.map(row=>`<option value="${escape(row.id)}">${escape(T("Rejected update","被拒绝的更新"))} · ${escape(row.name)} · ${escape(String(row.source_commit).slice(0,12))}</option>`).join("");
      sourceSelect.value=rejectedSources.some(row=>row.id===sourceValue)?sourceValue:"";
      $("#investigation-source-help").textContent=sourceSelect.value?T("Review this exact inactive update package. A verified maintenance draft can be inspected, but cannot be applied to the project or library from this workflow.","审查此未启用更新包的确切版本。维护草稿验证后可查看，但此流程不能将其应用到项目或 KI 库。"):T("Investigate the project's current KI. Rejected update sources are offered for this chat's selected KIs when their signed source evidence is intact.","排查项目当前使用的 KI。当签名来源证据完好时，也可选择本对话已选 KI 的被拒绝更新版本。");
      $("#investigation-mode-label").textContent=T("Repair workflow","修复流程");
      $("#investigation-recipe-label").textContent=T("Maintenance recipe","维护修复方案");
      const names=Array.isArray(job?.selected_kis)?job.selected_kis:[];
      const select=$("#investigation-ki"),chosen=select.value;
      select.innerHTML=names.map(name=>`<option value="${escape(name)}">${escape(name)}</option>`).join("");
      select.value=names.includes(chosen)?chosen:(job?.repair?.ki_name||names[0]||"");
      const mode=$("#investigation-mode"),selectedMode=mode.value||"authoring";
      mode.innerHTML=`<option value="authoring">${escape(T("Full authoring","完整创作验证"))}</option><option value="maintenance">${escape(T("Maintenance — reuse unchanged evidence","维护修复 — 复用未变更的证据"))}</option>`;
      mode.value=["authoring","maintenance"].includes(selectedMode)?selectedMode:"authoring";
      const rejectedJob=!!job?.maintenance_sources&&Object.keys(job.maintenance_sources).length>0;
      if(rejectedJob)mode.value="maintenance";
      const recipe=$("#investigation-recipe"),selectedRecipe=recipe.value||"tool_inventory";
      const recipes=["tool_inventory","preflight_reporting","package_contract"];
      if(!rejectedJob&&select.value==="WOFOST")recipes.push("wofost_parameter_routing","wofost_runtime_paths");
      recipe.innerHTML=recipes.map(value=>`<option value="${value}">${escape(recipeName(value))}</option>`).join("");
      recipe.value=recipes.includes(selectedRecipe)?selectedRecipe:"tool_inventory";
      $("#investigation-mode-help").textContent=mode.value==="maintenance"?T("Create a bounded repair in KDT. Reuse valid unchanged published metadata, then rerun current KDT checks. Changes apply only to this project; scientific edits need full authoring.","在 KDT 中创建限定范围的修复。复用有效且未变更的已发布元数据，并重新运行当前 KDT 检查。仅应用于本项目；科学内容变更需完整创作验证。"):T("Full authoring requires the complete authoring evidence. Choose maintenance for a supported tool-inventory or preflight-report correction.","完整创作验证需要完整的创作证据。支持的工具清单或预检报告修正可选择维护修复。");
      if(rejectedJob)$("#investigation-mode-help").textContent=T("Reuse valid unchanged published metadata in a bounded KDT maintenance draft. Verify the draft without changing the project or active library. Scientific edits need full authoring.","在限定范围的 KDT 维护草稿中复用有效且未变更的已发布元数据。验证草稿，不修改项目或当前 KI 库。科学内容变更需完整创作验证。");
      if(mode.value==="maintenance"&&recipe.value==="wofost_parameter_routing")$("#investigation-mode-help").textContent=T("Repair only the supported WOFOST stage 6 runner's soil/site parameter routing. Supplied values and existing defaults stay unchanged. Current KDT checks and real PCSE parameter tests are required; stage 5 and scientific validation are outside this repair.","仅修复支持的 WOFOST 第 6 阶段运行器的土壤与站点参数传递。保留原有输入值与缺省值，必须通过当前 KDT 检查及真实 PCSE 参数测试；第 5 阶段与科学验证不在本次修复范围内。");
      if(mode.value==="maintenance"&&recipe.value==="wofost_runtime_paths")$("#investigation-mode-help").textContent=T("Bind supported WOFOST preflight paths to this project's recorded Python, shared helpers and shipped runner. Preserve every check and version requirement. Current KDT and path checks are required; a fresh preflight and model run are still needed after applying.","将支持的 WOFOST 预检路径绑定到本项目已记录的 Python、共享工具和随 KI 提供的运行器。保留所有检查及版本要求，必须通过当前 KDT 和路径检查；应用后仍须重新预检并运行模型。");
      const labels={start:T("Start 3 independent reviews","开始三方独立审查"),retry:T("Retry incomplete reviews","重试未完成的审查"),cancel:T("Cancel investigation","取消排查"),draft:T("Create repair draft","创建修复草稿"),build:T("Build repair with agent","让 Agent 编写修复"),verify:T("Verify with KDT","用 KDT 验证"),apply:T("Apply repair and continue","应用修复并继续"),refresh:T("Refresh","刷新")};
      for(const [key,label] of Object.entries(labels))$("#investigation-"+key).textContent=label;
      const binding=options.binding()||{};
      $("#investigation-binding").textContent=sessionId?T("Three independent conversations using ","三个独立对话使用 ")+(job?.provider||binding.provider||T("an AI connection is required","请先连接 AI"))+(job?.llm_model||binding.llm_model?" · "+(job?.llm_model||binding.llm_model):""):T("Open a project to investigate its KI.","打开项目后即可排查 KI。");
      const active=!!(job&&ACTIVE.has(job.status)),locked=pending||hostBusy||busy();
      $("#investigation-start").disabled=!sessionId||loading||locked||active||!available||!options.ready();
      $("#investigation-issue").disabled=pending||active;
      sourceSelect.disabled=pending||active||locked;
      $("#investigation-cancel").hidden=!active||job?.status==="applying";
      $("#investigation-cancel").disabled=pending;
      const retryable=job?.can_retry_review===true;
      $("#investigation-retry").hidden=!retryable;
      $("#investigation-retry").disabled=!retryable||loading||locked||active;
      $("#investigation-retry-help").hidden=!["partial","cancelled"].includes(job?.status);
      $("#investigation-retry-help").textContent=retryable?T("Retry only failed or cancelled reviews with the original AI connection. Completed reports are retained only if the project and frozen evidence are unchanged. All three reviews must finish before a repair draft.","使用原 AI 连接，仅重试失败或取消的审查。只有项目及冻结证据未变更时，才保留已完成报告。三方审查全部完成后才能创建修复草稿。"):(job?.retry_review_reason||"");
      $("#investigation-ki-row").hidden=job?.status!=="reviewed";
      select.disabled=locked||names.length<2;
      const repair=job?.repair||{},draftable=job?.status==="reviewed"&&names.length>0;
      $("#investigation-mode-row").hidden=!draftable;
      $("#investigation-recipe-row").hidden=!draftable||mode.value!=="maintenance";
      mode.disabled=locked||!draftable||rejectedJob;recipe.disabled=locked||!draftable;
      const repairStatus=repair.status||job?.status;
      const repairReady=!!repair.kdt_job_id&&(["draft","verified"].includes(repairStatus)||(repairStatus==="failed"&&repair.retryable===true));
      const canVerify=!!repair.kdt_job_id&&repair.can_verify===true;
      $("#investigation-draft").hidden=!draftable;
      $("#investigation-draft").disabled=locked||!available;
      $("#investigation-build").hidden=!repairReady;
      $("#investigation-build").disabled=locked||active||!options.ready();
      $("#investigation-author-row").hidden=!repairReady;
      $("#investigation-author-label").textContent=T("Repair instructions (optional)","修复说明（可选）");
      $("#investigation-author-help").textContent=T("Clarify the next repair within the reviewed scope. These instructions go to the repair agent only; the frozen reviews and KDT requirements stay unchanged.","在已审查的范围内补充下一次修复要求。仅发送给修复 Agent；冻结的审查报告与 KDT 要求保持不变。");
      $("#investigation-author-notes").disabled=locked||active;
      if(repair.repair_mode==="maintenance")$("#investigation-build").textContent=T("Audit repair with agent (optional)","让 Agent 审核修复（可选）");
      $("#investigation-verify").hidden=!canVerify;
      $("#investigation-verify").disabled=!canVerify||locked||active;
      $("#investigation-apply").hidden=!repair.kdt_job_id||repair.draft_only===true;
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
      const scope=repair.draft_only?"":repair.authoring_scope==="portable"?`<p class="hint">${escape(T("Portable repair: KDT checks the source and this project's resolved copy separately. After adoption, compatible new projects can reuse it with their own paths.","可复用修复：KDT 分别检查源包和本项目的路径转换版本。应用后，兼容的新项目可使用各自的路径复用此修复。"))}</p>`:`<p class="hint">${escape(T("Project-local repair: this copy's paths stay bound to this project.","仅修复当前项目：此副本的路径继续绑定到当前项目。"))}</p>`;
      const authorSummary=block(T("Repair agent summary","修复 Agent 总结"),repair.author_report,"author")+(repair.author_report&&repair.author_report_meta?.truncated?`<p class="hint">${escape(T("The repair agent summary was shortened.","修复 Agent 总结已截短。"))}</p>`:"");
      const routingScope=repair.maintenance_recipe==="wofost_parameter_routing"?`<p class="hint">${escape(T("Stage 6 parameter routing only. Supplied values and existing defaults are preserved. Real PCSE interface tests do not establish a reference-case run or scientific validation. Stage 5 is unchanged.","仅修复第 6 阶段参数传递，保留原有输入值与缺省值。真实 PCSE 接口测试不代表参考案例已运行或科学验证通过。第 5 阶段保持原样。"))}</p>`:"";
      const interfaceCheck=repair.verification?.report?.interface_regression;
      const interfaceSummary=interfaceCheck&&interfaceCheck.status!=="not_required"?`<p class="${interfaceCheck.ok===true?"hint":"investigation-error"}">${escape(T("PCSE parameter tests","PCSE 参数测试"))}: ${escape(interfaceCheck.ok===true?String(interfaceCheck.fixture_count)+T(" passed; no model run"," 项通过；未运行模型"):interfaceCheck.error||T("Failed; inspect the verification report","失败；请查看验证报告"))}</p>`:"";
      const pathCheck=repair.verification?.report?.path_binding_regression;
      const failedCheck=repair.failure_phase==="verification"?`<p class="investigation-error">${escape(T("Verification failed. Review the error, edit the draft or run verification again. The repair has not been applied.","验证失败。请查看错误、修改草稿或重新验证。修复尚未应用。"))}</p>`:"";
      const pathSummary=pathCheck&&pathCheck.status!=="not_required"?`<p class="${pathCheck.ok===true?"hint":"investigation-error"}">${escape(T("Runtime path checks","运行环境路径检查"))}: ${escape(pathCheck.ok===true?T("Passed; fresh preflight and model run still required","通过；仍须重新预检并运行模型"):pathCheck.error||T("Failed; inspect the verification report","失败；请查看验证报告"))}</p>`:"";
      const maintenance=repair.repair_mode==="maintenance"?`<p class="hint"><b>${escape(T("Maintenance repair","维护修复"))}</b> · ${escape(recipeName(repair.maintenance_recipe))}<br>${escape(T("Valid unchanged published metadata is reused. Current KDT checks still apply to the whole candidate. This does not verify full-text literature, native installation or scientific results.","复用有效且未变更的已发布元数据，仍对整个候选包执行当前 KDT 检查。这不代表论文全文、本机安装或科学结果已验证。"))}</p>`+block(T("Prepared maintenance change","已准备的维护变更"),repair.maintenance_projection,"maintenance"):"";
      const draftOnly=repair.draft_only?`<p class="hint"><b>${escape(T("Draft verification only — not applied","仅验证草稿 — 未应用"))}</b><br>${escape(T("The source is a rejected update package. This draft has not changed any project KI, active library or native readiness.","来源是被拒绝的更新包。此草稿未改变任何项目 KI、当前 KI 库或本机运行准备状态。"))}</p>`:"";
      $("#investigation-report").innerHTML=`<section class="datacard"><b>${escape(statusName(job.status))}</b><small class="investigation-meta">${escape(job.id)} · ${done}/3 ${escape(T("reviewers completed","位审查者完成"))}</small>${job.issue?`<p>${escape(job.issue)}</p>`:""}${job.context_digest?`<small class="investigation-meta">${escape(T("Frozen context","冻结上下文"))}: ${escape(job.context_digest)}</small>`:""}${block(T("Context coverage and exclusions","上下文覆盖与排除项"),job.coverage,"coverage")}${job.error?`<p class="investigation-error">${escape(job.error)}</p>`:""}</section>`+
        reviewers.map(r=>`<section class="datacard"><b>${escape(roles[r.id]||r.label||r.id)}</b><span class="investigation-meta">${escape(statusName(r.status))}</span>${r.summary?`<p>${escape(r.summary)}</p>`:""}${r.error?`<p class="investigation-error">${escape(r.error)}</p>`:""}${block(T("Read independent report","阅读独立报告"),r.report,r.id)}</section>`).join("")+
        (job.report?`<section class="datacard"><h3>${escape(T("Combined report","综合报告"))}</h3>${reportHTML(job.report)}</section>`:"")+
        (repair.kdt_job_id?`<section class="datacard"><h3>${escape(T("KDT repair draft","KDT 修复草稿"))}</h3><p>${escape(repair.ki_name)} · ${escape(statusName(repair.status))}</p>${repair.candidate_path?`<p class="investigation-meta">${escape(T("Repair draft folder","修复草稿目录"))}: <code>${escape(repair.candidate_path)}</code></p>`:""}${scope}${maintenance}${routingScope}${failedCheck}${interfaceSummary}${pathSummary}${draftOnly}${authorSummary}<p class="hint">${escape(T("KDT verification checks package structure. Native and scientific tests require their own evidence. Continuing returns to the project's normal plan review.","KDT 验证检查包结构。原生模型与科学测试需要各自的证据。继续后将进入项目正常的计划审核流程。"))}</p>${repair.blocked_reason?`<p class="investigation-error">${escape(repair.blocked_reason)}</p>`:""}${changedFiles}${block(T("KDT verification report","KDT 验证报告"),repair.verification,"verification")}<small class="investigation-meta">${escape(repair.kdt_job_id)}${repair.verification_id?" · "+escape(repair.verification_id):""}</small></section>`:"");
    }
    function sync(){
      const id=current(),binding=currentBinding(),bindingChanged=binding!==bindingState;
      bindingState=binding;
      if(id!==sessionId){
        if(sessionId){issues.set(sessionId,$("#investigation-issue").value);authorNotes.set(sessionId,$("#investigation-author-notes").value);}
        stopPoll();sequence++;sessionId=id;job=null;available=false;hostBusy=false;reason="";error="";notice="";pending=false;loading=false;rejectedSources=[];
        $("#investigation-source").value="";
        $("#investigation-issue").value=issues.get(id)||"";
        $("#investigation-author-notes").value=authorNotes.get(id)||"";
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
        rejectedSources=Array.isArray(data.rejected_sources)?data.rejected_sources.filter(row=>row&&typeof row.id==="string"&&typeof row.name==="string"):[];
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
        if($("#investigation-source").value)payload.source_id=$("#investigation-source").value;
      }else{
        if(!captured?.id)return;
        suffix=`/${encodeURIComponent(captured.id)}/${action}`;
        if(action==="draft"){
          payload={ki_name:$("#investigation-ki").value};
          if($("#investigation-mode").value==="maintenance")Object.assign(payload,{repair_mode:"maintenance",maintenance_recipe:$("#investigation-recipe").value});
        }
        if(action==="build")payload.author_notes=$("#investigation-author-notes").value;
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
    for(const action of ["start","cancel","retry","draft","build","verify","apply"])$("#investigation-"+action).onclick=()=>mutate(action);
    $("#investigation-issue").addEventListener("input",()=>{if(sessionId)issues.set(sessionId,$("#investigation-issue").value);});
    $("#investigation-author-notes").addEventListener("input",()=>{if(sessionId)authorNotes.set(sessionId,$("#investigation-author-notes").value);});
    $("#investigation-mode").addEventListener("change",render);
    $("#investigation-recipe").addEventListener("change",render);
    $("#investigation-ki").addEventListener("change",render);
    $("#investigation-source").addEventListener("change",render);
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
