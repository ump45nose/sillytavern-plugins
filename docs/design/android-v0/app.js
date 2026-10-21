/* 安卓大方向设计稿：复用 v1 的 D（示例数据）、I（图标）与图表函数 */
const sv = p => `<svg viewBox="0 0 24 24" fill="currentColor">${p}</svg>`;
const SB_ICONS = sv('<path d="M2 20h3v-4H2zm5 0h3v-8H7zm5 0h3V8h-3zm5 0h3V4h-3z"/>')
  + sv('<path d="M12 20.5 1.5 9a15 15 0 0 1 21 0z" opacity=".95"/>')
  + '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="2.5" y="7" width="17" height="10" rx="2.5"/><rect x="4.5" y="9" width="10" height="6" rx="1" fill="currentColor" stroke="none"/><path d="M21.5 10.5v3" stroke-linecap="round"/></svg>';
const sbar = (lt = false) => `<div class="sb ${lt ? 'lt' : ''}"><span>17:58</span><span class="cam"></span><span class="sb-r">${SB_ICONS}</span></div>`;

const NAV = [['home', '主页'], ['life', '生活'], ['usage', '用量'], ['goals', '复盘'], ['memos', 'Memos']];
const nav = on => `<nav class="nb">${NAV.map(([i, l]) => `<button class="${i === on ? 'on' : ''}"><span class="pi">${I[i]}</span>${l}</button>`).join('')}</nav><i class="gest"></i>`;
const phone = (no, title, desc, inner, cls = '') => `<figure class="ph"><div class="ph-body"><div class="scr ${cls}">${inner}</div></div><figcaption class="cap"><b><span class="no">${no}</span>${title}</b><p>${desc}</p></figcaption></figure>`;
const head = (icon, title, tone, stamp = '17:55', extra = '') => `<div class="m-head" style="${T(tone)}"><span class="m-ico">${I[icon]}</span><span class="m-title">${title}</span>${extra}<span class="m-stamp">${stamp}</span></div>`;
const avatar = `<span class="avatar">玮</span>`;
const syncPill = `<span class="sync"><span class="dot" style="--tone:var(--olive)"></span>12 / 13</span>`;
const topbar = (title, sub, right = avatar) => `<header class="tb"><div><h2>${title}</h2>${sub ? `<p>${sub}</p>` : ''}</div><div class="tb-r">${right}</div></header>`;
const appbar = (title, right = '', back = true) => `<div class="ab">${back ? `<button class="ibtn">${I.chevL}</button>` : ''}<h3>${title}</h3><div class="r">${right}</div></div>`;
const ib = icon => `<button class="ibtn">${I[icon]}</button>`;

/* 主线与复盘：按阶段 5 接口的形状（progress 是文本，不换算百分比） */
const G = {
  mainline: D.mainline,
  cycle: { index: 3, day: 23, total: 42, end: '11/11' },
  goals: [
    { dom: '事业', tone: 'clay', goal: '上线个人信息中心 v1', progress: '安卓设计中', crit: 'Mac 与安卓日常可用' },
    { dom: '关系', tone: 'rose', goal: '每周联系 2 位老朋友', progress: '本周 1 / 2', crit: '6 周不断档' },
    { dom: '身体', tone: 'olive', goal: '每周 3 次力量训练', progress: '本周 2 / 3', crit: '体脂降到 18%' },
  ],
};
const cycleBar = () => `<div class="cycle">${Array.from({ length: G.cycle.total }, (_, i) => `<i class="${i < G.cycle.day - 1 ? 'p' : i === G.cycle.day - 1 ? 'now' : i === G.cycle.total - 1 ? 'close' : ''}" style="--i:${i}"></i>`).join('')}</div>
  <div class="between lbl"><span>第 ${G.cycle.index} 阶段 · 第 ${G.cycle.day} / ${G.cycle.total} 天</span><span>${G.cycle.end} 结案</span></div>`;
const goalRows = (detail = false) => G.goals.map(g => `<div class="gr" style="${T(g.tone)}"><span class="chip t">${g.dom}</span><div class="gt">${g.goal}${detail ? `<small>成功标准：${g.crit}</small>` : ''}</div><span class="gv">${g.progress}</span></div>`).join('');
const reviewTiles = () => `<div class="review"><div class="rv hot"><b>日报</b><span class="lbl">10/19 待确认<br>剩 6 小时</span></div><div class="rv"><b>周报</b><span class="lbl">W42 已归档<br>周日 21:50</span></div><div class="rv"><b>阶段结案</b><span class="lbl">19 天后<br>11/10 预备</span></div></div>`;
const goalsCard = () => `<div class="card" style="--i:2">${head('goals', '主线与复盘', 'clay', '第 23 天')}<div class="ml">${G.mainline}</div>${cycleBar()}${goalRows()}${reviewTiles()}</div>`;

/* ============ 简略模块（手机 2 列） ============ */
const CC = {
  health: () => `${head('health', '健康', 'olive')}<div class="cc-b"><div class="row" style="gap:10px"><div class="rg">${ring(58, 7, 86, 'var(--olive)')}<span class="num">86%</span></div><div><div class="mid">6,842</div><div class="lbl">步 / 8,000</div></div></div></div><div class="cc-f">睡眠 7h12m · 静息 58</div>`,
  bills: () => `${head('bills', '账单', 'kraft')}<div class="cc-b"><div class="big">¥128.5</div><div class="lbl" style="margin:4px 0 10px">今日支出</div>${track(86, 'var(--kraft)', 'thin')}</div><div class="cc-f">本月 ¥4,312 / 5,000</div>`,
  crm: () => `${head('crm', '交流', 'sky')}<div class="cc-b"><div class="pstack" style="margin-bottom:10px">${D.crm.today.map(p => `<span class="pp" style="${T(p.tone)}">${p.n}</span>`).join('')}</div><div><span class="mid">4</span> <span class="lbl">人 · 2 段录音</span></div></div><div class="cc-f">赵六 46 天未联系</div>`,
  media: () => `${head('media', '媒体', 'plum')}<div class="cc-b"><div class="row" style="gap:10px"><div class="poster" style="--pg:${D.media.cont[0].g};width:46px;flex:none;border-radius:8px;animation:none"><i class="pr" style="width:62%"></i></div><div style="min-width:0"><div style="font-family:var(--serif);font-size:14px;line-height:1.3">沙丘：预言</div><div class="lbl">S1 · E4 · 62%</div></div></div></div><div class="cc-f">下载中 2 · 小巷人家 73%</div>`,
  token: () => `${head('token', 'Token', 'clay')}<div class="cc-b"><div class="big">18.6<small>M</small></div><div class="lbl" style="margin:4px 0 9px">今日 · 估算 $42.17</div><div class="between lbl" style="margin-bottom:4px"><span>Claude 本周</span><span>61%</span></div>${track(61, 'var(--ochre)', 'thin')}</div><div class="cc-f">Codex 5 小时 18%</div>`,
  git: () => `${head('git', 'GitHub', 'steel')}<div class="cc-b"><div class="row" style="gap:16px"><div><div class="big">3</div><div class="lbl">等我回复</div></div><div><div class="big" style="color:var(--clay-d)">4</div><div class="lbl">阻塞 PR</div></div></div></div><div class="cc-f">#2790 等 review 9 天</div>`,
  net: () => `${head('net', '网络', 'sage')}<div class="cc-b" style="align-items:center"><div style="transform:scale(.72);transform-origin:50% 60%;margin:-12px 0 -16px">${gauge(64, 'var(--sage)')}</div><div class="mid" style="margin-top:-2px">182<small class="lbl"> GB 剩余</small></div></div><div class="cc-f" style="text-align:center">主力机场 · 11/30 到期</div>`,
  subs: () => `${head('subs', '订阅', 'ochre')}<div class="cc-b"><div class="big">¥1,486<small>/ 月</small></div><div class="lbl" style="margin-top:10px">Claude Max · 8 天后</div><div class="lbl">域名 ×2 · 5 天后</div></div><div class="cc-f">共 7 项</div>`,
};
const compactGrid = () => `<div class="g2">${['health', 'bills', 'crm', 'media', 'token', 'git', 'net', 'subs'].map((k, i) => `<div class="card cc" style="--i:${i + 3}">${CC[k]()}</div>`).join('')}</div>`;

/* ============ 1 主页 ============ */
const attention = D.attention.filter(a => !a.t.includes('逾期'));
const home = () => sbar() + `<div class="sc">
  <div class="hm-top"><span class="mk-s">${mark()}</span><span class="date">10 月 20 日 · 周二</span><span class="row" style="margin-left:auto;gap:8px">${syncPill}${avatar}</span></div>
  <h1 class="hi">晚上好，玮康</h1>
  <p class="say">今天走了 <a>6,842 步</a>，花了 <a>¥128.5</a>，和 <a>4 个人</a>聊过。<a>昨天的日报</a>还在等你确认。</p>
  <div class="sect-h">需要注意<span class="n">${attention.length}</span><span class="more">全部 ›</span></div>
  <div class="hs">${attention.map((a, i) => `<div class="att-c" style="${T(a.tone)};--i:${i}"><span class="dot"></span><div><b>${a.t}</b><span>${a.s}</span></div></div>`).join('')}</div>
  <div class="sect-h">主线与复盘</div>
  ${goalsCard()}
  <div class="sect-h">今天<span class="more">长按模块可编辑</span></div>
  ${compactGrid()}
  <button class="edit-ghost">${I.grid}编辑布局</button>
</div><button class="fab">${I.memos}<span>记一条</span></button>` + nav('home');

/* ============ 2 生活 ============ */
const life = () => sbar() + `<div class="sc">${topbar('生活', '健康 · 账单 · 交流 · 媒体')}
  <div class="card">${head('health', '健康', 'olive', 'personal-records · 17:52')}
    <div class="row" style="gap:16px;align-items:center"><div class="rg" style="width:96px;height:96px">${ring(96, 9, 86, 'var(--olive)')}<span class="num" style="flex-direction:column;font-size:20px;line-height:1.1;display:flex;align-items:center;justify-content:center">6,842<small class="lbl" style="font-family:var(--sans)">/ 8,000 步</small></span></div>
      <div class="stats" style="flex:1;grid-template-columns:1fr 1fr"><div><div class="lbl">活动</div><div class="v">412<small>/500 kcal</small></div></div><div><div class="lbl">锻炼</div><div class="v">18<small>/30 分</small></div></div><div><div class="lbl">静息心率</div><div class="v">58<small>bpm</small></div></div><div><div class="lbl">血氧</div><div class="v">97<small>%</small></div></div></div></div>
    <div class="sect">睡眠 7h12m</div><div class="sleepbar">${D.health.stages.map(s => `<i style="flex:${s[1]};background:${s[2]}"></i>`).join('')}</div>
    <div class="legend">${D.health.stages.map(s => `<span style="--c:${s[2]}">${s[0]}</span>`).join('')}</div>
    <div class="sect">近 14 天步数</div>${bars(D.health.steps14, { h: 52, tone: 'var(--olive)', labels: days14 })}
  </div>
  <div class="card">${head('bills', '账单', 'kraft', 'AutoAccounting · 17:50')}
    <div class="row" style="gap:20px;align-items:flex-end"><div><div class="lbl">今日</div><div class="big">¥128.5</div></div><div style="flex:1"><div class="between lbl" style="margin-bottom:5px"><span>本月 ¥4,312.6</span><span>预算 5,000</span></div>${track(86, 'var(--kraft)')}</div></div>
    <div class="sect">今日明细</div>${D.bills.items.map(b => `<div class="li"><div><div>${b[0]}</div><div class="t2">${b[1]} · ${b[2]}</div></div><span class="r amt">¥${b[3]}</span></div>`).join('')}
    <div class="sect">本月分类</div><div class="stackbar">${D.bills.cats.map(c => `<i style="flex:${c[1]};background:${c[2]}"></i>`).join('')}</div>
    <div class="legend">${D.bills.cats.map(c => `<span style="--c:${c[2]}">${c[0]} ¥${c[1]}</span>`).join('')}</div>
  </div>
  <div class="card">${head('crm', '交流', 'sky', 'personal-crm · Plaud')}
    ${D.crm.today.slice(0, 3).map(p => `<div class="ia"><div class="who"><span class="pp" style="${T(p.tone)}">${p.n}</span><b>${p.who}</b><span>${p.rel} · ${p.ch} · ${p.tm}</span></div><p>${p.s}</p>${p.rec ? `<div class="rec"><span class="play">${I.play}</span><span>${p.rec}</span><span class="wv">${Array.from({ length: 22 }, (_, i) => `<i class="${i < 7 ? 'on' : ''}" style="height:${30 + Math.abs(Math.sin(i * 1.3)) * 70}%"></i>`).join('')}</span><span class="muted">${p.dur}</span><span class="tr">转录</span></div>` : ''}</div>`).join('')}
    <div class="sect">本阶段</div><div class="stats"><div><div class="lbl">联系人</div><div class="v">23</div></div><div><div class="lbl">交流</div><div class="v">87</div></div><div><div class="lbl">录音</div><div class="v">11</div></div></div>
  </div>
  <div class="card">${head('media', '媒体', 'plum', 'Emby · Navidrome')}
    <div class="lbl" style="margin-bottom:8px">继续观看</div>
    <div class="hs" style="margin:0 -15px;padding:2px 15px 6px">${D.media.cont.map((m, i) => `<div class="poster" style="--pg:${m.g};--i:${i}"><span class="glyph">${m.t[0]}</span><span class="pt">${m.t}<small>${m.s}</small></span><i class="pr" style="width:${m.p}%"></i></div>`).join('')}</div>
    <div class="sect">下载</div>${D.media.dl.map(d => `<div class="li"><div style="flex:1"><div class="between" style="margin-bottom:6px"><span>${d[0]}</span><span class="muted">${d[1]}%</span></div>${track(d[1], 'var(--plum)', 'thin')}</div></div>`).join('')}
    <div class="svc">${['Emby', 'Navidrome', 'MoviePilot', 'qBittorrent'].map(s => `<span class="chip"><span class="dot" style="--tone:var(--olive)"></span>${s}</span>`).join('')}</div>
  </div>
</div>` + nav('life');

/* ============ 3 用量 ============ */
const W = TOKEN_RANGES.w;
const usage = () => sbar() + `<div class="sc">${topbar('用量', 'Token · GitHub · 网络 · 订阅')}
  <div class="card">${head('token', 'Token 用量', 'clay', '17:55')}
    <div class="segc" style="margin-bottom:12px"><button>日</button><button class="on">周</button><button>月</button><button>年</button></div>
    <div class="row" style="align-items:baseline;gap:8px"><span class="big">${fmtTok(W.total)}</span><span class="chip t" style="${T('olive')}">较前 7 天 +${pct(W.total, W.prev)}%</span></div>
    <div class="lbl" style="margin:4px 0 12px">${W.label}</div>
    <div class="stats" style="margin-bottom:14px"><div><div class="lbl">估算成本</div><div class="v">$${Math.round(W.total * COST_PER_M)}</div></div><div><div class="lbl">峰值</div><div class="v" style="font-size:15px">${W.peak}</div></div><div><div class="lbl">日均</div><div class="v">${fmtTok(W.avg)}</div></div></div>
    ${tokenHeat(W)}<div class="row" style="margin-top:2px"><span class="lbl">按小时 × 日期</span>${heatLegend()}</div>
    <div class="sect">额度</div>${D.token.limits.slice(0, 2).map(l => l.rows.map(r => `<div style="margin-bottom:10px"><div class="between" style="font-size:12px;margin-bottom:5px"><span><b style="font-weight:600">${l.tool}</b> <span class="muted">${r[0]}</span></span><span class="amt">${r[1]}%</span></div>${track(r[1], r[1] >= 60 ? 'var(--ochre)' : l.tone, 'thin')}<div class="lbl" style="margin-top:3px">${r[2]}</div></div>`).join('')).join('')}
  </div>
  <div class="card">${head('git', 'GitHub', 'steel', '17:56')}
    <div class="segc" style="margin-bottom:10px"><button class="on">等我回复 3</button><button>阻塞 PR 4</button></div>
    ${D.git.waitMe.map(g => { const k = { reply: ['评论回复', 'sky'], review: ['请求 review', 'plum'], mention: ['@提及', 'ochre'] }[g.k]; return `<div class="gh-i"><div class="gh-m"><span class="gk" style="${T(k[1])}">${k[0]}</span><span class="pr-n">${g.repo.replace('ump45nose/', '')}#${g.n}</span><span style="margin-left:auto">${g.ago}</span></div><div class="gh-t">${g.t}</div><div class="gh-q">${g.who}：${g.q}</div></div>`; }).join('')}
    <div class="swipe">← 左滑稍后 · 右滑已处理 →</div>
  </div>
  <div class="card">${head('net', '网络', 'sage', 'ShellCrash')}
    <div class="row" style="gap:14px"><div style="position:relative">${gauge(64, 'var(--sage)')}<div style="position:absolute;left:0;right:0;bottom:2px;text-align:center"><span class="mid">182</span><span class="lbl"> GB</span></div></div>
    <div style="flex:1">${D.net.pools.map(p => `<div style="margin-bottom:9px"><div class="between" style="font-size:12px;margin-bottom:4px"><span>${p.n}</span><span class="muted">${p.used} / ${p.total} GB</span></div>${track(p.used / p.total * 100, 'var(--sage)', 'thin')}<div class="lbl" style="margin-top:3px">${p.exp}</div></div>`).join('')}</div></div>
    <div class="lbl">今日 ↓ ${D.net.down} GB · ↑ ${D.net.up} GB · 本月 ${D.net.month} GB</div>
  </div>
  <div class="card">${head('subs', '订阅', 'ochre', '月合计 ¥1,486')}
    ${D.subs.list.slice(0, 5).map(s => `<div class="li"><span class="sub-i" style="background:${s[5]}">${s[0]}</span><div><div>${s[1]}</div><div class="t2">${s[2]}</div></div><span class="r ${s[4] ? '' : 'muted'}" style="${s[4] ? 'color:var(--clay-d)' : ''}">${s[3]}</span></div>`).join('')}
  </div>
</div>` + nav('usage');

/* ============ 4 复盘 ============ */
const review = () => sbar() + `<div class="sc">${topbar('复盘', '第 3 阶段 · 第 23 / 42 天 · 11/11 结案')}
  <div class="card hot-c">${head('review', '待确认', 'clay', '剩 6 小时')}
    <div style="font-family:var(--serif);font-size:20px;margin-bottom:4px">10 月 19 日 日报</div>
    <div class="lbl">灵珺 21:30 生成 · Telegram 也可确认，先确认者生效</div>
    <div class="row" style="margin-top:14px;gap:8px"><button class="btn pri">去确认 ${I.arrow}</button><button class="btn">看原文</button></div>
  </div>
  <div class="card">${head('goals', '主线', 'clay', '9/14 更新')}<div class="ml">${G.mainline}</div>
    <div class="lbl" style="margin-top:6px;line-height:1.6">方向：把分散的个人数据汇成每天能看、定期能复盘的系统。</div>${cycleBar()}</div>
  <div class="card">${head('spark', '阶段目标', 'clay', '3 / 5')}${goalRows(true)}</div>
  <div class="acts"><div class="act">${I.reply}记进度<span>给目标写一条</span></div><div class="act">${I.plus}新增目标<span>还可加 2 个</span></div><div class="act" style="opacity:.55">${I.goals}阶段结案<span>11/10 开放</span></div></div>
  <div class="sect-h">历史</div>
  <div class="card hist">${[['10/18 日报', '已归档 · Telegram 确认', 'st', '已归档'], ['W42 周报', '已归档 · App 确认', 'st', '已归档'], ['10/17 日报', '未确认，已过期', 'st exp', '已过期'], ['10/16 日报', '已归档 · App 确认', 'st', '已归档']].map(h => `<div class="li"><div><div>${h[0]}</div><div class="t2">${h[1]}</div></div><span class="r"><span class="${h[2]}">${h[3]}</span></span></div>`).join('')}</div>
</div>` + nav('goals');

/* ============ 5 日报确认 ============ */
const daily = () => sbar() + appbar('10/19 日报', `<span class="chip t" style="${T('clay')};margin-right:4px">剩 6 小时</span>${ib('more')}`)
  + `<div class="tabs"><button class="on">填写</button><button>灵珺原文</button><button>材料</button></div>
  <div class="sc nonav" style="padding-bottom:110px">
    <div class="fld"><label>一句话总结今天<span class="c">18 / 45</span></label><div class="inp ta">迁移方案拆成两期，个人中心设计定稿。</div></div>
    <div class="fld"><label>情绪</label><div class="chips">${['愉快', '充实', '平静', '疲惫', '焦虑'].map((w, i) => `<span class="chip ${i === 1 ? 'on' : ''}">${w}</span>`).join('')}</div></div>
    <div class="fld"><label>健康<span class="auto">确认时自动填入</span></label><div class="inp dis">步数、睡眠、心率由 personal-review 补全</div></div>
    <div class="fld"><label>财务<span class="auto">确认时自动填入</span></label><div class="inp dis">今日支出与分类由 personal-review 补全</div></div>
    <div class="fld"><label>留痕</label><div class="inp ta">Plaud 归档布局迁移完成，补了音频链接测试。</div></div>
    <div class="fld"><label>未解<span class="c">1 / 2</span></label><div class="inp">Q4 迁移排期还没和韩梅梅对齐</div></div>
    <div class="fld"><label>明天唯一重点</label><div class="inp foc">提交 Q4 迁移方案<span class="caret"></span></div></div>
    <div class="fld"><label>瞬间</label><div class="inp err">下雨</div><div class="e-msg">瞬间至少 6 个字</div></div>
  </div>
  <div class="bbar"><button class="btn">预览终稿</button><button class="btn pri">确认归档</button></div><i class="gest"></i>`;

/* ============ 6 Memos + 记一条 ============ */
const memos = () => sbar() + appbar('Memos', `${ib('search')}${ib('arrow')}`, false)
  + `<div class="web"><div class="bar">${I.search} 搜索 Memo</div>
    ${D.memos.map(m => `<div class="mc"><div class="tm">${m[0]}</div>${m[1]}</div>`).join('')}
    <div class="mc"><div class="tm">昨天 09:12</div>Plaud 归档的音频相对链接要在 Obsidian 里再验一遍。</div>
  </div>${nav('memos')}
  <div class="scrim"></div>
  <div class="sheet"><div class="hd"></div><h4>${I.memos}记一条<span class="muted" style="margin-left:auto;font-weight:400;font-size:12px">草稿自动保存</span></h4>
    <div class="inp foc">安卓底部导航定为五项，电脑历史先不上 <span class="tag">#想法</span><span class="caret"></span></div>
    <div class="row2"><div class="chips">${['#日报', '#主线', '#想法'].map(t => `<span class="chip">${t}</span>`).join('')}</div><span class="chip">私密 ▾</span><button class="send">${I.arrow}</button></div>
    <div class="kb">${[10, 9, 9, 5].map((n, r) => `<div>${r === 2 ? '<i class="w"></i>' : ''}${Array.from({ length: r === 3 ? 3 : n }, (_, k) => `<i class="${r === 3 && k === 1 ? 'sp' : r === 3 ? 'w' : ''}"></i>`).join('')}${r === 2 ? '<i class="w"></i>' : ''}</div>`).join('')}</div>
  </div>`;

/* ============ 7 首次登录 ============ */
const login = () => sbar() + `<div class="lg"><div class="mk-l">${mark({ anim: true })}</div>
  <h1>Personal Hub</h1><div class="tag2">个人信息中心</div>
  <p class="say">健康、账单、交流、媒体、用量和复盘，<br>和 Mac 看到的是同一份。</p>
  <div class="fld"><label>hub 地址</label><div class="inp">hub-home.172906573.xyz:28443</div></div>
  <button class="btn pri">用 Authelia 登录</button>
  <div class="note">在浏览器完成登录和双重验证后自动回到 App。设备令牌只存在本机 Keystore，可在 Mac 或设置里单独吊销。</div>
  <button class="ghost">先看示例数据</button>
</div><i class="gest"></i>`;

/* ============ 8 设置 ============ */
const it = (icon, tone, t, v, sub = '') => `<div class="it"><span class="ic" style="${T(tone)}">${I[icon]}</span><div>${t}${sub ? `<small>${sub}</small>` : ''}</div>${v}</div>`;
const chev = `<span class="chev">${I.chevR}</span>`;
const settings = () => sbar() + appbar('设置') + `<div class="sc nonav">
  <div class="lst"><div class="it" style="min-height:70px">${avatar.replace('avatar', 'avatar" style="width:42px;height:42px;font-size:18px')}<div><b style="font-weight:600;font-size:15px">玮康</b><small>Pixel · 10/21 登录 · 令牌存于 Keystore</small></div><span class="v" style="color:var(--clay-d)">退出</span></div></div>
  <div class="grp-t">数据</div>
  <div class="lst">${it('sync', 'olive', '来源状态', `<span class="v">12 / 13 正常</span>${chev}`, '<span class="srcdots" style="width:150px;margin-top:6px"><i></i><i></i><i></i><i></i><i class="w"></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></span>')}
    ${it('grid', 'steel', '布局', `<span class="v">与 Mac 同步 · v3</span>${chev}`)}
    ${it('net', 'sky', 'hub 地址', `<span class="v">公网 28443</span>${chev}`, '局域网时自动走 192.168.31.201')}</div>
  <div class="grp-t">通知</div>
  <div class="lst">${it('attention', 'clay', '需要注意', '<span class="tg on"></span>', '额度、流量、PR、续费、来源故障')}
    ${it('review', 'clay', '日报 / 周报待确认', '<span class="tg on"></span>')}
    ${it('spark', 'ochre', '检查频率', `<span class="v">15 分钟</span>${chev}`)}</div>
  <div class="grp-t">显示</div>
  <div class="lst">${it('brief', 'kraft', '主题', `<span class="v">浅色</span>${chev}`)}${it('life', 'sage', '减弱动效', `<span class="v">跟随系统</span>${chev}`)}</div>
  <div class="grp-t">关于</div>
  <div class="lst">${it('home', 'plum', 'Personal Hub', '<span class="v">0.1.0 · 侧载</span>')}</div>
</div><i class="gest"></i>`;

/* ============ 9 通知与小组件 ============ */
const system = () => sbar(true) + `<div class="sc nonav" style="padding-bottom:40px">
  <div class="clk">17:58</div><div class="clk-d">10 月 20 日 星期二</div>
  <span class="sys-l">通知</span>
  <div class="nt"><div class="h"><span class="ai">${mark()}</span>Personal Hub · 现在</div><b>10/19 日报待确认</b><p>剩 6 小时 · 灵珺 21:30 生成</p><div class="na"><span>去确认</span><span>稍后</span></div></div>
  <div class="nt"><div class="h"><span class="ai">${mark()}</span>Personal Hub · 12 分钟前</div><b>Codex 5 小时 额度已用 86%</b><p>20:00 重置</p></div>
  <span class="sys-l" style="margin-top:8px">桌面小组件（可选）</span>
  <div class="wg"><div class="between"><span style="font-family:var(--serif);font-size:17px">晚上好，玮康</span><span class="chip t" style="${T('clay')}">4 条需要注意</span></div>
    <div class="k3"><div><div class="lbl">步数</div><div class="mid">6,842</div></div><div><div class="lbl">支出</div><div class="mid">¥128</div></div><div><div class="lbl">Token</div><div class="mid">18.6M</div></div></div></div>
  <div class="wg-row"><div class="wg" style="padding:14px"><div class="lbl">第 3 阶段</div><div class="row" style="gap:10px;margin-top:8px"><div class="rg" style="width:46px;height:46px">${ring(46, 6, 55, 'var(--clay)')}<span class="num" style="font-size:11px">23</span></div><div class="lbl" style="line-height:1.4">/ 42 天<br>11/11 结案</div></div></div>
    <div class="wg" style="padding:14px;display:flex;flex-direction:column;justify-content:space-between"><div class="lbl">快捷</div><div style="display:flex;align-items:center;gap:8px;font-weight:600;color:var(--clay-d)">${I.memos}记一条</div></div></div>
  <div class="dock"><span><i class="ico hub">${mark()}</i>Hub</span><span><i class="ico"></i>Tasks</span><span><i class="ico"></i>Telegram</span><span><i class="ico"></i>相机</span></div>
</div><i class="gest lt"></i>`;

/* ============ 布局规则与决定 ============ */
const colsDemo = (n, items) => `<div class="cols" style="grid-template-columns:repeat(${n},1fr)">${items.map(([s, cls, t]) => `<i class="${cls}" style="grid-column:span ${s}">${t}</i>`).join('')}</div>`;
document.getElementById('rules').innerHTML = `
  <div class="rule"><h4>Mac · 12 列（主页）</h4><p>布局的唯一来源。简略默认 3 列，详细按模块定义（5 / 6 / 7 / 12）。</p>${colsDemo(12, [[12, 'd', '今日简报'], [7, 'd', '日程与任务 · 详（仅 Mac）'], [5, 'd', '主线与复盘 · 详'], [12, 'd', '需要注意'], [3, 'c', '健康'], [3, 'c', '账单'], [3, 'c', '交流'], [3, 'c', '媒体']])}</div>
  <div class="rule"><h4>手机 · 4 列</h4><p>简略 → 2 列（两两并排）；详细 → 4 列（独占一行）。日程与任务跳过；需要注意固定紧跟简报，显示为横滑条。</p>${colsDemo(4, [[4, 'd', '今日简报'], [4, 'd', '需要注意 · 横滑'], [4, 'd', '主线与复盘 · 详'], [2, 'c', '健康'], [2, 'c', '账单'], [2, 'c', '交流'], [2, 'c', '媒体']])}</div>
  <div class="rule"><h4>平板 / 折叠屏展开 · 8 列</h4><p>简略 → 2 列（一行四个）；详细 5–7 列 → 4 列（一行两个）；12 列 → 8 列。底部导航换成侧边导航栏。</p>${colsDemo(8, [[8, 'd', '今日简报'], [8, 'd', '需要注意'], [4, 'd', '主线与复盘 · 详'], [4, 'd', 'Token · 详'], [2, 'c', '健康'], [2, 'c', '账单'], [2, 'c', '交流'], [2, 'c', '媒体']])}</div>`;

document.getElementById('dec').innerHTML = [
  ['底部导航五项', '主页 / 生活 / 用量 / 复盘 / Memos，设置放在右上头像。<span class="q">推荐：</span>复盘单独成 Tab（Mac 上是 ⌘6 窗口），因为日报每天都要处理。'],
  ['电脑历史', 'hub 现在没有接口，Mac 是读本机归档。<span class="q">推荐：</span>安卓首版不放，等 NAS 补 sky 模块后作为「更多」或生活页的一个模块加入。'],
  ['记一条的入口', '主页悬浮按钮 + 桌面长按快捷方式 + 小组件。<span class="q">推荐：</span>悬浮按钮只在主页出现，其他页靠快捷方式，避免遮挡列表。'],
  ['编辑布局', '长按模块进入编辑：简 / 详切换、拖动排序、删除、添加。和 Mac 同一份布局 JSON，经 hub 同步，版本冲突时提示以哪端为准。'],
  ['模块点进去', '简略模块点击 → 跳到所在页并定位到详细版（如健康 → 生活页）。<span class="q">备选：</span>每个模块单独一个全屏详情页。'],
  ['主题与配色', '<span class="q">推荐：</span>首版只做浅色，和 Mac 稿一致；不使用 Material You 动态取色，保持陶土主色与模块大地色。深色模式放到之后。'],
  ['字体', '数字和标题用衬线：打包 Source Serif 4（只含拉丁与数字），中文回退系统 Noto Serif CJK；正文用系统无衬线。'],
  ['推送', '通知样式如第 9 张。<span class="q">推荐：</span>首版 WorkManager 每 15 分钟拉一次需要注意，按提醒 ID 去重，后端不改；要实时再接 FCM。'],
].map(([t, d]) => `<div><b>${t}</b>${d}</div>`).join('');

document.getElementById('docMark').innerHTML = mark();
document.getElementById('tabs').innerHTML = [
  phone(1, '主页', '简报 → 需要注意（横滑）→ 主线与复盘（详）→ 8 个简略模块两两并排。右下「记一条」，右上是来源状态和头像。', home()),
  phone(2, '生活', '健康、账单、交流、媒体的详细版纵向排列。录音在交流里直接播放、看转录；海报墙横滑。', life()),
  phone(3, '用量', 'Token 支持日 / 周 / 月 / 年切换和热力图；GitHub 分「等我回复 / 阻塞 PR」，左右滑稍后或已处理。', usage()),
  phone(4, '复盘', '顶部是待确认的日报 / 周报；下面是主线、阶段目标、记进度 / 新增目标 / 阶段结案，以及历史。', review()),
].join('');
document.getElementById('flows').innerHTML = [
  phone(5, '日报确认', '按字段填写，规则与服务端一致并在本地先校验；健康、财务确认时自动补全。先预览终稿，再确认归档。', daily()),
  phone(6, 'Memos 与记一条', 'Memos 整页嵌入网页；「记一条」是底部弹层，支持标签和可见性，失败时留本地草稿。', memos()),
].join('');
document.getElementById('sys').innerHTML = [
  phone(7, '首次登录', '默认公网 hub 地址，浏览器经 Authelia 登录后通过 personalhub://auth 回到 App。', login()),
  phone(8, '设置', '账户与设备、来源状态、布局同步、通知开关和检查频率、主题。', settings()),
  phone(9, '通知与桌面小组件', '需要注意条目以系统通知送达，日报通知可直接「去确认」。小组件为可选项。', system(), 'wall'),
].join('');

const only = new URLSearchParams(location.search).get('only');
if (only) {
  document.body.classList.add('only');
  document.querySelectorAll('.ph').forEach((f, i) => { if (String(i + 1) !== only) f.remove(); });
  document.querySelectorAll('.doc-sec').forEach(s => { if (!s.querySelector('.ph')) s.remove(); });
}
const sec = new URLSearchParams(location.search).get('sec');
if (sec) document.querySelectorAll('.doc-sec').forEach((s, i) => { if (String(i + 1) !== sec) s.remove(); });
if (new URLSearchParams(location.search).has('tall')) document.body.classList.add('tall');
const scrollTo = +new URLSearchParams(location.search).get('scroll');
if (scrollTo) document.querySelectorAll('.sc').forEach(s => { s.scrollTop = scrollTo; });
