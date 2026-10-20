/* ============ 基础件 ============ */
const svgI = p => `<svg class="i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`;
const I = {
  brief: svgI('<circle cx="12" cy="12" r="4"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6 7 7M17 17l1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4"/>'),
  agenda: svgI('<rect x="3.5" y="5" width="17" height="15" rx="3"/><path d="M3.5 10h17M8 3v4M16 3v4"/>'),
  goals: svgI('<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><circle cx="12" cy="12" r=".8" fill="currentColor"/>'),
  attention: svgI('<path d="M6 16v-5a6 6 0 0 1 12 0v5l1.5 2h-15z"/><path d="M10 20.5a2 2 0 0 0 4 0"/>'),
  health: svgI('<path d="M12 20s-7.5-4.6-7.5-10.2A4.3 4.3 0 0 1 12 7a4.3 4.3 0 0 1 7.5 2.8C19.5 15.4 12 20 12 20z"/><path d="M7.5 12.5h2.8l1.2-2 1.7 4 1.2-2h2.2"/>'),
  bills: svgI('<rect x="3.5" y="6" width="17" height="13" rx="3"/><path d="M3.5 10h17"/><circle cx="16.5" cy="14.5" r="1.1"/>'),
  crm: svgI('<circle cx="9" cy="9" r="3.2"/><path d="M3.5 19a5.5 5.5 0 0 1 11 0"/><circle cx="16.5" cy="10" r="2.6"/><path d="M15.6 14.6A4.6 4.6 0 0 1 20.5 19"/>'),
  media: svgI('<rect x="3.5" y="5" width="17" height="14" rx="3"/><path d="M10.5 9.5v5l4-2.5z"/>'),
  token: svgI('<path d="M12 3.5 19.4 7.75v8.5L12 20.5l-7.4-4.25v-8.5z"/><path d="M12 8v8M8.5 10l7 4M15.5 10l-7 4"/>'),
  git: svgI('<circle cx="7" cy="6" r="2"/><circle cx="7" cy="18" r="2"/><circle cx="17" cy="9" r="2"/><path d="M7 8v8M17 11c0 3-4 3.5-8.5 5.5"/>'),
  net: svgI('<path d="M3.5 14.5a8.5 8.5 0 0 1 17 0"/><path d="M7 14.5a5 5 0 0 1 10 0"/><circle cx="12" cy="14.5" r="1.3"/>'),
  subs: svgI('<path d="M4 12a8 8 0 0 1 14-5.3M20 12a8 8 0 0 1-14 5.3"/><path d="M18 3.5V7h-3.5M6 20.5V17h3.5"/>'),
  sky: svgI('<rect x="3.5" y="4.5" width="17" height="12" rx="2.5"/><path d="M9 20h6M12 16.5V20M12 8v3l2 1.2"/>'),
  memos: svgI('<path d="M6 3.5h8.5l4 4V20a.5.5 0 0 1-.5.5H6a.5.5 0 0 1-.5-.5V4a.5.5 0 0 1 .5-.5z"/><path d="M14 3.5V8h4.5M8.5 12h7M8.5 15.5h5"/>'),
  home: svgI('<path d="M4 10.5 12 4l8 6.5V19a1 1 0 0 1-1 1h-4.5v-5h-5v5H5a1 1 0 0 1-1-1z"/>'),
  life: svgI('<path d="M12 20c4.5-2.4 7.5-6 7.5-10A4.5 4.5 0 0 0 12 7.2 4.5 4.5 0 0 0 4.5 10c0 4 3 7.6 7.5 10z"/>'),
  usage: svgI('<path d="M4 19V11M9.3 19V5M14.7 19v-6M20 19V8"/>'),
  search: svgI('<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>'),
  sync: svgI('<path d="M4.5 12a7.5 7.5 0 0 1 13-5.1L20 9.5M19.5 12a7.5 7.5 0 0 1-13 5.1L4 14.5"/><path d="M20 4.5v5h-5M4 19.5v-5h5"/>'),
  grid: svgI('<rect x="4" y="4" width="7" height="7" rx="2"/><rect x="13" y="4" width="7" height="7" rx="2"/><rect x="4" y="13" width="7" height="7" rx="2"/><rect x="13" y="13" width="7" height="7" rx="2"/>'),
  plus: svgI('<path d="M12 5v14M5 12h14"/>'),
  more: svgI('<circle cx="6" cy="12" r="1" fill="currentColor"/><circle cx="12" cy="12" r="1" fill="currentColor"/><circle cx="18" cy="12" r="1" fill="currentColor"/>'),
  arrow: svgI('<path d="M5 12h14M13 6l6 6-6 6"/>'),
  play: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5.5v13l10.5-6.5z"/></svg>',
  spark: svgI('<path d="M12 4v4M12 16v4M4 12h4M16 12h4M6.5 6.5l2.5 2.5M15 15l2.5 2.5M6.5 17.5 9 15M15 9l2.5-2.5"/>'),
  check: '<svg viewBox="0 0 12 12"><path d="M2.5 6.2 5 8.5l4.5-5"/></svg>',
  reply: svgI('<path d="M5 5.5h14v10H11l-4 3.5v-3.5H5z"/>'),
  review: svgI('<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/>'),
  mention: svgI('<circle cx="12" cy="12" r="3.5"/><path d="M15.5 12v1.5a2.5 2.5 0 0 0 5 0V12a8.5 8.5 0 1 0-3.4 6.8"/>'),
  chevL: svgI('<path d="m14.5 6-6 6 6 6"/>'),
  chevR: svgI('<path d="m9.5 6 6 6-6 6"/>'),
};

const T = t => `--tone:var(--${t});--tint:var(--${t}-t)`;
const fmtN = (n, d = 0) => Number(n).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
const C = (v, { d = 0, pre = '', suf = '' } = {}) => `<span class="cnt" data-v="${v}" data-d="${d}" data-pre="${pre}" data-suf="${suf}">${pre}${fmtN(v, d)}${suf}</span>`;
const track = (p, tone, cls = '', delay = 0) => `<div class="track ${cls}"><i style="width:${Math.min(100, p)}%;${tone ? `--tone:${tone};` : ''}--d:${delay}"></i></div>`;

function bars(vals, { h = 64, tone = 'var(--clay)', labels, hl = 'last', base = '#E7E0D2' } = {}) {
  const max = Math.max(...vals), n = vals.length, w = 100;
  const bw = w / n;
  const rects = vals.map((v, i) => {
    const bh = Math.max(1.5, v / max * h);
    const on = hl === 'all' || (hl === 'last' && i === n - 1) || (Array.isArray(hl) && hl.includes(i));
    return `<rect class="gb" style="--i:${i}" x="${i * bw + bw * .17}" y="${h - bh}" width="${bw * .66}" height="${bh}" rx="1.4" fill="${on ? tone : base}"/>`;
  }).join('');
  const lab = labels ? `<div style="display:flex;font-size:10px;color:var(--ink4);margin-top:5px">${labels.map(l => `<span style="flex:1;text-align:center">${l}</span>`).join('')}</div>` : '';
  return `<svg width="100%" height="${h}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">${rects}</svg>${lab}`;
}
let gid = 0;
function area(vals, { h = 56, tone = '#D97757', fill = true } = {}) {
  const id = 'g' + (gid++), w = 100, max = Math.max(...vals), min = Math.min(...vals), pad = 5;
  const pts = vals.map((v, i) => [i / (vals.length - 1) * w, h - pad - (v - min) / ((max - min) || 1) * (h - pad * 2)]);
  const d = pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(2) + ' ' + p[1].toFixed(2)).join('');
  const last = pts[pts.length - 1];
  return `<div style="position:relative"><svg width="100%" height="${h}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    <defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${tone}" stop-opacity=".22"/><stop offset="1" stop-color="${tone}" stop-opacity="0"/></linearGradient></defs>
    ${fill ? `<path class="fadein" d="${d}L${w} ${h}L0 ${h}Z" fill="url(#${id})"/>` : ''}
    <path class="draw" pathLength="1" d="${d}" fill="none" stroke="${tone}" stroke-width="1.8" vector-effect="non-scaling-stroke" stroke-linejoin="round"/></svg>
    <i class="fadein" style="position:absolute;left:calc(${last[0]}% - 4px);top:${last[1] - 4}px;width:8px;height:8px;border-radius:50%;background:${tone};box-shadow:0 0 0 3px var(--card)"></i></div>`;
}
function ring(size, sw, p, tone, trackC = '#EEE8DC') {
  const r = size / 2 - sw / 2;
  return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}"><circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="${trackC}" stroke-width="${sw}"/>
  <circle class="ring-p" style="--len:${Math.min(100, p)}" pathLength="100" cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="${tone}" stroke-width="${sw}" stroke-linecap="round" transform="rotate(-90 ${size / 2} ${size / 2})"/></svg>`;
}
function gauge(p, tone) {
  return `<svg width="132" height="74" viewBox="0 0 132 74"><path d="M12 68a54 54 0 0 1 108 0" fill="none" stroke="#EEE8DC" stroke-width="10" stroke-linecap="round"/>
  <path class="ring-p" style="--len:${p}" pathLength="100" d="M12 68a54 54 0 0 1 108 0" fill="none" stroke="${tone}" stroke-width="10" stroke-linecap="round"/></svg>`;
}
function heat(weeks, seed = 7, cell = 11, gap = 3) {
  let s = seed; const r = () => (s = (s * 16807) % 2147483647) / 2147483647;
  const cs = ['#EEE9DE', '#DCE3CC', '#B9C79E', '#93A872', '#6F8550'];
  let out = '';
  for (let i = 0; i < weeks * 7; i++) {
    const v = r(), lv = v < .32 ? 0 : v < .58 ? 1 : v < .8 ? 2 : v < .93 ? 3 : 4;
    out += `<i style="--i:${i};background:${i === weeks * 7 - 1 ? '#6F8550' : cs[lv]}"></i>`;
  }
  return `<div class="heat" style="grid-template-rows:repeat(7,${cell}px);grid-auto-columns:${cell}px;gap:${gap}px">${out}</div>`;
}
function wave(n = 42, seed = 3) {
  let s = seed; const r = () => (s = (s * 16807) % 2147483647) / 2147483647;
  return `<div class="wave">${Array.from({ length: n }, (_, i) => `<i style="height:${20 + Math.abs(Math.sin(i * .5)) * 50 + r() * 30}%"></i>`).join('')}</div>`;
}
const days14 = ['7', '', '9', '', '11', '', '13', '', '15', '', '17', '', '19', '今'];
const mark = ({ mono = false, anim = false, cls = '', ink = '#1F1E1B' } = {}) => {
  const c = mono ? ['currentColor', 'currentColor', 'currentColor', 'currentColor', 'currentColor'] : ['#D97757', '#D4A27F', '#7D8F5E', '#6A9BCC', '#9C7BA0'];
  const core = mono ? 'currentColor' : ink;
  const L = [320, 216, 168, 120, 96];
  const P = ['M563.29 289.84A228 228 0 0 1 739.69 523.93', 'M711.41 622.54A228 228 0 0 1 539.79 738.30', 'M437.77 727.58A228 228 0 0 1 312.59 622.54', 'M284.31 523.93A228 228 0 0 1 308.85 408.49', 'M374.79 329.91A228 228 0 0 1 460.71 289.84'];
  return `<svg class="mk ${anim ? 'mk-anim' : ''} ${cls}" viewBox="244 244 536 536" fill="none" stroke-width="${mono ? 72 : 64}" stroke-linecap="round">${P.map((d, i) => `<path d="${d}" stroke="${c[i]}" style="--l:${L[i]}"/>`).join('')}<circle cx="512" cy="512" r="${mono ? 104 : 100}" fill="${core}"/><circle cx="512" cy="284" r="${mono ? 28 : 24}" fill="${core}"/></svg>`;
};

/* ============ 模块定义 ============ */
const D = window.D;
const M = {};

M.brief = {
  title: '今日简报', icon: 'brief', tone: 'clay', meta: '汇总所有模块', span: { c: 12, d: 12 }, bare: true,
  spec: { src: '后端聚合接口', refresh: '打开时 + 每 5 分钟', c: '问候 + 一句话摘要', d: '问候、可点击的摘要、快速输入栏', act: '摘要中的高亮词跳到对应模块；输入栏新增任务或 Memo' },
  c: () => `<div class="between"><div><div class="date">${D.now.date} · ${D.now.week}</div><h2 style="font-size:30px;margin:4px 0 0">下午好，玮康</h2></div>
    <div class="say" style="font-size:15px;max-width:620px;text-align:right">3 项任务到期 · 19:00 羽毛球 · 日报待确认</div></div>`,
  d: () => `<div class="brief-grid"><div>
      <div class="date">${D.now.date} · ${D.now.week}<span class="chip t" style="${T('clay')}">第 ${D.cycle.idx} 阶段 · 第 ${D.cycle.day} 天</span></div>
      <h2>下午好，玮康</h2>
      <div class="say">今天有 <a data-go="agenda">3 项任务</a>到期，其中 1 项已经逾期；<a data-go="agenda">19:00</a> 去打羽毛球。步数完成了 86%，支出 ¥128.50，仍在预算之内。昨天的<a data-go="goals">日报</a>还在等你确认，GitHub 上有 <a data-go="git">3 条回复</a>在等你。</div>
    </div><div>
      <div class="cmd">${I.spark}<span>记一条任务或想法…</span><span class="seg"><span class="on">任务 ⌃⌥Space</span><span>Memo ⌃⌥M</span></span></div>
      <div class="row muted" style="font-size:11.5px;gap:14px;padding-left:4px"><span>试试「明天下午3点 评审 #工作」</span><span style="margin-left:auto">⌘K 搜索全部</span></div>
    </div></div>`,
};

M.agenda = {
  title: '日程与任务', icon: 'agenda', tone: 'sky', meta: 'Google 日历 · Tasks', stamp: '17:56', span: { c: 3, d: 7 },
  spec: { src: 'Google Calendar / Tasks（Mac 直连）', refresh: '打开时 + 每 5 分钟；离线可编辑', c: '下一个日程 + 到期数', d: '当日时间轴（含当前时刻线）+ 逾期 / 今天 / 即将的任务 + 快速新增', act: '勾选完成、拖动改期、点击编辑；快速新增支持中文自然语言日期' },
  c: () => `<div class="evt" style="position:relative;left:0;right:0;${T('olive')};--i:0"><div class="tm">下一个 · 1 小时后</div><b>19:00 羽毛球</b></div>
    <div class="foot"><div class="hero"><span class="n md">${C(3)}</span><span class="u">项今天到期 · 1 项逾期</span></div>
    <div style="margin-top:10px">${track(25, 'var(--sky)', 'thin')}</div><div class="sub">已完成 1 / 4</div></div>`,
  d: () => {
    const pph = 30, h0 = 8, off = 12;
    const hrs = [8, 10, 12, 14, 16, 18, 20, 22].map(hh => `<div class="hr" style="top:${(hh - h0) * pph + off}px">${Math.abs(hh - D.now.hour) < .6 ? '' : `<span>${String(hh).padStart(2, '0')}:00</span>`}</div>`).join('');
    const evs = D.events.map((e, i) => {
      const top = (e.s - h0) * pph + 2 + off, ht = (e.e - e.s) * pph - 4;
      const pad = String(Math.floor(e.s)).padStart(2, '0') + ':' + (e.s % 1 ? '30' : '00');
      const end = String(Math.floor(e.e)).padStart(2, '0') + ':' + (e.e % 1 ? '30' : '00');
      return `<div class="evt" style="top:${top}px;height:${ht}px;${T(e.tone)};--i:${i}">${ht < 40 ? `<b>${e.t}</b> <span class="tm">${pad} · ${e.w}</span>` : `<div class="tm">${pad} – ${end}</div><b>${e.t}</b> <span class="tm">· ${e.w}</span>`}</div>`;
    }).join('');
    const tk = (t, cls = '') => `<div class="li task ${t.done ? 'done' : ''}"><span class="cbx">${I.check}</span><div><div class="tt">${t.t}</div><div class="t2">${t.l}</div></div>${t.d ? `<span class="r due ${cls}">${t.d}</span>` : ''}</div>`;
    return `<div class="agenda"><div>
        <div class="allday"><span class="chip t" style="${T('clay')}">全天 · 阶段第 ${D.cycle.day} 天</span><span class="chip">妈妈生日还有 6 天</span></div>
        <div class="daycol">${hrs}${evs}<div class="nowline" style="top:${(D.now.hour - h0) * pph + off}px"><span>${D.now.time}</span></div></div>
      </div><div class="tgroup">
        <div class="sect">逾期</div>${D.tasks.late.map(t => tk(t, 'late')).join('')}
        <div class="sect">今天 · 3</div>${D.tasks.today.map(t => tk(t)).join('')}
        <div class="sect">即将</div>${D.tasks.later.map(t => tk(t)).join('')}
        <div class="mini-in" style="margin-top:14px">${I.plus.replace('<svg', '<svg style="width:14px;height:14px"')}<span>明天下午3点 和李雷对齐方案</span><kbd>↩</kbd></div>
        <div class="nlp"><span class="chip t" style="${T('sky')}">10 月 21 日 周三</span><span class="chip t" style="${T('clay')}">15:00 · 同时建时间块</span><span class="chip t" style="${T('olive')}">清单：工作</span></div>
      </div></div>`;
  },
};

M.goals = {
  title: '主线与复盘', icon: 'goals', tone: 'clay', meta: 'personal-review · Memos', stamp: '昨天 21:30', span: { c: 3, d: 5 },
  spec: { src: 'personal-review（待补 HTTP）· Memos 账本', refresh: '打开时', c: '主线 + 周期进度 + 待确认提醒', d: '主线、42 天周期刻度、≤5 个阶段目标进度、日报 / 周报 / 阶段结案状态', act: '确认或编辑日报草稿；新建、结案阶段目标（规则由 personal-review 校验）' },
  c: () => `<div class="lbl">总主线</div><div class="mainline" style="font-size:17px">${D.mainline}</div>
    <div class="cycle" style="gap:2px;margin:12px 0 4px">${Array.from({ length: 42 }, (_, i) => `<i style="--i:${i};height:12px" class="${i < 22 ? 'p' : i === 22 ? 'now' : i === 41 ? 'close' : ''}"></i>`).join('')}</div>
    <div class="between muted" style="font-size:11px"><span>第 ${D.cycle.day} / ${D.cycle.total} 天</span><span>剩 19 天</span></div>
    <div class="foot"><span class="chip t" style="${T('clay')}"><span class="dot pulse" style="--tone:var(--clay)"></span>昨日日报待确认</span></div>`,
  d: () => `<div class="lbl">总主线</div><div class="mainline">${D.mainline}</div>
    <div class="cycle">${Array.from({ length: 42 }, (_, i) => `<i style="--i:${i}" class="${i < 22 ? 'p' : i === 22 ? 'now' : i === 41 ? 'close' : ''}"></i>`).join('')}</div>
    <div class="between muted" style="font-size:11px"><span>${D.cycle.start} 开始</span><span style="color:var(--clay-d);font-weight:600">今天 · 第 ${D.cycle.day} 天</span><span>${D.cycle.end} 结案</span></div>
    <div class="sect">第 ${D.cycle.idx} 阶段目标 · ${D.goals.length} / 5</div>
    ${D.goals.map((g, i) => `<div class="goal-row"><span class="chip t" style="${T(g.tone)};justify-content:center">${g.dom}</span><span style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${g.t}</span>${track(g.p, `var(--${g.tone})`, '', i * 80)}<span class="v">${g.v}</span></div>`).join('')}
    <div class="review">
      <div class="rv hot"><b>昨日日报</b><span class="muted" style="font-size:11px">草稿 · 待确认</span></div>
      <div class="rv"><b>本周周报</b><span class="muted" style="font-size:11px">周日 21:50</span></div>
      <div class="rv"><b>阶段结案</b><span class="muted" style="font-size:11px">11/10 预备材料</span></div>
    </div>`,
};

M.attention = {
  title: '需要注意', icon: 'attention', tone: 'ochre', meta: '跨模块提醒', span: { c: 12, d: 5 }, autoH: true,
  spec: { src: '后端规则引擎', refresh: '实时（推送）', c: '横向卡片条，最多 5 条', d: '完整列表，含来源与操作', act: '点击直达处理位置；可忽略或稍后提醒；同一规则可在设置中关闭' },
  c: () => `<div class="att-strip">${D.attention.map((a, i) => `<div class="att" style="${T(a.tone)};--i:${i}"><span class="dot ${i === 0 ? 'pulse' : ''}"></span><div><b>${a.t}</b><span>${a.s}</span></div><span class="go">${I.arrow.replace('<svg', '<svg style="width:14px;height:14px"')}</span></div>`).join('')}</div>`,
  d: () => D.attention.map((a, i) => `<div class="li" style="${T(a.tone)}"><span class="dot"></span><div><div>${a.t}</div><div class="t2">${a.s}</div></div><button class="r chip t">${a.a}</button></div>`).join(''),
};

M.health = {
  title: '健康', icon: 'health', tone: 'olive', meta: 'personal-records', stamp: '11:40', span: { c: 3, d: 6 },
  spec: { src: 'personal-records /api/v1/health', refresh: '每 15 分钟', c: '今日步数 + 目标环 + 睡眠 / 静息心率 + 14 天迷你柱', d: '活动三环、关键指标、14 天步数、昨晚睡眠分期、静息心率趋势', act: '点击指标查看 30 天趋势；数据断更时提示' },
  c: () => `<div class="between"><div class="hero"><span class="n">${C(D.health.steps)}</span><span class="u">步</span></div>${ring(46, 6, D.health.steps / D.health.goal * 100, 'var(--olive)')}</div>
    <div class="sub">睡眠 ${D.health.sleep} · 静息心率 ${D.health.rhr}</div><div class="foot">${bars(D.health.steps14, { h: 32, tone: 'var(--olive)' })}</div>`,
  d: () => `<div class="row" style="gap:22px;align-items:center">
      <div class="rings">${ring(118, 11, 86, 'var(--olive)')}<div style="position:absolute;inset:15px">${ring(88, 11, 82, 'var(--clay)')}</div><div style="position:absolute;inset:30px">${ring(58, 11, 60, 'var(--sky)')}</div></div>
      <div style="flex:1"><div class="hero"><span class="n">${C(D.health.steps)}</span><span class="u">/ ${fmtN(D.health.goal)} 步</span></div>
      <div class="legend" style="margin-top:10px"><span style="--c:var(--olive)">步数 86%</span><span style="--c:var(--clay)">活动 ${D.health.kcal} / ${D.health.kcalGoal} kcal</span><span style="--c:var(--sky)">锻炼 ${D.health.ex} / ${D.health.exGoal} 分钟</span></div></div></div>
    <div class="stats" style="margin-top:18px"><div><div class="lbl">睡眠</div><div class="v">7<small>h</small>12<small>m</small></div></div><div><div class="lbl">静息心率</div><div class="v">${D.health.rhr}<small>bpm</small></div></div><div><div class="lbl">血氧</div><div class="v">${D.health.spo2}<small>%</small></div></div></div>
    <div class="sect">近 14 天步数</div>${bars(D.health.steps14, { h: 72, tone: 'var(--olive)', labels: days14 })}
    <div class="cols2" style="margin-top:4px"><div><div class="sect">昨晚睡眠 · 23:48 – 07:00</div>
      <div class="sleepbar">${D.health.stages.map((s, i) => `<i style="flex:${s[1]};background:${s[2]};animation-delay:${i * 90}ms"></i>`).join('')}</div>
      <div class="legend">${D.health.stages.map(s => `<span style="--c:${s[2]}">${s[0]} ${Math.floor(s[1] / 60)}h${s[1] % 60}m</span>`).join('')}</div></div>
      <div><div class="sect">静息心率 · 14 天</div>${area(D.health.rhr14, { h: 52, tone: '#C97B84' })}</div></div>`,
};

M.bills = {
  title: '账单', icon: 'bills', tone: 'kraft', meta: 'AutoAccounting', stamp: '16:31', span: { c: 3, d: 6 },
  spec: { src: 'personal-records /api/v1/bills', refresh: '推送入库后 1 分钟内', c: '今日支出 + 本月预算进度', d: '今日明细、14 天支出、本月分类、净资产趋势与账户', act: '点击账单查看详情；可手动补记（写入 records）' },
  c: () => `<div class="hero"><span class="n">${C(D.bills.today, { d: 2, pre: '¥' })}</span></div><div class="sub">今日支出 · 4 笔</div>
    <div class="foot"><div class="between" style="font-size:11.5px;margin-bottom:6px"><span class="ink2">本月 ¥4,312</span><span class="muted">预算 86%</span></div>${track(86, 'var(--kraft)')}<div class="sub muted">剩 ¥688 · 还有 11 天</div></div>`,
  d: () => {
    const tot = D.bills.cats.reduce((a, c) => a + c[1], 0);
    return `<div class="cols2"><div><div class="hero"><span class="n">${C(D.bills.today, { d: 2, pre: '¥' })}</span><span class="u">今日</span></div>
      <div style="margin-top:12px">${D.bills.items.map(b => `<div class="li"><div><div>${b[0]}</div><div class="t2">${b[1]} · ${b[2]}</div></div><span class="r num">−${b[3].toFixed(2)}</span></div>`).join('')}</div></div>
      <div><div class="sect">近 14 天</div>${bars(D.bills.d14, { h: 70, tone: 'var(--kraft)', labels: days14, hl: [6, 13] })}
      <div class="sect">本月 · ¥${fmtN(D.bills.month, 0)} / ${fmtN(D.bills.budget)}</div>
      <div class="stackbar">${D.bills.cats.map((c, i) => `<i style="flex:${c[1]};background:${c[2]};animation-delay:${i * 80}ms"></i>`).join('')}</div>
      <div class="legend">${D.bills.cats.map(c => `<span style="--c:${c[2]}">${c[0]} ${Math.round(c[1] / tot * 100)}%</span>`).join('')}</div></div></div>
      <div class="sect">资产</div>
      <div class="row" style="align-items:flex-end;gap:24px"><div><div class="lbl">净资产</div><div class="hero" style="margin-top:4px"><span class="n md">${C(D.bills.net, { pre: '¥' })}</span><span class="u" style="color:var(--olive)">近 6 月 +14%</span></div></div><div style="flex:1;max-width:260px">${area(D.bills.net6, { h: 40, tone: '#7D8F5E' })}</div></div>
      <div class="acct">${D.bills.accts.map(a => `<div><div class="lbl">${a[0]}</div><div class="v">${a[1]}</div></div>`).join('')}</div>`;
  },
};

M.crm = {
  title: '交流', icon: 'crm', tone: 'rose', meta: 'personal-crm · 录音附属', stamp: '16:40', span: { c: 3, d: 6 },
  spec: { src: 'personal-crm /api/v1/crm · plaud-archive', refresh: '每 15 分钟', c: '今日交流人数 + 头像 + 录音数', d: '今日交流时间线（录音作为附件可播放、可看转录）+ 本阶段统计 + 久未联系', act: '快速记一条交流；播放录音；跳到人物详情' },
  c: () => `<div class="hero"><span class="n">${C(D.crm.today.length)}</span><span class="u">人 · 今日交流</span></div>
    <div class="pstack" style="margin-top:12px">${D.crm.today.map(p => `<span class="pp" style="${T(p.tone)}">${p.n}</span>`).join('')}</div>
    <div class="foot"><span class="chip t" style="${T('rose')}">${I.play.replace('<svg', '<svg style="width:10px;height:10px"')} 2 段录音 · 1:46:52</span></div>`,
  d: () => `<div class="sect">今日 · ${D.crm.today.length} 人</div>
    ${D.crm.today.map((p, i) => `<div class="inter"><span class="pp" style="${T(p.tone)}">${p.n}</span><div><div class="who"><b>${p.who}</b><span class="muted" style="font-size:11px">${p.rel} · ${p.ch}</span><span class="tm">${p.tm}</span></div><p>${p.s}</p>
      ${p.rec ? `<div class="recd"><span class="play">${I.play.replace('<svg', '<svg style="width:11px;height:11px"')}</span>${wave(38, i + 2)}<span class="meta">${p.rec} · ${p.dur} · 转录稿</span></div>` : ''}</div></div>`).join('')}
    <div class="sect">第 ${D.cycle.idx} 阶段</div>
    <div class="row" style="gap:28px;align-items:flex-end"><div><div class="hero"><span class="n md">${C(D.crm.stage.people)}</span></div><div class="lbl">联系过的人</div></div><div><div class="hero"><span class="n md">${C(D.crm.stage.inter)}</span></div><div class="lbl">次交流</div></div><div><div class="hero"><span class="n md">${C(D.crm.stage.recs)}</span></div><div class="lbl">段录音</div></div>
    <div style="margin-left:auto;text-align:right"><div class="lbl" style="margin-bottom:6px">久未联系</div><div class="row" style="gap:6px">${D.crm.stale.map(s => `<button class="chip">${s[0]} · ${s[1]} 天</button>`).join('')}</div></div></div>`,
};

M.media = {
  title: '媒体', icon: 'media', tone: 'plum', meta: 'Emby · Navidrome · MoviePilot', stamp: '17:30', span: { c: 3, d: 12 },
  spec: { src: 'Emby / Navidrome / MoviePilot / qBittorrent', refresh: '每 30 分钟', c: '继续观看 + 下载状态', d: '继续观看海报墙、最近添加、最近播放音乐、下载与 PT 状态、各服务入口', act: '点击海报在 Emby 继续播放；入口按钮打开对应网页' },
  c: () => { const p = D.media.cont[0]; return `<div class="row" style="gap:12px;align-items:stretch"><div class="poster" style="width:62px;flex:none;--pg:${p.g};--i:0;border-radius:9px"><div class="pr" style="width:${p.p}%"></div></div>
    <div style="min-width:0"><div class="lbl">继续观看</div><div class="serif" style="font-size:17px;margin-top:4px">${p.t}</div><div class="sub">${p.s} · 已看 ${p.p}%</div></div></div>
    <div class="foot between"><span class="sub" style="margin:0">下载中 2 · ↓ 12.4 MB/s</span><span class="chip">最近添加 3</span></div>`; },
  d: () => `<div class="sect">继续观看 · Emby</div><div class="posters">${D.media.cont.map((p, i) => `<div class="poster" style="--pg:${p.g};--i:${i}"><div class="glyph">${p.t[0]}</div><div class="pt">${p.t}<small>${p.s}</small></div><div class="pr" style="width:${p.p}%"></div></div>`).join('')}</div>
    <div class="media-b" style="display:grid;grid-template-columns:1.1fr 1fr 1fr;gap:0 28px;margin-top:4px">
      <div><div class="sect">最近添加</div>${D.media.latest.map(x => `<div class="li"><div><div>${x[0]}</div><div class="t2">${x[1]}</div></div><span class="r muted" style="font-size:11px">Emby</span></div>`).join('')}</div>
      <div><div class="sect">最近播放 · Navidrome</div><div class="albums">${D.media.albums.map(g => `<div class="album" style="--pg:${g}"></div>`).join('')}</div><div class="sub">《Random Access Memories》· 今天 09:12</div></div>
      <div><div class="sect">下载 · MoviePilot</div>${D.media.dl.map((d, i) => `<div style="margin:8px 0"><div class="between" style="font-size:12px"><span>${d[0]}</span><span class="muted">${d[1]}%</span></div><div style="margin-top:5px">${track(d[1], 'var(--plum)', '', i * 100)}</div></div>`).join('')}<div class="sub muted">↓ 12.4 MB/s · 做种 186 · 分享率 3.2</div></div>
    </div>
    <div class="svc" style="margin-top:16px">${['Emby', 'Navidrome', 'MoviePilot', 'qBittorrent', 'PT 站点'].map(s => `<button class="chip">${s} ↗</button>`).join('')}</div>`,
};

/* Token：按时间口径生成的热力图数据（示例数据，确定性随机） */
const rnd = seed => { let s = seed; return () => (s = (s * 16807) % 2147483647) / 2147483647; };
const TOOLS = D.token.tools.map(t => t[0]), TOOL_W = [.44, .27, .19, .10];
const HOUR_W = [.06, .03, .01, .01, .01, .02, .05, .2, .55, .85, 1, .9, .55, .7, 1, 1, .9, .8, .45, .4, .65, .75, .5, .2];
const HW_SUM = HOUR_W.reduce((a, b) => a + b, 0);
const WD = ['一', '二', '三', '四', '五', '六', '日'];
const TODAY = new Date(2026, 9, 20), NOW_H = 17;
const dayOff = n => { const d = new Date(TODAY); d.setDate(d.getDate() + n); return d; };
const md = d => `${d.getMonth() + 1}/${d.getDate()}`;
const wdOf = d => WD[(d.getDay() + 6) % 7];
const fmtTok = v => v >= 1000 ? (v / 1000).toFixed(2) + 'B' : v >= 100 ? Math.round(v) + 'M' : v.toFixed(1) + 'M';
const COST_PER_M = 2.267;
const pct = (a, b) => Math.round((a / b - 1) * 100);

const TOKEN_RANGES = (() => {
  const r = rnd(29);
  const dailyFor = n => { const d = dayOff(n), wk = d.getDay() % 6 === 0 ? .45 : 1; return +(wk * (9 + r() * 18)).toFixed(1); };
  const d14 = D.token.d14, days = {};
  for (let n = -400; n <= 0; n++) days[n] = n > -14 ? d14[13 + n] : dailyFor(n);
  const hourly = (tot, upto = 23) => HOUR_W.map((w, h) => h > upto ? null : tot * w / HW_SUM * (.6 + r() * .8));
  const sumN = (a, b) => { let s = 0; for (let n = a; n <= b; n++) s += days[n]; return s; };
  const peakOf = cells => cells.reduce((p, c) => c.v != null && c.v > p.v ? c : p, { v: -1 });

  const day = (() => {
    const cells = [];
    TOOLS.forEach((t, ri) => hourly(days[0] * TOOL_W[ri] * 4, NOW_H).forEach((v, h) => cells.push({ r: ri, c: h, v: v == null ? null : v / 4, tip: `${t} · ${String(h).padStart(2, '0')}:00` })));
    const pk = peakOf(cells), byHour = Array.from({ length: 24 }, (_, h) => cells.filter(c => c.c === h).reduce((a, c) => a + (c.v || 0), 0));
    const ph = byHour.indexOf(Math.max(...byHour));
    return { label: '今天 · 10 月 20 日 周二', title: '按小时 × 工具', rows: TOOLS, cols: 24, colLab: h => h % 3 ? '' : String(h).padStart(2, '0'), cells, total: days[0], prev: days[-1], vsT: '较昨天', peak: `${String(ph).padStart(2, '0')}:00`, peakV: byHour[ph], avgT: '本小时', avg: byHour[NOW_H], tools: TOOLS.map((t, i) => cells.filter(c => c.r === i).reduce((a, c) => a + (c.v || 0), 0)) , _pk: pk };
  })();

  const week = (() => {
    const cells = [], rows = [];
    for (let k = 0; k < 7; k++) {
      const n = k - 6, d = dayOff(n); rows.push(n === 0 ? '今天' : `周${wdOf(d)}`);
      hourly(days[n], n === 0 ? NOW_H : 23).forEach((v, h) => cells.push({ r: k, c: h, v, tip: `${md(d)} 周${wdOf(d)} · ${String(h).padStart(2, '0')}:00` }));
    }
    let best = -6; for (let n = -6; n <= 0; n++) if (days[n] > days[best]) best = n;
    const tot = sumN(-6, 0);
    return { label: `近 7 天 · ${md(dayOff(-6))} – ${md(TODAY)}`, title: '按小时 × 日期', rows, cols: 24, colLab: h => h % 3 ? '' : String(h).padStart(2, '0'), cells, total: tot, prev: sumN(-13, -7), vsT: '较前 7 天', peak: `周${wdOf(dayOff(best))} ${md(dayOff(best))}`, peakV: days[best], avgT: '日均', avg: tot / 7, tools: TOOL_W.map(w => tot * w) };
  })();

  const month = (() => {
    const cells = [];
    TOOLS.forEach((t, ri) => { for (let k = 0; k < 30; k++) { const n = k - 29; cells.push({ r: ri, c: k, v: days[n] * TOOL_W[ri] * (.7 + r() * .6), tip: `${t} · ${md(dayOff(n))}` }); } });
    let best = -29; for (let n = -29; n <= 0; n++) if (days[n] > days[best]) best = n;
    const tot = sumN(-29, 0);
    return { label: `近 30 天 · ${md(dayOff(-29))} – ${md(TODAY)}`, title: '按日期 × 工具', rows: TOOLS, cols: 30, colLab: k => (29 - k) % 7 ? '' : k === 29 ? '今天' : md(dayOff(k - 29)), cells, total: tot, prev: sumN(-59, -30) * .92, vsT: '较前 30 天', peak: md(dayOff(best)), peakV: days[best], avgT: '日均', avg: tot / 30, tools: TOOLS.map((t, i) => cells.filter(c => c.r === i).reduce((a, c) => a + c.v, 0)) };
  })();

  const year = (() => {
    const cells = [], todayRow = (TODAY.getDay() + 6) % 7, start = -(52 * 7 + todayRow);
    let lastM = -1; const mLab = {};
    for (let c = 0; c < 53; c++) for (let rr = 0; rr < 7; rr++) {
      const n = start + c * 7 + rr, d = dayOff(n);
      if (rr === 0 && d.getMonth() !== lastM) { lastM = d.getMonth(); if (c < 51) mLab[c] = `${lastM + 1}月`; }
      cells.push({ r: rr, c, v: n > 0 ? null : days[n] * (n < -200 ? .35 : 1), tip: `${d.getFullYear()}/${md(d)} 周${wdOf(d)}` });
    }
    const valid = cells.filter(c => c.v != null), tot = valid.reduce((a, c) => a + c.v, 0), pk = peakOf(cells);
    return { label: `近一年 · 2025/10/20 – 2026/10/20`, title: '按周 × 星期', rows: ['一', '', '三', '', '五', '', '日'], cols: 53, colLab: c => mLab[c] || '', cells, total: tot, prev: tot * .38, vsT: '较前一年', peak: pk.tip.split(' ')[0].slice(5), peakV: pk.v, avgT: '日均', avg: tot / valid.length, tools: TOOL_W.map(w => tot * w), small: true };
  })();
  return { d: day, w: week, m: month, y: year };
})();

const HEAT_C = ['#EFEAE0', '#F4DDD0', '#EDBBA3', '#E3977A', '#D97757', '#B35A3D'];
function tokenHeat(R) {
  const max = Math.max(...R.cells.map(c => c.v || 0));
  const lv = v => v == null ? -1 : v / max < .08 ? 0 : v / max < .25 ? 1 : v / max < .45 ? 2 : v / max < .65 ? 3 : v / max < .85 ? 4 : 5;
  const grid = R.rows.map((rl, ri) => `<span class="th-rl">${rl}</span>` + R.cells.filter(c => c.r === ri).map(c => {
    const l = lv(c.v);
    return `<i class="${l < 0 ? 'fut' : ''}" style="--i:${c.c + ri * 2};background:${l < 0 ? 'transparent' : HEAT_C[l]}" data-tip="${c.tip}${l < 0 ? ' · 尚未到达' : ' · ' + fmtTok(c.v)}"></i>`;
  }).join('')).join('');
  const labs = `<span></span>` + Array.from({ length: R.cols }, (_, k) => `<span class="th-cl">${R.colLab(k)}</span>`).join('');
  return `<div class="th ${R.small ? 'sm' : ''}" style="--n:${R.cols}">${grid}${labs}</div>`;
}
const heatLegend = () => `<span class="th-leg">少${HEAT_C.map(c => `<i style="background:${c}"></i>`).join('')}多</span>`;

M.token = {
  title: 'Token 用量', icon: 'token', tone: 'clay', meta: 'usage-monitor · Token Monitor', stamp: '17:55', span: { c: 3, d: 12 },
  state: { range: 'w' },
  spec: { src: 'usage-monitor（待补 HTTP）/ token-monitor-hub', refresh: '每 5 分钟', c: '今日 Token + 估算成本 + 两条主要额度', d: '时间口径切换（日 / 周 / 月 / 年）：总量、成本、环比、峰值、热力图、按工具 / 设备分布；额度为实时（Claude Desktop 样式）', act: '切换时间口径；悬停热力格看明细；额度超过阈值时进入「需要注意」' },
  c: () => `<div class="hero"><span class="n">${C(D.token.today, { d: 1 })}</span><span class="u">M tokens · ≈ $${D.token.cost}</span></div>
    <div class="foot">${[['Claude Code · 本周', 61, 'var(--clay)'], ['Codex · 本周', 35, 'var(--steel)']].map((r, i) => `<div style="margin-top:${i ? 10 : 0}px"><div class="between" style="font-size:11.5px;margin-bottom:5px"><span class="ink2">${r[0]}</span><span class="num">${r[1]}%</span></div>${track(r[1], r[2], 'thin', i * 120)}</div>`).join('')}</div>`,
  d() {
    const rk = this.state.range, R = TOKEN_RANGES[rk], big = R.total >= 1000;
    const tTot = R.tools.reduce((a, b) => a + b, 0), delta = pct(R.total, R.prev);
    const segs = [['d', '日'], ['w', '周'], ['m', '月'], ['y', '年']].map(([k, l]) => `<button data-opt="range:${k}" class="${k === rk ? 'on' : ''}">${l}</button>`).join('');
    return `<div class="tok-bar"><div class="segc">${segs}</div>
        <div class="tok-per"><button class="ib">${I.chevL}</button><span>${R.label}</span><button class="ib" disabled>${I.chevR}</button></div>${heatLegend()}</div>
      <div class="tok-grid"><div class="tok-main">
        <div class="kpis">
          <div><div class="lbl">总量</div><div class="hero"><span class="n" style="font-size:40px">${C(big ? R.total / 1000 : R.total, { d: big ? 2 : 1 })}</span><span class="u">${big ? 'B' : 'M'} tokens</span></div></div>
          <div><div class="lbl">估算成本</div><div class="v">${C(R.total * COST_PER_M, { pre: '$', d: big ? 0 : 2 })}</div></div>
          <div><div class="lbl">${R.vsT}</div><div class="v ${delta >= 0 ? 'up' : 'down'}">${delta >= 0 ? '↑' : '↓'} ${Math.abs(delta)}%</div></div>
          <div><div class="lbl">峰值</div><div class="v">${R.peak}<small>${fmtTok(R.peakV)}</small></div></div>
          <div><div class="lbl">${R.avgT}</div><div class="v">${fmtTok(R.avg)}</div></div>
        </div>
        <div class="sect">热力图 · ${R.title}</div>${tokenHeat(R)}
        <div class="cols2"><div><div class="sect">按工具</div>${TOOLS.map((t, i) => `<div class="tool-row"><span>${t}</span>${track(R.tools[i] / tTot * 100 * 2, D.token.tools[i][2], '', i * 80)}<span class="muted num" style="text-align:right">${fmtTok(R.tools[i])}</span></div>`).join('')}</div>
        <div><div class="sect">按设备</div>${D.token.devices.map((d, i) => { const v = R.total * d[1] / D.token.today; return `<div class="tool-row" style="grid-template-columns:64px minmax(0,1fr) 54px"><span>${d[0]}</span>${track(v / R.total * 100, 'var(--ink2)', '', i * 80)}<span class="muted num" style="text-align:right">${fmtTok(v)}</span></div>`; }).join('')}</div></div>
      </div><div class="tok-side">
        <div class="sect">额度 · 实时</div>
        ${D.token.limits.map((l, k) => `<div class="limit"><h4>${l.tool}<span class="chip">${l.plan}</span></h4>${l.rows.map((r, i) => `<div class="lrow"><div class="between"><span>${r[0]}</span><span class="num" style="font-size:13px">${r[1]}% 已用</span></div><div class="ltrack" style="margin-top:6px"><i style="width:${r[1]}%;--tone:${l.tone};--d:${(k * 2 + i) * 90}"></i></div><div class="rs">${r[2]}</div></div>`).join('')}</div>`).join('')}
      </div></div>`;
  },
};

const G_KIND = { reply: ['评论回复', 'sky'], review: ['请求 review', 'plum'], mention: ['@提及', 'ochre'] };
const pr = (repo, n) => `<span class="pr-ref">${repo.replace('ump45nose/', '')}<b>#${n}</b></span>`;
const ageCls = b => b.age >= 7 ? 'late' : b.age >= 2 ? 'warn' : '';
M.git = {
  title: 'GitHub', icon: 'git', tone: 'olive', meta: 'ump45nose · 通知与 PR', stamp: '17:50', span: { c: 3, d: 6 },
  spec: { src: 'GitHub API（后端代持 Token）：通知、review-requested、我的 open PR 的 checks / mergeable / review 状态', refresh: '每 10 分钟 + 打开时', c: '等我回复数 + 阻塞 PR 数 + 最紧急的两条', d: '等我回复（评论回复、review 请求、@提及）、我的阻塞 PR（CI 失败 / 需要修改 / 合并冲突 / 长时间无 review）、提交活动', act: '点击跳到 GitHub 对应位置；可标记「已处理」或「稍后」；等回复超 24 小时或阻塞超 3 天进入「需要注意」' },
  c: () => {
    const g = D.git, oldest = Math.max(...g.blocked.map(b => b.age));
    return `<div class="hero"><span class="n">${C(g.waitMe.length)}</span><span class="u">条等你回复 · ${g.blocked.length} 个 PR 阻塞</span></div>
    <div class="foot git-mini">${[g.waitMe[0], g.blocked[0]].map((x, i) => `<div class="gm"><span class="dot" style="background:var(--${i ? x.tone : G_KIND[x.k][1]})"></span><span class="gm-t">${i ? x.why : G_KIND[x.k][0]} · ${x.t}</span><span class="gm-a ${i ? ageCls(x) : ''}">${i ? x.age + ' 天' : x.ago.replace('前', '')}</span></div>`).join('')}
      <div class="sub" style="margin:6px 0 0">最久阻塞 ${oldest} 天 · 今日提交 ${g.today}</div></div>`;
  },
  d: () => {
    const g = D.git;
    const wait = g.waitMe.map((w, i) => { const [kl, kt] = G_KIND[w.k]; return `<div class="gi" style="--i:${i}"><span class="gi-ic" style="${T(kt)}">${I[w.k]}</span>
      <div class="gi-b"><div class="gi-t">${w.t}</div><div class="gi-m">${pr(w.repo, w.n)}<span>${kl} · ${w.who} · ${w.ago}</span></div><div class="gi-q">${w.q}</div></div>
      <button class="chip gi-act">${w.a} ↗</button></div>`; }).join('');
    const blk = g.blocked.map((b, i) => `<div class="gi" style="--i:${i + 3}"><span class="st" style="${T(b.tone)}">${b.why}</span>
      <div class="gi-b"><div class="gi-t">${b.t}</div><div class="gi-m">${pr(b.repo, b.n)}<span>${b.d}</span></div></div>
      <span class="gi-age ${ageCls(b)}">${b.ageT || b.age + ' 天'}</span></div>`).join('');
    return `<div class="kpis g4">
        <div><div class="lbl">等我回复</div><div class="hero"><span class="n">${C(g.waitMe.length)}</span><span class="u">条</span></div></div>
        <div><div class="lbl">我的 PR 阻塞</div><div class="hero"><span class="n">${C(g.blocked.length)}</span><span class="u">个</span></div></div>
        <div><div class="lbl">最久阻塞</div><div class="v late">${Math.max(...g.blocked.map(b => b.age))}<small>天</small></div></div>
        <div><div class="lbl">今日提交</div><div class="v">${g.today}<small>· 连续 ${g.streak} 天</small></div></div></div>
      <div class="git-grid"><div><div class="sect">等我回复 · ${g.waitMe.length}</div>${wait}</div>
        <div><div class="sect">我的 PR 阻塞 · ${g.blocked.length}</div>${blk}</div></div>
      <div class="sect">提交活动 · 近半年</div><div class="git-act">${heat(26, 11, 9, 3)}<div class="muted" style="font-size:11.5px;line-height:1.7">近 30 天 ${g.m30} 次<br>今天 ${g.today} 次 · 3 个仓库</div></div>`;
  },
};

M.net = {
  title: '网络', icon: 'net', tone: 'sage', meta: 'ShellCrash', stamp: '17:57', span: { c: 3, d: 6 },
  spec: { src: 'usage-monitor（ShellCrash，待补 HTTP）', refresh: '每 15 分钟', c: '主力订阅剩余流量仪表', d: '各订阅剩余 / 到期、今日上下行、逐小时流量', act: '剩余低于阈值或临近到期时进入「需要注意」' },
  c: () => { const p = D.net.pools[0], left = p.total - p.used; return `<div class="row" style="justify-content:center;margin-top:-2px"><div class="gauge">${gauge(left / p.total * 100, 'var(--sage)')}<div class="gv"><span class="num" style="font-size:26px">${C(left, { d: 0 })}</span><span class="muted" style="font-size:11px"> GB</span></div></div></div>
    <div class="foot" style="text-align:center"><div class="sub" style="margin:0">${p.n} · 剩 ${Math.round(left / p.total * 100)}% · ${p.left} 天后到期</div></div>`; },
  d: () => `${D.net.pools.map((p, i) => { const left = p.total - p.used; return `<div class="pool"><div class="between"><b style="font-weight:600">${p.n}</b><span class="num"><span style="font-size:18px">${C(left, { d: 1 })}</span><span class="muted" style="font-size:11px"> / ${p.total} GB 剩余</span></span></div><div style="margin-top:8px">${track(left / p.total * 100, 'var(--sage)', '', i * 100)}</div><div class="between muted" style="font-size:11px;margin-top:6px"><span>${p.exp}</span><span>日均可用 ${(left / p.left).toFixed(1)} GB</span></div></div>`; }).join('')}
    <div class="stats" style="margin-top:14px"><div><div class="lbl">今日下载</div><div class="v">${D.net.down}<small>GB</small></div></div><div><div class="lbl">今日上传</div><div class="v">${D.net.up}<small>GB</small></div></div><div><div class="lbl">本月</div><div class="v">${D.net.month}<small>GB</small></div></div></div>
    <div class="sect">今日逐小时</div>${bars(D.net.hourly, { h: 48, tone: 'var(--sage)', hl: 'all', labels: ['0', '', '', '3', '', '', '6', '', '', '9', '', '', '12', '', '', '15', '', '17'] })}`,
};

M.subs = {
  title: '订阅', icon: 'subs', tone: 'ochre', meta: '手动维护 · 自动识别账单', stamp: '今天', span: { c: 3, d: 6 },
  spec: { src: '后端自有配置 + 账单识别', refresh: '每天', c: '月度合计 + 最近两项续费', d: '全部订阅、价格、续费倒计时', act: '7 天内续费进入「需要注意」；可从账单一键识别为订阅' },
  c: () => `<div class="hero"><span class="n">${C(D.subs.month, { pre: '¥' })}</span><span class="u">/ 月</span></div><div class="sub">${D.subs.list.length} 项订阅 · 7 天内续费 2 项</div>
    <div class="foot">${D.subs.list.slice(0, 2).map(s => `<div class="between" style="margin-top:6px"><span class="row" style="gap:8px"><span class="logo-tile" style="background:${s[5]};width:20px;height:20px;border-radius:6px;font-size:11px">${s[0]}</span>${s[1]}</span><span class="cd soon">${s[3]}</span></div>`).join('')}</div>`,
  d: () => `<div class="between" style="align-items:flex-end;margin-bottom:10px"><div class="hero"><span class="n">${C(D.subs.month, { pre: '¥' })}</span><span class="u">/ 月合计</span></div><span class="muted" style="font-size:11px">年付已折算 · 汇率 7.12</span></div>
    ${D.subs.list.map(s => `<div class="sub-row"><span class="logo-tile" style="background:${s[5]}">${s[0]}</span><div style="min-width:0"><div>${s[1]}</div><div class="t2 num" style="font-size:11px;color:var(--ink3)">${s[2]}</div></div><span class="cd ${s[4] ? 'soon' : ''}">${s[3]}</span></div>`).join('')}`,
};

M.sky = {
  title: '电脑历史', icon: 'sky', tone: 'steel', meta: 'skysight-sync', stamp: '18:00', span: { c: 3, d: 6 },
  spec: { src: 'skysight-sync 归档（后端读取 NAS）', refresh: '每小时', c: '最近一个时间窗口的摘要', d: '今日全部窗口、应用分布', act: '点击打开电脑历史页对应窗口' },
  c: () => { const s = D.sky[0]; return `<div class="lbl">${s.tm} – ${s.te} · ${s.dev}</div><div style="font-weight:600;margin:5px 0 4px;font-size:13.5px">${s.t}</div>
    <div class="ink2" style="font-size:12px;line-height:1.55;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden">${s.d}</div>
    <div class="foot appdots">${s.apps.map(c => `<i style="--c:${c}"></i>`).join('')}<span class="muted" style="font-size:11px;margin-left:6px">今日 3 个窗口</span></div>`; },
  d: () => D.sky.filter(s => !s.y).map(s => `<div class="sw"><div class="tm">${s.tm}<br>${s.te}<br><span style="color:var(--ink4)">${s.dev}</span></div><div><b>${s.t}</b><p>${s.d}</p><div class="appdots">${s.apps.map(c => `<i style="--c:${c}"></i>`).join('')}</div></div></div>`).join('') + `<button class="chip" style="margin-top:12px" data-go-page="sky">打开电脑历史 ${I.arrow.replace('<svg', '<svg style="width:12px;height:12px"')}</button>`,
};

M.memos = {
  title: 'Memos', icon: 'memos', tone: 'sky', meta: 'memos · ⌃⌥M', stamp: '17:42', span: { c: 3, d: 6 },
  spec: { src: 'Memos API', refresh: '打开时', c: '输入框 + 最新一条', d: '输入框 + 最近 Memo + 常用标签', act: '⌃⌥M 全局快速记录；点击打开 Memos 页' },
  c: () => `<div class="mini-in">记一条…<kbd>⌃⌥M</kbd></div><div style="margin-top:12px;line-height:1.6;font-size:12.5px;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden">${D.memos[0][1]}</div><div class="foot muted" style="font-size:11px">${D.memos[0][0]}</div>`,
  d: () => `<div class="mini-in" style="height:40px">现在的想法是…<kbd>⌃⌥M</kbd></div><div class="row" style="gap:6px;margin:12px 0 14px">${['#日报', '#周报', '#主线', '#阶段目标', '#想法'].map(t => `<button class="chip">${t}</button>`).join('')}</div>
    ${D.memos.map(m => `<div class="memo-it"><div class="tm">${m[0]}</div>${m[1]}</div>`).join('')}`,
};

window.MODS = M; window.I = I; window.T = T; window.mark = mark; window.C = C; window.bars = bars; window.area = area; window.track = track;
