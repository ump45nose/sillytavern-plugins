import React, { useLayoutEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowDown, ArrowLeft, ArrowUp, ChevronLeft, Images, BookMarked, BookOpen, Check, ChevronDown,
  ChevronRight, Copy, Download, Ellipsis, Expand, Flag, Image, ImagePlus,
  Lightbulb, List, Moon, PanelLeftClose, PencilLine, Plus, Search, Send,
  Settings2, ShieldCheck, Smartphone, Star, Sun, Trash2, Users, X,
  Languages, Volume2, FileText, EyeOff, Eye, Paperclip, Bookmark, GitBranch, CopyPlus,
} from "lucide-react";

type View = "pwa" | "history" | "character" | "plan";
type Message = { id: number; user?: boolean; text: string; hidden?: boolean };
const paragraphs = [
  "雨停的时候，林晚刚刚合上那本航海日志。她没有抬头，只把一枚黄铜钥匙放在桌上，轻轻推到你面前。",
  "「父亲留下的东西，都在灯塔最上面。」她说。窗外传来最后一声汽笛，远处的海面正在慢慢变成铅灰色。",
  "你拿起钥匙。金属还带着她掌心的温度，齿缝里嵌着一点盐。很久以前，也有人在这样一个黄昏，走上那段锈蚀的旋梯。",
  "书页被风掀起，停在一个潦草的日期上。你认得那个日子。那是所有船只都没有返航的夜晚。",
];
const initial: Message[] = [
  { id: 17, text: paragraphs.join("\n\n") },
  { id: 18, user: true, text: "我拿起钥匙，问她愿不愿意一起去灯塔。" },
  { id: 19, text: "林晚终于抬起头来。\n\n「走吧。」她披上外衣，推开那扇已经很久没有打开的门。雨后的石板路上，映着一盏迟迟没有熄灭的灯。" },
];
const longHistory = [
  { id: 7, text: "你回到旧书店时，门上的铜铃响了两次。林晚站在高高的书架旁，手里握着一封尚未拆开的信。" },
  { id: 8, user: true, text: "我问她，信是谁寄来的。" },
  { id: 9, text: [...paragraphs, ...paragraphs, ...paragraphs].join("\n\n") },
  { id: 10, user: true, text: "我把钥匙收好，决定先去港口。" },
  { id: 11, text: "海面上没有船。雾里的汽笛却越来越近，像一封迟到了二十年的回信。" },
];
const names = ["林晚", "沈舟", "旧书店", "港口往事"];

function App() {
  const [view, setView] = useState<View>(() => {
    const v = new URLSearchParams(location.search).get("view");
    return ["history", "character", "plan"].includes(v || "") ? v as View : "pwa";
  });
  const [dark, setDark] = useState(false), [notice, setNotice] = useState("");
  const toastTimer = useRef<ReturnType<typeof setTimeout>>();
  const notify = (message: string) => {
    setNotice(message);
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setNotice(""), 3200);
  };
  const navigate = (next: View) => {
    setView(next);
    const url = new URL(location.href);
    url.searchParams.set("view", next);
    history.replaceState(null, "", url);
  };
  return <div className="review" data-theme={dark ? "dark" : "light"}>
    <header className="review-head">
      <div className="brand"><span className="brand-mark"><BookOpen size={22}/></span><div><span className="overline">NOVEL WORKBENCH</span><h1>消息编辑与角色卡</h1></div></div>
      <div className="review-head-actions"><span className="proposal-tag"><span></span>设计修订 · 03</span><button className="icon" aria-label={dark ? "切换浅色" : "切换深色"} onClick={() => setDark(!dark)}>{dark ? <Sun size={19}/> : <Moon size={19}/>}</button><a className="quiet-button previous-link" href="revision-02.html?view=pwa">上一版</a><button className="quiet-button plan-shortcut" onClick={() => navigate("plan")}>查看方案<ChevronRight size={15}/></button></div>
    </header>
    <nav className="review-nav" aria-label="设计稿场景">
      {([ ["pwa", Smartphone, "PWA 消息"], ["history", List, "历史消息"], ["character", Users, "角色侧栏"], ["plan", ShieldCheck, "修复方案"] ] as const).map(([id, Icon, label]) => <button key={id} aria-current={view === id ? "page" : undefined} onClick={() => navigate(id)}><Icon size={17}/><span>{label}</span></button>)}
      <span className="nav-caption">楼层信息与操作 · 等高对齐</span>
    </nav>
    <main>
      {view === "pwa" && <section className="review-layout" data-screen-label="01 PWA 消息编辑">
        <div className="device-stage"><div className="frame-caption"><span>01 / PWA · NOVEL</span><span>可点击体验</span></div><Reader phone notify={notify}/></div>
        <aside className="design-notes"><span className="overline">第三版 / 只露出六项常用操作</span><h2>一行图标，<br/>够用就好。</h2><p className="intro">生图、复制、插图、附件、删除、编辑使用与楼层信息等高的轻量图标；桌面端与「林晚 · 第 9 层」同行居中对齐。其余操作由省略号打开。</p>
          <Note number="01" title="每条 AI 消息常显铅笔">图标视觉高度 12 px，与楼层信息同级；桌面端头部保持紧凑，触屏保留 44 px 点击区域。</Note>
          <Note number="03" title="打开原位编辑，光标从开头开始">编辑后保留当前消息的位置。长文本在编辑框内滚动，正文不被拉到末尾。</Note>
          <Note number="04 / 05" title="次要操作进入二级菜单">翻译、朗读、提示词、候选、分支与检查点等收进更多；编辑时的复制副本、上下移动与思考块同样收纳。</Note>
          <div className="try-callout"><PencilLine size={18}/><div><strong>点省略号查看二级菜单</strong><span>图标保留悬停提示与辅助名称；删除前确认，手机触区仍保留足够空间。</span></div></div>
        </aside>
      </section>}
      {view === "history" && <section className="history-review" data-screen-label="02 历史消息原位编辑">
        <div className="section-heading"><div><span className="overline">02 / DESKTOP · NOVEL</span><h2>回到历史，也留在当前楼层。</h2></div><p>试着编辑第 9 层的长消息，再保存或取消。</p></div>
        <div className="desktop-frame"><header className="desktop-top"><BookOpen size={21}/><strong>灯塔来信</strong><span>Novel</span><div className="desktop-top-end"><Search size={17}/><Settings2 size={17}/><Ellipsis size={19}/></div></header><div className="desktop-body"><aside className="floor-nav"><div className="floor-nav-title">当前对话<span>11 层</span></div><div className="chat-name"><span>灯塔来信</span><small>今天 · 与林晚的对话</small></div><label>楼层导航</label>{longHistory.map(m => <button key={m.id} onClick={() => document.querySelector(`[data-history-floor="${m.id}"]`)?.scrollIntoView({ block: "start", behavior: "smooth" })}><span>{String(m.id).padStart(2, "0")}</span><div>{m.user ? "你的输入" : "林晚"}<small>{m.text.slice(0, 17)}…</small></div><ChevronRight size={14}/></button>)}<div className="floor-nav-bottom"><BookMarked size={16}/>大纲与记录<ChevronRight size={14}/></div></aside><Reader historyMode notify={notify}/></div></div>
        <div className="history-rules"><div><span>进入</span><strong>记录消息锚点</strong><p>以当前楼层位置为准，打开时不滚到消息末尾。</p></div><div><span>编辑</span><strong>长文本内部滚动</strong><p>工具栏固定可见，光标从开头开始。</p></div><div><span>退出</span><strong>回到原阅读位置</strong><p>保存或取消后继续阅读同一层。</p></div></div>
      </section>}
      {view === "character" && <section className="character-review" data-screen-label="03 角色侧栏">
        <div className="section-heading"><div><span className="overline">03 / CHARACTER PANEL</span><h2>上半身清晰，下半身渐隐。</h2></div><p>人物自然融入侧栏，虚化的下半身延续为背景。</p></div>
        <div className="character-layout"><CharacterPanel notify={notify}/><aside className="design-notes character-notes"><span className="overline">问题 02 / 角色卡样式</span><h3>人物在前，氛围在后。</h3><p className="intro">上半身作为侧栏的视觉主体。腰部以下逐渐虚化、淡出，让同一张角色卡自然延续到信息区。</p><Note number="主体" title="只保留清晰的上半身">头部与上半身居中展示，保持人物比例。收藏与展开按钮放在右上，不遮住面部。</Note><Note number="层次" title="名称与标签放在图片之外">长名称自然换行；标签可折行；描述、性格、场景和首条消息继续使用原有页签。</Note><Note number="过渡" title="下半身虚化，渐融入纸面">腰部以下柔和渐隐，同图的下半身虚化后延续到名称与描述背后。背景低对比，文字保持清楚。</Note><div className="try-callout"><Image size={18}/><div><strong>需要全图时，点右上角展开</strong><span>侧栏默认展示上半身，原图仍可完整查看。</span></div></div></aside></div>
      </section>}
      {view === "plan" && <Plan onView={navigate}/>}
    </main>
    <footer className="review-footer"><span>2026.10.28 · 第三版设计预览</span><span>本页操作为演示，修订版尚未接入酒馆</span></footer>
    {notice && <div className="toast" role="status"><Check size={17}/>{notice}</div>}
  </div>;
}

function Note({number, title, children}: {number: string; title: string; children: React.ReactNode}) {
  return <div className="note"><span className="note-number">{number}</span><div><h3>{title}</h3><p>{children}</p></div></div>;
}

function Reader({phone = false, historyMode = false, notify}: {phone?: boolean; historyMode?: boolean; notify: (s: string) => void}) {
  const [messages, setMessages] = useState<Message[]>(historyMode ? longHistory : initial);
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState(""), [more, setMore] = useState<number | null>(null);
  const [composer, setComposer] = useState(""), [folds, setFolds] = useState(new Set<number>());
  const [source, setSource] = useState<string | null>(null), [deleting, setDeleting] = useState<number | null>(null);
  const [inspection, setInspection] = useState<{title: string; text: string; messageId?: number} | null>(null);
  const [candidate, setCandidate] = useState<Record<number, number>>({});
  const scroll = useRef<HTMLDivElement>(null), field = useRef<HTMLTextAreaElement>(null);
  const attachment = useRef<HTMLInputElement>(null), reader = useRef<HTMLDivElement>(null);
  const menu = useRef<HTMLDivElement>(null), menuTrigger = useRef<HTMLButtonElement | null>(null);
  const [menuPosition, setMenuPosition] = useState({top: 0, right: 8, maxHeight: 400});
  const firstFloor = historyMode ? 7 : 17;
  const floorOf = (id: number) => messages.findIndex(m => m.id === id) + firstFloor;
  const anchor = useRef<{ id: number; top: number; left: number; focus: boolean } | null>(null);
  const changeAt = (id: number, change: () => void, nextId = id, focus = true) => {
    const target = scroll.current?.querySelector<HTMLElement>(`[data-floor="${id}"]`);
    if (target && scroll.current) anchor.current = { id: nextId, top: target.getBoundingClientRect().top, left: scroll.current.scrollLeft, focus };
    change();
  };
  useLayoutEffect(() => {
    const saved = anchor.current, box = scroll.current;
    if (!saved || !box) return;
    if (saved.focus && editing !== null && field.current) {
      field.current.focus({ preventScroll: true });
      field.current.setSelectionRange(0, 0);
      field.current.scrollTop = 0;
    }
    const target = box.querySelector<HTMLElement>(`[data-floor="${saved.id}"]`);
    if (target) box.scrollTop += target.getBoundingClientRect().top - saved.top;
    box.scrollLeft = saved.left;
    anchor.current = null;
  }, [editing, messages]);
  const start = (message: Message) => {
    if (editing !== null && draft !== messages.find(m => m.id === editing)?.text && !confirm("放弃这条消息的未保存修改？")) return;
    setDraft(message.text);
    setMore(null);
    changeAt(message.id, () => setEditing(message.id));
  };
  const finish = (message: Message, save: boolean) => {
    changeAt(message.id, () => {
      if (save) setMessages(list => list.map(m => m.id === message.id ? {...m, text: draft} : m));
      setEditing(null);
      setMore(null);
      notify(save ? `第 ${floorOf(message.id)} 层已在设计稿中保存` : "已取消修改，保留原消息");
    });
  };
  const copy = async (text: string) => {
    try { await navigator.clipboard.writeText(text); notify("已复制消息"); }
    catch { setSource(text); }
    setMore(null);
  };
  const duplicate = (message: Message) => {
    const id = Math.max(...messages.map(m => m.id), firstFloor) + 1;
    const duplicate = {...message, id, text: draft};
    changeAt(message.id, () => {
      const next = [...messages];
      next.splice(messages.indexOf(message) + 1, 0, duplicate);
      setMessages(next); setEditing(id); setMore(null);
      notify("已在下一层创建副本，原消息保留（演示）");
    }, id);
  };
  const move = (message: Message, direction: number) => {
    const index = messages.indexOf(message), target = index + direction;
    if (target < 0 || target >= messages.length) return;
    changeAt(message.id, () => {
      const next = [...messages];
      [next[index], next[target]] = [next[target], next[index]];
      setMessages(next); setMore(null);
      notify(direction < 0 ? "消息已上移一层（演示）" : "消息已下移一层（演示）");
    });
  };
  const remove = () => {
    if (deleting === null) return;
    const index = messages.findIndex(m => m.id === deleting);
    const neighbor = messages[index + 1] || messages[index - 1];
    changeAt(deleting, () => {
      setMessages(list => list.filter(m => m.id !== deleting));
      if (editing === deleting) setEditing(null);
      setDeleting(null); setMore(null); notify("已删除这条示例消息");
    }, neighbor?.id, false);
  };
  const tool = (label: string, Icon: React.ElementType, onClick: () => void, options: {danger?: boolean; accent?: boolean} = {}) =>
    <button type="button" className={`message-icon ${options.danger ? "danger" : ""} ${options.accent ? "edit-entry" : ""}`} aria-label={label} title={label} onClick={onClick}><Icon size={18}/></button>;
  const closeMenu = (restoreFocus = false) => {
    setMore(null);
    if (restoreFocus) menuTrigger.current?.focus({preventScroll: true});
  };
  const toggleMore = (id: number, e: React.MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation();
    if (more === id) { closeMenu(); return; }
    menuTrigger.current = e.currentTarget;
    const root = reader.current!.getBoundingClientRect(), trigger = e.currentTarget.getBoundingClientRect();
    const height = Math.min(editing === id ? 190 : 366, root.height - 16);
    const top = Math.max(8, Math.min(trigger.bottom - root.top + 5, root.height - height - 8));
    setMenuPosition({top, right: Math.max(8, root.right - trigger.right), maxHeight: root.height - top - 8});
    setMore(id);
  };
  useLayoutEffect(() => {
    if (more !== null) menu.current?.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus({preventScroll: true});
  }, [more]);
  const menuItem = (label: string, Icon: React.ElementType, action: () => void, disabled = false) =>
    <button role="menuitem" disabled={disabled} onClick={() => {closeMenu();action();}}><Icon size={16}/>{label}</button>;
  const currentMenuMessage = messages.find(m => m.id === more);
  return <div ref={reader} className={`${phone ? "phone" : "reader-desktop"}`}>
    {phone && <><header className="phone-top"><button className="icon" aria-label="查看对话信息" onClick={() => notify("灯塔来信 · 与林晚的对话")}><List size={21}/></button><div><strong>灯塔来信</strong><small>林晚 <span>· Novel</span></small></div><button className="icon" aria-label="查看角色设计" onClick={() => { location.search = "?view=character"; }}><img src="assets/character.webp" alt="林晚"/></button></header><div className="quick-config"><span><span className="online-dot"></span>已连接</span><span>创作预设<ChevronDown size={12}/></span><span><BookMarked size={13}/>灯塔纪事</span></div></>}
    <div className="reader-scroll" ref={scroll} onScroll={() => more !== null && closeMenu()} onClick={() => more !== null && closeMenu()}>
      {!phone && <div className="reading-chapter"><span>第二章</span><h3>没有返航的夜晚</h3><p>10 月 27 日 · 旧书店</p></div>}
      {messages.map((message, index) => <article key={message.id} className={`message ${message.user ? "is-user" : ""} ${message.hidden ? "is-excluded" : ""} ${editing === message.id ? "is-editing" : ""}`} data-floor={message.id} data-history-floor={historyMode ? message.id : undefined}>
        <header className="message-header"><div className="message-meta"><span>{message.user ? "你的输入" : "林晚"}</span><span className="meta-dot">·</span><span>第 {index + firstFloor} 层</span>{message.hidden && <span className="excluded-label">已排除</span>}</div>{editing !== message.id && <div className="message-primary-actions" role="group" aria-label={`第 ${index + firstFloor} 层常用操作`}>
          {tool("为此回复生图", ImagePlus, () => notify("生图入口演示：将使用当前生图配置"))}
          {tool("复制消息", Copy, () => copy(message.text))}
          {tool("在此回复后插入图片", Image, () => notify("插图入口演示：在此回复后插入图片"))}
          {tool("附加文件或图片", Paperclip, () => attachment.current?.click())}
          {tool("删除消息", Trash2, () => setDeleting(message.id), {danger: true})}
          {tool(`编辑第 ${index + firstFloor} 层`, PencilLine, () => start(message), {accent: true})}
          <button className="message-icon" aria-label={`第 ${index + firstFloor} 层更多操作`} title="更多操作" aria-haspopup="menu" aria-expanded={more === message.id} onClick={e => toggleMore(message.id, e)}><Ellipsis size={19}/></button>
        </div>}</header>
        {editing === message.id ? <div className="message-editor">
          <div className="edit-toolbar"><span className="editing-caption"><PencilLine size={13}/>编辑中</span>
            {tool("删除消息", Trash2, () => setDeleting(message.id), {danger: true})}
            <button className="message-icon" aria-label="更多编辑操作" title="更多编辑操作" aria-haspopup="menu" aria-expanded={more === message.id} onClick={e => toggleMore(message.id, e)}><Ellipsis size={19}/></button>
            <span className="toolbar-divider" aria-hidden="true"></span>
            <button className="message-icon cancel-edit" aria-label="取消编辑" title="取消编辑 · Esc" onClick={() => finish(message, false)}><X size={19}/></button>
            <button className="message-icon save-edit" aria-label="保存编辑" title="保存编辑 · Ctrl / ⌘ + Enter" onClick={() => finish(message, true)}><Check size={20}/></button>
          </div>
          <textarea ref={field} className="message-field" aria-label={`编辑第 ${index + firstFloor} 层原文`} value={draft} onChange={e => setDraft(e.target.value)} onKeyDown={e => { if (e.key === "Escape") finish(message, false); if ((e.ctrlKey || e.metaKey) && e.key === "Enter") finish(message, true); }}/>
          <div className="edit-bottom"><span>Markdown 原文</span><span>{draft.length} 字</span></div>
        </div> : <>
          {message.user ? <div className="user-line"><button className="fold-button" aria-expanded={folds.has(message.id)} onClick={() => setFolds(old => { const next = new Set(old); next.has(message.id) ? next.delete(message.id) : next.add(message.id); return next; })}><ChevronRight size={14} className={folds.has(message.id) ? "rotate" : ""}/><span>{folds.has(message.id) ? "收起原文" : message.text}</span></button>{folds.has(message.id) && <div className="message-text"><p>{message.text}</p></div>}</div> : <div className="message-text">{(candidate[message.id] && candidate[message.id] !== 1 ? ["林晚望向窗外，海雾正沿着石阶涌上来。", "「等天亮再走，也许就来不及了。」她把钥匙握紧了一些。"] : message.text.split("\n\n")).map((text, i) => <p key={i}>{text || "\u00a0"}</p>)}</div>}

        </>}
      </article>)}
      <div className="reading-end"><span></span>继续书写<span></span></div>
    </div>
    <div className="composer"><div className="composer-input"><button className="icon" aria-label="输入工具说明" onClick={() => notify("沿用原有输入工具，本次只修订消息编辑")}><Plus size={20}/></button><textarea aria-label="输入草稿" placeholder="写下你的回应…" value={composer} onChange={e => setComposer(e.target.value)}/><button className="send-button" aria-label="发送示例消息" disabled={!composer.trim()} onClick={() => {setMessages(list => [...list, {id: Math.max(...list.map(m => m.id), firstFloor) + 1, user: true, text: composer}]);setComposer("");notify("示例消息已加入设计稿");}}><ArrowUp size={19}/></button></div>{!phone && <span className="composer-hint">Enter 发送 · Shift + Enter 换行</span>}</div>
    {currentMenuMessage && <><button className="reader-menu-dismiss" aria-label="关闭更多操作" onClick={() => closeMenu(true)}></button><div ref={menu} className="action-menu reader-action-menu" style={menuPosition} role="menu" aria-label={editing === more ? "更多编辑操作" : "更多消息操作"} onKeyDown={e => {
      if (e.key === "Escape") {e.preventDefault();e.stopPropagation();closeMenu(true);return;}
      if (e.key === "Tab") {closeMenu();return;}
      if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) return;
      e.preventDefault();
      const buttons = [...menu.current!.querySelectorAll<HTMLButtonElement>("button:not(:disabled)")];
      const at = buttons.indexOf(document.activeElement as HTMLButtonElement);
      const next = e.key === "Home" ? 0 : e.key === "End" ? buttons.length - 1 : (at + (e.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length;
      buttons[next]?.focus({preventScroll: true});
    }}>
      {editing === more ? <>
        {menuItem("复制消息副本", CopyPlus, () => duplicate(currentMenuMessage))}
        {menuItem("上移消息", ArrowUp, () => move(currentMenuMessage, -1), messages.indexOf(currentMenuMessage) === 0)}
        {menuItem("下移消息", ArrowDown, () => move(currentMenuMessage, 1), messages.indexOf(currentMenuMessage) === messages.length - 1)}
        {menuItem("添加思考块", Lightbulb, () => {setDraft(value => `<think>\n\n</think>\n\n${value}`);field.current?.focus({preventScroll: true});notify("已在原文中加入思考块（演示）");})}
      </> : <>
        {menuItem("翻译消息", Languages, () => notify("翻译入口演示：将调用当前翻译服务"))}
        {menuItem("朗读消息", Volume2, () => notify("朗读入口演示：将使用当前语音配置"))}
        {menuItem("查看提示词", FileText, () => setInspection({title: "查看提示词", text: "演示内容：此处展示当前消息生成时的提示词记录。正式实现沿用酒馆的提示词查看器。"}))}
        {menuItem(currentMenuMessage.hidden ? "将此消息加入提示词" : "从提示词中排除此消息", currentMenuMessage.hidden ? Eye : EyeOff, () => {setMessages(list => list.map(m => m.id === more ? {...m, hidden: !m.hidden} : m));notify(currentMenuMessage.hidden ? "已加入示例上下文" : "已从示例上下文排除，消息仍然保留");})}
        {menuItem("候选历史", Bookmark, () => setInspection({title: "候选历史", text: "在此查看和切换当前消息的候选回复（演示）。", messageId: currentMenuMessage.id}))}
        {menuItem("创建分支", GitBranch, () => notify("分支入口演示：从当前楼层创建新对话"))}
        {menuItem("切换媒体展示方式", Images, () => setInspection({title: "消息媒体", text: "这条示例消息尚无图片或视频。正式实现可切换媒体列表与画廊。"}))}
        {menuItem("创建检查点", Flag, () => notify("检查点入口演示：以当前消息创建检查点"))}
      </>}
    </div></>}
    <input ref={attachment} className="hidden-file-input" type="file" aria-label="选择示例附件" onChange={e => {if (e.target.files?.length) notify("已选择「" + e.target.files[0].name + "」（仅演示，未上传）");e.target.value = "";}}/>
    {source !== null && <div className="source-backdrop"><div className="source-dialog" role="dialog" aria-modal="true" aria-label="复制原文"><header><strong>复制原文</strong><button className="icon" aria-label="关闭复制原文" onClick={() => setSource(null)}><X size={19}/></button></header><p>当前浏览器无法直接复制。长按或选中下方原文复制。</p><textarea readOnly aria-label="可选择复制的原文" value={source} onFocus={e => e.currentTarget.select()}/></div></div>}
    {inspection && <div className="source-backdrop"><div className="source-dialog" role="dialog" aria-modal="true" aria-label={inspection.title}><header><strong>{inspection.title}</strong><button className="icon" aria-label="关闭预览" onClick={() => setInspection(null)}><X size={19}/></button></header><p>{inspection.text}</p>{inspection.messageId !== undefined && <div className="candidate-switch" role="group" aria-label="切换消息候选"><button className="icon" aria-label="上一个候选" disabled={(candidate[inspection.messageId] || 1) === 1} onClick={() => setCandidate(old => ({...old, [inspection.messageId!]: (old[inspection.messageId!] || 1) - 1}))}><ChevronLeft size={16}/></button><span>{candidate[inspection.messageId] || 1} / 3</span><button className="icon" aria-label="下一个候选" disabled={candidate[inspection.messageId] === 3} onClick={() => setCandidate(old => ({...old, [inspection.messageId!]: (old[inspection.messageId!] || 1) + 1}))}><ChevronRight size={16}/></button></div>}<button className="quiet-button" onClick={() => setInspection(null)}>返回消息</button></div></div>}
    {deleting !== null && <div className="source-backdrop"><div className="source-dialog delete-dialog" role="alertdialog" aria-modal="true" aria-label="删除这条消息？"><span className="delete-symbol"><Trash2 size={21}/></span><h3>删除这条消息？</h3><p>第 {floorOf(deleting)} 层会从设计稿中移除。这里只影响示例消息。</p><div className="dialog-actions"><button className="quiet-button" autoFocus onClick={() => setDeleting(null)}>保留消息</button><button className="danger-button" onClick={remove}>删除消息</button></div></div></div>}
  </div>;
}

function CharacterPanel({notify}: {notify: (s: string) => void}) {
  const [selected, setSelected] = useState(0), [query, setQuery] = useState("");
  const [tab, setTab] = useState(0), [starred, setStarred] = useState(true), [expanded, setExpanded] = useState(false);
  const src = selected === 1 ? "assets/traveler.webp" : "assets/character.webp";
  const descriptions = ["旧书店的主人，也是灯塔看守人的女儿。她熟悉小镇的每一条街，却从未离开过这片海岸。父亲失踪后，她接管了书店，日复一日地等待一封不会寄来的信。", "安静、细心，习惯先倾听再回答。涉及父亲和灯塔时，她会显露出少有的坚持。", "海边小镇的黄昏。雨刚停，旧书店尚未打烊。一本航海日志和一枚黄铜钥匙，把你们带向一座废弃多年的灯塔。", "「你在找什么书？」她从书架后探出头，目光在你湿透的外衣上停了一瞬。"];
  return <div className="character-demo"><div className="resource-frame"><header className="resource-head"><span><Users size={18}/>角色</span><div><button className="icon" aria-label="展开角色原图" onClick={() => setExpanded(true)}><Expand size={16}/></button><button className="icon" aria-label="收起侧栏说明" onClick={() => notify("角色卡布局与现有资源侧栏兼容")}><X size={19}/></button></div></header><div className="resource-body"><nav className="character-rail" aria-label="示例角色列表"><label><Search size={15}/><input value={query} onChange={e => setQuery(e.target.value)} aria-label="搜索示例角色" placeholder="搜索角色"/></label><div className="character-list">{names.map((name, i) => name.includes(query) && <button key={name} aria-current={i === selected ? "true" : undefined} onClick={() => {setSelected(i);setTab(0);}}><img src={i === 1 ? "assets/traveler.webp" : "assets/character.webp"} alt=""/><span><strong>{name}</strong><small>{i === 0 ? "当前角色" : i < 2 ? "故事角色" : "场景卡"}</small></span>{i === 0 && <Star size={12} fill="currentColor"/>}</button>)}</div><button className="rail-new" onClick={() => notify("沿用现有角色新建与导入")}><Plus size={16}/>新建角色</button></nav><article className="character-profile"><div className="portrait-atmosphere" aria-hidden="true"><img className="portrait-backdrop" src={src} alt=""/></div><div className="portrait-area"><div className="portrait-crop"><img className="portrait-image" src={src} alt={`${names[selected]}上半身`}/></div><div className="portrait-tools"><button className={`icon ${starred ? "is-starred" : ""}`} aria-label={starred ? "取消收藏角色" : "收藏角色"} aria-pressed={starred} onClick={() => setStarred(!starred)}><Star size={17} fill={starred ? "currentColor" : "none"}/></button><button className="icon" aria-label="查看完整角色卡" onClick={() => setExpanded(true)}><Expand size={17}/></button></div></div><div className="character-info"><div className="character-title"><h3>{names[selected]}<span> · 灯塔来信</span></h3>{selected === 0 && <span className="current-label"><span className="online-dot"></span>当前对话</span>}</div><p>海边旧书店的主人</p><div className="character-tags"><span>悬疑</span><span>海边小镇</span><span>慢叙事</span><span>开放世界</span></div></div><div className="character-tabs" role="tablist" aria-label="角色字段">{["描述", "性格", "场景", "第一条消息"].map((label, i) => <button key={label} role="tab" aria-selected={tab === i} onClick={() => setTab(i)}>{label}</button>)}</div><div className="character-description" role="tabpanel" aria-label={["描述", "性格", "场景", "第一条消息"][tab]}>{descriptions[tab]}</div><div className="world-binding"><BookMarked size={15}/><span>绑定世界书</span><strong>灯塔纪事</strong><ChevronRight size={14}/></div><footer className="character-footer"><button className="quiet-button" onClick={() => notify("沿用现有角色导出")}><Download size={15}/><span>导出</span></button><button className="save-button" onClick={() => notify("正式实现保留原角色编辑器，本次仅调整查看区")}><PencilLine size={15}/>编辑角色</button></footer></article></div></div>{expanded && <div className="image-lightbox" role="dialog" aria-modal="true" aria-label="完整角色卡"><button className="lightbox-close icon" aria-label="关闭完整角色卡" onClick={() => setExpanded(false)}><X size={24}/></button><img src={src} alt={`${names[selected]}完整角色卡`}/><span>按原始比例完整展示</span></div>}</div>;
}

function Plan({onView}: {onView: (s: View) => void}) {
  return <section className="plan" data-screen-label="04 五项修复方案"><div className="plan-title"><span className="overline">IMPLEMENTATION PROPOSAL / 2026.10.27</span><h2>五处修复，一套一致的交互。</h2><p>本轮交付方案与可交互设计稿。页面中的编辑、保存与角色切换均为演示。</p></div><div className="plan-table"><div className="plan-row plan-table-head"><span>问题</span><span>建议行为</span><span>验收标准</span></div>{[
    ["01", "PWA 没有编辑 AI 对话入口", "生图、复制、插图、附件、删除、编辑六个图标与更多按钮同行，编辑入口常显。", "320–430 px、触屏与专注模式均能编辑当前和历史 AI 消息。", "pwa"],
    ["02", "角色卡样式不对", "侧栏直接显示清晰的上半身；腰部以下渐隐，并将同图下半身虚化为信息区背景。名称、状态与标签独立排布。", "人物不拉伸、面部不被遮挡；下半身平滑虚化；浅色、深色下文字清晰，展开仍可查看原图。", "character"],
    ["03", "编辑历史消息跳到底部", "进入前记录目标消息锚点；焦点不触发滚动，光标初始位于开头。长文在编辑框内部滚动。", "编辑长历史消息时保持当前楼层；保存、取消仍回到同一消息。", "history"],
    ["04", "展开消息操作后有不明空间", "仅保留六个常用图标；翻译、朗读、提示词、候选、分支、媒体和检查点等进入二级菜单。", "桌面端图标与楼层信息等高、同行、居中对齐；触屏保留点击空间，无横向滚动或空白占位。", "pwa"],
    ["05", "编辑控件样式不一致", "进入编辑后，一行图标保留删除、更多、取消、保存；复制副本、上下移动和思考块进入二级菜单。", "图标清晰、触区 ≥44 px；禁用状态可区分；浅色、深色与短视口可用。", "pwa"],
  ].map(([number, title, behavior, acceptance, target]) => <div className="plan-row" key={number}><div><span className="plan-index">{number}</span><strong>{title}</strong></div><p>{behavior}</p><div><p>{acceptance}</p><button onClick={() => onView(target as View)}>查看设计<ChevronRight size={14}/></button></div></div>)}</div><div className="implementation"><div><span className="overline">实现范围</span><h3>沿用原生编辑与数据链路。</h3><p>工作台负责入口、位置与视觉；保存、取消、复制、思考块、移动、删除仍由 SillyTavern 处理。模型调用与消息数据格式保持现有机制。</p></div><ol><li><strong>消息呈现</strong><span>Reading.tsx / MobileShell.tsx：编辑入口、目标消息锚点、焦点与操作菜单。</span></li><li><strong>角色查看区</strong><span>Characters.tsx / resource-panel.css：上半身主体、下半身虚化背景与独立信息区。</span></li><li><strong>样式收口与最终验收</strong><span>native-bridge.css / pwa.css：按钮、空占位、触屏与主题；开发完成后统一检查 PWA、桌面及 RP 回归。</span></li></ol></div><div className="plan-footnote"><ShieldCheck size={19}/><p>第三版重点：六项常用操作与编辑入口同行、只用图标。其余能力进入二级菜单；图标提供辅助名称与悬停提示，删除前确认，菜单可用键盘操作。当前页面用于审阅，修订版尚未接入酒馆。</p></div></section>;
}

createRoot(document.getElementById("app")!).render(<App/>);
