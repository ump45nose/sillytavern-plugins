/* Layout prototype only. No SillyTavern APIs, credentials, storage or model calls. */
const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icon = (name, extra = '') => `<svg class="icon ${extra}" aria-hidden="true"><use href="#i-${name}"></use></svg>`;
const button = (action, name, glyph, cls = '', attrs = '') => `<button class="${cls}" data-action="${action}" ${attrs}>${glyph ? icon(glyph) : ''}<span>${esc(name)}</span></button>`;
const ib = (action, name, glyph, attrs = '') => `<button class="icon-button" data-action="${action}" aria-label="${esc(name)}" title="${esc(name)}" ${attrs}>${icon(glyph)}</button>`;
const field = (label, content, cls = '') => `<label class="field ${cls}"><span>${esc(label)}</span>${content}</label>`;
const check = (label, key, checked) => `<label class="check"><input type="checkbox" data-field="${key}" ${checked ? 'checked' : ''}>${esc(label)}</label>`;
const input = (key, value, attrs = '') => `<input data-field="${key}" value="${esc(formValue(key,value))}" ${attrs}>`;
const area = (key, value, attrs = '') => `<textarea data-field="${key}" ${attrs}>${esc(formValue(key,value))}</textarea>`;
const select = (key, value, options, attrs = '') => `<select data-field="${key}" ${attrs}>${options.map(([id, label]) => `<option value="${esc(id)}" ${String(id) === String(formValue(key,value)) ? 'selected' : ''}>${esc(label)}</option>`).join('')}</select>`;
const states = [['todo', '未开始'], ['running', '进行中'], ['done', '已完成']];
const backends = ['OpenAI 兼容', 'Gemini', 'NovelAI', 'A1111', 'ComfyUI'];
const sampleImage = '../rp-desktop/assets/r-background.webp';
const initialNodes = [
  {id:'chapter1', parent:null, title:'第一章 · 林间重逢', content:'故事发生在 Eldoria 的古老森林。\n\n保持温柔、克制的叙事。让角色通过动作表达关心，避免直接解释情绪。', status:'running', rounds:1},
  {id:'arrival', parent:'chapter1', title:'01 · 抵达林间', content:'## 场景目标\n\n夕阳透过林叶，主角走进熟悉的小径。Seraphina 在小屋门前等候。\n\n- 描写光线、脚步与花香\n- 留出一句自然的问候\n- 暂不揭露她等待的原因', status:'done', rounds:1},
  {id:'promise', parent:'chapter1', title:'02 · 未说出口的约定', content:'## 场景目标\n\nSeraphina 带主角走到窗边，提起许久以前的一次约定。\n\n- 从窗外的灯塔引出回忆\n- 用一个细小的动作表达犹豫\n- 在对话结尾留下一个可回应的问题\n\n> 不要替用户决定回应或动作。', status:'running', rounds:2},
  {id:'lighthouse', parent:'chapter1', title:'03 · 远处的灯塔', content:'## 场景目标\n\n沿着森林边缘前往灯塔，让先前的约定逐渐清晰。\n\n- 保持行走过程中的自然对话\n- 增加一处与过去呼应的物件\n- 以灯塔亮起结束这一节', status:'todo', rounds:1},
  {id:'chapter2', parent:null, title:'第二章 · 潮汐来信', content:'海边章节的背景：来信来自一位久未见面的朋友，信封带有潮湿的盐味。', status:'todo', rounds:1},
  {id:'letter', parent:'chapter2', title:'01 · 拆开来信', content:'描写两人在灯塔内拆开信封。通过信中的一段话引出下一次旅程。', status:'todo', rounds:1},
];
const initialMessages = [
  {id:'m1', user:false, text:'夕阳穿过樱花，落在白色手帕的折痕上。她抬起头，笑着走近。', dialogue:'“你来了。沿着这条小径走吧，我有一件事想告诉你。”'},
  {id:'m2', user:true, text:'我跟上她的脚步，望向林间若隐若现的小屋。'},
  {id:'m3', user:false, text:'木窗半掩着，淡淡的茶香从屋里飘出来。Seraphina 停在窗边，指尖轻轻拨开垂落的花枝。', dialogue:'“还记得我们说过，等灯塔重新亮起，就一起去看看海吗？”'},
];
let manualImage=null;
const state = {
  nodes:structuredClone(initialNodes), selected:'promise', collapsed:new Set(), briefs:new Set(['promise']), query:'', outlineOpen:true, settingsExpanded:false, outlineTab:'content', imageTab:'prompt', panel:'outline', left:true, right:true, mode:'novel', deep:null, preview:true,
  enabled:{outline:true,image:true}, insertion:'insert', sendAfterInsert:false, runScope:'from', writing:{phase:'idle', queue:[], index:0, round:0, completed:0, total:0, timer:null, pauseRequested:false},
  messages:structuredClone(initialMessages), rewrite:'根据以下聊天场景，提取可见人物、动作、环境和光线。\n只输出正面提示词与负面提示词，不解释，不包含思考过程。\n{{scene}}', positive:'1girl, elf, silver hair, gentle smile, wooden cottage, cherry blossoms, warm sunset, cinematic lighting', negative:'text, watermark, low quality, extra fingers',
  image:{phase:'idle', target:'m3', before:3, backend:'OpenAI 兼容', profile:'current', format:'tags', automatic:false, every:3, counted:0, delivery:'insert', results:[], selected:null, timer:null, token:0, error:'', simulateFailure:false, configTab:'backend', sourceOpen:false, templateOpen:false, excludeThink:true,excludeSystem:true,excludeMedia:true},
  backendForms:{},
  shortcuts:{outline:'Ctrl+Shift+O',insert:'Ctrl+Shift+I',image:'Ctrl+Shift+G'}, pendingImport:[], importMode:'merge', dialogType:null,
};
const formKeys=new Set(['config-name','config-url','config-model','config-width','config-height','quality','ratio','count','seed','steps','scale','sampler','workflow','max-tokens']);
function formValue(key,value) {return formKeys.has(key)?state.backendForms[state.image.backend]?.[key]??value:value;}
function keepForm(key,value) {if(formKeys.has(key)){state.backendForms[state.image.backend]??={};state.backendForms[state.image.backend][key]=value;}}
const node = () => state.nodes.find(n => n.id === state.selected);
const getNode = id => state.nodes.find(n => n.id === id);
const children = id => state.nodes.filter(n => n.parent === id);
const ancestors = id => { const result = []; let n = getNode(id), seen = new Set(); while(n?.parent && !seen.has(n.parent)) {seen.add(n.parent);n=getNode(n.parent);if(n)result.unshift(n);} return result; };
const descendantIds = id => {const result = new Set([id]); const visit = p => children(p).forEach(n => {result.add(n.id);visit(n.id);});visit(id);return result;};
const ordered = () => {const result = [];const visit = (parent, depth) => children(parent).forEach(n => {result.push({...n,depth});visit(n.id,depth+1);});visit(null,0);return result;};
const leaves = () => ordered().filter(n => !children(n.id).length && n.content.trim());
const statusLabel = value => states.find(([id]) => id === value)?.[1] || '未开始';
let toastTimer;
function toast(message) { $('#toast').textContent=message;$('#toast').classList.add('is-visible');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').classList.remove('is-visible'),2600); }
function hydrateIcons(root=document) {root.querySelectorAll('i[data-icon]').forEach(el=>el.outerHTML=icon(el.dataset.icon,el.className));}
function markdown(text) {
  return text.split('\n').map(line => {const safe=esc(line).replace(/\*\*(.*?)\*\*/g,'<strong>$1</strong>');if(/^#{1,6}\s/.test(line))return `<h3>${safe.replace(/^#{1,6}\s/,'')}</h3>`;if(/^[-*] /.test(line))return `<ul><li>${safe.slice(2)}</li></ul>`;if(line.startsWith('> '))return `<blockquote>${safe.slice(5)}</blockquote>`;return line.trim()?`<p>${safe}</p>`:'';}).join('').replace(/<\/ul><ul>/g,'');
}
function statusOptions(n) {return `<div class="status-options" aria-label="节点状态">${states.map(([id,label])=>`<button data-action="node-status" data-value="${id}" class="${n.status===id?'is-selected':''}" aria-pressed="${n.status===id}"><span class="solid-circle"></span>${label}</button>`).join('')}</div>`;}
function treeMarkup(query=state.query, readOnly=false, inlineDetails=false) {
  const list=ordered(), matching=new Set();
  if(query)for(const n of list)if(`${n.title} ${n.content}`.toLowerCase().includes(query.toLowerCase())){matching.add(n.id);ancestors(n.id).forEach(p=>matching.add(p.id));}
  if(query&&!matching.size)return '<div class="empty">没有匹配节点</div>';
  const visit=(parent,depth)=>children(parent).filter(n=>!query||matching.has(n.id)).map(n=>{
    const branch=children(n.id).length>0,expanded=!!query||!state.collapsed.has(n.id),briefOpen=state.briefs.has(n.id);
    return `<div class="tree-item"><div class="tree-row ${n.id===state.selected?'is-selected':''}" data-node="${n.id}" role="treeitem" aria-selected="${n.id===state.selected}" aria-level="${depth+1}" ${branch?`aria-expanded="${expanded}"`:''} ${readOnly?'':'draggable="true"'} style="padding-left:${7+Math.min(depth,5)*12}px">
      ${!readOnly?`<span class="drag-handle" aria-hidden="true">${icon('drag')}</span>`:''}
      ${branch?`<button class="branch" data-action="branch" data-id="${n.id}" aria-label="${expanded?'收起':'展开'}${esc(n.title)}">${icon('chevron',expanded?'down':'')}</button>`:inlineDetails?`<button class="branch" data-action="node-brief" data-id="${n.id}" aria-label="${briefOpen?'收起':'展开'}${esc(n.title)}的内容" aria-expanded="${briefOpen}">${icon('chevron',briefOpen?'down':'')}</button>`:'<span class="branch"></span>'}
      <button class="node-choice" data-action="choose-node" data-id="${n.id}" title="${esc(n.title)}"><span class="node-status ${n.status}"></span><span class="node-title">${esc(n.title)}</span></button>${n.status==='done'?`<small>${icon('check')}</small>`:''}</div>
      ${branch?`<div class="branch-fold ${expanded?'is-open':''}" data-branch-container="${n.id}" role="group" ${expanded?'':'inert aria-hidden="true"'}><div class="branch-content">${visit(n.id,depth+1)}</div></div>`:inlineDetails?`<div class="branch-fold node-brief ${briefOpen?'is-open':''}" data-brief-container="${n.id}" ${briefOpen?'':'inert'}><div class="branch-content"><div class="node-brief-card"><div class="markdown-preview">${markdown(n.content||'暂无内容')}</div><footer><small>${statusLabel(n.status)} · ${n.rounds} 轮</small><span class="grow"></span>${ib('insert-brief','插入此节点','pencil',`data-id="${n.id}"`)}${ib('edit-brief','在右栏编辑此节点','expand',`data-id="${n.id}"`)}</footer></div></div></div>`:''}</div>`;
  }).join('');
  return visit(null,0);
}
function renderTrees() {
  $('#nav-tree').innerHTML=state.enabled.outline?treeMarkup(state.query,false,true):'<div class="empty">大纲已停用</div>';
  if($('#deep-tree'))$('#deep-tree').innerHTML=treeMarkup();
  const count=leaves(), done=count.filter(n=>n.status==='done').length;
  $('#outline-count').textContent=`${done} / ${count.length}`;
  requestAnimationFrame(()=>scrollBrief(state.selected));
}
function scrollBrief(id) {
  if(!state.left||state.deep||$('#nav-outline').inert)return;
  const container=$('#nav-tree'),card=$(`[data-brief-container="${id}"] .node-brief-card`),row=$(`#nav-tree [data-node="${id}"]`);
  if(!card||!state.briefs.has(id)||ancestors(id).some(n=>state.collapsed.has(n.id)))return;
  const box=container.getBoundingClientRect(),r=card.getBoundingClientRect();
  if(r.bottom>box.bottom-8)container.scrollTop+=row.getBoundingClientRect().top-box.top-5;
}
function syncShell() {
  $('#shell').classList.toggle('left-closed',!state.left);$('#shell').classList.toggle('right-closed',!state.right);$('#shell').classList.toggle('is-rp',state.mode==='rp');
  $('.edge-left').setAttribute('aria-expanded',state.left);$('.edge-left').setAttribute('aria-label',state.left?'收起左侧导航':'展开左侧导航');
  $('.edge-right').setAttribute('aria-expanded',state.right);$('.edge-right').setAttribute('aria-label',state.right?'收起右侧工作区':'展开右侧工作区');
  $('.navigation').inert=!state.left;$('#workarea').inert=!state.right;
  $('#outline-tab').classList.toggle('is-selected',state.panel==='outline');$('#image-tab').classList.toggle('is-selected',state.panel==='image');
  $('#outline-entry').classList.toggle('is-selected',state.right&&state.panel==='outline');
  $('#outline-entry').hidden=!state.enabled.outline;$('#outline-tab').hidden=!state.enabled.outline;document.querySelectorAll('[data-image-entry]').forEach(button=>button.hidden=!state.enabled.image);$('#image-tab').hidden=!state.enabled.image;
  const outlineExpanded=state.enabled.outline&&state.outlineOpen,settingsVisible=!outlineExpanded||state.settingsExpanded;
  $('[data-action="fold-tree"]').setAttribute('aria-expanded',outlineExpanded);$('#nav-outline').classList.toggle('is-open',outlineExpanded);$('#nav-outline').inert=!outlineExpanded;
  $('#nav-settings-actions').hidden=!outlineExpanded;$('#nav-settings').classList.toggle('is-open',settingsVisible);$('#nav-settings').inert=!settingsVisible;$('#nav-settings').setAttribute('aria-hidden',!settingsVisible);
  const settingsToggle=$('[data-action="fold-settings"]');settingsToggle.setAttribute('aria-expanded',settingsVisible);settingsToggle.querySelector('span').textContent=settingsVisible?'收纳设置':'展开设置';
  $('#mode-button').innerHTML=icon(state.mode==='rp'?'theater':'book');$('.reading-heading small').textContent=state.mode==='rp'?'RP':'Noval';
  document.querySelectorAll('#mode-menu button').forEach(b=>b.classList.toggle('is-selected',b.dataset.action===`mode-${state.mode}`));
}
function showPanel(panel) {
  if(!state.enabled[panel]) {toast('请在附加功能设置中启用');return;}
  state.panel=panel;state.right=true;state.deep=null;$('#deep-page').hidden=true;$('#shell').inert=false;
  if(innerWidth<=1100)state.left=false;
  syncShell();renderPanel();
}
function renderPanel() {
  const n=node();
  if(state.panel==='outline') {
    if(!state.enabled.outline){$('#panel-content').innerHTML='<div class="empty">请在附加功能设置中启用大纲。</div>';return;}
    $('#panel-content').innerHTML=`<header class="panel-heading">${icon('tree')}<div><h2>${esc(n?.title||'大纲')}</h2><small>${n?esc(ancestors(n.id).map(p=>p.title).join(' / ')||'当前聊天'):'当前聊天'} · ${n?statusLabel(n.status):'没有节点'}</small></div><span class="grow"></span>${ib('deep-outline','完整大纲编辑','expand')}</header>
      <nav class="panel-tabs" aria-label="大纲工作区视图">${[['content','节点内容'],['writing','写作与进度']].map(([id,label])=>button('outline-tab',label,null,state.outlineTab===id?'is-selected':'',`data-value="${id}"`)).join('')}<span class="grow"></span>${ib('import-export','大纲导入导出','more')}</nav>
      <div class="panel-scroll">${n?(state.outlineTab==='content'?`${statusOptions(n)}<div class="editor-label">Markdown<span class="grow"></span>${button('node-preview','预览','eye','text-button')}</div>${area('node-content',n.content,'class="markdown" aria-label="节点 Markdown 内容"')}<div class="section-heading">写作轮数</div><div class="two-columns">${field('当前节点',input('node-rounds',n.rounds,'type="number" min="1" max="50" aria-label="节点写作轮数"'))}${field('执行方式','<div class="muted-note">首次发送节点指令<br>后续轮次继续写作</div>')}</div><p class="muted-note">父节点提供背景，自动写作只执行有内容的叶节点。</p>`:writingControls()):'<div class="empty">添加一个节点，开始整理大纲。</div>'}</div>
      <footer class="panel-footer"><small>${state.insertion==='insert'?'插入光标处':'覆盖输入框'}${state.sendAfterInsert?' · 自动发送':' · 不发送'}</small>${button('quick-insert',state.sendAfterInsert?'插入并发送':'插入内容','pencil','secondary',n?'':'disabled')}</footer>`;
  } else renderImagePanel();
}
function writingControls() {
  const n=node(), w=state.writing, current=getNode(w.queue[w.index]);
  const progress=w.phase!=='idle'?`<div class="running-card"><div class="running-top"><span class="status-dot active"></span><strong>${{running:'正在写作',pausing:'本轮结束后暂停',paused:'已暂停',done:'已完成'}[w.phase]}</strong><span class="grow"></span><small>${w.completed} / ${w.total} 轮</small></div><p>${esc(current?.title||'本次大纲已写完')}</p><small>当前节点 ${w.round} / ${current?.rounds||0} 轮${w.queue[w.index+1]?` · 下一节 ${esc(getNode(w.queue[w.index+1])?.title)}`:''}</small><div class="progress-track"><div class="progress-fill" style="width:${w.total?w.completed/w.total*100:0}%"></div></div><div class="run-actions">${button(w.phase==='paused'?'resume-writing':'pause-writing',w.phase==='paused'?'继续':'暂停',w.phase==='paused'?'play':'pause','',w.phase==='done'?'disabled':'')}${button('stop-writing','停止','stop')}</div></div>`:'';
  return `${progress}<div class="section-heading">快速插入</div><div class="setting-row"><div>输入处理<small>快速插入与自动写作共用</small></div>${select('insertion',state.insertion,[['insert','插入光标处'],['replace','覆盖输入框']],'aria-label="输入处理方式"')}</div>${check('快速插入后立即发送','send-after',state.sendAfterInsert)}<div class="section-heading spaced">自动写作</div>${field('执行范围',select('run-scope',state.runScope,[['from','从选中节点开始'],['subtree','选中节点及子树']]))}<div class="two-columns">${field('当前节点轮数',input('node-rounds',n.rounds,'type="number" min="1" max="50" aria-label="节点写作轮数"'))}${field('完成后', '<div class="muted-note">标记已完成<br>推进至下一叶节点</div>')}</div><p class="muted-note">跳过已完成节点。暂停等待当前回复结束；停止立即结束任务。手动输入或编辑大纲会暂停任务。</p><div class="button-group spaced">${button('start-writing','开始自动写作','play','primary',['running','pausing'].includes(w.phase)?'disabled':'')}${button('shortcuts','快捷键','keyboard','text-button')}</div>`;
}
function renderMessages(scroll=false) {
  $('#messages').innerHTML=state.messages.map((m,index)=>`<article class="message ${m.user?'is-user':''}" data-message="${m.id}"><header><span>${index+1} 层 · ${m.user?'你的输入':'Seraphina'}</span><span class="grow"></span><small>${m.generated?'写作预览':'示例'}</small>${ib('edit-demo','编辑正文','pencil',`data-id="${m.id}"`)}${ib('manual-image','输入生图提示词','image',`data-image-entry data-id="${m.id}"`)}</header><p>${esc(m.text)}</p>${m.dialogue?`<p class="dialogue">${esc(m.dialogue)}</p>`:''}${m.image?`<figure class="message-media"><img src="${sampleImage}" alt="图片附件示例"><figcaption>正文后的图片附件<span class="grow"></span>${ib('remove-attachment','移除图片附件','trash',`data-id="${m.id}"`)}</figcaption></figure>`:''}</article>`).join('');
  $('#message-count').textContent=state.messages.length;
  if(scroll)$('#messages').scrollTop=$('#messages').scrollHeight;
}
function writeToInput(content, send=state.sendAfterInsert) {
  const draft=$('#draft');if(state.insertion==='replace')draft.value=content;else{const start=draft.selectionStart,end=draft.selectionEnd;draft.value=draft.value.slice(0,start)+content+draft.value.slice(end);draft.selectionStart=draft.selectionEnd=start+content.length;}
  draft.focus();if(send)sendDemo();else toast('已插入示例输入框，尚未发送');
}
function addReply(text) {
  const id=`m${Date.now()}-${state.messages.length}`;state.messages.push({id,user:false,text,dialogue:'“我们慢慢走，还有时间。”',generated:true});renderMessages(true);storyRound(id);return id;
}
function sendDemo() {
  const draft=$('#draft');if(!draft.value.trim()){toast('请先输入内容');return;}
  if(manualImage){state.positive=draft.value;draft.value=manualImage.draft;manualImage=null;$('#manual-image-note').hidden=true;startImage('generate-direct');return;}
  state.messages.push({id:`u${Date.now()}`,user:true,text:draft.value});draft.value='';renderMessages(true);
  setTimeout(()=>{addReply('她稍稍放慢了脚步，等你走到身旁。小径另一端，灯塔在暮色中亮起第一束光。');if(state.panel==='image'&&state.right&&!state.deep)renderPanel();},650);
}
function writingQueue() {
  const selected=node(), list=leaves().filter(n=>n.status!=='done');
  if(!selected)return [];
  if(state.runScope==='subtree'){const ids=descendantIds(selected.id);return list.filter(n=>ids.has(n.id));}
  const order=ordered().map(n=>n.id), index=order.indexOf(selected.id);return list.filter(n=>order.indexOf(n.id)>=index);
}
function startWriting() {
  const queue=writingQueue();if(!queue.length){toast('此范围没有待写的叶节点');return;}
  stopWriting(false);state.writing={phase:'running',queue:queue.map(n=>n.id),index:0,round:0,completed:0,total:queue.reduce((sum,n)=>sum+n.rounds,0),timer:null,pauseRequested:false};
  stepWriting();toast('开始写作预览；收起工作区后仍会继续');
}
function stepWriting() {
  const w=state.writing,n=getNode(w.queue[w.index]);
  if(!n){w.phase='done';refreshTaskUI();return;}
  w.phase='running';n.status='running';
  if(w.round===0){const context=ancestors(n.id).map(p=>p.content).filter(Boolean).join('\n\n');const draft=$('#draft');const instruction=[context,n.content].filter(Boolean).join('\n\n');if(state.insertion==='replace')draft.value=instruction;else draft.value+=instruction;state.messages.push({id:`uw${Date.now()}`,user:true,text:draft.value,generated:true});draft.value='';renderMessages(true);}
  refreshTaskUI();w.timer=setTimeout(()=>{
    w.timer=null;w.round++;w.completed++;
    addReply(`她望向窗外，像是在寻找回忆中的一束光。${n.title.replace(/^\d+\s*·\s*/, '')}的故事，随着暮色缓缓展开。`);
    if(w.round>=n.rounds){n.status='done';w.index++;w.round=0;}
    if(w.index>=w.queue.length){w.phase='done';refreshTaskUI();toast('本次大纲写作预览已完成');return;}
    if(w.pauseRequested){w.phase='paused';w.pauseRequested=false;refreshTaskUI();return;}
    stepWriting();
  },2200);
}
function pauseWriting(reason) {const w=state.writing;if(w.phase==='running'){w.pauseRequested=true;w.phase='pausing';refreshTaskUI();if(reason)toast(reason);} }
function stopWriting(show=true) {clearTimeout(state.writing.timer);state.writing.phase='idle';state.writing.timer=null;state.writing.queue=[];refreshTaskUI();if(show)toast('写作任务已停止，已完成的节点保留');}
function refreshTaskUI() {
  renderTrees();renderBadges();
  if(state.panel==='outline'&&state.outlineTab==='writing'&&state.right&&!state.deep)renderPanel();
  if(state.deep==='outline')updateDeepProgress();
}
function renderBadges() {
  const w=state.writing,i=state.image,html=[];
  if(['running','pausing','paused'].includes(w.phase))html.push(`<div class="task-badge"><span class="status-dot active"></span><span>${w.phase==='paused'?'写作暂停':`写作 ${w.completed}/${w.total}`}</span>${ib(w.phase==='paused'?'resume-writing':'pause-writing',w.phase==='paused'?'继续写作':'暂停写作',w.phase==='paused'?'play':'pause')}${ib('stop-writing','停止写作','stop')}</div>`);
  if(['rewriting','generating'].includes(i.phase))html.push(`<div class="task-badge"><span class="status-dot active"></span><span>${i.phase==='rewriting'?'转写中':'生图中'}</span>${ib('cancel-image','取消生图','stop')}</div>`);
  $('#task-badges').innerHTML=html.join('');
  if($('#deep-task-badges'))$('#deep-task-badges').innerHTML=html.join('');
}
function openDeep(type) {
  state.deep=type;$('#deep-page').hidden=false;$('#shell').inert=true;renderDeep();
}
function renderDeep() {
  if(state.deep==='outline')renderOutlineEditor();else if(state.deep==='image')renderImageConfig();else renderAddonSettings();
  renderBadges();
}
function deepTop(title,glyph,actions='') {return `<header class="deep-top">${ib('close-deep','返回工作台','arrow')}<span class="divider"></span>${icon(glyph)}<h1>${title}</h1><small>林间的约定</small><span class="grow"></span><div id="deep-task-badges"></div>${actions}</header>`;}
function renderOutlineEditor() {
  const n=node();
  $('#deep-page').innerHTML=`${deepTop('大纲编辑','tree',`${button('import-export','导入 / 导出','download')}${ib('shortcuts','大纲快捷键','keyboard')}`)}<div class="deep-layout"><aside class="deep-tree"><label class="search">${icon('search')}<input data-field="tree-search" type="search" value="${esc(state.query)}" placeholder="搜索标题或正文" aria-label="搜索完整大纲"></label><div class="deep-tree-toolbar">${ib('add-node','新建同级节点','plus')}${ib('add-child','新建子节点','indent')}${ib('duplicate-node','复制节点','copy')}${ib('delete-node','删除节点','trash')}<span class="grow"></span>${ib('tree-help','排序与层级帮助','more')}</div><div class="tree" id="deep-tree" role="tree" aria-label="完整大纲树"></div><small class="caption">拖动排序 · Alt + 方向键调整层级</small></aside><div class="deep-main">${n?`<div class="node-meta">${input('node-title',n.title,'aria-label="节点标题"')}${statusOptions(n)}<label class="rounds">轮数${input('node-rounds',n.rounds,'type="number" min="1" max="50" aria-label="节点写作轮数"')}</label></div><div class="editor-columns ${state.preview?'':'preview-hidden'}"><div class="editor-area"><div class="editor-label">Markdown 编辑<span class="grow"></span>${button('toggle-preview',state.preview?'收起预览':'显示预览','eye','text-button')}</div>${area('node-content',n.content,'aria-label="完整页 Markdown 编辑" spellcheck="false"')}</div><section class="preview-area"><div class="editor-label">正文预览<span class="grow"></span><small>随编辑更新</small></div><div class="markdown-preview" id="live-preview">${markdown(n.content)}</div></section></div>`:'<div class="empty">点击左上角添加节点。</div>'}<footer class="deep-bottom">${select('insertion',state.insertion,[['insert','插入光标处'],['replace','覆盖输入框']],'aria-label="完整页输入处理"')}${check('插入后发送','send-after',state.sendAfterInsert)}<small id="deep-progress">${deepProgress()}</small><div class="button-group">${button('quick-insert','插入内容','pencil','secondary',n?'':'disabled')}${button('start-writing','自动写作','play','primary',n&&!['running','pausing'].includes(state.writing.phase)?'':'disabled')}</div></footer></div></div>`;
  renderTrees();
}
function deepProgress() {const w=state.writing;return ['running','pausing','paused'].includes(w.phase)?`${w.phase==='paused'?'已暂停':'运行中'} · ${w.completed} / ${w.total} 轮`:'当前聊天 · 编辑仅在预览会话内保留';}
function updateDeepProgress(){if($('#deep-progress'))$('#deep-progress').textContent=deepProgress();}
function sourceText() {const targetIndex=state.messages.findIndex(m=>m.id===state.image.target);return state.messages.slice(Math.max(0,targetIndex-state.image.before),targetIndex+1).map(m=>`${m.user?'用户':'Seraphina'}：${m.text}${m.dialogue?'\n'+m.dialogue:''}`).join('\n\n');}
function targetOptions() {return state.messages.filter(m=>!m.user).map(m=>[m.id,`${state.messages.indexOf(m)+1} 层 · Seraphina`]);}
function currentResult() {return state.image.results.find(r=>r.id===state.image.selected)||state.image.results.at(-1);}
function fold(action,title,open,content) {return `<section class="fold"><button data-action="${action}" aria-expanded="${open}">${icon('chevron',open?'down':'')}${title}<span class="grow"></span></button><div class="fold-body ${open?'is-open':''}" ${open?'':'inert'}><div>${content}</div></div></section>`;}
function renderImagePanel() {
  const i=state.image,busy=['rewriting','generating'].includes(i.phase),r=currentResult();
  const tabs=[['prompt','提示词'],['results',`图片结果${i.results.length?' · '+i.results.length:''}`],['automatic','自动规则']];
  let content='';
  if(state.imageTab==='prompt') {
    content=`<div class="image-topline">${select('image-target',i.target,targetOptions(),'aria-label="生图目标楼层"')}${button('deep-image','配置','sliders','secondary')}</div>${field('正面提示词',area('positive',state.positive,'aria-label="正面提示词"'),'prompt-block')}${field('负面提示词',area('negative',state.negative,'aria-label="负面提示词"'),'prompt-block negative')}
      <div class="button-group">${button('rewrite','仅转写','text','secondary',busy?'disabled':'')}${button('generate-direct','用此提示词生成','image','secondary',busy?'disabled':'')}</div>
      ${fold('fold-source','场景来源',i.sourceOpen,`${field('包含前文',input('image-before',i.before,'type="number" min="0" max="30" aria-label="包含前文楼层数"'))}${field('提取场景',area('source',sourceText(),'readonly aria-label="提取的示例场景"'))}<p class="muted-note">默认排除思考块、系统消息和图片任务记录。</p>`)}
      ${fold('fold-template','独立转写提示词',i.templateOpen,`${field('转写模板',area('rewrite-template',state.rewrite,'aria-label="独立转写模板"'))}<p class="muted-note">{{scene}} 为目标楼层和所选前文。转写不改变主聊天预设。</p>`)}${busy?`<div class="image-progress"><span class="spinner"></span>${i.phase==='rewriting'?'正在转写并清洗场景…':'正在生成图片…'}<span class="grow"></span>${button('cancel-image','取消','stop','text-button')}</div>`:''}${i.error?`<p class="error-note">${esc(i.error)}</p>${button('generate-direct','重试','refresh','text-button')}`:''}
      ${r?resultMarkup(r,true):'<div class="notice"><strong>从场景到图片</strong>先转写并清洗，确认提示词后生成。结果可插入所选楼层，或拖到正文中的任意楼层。</div>'}`;
  } else if(state.imageTab==='results') {
    content=`<div class="image-topline">${select('image-target',i.target,targetOptions(),'aria-label="图片插入目标楼层"')}<small>${i.results.length} 张 · 当前聊天</small></div>${r?`${resultMarkup(r)}<div class="result-history">${i.results.map(result=>`<button data-action="select-result" data-id="${result.id}" class="${result.id===r.id?'is-selected':''}"><img src="${sampleImage}" alt="图片结果缩略图"><small>${result.number} · ${result.inserted?'已插入':'待选'} · ${result.floor} 层</small></button>`).join('')}</div>`:'<div class="empty">生成的图片会保留在这里。</div>'}<p class="muted-note spaced">拖动图片到指定楼层，可将它附在正文之后。图片不改变聊天文本。</p>`;
  } else {
    content=`<div class="setting-row"><div>按剧情回复自动生图<small>独立转写，不占用剧情回复轮数</small></div>${check('启用','auto-image',i.automatic)}</div><div class="two-columns">${field('每 x 次回复',input('image-every',i.every,'type="number" min="1" max="50" aria-label="自动生图间隔"'))}${field('当前计轮',`<div class="muted-note">${i.counted} / ${i.every}<br>仅成功的剧情回复</div>`)}</div>${field('结果交付',select('image-delivery',i.delivery,[['insert','插入触发楼层'],['workspace','存入右栏待选']],'aria-label="自动图片交付方式"'))}<div class="notice"><strong>关闭工作区后继续</strong>任务状态保留在输入工具栏，可随时停止。续写计轮，重新生成和候选回复切换不重复计轮。</div><p class="muted-note">此页为交互预览。点击正文输入框的发送按钮可模拟一次剧情回复，查看自动生图流程。</p>${button('simulate-round','模拟一轮剧情回复','play','secondary')}`;
  }
  $('#panel-content').innerHTML=`<header class="panel-heading">${icon('image')}<div><h2>场景生图</h2><small>${esc(i.backend)} · ${i.format==='tags'?'标签提示词':'自然语言'}</small></div><span class="grow"></span>${ib('deep-image','完整生图配置','expand')}</header><nav class="panel-tabs" aria-label="生图工作区视图">${tabs.map(([id,label])=>button('image-tab',label,null,state.imageTab===id?'is-selected':'',`data-value="${id}"`)).join('')}</nav><div class="panel-scroll">${content}</div><footer class="panel-footer"><small>${i.automatic?`自动 · ${i.counted}/${i.every} 轮`:'自动生图未开启'}${busy?' · 后台运行':''}</small>${button(busy?'cancel-image':'rewrite-generate',busy?'取消任务':'转写并生成',busy?'stop':'magic','primary')}</footer>`;
}
function resultMarkup(r, compact=false) {
  return `<article class="image-result"><img class="result-image" src="${sampleImage}" alt="场景图片示例，可拖至聊天楼层" draggable="true" data-image="${r.id}"><header><strong>场景 ${r.number}</strong><span class="grow"></span><small>${r.floor} 层 · ${r.inserted?'已插入':'待选'} · 示例素材</small></header><div class="result-actions">${button('insert-image','插入楼层','plus','secondary',`data-id="${r.id}"`)}${button('replace-image','替换已有','refresh','',`data-id="${r.id}"`)}${button('regenerate-image','重新生成','image','',`data-id="${r.id}"`)}${compact?'':ib('delete-image','移除结果','trash',`data-id="${r.id}"`)}</div></article>`;
}
function storyRound(target) {
  const i=state.image;if(!i.automatic||!state.enabled.image)return;i.counted++;
  if(i.counted>=i.every){i.counted=0;if(['rewriting','generating'].includes(i.phase)){toast('已有生图任务运行，本次不重复启动');}else{i.target=target;startImage('rewrite-generate',target);}}
}
function cancelImage(show=true) {const i=state.image;clearTimeout(i.timer);i.timer=null;i.token++;i.phase='idle';renderBadges();if(state.panel==='image'&&state.right&&!state.deep)renderPanel();if(show)toast('生图任务已取消，提示词保留');}
function startImage(action, autoTarget=null) {
  const i=state.image;if(['rewriting','generating'].includes(i.phase))return;
  if(!state.enabled.image)return;if(action==='generate-direct'&&!state.positive.trim()){i.error='请输入有效的正面提示词。';renderPanel();return;}
  const token=++i.token,target=autoTarget||i.target,signature=state.messages.find(m=>m.id===target)?.text;i.error='';
  const generate=()=>{
    i.phase='generating';renderBadges();if(state.panel==='image'&&state.right&&!state.deep)renderPanel();
    i.timer=setTimeout(()=>{
      if(token!==i.token)return;i.timer=null;
      if(i.simulateFailure){i.phase='error';i.error='示例后端连接失败。提示词与目标楼层已保留，可重试。';if(state.panel==='image'&&state.right&&!state.deep)renderPanel();renderBadges();return;}
      i.phase='idle';const result={id:`img${Date.now()}`,number:i.results.length+1,target,floor:state.messages.findIndex(m=>m.id===target)+1,prompt:state.positive,inserted:false};i.results.push(result);i.selected=result.id;
      const valid=state.messages.find(m=>m.id===target)?.text===signature;
      if(autoTarget&&i.delivery==='insert'&&valid)insertImage(result.id,target);
      else toast(valid?'图片预览已生成，可插入或拖到楼层':'目标回复已改变，图片保留在待选区');
      renderBadges();if(state.panel==='image'&&state.right&&!state.deep)renderPanel();
    },1600);
  };
  if(action==='generate-direct'){generate();return;}
  i.phase='rewriting';renderBadges();if(state.panel==='image'&&state.right&&!state.deep)renderPanel();
  i.timer=setTimeout(()=>{
    if(token!==i.token)return;state.positive=i.format==='tags'?'1girl, elf, silver hair, wooden cottage, cherry blossoms, gentle smile, warm sunset, soft lighting, cinematic composition':'A silver-haired elf stands beside a cottage window, cherry blossoms in the warm evening light, a gentle expression and quiet cinematic atmosphere.';state.negative='text, watermark, low quality, malformed hands';
    if(action==='rewrite'){i.phase='idle';i.timer=null;renderBadges();if(state.panel==='image'&&state.right&&!state.deep)renderPanel();toast('转写清洗预览完成，可编辑最终提示词');}else generate();
  },1100);
}
function insertImage(id,target=state.image.target,replace=false) {
  const r=state.image.results.find(r=>r.id===id),m=state.messages.find(m=>m.id===target);if(!r||!m){toast('目标楼层不存在，图片保留在结果区');return;}
  if(m.image&&!replace){toast('此楼层已有图片，请使用“替换已有”');return;}
  m.image=r.id;r.inserted=true;r.floor=state.messages.indexOf(m)+1;renderMessages(true);toast(`图片${replace?'替换':'插入'}至 ${r.floor} 层正文之后`);if(state.panel==='image'&&state.right&&!state.deep)renderPanel();
}
function renderImageConfig() {
  const i=state.image,tab=i.configTab;
  const nav=[['backend','生图后端','image'],['rewrite','转写与清洗','text'],['automatic','自动规则','refresh']];
  let content='';
  if(tab==='backend') {
    const local=['A1111','ComfyUI'].includes(i.backend);
    const dimensions=`${field('宽度',input('config-width',1024,'type="number" min="64" step="64"'))}${field('高度',input('config-height',1024,'type="number" min="64" step="64"'))}`;
    const pairs=i.backend==='OpenAI 兼容'?`${field('模型',input('config-model','gpt-image-1'))}${field('画质',select('quality','auto',[['auto','自动'],['high','高'],['medium','中']]))}${dimensions}`:
      i.backend==='Gemini'?`${field('模型',input('config-model','gemini-2.5-flash-image'))}${field('比例',select('ratio','1:1',[['1:1','1:1'],['16:9','16:9'],['9:16','9:16']]))}${field('输出数量',input('count',1,'type="number" min="1" max="4"'))}${field('种子',input('seed',-1,'type="number"'))}`:
      `${dimensions}${field('采样步数',input('steps',28,'type="number" min="1" max="150"'))}${field('提示词强度',input('scale',7,'type="number" step=".5"'))}${field('种子',input('seed',-1,'type="number"'))}${field('采样器',select('sampler','euler',[['euler','Euler'],['dpm','DPM++ 2M']]))}${field('输出数量',input('count',1,'type="number" min="1" max="4"'))}${field('提示词格式',select('image-format',i.format,[['tags','标签式'],['natural','自然语言']]))}`;
    content=`<div class="backend-cards" aria-label="选择生图后端">${backends.map(name=>`<button data-action="backend" data-value="${name}" class="${i.backend===name?'is-selected':''}" aria-pressed="${i.backend===name}"><span class="solid-circle"></span>${name}</button>`).join('')}</div><div class="config-card"><div class="section-heading">连接</div><div class="four-columns">${field('配置名称',input('config-name',`${i.backend} · 默认`))}${field(local?'服务地址':'API 地址',input('config-url',local?'http://127.0.0.1:7860':'','placeholder="沿用后端默认地址"'),'double')}${field('凭据',input('config-key','','type="password" placeholder="预览不填写凭据" autocomplete="off" disabled'))}</div><p class="muted-note">后端配置属于用户设置，聊天元数据与内容导出不包含密钥。预览页面不会发出网络请求。</p></div><div class="config-card"><div class="section-heading">生成参数</div><div class="four-columns">${pairs}</div></div>${i.backend==='ComfyUI'?`<div class="config-card"><div class="section-heading">API 工作流</div>${field('工作流 JSON',area('workflow','{\n  "6": {\n    "class_type": "CLIPTextEncode",\n    "inputs": { "text": "{{positive}}" }\n  }\n}','spellcheck="false"'))}<p class="muted-note">替换正负提示词、尺寸、种子；保留已有工作流节点结构。</p></div>`:''}`;
  } else if(tab==='rewrite') {
    content=`<div class="config-card"><div class="section-heading">独立模型请求</div><div class="four-columns">${field('转写连接',select('image-profile',i.profile,[['current','当前连接'],['dedicated','指定连接配置']]))}${field('输出格式',select('image-format',i.format,[['tags','标签式'],['natural','自然语言']]))}${field('包含前文楼层',input('image-before',i.before,'type="number" min="0" max="30"'))}${field('最大输出 Token',input('max-tokens',600,'type="number" min="64"'))}</div><p class="muted-note">使用独立请求，保持主聊天连接、预设及提示词不变。</p></div><div class="config-card"><div class="section-heading">转写模板</div>${field('场景 → 生图提示词',area('rewrite-template',state.rewrite,'aria-label="完整页转写模板"'))}<p class="muted-note">{{scene}} 替换为场景原文。输出经过思考块、解释文字、代码围栏和外层包装清洗。</p></div><div class="config-card"><div class="section-heading">清洗与失败演示</div><div class="four-columns">${check('排除思考块','demo-think',i.excludeThink)}${check('排除系统消息','demo-system',i.excludeSystem)}${check('排除图片任务记录','demo-media',i.excludeMedia)}${check('演示生成失败','simulate-failure',i.simulateFailure)}</div><p class="muted-note">模拟失败用于审阅错误与重试布局，不连接真实后端。</p></div>`;
  } else {
    content=`<div class="config-card"><div class="section-heading">按剧情回复触发</div><div class="four-columns">${check('启用自动生图','auto-image',i.automatic)}${field('每 x 次回复',input('image-every',i.every,'type="number" min="1" max="50"'))}${field('结果交付',select('image-delivery',i.delivery,[['insert','插入触发楼层'],['workspace','存入右栏待选']]))}${field('本次计轮',`<div class="muted-note">${i.counted} / ${i.every} 轮</div>`)}</div><p class="muted-note">正常剧情回复和成功续写计轮。转写、重生成、切换候选回复和图片附件变化不重复计轮。</p></div><div class="config-card"><div class="section-heading">任务与目标</div><p class="muted-note">关闭右栏或编辑页，已启动任务继续运行。切换聊天、返回原生或停用插件会停止任务；目标楼层或回复版本已改变时，结果保留在待选区。</p></div>`;
  }
  $('#deep-page').innerHTML=`${deepTop('生图配置','image','<span class="preview-pill">交互预览</span>')}<div class="config-layout"><nav class="config-nav" aria-label="生图配置分组">${nav.map(([id,label,glyph])=>button('config-tab',label,glyph,tab===id?'is-selected':'',`data-value="${id}"`)).join('')}</nav><div class="config-content">${content}</div></div><footer class="deep-bottom"><small>示例配置仅在当前预览会话内保留</small><span class="grow"></span>${button('save-config','完成配置','check','primary')}</footer>`;
}
function renderAddonSettings() {
  $('#deep-page').innerHTML=`${deepTop('工作台附加功能','settings','<span class="preview-pill">按需加载</span>')}<div class="config-content"><div class="section-heading">启用与入口</div><div class="addon-grid">${[['outline','大纲','tree','当前聊天的树状大纲、Markdown 编辑、节点进度与自动写作。'],['image','场景生图','image','独立转写与清洗、手动或按剧情轮数生成、原生图片附件。']].map(([id,name,glyph,description])=>`<section class="addon-card"><header>${icon(glyph)}<h2>${name}</h2></header><p>${description}</p>${check(`启用${name}`,`enable-${id}`,state.enabled[id])}<footer><small>点击入口才加载</small>${button(`pin-${id}`,'固定到工具栏','plus','text-button')}</footer></section>`).join('')}<section class="addon-card"><header>${icon('download')}<h2>记录导出</h2></header><p>现有附加插件：扫描 XML 结构、筛选内容与导出记录。</p><span class="muted-note">沿用当前功能与布局</span><footer><small>本轮不修改</small></footer></section></div><div class="notice"><strong>后台任务与界面分开</strong>关闭工作区只收起界面。运行状态与暂停、停止入口保留在输入工具栏；停用功能会结束对应任务。</div><p class="muted-note">数据库总结与辅助匹配进度后续同数据库插件一起接入，本轮保留接口，不增加空操作入口。</p></div><footer class="deep-bottom"><small>此页为布局演示；不更改酒馆设置</small><span class="grow"></span>${button('save-config','返回工作台','check','primary')}</footer>`;
}
function openDialog(type,content) {state.dialogType=type;$('#dialog-content').innerHTML=content;if(!$('#dialog').open)$('#dialog').showModal();}
function dialogHeading(title,glyph) {return `<header class="dialog-heading">${icon(glyph)}<h2>${title}</h2><span class="grow"></span>${ib('close-dialog','关闭对话框','close')}</header>`;}
function showGuide() {openDialog('guide',`${dialogHeading('大纲与生图 · 交互预览','eye')}<div class="dialog-body"><p class="muted-note">按真实网页视口排版，1496 × 817 CSS 像素为主要检查尺寸。没有固定画布缩放。</p><div class="help-grid spaced">${button('guide-outline','大纲 · 右侧工作区','tree')}${button('guide-editor','大纲 · 完整编辑','pencil')}${button('guide-image','生图 · 右侧工作区','image')}${button('guide-config','生图 · 完整配置','sliders')}</div><ul class="guide-list spaced"><li>选节点、折叠树、拖动排序；完整编辑页实时 Markdown 预览。</li><li>自动写作和生图用计时模拟，关闭右栏后仍可暂停或停止。</li><li>图片用既有设计素材演示；可点击或拖至任意示例楼层。</li><li>所有编辑仅在本页会话内保留。没有模型调用或酒馆数据写入。</li></ul></div><footer class="dialog-footer">${button('close-dialog','开始查看','check','primary')}</footer>`);}
function showShortcuts() {openDialog('shortcuts',`${dialogHeading('自定义快捷键','keyboard')}<div class="dialog-body"><p class="muted-note">点击快捷键框，再按组合键。使用 Ctrl／Alt／Meta 加按键，避开发送与常见浏览器快捷键。</p>${[['outline','打开完整大纲'],['insert','插入当前节点'],['image','打开生图工作区']].map(([id,label])=>`<label class="shortcut-row"><span>${label}</span><input data-shortcut="${id}" value="${esc(state.shortcuts[id])}" readonly aria-label="${label}快捷键">${ib('clear-shortcut','清除'+label+'快捷键','close',`data-id="${id}"`)}</label>`).join('')}<p class="muted-note spaced">树节点：Alt + ↑／↓ 排序，Alt + →／← 调整层级。Escape 关闭弹层。</p><p id="shortcut-error" class="import-error" role="status"></p></div><footer class="dialog-footer">${button('close-dialog','完成','check','primary')}</footer>`);}
function showImportExport() {
  state.pendingImport=[];
  openDialog('import',`${dialogHeading('大纲导入与导出','download')}<div class="dialog-body"><div class="button-group">${button('export-json','导出 JSON','download','secondary')}${button('export-md','导出 Markdown','download','secondary')}<span class="grow"></span><small>JSON 保留状态和轮数</small></div><div class="section-heading spaced">导入预览</div><label class="import-drop">选择 JSON 或 Markdown 文件，也可粘贴内容<input type="file" data-field="import-file" accept=".json,.md,.markdown,.txt" aria-label="选择大纲文件"></label>${field('文件内容',area('import-text','# 第三章 · 海风\n\n新的章节背景。\n\n## 01 · 抵达海边\n\n描写角色在海边等待来信。','aria-label="导入大纲内容"'))}<div class="button-group">${button('preview-import','分析内容','search','secondary')}${select('import-mode',state.importMode,[['merge','合并到当前大纲'],['replace','替换当前大纲']],'aria-label="大纲导入方式"')}</div><div id="import-preview"></div><p id="import-error" class="import-error" role="status"></p></div><footer class="dialog-footer">${button('close-dialog','取消',null)}${button('confirm-import','确认导入','check','primary','disabled')}</footer>`);
}
function parseImport(text) {
  if(text.trim().startsWith('{')||text.trim().startsWith('[')){
    const json=JSON.parse(text),entries=Array.isArray(json)?json:json.nodes;
    if(!Array.isArray(entries)||!entries.length)throw new Error('JSON 需要非空 nodes 数组。');
    if(entries.length>500)throw new Error('预览最多导入 500 个节点。');
    const map=new Map();for(const [index,n]of entries.entries()){if(typeof n.title!=='string'||typeof n.content!=='string')throw new Error('每个节点需要 title 与 content。');if(map.has(n.id))throw new Error('节点 ID 重复。');map.set(n.id,`import-${Date.now()}-${index}`);}
    for(const n of entries){let p=n,seen=new Set([n.id]);while(p.parent!=null){if(!map.has(p.parent)||seen.has(p.parent))throw new Error('父节点缺失或形成循环。');seen.add(p.parent);p=entries.find(entry=>entry.id===p.parent);}}
    return entries.map(n=>({id:map.get(n.id),parent:n.parent==null?null:map.get(n.parent),title:n.title,content:n.content,status:states.some(([id])=>id===n.status)?n.status:'todo',rounds:Math.min(50,Math.max(1,Number(n.rounds)||1))}));
  }
  const result=[],stack=[];let current;
  for(const line of text.split('\n')){const match=line.match(/^(#{1,6})\s+(.+)$/);if(match){const depth=match[1].length;while(stack.length&&stack.at(-1).depth>=depth)stack.pop();current={id:`import-${Date.now()}-${result.length}`,parent:stack.at(-1)?.id||null,title:match[2],content:'',status:'todo',rounds:1};result.push(current);stack.push({id:current.id,depth});}else if(current)current.content+=line+'\n';}
  if(!result.length)throw new Error('Markdown 需要至少一个标题。');if(result.length>500)throw new Error('预览最多导入 500 个节点。');return result.map(n=>({...n,content:n.content.trim()}));
}
function download(kind) {const content=kind==='json'?JSON.stringify({version:1,nodes:state.nodes},null,2):ordered().map(n=>`${'#'.repeat(n.depth+1)} ${n.title}\n\n${n.content}`).join('\n\n');const blob=new Blob([content],{type:kind==='json'?'application/json':'text/markdown'}),a=document.createElement('a'),url=URL.createObjectURL(blob);a.href=url;a.download=`大纲预览.${kind==='json'?'json':'md'}`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function addNode(asChild=false,duplicate=false) {
  pauseWriting('编辑大纲后，自动写作将在本轮结束时暂停');
  const n=node(),id=`n${Date.now()}-${state.nodes.length}`,added={id,parent:asChild?n?.id||null:n?.parent||null,title:duplicate?`${n.title} · 副本`:asChild?'新的场景':'新的节点',content:duplicate?n.content:'',status:'todo',rounds:duplicate?n.rounds:1};
  if(n){let index=state.nodes.findIndex(item=>item.id===n.id);const ids=descendantIds(n.id);while(index+1<state.nodes.length&&ids.has(state.nodes[index+1].id))index++;state.nodes.splice(index+1,0,added);}else state.nodes.push(added);
  if(asChild&&n)state.collapsed.delete(n.id);state.selected=id;renderTrees();state.deep==='outline'?renderDeep():renderPanel();
}
function moveNode(id,target,asChild=false) {
  if(id===target)return;const n=getNode(id),t=getNode(target),ids=descendantIds(id);if(!n||!t||ids.has(target)){toast('不能把节点移入自己的子树');return;}
  pauseWriting('大纲结构发生变化，写作将在本轮结束时暂停');const moved=state.nodes.filter(n=>ids.has(n.id));state.nodes=state.nodes.filter(n=>!ids.has(n.id));n.parent=asChild?t.id:t.parent;
  let index=state.nodes.findIndex(n=>n.id===target);if(asChild)index++;state.nodes.splice(index,0,...moved);state.collapsed.delete(t.id);renderTrees();
}
function adjustNode(key) {
  const n=node();if(!n)return;const siblings=children(n.parent),index=siblings.findIndex(item=>item.id===n.id);
  if(key==='ArrowUp'&&index>0)moveNode(n.id,siblings[index-1].id);
  if(key==='ArrowDown'&&index<siblings.length-1){const next=siblings[index+1],ids=descendantIds(n.id),moved=state.nodes.filter(n=>ids.has(n.id));state.nodes=state.nodes.filter(n=>!ids.has(n.id));const nextIds=descendantIds(next.id);let insert=state.nodes.findIndex(n=>n.id===next.id);while(insert+1<state.nodes.length&&nextIds.has(state.nodes[insert+1].id))insert++;state.nodes.splice(insert+1,0,...moved);pauseWriting();renderTrees();}
  if(key==='ArrowRight'&&index>0)moveNode(n.id,siblings[index-1].id,true);
  if(key==='ArrowLeft'&&n.parent){const parent=getNode(n.parent);n.parent=parent?.parent||null;pauseWriting();renderTrees();}
}
const handlers = {
  'edit-demo':()=>toast('正文编辑沿用酒馆原生控件'),
  'manual-image':el=>{state.image.target=el.dataset.id;manualImage={draft:$('#draft').value};$('#draft').value='';$('#draft').placeholder='输入生图提示词…';$('#draft').focus();$('#manual-image-note').hidden=false;},
  'cancel-manual-image':()=>{if(manualImage)$('#draft').value=manualImage.draft;manualImage=null;$('#manual-image-note').hidden=true;},
  'panel-outline':()=>showPanel('outline'),'panel-image':()=>showPanel('image'),
  'toggle-left':()=>{state.left=!state.left;if(innerWidth<=1100&&state.left)state.right=false;syncShell();},
  'toggle-right':()=>{state.right=!state.right;if(innerWidth<=1100&&state.right)state.left=false;syncShell();},'close-right':()=>{state.right=false;syncShell();},
  'fold-tree':()=>{state.outlineOpen=!state.outlineOpen;state.settingsExpanded=false;syncShell();if(state.outlineOpen)setTimeout(()=>scrollBrief(state.selected),240);},
  'fold-settings':()=>{state.settingsExpanded=!state.settingsExpanded;syncShell();},
  'branch':el=>{const id=el.dataset.id,expanded=state.collapsed.has(id);expanded?state.collapsed.delete(id):state.collapsed.add(id);document.querySelectorAll(`[data-branch-container="${id}"]`).forEach(group=>{group.classList.toggle('is-open',expanded);group.inert=!expanded;group.setAttribute('aria-hidden',!expanded);});document.querySelectorAll(`[data-action="branch"][data-id="${id}"]`).forEach(button=>{button.querySelector('.icon').classList.toggle('down',expanded);button.setAttribute('aria-label',`${expanded?'收起':'展开'}${getNode(id).title}`);button.closest('.tree-row').setAttribute('aria-expanded',expanded);});},
  'node-brief':el=>{const id=el.dataset.id,expanded=!state.briefs.has(id);expanded?state.briefs.add(id):state.briefs.delete(id);const group=$(`[data-brief-container="${id}"]`);group.classList.toggle('is-open',expanded);group.inert=!expanded;el.setAttribute('aria-expanded',expanded);el.querySelector('.icon').classList.toggle('down',expanded);el.setAttribute('aria-label',`${expanded?'收起':'展开'}${getNode(id).title}的内容`);if(expanded)setTimeout(()=>scrollBrief(id),240);},
  'insert-brief':el=>{state.selected=el.dataset.id;handlers['quick-insert']();renderTrees();if(state.panel==='outline'&&state.right)renderPanel();},
  'edit-brief':el=>{state.selected=el.dataset.id;showPanel('outline');state.outlineTab='content';renderTrees();renderPanel();},
  'choose-node':el=>{state.selected=el.dataset.id;renderTrees();if(state.deep==='outline')renderDeep();else if(state.panel==='outline')renderPanel();},
  'node-status':el=>{if(!node())return;node().status=el.dataset.value;pauseWriting();renderTrees();state.deep==='outline'?renderDeep():renderPanel();},
  'outline-tab':el=>{state.outlineTab=el.dataset.value;renderPanel();},'image-tab':el=>{state.imageTab=el.dataset.value;renderPanel();},
  'deep-outline':()=>openDeep('outline'),'deep-image':()=>openDeep('image'),'settings':()=>openDeep('settings'),
  'close-deep':()=>{state.deep=null;$('#deep-page').hidden=true;$('#shell').inert=false;renderPanel();syncShell();},'save-config':()=>handlers['close-deep'](),
  'toggle-preview':()=>{state.preview=!state.preview;const cols=$('.editor-columns');cols.classList.toggle('preview-hidden',!state.preview);cols.querySelector('[data-action="toggle-preview"]').innerHTML=icon('eye')+(state.preview?'收起预览':'显示预览');},
  'quick-insert':()=>{if(!node())return;pauseWriting('手动插入后，自动写作将在本轮结束时暂停');if(state.deep)handlers['close-deep']();writeToInput(node().content);},
  'node-preview':()=>{if(node())openDialog('node-preview',`${dialogHeading(esc(node().title),'book')}<div class="dialog-body markdown-preview">${markdown(node().content)}</div>`);},
  'start-writing':startWriting,'pause-writing':()=>pauseWriting('当前回复完成后暂停'),
  'resume-writing':()=>{state.writing.pauseRequested=false;stepWriting();},'stop-writing':()=>stopWriting(),
  'send-demo':()=>{pauseWriting('用户手动发送，自动写作将在本轮结束时暂停');sendDemo();},
  'simulate-round':()=>{addReply('远处的海风穿过林叶。她望向灯塔，轻声讲起过去的约定。');renderPanel();},
  'rewrite':()=>startImage('rewrite'),'rewrite-generate':()=>startImage('rewrite-generate'),'generate-direct':()=>startImage('generate-direct'),'cancel-image':()=>cancelImage(),
  'insert-image':el=>insertImage(el.dataset.id),'replace-image':el=>insertImage(el.dataset.id,state.image.target,true),
  'regenerate-image':el=>{const r=state.image.results.find(r=>r.id===el.dataset.id);if(r){state.positive=r.prompt;startImage('generate-direct');}},
  'remove-attachment':el=>{const m=state.messages.find(m=>m.id===el.dataset.id);if(m){const r=state.image.results.find(r=>r.id===m.image);if(r)r.inserted=false;delete m.image;renderMessages();if(state.panel==='image'&&state.right&&!state.deep)renderPanel();}},
  'select-result':el=>{state.image.selected=el.dataset.id;renderPanel();},
  'delete-image':el=>{const r=state.image.results.find(r=>r.id===el.dataset.id);if(r?.inserted){toast('先移除楼层附件，再删除结果');return;}state.image.results=state.image.results.filter(r=>r.id!==el.dataset.id);renderPanel();},
  'fold-source':()=>{state.image.sourceOpen=!state.image.sourceOpen;toggleFold('fold-source',state.image.sourceOpen);},
  'fold-template':()=>{state.image.templateOpen=!state.image.templateOpen;toggleFold('fold-template',state.image.templateOpen);},
  'config-tab':el=>{state.image.configTab=el.dataset.value;renderDeep();},'backend':el=>{state.image.backend=el.dataset.value;renderDeep();},
  'add-node':()=>addNode(),'add-child':()=>addNode(true),'duplicate-node':()=>{if(node())addNode(false,true);},
  'delete-node':()=>{const n=node();if(!n)return;openDialog('delete',`${dialogHeading('删除大纲节点','trash')}<div class="dialog-body"><p>删除“${esc(n.title)}”及其 ${descendantIds(n.id).size-1} 个子节点？</p><p class="muted-note spaced">本操作只影响此设计预览。</p></div><footer class="dialog-footer">${button('close-dialog','取消',null)}${button('confirm-delete','删除','trash','primary')}</footer>`);},
  'confirm-delete':()=>{pauseWriting();const n=node(),ids=descendantIds(n.id);state.nodes=state.nodes.filter(n=>!ids.has(n.id));state.selected=state.nodes[0]?.id;$('#dialog').close();renderTrees();state.deep==='outline'?renderDeep():renderPanel();},
  'tree-help':()=>toast('拖到节点前方排序；按住 Shift 拖入节点。Alt + 方向键也可调整。'),
  'shortcuts':showShortcuts,'clear-shortcut':el=>{state.shortcuts[el.dataset.id]='';showShortcuts();},
  'guide':showGuide,'guide-outline':()=>{$('#dialog').close();showPanel('outline');},'guide-editor':()=>{$('#dialog').close();openDeep('outline');},'guide-image':()=>{$('#dialog').close();showPanel('image');},'guide-config':()=>{$('#dialog').close();openDeep('image');},
  'close-dialog':()=>$('#dialog').close(),'import-export':showImportExport,'export-json':()=>download('json'),'export-md':()=>download('md'),
  'preview-import':()=>{try{state.pendingImport=parseImport($('[data-field="import-text"]').value);$('#import-preview').innerHTML=`<div class="notice"><strong>${state.pendingImport.length} 个节点 · 待导入</strong>${state.pendingImport.map(n=>`<div>${esc(n.title)}</div>`).join('')}</div>`;$('#import-error').textContent='';$('[data-action="confirm-import"]').disabled=false;}catch(error){state.pendingImport=[];$('#import-error').textContent=error.message;$('[data-action="confirm-import"]').disabled=true;$('#import-preview').innerHTML='';}},
  'confirm-import':()=>{if(!state.pendingImport.length)return;pauseWriting();state.nodes=state.importMode==='replace'?state.pendingImport:[...state.nodes,...state.pendingImport];state.selected=state.pendingImport[0].id;state.query='';state.collapsed.clear();$('#dialog').close();renderTrees();state.deep==='outline'?renderDeep():renderPanel();toast('大纲已导入预览会话');},
  'mode-menu':()=>{const menu=$('#mode-menu');menu.hidden=!menu.hidden;$('#mode-button').setAttribute('aria-expanded',!menu.hidden);},
  'mode-step':()=>setMode(state.mode==='rp'?'novel':'rp'),'mode-novel':()=>setMode('novel'),'mode-rp':()=>setMode('rp'),
  'pin-outline':()=>toast('大纲已固定到示例工具栏'),'pin-image':()=>toast('生图已固定到示例工具栏'),
};
function toggleFold(action,open){const el=$(`[data-action="${action}"]`);if(!el)return;el.setAttribute('aria-expanded',open);el.querySelector('.icon').classList.toggle('down',open);el.nextElementSibling.classList.toggle('is-open',open);el.nextElementSibling.inert=!open;}
function setMode(mode){state.mode=mode;$('#mode-menu').hidden=true;$('#mode-button').setAttribute('aria-expanded','false');if(mode==='rp'){state.left=false;state.right=false;}syncShell();renderBadges();}
document.addEventListener('click',event=>{const el=event.target.closest('[data-action]');if(el&&!el.disabled){handlers[el.dataset.action]?.(el,event);}else if(!event.target.closest('#mode-menu,#mode-button')){$('#mode-menu').hidden=true;$('#mode-button').setAttribute('aria-expanded','false');}});
document.addEventListener('input',event=>{
  const el=event.target,key=el.dataset.field;
  keepForm(key,el.value);
  if(el.id==='draft')pauseWriting('手动输入后，自动写作将在本轮结束时暂停');
  if(key==='tree-search'){state.query=el.value;document.querySelectorAll('[data-field="tree-search"]').forEach(other=>{if(other!==el)other.value=el.value;});renderTrees();}
  if(key==='node-content'&&node()){node().content=el.value;pauseWriting();renderTrees();if($('#live-preview'))$('#live-preview').innerHTML=markdown(el.value);}
  if(key==='node-title'&&node()){node().title=el.value;pauseWriting();renderTrees();}
  if(key==='node-rounds'&&node()){node().rounds=Math.min(50,Math.max(1,Number(el.value)||1));pauseWriting();}
  if(key==='positive')state.positive=el.value;if(key==='negative')state.negative=el.value;if(key==='rewrite-template')state.rewrite=el.value;
  if(key==='import-text'){state.pendingImport=[];if($('[data-action="confirm-import"]'))$('[data-action="confirm-import"]').disabled=true;}
});
document.addEventListener('change',async event=>{
  const el=event.target,key=el.dataset.field,i=state.image;
  keepForm(key,el.value);
  const values={'insertion':()=>state.insertion=el.value,'send-after':()=>state.sendAfterInsert=el.checked,'run-scope':()=>state.runScope=el.value,'image-target':()=>i.target=el.value,'image-before':()=>i.before=Math.min(30,Math.max(0,Number(el.value)||0)),'image-every':()=>i.every=Math.min(50,Math.max(1,Number(el.value)||3)),'image-delivery':()=>i.delivery=el.value,'image-profile':()=>i.profile=el.value,'image-format':()=>i.format=el.value,'simulate-failure':()=>i.simulateFailure=el.checked,'import-mode':()=>state.importMode=el.value};values[key]?.();
  if(key==='auto-image'){i.automatic=el.checked;i.counted=0;toast(i.automatic?'自动生图已开启，可模拟剧情回复':'自动规则已关闭');}
  if(key==='demo-think')i.excludeThink=el.checked;if(key==='demo-system')i.excludeSystem=el.checked;if(key==='demo-media')i.excludeMedia=el.checked;
  if(key?.startsWith('enable-')){const id=key.slice(7);state.enabled[id]=el.checked;if(!el.checked){id==='outline'?stopWriting(false):cancelImage(false);if(id==='image')i.automatic=false;}syncShell();renderTrees();}
  if(key==='import-file'&&el.files[0]){if(el.files[0].size>2*1024*1024){$('#import-error').textContent='预览文件请小于 2 MB。';return;}$('[data-field="import-text"]').value=await el.files[0].text();handlers['preview-import']();}
  if(['insertion','send-after'].includes(key)&&!state.deep)renderPanel();
});
function combo(event){const parts=[];if(event.ctrlKey)parts.push('Ctrl');if(event.metaKey)parts.push('Meta');if(event.altKey)parts.push('Alt');if(event.shiftKey)parts.push('Shift');if(!['Control','Meta','Alt','Shift'].includes(event.key))parts.push(event.key.length===1?event.key.toUpperCase():event.key);return parts.join('+');}
document.addEventListener('keydown',event=>{
  if(event.target.dataset.shortcut){event.preventDefault();if(['Control','Meta','Alt','Shift'].includes(event.key))return;const value=combo(event),id=event.target.dataset.shortcut,reserved=new Set(['Ctrl+R','Meta+R','Ctrl+L','Meta+L','Ctrl+T','Meta+T','Ctrl+W','Meta+W','Ctrl+N','Meta+N','Ctrl+Enter','Meta+Enter','Alt+ArrowLeft','Alt+ArrowRight']);if(!(event.ctrlKey||event.altKey||event.metaKey)||reserved.has(value)||Object.entries(state.shortcuts).some(([other,binding])=>other!==id&&binding===value)){$('#shortcut-error').textContent='此组合与常用操作冲突，请换一个。';return;}state.shortcuts[id]=value;event.target.value=value;$('#shortcut-error').textContent='已更新此预览会话的快捷键';return;}
  if(event.key==='Escape'){$('#mode-menu').hidden=true;if(!$('#dialog').open&&state.deep)handlers['close-deep']();return;}
  if($('#dialog').open)return;
  const value=combo(event),binding=Object.entries(state.shortcuts).find(([,key])=>key===value);
  if(binding){event.preventDefault();if(binding[0]==='outline'&&state.enabled.outline)openDeep('outline');if(binding[0]==='image')showPanel('image');if(binding[0]==='insert'&&state.enabled.outline)handlers['quick-insert']();return;}
  if(event.altKey&&event.target.closest('.tree')&&event.key.startsWith('Arrow')){event.preventDefault();adjustNode(event.key);}
});
let draggedNode=null;
document.addEventListener('dragstart',event=>{const image=event.target.closest('[data-image]');if(image){event.dataTransfer.setData('application/x-workbench-preview-image',image.dataset.image);event.dataTransfer.effectAllowed='copy';return;}const row=event.target.closest('.tree-row');if(row){draggedNode=row.dataset.node;event.dataTransfer.setData('application/x-workbench-preview-node',draggedNode);event.dataTransfer.effectAllowed='move';row.classList.add('is-dragging');}});
document.addEventListener('dragover',event=>{const types=[...event.dataTransfer.types],row=event.target.closest('.tree-row'),message=event.target.closest('[data-message]');if(types.includes('application/x-workbench-preview-node')&&row){event.preventDefault();row.classList.add('is-target');}if(types.includes('application/x-workbench-preview-image')&&message){event.preventDefault();message.classList.add('drop-target');event.dataTransfer.dropEffect='copy';}});
document.addEventListener('dragleave',event=>{event.target.closest('.tree-row')?.classList.remove('is-target');event.target.closest('[data-message]')?.classList.remove('drop-target');});
document.addEventListener('drop',event=>{const row=event.target.closest('.tree-row'),message=event.target.closest('[data-message]'),image=event.dataTransfer.getData('application/x-workbench-preview-image');if(image&&message){event.preventDefault();insertImage(image,message.dataset.message);message.classList.remove('drop-target');}if(draggedNode&&row){event.preventDefault();moveNode(draggedNode,row.dataset.node,event.shiftKey);}draggedNode=null;document.querySelectorAll('.is-target,.is-dragging,.drop-target').forEach(el=>el.classList.remove('is-target','is-dragging','drop-target'));});
document.addEventListener('dragend',()=>{draggedNode=null;document.querySelectorAll('.is-target,.is-dragging,.drop-target').forEach(el=>el.classList.remove('is-target','is-dragging','drop-target'));});
$('#dialog').addEventListener('click',event=>{if(event.target===$('#dialog')){const r=$('#dialog').getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)$('#dialog').close();}});
hydrateIcons();renderTrees();renderMessages();renderPanel();syncShell();
const params=new URLSearchParams(location.search);if(params.get('panel')==='image')showPanel('image');if(params.get('view')==='outline')openDeep('outline');if(params.get('view')==='image')openDeep('image');if(params.get('view')==='settings')openDeep('settings');if(params.get('mode')==='rp')setMode('rp');
