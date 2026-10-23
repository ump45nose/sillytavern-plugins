/* ==========================================================================
   公益 AI 资源中枢 · 交互控制器 (app.js)
   涵盖 5 大核心体验的完整闭环交互
   ========================================================================== */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const STATE = {
  view: "resources",          // 'resources' | 'equity' | 'scan' | 'sources'
  resPerspective: "both",     // 'both' | 'models' | 'sites'
  siteFilter: "all",          // 'all' | 'daily' | 'attention'
  searchQuery: "",
  selectedTemplateId: "tpl-reasoning",
  diffFilter: "all",          // 'all' | 'add' | 'upd' | 'warn'
  scanning: false,
  verifying: false,
  syncing: false
};

/* ---------- SVG Icons (Anthropic Warm Line Style) ---------- */
const ICONS = {
  spark: `<svg class="nav-ic" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M10 2.5L12.2 7.8L17.5 10L12.2 12.2L10 17.5L7.8 12.2L2.5 10L7.8 7.8L10 2.5Z" stroke-linejoin="round"/></svg>`,
  clock: `<svg class="nav-ic" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="10" cy="10" r="7.2"/><path d="M10 6V10.2L13 12" stroke-linecap="round"/></svg>`,
  radar: `<svg class="nav-ic" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="10" cy="10" r="7.2"/><circle cx="10" cy="10" r="3.6"/><path d="M10 10L15 5" stroke-linecap="round"/></svg>`,
  nodes: `<svg class="nav-ic" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="5" cy="6" r="2.2"/><circle cx="5" cy="14" r="2.2"/><circle cx="15" cy="10" r="2.5"/><path d="M7.2 6.8L12.6 9.1M7.2 13.2L12.6 10.9" stroke-linecap="round"/></svg>`,
  search: `<svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="9" cy="9" r="5.8"/><path d="M13.5 13.5L17 17" stroke-linecap="round"/></svg>`,
  sync: `<svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M16.5 10A6.5 6.5 0 1 1 14.5 5.2M16.5 3.5V7.5H12.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  key: `<svg width="13" height="13" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="7" cy="10" r="3.5"/><path d="M10.5 10H17.5M14.5 10V13M17 10V12.5" stroke-linecap="round"/></svg>`,
  merge: `<svg width="13" height="13" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M5 4V9C5 11.5 7 13 10 13M15 4V9C15 11.5 13 13 10 13M10 13V17" stroke-linecap="round"/></svg>`,
  check: `<svg width="13" height="13" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 10.5L8 14.5L16 6.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  copy: `<svg width="13" height="13" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="7" y="7" width="9" height="9" rx="1.8"/><path d="M4 13V5C4 4.4 4.4 4 5 4H13" stroke-linecap="round"/></svg>`
};

/* ---------- Toast Helper ---------- */
function showToast(msg) {
  let wrap = $("#toastWrap");
  if (!wrap) {
    wrap = document.createElement("div");
    wrap.id = "toastWrap";
    wrap.className = "toast-wrap";
    document.body.appendChild(wrap);
  }
  const el = document.createElement("div");
  el.className = "toast";
  el.innerHTML = `<span style="color:var(--clay)">●</span><span>${msg}</span>`;
  wrap.appendChild(el);
  setTimeout(() => {
    el.style.opacity = "0";
    el.style.transition = "opacity 200ms";
    setTimeout(() => el.remove(), 220);
  }, 2800);
}

/* ---------- Compute Dynamic Summary Stats ---------- */
function computeTotals() {
  const sites = window.HUB_DATA.sites;
  let totalPerm = 0;
  let totalDaily = 0;
  let totalAccounts = 0;
  sites.forEach(s => {
    s.accounts.forEach(a => {
      totalPerm += a.permBalance;
      totalDaily += a.dailyQuota;
      totalAccounts += 1;
    });
  });
  return {
    siteCount: sites.length,
    accountCount: totalAccounts,
    totalPerm: totalPerm.toFixed(2),
    totalDaily: totalDaily.toFixed(2)
  };
}

/* ---------- Render Sidebar ---------- */
function renderSidebar() {
  const D = window.HUB_DATA;
  const stats = computeTotals();
  const triageCount = D.triageItems.length;

  $("#sidePulse").innerHTML = `
    <div class="side-pulse-row">
      <span class="side-pulse-lbl">今日优先可用额度</span>
      <span class="chip clay" style="padding:1px 6px;font-size:10px">当日优先</span>
    </div>
    <div class="side-pulse-row" style="margin-top:3px">
      <span class="side-pulse-val num">$${stats.totalDaily}</span>
      <span class="muted" style="font-size:11px">储备 $${stats.totalPerm}</span>
    </div>
    <div class="side-pulse-bar" title="陶土色：今日必耗限时额度 · 橄榄色：长期储备余额">
      <i style="width:26%;background:var(--clay)"></i>
      <i style="width:74%;background:var(--olive)"></i>
    </div>
    <div class="side-pulse-row" style="font-size:11px;color:var(--ink2)">
      <span>${stats.siteCount} 个聚合站点 · ${stats.accountCount} 个独立号</span>
      <span style="color:var(--olive);font-weight:600">6 款优选模型</span>
    </div>
  `;

  const navItems = [
    { id: "resources", label: "选模型与查资源", icon: ICONS.spark, badge: `${stats.siteCount} 站`, badgeCls: "" },
    { id: "equity", label: "权益利用与 Cron", icon: ICONS.clock, badge: `$${stats.totalDaily} 限时`, badgeCls: "warn" },
    { id: "scan", label: "渠道扫描与验证", icon: ICONS.radar, badge: "1 项实测中", badgeCls: "live" },
    { id: "sources", label: "来源接入与同步", icon: ICONS.nodes, badge: "3 来源", badgeCls: "" }
  ];

  $("#sideNav").innerHTML = navItems.map(item => `
    <button class="nav-btn ${STATE.view === item.id ? "on" : ""}" data-view="${item.id}">
      ${item.icon}
      <span>${item.label}</span>
      <span class="nav-badge ${item.badgeCls}">${item.badge}</span>
    </button>
  `).join("");

  $$("#sideNav .nav-btn").forEach(btn => {
    btn.onclick = () => switchView(btn.dataset.view);
  });

  $("#sideSources").innerHTML = `
    <div class="side-src-head">
      <span>已接入数据来源</span>
      <button class="btn ghost sm" style="height:20px;padding:0 6px;font-size:11px" onclick="switchView('sources')">详情 →</button>
    </div>
    ${D.sources.map(src => `
      <div class="side-src-item" onclick="switchView('sources')">
        <span class="status-dot ${src.authStatus === 'ok' ? 'ok' : 'warn'}"></span>
        <span style="font-weight:500;color:var(--ink)">${src.name}</span>
        <span class="muted" style="margin-left:auto;font-size:10.5px">${src.lastSync.replace('今天 ', '').split('（')[0]}</span>
      </div>
    `).join("")}
    ${triageCount > 0 ? `
      <div style="margin-top:4px;padding-top:7px;border-top:1px dashed var(--line);display:flex;align-items:center;justify-content:space-between;font-size:11px;color:var(--clay-d)">
        <span>● 待自己处理事项</span>
        <b>${triageCount} 项</b>
      </div>
    ` : ""}
  `;
}

/* ---------- Render Global Top Bar & Triage Strip ---------- */
function renderTopAndTriage() {
  const D = window.HUB_DATA;
  const activeCheck = D.liveChecks[0];

  $("#sysActivityPill").innerHTML = `
    <span class="status-dot run"></span>
    <span>系统正在检查：<b>${activeCheck.title}</b> (${activeCheck.progress}%)</span>
    <span class="muted" style="font-size:11px">查看队列 →</span>
  `;
  $("#sysActivityPill").onclick = () => switchView("scan");

  const triageContainer = $("#triageStrip");
  if (!D.triageItems.length) {
    triageContainer.classList.add("hidden");
    return;
  }
  triageContainer.classList.remove("hidden");
  triageContainer.innerHTML = `
    <div class="triage-head">
      <div class="triage-title">
        <span>● 需要你处理的事项（${D.triageItems.length} 项人工维护与异常干预，其余均已由系统自动完成）</span>
      </div>
      <span class="muted" style="font-size:11.5px">遵循「少逛后台、少做重复维护」：行内一键处理</span>
    </div>
    <div class="triage-grid">
      ${D.triageItems.map(item => `
        <div class="triage-card ${item.tone}">
          <div class="triage-info">
            <div class="t-kicker">${item.kicker}</div>
            <div class="t-main" title="${item.title}">${item.title}</div>
            <div class="t-sub">${item.desc}</div>
          </div>
          <button class="btn sm ${item.tone === 'clay' ? 'clay' : ''}" data-triage-act="${item.id}">
            ${item.actionLabel}
          </button>
        </div>
      `).join("")}
    </div>
  `;

  $$("[data-triage-act]", triageContainer).forEach(btn => {
    btn.onclick = () => handleTriageAction(btn.dataset.triageAct);
  });
}

function handleTriageAction(triageId) {
  const item = window.HUB_DATA.triageItems.find(x => x.id === triageId);
  if (!item) return;
  if (item.kind === "missing_key") {
    openAddKeyModal(item.siteId);
  } else if (item.kind === "duplicate_site") {
    openMergeModal(item.siteId);
  } else if (item.kind === "threshold_blocked") {
    switchView("equity");
    showToast("已定位至「星火公益」签到门槛削峰窗口，可调整或确认 Cron 绑定");
  } else if (item.kind === "auth_expiring") {
    switchView("sources");
    showToast("已定位至「NAS · CPA」来源凭证状态");
  }
}

/* ==========================================================================
   View 1: 选模型与查资源 (Models Advisor + Aggregated Sites)
   ========================================================================== */
function renderResourcesView() {
  const D = window.HUB_DATA;
  const q = STATE.searchQuery.trim().toLowerCase();

  // Filter models
  const filteredModels = D.models.filter(m => {
    if (!q) return true;
    return m.id.toLowerCase().includes(q) ||
      m.roleTag.toLowerCase().includes(q) ||
      m.routes.some(r => r.siteName.toLowerCase().includes(q));
  });
  const strongModels = filteredModels.filter(m => m.tier === "strong");
  const execModels = filteredModels.filter(m => m.tier === "exec");

  // Filter sites
  const filteredSites = D.sites.filter(s => {
    if (STATE.siteFilter === "daily" && !s.accounts.some(a => a.dailyQuota > 0)) return false;
    if (STATE.siteFilter === "attention" && s.status === "ok" && !s.duplicateCandidate) return false;
    if (!q) return true;
    const matchBasic = s.name.toLowerCase().includes(q) || s.url.toLowerCase().includes(q);
    const matchModel = s.strongModels.some(m => m.toLowerCase().includes(q)) ||
      s.execModels.some(m => m.toLowerCase().includes(q));
    const matchAcct = s.accounts.some(a => a.username.toLowerCase().includes(q));
    return matchBasic || matchModel || matchAcct;
  });

  const renderModelCard = m => `
    <div class="model-card" data-model-inspect="${m.id}">
      <div class="model-top">
        <div>
          <span class="model-id">${m.name}</span>
          <span class="muted" style="font-size:11.5px;margin-left:6px">${m.roleTag}</span>
        </div>
        <div style="display:flex;align-items:center;gap:6px">
          <span class="chip ${m.verifyTone}">${m.verifyBadge}</span>
          <button class="btn sm" data-copy-model="${m.id}" title="复制模型 ID 与最优路由建议">
            ${ICONS.copy} 复制配置
          </button>
        </div>
      </div>
      <div class="model-evidence-bar">
        <span>今日优先可用：<b class="num" style="color:var(--clay-d)">${m.dailyAvailQuota}</b>（总储备 ${m.totalAvailQuota}）</span>
        <span>·</span>
        <span>实测均值：<code class="mono">TTFT ${m.avgTtft} · ${m.avgTps}</code></span>
      </div>
      <div style="font-size:12px;color:var(--ink2);margin-bottom:8px;background:var(--sunk);padding:6px 10px;border-radius:6px">
        <b>选型依据：</b>${m.callerHint}
      </div>
      <div class="route-candidates">
        ${m.routes.map(r => `
          <div class="route-item ${r.status}">
            <span class="route-rank">${r.rank}</span>
            <b style="font-size:12px">${r.siteName}</b>
            <span class="muted" style="font-size:11px">${r.account}</span>
            <span style="margin-left:auto;font-family:var(--mono);font-size:11px;color:var(--ink2)">${r.quotaText}</span>
            <span class="chip ${r.status === 'warn' ? 'rose' : 'olive'}" style="font-size:10.5px;padding:1px 6px">${r.evidence}</span>
          </div>
        `).join("")}
      </div>
    </div>
  `;

  const renderSiteCard = s => {
    const srcPills = s.sources.map(src => {
      const cls = src.includes("All API") ? "hub" : (src.includes("New API") ? "newapi" : "cpa");
      return `<span class="src-pill ${cls}">${src}</span>`;
    }).join("");

    return `
      <article class="site-card" id="card-${s.id}">
        <div class="site-card-head">
          <div class="site-identity">
            <span class="status-dot ${s.status === 'ok' ? 'ok' : 'warn'}"></span>
            <span class="site-name">${s.name}</span>
            <a class="site-url" href="${s.url}" target="_blank" rel="noreferrer" onclick="event.stopPropagation()">${s.url.replace('https://', '')}</a>
            ${s.mirrorUrl ? `<span class="muted" style="font-size:11px">备用: ${s.mirrorUrl.replace('https://', '')}</span>` : ""}
            <div class="src-badges">${srcPills}</div>
          </div>
          <div style="display:flex;align-items:center;gap:6px">
            ${s.duplicateCandidate ? `
              <button class="btn sm clay" data-merge-site="${s.id}">
                ${ICONS.merge} 合并重复站点
              </button>
            ` : ""}
            <button class="btn sm" data-add-key="${s.id}">
              ${ICONS.key} 补 Key
            </button>
            <button class="btn sm" data-edit-site="${s.id}">
              编辑资料
            </button>
            <button class="btn sm ghost" data-scan-one="${s.id}">
              立即扫描
            </button>
          </div>
        </div>

        <!-- 保留独立账号及余额 -->
        <div class="acct-grid">
          ${s.accounts.map(a => {
            const overThreshold = a.permBalance >= a.thresholdCap;
            return `
              <div class="acct-box" style="${overThreshold ? 'border-color:var(--ochre);background:#FCF9F0' : ''}">
                <div class="acct-top">
                  <div class="acct-user">
                    <span>👤 ${a.username}</span>
                    <span class="chip" style="padding:1px 6px;font-size:10px">${a.label}</span>
                  </div>
                  <span class="chip ${a.signinTone}">${a.signinStatus}</span>
                </div>
                <div class="acct-balances">
                  <div>
                    <span class="muted" style="font-size:11px">独立永久余额 </span>
                    <span class="bal-main num">$${a.permBalance.toFixed(2)}</span>
                  </div>
                  ${a.dailyQuota > 0 ? `
                    <span class="bal-daily">当日有效 $${a.dailyQuota.toFixed(2)} (${a.dailyExpireAt})</span>
                  ` : `<span class="muted" style="font-size:11px">${a.dailyExpireAt}</span>`}
                </div>
                <div class="acct-meta">
                  <span>签到门槛：<b style="${overThreshold ? 'color:var(--ochre)' : ''}">&lt; $${a.thresholdCap.toFixed(2)}</b></span>
                  <span>
                    ${a.keysCount > 0
                      ? `已绑 ${a.keysCount} 个 Key (${a.keys.map(k => `<code class="mono">${k.masked}</code>`).join(", ")})`
                      : `<b style="color:var(--clay-d)">⚠ 暂无可用 Key（点右上角补 Key）</b>`}
                  </span>
                </div>
              </div>
            `;
          }).join("")}
        </div>

        <!-- 模型分组、使用限制、有效期与近期表现 -->
        <div style="display:flex;flex-wrap:wrap;gap:14px;align-items:center;font-size:12px;padding:8px 11px;background:var(--sunk);border-radius:8px;margin-bottom:8px">
          <div>
            <span class="muted">强模型：</span>
            ${s.strongModels.length
              ? s.strongModels.map(m => `<code class="mono" style="color:var(--clay-d);font-weight:600;margin-right:6px">${m}</code>`).join("")
              : `<span style="color:var(--rose)">无通过实测的强模型（已拦截异常套壳）</span>`}
          </div>
          <span class="muted">|</span>
          <div>
            <span class="muted">执行模型：</span>
            ${s.execModels.map(m => `<code class="mono" style="color:var(--olive);margin-right:6px">${m}</code>`).join("")}
          </div>
        </div>

        <div class="site-foot">
          <div style="display:flex;flex-wrap:wrap;gap:14px">
            <span><b>有效期：</b>${s.validity}</span>
            <span><b>使用限制：</b>${s.restrictions}</span>
            <span><b>签到规则：</b>${s.signinRule}</span>
          </div>
          <div style="display:flex;align-items:center;gap:8px;margin-left:auto">
            <span>近期表现：<b>${s.recentSuccessRate}</b> (${s.recentLatency})</span>
            <span class="probe-bars" title="最近 12 次探测与实测状态">
              ${s.probes.map(p => `<i class="${p === 'ok' ? '' : p}"></i>`).join("")}
            </span>
          </div>
        </div>
      </article>
    `;
  };

  return `
    <div class="page-header">
      <div>
        <h1>资源总览与模型选型依据</h1>
        <p>聚合各来源同域名站点并保留独立账号余额。模型按「强模型」与「执行模型」分层，为调用方提供实测表现与消耗优先级依据。</p>
      </div>
      <div style="display:flex;align-items:center;gap:8px">
        <div class="seg">
          <button class="${STATE.resPerspective === 'both' ? 'on' : ''}" data-persp="both">全景视图</button>
          <button class="${STATE.resPerspective === 'models' ? 'on' : ''}" data-persp="models">仅看模型依据</button>
          <button class="${STATE.resPerspective === 'sites' ? 'on' : ''}" data-persp="sites">仅看聚合站点</button>
        </div>
      </div>
    </div>

    ${STATE.resPerspective !== "sites" ? `
      <section>
        <div class="sec-bar">
          <div class="sec-title">
            <h2>模型选型依据</h2>
            <span class="sec-sub">调用方（Claude Code / Codex / 本地 Agent / Cron）自行选模型，本中心提供实测真伪、延迟与当日额度优先顺序</span>
          </div>
          <span class="chip olive">✓ 已自动剔除 1 个模型广场绿灯但实测降智的伪强模型渠道</span>
        </div>
        <div class="tier-columns">
          <div class="tier-panel strong-tier">
            <div class="tier-head">
              <div>
                <h3><span style="color:var(--clay)">◆</span> 强模型 (Frontier Reasoning)</h3>
                <p>用于架构设计、复杂推理、疑难重构与最终审阅。经「防降智推理探针」实测验证原生思维链。</p>
              </div>
              <span class="chip clay">${strongModels.length} 款可用</span>
            </div>
            ${strongModels.map(renderModelCard).join("") || `<div class="muted">无匹配强模型</div>`}
          </div>

          <div class="tier-panel exec-tier">
            <div class="tier-head">
              <div>
                <h3><span style="color:var(--olive)">●</span> 执行模型 (Fast Execution)</h3>
                <p>用于高频代码执行、子 Agent 检索、长文本 JSON 抽取与定时 Cron 任务。高吞吐、低倍率。</p>
              </div>
              <span class="chip olive">${execModels.length} 款可用</span>
            </div>
            ${execModels.map(renderModelCard).join("") || `<div class="muted">无匹配执行模型</div>`}
          </div>
        </div>
      </section>
    ` : ""}

    ${STATE.resPerspective !== "models" ? `
      <section>
        <div class="sec-bar">
          <div class="sec-title">
            <h2>聚合站点与独立账号账本</h2>
            <span class="sec-sub">自动合并 All API Hub、NAS New API、CPA 中的同站点条目，独立保留各账号余额、签到与 Key</span>
          </div>
          <div class="site-filters">
            <div class="seg">
              <button class="${STATE.siteFilter === 'all' ? 'on' : ''}" data-sfilter="all">全部站点 (${D.sites.length})</button>
              <button class="${STATE.siteFilter === 'daily' ? 'on' : ''}" data-sfilter="daily">含当日有效额度</button>
              <button class="${STATE.siteFilter === 'attention' ? 'on' : ''}" data-sfilter="attention">需人工维护 / 预警</button>
            </div>
          </div>
        </div>
        <div class="site-list">
          ${filteredSites.map(renderSiteCard).join("") || `<div class="kpi-card muted">未找到匹配的站点、网址或模型</div>`}
        </div>
      </section>
    ` : ""}
  `;
}

/* ==========================================================================
   View 2: 权益利用与限时调度 (Quota Windows, Thresholds, Cron Binding)
   ========================================================================== */
function renderEquityView() {
  const D = window.HUB_DATA;
  const stats = computeTotals();

  return `
    <div class="page-header">
      <div>
        <h1>权益利用与限时资源调度</h1>
        <p>当日有效额度优先消耗；明确区分「投放时刻」与「实际可用窗口」，支持将已有 Cron 任务绑定至限时或需削峰资源。</p>
      </div>
      <div style="display:flex;gap:8px">
        <span class="chip clay">当前时刻：${D.now} · 晚间限时窗口开放中</span>
      </div>
    </div>

    <div class="quota-kpi-row">
      <div class="kpi-card" style="border-top:3px solid var(--clay)">
        <div class="kpi-lbl">今日剩余有效额度（优先消耗）</div>
        <div class="kpi-val num" style="color:var(--clay-d)">$${stats.totalDaily}</div>
        <div class="kpi-sub">含 23:00 失效晚间包 $6.00 + 24:00 清零签到金 $10.00</div>
      </div>
      <div class="kpi-card" style="border-top:3px solid var(--ochre)">
        <div class="kpi-lbl">签到余额门槛阻塞</div>
        <div class="kpi-val num" style="color:var(--ochre)">1 个账号</div>
        <div class="kpi-sub">星火公益 ($10.40 ≥ $10.00)，明早 08:00 前需消耗 $0.45</div>
      </div>
      <div class="kpi-card" style="border-top:3px solid var(--olive)">
        <div class="kpi-lbl">正在开放的限时窗口</div>
        <div class="kpi-val num" style="color:var(--olive)">2 个窗口</div>
        <div class="kpi-sub">凛冬晚间池 (至 23:00) · LinuxDo 当日签到池 (至 24:00)</div>
      </div>
      <div class="kpi-card" style="border-top:3px solid var(--sky)">
        <div class="kpi-lbl">已绑定限时资源的 Cron</div>
        <div class="kpi-val num" style="color:var(--sky)">${D.cronJobs.length} 个任务</div>
        <div class="kpi-sub">预计今晚自动消化 $3.20 限时与超门槛额度</div>
      </div>
    </div>

    <!-- 24-Hour Drop vs Usable Window Timeline -->
    <div class="timeline-card">
      <div class="sec-bar" style="margin-bottom:8px">
        <div class="sec-title">
          <h2>24 小时投放时刻与实际可用窗口</h2>
          <span class="sec-sub">投放时刻 ≠ 全天可用（受公共额度池抢空、时段分组开关与晚高峰限流影响）</span>
        </div>
        <div class="tl-legend">
          <span><b style="display:inline-block;width:8px;height:8px;background:var(--ink);transform:rotate(45deg);margin-right:4px"></b>投放 / 核验时刻</span>
          <span><b style="display:inline-block;width:12px;height:8px;background:var(--clay-t);border:1px solid var(--clay);margin-right:4px"></b>当前开放窗口</span>
          <span><b style="display:inline-block;width:12px;height:8px;background:var(--olive-t);border:1px solid var(--olive);margin-right:4px"></b>常规可用窗口</span>
          <span style="color:var(--clay-d);font-weight:600">┃ 当前 ${D.now}</span>
        </div>
      </div>

      <div class="tl-axis">
        <div>站点与限时权益项</div>
        <div class="tl-hours">
          <span>00:00</span><span>04:00</span><span>08:00</span><span>12:00</span><span>16:00</span><span style="color:var(--clay-d);font-weight:700">19:27 ▼</span><span>24:00</span>
        </div>
        <div style="text-align:right">当日有效额度 / 状态</div>
      </div>

      ${D.quotaWindows.map(w => {
        const leftPct = (w.winStart / 24) * 100;
        const widthPct = Math.max(4, ((w.winEnd - w.winStart) / 24) * 100);
        const dropPct = (w.dropHour / 24) * 100;
        const nowPct = (19.45 / 24) * 100;
        return `
          <div class="tl-row">
            <div>
              <div style="font-weight:600;font-size:12.5px">${w.siteName}</div>
              <div class="muted" style="font-size:11px">${w.quotaTitle}</div>
            </div>
            <div>
              <div class="tl-track" title="${w.whyNotAllDay}">
                <div class="tl-now-line" style="left:${nowPct}%"></div>
                <div class="tl-drop-pin" style="left:${dropPct}%" title="${w.dropTime}"></div>
                <div class="tl-win-bar ${w.state}" style="left:${leftPct}%;width:${widthPct}%">
                  <span>◆ ${w.dropTime} → 可用窗口 ${w.usableWindowText}</span>
                </div>
              </div>
              <div class="muted" style="font-size:11px;margin-top:3px">${w.whyNotAllDay}</div>
            </div>
            <div style="text-align:right">
              <div class="num" style="font-size:15px;font-weight:600;color:var(--clay-d)">${w.dailyEffective}</div>
              <div style="font-size:11px;color:var(--ink2)">${w.stateLabel}</div>
            </div>
          </div>
        `;
      }).join("")}
    </div>

    <!-- Split: Sign-in Balance Thresholds + Existing Cron Binding -->
    <div class="equity-split">
      <div class="timeline-card">
        <div class="sec-bar">
          <div class="sec-title">
            <h2>签到余额门槛监控</h2>
            <span class="sec-sub">高于门槛将无法领每日签到金</span>
          </div>
        </div>
        ${D.sites.flatMap(s => s.accounts.map(a => ({ site: s, acct: a }))).map(({ site, acct }) => {
          const pct = Math.min(100, Math.round((acct.permBalance / acct.thresholdCap) * 100));
          const blocked = acct.permBalance >= acct.thresholdCap;
          return `
            <div class="threshold-item" style="${blocked ? 'border-color:var(--ochre);background:#FCF8EE' : ''}">
              <div style="display:flex;justify-content:space-between;align-items:center">
                <div>
                  <b>${site.name}</b>
                  <span class="muted" style="font-size:11.5px;margin-left:6px">${acct.username}</span>
                </div>
                <span class="chip ${blocked ? 'ochre' : 'olive'}">
                  ${blocked ? `⚠ 超门槛 $${(acct.permBalance - acct.thresholdCap + 0.05).toFixed(2)} · 签到冻结` : `安全 · 距门槛还差 $${(acct.thresholdCap - acct.permBalance).toFixed(2)}`}
                </span>
              </div>
              <div class="threshold-meter">
                <div class="threshold-fill" style="width:${pct}%;background:${blocked ? 'var(--ochre)' : 'var(--olive)'}"></div>
                <div class="threshold-Gate" style="left:85%" title="签到余额上限门槛"></div>
              </div>
              <div style="display:flex;justify-content:space-between;font-size:11px;color:var(--ink2)">
                <span>当前永久余额：<b class="mono">$${acct.permBalance.toFixed(2)}</b> (当日限时 $${acct.dailyQuota.toFixed(2)})</span>
                <span>签到上限门槛：<b class="mono">&lt; $${acct.thresholdCap.toFixed(2)}</b></span>
              </div>
            </div>
          `;
        }).join("")}
      </div>

      <div class="timeline-card">
        <div class="sec-bar">
          <div class="sec-title">
            <h2>选择已有 Cron 任务绑定限时资源</h2>
            <span class="sec-sub">自动校验 Cron 触发时刻是否落在资源的「实际可用窗口」内</span>
          </div>
        </div>
        <table class="cron-table">
          <thead>
            <tr>
              <th>已有 Cron 定时任务</th>
              <th>触发时刻</th>
              <th>模型层级需求 / 预估消耗</th>
              <th>绑定限时 / 削峰资源窗口</th>
              <th>窗口匹配校验</th>
            </tr>
          </thead>
          <tbody>
            ${D.cronJobs.map(job => {
              const win = D.quotaWindows.find(w => w.id === job.boundWinId);
              const inWindow = win ? (job.runHour >= win.winStart && job.runHour <= win.winEnd) : false;
              return `
                <tr>
                  <td>
                    <div style="font-weight:600;font-size:12.5px">${job.name}</div>
                    <code class="mono muted">${job.cronExpr}</code>
                  </td>
                  <td>
                    <span class="chip">${job.runTimeText}</span>
                  </td>
                  <td>
                    <div style="font-size:11.5px">${job.tierReq}</div>
                    <div class="muted" style="font-size:11px">预计 ${job.estCost}</div>
                  </td>
                  <td>
                    <select class="form-input" style="padding:4px 8px;font-size:12px" data-cron-bind="${job.id}">
                      ${D.quotaWindows.map(w => `
                        <option value="${w.id}" ${w.id === job.boundWinId ? "selected" : ""}>
                          ${w.siteName} · ${w.quotaTitle} (${w.dailyEffective})
                        </option>
                      `).join("")}
                    </select>
                  </td>
                  <td>
                    ${inWindow
                      ? `<span class="chip olive">✓ 落入可用窗口 · 当日额度优先</span>`
                      : `<span class="chip rose" title="任务触发时刻不在该资源的实际可用窗口内">⚠ 偏离可用窗口 (${win ? win.usableWindowText.split(' ')[0] : ''})</span>`}
                  </td>
                </tr>
              `;
            }).join("")}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

/* ==========================================================================
   View 3: 渠道扫描与任务验证 (Batch Scan + Real Task Verification)
   ========================================================================== */
function renderScanView() {
  const D = window.HUB_DATA;
  const selectedCount = D.scanChannels.filter(c => c.checked).length;

  return `
    <div class="page-header">
      <div>
        <h1>渠道批量扫描与实际任务验证</h1>
        <p>先批量扫描站点访问状态、Key 的模型目录与模型广场指标；再针对性安排真实微任务验证，识别「广场绿灯但实测降智或超时」。</p>
      </div>
      <div style="display:flex;gap:8px">
        <button class="btn" id="btnBatchScan">
          ${ICONS.sync} ${STATE.scanning ? "正在扫描站点与目录..." : `1. 批量扫描选中渠道 (${selectedCount})`}
        </button>
        <button class="btn clay" id="btnRunVerify">
          ${ICONS.spark} ${STATE.verifying ? "正在执行实测探针..." : `2. 安排实际任务验证 (${selectedCount})`}
        </button>
      </div>
    </div>

    <!-- 系统正在检查什么：实时后台巡检与验证队列 -->
    <div class="timeline-card" style="background:#F7FAFC;border-color:var(--sky-border)">
      <div class="sec-bar" style="margin-bottom:8px">
        <div class="sec-title">
          <h2 style="font-size:16px;color:var(--sky)">● 系统正在检查的后台队列</h2>
          <span class="sec-sub">自动巡检与按需触发的实际任务验证实时进度</span>
        </div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
        ${D.liveChecks.map(chk => `
          <div style="background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 13px">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
              <span class="chip ${chk.progress < 100 ? 'sky' : 'olive'}">${chk.type} · ${chk.progress}%</span>
              <span class="mono muted">启动于 ${chk.startedAt}</span>
            </div>
            <div style="font-weight:600;font-size:12.5px;margin-bottom:3px">${chk.title}</div>
            <div class="muted" style="font-size:11.5px">${chk.detail}</div>
          </div>
        `).join("")}
      </div>
    </div>

    <!-- Stage 2 Task Template Selector -->
    <div class="timeline-card">
      <div class="sec-bar">
        <div class="sec-title">
          <h2>第二步验证任务配置 · 真实任务探针库</h2>
          <span class="sec-sub">区别于简单 ping /v1/models，使用真实微任务检验思维链签名、AST 代码补丁与长文本吞吐</span>
        </div>
        <button class="btn sm" id="btnScheduleIdle">排入夜间空闲窗口 (01:00) 验证</button>
      </div>
      <div class="task-templates">
        ${D.verifyTemplates.map(tpl => `
          <div class="tpl-card ${STATE.selectedTemplateId === tpl.id ? 'on' : ''}" data-tpl="${tpl.id}">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
              <b style="font-size:13px">${tpl.name}</b>
              <span class="chip ${STATE.selectedTemplateId === tpl.id ? 'clay' : ''}">${tpl.targetTier}</span>
            </div>
            <p style="margin:0 0 8px;font-size:11.5px;color:var(--ink2)">${tpl.desc}</p>
            <div class="muted" style="font-size:11px;font-family:var(--mono)">预估消耗：${tpl.costEst}</div>
          </div>
        `).join("")}
      </div>
    </div>

    <!-- Unified Scan & Verification Workbench Table -->
    <div class="scan-workbench">
      <div class="sec-bar" style="margin-bottom:-8px">
        <div class="sec-title">
          <h2>站点/渠道扫描结果与实测对比表</h2>
          <span class="sec-sub">左侧为「第一阶段：批量扫描指标」，右侧为「第二阶段：实际任务验证结论」</span>
        </div>
        <div style="display:flex;gap:8px">
          <button class="btn sm" id="btnSelectAllCh">全选 / 反选</button>
        </div>
      </div>

      <table class="scan-table">
        <thead>
          <tr>
            <th style="width:36px">选择</th>
            <th>站点与渠道 Key</th>
            <th>网站访问状态</th>
            <th>Key 的模型目录 (/v1/models)</th>
            <th>站点模型广场指标 (官方宣称)</th>
            <th>实际任务验证结果 (中心判断依据)</th>
          </tr>
        </thead>
        <tbody>
          ${D.scanChannels.map(ch => `
            <tr>
              <td>
                <input type="checkbox" ${ch.checked ? "checked" : ""} data-ch-check="${ch.id}" style="cursor:pointer"/>
              </td>
              <td>
                <div style="font-weight:600;font-size:13px">${ch.siteName}</div>
                <div class="mono muted" style="font-size:11px">${ch.channelName}</div>
                <span class="chip" style="margin-top:4px;font-size:10px">${ch.source} · 扫描于 ${ch.lastScanAt}</span>
              </td>
              <td>
                <span class="chip ${ch.webTone}">${ch.webStatus}</span>
              </td>
              <td>
                <div style="font-size:12px;margin-bottom:4px">${ch.keyCatalog}</div>
                <div style="display:flex;flex-wrap:wrap;gap:4px">
                  ${ch.keyModels.map(m => `<code class="mono" style="background:var(--sunk);padding:1px 5px;border-radius:4px;font-size:10.5px">${m}</code>`).join("")}
                </div>
              </td>
              <td>
                <div style="font-size:12px;color:var(--ink2)">${ch.plazaMetrics}</div>
              </td>
              <td>
                <div style="margin-bottom:5px">
                  <span class="chip ${ch.verifyTone}" style="white-space:normal;text-align:left;line-height:1.35">${ch.verifySummary}</span>
                </div>
                <div class="muted" style="font-size:11px;line-height:1.45">${ch.verifyDetail}</div>
              </td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

/* ==========================================================================
   View 4: 来源接入与数据同步 (All API Hub, NAS New API, NAS CPA)
   ========================================================================== */
function renderSourcesView() {
  const D = window.HUB_DATA;
  const allDiffs = D.sources.flatMap(s => s.diffs.map(d => ({ ...d, srcName: s.name, badgeClass: s.badgeClass })))
    .filter(d => STATE.diffFilter === "all" || d.type === STATE.diffFilter);

  return `
    <div class="page-header">
      <div>
        <h1>来源接入与数据同步</h1>
        <p>连接浏览器 All API Hub 与 NAS 上的 New API、CPA。看清各来源同步范围、授权健康度、最后更新时间及本次新增或更新明细。</p>
      </div>
      <div>
        <button class="btn pri" id="btnSyncAllSources">
          ${ICONS.sync} ${STATE.syncing ? "正在同步三大来源..." : "立即增量同步全部来源"}
        </button>
      </div>
    </div>

    <div class="sources-grid">
      ${D.sources.map(src => `
        <div class="src-card">
          <div style="display:flex;justify-content:space-between;align-items:flex-start">
            <div>
              <span class="src-pill ${src.badgeClass}" style="font-size:11px">${src.location}</span>
              <h3 class="serif" style="font-size:21px;margin:6px 0 2px">${src.name}</h3>
            </div>
            <span class="chip ${src.authStatus === 'ok' ? 'olive' : 'ochre'}">
              ${src.authStatus === 'ok' ? '● 授权正常' : '● 凭证预警'}
            </span>
          </div>

          <dl class="src-dl">
            <dt>授权状态</dt>
            <dd>
              <b>${src.authText}</b>
              <div class="muted" style="font-size:11px">${src.authDetail}</div>
            </dd>
            <dt>最后更新</dt>
            <dd>
              <b>${src.lastSync}</b>
              <div class="muted" style="font-size:11px">${src.syncFreq}</div>
            </dd>
            <dt>能同步什么</dt>
            <dd>
              <div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:2px">
                ${src.capabilities.map(c => `<span class="chip" style="font-size:10.5px;padding:1px 7px">${c}</span>`).join("")}
              </div>
            </dd>
          </dl>

          <div class="diff-box" style="margin-top:auto">
            <div style="font-weight:600;color:var(--ink);margin-bottom:2px">本次同步新增 / 更新：</div>
            ${src.diffs.map(d => `
              <div style="display:flex;gap:6px;align-items:baseline">
                <span class="chip ${d.type === 'add' ? 'olive' : (d.type === 'upd' ? 'sky' : 'clay')}" style="font-size:10px;padding:0 5px">${d.tag}</span>
                <span style="color:var(--ink2)">${d.text}</span>
              </div>
            `).join("")}
          </div>

          <div style="display:flex;justify-content:space-between;align-items:center;padding-top:8px;border-top:1px solid var(--line-subtle)">
            <button class="btn sm" data-sync-one="${src.id}">${ICONS.sync} 单独同步</button>
            <button class="btn sm ghost" data-auth-check="${src.id}">校验授权连通性</button>
          </div>
        </div>
      `).join("")}
    </div>

    <!-- Unified Sync Diff Changelog Stream -->
    <div class="timeline-card">
      <div class="sec-bar">
        <div class="sec-title">
          <h2>本次同步变更流水 (Changelog)</h2>
          <span class="sec-sub">确定性的站点去重、余额对齐与模型目录比对已由系统自动完成</span>
        </div>
        <div class="seg">
          <button class="${STATE.diffFilter === 'all' ? 'on' : ''}" data-dfilter="all">全部变更</button>
          <button class="${STATE.diffFilter === 'add' ? 'on' : ''}" data-dfilter="add">新增站点 / Key</button>
          <button class="${STATE.diffFilter === 'upd' ? 'on' : ''}" data-dfilter="upd">余额与路由更新</button>
          <button class="${STATE.diffFilter === 'warn' ? 'on' : ''}" data-dfilter="warn">预警与隔离</button>
        </div>
      </div>

      <div style="display:flex;flex-direction:column;gap:8px">
        ${allDiffs.map(d => `
          <div style="display:flex;align-items:center;gap:10px;padding:9px 12px;background:var(--bg);border:1px solid var(--line);border-radius:8px">
            <span class="src-pill ${d.badgeClass}">${d.srcName}</span>
            <span class="chip ${d.type === 'add' ? 'olive' : (d.type === 'upd' ? 'sky' : 'clay')}">${d.tag}</span>
            <span style="font-size:12.5px;color:var(--ink)">${d.text}</span>
            <span class="mono muted" style="margin-left:auto">${d.time}</span>
          </div>
        `).join("")}
      </div>
    </div>
  `;
}

/* ==========================================================================
   Modals for Core Experience 5: 少量人工维护 (补 Key、编辑资料、合并重复站点)
   ========================================================================== */
function closeModal() {
  const m = $("#modalRoot");
  if (m) m.innerHTML = "";
}

function openModelInspectModal(modelId) {
  const m = window.HUB_DATA.models.find(x => x.id === modelId);
  if (!m) return;
  $("#modalRoot").innerHTML = `
    <div class="modal-backdrop" onclick="if(event.target===this)closeModal()">
      <div class="modal-panel" style="max-width:680px">
        <div class="modal-head">
          <div>
            <span class="chip ${m.tier === 'strong' ? 'clay' : 'olive'}" style="margin-bottom:4px">
              ${m.tier === 'strong' ? '◆ 强模型 · 决策与复杂推理' : '● 执行模型 · 高吞吐与自动化'}
            </span>
            <h3 class="mono">${m.name} · 选型判断依据明细</h3>
          </div>
          <button class="btn sm ghost" onclick="closeModal()">✕ 关闭</button>
        </div>

        <div style="padding:11px 13px;background:var(--sunk);border-radius:10px;margin-bottom:14px;font-size:12.5px">
          <b>中心结论：</b>${m.verdict}<br/>
          <span class="muted">${m.callerHint}</span>
        </div>

        <div style="font-weight:600;font-size:12.5px;margin-bottom:8px">各渠道实测表现与消耗优先级排序：</div>
        <div style="display:flex;flex-direction:column;gap:8px;margin-bottom:16px">
          ${m.routes.map(r => `
            <div style="padding:10px 12px;border-radius:10px;border:1px solid ${r.status === 'warn' ? 'var(--rose-border)' : 'var(--line)'};background:${r.status === 'warn' ? '#FDF8F8' : 'var(--bg)'}">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
                <div>
                  <span class="route-rank" style="${r.status === 'best' ? 'background:var(--olive);color:#fff' : ''}">${r.rank}</span>
                  <b style="margin-left:6px">${r.siteName}</b>
                  <span class="muted" style="font-size:11.5px;margin-left:6px">${r.account}</span>
                </div>
                <span class="mono" style="font-size:11.5px;font-weight:600">${r.quotaText}</span>
              </div>
              <div style="display:flex;justify-content:space-between;font-size:11.5px;color:var(--ink2)">
                <span>网关来源：${r.source} · ${r.metrics}</span>
                <span style="color:${r.status === 'warn' ? 'var(--rose)' : 'var(--olive)'};font-weight:600">${r.evidence}</span>
              </div>
            </div>
          `).join("")}
        </div>

        <div style="display:flex;justify-content:flex-end;gap:8px">
          <button class="btn" onclick="closeModal()">关闭</button>
          <button class="btn pri" onclick="closeModal();switchView('scan')">前往扫描与验证工作台 →</button>
        </div>
      </div>
    </div>
  `;
}

function openAddKeyModal(siteId) {
  const site = window.HUB_DATA.sites.find(s => s.id === siteId) || window.HUB_DATA.sites[3];
  const acct = site.accounts[0];
  $("#modalRoot").innerHTML = `
    <div class="modal-backdrop" onclick="if(event.target===this)closeModal()">
      <div class="modal-panel">
        <div class="modal-head">
          <h3>补全渠道 API Key · ${site.name}</h3>
          <button class="btn sm ghost" onclick="closeModal()">✕ 关闭</button>
        </div>
        <p class="muted" style="margin:0 0 14px">
          当浏览器扩展同步了站点账号余额但未获取到令牌，或原有 Key 401 失效时，在此补充并自动同步至 NAS New API / CPA。
        </p>
        <div class="form-row">
          <label>归属站点与独立账号</label>
          <input class="form-input" value="${site.name} (${site.url}) · 账号 ${acct.username} [$${acct.permBalance.toFixed(2)}]" disabled />
        </div>
        <div class="form-row">
          <label>API Key (sk-...)</label>
          <div style="display:flex;gap:8px">
            <input id="inpNewKey" class="form-input mono" style="flex:1" placeholder="粘贴 sk- 开头的令牌..." value="sk-aur-98f1c4b2e019a77d3310fa" />
            <button class="btn sm" type="button" onclick="$('#inpNewKey').value='sk-aur-98f1c4b2e019a77d3310fa'">填入示例 Key</button>
          </div>
        </div>
        <div class="form-row">
          <label>分组备注与下行同步目标</label>
          <input id="inpKeyName" class="form-input" value="极光-主号默认Key (自动推送至 NAS New API)" />
        </div>
        <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:18px">
          <button class="btn" onclick="closeModal()">取消</button>
          <button class="btn clay" id="btnConfirmAddKey">保存 Key 并扫描模型目录</button>
        </div>
      </div>
    </div>
  `;

  $("#btnConfirmAddKey").onclick = () => {
    const raw = $("#inpNewKey").value.trim() || "sk-aur...10fa";
    const masked = raw.slice(0, 6) + "..." + raw.slice(-4);
    acct.keys.push({ name: "极光主Key", masked, group: "Default", status: "ok" });
    acct.keysCount = acct.keys.length;
    acct.signinStatus = "今日已签到 (+$2.00) · Key 正常";
    acct.signinTone = "olive";
    site.status = "ok";
    site.statusText = "200 OK · 132ms";
    if (!site.sources.includes("NAS · New API")) site.sources.push("NAS · New API");
    window.HUB_DATA.triageItems = window.HUB_DATA.triageItems.filter(t => t.id !== "tri-key");
    closeModal();
    renderAll();
    showToast(`已为「${site.name}」补全 Key (${masked})，并同步挂载至 NAS New API`);
  };
}

function openEditSiteModal(siteId) {
  const site = window.HUB_DATA.sites.find(s => s.id === siteId);
  if (!site) return;
  const acct = site.accounts[0];
  $("#modalRoot").innerHTML = `
    <div class="modal-backdrop" onclick="if(event.target===this)closeModal()">
      <div class="modal-panel">
        <div class="modal-head">
          <h3>编辑站点资料 · ${site.name}</h3>
          <button class="btn sm ghost" onclick="closeModal()">✕ 关闭</button>
        </div>
        <div class="form-row">
          <label>站点名称</label>
          <input id="editSiteName" class="form-input" value="${site.name}" />
        </div>
        <div class="form-row">
          <label>主接口地址 (Base URL)</label>
          <input id="editSiteUrl" class="form-input mono" value="${site.url}" />
        </div>
        <div class="form-row">
          <label>有效期说明</label>
          <input id="editSiteValid" class="form-input" value="${site.validity}" />
        </div>
        <div class="form-row">
          <label>使用限制与调用注意</label>
          <input id="editSiteRestr" class="form-input" value="${site.restrictions}" />
        </div>
        <div class="form-row">
          <label>签到余额上限门槛 ($)</label>
          <input id="editSiteThresh" type="number" step="0.5" class="form-input mono" value="${acct.thresholdCap}" />
        </div>
        <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:18px">
          <button class="btn" onclick="closeModal()">取消</button>
          <button class="btn pri" id="btnSaveSiteEdit">保存修改</button>
        </div>
      </div>
    </div>
  `;

  $("#btnSaveSiteEdit").onclick = () => {
    site.name = $("#editSiteName").value.trim() || site.name;
    site.url = $("#editSiteUrl").value.trim() || site.url;
    site.validity = $("#editSiteValid").value.trim() || site.validity;
    site.restrictions = $("#editSiteRestr").value.trim() || site.restrictions;
    const cap = parseFloat($("#editSiteThresh").value);
    if (!isNaN(cap)) site.accounts.forEach(a => a.thresholdCap = cap);
    closeModal();
    renderAll();
    showToast(`已更新「${site.name}」的资料与门槛规则`);
  };
}

function openMergeModal(siteId) {
  const site = window.HUB_DATA.sites.find(s => s.id === siteId) || window.HUB_DATA.sites.find(s => s.duplicateCandidate);
  if (!site || !site.duplicateCandidate) {
    showToast("当前没有待合并的重复站点");
    return;
  }
  const dup = site.duplicateCandidate;
  $("#modalRoot").innerHTML = `
    <div class="modal-backdrop" onclick="if(event.target===this)closeModal()">
      <div class="modal-panel">
        <div class="modal-head">
          <h3>合并重复站点 · 跨来源同源识别</h3>
          <button class="btn sm ghost" onclick="closeModal()">✕ 关闭</button>
        </div>
        <div style="padding:10px 12px;background:var(--sky-t);border:1px solid var(--sky-border);border-radius:8px;font-size:12px;color:var(--ink);margin-bottom:14px">
          <b>系统识别依据：</b>${dup.reason}
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px">
          <div style="padding:12px;background:var(--bg);border:1px solid var(--line);border-radius:10px">
            <div class="chip olive" style="margin-bottom:6px">保留为主站点 (All API Hub)</div>
            <div style="font-weight:600;font-size:14px">${site.name}</div>
            <div class="mono muted" style="margin:4px 0">${site.url}</div>
            <div style="font-size:12px">现有账号：<b>neko_wk</b> ($7.80 + 今日 $2.00)</div>
          </div>
          <div style="padding:12px;background:var(--bg);border:1px dashed var(--clay);border-radius:10px">
            <div class="chip clay" style="margin-bottom:6px">并入主站点 (${dup.dupSource})</div>
            <div style="font-weight:600;font-size:14px">${dup.dupName}</div>
            <div class="mono muted" style="margin:4px 0">${dup.dupUrl}</div>
            <div style="font-size:12px">独立账号：<b>${dup.dupAccount}</b></div>
          </div>
        </div>
        <p class="muted" style="font-size:12px;margin:0 0 16px">
          合并后：站点统一展示为「${site.name}」，<code>${dup.dupUrl}</code> 转为备用域名；两个独立账号及各自余额 ($7.80 与 $3.40) 完整保留。
        </p>
        <div style="display:flex;justify-content:flex-end;gap:8px">
          <button class="btn" onclick="closeModal()">暂不合并</button>
          <button class="btn clay" id="btnConfirmMerge">${ICONS.merge} 确认合并并保留双账号</button>
        </div>
      </div>
    </div>
  `;

  $("#btnConfirmMerge").onclick = () => {
    site.accounts.push({
      id: "acc-nk-2",
      username: "neko_nas_legacy",
      label: "NAS 合并账号",
      permBalance: 3.40,
      dailyQuota: 0.00,
      dailyExpireAt: "长期有效",
      signinStatus: "已并入主站统一监控",
      signinTone: "olive",
      thresholdCap: 12.00,
      keysCount: 1,
      keys: [{ name: "NAS旧渠道Key", masked: "sk-neko...09c2", group: "Default", status: "ok" }]
    });
    site.sources = ["All API Hub", "NAS · New API"];
    site.mirrorUrl = "https://relay.nekoapi.com";
    site.statusText = "200 OK · 双来源已聚合";
    delete site.duplicateCandidate;
    window.HUB_DATA.triageItems = window.HUB_DATA.triageItems.filter(t => t.id !== "tri-merge");
    closeModal();
    renderAll();
    showToast("已合并「ネコ公益」与「NekoRelay」，双账号独立余额均已保留");
  };
}

/* ---------- Switch View & Bind View Events ---------- */
function switchView(viewId) {
  STATE.view = viewId;
  $$(".scenario-nav button").forEach(b => b.classList.toggle("on", b.dataset.scen === viewId));
  renderAll();
}

function bindViewEvents() {
  const page = $("#viewPage");

  // Perspective buttons in View 1
  $$("[data-persp]", page).forEach(b => {
    b.onclick = () => {
      STATE.resPerspective = b.dataset.persp;
      renderMainView();
    };
  });

  // Site filter buttons in View 1
  $$("[data-sfilter]", page).forEach(b => {
    b.onclick = () => {
      STATE.siteFilter = b.dataset.sfilter;
      renderMainView();
    };
  });

  // Copy model config
  $$("[data-copy-model]", page).forEach(b => {
    b.onclick = (e) => {
      e.stopPropagation();
      const m = window.HUB_DATA.models.find(x => x.id === b.dataset.copyModel);
      if (m) {
        const best = m.routes[0];
        showToast(`已复制 ${m.id} 推荐配置：优先走「${best.siteName}」(${best.quotaText})`);
      }
    };
  });

  // Model card inspect modal (次要信息按需展开)
  $$("[data-model-inspect]", page).forEach(card => {
    card.onclick = () => openModelInspectModal(card.dataset.modelInspect);
  });

  // Site maintenance actions
  $$("[data-add-key]", page).forEach(b => b.onclick = () => openAddKeyModal(b.dataset.addKey));
  $$("[data-edit-site]", page).forEach(b => b.onclick = () => openEditSiteModal(b.dataset.editSite));
  $$("[data-merge-site]", page).forEach(b => b.onclick = () => openMergeModal(b.dataset.mergeSite));
  $$("[data-scan-one]", page).forEach(b => b.onclick = () => {
    const s = window.HUB_DATA.sites.find(x => x.id === b.dataset.scanOne);
    if (s) showToast(`已发起对「${s.name}」的站点连通性与 Key 模型目录扫描`);
  });

  // View 2: Cron binding select
  $$("[data-cron-bind]", page).forEach(sel => {
    sel.onchange = () => {
      const job = window.HUB_DATA.cronJobs.find(j => j.id === sel.dataset.cronBind);
      const win = window.HUB_DATA.quotaWindows.find(w => w.id === sel.value);
      if (job && win) {
        job.boundWinId = win.id;
        renderMainView();
        const ok = job.runHour >= win.winStart && job.runHour <= win.winEnd;
        showToast(ok
          ? `已将「${job.name}」绑定至「${win.siteName}」，触发时刻落入可用窗口`
          : `注意：「${job.name}」(${job.runTimeText}) 偏离「${win.siteName}」的可用窗口！`);
      }
    };
  });

  // View 3: Scan & Verify
  $$("[data-tpl]", page).forEach(card => {
    card.onclick = () => {
      STATE.selectedTemplateId = card.dataset.tpl;
      renderMainView();
    };
  });

  $$("[data-ch-check]", page).forEach(chk => {
    chk.onchange = () => {
      const ch = window.HUB_DATA.scanChannels.find(c => c.id === chk.dataset.chCheck);
      if (ch) ch.checked = chk.checked;
      renderMainView();
    };
  });

  const btnSelectAll = $("#btnSelectAllCh", page);
  if (btnSelectAll) {
    btnSelectAll.onclick = () => {
      const allChecked = window.HUB_DATA.scanChannels.every(c => c.checked);
      window.HUB_DATA.scanChannels.forEach(c => c.checked = !allChecked);
      renderMainView();
    };
  }

  const btnBatchScan = $("#btnBatchScan", page);
  if (btnBatchScan) {
    btnBatchScan.onclick = () => {
      STATE.scanning = true;
      renderMainView();
      setTimeout(() => {
        STATE.scanning = false;
        window.HUB_DATA.scanChannels.forEach(c => {
          if (c.checked) c.lastScanAt = "刚刚";
        });
        renderMainView();
        showToast("批量扫描完成：已更新选中渠道的网站访问状态、Key 模型目录与模型广场指标");
      }, 650);
    };
  }

  const btnRunVerify = $("#btnRunVerify", page);
  if (btnRunVerify) {
    btnRunVerify.onclick = () => {
      const tpl = window.HUB_DATA.verifyTemplates.find(t => t.id === STATE.selectedTemplateId);
      STATE.verifying = true;
      renderMainView();
      setTimeout(() => {
        STATE.verifying = false;
        window.HUB_DATA.liveChecks[0].progress = 100;
        window.HUB_DATA.liveChecks[0].title = `已完成「${tpl.name}」实测 (3/3 完成)`;
        renderAll();
        showToast(`实测完成：已用「${tpl.name}」检验选中渠道，结果已同步至模型选型依据`);
      }, 750);
    };
  }

  const btnScheduleIdle = $("#btnScheduleIdle", page);
  if (btnScheduleIdle) {
    btnScheduleIdle.onclick = () => {
      showToast("已将选中渠道的实际任务验证排入 01:00 夜间低峰窗口执行");
    };
  }

  // View 4: Sources sync & filter
  $$("[data-dfilter]", page).forEach(b => {
    b.onclick = () => {
      STATE.diffFilter = b.dataset.dfilter;
      renderMainView();
    };
  });

  const btnSyncAll = $("#btnSyncAllSources", page);
  if (btnSyncAll) {
    btnSyncAll.onclick = () => triggerGlobalSync();
  }

  $$("[data-sync-one]", page).forEach(b => {
    b.onclick = () => {
      const src = window.HUB_DATA.sources.find(s => s.id === b.dataset.syncOne);
      if (src) {
        src.lastSync = "刚刚";
        renderAll();
        showToast(`已完成「${src.name}」增量数据同步`);
      }
    };
  });

  $$("[data-auth-check]", page).forEach(b => {
    b.onclick = () => {
      const src = window.HUB_DATA.sources.find(s => s.id === b.dataset.authCheck);
      if (src) showToast(`${src.name} 连通性校验：${src.authText}`);
    };
  });
}

function triggerGlobalSync() {
  STATE.syncing = true;
  renderMainView();
  setTimeout(() => {
    STATE.syncing = false;
    window.HUB_DATA.sources.forEach(s => s.lastSync = "刚刚 (19:28)");
    window.HUB_DATA.sources[0].diffs.unshift({
      type: "upd",
      tag: "增量校验",
      text: "全站余额与签到状态二次核对完成，未发现未入账签到",
      time: "19:28"
    });
    renderAll();
    showToast("三大来源 (All API Hub / New API / CPA) 增量同步已完成");
  }, 600);
}

function renderMainView() {
  const container = $("#viewPage");
  if (STATE.view === "resources") {
    container.innerHTML = renderResourcesView();
  } else if (STATE.view === "equity") {
    container.innerHTML = renderEquityView();
  } else if (STATE.view === "scan") {
    container.innerHTML = renderScanView();
  } else if (STATE.view === "sources") {
    container.innerHTML = renderSourcesView();
  }
  bindViewEvents();
}

function renderAll() {
  renderSidebar();
  renderTopAndTriage();
  renderMainView();
}

/* ---------- Boot ---------- */
window.addEventListener("DOMContentLoaded", () => {
  // Search box binding
  const searchInp = $("#globalSearchInput");
  if (searchInp) {
    searchInp.addEventListener("input", () => {
      STATE.searchQuery = searchInp.value;
      if (STATE.view !== "resources") {
        STATE.view = "resources";
        renderSidebar();
      }
      renderMainView();
    });
  }

  // Top scenario navigation bar
  $$(".scenario-nav button").forEach(btn => {
    btn.onclick = () => {
      const sc = btn.dataset.scen;
      if (sc === "maint") {
        switchView("resources");
        openMergeModal("site-neko");
      } else {
        switchView(sc);
      }
    };
  });

  // Top bar quick buttons
  const topSyncBtn = $("#topSyncBtn");
  if (topSyncBtn) topSyncBtn.onclick = () => triggerGlobalSync();

  const topScanBtn = $("#topScanBtn");
  if (topScanBtn) topScanBtn.onclick = () => switchView("scan");

  // Keyboard shortcut Cmd+K / Ctrl+K focuses search
  window.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      if (searchInp) searchInp.focus();
    }
    if (e.key === "Escape") closeModal();
  });

  renderAll();
});
