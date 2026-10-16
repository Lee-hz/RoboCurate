import {auditStatus,taskOutcome,matchesTaskOutcome,matchesRetention,recordNavigation} from './record-audit.mjs';
import { latestPoint, recordedGhosts } from "./trajectory-data.mjs";
import { EpisodeData } from "./viewer/data.js";
import { ReviewTools } from "./review-tools.js";
import { ProgressPanel, mountProgressExport, progressExportOptions } from "./progress-view.js";
import {
  FramePlayer,
  nearestFrame,
  adjacentFrame,
  clampWindow,
  zoomWindow,
} from "./playback.mjs";
import { icon, installIcons } from "./icons.js";
import { compareDataGrades, ratingPoints, ratingText, ratingPercent } from "./grading-view.mjs";
import { reviewLabels, reviewIcons, queues, workflowState, nextReviewStep } from "./workflow.mjs";
import {selectCandidates} from './selection.mjs';
import {installMiniMaxAccess} from './minimax-access.mjs';

const $ = (s) => document.querySelector(s),
  $$ = (s) => [...document.querySelectorAll(s)];
const escape = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const copy = (x) => JSON.parse(JSON.stringify(x));
const grades = reviewLabels;
const dataGrades = { A: "优先候选", B: "常规候选", C: "低优先候选", D: "已筛出 · 未完成", E: "已筛出 · 不完整", R: "待准入复核", U: "待任务识别" };
const camNames = {
  head: "头部相机",
  left_wrist: "左腕相机",
  right_wrist: "右腕相机",
};
const tags = [
  "任务失败",
  "图像遮挡",
  "丢帧 / 卡顿",
  "跟踪偏差",
  "动作不完整",
  "无效等待",
  "指令不清",
  "需裁剪",
];
let catalog = { episodes: [], counts: {}, roots: [] },
  selected = new Set(),
  page = "library",
  current = null,
  draft = null,
  dirty = false;
let editingClip = null;
let progressPanel = null;
let simDemo = null;
let taskflowPanel = null;
let auditOverview=null,routeEpoch=0;
const recordViewStates=new Map();
let reviewIntent = null;
let workflowBusyFor = null;
let data = null,
  loadingData = false,
  detailTab = "diagnostics",
  reviewTools = null,
  signalKind = "position",
  joint = 15,
  robot = null,
  robotLoading = false,
  reviewToken = 0;
let trajectoryData = null, trajectoryLoading = false, activeEvidenceId = null, stageLayout = "motion";
let rendererChoice = "full";
let framePlayer = null,
  primaryCamera = "head",
  exactFrame = null,
  chartWindow = null,
  scrubState = null,
  chartDrag = null;
let renderedFrames = 0,
  fpsStart = performance.now(),
  frameError = false;
let playhead = 0,
  playing = false,
  lastTick = 0,
  lastFrame = 0,
  speed = 1,
  playRange = null,
  toastTimer,
  refreshing = false;
const filters = {
  search: "",
  stageaudit: "",
  stageoutcome: "",
  source: "original",
  grade: "",
  auto: "",
  cohort: "",
  queue: "",
  review: "",
  outcome: "",
  sort: "newest",
};
const fmt = (n, d = 1) => Number(n || 0).toFixed(d);
const size = (n) =>
  n >= 1e9 ? `${fmt(n / 1e9, 2)} GB` : `${fmt(n / 1e6, 0)} MB`;
const clock = (n) =>
  `${String(Math.floor(n / 60)).padStart(2, "0")}:${Number(n % 60)
    .toFixed(2)
    .padStart(5, "0")}`;
function updateThemeLabel() {
  const button = $("#theme-toggle");
  if (button)
    button.innerHTML =
      document.documentElement.dataset.theme === "dark"
        ? `${icon("sun")}浅色`
        : `${icon("moon")}深色`;
}
function setSidebarCollapsed(collapsed, persist = true) {
  document.documentElement.dataset.sidebar = collapsed ? 'collapsed' : 'expanded';
  if (persist) {
    try { localStorage.setItem('robocurate-sidebar',collapsed?'collapsed':'expanded'); } catch {}
  }
  const button = $('#sidebar-toggle');
  if (button) {
    const label = collapsed ? '展开侧栏' : '收起侧栏';
    button.innerHTML = `<svg class="sidebar-control-icon" viewBox="0 0 24 24" aria-hidden="true"><use href="/sidebar-control.svg#panel"/></svg><span class="sidebar-toggle-label">${label}</span>`;
    button.setAttribute('aria-expanded',String(!collapsed));
    button.setAttribute('aria-label',label);
    button.title = label + ' · Ctrl+\\';
  }
  requestAnimationFrame(()=>{
    drawChart();
    robot?.resize?.();
  });
}
function toggleSidebar() {
  setSidebarCollapsed(document.documentElement.dataset.sidebar !== 'collapsed');
}
function toast(message, error = false) {
  clearTimeout(toastTimer);
  $("#toast").textContent = message;
  $("#toast").className = "show" + (error ? " error" : "");
  toastTimer = setTimeout(
    () => ($("#toast").className = ""),
    error ? 7000 : 3500,
  );
}
async function api(url, body) {
  const res = await fetch(
    url,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  const out = await res.json();
  if (!res.ok)
    throw Error(out.error || out.message || `请求失败 ${res.status}`);
  return out;
}
function errorDialog(e) {
  const el = $("#dialog-error");
  if (el) el.textContent = e.message;
  else toast(e.message, true);
}
const frame = (e, cam, t) =>
  `/api/frame?ep=${encodeURIComponent(e.id)}&cam=${encodeURIComponent(cam)}&t=${Number(t).toFixed(3)}`;
const outcome = (e) =>
  e.outcome === true
    ? '<span class="badge success" title="采集人员记录的任务结果">采集标记 · 成功</span>'
    : e.outcome === false
      ? '<span class="badge failure" title="采集人员记录的任务结果">采集标记 · 失败</span>'
      : '<span class="badge grade-none">未标记</span>';
const badge = (g) =>
  `<span class="badge review-verdict verdict-${g || 'none'}">${icon(reviewIcons[g] || 'clock')}${grades[g] || '未审核'}</span>`;
const filtered = () =>
  catalog.episodes
    .filter(
      (e) =>
        (!filters.search ||
          [
            e.episode_id,
            e.name,
            e.task,
            e.session,
            e.instruction,
            e.review.instruction,
            ...e.review.tags,
          ]
            .join(" ")
            .toLowerCase()
            .includes(filters.search.toLowerCase())) &&
        (!filters.source || (filters.source==='snapshots'?e.snapshot:!e.snapshot)) &&
        (!filters.stageaudit || auditStatus(auditOverview,e.id).key === filters.stageaudit) &&
        matchesTaskOutcome(auditOverview,e.id,filters.stageoutcome) &&
        matchesRetention(e,filters.grade) &&
        (!filters.review ||
          (filters.review === "yes" ? !!e.review.grade : !e.review.grade)) &&
        (!filters.outcome ||
          (filters.outcome === "yes"
            ? e.outcome === true
            : e.outcome === false)),
    )
    .sort((a, b) =>
      filters.sort === "duration"
          ? b.duration_s - a.duration_s
          : Number(!!b.session) - Number(!!a.session) ||
            (b.episode_id || b.name).localeCompare(a.episode_id || a.name),
    );

async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    const [nextCatalog,nextAudits]=await Promise.all([api("/api/catalog"),api("/api/taskflow").catch(()=>null)]);catalog=nextCatalog;auditOverview=nextAudits;
    $("#source-name").textContent =
      catalog.roots.length === 1
        ? catalog.roots[0].split("/").pop()
        : `${catalog.roots.length} 个本地数据源`;
    $("#source-name").title = catalog.roots.join("\n");
    $("#service-status").innerHTML = '<i class="local-dot"></i> 服务已连接';
    for (const id of selected)
      if (!catalog.episodes.some((e) => e.id === id)) selected.delete(id);
    if (page === "library" && $("#episode-rows")) updateLibrary();
    if (page === "review" && current) {
      const old = current.cache;
      current = catalog.episodes.find((e) => e.id === current.id) || current;
      if(progressPanel){progressPanel.episode=current;if(old!==current.cache)progressPanel.refresh();}
      const status = $("#decode-status");
      if (status) status.innerHTML = cacheStatus(current);
      if (old === "ready" && current.cache !== "ready") {
        data = null;trajectoryData=null;trajectoryLoading=false;
        loadingData = false;
        robot?.destroy();
        robot = null;
      }
      if (current.cache === "ready" && !data && !loadingData) loadSignals();
      if(!current.snapshot)reviewTools?.ensureLoaded();
      putHTML('#auto-grade-review', gradeReviewHTML(current));
      putHTML('#rating-overview', ratingOverviewHTML(current));
      updateReviewStep();
      if (detailTab === "quality" && old !== current.cache) renderDetail();
    }
    if (page === "exports" && $("#export-list")) loadExports();
  } catch (e) {
    $("#service-status").textContent = "连接中断 · 自动重试";
    if (!catalog.episodes.length && $("#main").querySelector(".loading-page"))
      $("#main").innerHTML =
        `<div class="empty"><strong>暂时无法读取数据</strong>${escape(e.message)}<br><button data-action="retry">重新连接</button></div>`;
  } finally {
    refreshing = false;
  }
}

function cacheStatus(e) {
  if(e.snapshot)return '<span class="qc-status">本机证据快照</span>';
  return e.cache === "ready"
    ? '<span class="qc-status ready">已解析</span>'
    : e.cache === "building"
      ? `<span class="progress-inline" title="${escape(e.cache_message)}"><span class="spinner"></span> ${e.cache_message.includes("排队") ? "等待解析" : "正在解析"}</span>`
      : e.cache === "error"
        ? `<span class="qc-status error" title="${escape(e.cache_message)}">解析失败 · 可重试</span>`
        : '<span class="qc-status">待解析</span>';
}
function dataGradeBadge(e) {
  const g=e.quality.grading;
  return `<span class="data-grade" data-level="${g?.grade || 'pending'}">${g?.grade?`<span class="data-grade-code">${g.grade}</span><span>${escape(g.label)}</span>`:'待评估'}</span>`;
}
function coverageText(e) {
  const value = e.quality.grading?.metrics.coverage_fraction;
  return value == null ? '—' : `${fmt(value * 100, 2)}%`;
}
function gradeReviewHTML(e) {
  return `<div class="grade-review-meta"><span>${escape(e.curation?.reason||"等待任务准入")}</span></div>`;
}
function gradeReportHTML(e) {
  if(e.quality.grading?.method==='deminf_qualified_v2')return curationEvidenceHTML(e);
  const g=e.quality.grading;
  if (!g) return '<p>等待分级结果，请刷新或重新解析。</p>';
  const m=g.metrics;
  return `<section class="grade-report"><div class="grade-review-heading"><h3>分级依据</h3>${dataGradeBadge(e)}</div>
  <div class="grade-report-metrics"><div>有效覆盖<strong>${coverageText(e)}</strong><small>${m.aligned_samples ?? '—'} / ${m.samples ?? '—'} 个完整时刻</small></div><div>最长连续有效区间<strong>${m.longest_valid_s==null?'—':fmt(m.longest_valid_s,2)+' s'}</strong></div></div>
  <div class="grade-result-label">${g.state==='pending'?'等待深度质检':g.reasons.length?`${g.reasons.length} 个维度需复核`:'已测指标在规则范围内'}</div>
  ${g.reasons.length?g.reasons.map(c=>`<article class="grade-attention"><div>${icon(c.grade==='D'?'close':'warning')}<strong>${escape(c.label)}</strong></div><p>${escape(c.detail)}</p><p class="grade-action">建议：${escape(c.action)}</p>${['motion','coverage','numeric','continuity','timestamps'].includes(c.key)&&e.cache==='ready'?`<button class="small" data-grade-evidence="${c.key}">${icon('search')}定位相关线索</button>`:`<button class="small" data-detail="streams">${icon('list')}查看数据通道</button>`}</article>`).join(''):`<p>${escape(g.summary)}</p>`}
  <div class="evidence-actions"><button class="small" data-action="open-clips">${icon('crop')}检查保留范围</button><button class="small" data-action="review-instruction">${icon('list')}完善任务标注</button></div>
  <details class="grade-policy grade-all-checks"><summary>全部检查维度 · ${g.checks.length} 项</summary>${g.checks.map(c=>`<article class="grade-check"><div><span class="grade-code">${c.grade}</span><strong>${escape(c.label)}</strong></div><p>${escape(c.detail)}</p></article>`).join('')}</details>
  <p class="hint">技术等级依据数值与时序，任务结果结合画面复核。</p></section>`;
}
async function loadReferenceChecks() {
  const target = $("#reference-checks-body"), ep = current?.id;
  if (!target || !ep) return;
  if (current.cache !== "ready") {
    target.textContent = "完成深度质检后可查看原始通道的参考检查。";
    return;
  }
  try {
    const report = await api('/api/reference-checks?ep=' + ep);
    if (!target.isConnected || current?.id !== ep) return;
    const names = {'state.q':'身体状态','action.q':'身体动作','hand.left.state_q':'左手状态','hand.right.state_q':'右手状态','hand.left.cmd_q':'左手指令','hand.right.cmd_q':'右手指令','camera.head':'头部相机','camera.left_wrist':'左腕相机','camera.right_wrist':'右腕相机'};
    const number = (x, decimals=1) => x == null ? '—' : fmt(x, decimals);
    const details = `<p>参考 HFlow 的原始采集检查：以通道中位间隔为基准，记录超过 10 ms 的间隔偏差及超过 3 个周期的间隔。这里的测量不自动改变数据等级。</p><div class="table-scroll"><table class="technical-table reference-timing"><thead><tr><th>通道</th><th>中位频率</th><th>间隔偏差比例</th><th>非递增时间戳</th><th>长间隔次数</th></tr></thead><tbody>${Object.entries(report.timing).map(([key,r])=>`<tr><td>${escape(names[key] || key)}</td><td>${r.median_dt_s > 0 ? number(1/r.median_dt_s) + ' Hz' : '—'}</td><td>${number(r.period_violation_pct,2)}${r.period_violation_pct == null ? '' : '%'}</td><td>${r.nonpositive_dt_count ?? '—'}</td><td>${r.gap_count ?? '—'}</td></tr>`).join('')}</tbody></table></div><p>数值重复是复核线索。保持姿态、保持抓握、量化传感器和不变的控制目标都可能产生重复值。</p><div class="table-scroll"><table class="technical-table reference-values"><thead><tr><th>通道</th><th>NaN / Inf</th><th>完全重复步占比</th><th>未变化维数</th></tr></thead><tbody>${Object.entries(report.values).map(([key,r])=>`<tr><td>${escape(names[key] || key)}</td><td>${r.nan_count} / ${r.inf_count}</td><td>${number(r.repeated_step_pct,2)}%</td><td>${r.unchanged_dimensions?.length ?? '—'} / ${r.dimensions}</td></tr>`).join('')}</tbody></table></div><p class="hint">trajlens 的 0.1 ms 时间容差针对固定帧率数据，仅用于导出网格检查；不直接套用到原始多传感器采集。运动指标随任务画面同步呈现。参考：<a href="https://github.com/Hebbian-Robotics/hflow" target="_blank" rel="noreferrer">HFlow</a> · <a href="https://github.com/Kunal-Somani/trajlens" target="_blank" rel="noreferrer">trajlens</a></p>`;
    const changed = Object.values(report.timing).filter(r=>(r.nonpositive_dt_count||0)>0 || (r.gap_count||0)>0).length;
    const invalid = Object.values(report.values).reduce((n,r)=>n+r.nan_count+r.inf_count,0);
    const repeating = Object.values(report.values).filter(r=>(r.repeated_step_pct||0)>0).length;
    target.innerHTML = `<div class="reference-summary"><span>时间间隔待核对 <b>${changed} 路</b></span><span>无效数值 <b>${invalid} 个</b></span><span>出现重复值 <b>${repeating} 路</b></span></div><p>这些现象供进一步复核，不自动改变数据等级。正常保持姿态或抓握也可能产生重复值。</p><button class="small" data-action="review-problems">${icon('search')}查看问题导航</button><details class="reference-raw grade-policy"><summary>原始指标与规则来源</summary>${details}</details>`;

  } catch (error) {
    if (target.isConnected) target.textContent = '参考检查暂不可用：' + error.message;
  }
}
const renderedHTML = new WeakMap();
function putHTML(selector, html) {
  const host = typeof selector === 'string' ? $(selector) : selector;
  if (host && renderedHTML.get(host) !== html) {
    host.innerHTML = html;
    renderedHTML.set(host, html);
  }
}
function qualityOverviewHTML() {
  const ready=selectCandidates(catalog.episodes).length,excluded=catalog.episodes.filter(e=>['D','E'].includes(e.quality.grading?.grade)).length;
  return `<div class="quality-overview-head"><h2>筛选与分级</h2><span class="muted" id="curation-version">候选筛选</span><a class="subtle-link" href="#rules">分级标准</a></div><p class="curation-status">${ready} 条已排序候选 · ${excluded} 条已筛出 · ${catalog.episodes.length-ready-excluded} 条待判断。不同任务分别比较，待判断记录进入复核队列。</p><div class="quality-card-grid">${Object.entries(dataGrades).map(([g,label])=>{
    const count=catalog.episodes.filter(e=>(e.quality.grading?.grade || 'pending')===g).length;
    return `<button class="quality-card ${filters.auto===g?'selected':''}" data-quality-filter="${g}" aria-pressed="${filters.auto===g}" aria-label="筛选${g==='pending'?label:g+'级'+label}，${count}条"><span class="quality-card-label">${g==='pending'?'':`<span class="grade-code">${g}</span>`}<span>${label}</span></span><span class="quality-count">${count}</span></button>`;
  }).join('')}</div><div class="curation-actions"><button data-action="select-qualified">选择当前范围全部合格候选</button><button data-action="select-priority">仅选择当前范围优先候选</button><span class="muted">选中后导出清单；不会删除原始数据。排名分在详情中查看。</span></div>`;
}
function queueHTML() {
  return `<span class="queue-heading">工作队列</span><button data-queue-filter="" class="queue-tab ${!filters.queue?'active':''}" aria-pressed="${!filters.queue}">全部 <b>${catalog.episodes.length}</b></button>${Object.entries(queues).map(([id,q])=>`<button data-queue-filter="${id}" class="queue-tab ${filters.queue===id?'active':''}" aria-pressed="${filters.queue===id}">${icon(q.icon)}${q.label}<b>${catalog.episodes.filter(e=>workflowState(e).queue===id).length}</b></button>`).join('')}`;
}
function syncFilters() {
  for (const key of ['grade','auto','cohort','review','outcome','sort','stageaudit','stageoutcome','source']) if ($('#filter-'+key)) $('#filter-'+key).value=filters[key];
  if ($('#search')) $('#search').value=filters.search;
}
function resetBrowseFilters() {
  Object.assign(filters,{search:'',stageaudit:'',stageoutcome:'',grade:'',auto:'',cohort:'',review:'',outcome:'',queue:''});
}
function chooseOverviewFilter(key,value) {
  const same=filters[key]===value;
  resetBrowseFilters();filters[key]=same?'':value;
  syncFilters();updateLibrary();
}
function workflowButton(e) {
  const state=workflowState(e);
  const symbol={analyze:'sliders',review:'search',instruction:'list',preflight:'export',inspect:'info'}[state.action];
  return `<button class="small workflow-open" data-workflow-open="${e.id}" ${e.cache==='building'&&state.action==='analyze'?'disabled':''}>${icon(symbol)}${state.label}</button>`;
}
function updateReviewStep() {
  if (page !== 'review' || !current || !draft || !$('#review-next')) return;
  const step = nextReviewStep(current, draft, dirty);
  const busy = workflowBusyFor === current.id;
  const symbol = {inspect:'info',analyze:'sliders',decision:'check',instruction:'list',save:'save',preflight:'export'}[step.action];
  putHTML('#review-next', `<div class="next-step-heading"><strong>${escape(step.title)}</strong></div><p>${escape(step.detail)}</p><button class="text-btn" data-action="workflow-next" data-next-step="${step.action}" ${step.disabled||busy?'disabled':''}>${icon(busy?'clock':symbol)}${busy?'处理中…':step.button}</button>`);
}
function openClipEditor(focus = true) {
  const editor = $('#clip-editor');
  if (!editor) return;
  editor.open = true;
  if (focus) {
    editor.scrollIntoView({block:'nearest'});
    $('#clip-start')?.focus({preventScroll:true});
  }
}
function revealQuality() {
  detailTab = 'quality';
  renderDetail();
  const panel = $('.details-panel');
  if (panel) {
    panel.scrollTop = 0;
    panel.scrollIntoView({block:'nearest'});
  }
}
function applyReviewAction(action) {
  if (action === 'inspect') return revealQuality();
  if (["instruction","decision"].includes(action)) {detailTab="review";renderDetail();}
  if (action === 'instruction') {
    $('#task-instruction')?.scrollIntoView({block:'nearest'});
    $('#task-instruction')?.focus({preventScroll:true});
  } else if (action === 'decision') {
    $('.grade-picker')?.scrollIntoView({block:'nearest'});
    $('[data-grade]')?.focus({preventScroll:true});
  } else {
    detailTab = 'diagnostics';renderDetail();
    $('.details-panel')?.scrollIntoView({block:'nearest'});
  }
}
async function openWorkflow(record, action = workflowState(record).action) {
  if (action === 'analyze') {
    if (record.cache === 'building') return;
    await api('/api/analyze',{ids:[record.id]});
    await refresh();toast('该记录已加入质检队列。');return;
  }
  if (action === 'preflight') return exportDialog([record.id], 'dataset');
  if (page === 'record' && taskflowPanel?.recording?.id === record.id) {taskflowPanel.setDetailTab(['instruction','decision','review'].includes(action)?'manual':'criteria');return;}
  reviewIntent = {id:record.id,action};
  location.hash = 'record/' + record.id;
}
async function locateGradeEvidence(key) {
  const tools = reviewTools, id = current?.id;
  if (!tools) return;
  await tools.ensureLoaded();
  if (tools !== reviewTools || current?.id !== id) return;
  const kinds = {motion:['tracking','temperature'],coverage:['gap','invalid'],numeric:['invalid'],continuity:['gap'],timestamps:['gap']}[key] || [];
  const event = tools.data?.events.find(e=>kinds.includes(e.kind));
  if (!event) {
    applyReviewAction('review');
    toast('请在问题导航中复核；此项汇总指标没有对应的单一时刻。');return;
  }
  tools.group = '';tools.verdict = '';
  tools.page = Math.floor(tools.events().findIndex(e=>e.id===event.id)/6);
  tools.select(event.id);
  $('.details-panel')?.scrollIntoView({block:'nearest'});
}
function stageAuditCell(record){
  const state=auditStatus(auditOverview,record.id),result=taskOutcome(auditOverview,record.id);
  if(state.key==='not_started')return '<span class="record-audit-status" data-state="not_started">未分析</span>';
  if(['unavailable','failed'].includes(state.key))return `<span class="record-audit-status" data-state="${state.key}">${escape(state.label)}</span>`;
  const run=state.run;
  const headline=state.key==='running'?state.label:result.label+(result.key==='failed'&&run?.summary.uncertain>0?` · ${run.summary.uncertain} 段证据不足`:'');
  const scope=run?.analysis_range;
  const range=scope?`${scope.start_s.toFixed(1)}–${scope.end_s.toFixed(1)}s`:'范围见结果';
  const detail=state.key==='legacy'?range:state.key==='running'?state.detail:state.detail.replace('人工 ','已复核 ');
  const provenance=run?`${run.model==='HORIZON-MiniMax'?'MiniMax':run.model||'历史模型未标注'} · ${detail}`:detail;
  return `<span class="record-task-outcome" data-result="${state.key==='running'?'running':result.key}">${escape(headline)}</span><div class="ep-sub audit-provenance">${escape(provenance)}</div>`;
}
async function openTemplateManager(){
  if(taskflowPanel)return;
  const epoch=routeEpoch,{Taskflow}=await import('./taskflow.mjs');if(epoch!==routeEpoch||taskflowPanel)return;
  const host=document.createElement('div');host.id='template-manager';$('#main').append(host);
  const panel=new Taskflow(host,api,escape);taskflowPanel=panel;
  try{await panel.mount(null,{configurationOnly:true});}catch(error){panel.destroy();host.remove();if(taskflowPanel===panel)taskflowPanel=null;throw error;}if(!panel.alive)return;
  host.querySelector('#tf-setup-dialog').addEventListener('close',()=>{panel.destroy();host.remove();if(taskflowPanel===panel)taskflowPanel=null;},{once:true});
}
function renderLibrary() {
  page = "library";
  $("#main").innerHTML = `<div class="library-page"><div class="page-head"><h1>数据工作台</h1><div class="actions"><button data-open-templates>任务范本</button><button class="primary" data-action="import">导入数据</button></div></div>
  <section class="panel library-records" aria-label="采集记录"><div class="panel-head"><h2>采集记录 <span id="record-count" aria-live="polite"></span></h2><div class="library-list-actions"><span id="analysis-progress"></span><select id="filter-sort" aria-label="排序"><option value="newest" ${filters.sort==='newest'?'selected':''}>编号 ↓</option><option value="duration" ${filters.sort==='duration'?'selected':''}>时长 ↓</option></select><button class="text-btn" data-action="clear-filters" id="clear-filters">重置筛选</button></div></div>
  <div class="library-filters">
    <div class="search-box"><span>${icon('search')}</span><input id="search" placeholder="搜索记录、任务或标签" aria-label="搜索记录" value="${escape(filters.search)}"></div>
    <select id="filter-source" aria-label="记录来源">${[['original','原始采集'],['snapshots','历史参考快照'],['','全部来源']].map(([v,label])=>`<option value="${v}" ${filters.source===v?'selected':''}>${label}</option>`).join('')}</select>
    <label>审核进度<select id="filter-stageaudit" aria-label="阶段审核进度">${[['','全部进度'],['not_started','待分析'],['running','分析中'],['failed','分析失败'],['pending','待人工复核'],['reviewed','已复核'],['legacy','仅历史模型结果']].map(([v,label])=>`<option value="${v}" ${filters.stageaudit===v?'selected':''}>${label}</option>`).join('')}</select></label>
    <label>阶段判断<select id="filter-stageoutcome" aria-label="任务判断筛选">${[['','全部判断'],['failed','含未完成尝试'],['uncertain','证据不足'],['completed','已分析阶段均完成']].map(([v,label])=>`<option value="${v}" ${filters.stageoutcome===v?'selected':''}>${label}</option>`).join('')}</select></label>
    <label>人工保留<select id="filter-grade" aria-label="保留结论筛选"><option value="">全部结论</option><option value="unreviewed" ${filters.grade==='unreviewed'?'selected':''}>尚未决定</option>${Object.entries(grades).map(([g,label])=>`<option value="${g}" ${filters.grade===g?'selected':''}>${label}</option>`).join('')}<option value="stale" ${filters.grade==='stale'?'selected':''}>源文件变化，需复核</option></select></label>

  </div><div id="bulk-bar"></div>
  <div class="table-scroll"><table aria-label="采集记录列表"><thead><tr><th><input type="checkbox" id="select-all" aria-label="选择筛选后的全部记录"></th><th>记录</th><th>时长</th><th>阶段审核</th><th>人工保留</th><th><span class="library-action-label">操作</span></th></tr></thead><tbody id="episode-rows"></tbody></table></div></section></div>`;
  updateLibrary();
}
function updateLibrary() {
  const rows = filtered();
  const filtersOn=!!(filters.search||filters.stageaudit||filters.stageoutcome||filters.grade);
  $('#clear-filters').hidden=!filtersOn;
  $("#record-count").textContent = `${rows.length} 条`;
  const building = catalog.episodes.filter(e=>e.cache === "building").length;
  $("#analysis-progress").innerHTML = building
    ? `<span class="progress-inline"><span class="spinner"></span>${building} 条解析中</span>` : '';
  putHTML('#episode-rows',rows.length ? rows.map(e=>`<tr class="episode-row" data-ep="${e.id}"><td class="record-selection"><input type="checkbox" class="select-ep" data-id="${e.id}" ${selected.has(e.id)?'checked':''} aria-label="选择 ${escape(e.episode_id||e.name)}"></td>
  <td class="record-identity"><div class="ep-cell"><img class="thumb" loading="lazy" alt="${escape(e.episode_id||e.name)} 场景预览" src="${frame(e,Object.keys(e.cameras)[0]||'head',e.duration_s*.4)}"><div><div class="ep-name">${escape(e.episode_id||e.name)}</div><div class="ep-sub">${escape(e.task||'未命名任务')}${e.snapshot?' · 历史快照':''}</div></div></div></td>
  <td class="record-duration"><span>${fmt(e.duration_s)} <span class="record-unit">s</span></span><div class="ep-sub">${Object.keys(e.cameras).length} 路相机</div></td><td class="record-analysis">${stageAuditCell(e)}</td>
  <td class="record-retention">${e.review.grade?badge(e.review.grade):`<span class="badge review-verdict verdict-none">${icon('clock')}未决定</span>`}${e.review_stale?'<span class="grade-meta">源文件已变化，需复核</span>':''}</td><td class="record-action"><a class="record-open" href="#record/${encodeURIComponent(e.id)}" aria-label="审核 ${escape(e.episode_id||e.name)}">审核 ${icon('right')}</a></td></tr>`).join('') : '<tr><td colspan="6"><div class="empty"><strong>没有符合条件的记录</strong>调整筛选条件，或导入数据。</div></td></tr>');
  $("#select-all").checked = rows.length > 0 && rows.every(e=>selected.has(e.id));
  $("#select-all").indeterminate = rows.some(e=>selected.has(e.id)) && !$("#select-all").checked;
  const visibleSelected=rows.filter(e=>selected.has(e.id)).length;
  $("#bulk-bar").innerHTML = selected.size
    ? `<div class="bulk-bar"><b>已选 ${selected.size} 条${visibleSelected<selected.size?` · ${selected.size-visibleSelected} 条不在当前筛选中`:''}</b><button class="small" data-action="batch-grade">批量保留结论</button><span class="spacer"></span><button class="small ghost" data-action="clear-selection">取消选择</button><button class="small primary" data-action="export-selected">导出所选 ↗</button></div>` : "";
}

function saveDraft() {
  if (!current || !draft) return;
  dirty = true;
  localStorage.setItem("rds-draft-" + current.id, JSON.stringify(draft));
  const s = $("#save-state");
  updateReviewStep();
  if (s) {
    s.textContent = "未保存";
    s.classList.add("dirty");
  }
}
function filmstripHTML(e,headMode) {
  const cam=e.cameras.head?'head':Object.keys(e.cameras)[0];
  if(!cam)return '';
  return `<div class="filmstrip" id="filmstrip" aria-label="全段画面索引">${Array.from({length:8},(_,i)=>{
    const t=e.duration_s*(i+.5)/8;
    return `<button data-film-time="${t}" title="定位到 ${clock(t)}" aria-label="画面索引 ${clock(t)}"><span class="film-image ${cam==='head'?headMode:''}"><img loading="lazy" src="${frame(e,cam,t)}" alt="${clock(t)} 场景预览"></span><span>${clock(t)}</span></button>`;
  }).join('')}<i class="film-playhead" aria-hidden="true"></i></div>`;
}
function trajectoryHTML() {
  return `<section class="trajectory-panel" aria-label="人形移动操作可视化"><div class="scene-header"><div><strong>全身运动</strong><span id="robot-renderer">G1 · 加载中</span></div><span id="scene-time">00:00.00</span></div>
    <div class="scene-toolbar"><div class="scene-tools"><select id="trail-part" aria-label="轨迹部位"><option value="wrist">双腕 · 操作</option><option value="foot">双足 · 下肢</option><option value="all">双腕与双足</option></select><select id="trail-side" aria-label="轨迹左右侧"><option value="both">左右侧</option><option value="left">仅左侧</option><option value="right">仅右侧</option></select><select id="trail-window" aria-label="轨迹时间范围"><option value="5">过去 5 秒</option><option value="2" selected>过去 2 秒</option><option value="10">过去 10 秒</option><option value="0">全段轨迹</option></select></div><div class="scene-tools"><select id="scene-focus" aria-label="模型取景范围"><option value="all">全身</option><option value="upper">上肢近景</option><option value="lower">下肢近景</option></select><button class="small scene-toggle" data-scene-toggle="show-pose-trail" aria-pressed="false">残影</button><button class="small scene-toggle" data-scene-toggle="show-targets" aria-pressed="false">目标对照</button><select id="robot-view" aria-label="三维视角"><option value="iso">斜视</option><option value="front">正面</option><option value="side">侧面</option><option value="top">俯视</option></select><button class="small" data-action="robot-fit" title="适配当前姿态与可见轨迹">适配</button><button class="icon-btn" data-action="robot-reset" title="复位视角" aria-label="复位视角">${icon('reset')}</button><details class="scene-settings"><summary title="显示设置">${icon('sliders')}显示</summary><div><label>模型姿态<select id="robot-source" aria-label="三维姿态数据源"><option value="state.q">实测关节</option><option value="action.q">控制目标</option><option value="ref.dof">遥操作参考</option></select></label><label><input id="robot-overlay" type="checkbox">叠加控制目标姿态</label><label><input id="show-trails" type="checkbox" checked>显示历史轨迹</label><label><input id="show-targets" type="checkbox">对照控制目标轨迹</label><p>当前模型为 100 Hz 回放网格；轨迹由原始采样计算。控制目标不代表理想路径。</p><fieldset class="pose-settings"><legend>录制姿态残影</legend><label><input id="show-pose-trail" type="checkbox">显示多时刻姿态</label><label><input id="show-past" type="checkbox" checked>历史姿态 <select id="past-window" aria-label="历史姿态窗口"><option value="0.5">0.5 秒</option><option value="1">1 秒</option><option value="2" selected>2 秒</option><option value="5">5 秒</option></select></label><label><input id="show-future" type="checkbox">后续记录 <select id="future-window" aria-label="后续记录窗口"><option value="0.5">0.5 秒</option><option value="1">1 秒</option><option value="2" selected>2 秒</option><option value="5">5 秒</option></select></label><label>残影部位<select id="pose-scope" aria-label="姿态残影部位"><option value="all">全身协同</option><option value="upper">上肢操作</option><option value="lower">下肢动作</option></select></label><label>每侧姿态数<select id="pose-count" aria-label="每侧残影数量"><option value="1">1</option><option value="2">2</option><option value="3" selected>3</option></select></label><label>透明度 <input id="pose-opacity" type="range" min="0.08" max="0.45" step="0.01" value="0.18" aria-label="残影透明度"></label><p>紫色：历史；金色：后续记录。全部来自实测采样，不是模型预测。点击姿态或下方时间可定位。</p></fieldset><label><input id="show-joint-frames" type="checkbox">腕 / 踝关节坐标轴</label><label><input id="show-grid" type="checkbox" checked>显示坐标网格</label></div></details></div></div>
    <div class="scene-stage"><div class="robot-host" id="robot-host"><div class="empty"><span class="spinner"></span>解析完成后加载全身运动…</div></div><div class="scene-legend"><span><i class="left-point"></i>左侧</span><span><i class="right-point"></i>右侧</span><span>实线 · 实测</span><span class="target-legend">虚线 · 目标</span></div><div class="scene-pose-times" id="scene-pose-times" aria-label="录制姿态时间"></div><div class="scene-interaction">拖动旋转 · 滚轮缩放 · 点击轨迹点定位</div><div id="scene-evidence" class="scene-evidence">选择右侧线索或时间轴标记，联动画面与轨迹</div></div>
    <div class="scene-readout"><span><b id="point-left-label">左腕</b><span id="wrist-left">—</span></span><span><b id="point-right-label">右腕</b><span id="wrist-right">—</span></span><span class="imu-readout">IMU 横滚 / 俯仰 <span id="base-tilt">—</span></span></div><div class="scene-foot"><span>骨盆相对坐标 · m <span class="coordinate-help" title="腕部与踝部关节原点；没有基座平移，不代表世界行走路线。未标定夹爪 TCP、足底接触点。">ⓘ</span></span><span id="trajectory-status">读取原始轨迹…</span></div></section>`;
}
function ratingOverviewHTML(e) {
  const r=e.quality.rating,c=e.curation;
  return `<div class="rating-title"><span>数据质量评分</span>${dataGradeBadge(e)}</div><div class="rating-number"><strong>${ratingText(r)}</strong><span>/ 10</span><button class="text-btn" data-action="show-quality">评分依据 ${icon('right')}</button></div><div class="rating-bar"><i style="width:${ratingPercent(r)}%"></i></div><div class="rating-context">${c?.rank?`${c.cohort==='sim'?'仿真':'实操'}完整任务候选内 ${c.rank} / ${c.cohort_size} · DemInf 质量排序`:'未通过准入，不计分'} · 完整度不加权</div>`;
}
function curationEvidenceHTML(e){const c=e.curation||{},b=catalog.curation?.benchmark;
 return `<section class="grade-report"><h3>先准入，再评质量</h3><p>${escape(c.reason||'尚无任务准入结论')}</p><p>过程完整且任务完成的记录进入候选池，其余记录分类保存。</p>${c.rank?`<p>本任务候选内第 ${c.rank} / ${c.cohort_size}。质量分按 DemInf 三个随机种子的组内名次计算。</p><p>三次训练范围 ${(c.seed_score_range||[]).join('–')}${c.unstable?'，排序波动较大，应复核':''}。</p>`:''}<details><summary>公开高手演示对照</summary><p>RoboMimic Can 100 段高手演示的无量纲动作指标参考分布。</p>${Object.entries(c.external_comparison||{}).map(([k,v])=>`<p>${escape(({pause_fraction:'低活动时间占比',reversal_fraction:'动作反向占比',joint_path_efficiency:'关节路径直达比',speed_burst:'速度峰值比'})[k]||k)}：本段 ${v.value.toFixed(3)}；公开 P10–P90 ${v.reference.p10.toFixed(3)}–${v.reference.p90.toFixed(3)}</p>`).join('')}</details>${b?`<details><summary>公开实验与适用范围</summary><p>150 段留出成功演示中，DemInf 前四分之一高手占比 52.6%，基线 33.3%。</p><p>离线动作预测对照采用全量记录与等量子集，比较各策略的动作误差。</p></details>`:''}</section>`;
}
function ratingDetailsHTML(e) {return curationEvidenceHTML(e);}

function renderReview(id) {
  progressPanel?.destroy();
  progressPanel = null;
  page = "review";
  current = catalog.episodes.find((e) => e.id === id);
  if (!current) {
    $("#main").innerHTML =
      '<div class="empty">未找到这条记录。<a href="#library">返回工作台</a></div>';
    return;
  }
  reviewToken++;
  data = null;
  loadingData = false;
  robot?.destroy();
  robot = null;
  robotLoading = false;
  playing = false;
  framePlayer?.destroy();
  framePlayer = null;
  exactFrame = null;
  chartWindow = null;
  scrubState = null;
  chartDrag = null;
  primaryCamera = current.cameras.head
    ? "head"
    : Object.keys(current.cameras)[0];
  playhead = 0;
  trajectoryData = null;trajectoryLoading = false;activeEvidenceId=null;
  detailTab = "diagnostics";
  signalKind = "position";
  playRange = null;
  editingClip = null;
  reviewTools?.destroy();
  reviewTools = null;
  draft = copy(current.review);
  dirty = false;
  try {
    const saved = JSON.parse(localStorage.getItem("rds-draft-" + id));
    if (saved) {
      draft = saved;
      dirty = true;
    }
  } catch {}
  const e = current,
    headMode = e.head_camera_mode === "stereo_sbs" ? "crop-left" : "";
  $("#main").innerHTML =
    `${recordNavigation(e,'quality',escape)}<div class="page-head review-head"><div><h1>${escape(e.episode_id || e.name)} <span style="vertical-align:middle;margin-left:8px">${outcome(e)}</span></h1><p>${escape(e.task || "未命名任务")} · ${fmt(e.duration_s, 2)} 秒 · ${Object.keys(e.cameras).length} 路相机 · ${e.message_count.toLocaleString()} 条消息</p></div><div class="actions"><button class="small" data-action="previous">← 上一条</button><button class="small" data-action="next">下一条 →</button></div></div><div class="review-layout"><section class="review-main"><div class="panel playback-panel"><div class="player-header"><span>移动操作回放</span><div class="visual-layout-switch" role="group" aria-label="可视化布局"><button data-stage-layout="balanced" aria-pressed="true">联看</button><button data-stage-layout="motion" aria-pressed="false">3D 轨迹</button><button data-stage-layout="video" aria-pressed="false">相机</button></div>${e.cameras.head ? `<select id="head-view" aria-label="头部相机显示方式"><option value="" ${!headMode ? "selected" : ""}>完整原图</option><option value="crop-left" ${headMode ? "selected" : ""}>头部 · 左目</option><option value="crop-right">头部 · 右目</option></select>` : ""}</div><div class="camera-grid">${Object.entries(
      e.cameras,
    )
      .map(
        ([cam, c], i) =>
          `<div class="camera-card ${i === 0 ? "camera-main " + headMode : ""}" data-cam-card="${escape(cam)}"><span class="camera-label">${escape(camNames[cam] || cam)} · ${fmt(c.rate_hz, 0)} Hz</span><img data-camera="${escape(cam)}" alt="${escape(camNames[cam] || cam)} 原始图像"><span class="camera-error" hidden>当前时刻无图像</span><span class="camera-frame">RGB</span><button class="camera-expand icon-btn" data-camera-expand="${escape(cam)}" title="放大 / 还原" aria-label="放大${escape(camNames[cam] || cam)}">${icon("expand")}</button></div>`,
      )
      .join(
        "",
      )}</div>${filmstripHTML(e,headMode)}${trajectoryHTML()}<div class="transport-area">${transportHTML(e)}<div class="segment-track" id="segment-track"></div><details class="analysis-tracks" id="analysis-tracks" open><summary>问题与任务进展时间轴</summary><div id="event-timeline" class="event-timeline"></div><div id="progress-timeline" class="warp-timeline"></div></details></div><details class="clip-editor" id="clip-editor"><summary><span>${icon("crop")}保留片段</span><small id="clip-summary">整段保留</small></summary><div class="clip-tools"><span>保留范围</span><button data-action="mark-in" title="将当前时刻设为起点 [">设起点 [</button><input type="number" id="clip-start" min="0" max="${e.duration_s}" step="0.01" value="0" aria-label="片段起点（秒）"><span>—</span><input type="number" id="clip-end" min="0" max="${e.duration_s}" step="0.01" value="${fmt(e.duration_s, 6)}" aria-label="片段终点（秒）"><button data-action="mark-out" title="将当前时刻设为终点 ]">设终点 ]</button><input class="clip-label" id="clip-label" placeholder="片段名称（可选）" aria-label="片段名称"><select id="clip-grade" aria-label="片段结论">${Object.entries(grades).map(([g,label])=>`<option value="${g}" ${g==="B"?"selected":""}>${label}</option>`).join("")}</select><button class="primary" data-action="add-clip">＋ 加入</button><button id="cancel-clip-edit" class="hidden" data-action="cancel-clip-edit">取消编辑</button></div><div class="clips" id="clips"></div></details></div></section><div class="panel details-panel"><div id="rating-overview" class="rating-overview">${ratingOverviewHTML(e)}</div><div class="detail-tabs" role="tablist" aria-label="审核面板">${[
      ["diagnostics", "数据问题"],
      ["review", "保留与导出"],
    ]
      .map(
        ([id, label]) =>
          `<button class="${id === detailTab ? "active" : ""}" data-detail="${id}" role="tab" aria-selected="${id===detailTab}">${label}</button>`,
      )
      .join(
        "",
      )}<details class="detail-more"><summary>更多</summary><div class="detail-more-menu"><button data-detail="progress">历史进展分析</button><button data-detail="signals">关节曲线</button><button data-detail="streams">原始通道</button></div></details><span style="margin-left:auto;display:flex;align-items:center" id="decode-status">${cacheStatus(e)}</span></div><div class="detail-body" id="detail-body"></div><aside class="inspector" hidden><div class="inspector-fields"><div class="inspector-title"><h2>审核</h2><span id="save-state" class="save-state ${dirty ? "dirty" : ""}">${dirty ? "未保存" : draft.revision ? "已保存" : "尚未审核"}</span></div><div id="auto-grade-review" class="auto-grade-review">${gradeReviewHTML(e)}</div><label class="field-label">审核结论 <span class="muted">· 快捷键 1–4</span></label><div class="grade-picker">${Object.keys(
      grades,
    )
      .map(
        (g, i) =>
          `<button data-grade="${g}" class="grade-button ${draft.grade === g ? "selected" : ""}" aria-pressed="${draft.grade===g}" title="${grades[g]} · 快捷键 ${i+1}">${icon(reviewIcons[g])}<span>${grades[g]}</span><kbd>${i+1}</kbd></button>`,
      )
      .join(
        "",
      )}</div><p class="decision-hint">审核结论表达使用意向，数据质量等级保持独立。训练导出仍需通过预检。</p>${e.source_eligible === false ? '<details class="source-restriction"><summary>源转换限制</summary><p>源记录标记：RGB 转换尚未启用。该标记随导出保留。</p></details>' : ""}<label class="field-label" for="task-instruction">任务指令 <span class="muted">· 训练包必填</span></label><textarea id="task-instruction" rows="2" placeholder="描述具体操作目标，例如：拿起桌上的物体并放入容器">${escape(draft.instruction)}</textarea><details class="source-instruction"><summary>原始任务描述</summary><p>${escape(e.source_instruction || "未记录")}</p></details><details class="review-tags"><summary>问题标签</summary><div class="tag-list">${[...new Set([...tags, ...draft.tags])].map((t) => `<button class="tag-toggle ${draft.tags.includes(t) ? "selected" : ""}" data-tag="${escape(t)}">${escape(t)}</button>`).join("")}</div></details><label class="field-label" for="review-note">审核备注</label><textarea id="review-note" rows="2" placeholder="记录异常位置、保留原因或后续处理方式">${escape(draft.note)}</textarea><section id="review-next" class="review-next" aria-live="polite"></section></div><div class="inspector-footer"><button data-action="save">保存审核</button><button class="primary" data-action="save-next">保存并下一条 →</button></div><div class="key-help"><kbd>Space</kbd> 播放 / 暂停　<kbd>Ctrl S</kbd> 保存<br>草稿保存在本机，提交后写入审核记录</div><div style="display:flex;justify-content:space-between;margin-top:13px"><button class="text-btn" data-action="history">查看审核历史</button><button class="text-btn" data-action="discard-draft">恢复已保存标注</button></div></aside></div></div>`;
  $$("[data-camera]").forEach((img) => {
    img.onload = () =>
      (img.parentElement.querySelector(".camera-error").hidden = true);
    img.onerror = () =>
      (img.parentElement.querySelector(".camera-error").hidden = false);
  });
  if(e.snapshot){
    for(const button of $$('.inspector button,.inspector textarea,[data-detail="review"],.clip-editor button'))button.disabled=true;
    $('#clip-editor').hidden=true;
    $('#player-status').textContent='本机缓存抽帧 · 2 Hz，非原始视频';
    for(const button of $$('[data-frame-control]'))button.disabled=!Object.keys(e.cameras).length;
  }
  setStageLayout(stageLayout);
  refreshFrames();
  if(!e.snapshot)loadFramePlayer();
  renderClips();
  progressPanel = new ProgressPanel({episode:current,api,escape,toast,
    seek:t=>{setPlaying(false);playRange=null;seek(t);},
    preview:(start,end)=>{playRange={start,end};seek(start);setPlaying(true);},
    open:()=>{detailTab="progress";renderDetail();},
    propose:clip=>{openClipEditor(false);$("#clip-start").value=fmt(clip.start,6);$("#clip-end").value=fmt(clip.end,6);$("#clip-label").value=clip.label;setPlaying(false);seek(clip.start);toast("候选已填入保留范围；复核后点击“加入”并保存审核。");}
  });
  reviewTools = new ReviewTools({
    selection: updateEvidenceFocus,
    current: () => current,
    draft: () => draft,
    api,
    escape,
    toast,
    dirty: saveDraft,
    seek: (t) => {
      setPlaying(false);
      playRange = null;
      seek(t);
    },
    clips: renderClips,
    analyze: () =>
      api("/api/analyze", { ids: [current.id], rebuild: true })
        .then(refresh)
        .catch((e) => toast(e.message, true)),
    open: () => {
      detailTab = "diagnostics";
      renderDetail();
    },
    preview: (start, end) => {
      playRange = { start, end };
      seek(start);
      setPlaying(true);
    },
    signal: (event) => {
      signalKind =
        event.kind === "temperature"
          ? "temperature"
          : event.group === "left_hand"
            ? "left_hand"
            : event.group === "right_hand"
              ? "right_hand"
              : "position";
      joint = event.joint_index ?? 0;
      chartWindow = clampWindow(
        Math.max(0, event.start_s - 0.5),
        event.end_s + 0.5,
        current.duration_s,
        0.5,
      );
      detailTab = "signals";
      renderDetail();
      seek(event.peak_s);
    },
  });
  if(!e.snapshot)reviewTools.ensureLoaded();
  renderDetail();
  updateReviewStep();
  if (reviewIntent?.id === id) {
    const intent = reviewIntent;reviewIntent = null;
    requestAnimationFrame(()=>{if(current?.id===id && page==='review') applyReviewAction(intent.action);});
  }
  if (e.cache === "ready") loadSignals();
  else if (!e.snapshot && e.cache !== "building" && !["D","E"].includes(e.quality.grading?.grade))
    api("/api/analyze", { ids: [id] })
      .then(refresh)
      .catch((e) => toast(e.message, true));
}

function renderClips() {
  if (!$("#clips")) return;
  if ($("#clip-summary")) $("#clip-summary").textContent = draft.segments.length ? `${draft.segments.length} 个保留片段` : "整段保留";
  $("#clips").innerHTML = draft.segments.length
    ? draft.segments
        .map(
          (s, i) =>
            `<div class="clip-row">${badge(s.grade || draft.grade)}<span>${escape(s.label)} <span class="muted">${fmt(s.start, 2)} – ${fmt(s.end, 2)} s</span></span><button class="icon-btn" data-preview-clip="${i}" title="播放此片段" aria-label="播放此片段">${icon("play")}</button><button data-edit-clip="${i}" title="修改片段边界与等级">编辑</button><button class="icon-btn" data-remove-clip="${i}" aria-label="删除片段 ${i + 1}">${icon("close")}</button></div>`,
        )
        .join("")
    : '<div class="hint" style="font-size:10px;padding:3px 0">未设置片段时导出完整记录。添加后仅导出保留片段，区间不可重叠。</div>';
  $("#segment-track").innerHTML = draft.segments
    .map(
      (s) =>
        `<span style="left:${(s.start / current.duration_s) * 100}%;width:${((s.end - s.start) / current.duration_s) * 100}%" title="${escape(s.label)}"></span>`,
    )
    .join("");
}
function resetClipEditor() {
  editingClip = null;
  const b = $('[data-action="add-clip"]');
  if (b) b.innerHTML = icon("plus") + "添加";
  $("#cancel-clip-edit")?.classList.add("hidden");
}
function setGrade(g) {
  if(detailTab!=="review"){detailTab="review";renderDetail();}
  draft.grade = g;
  $$("[data-grade]").forEach((b) => {
    b.classList.toggle("selected", b.dataset.grade === g);
    b.setAttribute("aria-pressed", String(b.dataset.grade === g));
  });
  saveDraft();
}
function seek(t, exact = null) {
  if (!current) return;
  playhead = Math.max(0, Math.min(current.duration_s, t));
  exactFrame = exact;
  $("#timeline").value = playhead;
  $("#timecode").innerHTML =
    `${clock(playhead)} <span class="muted">/ ${clock(current.duration_s)}</span>`;
  if (robot?.solid)
    robot.pose(
      Math.min(
        data.samples - 1,
        Math.round(playhead * data.meta.timeline.rate_hz),
      ),
    );
  robot?.setTime?.(playhead);
  progressPanel?.setTime(playhead);
  updateTrajectoryReadout();
  updatePoseTimes();
  updateEvidenceFocus(reviewTools?.data?.events.find(e=>e.id===reviewTools.active));
  if($("#filmstrip"))$("#filmstrip").style.setProperty("--playhead",`${100*playhead/current.duration_s}%`);
  if($("#scene-time"))$("#scene-time").textContent=clock(playhead);
  drawChart();
  refreshFrames();
  updateFrameCounter();
}
function refreshFrames() {
  if (page !== "review" || !current) return;
  if (framePlayer?.index) {
    framePlayer.update(playhead, playing, exactFrame);
    return;
  }
  if(current.snapshot){for(const img of $$("[data-camera]")){const url=frame(current,img.dataset.camera,Math.floor(playhead*2)/2);if(img.getAttribute("src")!==url)img.src=url;}return;}
  if (playing) return;
  for (const img of $$("[data-camera]"))
    if (!img.getAttribute("src"))
      img.src = frame(current, img.dataset.camera, playhead);
  lastFrame = performance.now();
}
function primaryTimes() {
  if(current?.snapshot)return Array.from({length:Math.floor(current.duration_s*2)+1},(_,i)=>i/2);
  return framePlayer?.index?.cameras[primaryCamera]?.times_s || [];
}
function updateFrameCounter() {
  const el = $("#frame-counter");
  if (!el) return;
  const times = primaryTimes(),
    img = document.querySelector(`[data-camera="${primaryCamera}"]`);
  const shown = current?.snapshot?nearestFrame(times,playhead):img?.dataset.frameIndex;
  el.textContent = `${shown === undefined ? "—" : String(Number(shown) + 1).padStart(4, "0")} / ${String(times.length).padStart(4, "0")} 帧`;
  el.dataset.target = String(
    exactFrame?.cam === primaryCamera
      ? exactFrame.index
      : nearestFrame(times, playhead),
  );
}
function setPlaying(value) {
  if (value && (current?.snapshot?!Object.keys(current.cameras).length:(!framePlayer?.index || frameError))) {
    toast("回放尚未就绪，请等待或重试。", true);
    return;
  }
  playing = value;
  lastTick = performance.now();
  fpsStart = lastTick;
  renderedFrames = 0;
  const b = $("#play-button");
  if (b) {
    b.innerHTML = icon(playing ? "pause" : "play");
    b.setAttribute("aria-label", playing ? "暂停" : "播放");
    b.setAttribute("aria-pressed", String(playing));
  }
  const s = $("#player-status");
  if (s && !frameError) s.textContent = current?.snapshot?'缓存抽帧 · 2 Hz · '+(playing?'播放中':'就绪'):playing ? "播放中" : "就绪";
  refreshFrames();
}
async function loadFramePlayer() {
  if (!current) return;
  const token = reviewToken;
  framePlayer?.destroy();
  frameError = false;
  const player = new FramePlayer(current.id, {
    status: (message, error = false) => {
      if (token !== reviewToken) return;
      frameError = error;
      const s = $("#player-status");
      if (s) {
        s.textContent = message;
        s.classList.toggle("error", error);
      }
      $("#retry-frames")?.classList.toggle("hidden", !error);
    },
    painted: (cam) => {
      if (token !== reviewToken) return;
      if (cam === primaryCamera && playing) renderedFrames++;
      updateFrameCounter();
    },
  });
  framePlayer = player;
  player.time = playhead;
  try {
    await player.load();
    if (token !== reviewToken) return;
    for (const b of $$("[data-frame-control]")) b.disabled = false;
    updateFrameCounter();
    refreshFrames();
  } catch (e) {
    if (token === reviewToken) {
      frameError = true;
      $("#player-status").textContent = e.message;
      $("#retry-frames")?.classList.remove("hidden");
    }
  }
}
function stepFrame(direction) {
  const times = primaryTimes();
  if (!times.length) return;
  const currentIndex =
    exactFrame?.cam === primaryCamera ? exactFrame.index : null;
  const next = adjacentFrame(times, playhead, direction, currentIndex);
  if (next < 0) return;
  setPlaying(false);
  playRange = null;
  seek(times[next], { cam: primaryCamera, index: next });
}
function resetPlayback() {
  setPlaying(false);
  playRange = null;
  const times = primaryTimes();
  seek(
    times.length ? times[0] : 0,
    times.length ? { cam: primaryCamera, index: 0 } : null,
  );
}
function beginScrub(event) {
  if (!current) return;
  scrubState = { wasPlaying: playing };
  setPlaying(false);
  playRange = null;
  event.target.setPointerCapture?.(event.pointerId);
}
function endScrub() {
  if (!scrubState) return;
  const resume = scrubState.wasPlaying;
  scrubState = null;
  if (resume) setPlaying(true);
}
function transportHTML(e) {
  return `<div class="player-controls"><div class="transport-buttons"><button class="icon-btn" data-action="reset-playback" data-frame-control disabled title="回到起点 · Home" aria-label="回到起点">${icon("reset")}</button><button class="icon-btn" data-action="frame-previous" data-frame-control disabled title="上一帧 · ←" aria-label="上一帧">${icon("previous")}</button><button class="play-button icon-btn" data-action="play" id="play-button" data-frame-control disabled title="播放 / 暂停 · Space" aria-label="播放" aria-pressed="false">${icon("play")}</button><button class="icon-btn" data-action="frame-next" data-frame-control disabled title="下一帧 · →" aria-label="下一帧">${icon("next")}</button></div><span class="timecode" id="timecode">${clock(0)} / ${clock(e.duration_s)}</span><input class="timeline" id="timeline" type="range" min="0" max="${e.duration_s}" step="any" value="0" aria-label="回放时间轴"><select id="play-speed" aria-label="播放速度"><option value="0.25">0.25×</option><option value="0.5">0.5×</option><option value="1" selected>1×</option><option value="2">2×</option></select></div><div class="frame-statusbar"><label>逐帧基准 <select id="primary-camera" aria-label="逐帧基准相机">${Object.keys(
    e.cameras,
  )
    .map(
      (name) =>
        `<option value="${name}" ${name === primaryCamera ? "selected" : ""}>${camNames[name] || name}</option>`,
    )
    .join(
      "",
    )}</select></label><span id="frame-counter" class="frame-counter">— / — 帧</span><span id="player-status">读取帧索引…</span><button id="retry-frames" class="text-btn hidden" data-action="retry-frames">重试</button><button class="icon-btn" data-action="shortcut-help" title="快捷键" aria-label="快捷键">${icon("keyboard")}</button></div>`;
}
function tick(time) {
  requestAnimationFrame(tick);
  if (!playing || page !== "review") {
    lastTick = time;
    return;
  }
  const dt = Math.min((time - lastTick) / 1000, 0.25);
  lastTick = time;
  const stop = playRange?.end ?? current.duration_s;
  seek(Math.min(stop, playhead + dt * speed));
  if (time - fpsStart >= 1000) {
    if (!frameError)
      $("#player-status").textContent = current.snapshot?'缓存抽帧 · 2 Hz · 播放中':
        `播放中 · ${Math.round((renderedFrames * 1000) / (time - fpsStart))} 帧/秒`;
    fpsStart = time;
    renderedFrames = 0;
  }
  if (playhead >= (playRange?.end ?? current.duration_s)) {
    setPlaying(false);
  }
}
requestAnimationFrame(tick);

async function loadSignals() {
  if (!current || loadingData) return;
  const token = reviewToken,
    ep = current.id;
  loadingData = true;
  try {
    const loaded = await EpisodeData.load(ep);
    if (token !== reviewToken) return;
    data = loaded;
    for(const option of $('#robot-source').options)option.disabled=!data.has(option.value);
    if(!data.has($('#robot-source').value))$('#robot-source').value=[...$('#robot-source').options].find(o=>!o.disabled)?.value||'state.q';
    renderDetail();
    mountRobot();
    if(!current.snapshot)loadTrajectories();
    else $("#trajectory-status").textContent="缓存姿态回放 · 原始轨迹未导入";
  } catch (e) {
    if (token === reviewToken && $("#detail-body"))
      $("#detail-body").innerHTML =
        `<div class="empty">运动数据加载失败：${escape(e.message)}<br><button data-action="retry-signals">重试</button></div>`;
  } finally {
    if (token === reviewToken) loadingData = false;
  }
}
function renderDetail() {
  if (!$("#detail-body")) return;
  const activeTab=detailTab==='quality'?'diagnostics':detailTab;
  $$("[data-detail]").forEach((b) =>
    b.classList.toggle("active", b.dataset.detail === activeTab),
  );
  const more=$('.detail-more');
  if(more){const label={progress:'历史进展分析',signals:'关节曲线',streams:'原始通道'}[detailTab];more.classList.toggle('active',!!label);more.querySelector('summary').textContent=label||'更多';}
  const diagnostics=detailTab!=='progress';
  $('#event-timeline').hidden=!diagnostics;
  $('#progress-timeline').hidden=diagnostics;
  $('#analysis-tracks>summary').textContent=diagnostics?'质检时间轴':'任务时间轴';
  if (robot) robot.visible = stageLayout!=="video";
  const host = $("#detail-body");
  $(".details-panel").dataset.view = detailTab;
  $(".inspector").hidden = detailTab !== "review";
  host.hidden = detailTab === "review";
  $$("[data-detail][role=tab]").forEach(b=>b.setAttribute("aria-selected",String(b.dataset.detail===activeTab)));
  // The diagnostics pane installs a delegated click handler. It must not
  // intercept toolbar buttons after another pane reuses the same container.
  host.onclick = null;
  if (reviewTools) reviewTools.host = null;
  if (detailTab === "progress") {progressPanel?.mount(host);return;}
  progressPanel?.unmount();
  if (detailTab === "review") return;
  if (detailTab === "diagnostics") {
    if(current.snapshot){host.innerHTML=curationEvidenceHTML(current);return;}
    reviewTools?.mount(host);
    return;
  }
  if (detailTab === "quality") {
    if(current.snapshot){host.innerHTML=curationEvidenceHTML(current);return;}
    host.innerHTML = ratingDetailsHTML(current) + `<details class="grade-policy reference-checks"><summary>采样与数值复查 <span class="muted">· 参考检查</span></summary><div id="reference-checks-body">正在读取原始通道…</div></details><h3 class="quality-subheading">技术提醒与审核待办</h3><div class="issues">${current.quality.issues.map((i) => `<div class="issue ${i.level}"><span class="issue-icon">${icon(i.level === "error" ? "close" : "info")}</span><div><strong>${escape(i.label)}</strong><p>${escape(i.detail)}</p></div></div>`).join("") || '<div class="hint">当前规则范围内未发现异常。</div>'}</div><button class="text-btn" data-action="retry-analysis">重新运行解析</button>`;
    loadReferenceChecks();
    return;
  }
  if (detailTab === "streams") {
    const rows = data?.meta.topics || current.topics;
    host.innerHTML = `<div class="table-scroll"><table class="technical-table"><thead><tr><th>通道</th><th>消息数</th><th>Hz</th><th>最大间隔</th></tr></thead><tbody>${rows.map((t) => `<tr><td>${escape(t.topic)}</td><td>${t.count.toLocaleString()}</td><td>${fmt(t.rate_hz)}</td><td>${t.max_gap_ms == null ? "解析后可见" : fmt(t.max_gap_ms) + " ms"}</td></tr>`).join("")}</tbody></table></div>`;
    return;
  }
  if (!data) {
    host.innerHTML = `<div class="empty"><span class="spinner"></span><br>正在读取运动信号<br><span class="hint">首次解析约需 1 分钟 / 条。三路相机与人工标注现在即可使用。</span>${current.cache === "error" ? `<p>${escape(current.cache_message)}</p><button data-action="retry-analysis">重试解析</button>` : ""}</div>`;
    return;
  }
  const config = signalConfig();
  const names = data.channel(config.keys[0])?.names || [];
  joint = Math.min(joint, Math.max(0, names.length - 1));
  host.innerHTML = `<div class="chart-controls"><select id="signal-kind" aria-label="运动信号类型">${Object.entries(
    signalKinds,
  )
    .map(
      ([k, v]) =>
        `<option value="${k}" ${k === signalKind ? "selected" : ""}>${v.label}</option>`,
    )
    .join(
      "",
    )}</select><select id="joint-select" aria-label="查看关节">${names.map((n, i) => `<option value="${i}" ${i === joint ? "selected" : ""}>${String(i + 1).padStart(2, "0")} · ${escape(n)}</option>`).join("")}</select><div class="legend"><span><i style="background:var(--series-measured)"></i>实测</span>${config.keys.length > 1 ? '<span><i style="background:var(--series-command)"></i>指令</span>' : ""}</div></div>${chartToolbarHTML()}<div class="chart-wrap"><canvas class="signal-canvas" id="signal-chart" aria-label="关节实测与动作目标曲线"></canvas><canvas class="signal-overlay" id="signal-cursor"></canvas><div id="chart-selection" class="chart-selection hidden"></div><div id="chart-readout" class="chart-readout hidden"></div></div><div class="chart-foot">${config.unit} · 拖动选择时间范围，双击恢复全段 · 回放网格 100 Hz</div>`;
  drawChart();
}
const signalKinds = {
  position: { label: "关节角度", keys: ["state.q", "action.q"], unit: "rad" },
  velocity: { label: "关节速度", keys: ["state.dq"], unit: "rad/s" },
  temperature: { label: "电机温度", keys: ["state.temp"], unit: "°C" },
  effort: { label: "关节力矩", keys: ["state.tau"], unit: "N·m" },
  left_hand: {
    label: "左手闭合",
    keys: ["hand.left.state_q", "hand.left.cmd_q"],
    unit: "归一化闭合量",
  },
  right_hand: {
    label: "右手闭合",
    keys: ["hand.right.state_q", "hand.right.cmd_q"],
    unit: "归一化闭合量",
  },
};
const signalConfig = () => signalKinds[signalKind] || signalKinds.position;
function readRobotOptions(view=robot) {
  $$('[data-scene-toggle]').forEach(b=>{const on=$('#'+b.dataset.sceneToggle)?.checked;b.classList.toggle('active',!!on);b.setAttribute('aria-pressed',String(!!on));});
  if($('.target-legend'))$('.target-legend').hidden=!$('#show-targets').checked;
  if(!view)return;
  Object.assign(view.opts,{source:$('#robot-source').value,showGhost:$('#robot-overlay').checked,
    showTrails:$('#show-trails').checked,showTargets:$('#show-targets').checked,
    trailPart:$('#trail-part').value,trailSide:$('#trail-side').value,trailWindow:Number($('#trail-window').value),applyImu:false,
    showPoseTrail:$('#show-pose-trail').checked,showPast:$('#show-past').checked,showFuture:$('#show-future').checked,
    pastWindow:Number($('#past-window').value),futureWindow:Number($('#future-window').value),poseCount:Number($('#pose-count').value),
    poseOpacity:Number($('#pose-opacity').value),poseScope:$('#pose-scope').value,showGrid:$('#show-grid').checked,showJointFrames:$('#show-joint-frames').checked});
}
async function mountRobot() {
  if(!data || robotLoading || robot?.solid)return;
  const token=reviewToken,host=$('#robot-host'),episodeData=data;
  if(!host)return;
  robotLoading=true;host.dataset.ready='false';
  const valid=()=>token===reviewToken && host===$('#robot-host');
  host.innerHTML='<div class="empty"><span class="spinner"></span>加载完整 G1 模型…</div>';
  try {
    const {RobotView}=await import('./viewer/robot3d.js?v=20260916-full-model');
    const description=await RobotView.describe();if(!valid())return;
    if(!description.ok)throw Error(description.reason);
    host.innerHTML='';
    let view;
    if(rendererChoice==='compat') {
      const {SolidCanvasView}=await import('./solid-canvas.js?v=20260916-full-model');
      if(!valid())return;
      view=new SolidCanvasView(host,episodeData,description.desc);
    } else view=new RobotView(host,episodeData,{},description.desc);
    robot=view;readRobotOptions(view);await view.mount();
    if(!valid()){view.destroy();return;}
    view.resize();view.pose(Math.min(episodeData.samples-1,Math.round(playhead*episodeData.meta.timeline.rate_hz)));
    view.onSeek=t=>{setPlaying(false);playRange=null;seek(t)};
    if(trajectoryData)view.setTrajectories(trajectoryData);
    view.setTime(playhead);view.setFocus?.($('#scene-focus').value);view.visible=stageLayout!=='video';
    host.dataset.ready='true';updatePoseTimes();
    $('#robot-renderer').innerHTML=rendererChoice==='compat'?'兼容预览 <button class="text-btn" data-action="retry-robot">切回完整模型</button>':'G1 · 原始完整模型';
  } catch(error) {
    if(!valid())return;
    robot?.destroy();robot=null;
    $('#robot-renderer').textContent='完整模型未启动';
    host.innerHTML=`<div class="empty model-unavailable"><strong>完整模型暂未能显示</strong><p>完整实体需要浏览器启用 WebGL 2 图形加速。可以重试，或临时使用简化兼容预览。</p><div class="actions"><button class="primary" data-action="retry-robot">重试完整模型</button><button data-action="robot-compat">使用兼容预览</button></div><details><summary>诊断信息</summary><p>${escape(error.message)}</p></details></div>`;
  } finally {if(valid())robotLoading=false;}
}
async function loadTrajectories() {
  if(!current || trajectoryLoading || trajectoryData)return;
  const token=reviewToken;trajectoryLoading=true;
  try {
    const loaded=await api('/api/trajectories?ep='+current.id);if(token!==reviewToken)return;
    trajectoryData=loaded;if(robot?.solid){robot.setTrajectories(loaded);robot.setTime(playhead);}
    updatePoseTimes();
    const points=loaded.tracks.reduce((n,t)=>n+t.points,0);
    $('#trajectory-status').textContent=loaded.unavailable.length?`部分轨迹不可用 · ${loaded.unavailable.map(t=>t.reason).join('；')}`:`原始采样 · ${points.toLocaleString()} 个显示点`;
    $('#trajectory-status').title=loaded.note;
    updateTrajectoryReadout();if(detailTab==='quality')renderDetail();
  } catch(e) {
    if(token===reviewToken)$('#trajectory-status').innerHTML=`轨迹读取失败：${escape(e.message)} <button class="text-btn" data-action="retry-trails">重试</button>`;
  } finally {if(token===reviewToken)trajectoryLoading=false}
}
function setStageLayout(value) {
  stageLayout=['balanced','motion','video'].includes(value)?value:'balanced';
  const panel=$('.playback-panel');if(!panel)return;panel.dataset.stageLayout=stageLayout;
  if($('#analysis-tracks'))$('#analysis-tracks').open=stageLayout!=='motion';
  $$('button[data-stage-layout]').forEach(b=>{b.classList.toggle('active',b.dataset.stageLayout===stageLayout);b.setAttribute('aria-pressed',String(b.dataset.stageLayout===stageLayout));});
  if(robot)robot.visible=stageLayout!=='video';
  requestAnimationFrame(()=>{robot?.resize?.();if(robot?.solid)robot.setTime(playhead)});
}
function updatePoseTimes() {
  if(!$('#scene-pose-times'))return;
  const poses=robot?recordedGhosts(trajectoryData?.poses,playhead,robot.opts):[];
  putHTML('#scene-pose-times',poses.length?`<span>实测残影</span>${poses.map(p=>`<button class="pose-stamp ${p.direction<0?'past':'future'}" data-film-time="${p.time}" title="${p.direction<0?'历史姿态':'后续录制姿态，非预测'} ${p.time.toFixed(3)} 秒">${p.direction<0?'−':'+'}${Math.abs(p.time-playhead).toFixed(1)}s</button>`).join('')}<small>${poses.some(p=>p.direction>0)?'含后续记录 · 非预测':''}</small>`:robot?.opts.showPoseTrail?'<span>此窗口暂无完整实测残影</span>':'');
}
function updateTrajectoryReadout() {
  if(data?.has('imu.quat') && $('#base-tilt')) {
    const q=[0,1,2,3].map(i=>data.value('imu.quat',i,Math.min(data.samples-1,Math.round(playhead*data.meta.timeline.rate_hz))));
    const n=Math.hypot(...q);if(q.every(Number.isFinite)&&n>0){const [w,x,y,z]=q.map(v=>v/n);const roll=Math.atan2(2*(w*x+y*z),1-2*(x*x+y*y))*180/Math.PI,pitch=Math.asin(Math.max(-1,Math.min(1,2*(w*y-z*x))))*180/Math.PI;$('#base-tilt').textContent=`${roll.toFixed(1)}° / ${pitch.toFixed(1)}°`;}else $('#base-tilt').textContent='无有效采样';
  }
  for(const side of ['left','right']) {
    const part=$('#trail-part')?.value==='foot'?'foot':'wrist';
    const host=$('#wrist-'+side),track=trajectoryData?.tracks.find(t=>t.source==='state.q'&&t.side===side&&t.part===part);
    if($('#point-'+side+'-label'))$('#point-'+side+'-label').textContent=(side==='left'?'左':'右')+(part==='foot'?'踝':'腕');
    if(!host)continue;const point=track&&latestPoint(track,playhead);
    host.textContent=point?point.position.map(v=>v.toFixed(3)).join(' / '):'此刻无有效采样';
  }
}
function updateEvidenceFocus(event) {
  if(event?.id && event.id!==activeEvidenceId) {
    activeEvidenceId=event.id;
    const part=event.group?.includes('leg')?'foot':event.group==='waist'?'all':event.group?.includes('arm')||event.group?.includes('hand')?'wrist':null;
    if(part && $('#trail-part')) {$('#trail-part').value=part;readRobotOptions();if(robot?.solid){robot.pose(Math.min(data.samples-1,Math.round(playhead*data.meta.timeline.rate_hz)));robot.setTime(playhead);}updateTrajectoryReadout();}
  }
  if(!event)activeEvidenceId=null;
  const host=$('#scene-evidence');if(!host)return;
  host.dataset.active=String(!!event);
  host.textContent=event?`已选线索 · ${event.label} · ${event.start_s.toFixed(2)}–${event.end_s.toFixed(2)} s${playhead<event.start_s||playhead>event.end_s?" · 当前在范围外":""}`:'选择右侧线索或时间轴标记，联动画面与轨迹';
  host.title=event?.detail||'';
}
function currentWindow() {
  return chartWindow || [0, current?.duration_s || 0];
}
function setChartWindow(a, b) {
  chartWindow = clampWindow(a, b, current.duration_s);
  renderDetail();
}
function chartToolbarHTML() {
  const [a, b] = currentWindow();
  return `<div class="chart-toolbar"><div class="actions"><button class="icon-btn" data-action="chart-in" title="放大时间范围" aria-label="放大时间范围">${icon("zoomIn")}</button><button class="icon-btn" data-action="chart-out" title="缩小时间范围" aria-label="缩小时间范围">${icon("zoomOut")}</button><button class="small" data-action="chart-reset">${icon("reset")}全段</button><button class="small" data-action="chart-current">当前时刻 ±1s</button></div><span id="chart-window" data-start="${a}" data-end="${b}">${a.toFixed(3)} – ${b.toFixed(3)} s</span><button class="small" data-action="chart-to-clip">${icon("crop")}设为片段</button></div>`;
}
function chartTimeAt(clientX, bounds = currentWindow()) {
  const r = $("#signal-chart").getBoundingClientRect();
  return (
    bounds[0] +
    Math.max(0, Math.min(1, (clientX - r.left - 42) / (r.width - 54))) *
      (bounds[1] - bounds[0])
  );
}
function beginChartDrag(e) {
  if (!data) return;
  setPlaying(false);
  chartDrag = {
    x: e.clientX,
    time: chartTimeAt(e.clientX),
    bounds: [...currentWindow()],
  };
  e.target.setPointerCapture?.(e.pointerId);
  e.preventDefault();
}
function moveChartDrag(e) {
  const canvas = $("#signal-chart");
  if (!canvas) {
    chartDrag = null;
    return;
  }
  const r = canvas.getBoundingClientRect(),
    a = Math.max(42, Math.min(r.width - 12, chartDrag.x - r.left)),
    b = Math.max(42, Math.min(r.width - 12, e.clientX - r.left));
  const el = $("#chart-selection");
  el.classList.remove("hidden");
  el.style.left = Math.min(a, b) + "px";
  el.style.width = Math.abs(a - b) + "px";
}
function endChartDrag(e) {
  const drag = chartDrag;
  chartDrag = null;
  $("#chart-selection")?.classList.add("hidden");
  if (!drag || !$("#signal-chart")) return;
  const t = chartTimeAt(e.clientX, drag.bounds);
  if (Math.abs(e.clientX - drag.x) > 5) {
    setChartWindow(drag.time, t);
    seek(Math.min(drag.time, t));
  } else seek(t);
}
function drawChart() {
  const canvas = $("#signal-chart"),
    cursor = $("#signal-cursor");
  if (!canvas || !cursor || !data) return;
  const width = canvas.clientWidth,
    height = canvas.clientHeight;
  if (!width) return;
  const dpr = window.devicePixelRatio || 1,
    css = getComputedStyle(document.documentElement),
    tone = (k) => css.getPropertyValue(k).trim();
  const [start, end] = currentWindow(),
    pad = { l: 42, r: 12, t: 12, b: 24 },
    w = width - pad.l - pad.r,
    h = height - pad.t - pad.b;
  const key = [
    current.id,
    signalKind,
    joint,
    start,
    end,
    width,
    height,
    dpr,
    document.documentElement.dataset.theme,
  ].join("|");
  if (canvas.dataset.renderKey !== key) {
    canvas.dataset.renderKey = key;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    const c = canvas.getContext("2d");
    c.scale(dpr, dpr);
    const stepS = data.meta.timeline.step_ns / 1e9,
      first = Math.max(0, Math.floor(start / stepS)),
      last = Math.min(data.samples - 1, Math.ceil(end / stepS));
    const series = signalConfig().keys.map((k) => data.series(k, joint));
    let lo = Infinity,
      hi = -Infinity;
    for (const values of series)
      if (values)
        for (let i = first; i <= last; i++)
          if (Number.isFinite(values[i])) {
            lo = Math.min(lo, values[i]);
            hi = Math.max(hi, values[i]);
          }
    c.font = "11px ui-monospace,monospace";
    c.lineWidth = 1;
    if (!Number.isFinite(lo)) {
      c.fillStyle = tone("--muted");
      c.fillText("所选范围无有效数值", 45, 60);
    } else {
      if (hi - lo < 0.02) {
        hi += 0.01;
        lo -= 0.01;
      }
      const margin = (hi - lo) * 0.1;
      lo -= margin;
      hi += margin;
      for (let i = 0; i < 4; i++) {
        const y = pad.t + (h * i) / 3;
        c.strokeStyle = tone("--chart-grid");
        c.beginPath();
        c.moveTo(pad.l, y);
        c.lineTo(width - pad.r, y);
        c.stroke();
        c.fillStyle = tone("--muted");
        c.fillText((hi - ((hi - lo) * i) / 3).toFixed(2), 1, y + 3);
      }
      for (let i = 0; i <= 5; i++) {
        const x = pad.l + (w * i) / 5;
        c.fillText(
          (start + ((end - start) * i) / 5).toFixed(end - start < 2 ? 2 : 1),
          x - 10,
          height - 5,
        );
      }
      series.forEach((values, j) => {
        if (!values) return;
        c.strokeStyle = [tone("--series-measured"), tone("--series-command")][
          j
        ];
        c.lineWidth = 1.4;
        c.beginPath();
        let started = false;
        const skip = Math.max(1, Math.floor((last - first) / w / 2));
        for (let i = first; i <= last; i += skip) {
          if (!Number.isFinite(values[i])) {
            started = false;
            continue;
          }
          const x = pad.l + ((i * stepS - start) / (end - start)) * w,
            y = pad.t + ((hi - values[i]) / (hi - lo)) * h;
          if (started) c.lineTo(x, y);
          else {
            c.moveTo(x, y);
            started = true;
          }
        }
        c.stroke();
      });
    }
  }
  if (cursor.width !== width * dpr || cursor.height !== height * dpr) {
    cursor.width = width * dpr;
    cursor.height = height * dpr;
  }
  const overlay = cursor.getContext("2d");
  overlay.setTransform(dpr, 0, 0, dpr, 0, 0);
  overlay.clearRect(0, 0, width, height);
  if (playhead >= start && playhead <= end) {
    const x = pad.l + ((playhead - start) / (end - start)) * w;
    overlay.strokeStyle = tone("--green");
    overlay.setLineDash([3, 3]);
    overlay.beginPath();
    overlay.moveTo(x, pad.t);
    overlay.lineTo(x, height - pad.b);
    overlay.stroke();
  }
}

function dialog(title, body, actions) {
  setPlaying(false);
  $("#dialog-content").innerHTML =
    `<div class="dialog-title"><h2>${title}</h2><button data-action="close-dialog" aria-label="关闭对话框">×</button></div><div class="dialog-body">${body}</div><div class="form-error" id="dialog-error" role="alert"></div><div class="dialog-actions"><button data-action="close-dialog">取消</button>${actions}</div>`;
  $("#dialog").showModal();
}
function importDialog() {
  dialog(
    "添加本地数据",
    `<p>选择包含 MCAP 文件的本机目录。工具会自动识别记录和旁边的元数据，也支持单个 .mcap 文件。</p><label class="field-label" for="import-path">本机目录或 MCAP 路径</label><input id="import-path" placeholder="/home/…/recordings" autocomplete="off"><p>导入只建立索引；质检缓存和人工标注存放在独立工作空间。</p>`,
    `<button class="primary" data-action="confirm-import">扫描并导入</button>`,
  );
  $("#import-path").focus();
}
function batchDialog() {
  if([...selected].some(id=>catalog.episodes.find(e=>e.id===id)?.snapshot)){toast('所选含只读证据快照，请导入原始文件后保存审核。',true);return;}
  dialog(
    "批量设置审核结论",
    `<p>为已选的 ${selected.size} 条记录设置审核结论，原有任务指令、标签和片段保留不变。每条修改都会写入审核历史。</p><label class="field-label">审核结论</label><select id="batch-grade">${Object.entries(
      grades,
    )
      .map(
        ([g, s]) =>
          `<option value="${g}" ${g === "C" ? "selected" : ""}>${s}</option>`,
      )
      .join("")}</select>`,
    `<button class="primary" data-action="confirm-batch">保存 ${selected.size} 条结论</button>`,
  );
}
let exportIds = [],
  preflightToken = 0;
function reviewWording(text) {
  return String(text).replaceAll('人工等级需为 A 或 B','审核结论需为“通过”或“处理后保留”').replaceAll('待人工分级','待确认审核结论').replaceAll('人工等级未纳入训练','当前审核结论未纳入训练').replaceAll('没有 A / B 级保留片段','没有可纳入训练的保留片段');
}
function exportOptions() {
  return {
    ids: exportIds,
    kind: $('input[name="export-kind"]:checked').value,
    fps: Number($("#export-fps").value),
    validation_ratio: Number($("#export-ratio").value),
    seed: 42,
    progress: progressExportOptions(),
  };
}
async function checkExport() {
  const token = ++preflightToken,
    host = $("#preflight-result"),
    button = $('[data-action="confirm-export"]');
  if (!host || !button) return;
  button.disabled = true;
  host.innerHTML = '<span class="spinner"></span> 正在检查全部所选记录…';
  try {
    const report = await api("/api/preflight", exportOptions());
    if (token !== preflightToken || !host.isConnected) return;
    host.innerHTML = `<div class="preflight-title ${report.ready ? "ok" : "blocked"}">${icon(report.ready?'check':'warning')}${report.ready ? "导出前检查通过" : "需要先处理以下项目"}</div>${report.kind === "dataset" ? `<p>预计 ${report.samples.toLocaleString()} 个采样时刻，其中 ${report.aligned_samples.toLocaleString()} 个满足数值与时间覆盖。</p>` : ""}${report.records.map((r) => `<div class="preflight-row"><div class="preflight-record-head"><b>${escape(r.name)}</b>${r.blockers.length?`<button class="small" data-preflight-review="${r.id}">${icon('right')}去完善</button>`:'<span class="preflight-ok">已通过预检</span>'}</div>${r.blockers.map((s) => `<div class="preflight-blocker">${icon('warning')}${escape(reviewWording(s))}</div>`).join("")}${r.progress ? `<p>进展覆盖 ${r.progress.covered_samples} 帧 · 完整动作块 ${r.progress.eligible_anchors} 个 · 保留 ${r.progress.retained_anchors} 个</p>` : ""}${r.warnings.map((s) => `<div class="preflight-warning">${escape(reviewWording(s))}</div>`).join("")}</div>`).join("")}<small>${escape(report.note)}</small>`;
    button.disabled = !report.ready;
  } catch (e) {
    if (token === preflightToken && host.isConnected)
      host.textContent = e.message;
  }
}
function exportDialog(ids, preferredKind = null) {
  exportIds =
    ids ||
    catalog.episodes
      .filter((e) => ["A", "B"].includes(e.review.grade) && !e.review_stale)
      .map((e) => e.id);
  if (!exportIds.length) {
    toast("请先选择记录，或保存至少一条“通过 / 处理后保留”的审核结论。", true);
    return;
  }
  if(exportIds.some(id=>catalog.episodes.find(e=>e.id===id)?.snapshot)){
    const rows=exportIds.map(id=>catalog.episodes.find(e=>e.id===id)).filter(Boolean);
    const eligible=rows.filter(e=>['A','B','C'].includes(e.quality.grading?.grade));
    dialog('导出质量筛选清单',`<p>已选 ${rows.length} 条，合格候选 ${eligible.length} 条，筛出或待准入 ${rows.length-eligible.length} 条。</p><p>导出评分与记录清单，按任务及仿真、实操数据域分别列出。训练包在原始录制导入后生成。</p>`, '<button class="primary" data-action="download-curation">下载 JSON 清单</button>');
    return;
  }
  const allApproved = exportIds.every((id) =>
    ["A", "B"].includes(
      catalog.episodes.find((e) => e.id === id)?.review.grade,
    ),
  );
  const datasetSelected = preferredKind ? preferredKind === "dataset" : allApproved;
  dialog(
    "导出预检",
    `<p>已选择 <b>${exportIds.length}</b> 条记录。导出使用已保存的标注，浏览器草稿不会进入数据包。</p><label class="format-card"><input type="radio" name="export-kind" value="manifest" ${!datasetSelected ? "checked" : ""}> 筛选清单 · JSON<p>包含原始路径、质检依据、分级和片段，无需复制大文件。</p></label><label class="format-card"><input type="radio" name="export-kind" value="dataset" ${datasetSelected ? "checked" : ""}> 通用训练包 · NPZ + JPEG<p>41 维状态 / 动作、三路图像、时间戳和有效性掩码。仅纳入审核为“通过 / 处理后保留”的记录。</p></label><div style="display:grid;grid-template-columns:1fr 1fr;gap:15px"><div><label class="field-label">目标采样率</label><select id="export-fps">${[10, 20, 30, 50, 100].map((n) => `<option ${n === 30 ? "selected" : ""} value="${n}">${n} Hz</option>`).join("")}</select></div><div><label class="field-label">验证集目标比例</label><select id="export-ratio"><option value="0.2">20%</option><option value="0.1">10%</option><option value="0">全部训练集</option></select></div></div><p>训练包需先完成深度质检并填写具体任务指令。同一源文件的所有片段分配到同一集合，小样本比例可能偏离目标。图像保留原始尺寸。</p>`,
    `<button class="primary" data-action="confirm-export">开始导出 ↗</button>`,
  );
  $("#dialog-content .dialog-body").insertAdjacentHTML(
    "beforeend",
    '<div id="preflight-result" class="preflight-result"></div>',
  );
  checkExport();
  const progressHost=document.createElement("div");
  $("#preflight-result").before(progressHost);
  mountProgressExport(progressHost,api,escape,checkExport).catch(e=>{if(progressHost.isConnected)progressHost.textContent=e.message;});
}
async function saveReview(next = false) {
  if (!current) return;
  if(current.snapshot){toast('当前为只读证据快照，请先导入原始文件。',true);return;}
  const ep = current.id,
    snapshot = copy(draft);
  const result = await api("/api/reviews", {
    changes: [{ id: ep, review: snapshot }],
  });
  if (!current || current.id !== ep) {
    localStorage.removeItem("rds-draft-" + ep);
    await refresh();
    toast("标注已保存。");
    return;
  }
  current.review = result.reviews[ep];
  if (JSON.stringify(draft) === JSON.stringify(snapshot)) {
    draft = copy(current.review);
    dirty = false;
    localStorage.removeItem("rds-draft-" + ep);
    $("#save-state").textContent = "已保存";
    $("#save-state").className = "save-state";
  } else {
    draft.revision = current.review.revision;
    saveDraft();
  }
  toast("标注已保存，审核历史已记录。");
  await refresh();
  reviewTools?.render();
  reviewTools?.renderTimeline();
  if (next) goAdjacent(1);
}
function goAdjacent(delta) {
  if (!current) return;
  playing = false;
  const rows = filtered(),
    i = rows.findIndex((e) => e.id === current.id),
    next = rows[i + delta];
  if (next) location.hash = "review/" + next.id;
  else toast(delta > 0 ? "已经是最后一条记录。" : "已经是第一条记录。");
}
async function renderRules() {
  page = "rules";
  const r = await api("/api/rules");
  if (page !== "rules") return;
  const levels=[['A','优先候选','完整任务候选内前约 25%'],['B','常规候选','随后约 25%'],['C','低优先候选','其余完整任务候选'],['D','已筛出','任务未完成，不参与质量评分'],['E','已筛出','任务过程不完整，不参与质量评分'],['R','待准入复核','证据不够，不参与评分'],['U','待任务识别','尚无适用任务与模型']];
  $('#main').innerHTML=`<div class="page-head"><div><h1>数据质量分级</h1><p>先检查过程完整性与任务结果，再对同任务候选进行排序。</p></div></div><section class="panel padded"><div class="grade-standard-list">${levels.map(([g,t,d])=>`<article class="grade-standard"><span class="grade-code">${g}</span><div><h3>${t}</h3><p>${d}</p></div></article>`).join('')}</div><p>评分使用DemInf学习的状态—动作信息；A、B、C表示同任务候选的相对选择优先级。</p><p>${escape(catalog.curation?.benchmark?.selection_efficacy||'尚未建立本任务基准')}</p></section>`;
}

function renderExports() {
  page = "exports";
  const ready = catalog.episodes.filter(e=>workflowState(e).queue==='preflight').length;
  const todo = catalog.episodes.filter(e=>workflowState(e).queue==='review').length;
  const complete = catalog.episodes.filter(e=>workflowState(e).queue==='complete').length;
  $("#main").innerHTML = `<div class="page-head"><div><h1>导出中心</h1><p>先检查所选记录，再创建数据包。</p></div><button class="primary" data-action="new-export">创建导出</button></div>
  <section class="panel export-readiness"><div><h2>${icon('export')}导出准备</h2><p>可预检 ${ready} 条 · 待复核 ${todo} 条 · 待完善 ${complete} 条</p><span class="muted">预检将逐项检查图像完整性、时间区间和导出输入。</span></div><div class="actions"><button data-queue-nav="review">${icon('search')}继续复核</button><button data-queue-nav="preflight">${icon('list')}查看可预检记录</button></div></section>
  <section class="panel"><div class="panel-head"><h2>导出任务</h2></div><div id="export-list"><div class="empty">读取导出任务…</div></div></section>
  <details class="panel export-format-details"><summary>${icon('info')}数据包内容与使用约定</summary><p>通用训练包包含 NPZ 状态 / 动作、原始 JPEG 图像、JSON 审核和来源信息。有效性掩码标明可用时刻；训练序列不得跨越无效区间。</p><p>接入训练模型时，按目标接口配置字段、单位与预处理。</p></details>`;
  loadExports();
}
async function loadExports() {
  try {
    const { exports: list } = await api("/api/exports");
    if (!$("#export-list")) return;
    $("#export-list").innerHTML = list.length
      ? list
          .map(
            (e) =>
              `<div class="export-card"><div class="export-icon">⇧</div><div class="export-desc"><strong>${escape(e.id)}</strong><p>${e.state === "done" ? (e.kind === "manifest" || (!e.kind && !e.samples) ? `筛选清单 · ${e.episodes} 条记录 · ${size(e.size_bytes)}` : `训练包 · ${e.episodes} 条记录 · ${e.samples.toLocaleString()} 个样本 / ${e.valid_samples.toLocaleString()} 个有效样本 · ${size(e.size_bytes)}`) : escape(e.message)}</p>${e.state === "running" || e.state === "queued" ? `<div class="export-progress"><span style="width:${e.progress}%"></span></div>` : ""}</div>${e.state === "done" ? `<a class="subtle-link" href="/api/download?file=${encodeURIComponent(e.file)}" download>下载 ZIP ↗</a>` : e.state === "error" ? '<span class="badge failure">导出失败</span>' : '<span class="spinner"></span>'}</div>`,
          )
          .join("")
      : '<div class="empty"><strong>暂无导出任务</strong>在工作台选择记录导出筛选清单，或保存“通过 / 处理后保留”结论后创建训练包。</div>';
  } catch (e) {
    toast(e.message, true);
  }
}
function renderGuide() {
  page = "guide";
  $("#main").innerHTML =
    `<div class="page-head"><div><h1>从采集记录到训练数据</h1><p>第一次使用，按这五步完成一轮筛选。</p></div></div><section class="panel guide">${[
      [
        "认识这批数据",
        "样例包含G1身体关节、双手、三路RGB相机和遥操作参考。导出前依次检查采集标记、人工审核与片段质量。",
      ],
      [
        "查看任务与技术质检",
        "进入记录后，相机、3D 和联看共用播放器与时间轴。右侧“完成条件、人工复核”核对 VLM 的目标判断和每次尝试。点击“MiniMax 审核”选择范本并提交。数据工作台按已分析阶段的未完成尝试、证据不足和人工保留结论筛选；局部结果不代表整条任务已审核。",
      ],
      [
        "同步回放并保留片段",
        "用时间轴回放头部和左右腕图像。在“质检”定位采样中断、无效数值、关节偏差等异常；“更多”中可查看关节曲线和原始通道。上方可切换联看、3D 轨迹或相机。任务片段的“回看”会播放前后上下文；“填入审核范围”仅填写草稿。也可用 [ / ] 设置起止时刻，点击“加入”保留片段，再到“审核”保存。片段至少 0.1 秒且不能重叠。",
      ],
      [
        "填写任务指令，确认审核结论",
        "打开右侧“审核”标签。任务指令应描述具体移动与操作目标，不要使用泛化的系统验证说明。选择通过、处理后保留、待复核或排除，记录问题标签和备注后保存。变更记录可在审核历史中查看；未保存草稿只留在当前浏览器。左上角可收起或展开侧栏，所有页面保持该选择；右上角可切换明暗主题。问题支持技术优先排序、连续判断和当前筛选的批量判断，已有结论不会被批量覆盖。",
      ],
      [
        "导出并接入训练",
        "筛选清单适合整理和转交。通用训练包需要先完成通过或处理后保留的审核结论与深度质检，包含 samples.npz、图像、images.jsonl 和 manifest.json。状态 41 维 = 身体 29 + 左手 6 + 右手 6；动作同维度。使用 valid 掩码筛除无效样本；序列训练必须按连续有效区间采样。头部双目图像保留原始拼接，缩放、裁剪和归一化按目标模型进行。",
      ],
    ]
      .map(
        ([h, p], i) =>
          `<div class="guide-step"><span class="guide-number">${i + 1}</span><div><h2>${h}</h2><p>${p}</p></div></div>`,
      )
      .join(
        "",
      )}<div class="padded hint">工作空间：${escape(catalog.workspace)}<br>审核数据库：reviews.sqlite3 · 派生缓存：cache/ · 导出：exports/<br>备份审核结果时可导出筛选清单；完整工作空间备份请先停止服务，再复制目录。<br>公开参考：<a class="subtle-link" href="https://github.com/huggingface/lerobot" target="_blank" rel="noreferrer">LeRobot ↗</a> · <a class="subtle-link" href="https://github.com/ARISE-Initiative/robomimic" target="_blank" rel="noreferrer">robomimic ↗</a></div></section>`;
}

function selectCandidateRows(priorityOnly){
  const ids=selectCandidates(filtered(),priorityOnly);
  selected.clear();for(const id of ids)selected.add(id);
  updateLibrary();
  toast(ids.length?`已选择 ${ids.length} 条${priorityOnly?'优先':'合格'}候选，可导出清单。`:'当前筛选范围没有合格候选。',!ids.length);
}
const actions = {
  'select-qualified':()=>selectCandidateRows(false),
  'select-priority':()=>selectCandidateRows(true),
  "chart-in": () => {
    const w = currentWindow(),
      anchor = Math.max(w[0], Math.min(w[1], playhead));
    chartWindow = zoomWindow(w, anchor, 0.5, current.duration_s);
    renderDetail();
  },
  "chart-out": () => {
    const w = currentWindow();
    chartWindow = zoomWindow(w, (w[0] + w[1]) / 2, 2, current.duration_s);
    renderDetail();
  },
  "chart-reset": () => {
    chartWindow = null;
    renderDetail();
  },
  "chart-current": () => setChartWindow(playhead - 1, playhead + 1),
  "chart-to-clip": () => {
    const [a, b] = currentWindow();
    $("#clip-start").value = a.toFixed(6);
    $("#clip-end").value = b.toFixed(6);
    toast("已填入片段范围，请确认等级后添加。");
  },
  "retry-frames": loadFramePlayer,
  "frame-previous": () => stepFrame(-1),
  "frame-next": () => stepFrame(1),
  "reset-playback": resetPlayback,
  "shortcut-help": () =>
    dialog(
      "快捷键",
      '<div class="shortcut-list"><p><kbd>Space</kbd> 播放 / 暂停</p><p><kbd>←</kbd> <kbd>→</kbd> 按主相机的真实帧前后移动</p><p><kbd>Home</kbd> 暂停并回到起点</p><p><kbd>Ctrl</kbd> + <kbd>\\</kbd> 展开 / 收起侧栏</p><p><kbd>N</kbd> <kbd>P</kbd> 下一 / 上一未复核项</p><p><kbd>[</kbd> <kbd>]</kbd> 设置片段起止时间</p><p><kbd>Ctrl S</kbd> 保存标注</p><p>拖动曲线选择时间范围；双击曲线恢复全段。</p></div>',
      "",
    ),
  theme: () => {
    const next =
      document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("robocurate-theme", next);
    } catch {}
    updateThemeLabel();
    drawChart();
    robot?.applyTheme?.();
  },
  "toggle-sidebar": toggleSidebar,
  import: importDialog,
  "rescan-sources": async () => {
    const button = $("#source-refresh");
    if (button) {
      button.disabled = true;
      button.dataset.busy = "1";
    }
    try {
      const r = await api("/api/roots/rescan", {});
      await refresh();
      const changes = [
        r.added ? `新增 ${r.added} 条` : "",
        r.removed ? `移除 ${r.removed} 条` : "",
      ].filter(Boolean);
      toast(
        `已重新扫描 ${r.roots.length} 个数据目录：${changes.join(" · ") || "没有变化"}。` +
          (r.missing.length ? ` ${r.missing.length} 个目录不可用。` : ""),
        r.missing.length > 0,
      );
    } finally {
      if (button) {
        button.disabled = false;
        delete button.dataset.busy;
      }
    }
  },
  "close-dialog": () => $("#dialog").close(),
  "confirm-import": async () => {
    const button = $('[data-action="confirm-import"]');
    button.disabled = true;
    try {
      const r = await api("/api/roots", { path: $("#import-path").value });
      $("#dialog").close();
      await refresh();
      location.hash = "library";
      renderLibrary();
      toast(`已识别 ${r.added} 条记录。`);
    } finally {
      button.disabled = false;
    }
  },
  retry: async () => {
    await refresh();
    renderLibrary();
  },
  analyze: async () => {
    await api("/api/analyze", { ids: catalog.episodes.filter(e=>!e.snapshot).map((e) => e.id) });
    toast("深度质检已加入队列，可继续审核。");
    refresh();
  },
  "analyze-selected": async () => {
    const ids=[...selected].filter(id=>!catalog.episodes.find(e=>e.id===id)?.snapshot);
    if(!ids.length){toast('证据快照不能重新解析，请先导入原始文件。',true);return;}
    await api("/api/analyze", { ids });
    toast("所选记录已加入质检队列。");
    refresh();
  },
  "retry-analysis": async () => {
    if(current.snapshot){toast('证据快照不能重新解析，请先导入原始文件。',true);return;}
    await api("/api/analyze", { ids: [current.id], rebuild: true });
    toast("已请求重新解析。");
    refresh();
  },
  "retry-signals": () => loadSignals(),
  "clear-selection": () => {
    selected.clear();
    updateLibrary();
  },
  "batch-grade": batchDialog,
  "confirm-batch": async () => {
    const changes = [...selected].map((id) => ({
      id,
      review: {
        revision: catalog.episodes.find((e) => e.id === id).review.revision,
        grade: $("#batch-grade").value,
      },
    }));
    await api("/api/reviews", { changes });
    $("#dialog").close();
    await refresh();
    toast(`已保存 ${changes.length} 条审核结论。`);
  },
  "export-selected": () => exportDialog([...selected]),
  "download-curation": () => {
    const rows=exportIds.map(id=>catalog.episodes.find(e=>e.id===id)).filter(Boolean);
    const item=e=>({id:e.id,name:e.name,source_path:e.path,source_sha256:e.curation?.source_sha256,cohort:e.curation?.cohort||'unknown',grade:e.quality.grading.grade,score:e.quality.rating.score,reason:e.quality.grading.summary,snapshot:!!e.snapshot});
    const result={version:catalog.curation?.version||'curation-v2-admission-first',completeness_scored:false,external_quality_certified:false,includes_raw_data:false,episodes:rows.filter(e=>['A','B','C'].includes(e.quality.grading.grade)).map(item),excluded:rows.filter(e=>!['A','B','C'].includes(e.quality.grading.grade)).map(item)};
    const url=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'}));
    const a=document.createElement('a');a.href=url;a.download='RoboCurate-quality-selection.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    $('#dialog').close();toast(`已导出 ${result.episodes.length} 条候选，另列 ${result.excluded.length} 条筛出或待准入记录。`);
  },
  "new-export": () => exportDialog(selected.size ? [...selected] : undefined),
  "confirm-export": async () => {
    const r = await api("/api/exports", exportOptions());
    $("#dialog").close();
    location.hash = "exports";
    toast("导出任务已创建。");
  },
  previous: () => goAdjacent(-1),
  next: () => goAdjacent(1),
  play: () => {
    if (playRange) playRange = null;
    if (playhead >= current.duration_s) seek(0);
    setPlaying(!playing);
  },
  "mark-in": () => {openClipEditor(false);$("#clip-start").value = fmt(playhead, 6);},
  "mark-out": () => {openClipEditor(false);$("#clip-end").value = fmt(playhead, 6);},
  "cancel-clip-edit": resetClipEditor,
  "add-clip": () => {
    const start = Number($("#clip-start").value),
      end = Number($("#clip-end").value);
    if (
      !Number.isFinite(start + end) ||
      start < 0 ||
      end > current.duration_s + 0.001 ||
      end - start < 0.1
    )
      throw Error("片段必须在记录范围内，时长至少 0.1 秒。");
    if (
      draft.segments.some(
        (s, i) => i !== editingClip && start < s.end && end > s.start,
      )
    )
      throw Error("该片段与已有保留片段重叠，请调整起止时间。");
    const clip = {
      start,
      end: Math.min(end, current.duration_s),
      label:
        $("#clip-label").value.trim() || `片段 ${draft.segments.length + 1}`,
      grade:
        $("#clip-grade")?.value ||
        (["A", "B"].includes(draft.grade) ? draft.grade : "B"),
    };
    if (editingClip === null) draft.segments.push(clip);
    else draft.segments[editingClip] = clip;
    draft.segments.sort((a, b) => a.start - b.start);
    saveDraft();
    renderClips();
    resetClipEditor();
    toast("保留片段已加入草稿，请保存标注。");
  },
  save: () => saveReview(),
  "save-next": () => saveReview(true),
  "show-quality": revealQuality,
  "open-clips": () => openClipEditor(),
  "review-instruction": () => applyReviewAction("instruction"),
  "review-problems": () => applyReviewAction("review"),
  "clear-filters": () => {resetBrowseFilters();syncFilters();updateLibrary();},
  "workflow-next": async () => {
    if (workflowBusyFor === current.id) return;
    const ep = current.id;
    const step = nextReviewStep(current,draft,dirty);
    if (step.disabled) return;
    workflowBusyFor = ep;
    updateReviewStep();
    try {
      if (step.action === "save") await saveReview();
      else await openWorkflow(current,step.action);
    } finally {
      if (workflowBusyFor === ep) workflowBusyFor = null;
      updateReviewStep();
    }
  },
  "discard-draft": () => {
    localStorage.removeItem("rds-draft-" + current.id);
    renderReview(current.id);
    toast("已恢复服务器上保存的标注。");
  },
  history: async () => {
    const r = await api("/api/history?ep=" + current.id);
    dialog(
      "审核历史",
      r.history.length
        ? r.history
            .map(
              (h) =>
                `<div class="history-row"><b>版本 ${h.after.revision} · ${grades[h.after.grade] || "未审核"}</b><br>${escape(new Date(h.at).toLocaleString())}<br>${escape(h.after.instruction || "未填写任务指令")}<br>${escape(h.after.note || "无备注")} · ${h.after.segments.length} 个保留片段 · ${Object.keys(h.after.event_decisions || {}).length} 处问题判断<br><button class="small" data-restore-review="${h.seq}" ${dirty ? 'disabled title="请先保存当前草稿"' : ""}>恢复为此版本</button></div>`,
            )
            .join("")
        : "<p>这条记录还没有已保存的人工审核。</p>",
      "",
    );
  },
  "save-rules": async () => {
    const rules = Object.fromEntries(
      $$("[data-rule]").map((i) => [i.dataset.rule, Number(i.value)]),
    );
    await api("/api/rules", { rules });
    toast("规则已保存，质量建议已更新。");
    refresh();
  },
  "reset-rules": async () => {
    const r = await api("/api/rules");
    for (const input of $$("[data-rule]"))
      input.value = r.defaults[input.dataset.rule];
    toast("已填入默认值，点击保存规则后生效。");
  },
  "robot-fit": () => robot?.fitView?.(),
  "robot-reset": () => {robot?.setView("iso");if($("#robot-view"))$("#robot-view").value="iso";},
  "retry-robot": () => {rendererChoice="full";robot?.destroy();robot=null;mountRobot();},
  "robot-compat": () => {rendererChoice="compat";robot?.destroy();robot=null;mountRobot();},
  "retry-trails": () => loadTrajectories(),
};
document.addEventListener("click", async (e) => {
  try {
    if(e.target.closest('[data-nav]') && innerWidth<=760 && document.documentElement.dataset.sidebar==='expanded') setSidebarCollapsed(true);
    const queueNav = e.target.closest('[data-queue-nav]');
    if (queueNav) {
      resetBrowseFilters();filters.queue=queueNav.dataset.queueNav;
      if(page==='library'){syncFilters();updateLibrary();}else location.hash='library';return;
    }
    const qualityFilter = e.target.closest('[data-quality-filter]');
    if (qualityFilter) {chooseOverviewFilter('auto',qualityFilter.dataset.qualityFilter);return;}
    const queueFilter = e.target.closest('[data-queue-filter]');
    if (queueFilter) {chooseOverviewFilter('queue',queueFilter.dataset.queueFilter);return;}
    if(e.target.closest('[data-open-templates]')){await openTemplateManager();return;}
    const workflow = e.target.closest('[data-workflow-open]');
    if (workflow) {
      const record = catalog.episodes.find(r=>r.id===workflow.dataset.workflowOpen);
      if(record) await openWorkflow(record);return;
    }
    const evidence = e.target.closest('[data-grade-evidence]');
    if (evidence) {await locateGradeEvidence(evidence.dataset.gradeEvidence);return;}
    const repair = e.target.closest('[data-preflight-review]');
    if (repair) {
      preflightToken++;$('#dialog').close();
      const record=catalog.episodes.find(r=>r.id===repair.dataset.preflightReview);
      if(record) await openWorkflow(record,workflowState(record).queue==='complete'?'instruction':workflowState(record).queue==='excluded'?'inspect':'review');return;
    }
    const camera = e.target.closest("[data-camera-expand]");
    if (camera) {
      const grid = $(".camera-grid"),
        cam = camera.dataset.cameraExpand,
        on = grid.dataset.expanded !== cam;
      if (on) {
        grid.dataset.expanded = cam;
        primaryCamera = cam;
        $("#primary-camera").value = cam;
      } else delete grid.dataset.expanded;
      $$("[data-cam-card]").forEach((c) => {
        const enlarged = on && c.dataset.camCard === cam;
        c.classList.toggle("enlarged", enlarged);
        c.querySelector("[data-camera-expand]").innerHTML = icon(
          enlarged ? "compress" : "expand",
        );
      });
      updateFrameCounter();
      return;
    }
    const restore = e.target.closest("[data-restore-review]");
    if (restore) {
      const ep = current.id;
      const result = await api("/api/reviews/restore", {
        ep,
        revision: draft.revision,
        seq: Number(restore.dataset.restoreReview),
      });
      current.review = result.reviews[ep];
      localStorage.removeItem("rds-draft-" + ep);
      $("#dialog").close();
      await refresh();
      renderReview(ep);
      toast("已恢复历史标注，并新增一条审核记录。");
      return;
    }
    const edit = e.target.closest("[data-edit-clip]");
    if (edit) {
      openClipEditor(false);
      editingClip = Number(edit.dataset.editClip);
      const s = draft.segments[editingClip];
      $("#clip-start").value = s.start;
      $("#clip-end").value = s.end;
      $("#clip-label").value = s.label;
      $("#clip-grade").value = s.grade || "B";
      $('[data-action="add-clip"]').innerHTML = icon("check") + "更新片段";
      $("#cancel-clip-edit").classList.remove("hidden");
      return;
    }
    const preview = e.target.closest("[data-preview-clip]");
    if (preview) {
      const s = draft.segments[Number(preview.dataset.previewClip)];
      playRange = { start: s.start, end: s.end };
      seek(s.start);
      setPlaying(true);
      return;
    }
    const sceneToggle=e.target.closest('[data-scene-toggle]');
    if(sceneToggle){const input=$('#'+sceneToggle.dataset.sceneToggle);input.checked=!input.checked;input.dispatchEvent(new Event('change',{bubbles:true}));return;}
    const layout=e.target.closest("button[data-stage-layout]");if(layout){setStageLayout(layout.dataset.stageLayout);return;}
    if(e.target.closest("[data-rating-detail]")){revealQuality();return;}
    const film = e.target.closest("[data-film-time]");
    if(film){setPlaying(false);playRange=null;seek(Number(film.dataset.filmTime));return;}
    const b = e.target.closest("[data-action]");
    if (b) {
      e.preventDefault();
      await actions[b.dataset.action]?.();
      return;
    }
    const g = e.target.closest("[data-grade]");
    if (g) {
      setGrade(g.dataset.grade);
      return;
    }
    const tag = e.target.closest("[data-tag]");
    if (tag) {
      const t = tag.dataset.tag;
      draft.tags = draft.tags.includes(t)
        ? draft.tags.filter((v) => v !== t)
        : [...draft.tags, t];
      tag.classList.toggle("selected", draft.tags.includes(t));
      saveDraft();
      return;
    }
    const detail = e.target.closest("[data-detail]");
    if (detail) {
      detailTab = detail.dataset.detail;
      const menu=detail.closest('.detail-more');if(menu)menu.open=false;
      renderDetail();
      return;
    }
    const rm = e.target.closest("[data-remove-clip]");
    if (rm) {
      draft.segments.splice(Number(rm.dataset.removeClip), 1);
      resetClipEditor();
      saveDraft();
      renderClips();
      return;
    }
    const jump = e.target.closest("[data-seek]");
    if (jump) {
      seek(Number(jump.dataset.seek));
      return;
    }
    if (e.target.closest("input,a,button,select")) return;
    const row = e.target.closest("[data-ep]");
    if (row) location.hash = "record/" + row.dataset.ep;
  } catch (err) {
    if ($("#dialog").open) errorDialog(err);
    else toast(err.message, true);
  }
});
document.addEventListener("input", (e) => {
  if (e.target.id === "search") {
    filters.search = e.target.value;
    updateLibrary();
  }
  if (e.target.id === "timeline") {
    playRange = null;
    seek(Number(e.target.value));
  }
  if (e.target.id === "task-instruction") {
    draft.instruction = e.target.value;
    saveDraft();
  }
  if (e.target.id === "review-note") {
    draft.note = e.target.value;
    saveDraft();
  }
});
document.addEventListener("change", (e) => {
  const t = e.target;
  if (
    t.name === "export-kind" ||
    t.id === "export-fps" ||
    t.id === "export-ratio"
  ) {
    checkExport();
    return;
  }
  if(t.id==='filter-source'){filters.source=t.value;updateLibrary();return;}
  if(t.id==='filter-stageaudit'){filters.stageaudit=t.value;updateLibrary();return;}
  if (t.classList.contains("select-ep")) {
    t.checked ? selected.add(t.dataset.id) : selected.delete(t.dataset.id);
    updateLibrary();
  }
  if (t.id === "select-all") {
    for (const row of filtered())
      t.checked ? selected.add(row.id) : selected.delete(row.id);
    updateLibrary();
  }
  if (t.id.startsWith("filter-")) {
    filters[t.id.slice(7)] = t.value;
    updateLibrary();
  }
  if (t.id === "head-view") {
    $('[data-cam-card="head"]').className =
      "camera-card camera-main " + t.value;
  }
  if (t.id === "play-speed") speed = Number(t.value);
  if (t.id === "primary-camera") {
    primaryCamera = t.value;
    exactFrame = null;
    updateFrameCounter();
    refreshFrames();
  }
  if (t.id === "joint-select") {
    joint = Number(t.value);
    drawChart();
  }
  if (t.id === "signal-kind") {
    signalKind = t.value;
    joint = 0;
    renderDetail();
  }
  if (["robot-source","robot-overlay","show-trails","show-targets","trail-side","trail-window","trail-part","show-pose-trail","show-past","show-future","past-window","future-window","pose-count","pose-opacity","pose-scope","show-grid","show-joint-frames"].includes(t.id) && robot?.solid) {
    readRobotOptions();updateTrajectoryReadout();updatePoseTimes();robot.pose(Math.min(data.samples-1,Math.round(playhead*data.meta.timeline.rate_hz)));robot.setTime(playhead);
  }
  if(t.id==='robot-view')robot?.setView(t.value);
  if(t.id==='scene-focus')robot?.setFocus?.(t.value);

});
document.addEventListener("keydown", async (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "\\" && !$('#dialog').open) {
    e.preventDefault();toggleSidebar();return;
  }
  if(e.key==='Escape' && innerWidth<=760 && document.documentElement.dataset.sidebar==='expanded' && !$('#dialog').open) {
    setSidebarCollapsed(true);$('#sidebar-toggle')?.focus();return;
  }
  if (page !== "review" || $("#dialog").open) return;
  try {
    if ((e.ctrlKey || e.metaKey) && e.key === "s") {
      e.preventDefault();
      await saveReview();
      return;
    }
    if (
      ["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName) &&
      e.target.id !== "timeline"
    )
      return;
    if (e.key === "n" || e.key === "N") {
      e.preventDefault();
      reviewTools?.next();
      return;
    }
    if (e.key === "p" || e.key === "P") {
      e.preventDefault();
      reviewTools?.next(-1);
      return;
    }
    if (e.code === "Space") {
      e.preventDefault();
      actions.play();
    }
    if (["1", "2", "3", "4"].includes(e.key))
      setGrade("ABCD"[Number(e.key) - 1]);
    if (e.key === "[") actions["mark-in"]();
    if (e.key === "]") actions["mark-out"]();
    if (e.key === "ArrowRight") {
      e.preventDefault();
      stepFrame(1);
    }
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      stepFrame(-1);
    }
    if (e.key === "Home") {
      e.preventDefault();
      resetPlayback();
    }
  } catch (err) {
    toast(err.message, true);
  }
});
window.addEventListener("resize", drawChart);
document.addEventListener("pointerdown", (e) => {
  if (e.target.id === "timeline") beginScrub(e);
  if (e.target.id === "signal-chart") beginChartDrag(e);
});
document.addEventListener("pointerup", (e) => {
  if (scrubState) endScrub();
  if (chartDrag) endChartDrag(e);
});
document.addEventListener("pointercancel", () => {
  if (scrubState) {
    scrubState = null;
    setPlaying(false);
  }
  chartDrag = null;
  $("#chart-selection")?.classList.add("hidden");
});
document.addEventListener("pointermove", (e) => {
  if (chartDrag) moveChartDrag(e);
});
document.addEventListener("dblclick", (e) => {
  if (e.target.id === "signal-chart") {
    chartWindow = null;
    renderDetail();
  }
});
async function route() {
  const epoch=++routeEpoch;
  if(taskflowPanel?.recording)recordViewStates.set(taskflowPanel.recording.id,taskflowPanel.viewState());
  taskflowPanel?.destroy();taskflowPanel=null;
  simDemo?.destroy();simDemo=null;
  progressPanel?.destroy();
  progressPanel = null;
  playing = false;
  framePlayer?.destroy();
  framePlayer = null;
  scrubState = null;
  chartDrag = null;
  robot?.destroy();
  robot = null;
  reviewTools?.destroy();
  reviewTools = null;
  reviewToken++;
  let [view,id,runId]=location.hash.slice(1).split("/");
  if(view==='rules'){view='library';history.replaceState(null,'','#library');}
  if(view==='taskflow'&&!id){view='library';history.replaceState(null,'','#library');}
  if(view==='taskflow'&&id){const run=auditOverview?.runs.find(r=>r.id===id),asset=auditOverview?.assets.find(a=>a.id===run?.asset_id),record=catalog.episodes.find(r=>asset?.source.kind==='recording'&&r.id===asset.source.id);if(record){runId=id;id=record.id;view='record';history.replaceState(null,'',`#record/${id}/${runId}`);}}
  if(view==='review'){view='record';history.replaceState(null,'',`#record/${id}`);}
  page = view || "library";
  $$("[data-nav]").forEach(a=>{
    const active=a.dataset.nav===(['review','record','taskflow'].includes(page)?'library':page);
    a.classList.toggle('active',active);
    if(active)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');
  });
  $("#breadcrumb").textContent =
    {
      taskflow: "视频阶段审核",
      record: "记录审核",
      library: "数据工作台",
      review: "记录审核 / 数据质检与轨迹",
      exports: "导出中心",
      rules: "分级与质检规则",
      guide: "使用指南",
      'sim-demo': "仿真参考演示",
    }[page] || "数据工作台";
  try {
    if (page === "review") renderReview(id);
    else if (page === 'taskflow'||page==='record') {const {Taskflow}=await import('./taskflow.mjs');if(epoch!==routeEpoch)return;const record=page==='record'?catalog.episodes.find(r=>r.id===id):null;if(page==='record'&&!record)throw Error('未找到这条采集记录。');taskflowPanel=new Taskflow($('#main'),api,escape);await taskflowPanel.mount(page==='record'?runId:id,{recording:record,savedState:recordViewStates.get(record?.id)});if(epoch===routeEpoch&&reviewIntent?.id===record?.id){const action=reviewIntent.action;reviewIntent=null;taskflowPanel.setDetailTab(['instruction','decision','review'].includes(action)?'manual':'criteria');}}
    else if (page === "rules") await renderRules();
    else if (page === "exports") renderExports();
    else if (page === "guide") renderGuide();
    else if (page === 'sim-demo') {const {SimDemo}=await import('./sim-demo.mjs');if(page==='sim-demo'){simDemo=new SimDemo($('#main'),api,escape);await simDemo.mount();}}
    else renderLibrary();
    if(epoch===routeEpoch)window.scrollTo(0, 0);
  } catch (e) {
    toast(e.message, true);
  }
}
window.addEventListener("hashchange", route);
installIcons();
installMiniMaxAccess(api);
updateThemeLabel();
setSidebarCollapsed(document.documentElement.dataset.sidebar === 'collapsed', false);
window.addEventListener('resize',()=>{
  try { if(!localStorage.getItem('robocurate-sidebar')) setSidebarCollapsed(innerWidth<=1000,false); } catch {}
});
await refresh();
await route();
setInterval(refresh, 5000);
