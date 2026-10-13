import fs from 'node:fs';
const dir = 'artifacts/design-fidelity';
const pages = ['角色管理','用户设定','生成配置','连接','世界书','用户设置','回复格式','背景','扩展'];
const sizes = [[1496,817],[1366,768],[1440,900],[1920,1080]];
const extras = [
 ['顶栏资源选中样式','../preferences/selection-header-persona-1496.png'],
 ['侧栏资源选中样式','../preferences/selection-sidebar-persona-1496.png'],
 ['T 中的正文留白滑条','../preferences/reading-settings-1496.png'],
 ['自定义快捷键','../preferences/custom-shortcuts-1496.png'],
 ['世界书编辑区展开','../click-motion/world-editor.png'],
 ['提示词编辑区展开','../click-motion/prompt-editor.png'],
 ['预设与一级资源列','../migration-runtime/sidebar-预设-1496.png'],
 ['世界书与一级资源列','../migration-runtime/sidebar-世界书-1496.png'],
 ['连接与一级资源列','../migration-runtime/sidebar-连接-1496.png'],
 ['用户输入展开与悬浮信息','../motion-layout/reading-expanded-1496.png'],
 ['快捷回复','../migration-runtime/quick-reply-1496.png'],
 ['背景单行工具栏与图库','../motion-layout/background-1496.png'],
 ['折叠控件与选中边框','../motion-layout/home-selection-1496.png'],
 ['外观与阅读','../migration-runtime/settings-1496.png'],
 ['高级参数','../migration-runtime/generation-advanced-1496.png'],
 ['指令模板','checked-回复格式-指令模板.png'],
 ['消息与输入','checked-用户设置-消息与输入.png'],
 ['酒馆助手脚本','../migration-runtime/helper-scripts-1496.png'],
 ['世界书绑定与全局设置','checked-world-bindings.png'],
 ['群组编辑','checked-group-editor.png'],
];
if (fs.existsSync('artifacts/migration-runtime/home-reading-1496.png')) extras.unshift(['阅读主页','../migration-runtime/home-reading-1496.png']);
const verification = JSON.parse(fs.readFileSync(`${dir}/verification.json`, 'utf8'));
const migration = JSON.parse(fs.readFileSync('artifacts/migration-runtime/verification.json', 'utf8'));
const clicking = JSON.parse(fs.readFileSync('artifacts/click-motion/verification.json', 'utf8'));
const motion = JSON.parse(fs.readFileSync('artifacts/motion-layout/verification.json', 'utf8'));
const preferences = JSON.parse(fs.readFileSync('artifacts/preferences/verification.json', 'utf8'));
if (!preferences.passed || preferences.errors.length) throw new Error('留白、选中样式或自定义快捷键检查未通过。');
if (!verification.passed || !migration.checks.every(x=>x.passed) || migration.errors.length) throw new Error('运行检查未通过，不能生成通过状态的页面。');
if (!motion.passed || motion.errors.length) throw new Error('动画和布局检查未通过，不能生成通过状态的页面。');
if (!clicking.passed || clicking.errors.length || !fs.existsSync('artifacts/click-motion/actual-clicks.mp4')) throw new Error('真实点击检查或录像缺失，不能生成通过状态的页面。');
for (const name of pages) for (const [w] of sizes) {
 if (!fs.existsSync(`${dir}/checked-${name}-${w}.png`)) throw new Error(`缺少实际页面截图：${name} ${w}`);
}
for (const [,file] of extras) if (!fs.existsSync(`${dir}/${file}`)) throw new Error(`缺少实际页面截图：${file}`);
const src = s => encodeURI(s);
fs.writeFileSync(`${dir}/review.html`, `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Noval · 实际页面检查图</title>
<style>body{margin:0;background:#faf9f5;color:#35312b;font:14px/1.7 system-ui}header{padding:22px 26px;border-bottom:1px solid #e2ddd2}h1{margin:0 0 8px;font-size:23px;font-weight:500}p{margin:6px 0;color:#81786b}nav{position:sticky;top:0;z-index:2;display:flex;align-items:center;gap:16px;flex-wrap:wrap;padding:12px 26px;background:#f0eee6;border-bottom:1px solid #e2ddd2}select{background:#fffefa;color:#35312b;border:1px solid #d9d1c4;border-radius:7px;padding:8px 12px;font:inherit}main{padding:18px 26px}figure{margin:0}figcaption{padding:8px 0;color:#81786b}video{display:block;width:100%;max-height:82vh;background:#f0eee6;border:1px solid #e2ddd2;border-radius:8px}img{display:block;width:100%;height:auto;border:1px solid #e2ddd2;border-radius:8px;background:#fffefa}a{color:#b76449}.viewport{overflow:auto}.viewport.is-original img{width:var(--actual-width);max-width:none;border:0;border-radius:0}.extra{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:22px;margin:20px 0}h2{font-size:18px;font-weight:500;margin-top:30px}@media(max-width:900px){.extra{grid-template-columns:1fr}header,nav,main{padding-left:16px;padding-right:16px}}</style>
<header><h1>Noval · 实际页面检查图</h1><p>主工作区为 1496 × 817 CSS px；其他尺寸沿用同一布局规则。以下全部来自运行中的隔离验证实例。</p><p>默认缩略展示，点击图片可查看原图；勾选“原始尺寸”按对应 CSS 宽度展示。原设计稿保持原文件。</p></header>
<nav><label>页面 <select id="page">${pages.map(name=>`<option>${name}</option>`).join('')}</select></label><label>浏览器工作区 <select id="size">${sizes.map(([w,h])=>`<option value="${w}">${w} × ${h}</option>`).join('')}</select></label><label><input id="original" type="checkbox"> 原始尺寸</label><a href="verification.json">功能检查记录</a><a href="../migration-runtime/verification.json">布局与迁移检查</a><a href="../motion-layout/verification.json">动画帧与布局检查</a></nav>
<main><h2>验证酒馆 · 真实鼠标点击录像</h2><p>菜单和下拉框的打开／关闭、编辑区收纳、勾选及设置切换。<a href="../click-motion/verification.json">点击动画检查记录</a></p><video controls preload="metadata" src="../click-motion/actual-clicks.mp4"></video><h2>实际页面截图</h2><figure><figcaption id="actual-label"></figcaption><div class="viewport" id="viewport"><a id="actual-link"><img id="actual" alt="实际运行页面"></a></div></figure><h2>具体操作与编辑状态 · 1496 × 817</h2><div class="extra">${extras.map(([label,file])=>`<figure><figcaption>${label}</figcaption><a href="${src(file)}"><img loading="lazy" src="${src(file)}" alt="${label}"></a></figure>`).join('')}</div></main>
<script>const page=document.getElementById('page'),size=document.getElementById('size'),original=document.getElementById('original'),viewport=document.getElementById('viewport');function show(){const actual=encodeURI('checked-'+page.value+'-'+size.value+'.png');document.getElementById('actual').src=actual;document.getElementById('actual-link').href=actual;document.getElementById('actual-label').textContent=page.value+' · 实际运行页面 · '+size.selectedOptions[0].textContent+' CSS px';viewport.style.setProperty('--actual-width',size.value+'px');viewport.classList.toggle('is-original',original.checked);}page.onchange=show;size.onchange=show;original.onchange=show;show();</script></html>`);
console.log(`${dir}/review.html`);
