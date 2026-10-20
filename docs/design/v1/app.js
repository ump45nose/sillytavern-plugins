/* ============ 工具 ============ */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const withVT = fn => (document.startViewTransition && !reduced) ? document.startViewTransition(fn) : fn();

function countUp(root) {
  if (reduced || document.documentElement.classList.contains('static')) return;
  $$('.cnt', root).forEach(el => {
    const v = +el.dataset.v, d = +el.dataset.d || 0, pre = el.dataset.pre || '', suf = el.dataset.suf || '';
    const t0 = performance.now(), dur = 950 + Math.min(500, v.toString().length * 60);
    const step = t => {
      const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 4);
      el.textContent = pre + fmtN(v * e, d) + suf;
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
}
function movePill(container, active) {
  const pill = $('.pill', container);
  if (!pill || !active) return;
  if (container.classList.contains('doc-tabs')) { pill.style.left = active.offsetLeft + 'px'; pill.style.width = active.offsetWidth + 'px'; }
  else { pill.style.top = active.offsetTop + 'px'; pill.style.height = active.offsetHeight + 'px'; }
}

/* ============ 页面定义：页面只是模块的组合 ============ */
const PAGES = {
  home: { t: '主页', layout: [['brief', 'd'], ['agenda', 'd'], ['goals', 'd'], ['attention', 'c'], ['health', 'c'], ['bills', 'c'], ['crm', 'c'], ['token', 'c'], ['net', 'c'], ['git', 'c'], ['sky', 'c'], ['memos', 'c']] },
  life: { t: '生活', sub: '健康、账单、交流与媒体', layout: [['health', 'd'], ['bills', 'd'], ['crm', 'd'], ['media', 'd', 6]] },
  usage: { t: '用量', sub: 'Token、GitHub、网络与订阅', layout: [['token', 'd'], ['git', 'd', 12], ['net', 'd'], ['subs', 'd']] },
  sky: { t: '电脑历史', sub: 'MacPro 与 MacAir 的 6 小时窗口摘要', custom: 'sky' },
  memos: { t: 'Memos', sub: '直接嵌入 Memos · ⌃⌥M 随时记录', custom: 'memos' },
};
const NAV = [['home', '主页', 'home', '⌘1'], ['life', '生活', 'life', '⌘2'], ['usage', '用量', 'usage', '⌘3'], ['sky', '电脑历史', 'sky', '⌘4'], ['memos', 'Memos', 'memos', '⌘5']];
let cur = 'home', editing = false, skySel = 0;

/* ============ 模块渲染 ============ */
function modHTML(id, sz, span, idx, { vt = true, k = 0 } = {}) {
  const m = MODS[id];
  const sp = sz === 'd' && span ? span : (sz === 'c' ? m.span.c : m.span.d);
  const tools = `<div class="edit-mv"><button data-mv="-1">←</button><button data-mv="1">→</button></div>
    <div class="m-sz"><button data-sz="c" class="${sz === 'c' ? 'on' : ''}">简</button><button data-sz="d" class="${sz === 'd' ? 'on' : ''}">详</button></div><button class="m-more">${I.more}</button>`;
  const head = m.bare ? `<div class="m-tools" style="position:absolute;top:0;right:0">${tools}</div>`
    : `<header class="m-head"><span class="m-ico">${I[m.icon]}</span><span class="m-title">${m.title}</span><span class="m-meta">${m.meta}</span>${m.stamp ? `<span class="m-stamp">${m.stamp}</span>` : ''}<div class="m-tools">${tools}</div></header>`;
  const cls = ['m', sz === 'c' ? 'c' : '', m.autoH && sz === 'c' ? 'auto' : '', m.bare ? 'brief' : '', 's' + sp].join(' ');
  return `<article class="${cls}" data-id="${id}" data-idx="${idx}" style="${T(m.tone)};--k:${k}${vt ? `;view-transition-name:vt-${id}` : ''}"><button class="edit-x" data-rm>×</button>${head}<div class="m-body">${m[sz]()}</div></article>`;
}

function toolbar() {
  const p = PAGES[cur];
  return `<div class="toolbar"><span class="crumb">Personal Hub / <b>${p.t}</b></span>
    <div class="search">${I.search}<span>搜索任务、交流、Memo…</span><kbd>⌘K</kbd></div>
    <button class="tbtn" id="sync">${I.sync}<span id="stamp">17:58</span></button>
    ${p.custom ? '' : `<button class="tbtn ${editing ? 'on' : ''}" id="edit">${I.grid}<span>${editing ? '完成' : '编辑布局'}</span></button>`}</div>`;
}

function renderNav() {
  const nav = $('#nav');
  nav.innerHTML = `<div class="pill"></div>` + NAV.map(n => `<button data-p="${n[0]}" class="${n[0] === cur ? 'on' : ''}"><span class="ic">${I[n[2]]}</span>${n[1]}<kbd>${n[3]}</kbd></button>`).join('')
    + `<div class="grp">自定义</div><button class="ghost" title="后续支持">${'<span class="ic">' + I.plus + '</span>'}新建页面</button>`;
  requestAnimationFrame(() => movePill(nav, $('button.on', nav)));
  $$('button[data-p]', nav).forEach(b => b.onclick = () => go(b.dataset.p));
}

function go(p) {
  if (p === cur) return;
  cur = p; editing = false;
  $$('#nav button[data-p]').forEach(b => b.classList.toggle('on', b.dataset.p === cur));
  movePill($('#nav'), $('#nav button.on'));
  withVT(() => renderMain(true));
  $('#main').scrollTop = 0;
}

function renderMain(anim) {
  const main = $('#main'), p = PAGES[cur];
  if (p.custom === 'sky') { main.innerHTML = toolbar() + `<div class="page">${pageHead(p)}${skyPage()}</div>`; bindChrome(); bindSky(); return; }
  if (p.custom === 'memos') { main.innerHTML = toolbar() + `<div class="page">${pageHead(p)}${memosPage()}</div>`; bindChrome(); return; }
  const unused = Object.keys(MODS).filter(k => !p.layout.some(l => l[0] === k));
  main.innerHTML = toolbar() + `<div class="page ${editing ? 'editing' : ''}">${cur === 'home' ? '' : pageHead(p)}
    <div class="grid ${anim ? 'enter' : ''}">${p.layout.map((l, i) => modHTML(l[0], l[1], l[2], i, { k: i })).join('')}
    <div class="add-tile"><b>添加模块</b><span class="muted" style="margin-left:8px">每个模块都有简略版和详细版，可放在任意页面</span>
      <div class="opts">${unused.map(k => `<button class="chip" data-add="${k}"><span style="width:14px;height:14px;display:inline-block">${I[MODS[k].icon]}</span>${MODS[k].title}</button>`).join('') || '<span class="muted">所有模块都已在此页</span>'}</div></div></div></div>`;
  bindChrome(); bindGrid(); countUp(main);
}
const pageHead = p => `<div class="page-h"><div><h2>${p.t}</h2><p>${p.sub || ''}</p></div><span class="r">${p.layout ? p.layout.length + ' 个模块 · ' : ''}更新于 17:58</span></div>`;

function bindChrome() {
  const s = $('#sync');
  if (s) s.onclick = () => { s.classList.remove('spin'); void s.offsetWidth; s.classList.add('spin'); setTimeout(() => { $('#stamp').textContent = '刚刚'; countUp($('#main')); }, 600); };
  const e = $('#edit');
  if (e) e.onclick = () => { editing = !editing; withVT(() => renderMain(false)); };
}

function bindGrid() {
  const grid = $('.grid', $('#main')), lay = PAGES[cur].layout;
  grid.addEventListener('click', ev => {
    const art = ev.target.closest('article.m'); const t = ev.target.closest('button');
    if (ev.target.closest('.task')) { ev.target.closest('.task').classList.toggle('done'); return; }
    const goA = ev.target.closest('[data-go]');
    if (goA) { const el = $(`article[data-id="${goA.dataset.go}"]`, grid); if (el) { el.scrollIntoView({ behavior: 'smooth', block: 'center' }); el.animate([{ boxShadow: '0 0 0 0 rgba(217,119,87,.5)' }, { boxShadow: '0 0 0 10px rgba(217,119,87,0)' }], { duration: 900, iterations: 2 }); } return; }
    const gp = ev.target.closest('[data-go-page]'); if (gp) { go(gp.dataset.goPage); return; }
    if (t && t.dataset.add) { lay.push([t.dataset.add, 'c']); withVT(() => renderMain(false)); return; }
    if (!art || !t) return;
    const idx = +art.dataset.idx;
    if (t.dataset.sz) {
      if (lay[idx][1] === t.dataset.sz) return;
      lay[idx][1] = t.dataset.sz;
      withVT(() => {
        const tmp = document.createElement('div'); tmp.innerHTML = modHTML(lay[idx][0], lay[idx][1], lay[idx][2], idx);
        const n = tmp.firstElementChild; art.replaceWith(n); countUp(n);
      });
    } else if (t.dataset.mv) {
      const j = idx + +t.dataset.mv; if (j < 0 || j >= lay.length) return;
      [lay[idx], lay[j]] = [lay[j], lay[idx]]; withVT(() => renderMain(false));
    } else if (t.hasAttribute('data-rm')) { lay.splice(idx, 1); withVT(() => renderMain(false)); }
  });
}

document.addEventListener('click', ev => {
  const op = ev.target.closest('[data-opt]'), art = op && op.closest('article.m');
  if (!art) return;
  const m = MODS[art.dataset.id], [k, v] = op.dataset.opt.split(':');
  if (m.state[k] === v) return;
  m.state[k] = v;
  const body = $('.m-body', art);
  body.innerHTML = m[art.classList.contains('c') ? 'c' : 'd']();
  countUp(body);
});

const tip = Object.assign(document.createElement('div'), { className: 'tip' });
document.body.appendChild(tip);
document.addEventListener('mouseover', ev => {
  const el = ev.target.closest('[data-tip]');
  if (!el) { tip.classList.remove('on'); return; }
  const r = el.getBoundingClientRect();
  tip.textContent = el.dataset.tip;
  tip.style.left = r.left + r.width / 2 + 'px'; tip.style.top = r.top + 'px';
  tip.classList.add('on');
});

/* ============ 电脑历史 & Memos 整页 ============ */
function skyPage() {
  let lastY = null;
  const list = D.sky.map((s, i) => {
    const hdr = lastY !== !!s.y ? `<div class="sky-day">${s.y ? '昨天 · 10 月 19 日' : '今天 · 10 月 20 日'}</div>` : ''; lastY = !!s.y;
    return hdr + `<div class="sky-it ${i === skySel ? 'on' : ''}" data-i="${i}"><div class="tm">${s.tm} – ${s.te} · ${s.dev}</div><b>${s.t}</b><p>${s.d}</p><div class="appdots">${s.apps.map(c => `<i style="--c:${c}"></i>`).join('')}</div></div>`;
  }).join('');
  return `<div class="sky-page"><div class="sky-list">${list}</div><div class="sky-detail" id="skyd">${skyDetail()}</div></div>`;
}
function skyDetail() {
  const s = D.sky[skySel], names = ['Cursor', 'Chrome', '终端', 'Telegram'];
  return `<div class="inner" style="view-transition-name:skyd"><div class="row" style="gap:8px"><span class="chip t" style="${T('steel')}">${s.dev}</span><span class="muted">${s.tm} – ${s.te} · 6 小时摘要</span></div>
    <h3>${s.t}</h3><div class="lead">${s.d}</div>
    <div class="usage-bar">${s.u.map((u, i) => `<i style="flex:${u};background:${s.apps[i]};animation-delay:${i * 80}ms"></i>`).join('')}</div>
    <div class="legend">${s.u.map((u, i) => `<span style="--c:${s.apps[i]}">${names[i] || '其他'} ${u}%</span>`).join('')}</div>
    <h4>主要活动</h4><ul><li>阅读旧 Hub 归档与四个采集仓库的 README，确认各来源的接口形态。</li><li>通过 SSH 只读核对 NAS 上 Hermes 的定时任务与 personal-review 的阶段模型。</li><li>重做模块库：每个模块定义简略与详细两种形态，页面只做组合。</li></ul>
    <h4>决定</h4><ul><li>平台为 Mac + 安卓；Google 只在 Mac 端接入。</li><li>任务与复盘目标并入主页；数据按模块组装，不按领域。</li></ul>
    <h4>未完成</h4><ul><li>安卓端的布局适配。</li><li>后端接口契约。</li></ul>
    <div class="muted" style="margin-top:28px;font-size:11px;font-family:var(--mono)">archive/macpro/2026-10-20T04-00.md</div></div>`;
}
function bindSky() {
  $$('.sky-it').forEach(e => e.onclick = () => {
    skySel = +e.dataset.i;
    $$('.sky-it').forEach(x => x.classList.toggle('on', x === e));
    withVT(() => { $('#skyd').innerHTML = skyDetail(); });
  });
}
function memosPage() {
  return `<div class="webview"><div class="wv-bar"><span>‹ ›</span><span>⟳</span><div class="wv-url">🔒 memos.home:5230</div><span>已登录 · 玮康</span></div>
    <div class="wv-body"><div class="wv-side"><b style="color:#222">玮康</b><br><span style="color:#999">232 条 Memo</span><br><br><b style="color:#222">标签</b><br># 日报 <span style="color:#bbb">96</span><br># 周报 <span style="color:#bbb">14</span><br># 主线 <span style="color:#bbb">1</span><br># 阶段目标 <span style="color:#bbb">15</span><br># 阶段总结 <span style="color:#bbb">2</span><br># 想法 <span style="color:#bbb">58</span></div>
    <div class="wv-feed"><div class="wv-memo" style="color:#aaa;min-height:90px">现在的想法是…</div>
    ${D.memos.map(m => `<div class="wv-memo"><div class="mt">${m[0]}</div>${m[1].replace(/class="tag"/g, 'class="tg"')}</div>`).join('')}
    <div class="wv-memo"><div class="mt">10 月 19 日 21:48</div><span class="tg">#日报</span> 2026-10-19<br><b>情绪</b>：平静 · <b>健康</b>：步数 8,450 · <b>明天唯一重点</b>：定下个人信息中心方向<br>上午修 Plaud 布局迁移，下午部署 personal-records……</div></div></div></div>`;
}

/* ============ 模块库 ============ */
const LIB_ORDER = ['brief', 'agenda', 'goals', 'attention', 'health', 'bills', 'crm', 'media', 'token', 'git', 'net', 'subs', 'sky', 'memos'];
const W = { 3: 284, 4: 380, 5: 476, 6: 572, 7: 668, 12: 1100 };
function renderLib() {
  $('#lib').innerHTML = LIB_ORDER.map(id => {
    const m = MODS[id], s = m.spec;
    const cw = m.span.c === 12 ? '100%' : W[m.span.c] + 'px', dw = m.span.d >= 12 ? '100%' : W[m.span.d] + 'px';
    return `<div class="lib-row"><div class="lib-spec"><div class="row" style="gap:10px;margin-bottom:6px;${T(m.tone)}"><span class="m-ico">${I[m.icon]}</span><h4>${m.title}</h4></div>
      <dl><dt>来源</dt><dd>${s.src}</dd><dt>刷新</dt><dd>${s.refresh}</dd><dt>简略</dt><dd>${s.c}</dd><dt>详细</dt><dd>${s.d}</dd><dt>交互</dt><dd>${s.act}</dd></dl>
      <div class="row" style="gap:6px;margin-top:10px"><span class="chip">简 ${m.span.c} 列</span><span class="chip">详 ${m.span.d} 列</span></div></div>
      <div style="display:flex;flex-wrap:wrap;gap:20px;align-items:flex-start">
        <div style="width:${cw}"><div class="lib-cap">简略</div>${modHTML(id, 'c', null, 0, { vt: false })}</div>
        <div style="width:${dw};max-width:100%"><div class="lib-cap">详细</div>${modHTML(id, 'd', null, 0, { vt: false })}</div>
      </div></div>`;
  }).join('');
  $$('#lib .m').forEach(e => e.style.background = e.classList.contains('brief') ? 'var(--bg)' : '');
  $$('#lib .m.brief').forEach(e => { e.style.padding = '20px 24px'; e.style.borderRadius = '18px'; e.style.border = '1px solid var(--line)'; });
  $('#lib').onclick = ev => { const t = ev.target.closest('.task'); if (t) t.classList.toggle('done'); };
  countUp($('#lib'));
}

/* ============ 菜单栏场景 ============ */
function renderDesk() {
  $('#desk').innerHTML = `<div class="menubar"><b></b><b>Cursor</b><span>文件</span><span>编辑</span><span>视图</span><span>窗口</span>
    <div class="r"><span class="status-item">${mark({ mono: true })}<span>3 · 19:00 羽毛球</span><span class="bd"></span></span><span>⌘</span><span>Wi‑Fi</span><span>周二 17:58</span></div></div>
  <div class="pop">
    <div class="ptabs"><span class="on">今天</span><span>即将</span><span>全部</span></div>
    <div class="row" style="gap:8px;margin-bottom:10px">${D.attention.slice(0, 2).map(a => `<div class="att" style="${T(a.tone)};flex:1;padding:9px 10px;--i:0"><span class="dot"></span><div><b style="font-size:12px">${a.t}</b><span>${a.s}</span></div></div>`).join('')}</div>
    <div class="sect">日程</div>
    <div class="evt" style="position:relative;left:0;right:0;${T('olive')};--i:1"><div class="tm">19:00 – 20:30 · 1 小时后</div><b>羽毛球</b> <span class="tm">· 体育馆 3 号场</span></div>
    <div class="sect">任务 · 3 项到期</div>
    ${[...D.tasks.late.map(t => ({ ...t, late: 1 })), ...D.tasks.today].map(t => `<div class="li task ${t.done ? 'done' : ''}"><span class="cbx">${I.check}</span><div class="tt">${t.t}</div>${t.late ? '<span class="r due late">逾期 1 天</span>' : `<span class="r muted" style="font-size:11px">${t.l}</span>`}</div>`).join('')}
    <div class="mini-in" style="margin-top:10px">${I.plus.replace('<svg', '<svg style="width:14px;height:14px"')}添加任务，例如「明天下午3点 开会」<kbd>⌃⌥Space</kbd></div>
    <div class="mini"><div><div class="lbl">步数</div><div class="v">6,842</div></div><div><div class="lbl">今日支出</div><div class="v">¥128</div></div><div><div class="lbl">Token</div><div class="v">18.6M</div></div><div><div class="lbl">剩余流量</div><div class="v">182G</div></div></div>
    <div class="pop-foot"><span class="row" style="gap:6px">${mark().replace('class="mk', 'style="width:14px;height:14px" class="mk')}打开 Personal Hub</span><span>⌘S 同步 · ⌘, 设置</span></div>
  </div>
  <div class="cap" style="top:44px;right:600px">菜单栏：到期数 · 下一个日程 · 注意点</div>
  <div class="qpanel" id="qtask" style="left:90px;top:250px;animation-delay:.25s">
    <div class="qh"><span class="kbd">⌃⌥Space</span>快速任务<span class="seg"><span class="on">新增</span><span>搜索</span><span>今天</span></span></div>
    <div class="q" id="qtext"><span class="caret"></span></div>
    <div class="nlp" id="qchips" style="margin-top:12px;min-height:24px"></div>
    <div class="qf"><span>↩ 添加</span><span>⌘↩ 添加并打开</span><span>⇥ 切换模式</span><span>Esc 关闭</span></div>
  </div>
  <div class="cap" style="left:90px;top:212px">全局快捷键，任意应用中呼出，回车即走</div>
  <div class="qpanel" style="left:150px;top:560px;width:560px;animation-delay:.5s">
    <div class="qh"><span class="kbd">⌃⌥M</span>快速 Memo<span class="seg"><span class="on">私密</span><span>公开</span></span></div>
    <div class="q" style="font-size:17px;min-height:92px;align-items:flex-start;display:block">方向定下来了：按模块组装，不按领域；任务和复盘目标合进主页。 <mark>#日报</mark></div>
    <div class="qf"><span>⌘↩ 发布到 Memos</span><span>⌘⇧↩ 发布并打开</span><span>Esc 保存草稿</span></div>
  </div>`;
  typeTask();
}
function typeTask() {
  const parts = [['明天下午3点', 1], [' 和李雷对齐迁移方案 ', 0], ['#工作', 1]];
  const box = $('#qtext'), chips = $('#qchips'); if (!box) return;
  const full = parts.map(p => p[0]).join(''); let n = 0;
  const tick = () => {
    n++; let left = n, html = '';
    for (const [s, hl] of parts) { const take = s.slice(0, Math.max(0, left)); left -= s.length; if (!take) break; html += hl ? `<mark>${take}</mark>` : take; }
    box.innerHTML = html + '<span class="caret"></span>';
    if (n === 6) chips.innerHTML = `<span class="chip t" style="${T('sky')};animation:rise .3s var(--ease-out) both">10 月 21 日 周三</span><span class="chip t" style="${T('clay')};animation:rise .3s var(--ease-out) .08s both">15:00 · 同时在日历建时间块</span>`;
    if (n === full.length) chips.innerHTML += `<span class="chip t" style="${T('olive')};animation:rise .3s var(--ease-out) both">清单：工作</span>`;
    if (n < full.length) setTimeout(tick, reduced ? 0 : 55 + Math.random() * 60);
  };
  setTimeout(tick, reduced ? 0 : 700);
}

/* ============ 品牌与规范 ============ */
function renderBrand() {
  const pal = [['陶土 Clay', '#D97757', '主强调 · 主线 · Token'], ['牛皮纸 Kraft', '#C99A6E', '账单'], ['橄榄 Olive', '#7D8F5E', '健康 · Git'], ['天青 Sky', '#6A9BCC', '日程 · Memos'], ['藕荷 Plum', '#9C7BA0', '媒体'], ['鼠尾草 Sage', '#7FA394', '网络'], ['赭石 Ochre', '#C9A23F', '订阅 · 提醒'], ['玫瑰 Rose', '#C97B84', '交流'], ['钢蓝 Steel', '#5F7A99', '电脑历史']];
  $('#brand').innerHTML = `
  <div class="brand-hero"><div id="bigicon" class="hero-mark">${mark({ anim: true })}</div>
    <div><div class="lbl" style="margin-bottom:10px">LOGO · 表盘</div><h3>汇聚，然后看清方向</h3>
      <p>外圈五段长短不一的弧，是汇聚进来的各类个人数据；中心的深色圆是「你」；顶部缺口里的小圆点是「此刻」，像表盘上的指针，也像罗盘的北。</p>
      <p>弧的长短不对称，表达数据是有轻重的；缺口留在正上方，提示每天都从「现在」出发去复盘、定目标。</p>
      <div class="meaning"><div><b>外圈五段</b><span class="muted">数据来源汇聚</span></div><div><b>中心</b><span class="muted">自己</span></div><div><b>顶部圆点</b><span class="muted">此刻 · 方向</span></div></div>
      <button class="tbtn" style="margin-top:18px" id="replayLogo">${I.sync}重播</button></div></div>
  <div class="bcards">
    <div class="bcard"><h4>应用图标 · 无底板</h4><div class="sizes">${[96, 56, 32, 16].map(s => `<div style="text-align:center"><img src="logo.svg" width="${s}" height="${s}"><div class="muted" style="font-size:10px;margin-top:6px">${s}</div></div>`).join('')}</div><span class="muted" style="font-size:11px">图形直接放置，不加圆角底板和阴影</span></div>
    <div class="bcard"><h4>菜单栏图标（模板图）</h4><div class="mbar light">${mark({ mono: true })}<span>3 · 19:00 羽毛球</span></div><div class="mbar dark">${mark({ mono: true })}<span>3 · 19:00 羽毛球</span></div></div>
    <div class="bcard"><h4>浅色 / 深色 / 安卓主题图标</h4><div class="on-bg"><div style="background:#FAF9F5"><img src="logo.svg"></div><div style="background:#262624">${mark({ ink: '#F4F1EA' })}</div><div style="background:#DCE3CC;color:#3E4A2C">${mark({ mono: true })}</div></div><span class="muted" style="font-size:11px">安卓自适应图标背景层透明，主题图标用单色版</span></div>
    <div class="bcard"><h4>字标</h4><div class="row" style="gap:12px"><div style="width:40px;height:40px">${mark()}</div><span class="serif" style="font-size:26px;letter-spacing:-.01em">Personal Hub</span></div><div class="row" style="gap:10px;background:var(--ink);color:#F4F1EA;border-radius:12px;padding:12px 14px"><div style="width:28px;height:28px;color:#F4F1EA">${mark({ mono: true })}</div><span class="serif" style="font-size:20px">Personal Hub</span></div></div>
  </div>
  <h3 class="doc-h" style="margin-top:44px">色彩</h3><p class="doc-p">米色纸张底 + 深墨文字，陶土色作为唯一的主强调色；每个模块分配一个低饱和的大地色，用于图标底色、图表和标签，保证并排时仍然安静。</p>
  <div class="palette">${pal.map(p => `<div class="sw-c"><i style="--c:${p[1]}"></i><div><b>${p[0]}</b>${p[1]}<br>${p[2]}</div></div>`).join('')}</div>
  <div class="type">
    <div class="bcard"><h4>字体 · 衬线（标题与数字）</h4><div class="s1">下午好，玮康 6,842</div><div class="s2">构建可持续的个人系统</div><div class="muted">Source Serif 4 / 宋体回退 · 数字用等宽衬线，适合大号数据展示</div></div>
    <div class="bcard"><h4>字体 · 无衬线（界面）</h4><div style="font-size:20px;font-weight:600">日程与任务 · Token 用量</div><div style="font-size:13px;color:var(--ink2);line-height:1.7">Inter / 苹方。正文 13px，辅助信息 11–12px，模块标题 13px 粗体，页面标题 34px 衬线。</div><div class="row" style="gap:6px"><span class="chip">圆角 18 / 12 / 8</span><span class="chip">栅格 12 列 · 间距 16</span><span class="chip">简略卡高 192</span></div></div>
  </div>
  <h3 class="doc-h" style="margin-top:44px">动效</h3><p class="doc-p">克制、有方向感：元素从下方 12px 轻轻浮起，依次错开 55ms；数字从 0 滚到目标值；图表从基线生长；简略 / 详细切换和页面切换使用 View Transitions 做形变过渡。系统开启「减弱动态效果」时全部关闭。</p>
  <div class="motion">
    <div class="bcard"><h4>页面进入 · 错峰浮现</h4><div class="demo" id="dm1"></div><button class="tbtn" data-demo="1">${I.sync}重播</button><span class="muted" style="font-size:11px">550ms · ease-out · 间隔 55ms</span></div>
    <div class="bcard"><h4>数字滚动</h4><div class="demo" id="dm2"></div><button class="tbtn" data-demo="2">${I.sync}重播</button><span class="muted" style="font-size:11px">~1s · ease-out-quart</span></div>
    <div class="bcard"><h4>图表生长</h4><div class="demo" id="dm3" style="padding:16px"></div><button class="tbtn" data-demo="3">${I.sync}重播</button><span class="muted" style="font-size:11px">800ms · 每根柱子延迟 28ms</span></div>
    <div class="bcard"><h4>简 / 详形变</h4><div class="demo" id="dm4" style="place-items:start;padding:12px"></div><button class="tbtn" data-demo="4">${I.sync}切换</button><span class="muted" style="font-size:11px">View Transitions · 280ms</span></div>
  </div>`;
  const demos = {
    1: () => $('#dm1').innerHTML = `<div class="enter" style="display:grid;grid-template-columns:repeat(3,48px);gap:8px">${Array.from({ length: 6 }, (_, i) => `<div style="--k:${i};height:34px;border-radius:8px;background:${pal[i][1]};opacity:.85"></div>`).join('')}</div>`,
    2: () => { $('#dm2').innerHTML = `<div class="hero"><span class="n" style="font-size:44px">${C(6842)}</span><span class="u">步</span></div>`; countUp($('#dm2')); },
    3: () => $('#dm3').innerHTML = `<div style="width:100%">${bars(D.health.steps14, { h: 70, tone: 'var(--olive)' })}</div>`,
    4: (() => { let big = false; return () => { big = !big; withVT(() => { $('#dm4').innerHTML = `<div style="view-transition-name:demo4;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 12px;width:${big ? '100%' : '55%'};height:${big ? 86 : 52}px"><div class="hero"><span class="n" style="font-size:${big ? 26 : 18}px">¥128.50</span></div>${big ? `<div style="margin-top:8px">${track(86, 'var(--kraft)')}</div>` : ''}</div>`; }); }; })(),
  };
  Object.values(demos).forEach(f => f());
  $$('[data-demo]').forEach(b => b.onclick = () => demos[b.dataset.demo]());
  $('#replayLogo').onclick = () => { const h = $('#bigicon .mk').outerHTML; $('#bigicon .mk').outerHTML = h; };
}

/* ============ 文档外壳 ============ */
const TABS = { app: '#sec-app', lib: '#sec-lib', desk: '#sec-desk', brand: '#sec-brand' };
function showTab(t) {
  $$('.doc-tabs button').forEach(b => b.classList.toggle('on', b.dataset.t === t));
  movePill($('.doc-tabs'), $(`.doc-tabs button[data-t="${t}"]`));
  Object.entries(TABS).forEach(([k, s]) => $(s).classList.toggle('hidden', k !== t));
  if (t === 'lib') renderLib();
  if (t === 'desk') renderDesk();
  if (t === 'brand') renderBrand();
  if (t === 'app') withVT(() => renderMain(true));
}
function boot() {
  $('#brandMark').innerHTML = mark({ anim: true });
  $('#docMark').innerHTML = mark();
  const q = Object.fromEntries(location.hash.slice(1).split('&').filter(Boolean).map(s => s.split('=')));
  if (q.page && PAGES[q.page]) cur = q.page;
  if (q.edit) editing = true;
  if (q.range) MODS.token.state.range = q.range;
  if (q.static) document.documentElement.classList.add('static');
  if (q.tall) document.documentElement.classList.add('tall');
  renderNav();
  $$('.doc-tabs button').forEach(b => b.onclick = () => showTab(b.dataset.t));
  const t = q.tab && TABS[q.tab] ? q.tab : 'app';
  if (t === 'app') { renderMain(true); requestAnimationFrame(() => movePill($('.doc-tabs'), $('.doc-tabs button.on'))); }
  else showTab(t);
  document.addEventListener('keydown', e => {
    if (!(e.metaKey || e.ctrlKey)) return;
    const n = +e.key; if (n >= 1 && n <= NAV.length) { e.preventDefault(); go(NAV[n - 1][0]); }
  });
}
document.fonts ? document.fonts.ready.then(boot) : boot();
