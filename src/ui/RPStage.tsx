import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ArrowRight, BookOpen, Check, ChevronLeft, ChevronRight, Clock3, CornerDownLeft, History, MapPin, Maximize2, Minimize2, PencilLine, RotateCcw, Square, X, ImagePlus } from "lucide-react";
import type { HostAdapter } from "../host/adapter";
import { boundedPreference, dialoguePages } from "../host/rp";
import { IconButton, useHost } from "./common";
import { ReadingPresentation } from "./Reading";
import { beginImage } from "./AddonControls";
import { addonEnabled } from "../addons/catalog";
import { RPAppearance } from "./RPAppearance";
import { motionAllowed } from "./Motion";

type Message = { node: HTMLElement; id: number; name: string; user: boolean; parts: HTMLElement[]; pages: number[][]; editing: boolean };
type Cursor = { id: number; page: number; compose: boolean };

/** Keep native message, media, iframe, textarea and event-handler identities intact. */
function useNativeDialogue(host: HostAdapter, capacity: number) {
  const [messages, setMessages] = useState<Message[]>([]);
  useLayoutEffect(() => {
    const chat = document.getElementById("chat")!;
    let frame = 0;
    const scan = () => {
      const snapshot = host.snapshot();
      setMessages([...chat.querySelectorAll<HTMLElement>(".mes")].map(node => {
        const id = Number(node.getAttribute("mesid")), text = node.querySelector<HTMLElement>(".mes_text"), message = snapshot.messages.find(m => m.id === id);
        // Mixed text/HTML and nested plugin output stay together as a single scrollable page.
        const mixed = [...(text?.childNodes || [])].some(n => n.nodeType === Node.TEXT_NODE && n.textContent?.trim());
        const parts = mixed ? [] : [...(text?.children || [])] as HTMLElement[];
        const pages = dialoguePages(parts.map(part => ({ length: part.textContent?.length || 1, atomic: part.matches("iframe,pre,table,img,video,audio,svg,canvas") || !!part.querySelector("iframe,pre,table,img,video,audio,canvas") })), capacity);
        return { node, id, name: message?.name || node.querySelector(".name_text")?.textContent || "", user: node.getAttribute("is_user") === "true", parts, pages, editing: !!node.querySelector(".edit_textarea") };
      }));
    };
    scan();
    const observer = new MutationObserver(() => { cancelAnimationFrame(frame); frame = requestAnimationFrame(scan); });
    observer.observe(chat, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["mesid", "is_user"] });
    return () => { observer.disconnect(); cancelAnimationFrame(frame); };
  }, [host, capacity]);
  return messages;
}

export function RPStage({ host, hidden, blocked, width, readingLayout, run }: {
  host: HostAdapter; hidden: boolean; blocked: boolean; width: number; readingLayout: () => void; run: (fn: () => unknown) => unknown;
}) {
  const snap = useHost(host), prefs = host.prefs();
  const textSize = boundedPreference(prefs.rpTextSize, 19, 14, 26), dialogWidth = boundedPreference(prefs.rpDialogWidth, 88, 65, 94);
  const [height, setHeight] = useState(innerHeight);
  useEffect(() => { const resize = () => setHeight(innerHeight); window.addEventListener("resize", resize); return () => window.removeEventListener("resize", resize); }, []);
  const capacity = Math.max(120, Math.round((width * dialogWidth / 100 - 56) / textSize * Math.max(2, (Math.min(360, Math.max(180, height * .25)) - 50) / (textSize * 1.9))));
  const messages = useNativeDialogue(host, capacity), [cursor, setCursor] = useState<Cursor>({ id: -1, page: -1, compose: false });
  const beforeImage=useRef<Cursor|null>(null),cursorNow=useRef(cursor);cursorNow.current=cursor;
  const [history, setHistory] = useState(false), [expanded, setExpanded] = useState(false), [mediaRevision, setMediaRevision] = useState(0);
  const [scroll, setScroll] = useState({ overflow:false, scrolled:false, end:true });
  const originals = useRef(new Map<HTMLElement, { inert: boolean; aria: string | null }>()), partsSeen = useRef(new Set<HTMLElement>());
  const live = useRef(true), lastChat = useRef(snap.chatName), lastCount = useRef(0), lastTurn = useRef(""), animation = useRef<Animation | null>(null);
  const current = messages.find(m => m.id === cursor.id) || messages.at(-1);
  const page = current ? Math.min(current.pages.length - 1, Math.max(0, cursor.page < 0 ? current.pages.length - 1 : cursor.page)) : 0;
  const compose = cursor.compose || !current, presentation = host.rpPresentation(current?.user ? undefined : current?.name);
  void mediaRevision;
  const isHidden = hidden || blocked;
  useEffect(() => {
    if (lastChat.current !== snap.chatName) { lastChat.current = snap.chatName; live.current = true; setCursor({ id: -1, page: -1, compose: false }); setHistory(false); setExpanded(false); }
  }, [snap.chatName]);
  useEffect(() => {
    if (!messages.length) { lastCount.current = 0; return; }
    const newest = messages.at(-1)!;
    if (live.current && newest.id !== cursor.id && (messages.length !== lastCount.current || cursor.id < 0)) setCursor({ id: newest.id, page: 0, compose: false });
    lastCount.current = messages.length;
  }, [messages, cursor.id]);
  useEffect(() => {
    const jump = (e: Event) => { live.current = false; setHistory(false); setCursor({ id: (e as CustomEvent<number>).detail, page: 0, compose: false }); };
    const imageCompose=()=>{beforeImage.current??={...cursorNow.current};live.current=false;setHistory(false);setCursor(old=>({...old,compose:true}));};
    const imageEnd=()=>{if(beforeImage.current){setCursor(beforeImage.current);beforeImage.current=null;}};
    window.addEventListener("wb-image-compose", imageCompose);
    window.addEventListener("wb-image-compose-end", imageEnd);
    window.addEventListener("wb-rp-jump", jump);
    return () => {window.removeEventListener("wb-rp-jump", jump);window.removeEventListener("wb-image-compose", imageCompose);window.removeEventListener("wb-image-compose-end", imageEnd);};
  }, []);
  useEffect(() => {
    let frame = 0;
    const observer = new MutationObserver(records => {
      if (records.some(r => (r.target as Element).closest?.("#expression-wrapper,#visual-novel-wrapper") || [...r.addedNodes].some(n => n instanceof Element && n.matches("#expression-wrapper,#visual-novel-wrapper")))) {
        cancelAnimationFrame(frame); frame = requestAnimationFrame(() => setMediaRevision(v => v + 1));
      }
    });
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["src", "data-avatar"] });
    return () => { observer.disconnect(); cancelAnimationFrame(frame); };
  }, []);
  useLayoutEffect(() => {
    document.body.classList.toggle("wb-rp-compose", compose && !history);
    document.body.classList.toggle("wb-rp-expanded", expanded && compose && !history);
    document.body.classList.toggle("wb-rp-history", history);
    const sheld = document.getElementById("sheld")!, form = document.getElementById("form_sheld")!;
    sheld.inert = isHidden;
    form.inert = !compose || history || isHidden;
    document.body.style.setProperty("--wb-rp-text", textSize + "px");
    document.body.style.setProperty("--wb-rp-width", String(dialogWidth / 100));
    document.body.style.setProperty("--wb-rp-sprite", boundedPreference(prefs.rpSpriteScale, 91, 55, 100) + "vh");
    document.body.style.setProperty("--wb-rp-font", prefs.readingFont === "sans" ? "system-ui,sans-serif" : "'Noto Serif CJK SC','Source Han Serif SC','Songti SC',SimSun,serif");
    for (const message of messages) {
      const visible = history || (message === current && !compose);
      if (!originals.current.has(message.node)) originals.current.set(message.node, { inert: message.node.inert, aria: message.node.getAttribute("aria-hidden") });
      message.node.classList.toggle("wb-rp-current", message === current);
      message.node.inert = !visible;
      message.node.setAttribute("aria-hidden", String(!visible));
      message.parts.forEach((part, index) => {
        partsSeen.current.add(part); part.classList.add("wb-rp-part");
        part.classList.toggle("wb-rp-part-active", message.pages[page]?.includes(index) || false);
      });
    }
    for (const [node, previous] of originals.current) if (!node.isConnected) { node.inert = previous.inert; previous.aria === null ? node.removeAttribute("aria-hidden") : node.setAttribute("aria-hidden", previous.aria); node.classList.remove("wb-rp-current"); originals.current.delete(node); }
    for (const part of partsSeen.current) if (!part.isConnected) { part.classList.remove("wb-rp-part", "wb-rp-part-active"); partsSeen.current.delete(part); }
    const turn = `${current?.id}:${page}:${compose}:${history}`;
    if (turn !== lastTurn.current) {
      lastTurn.current = turn;
      const text = current?.node.querySelector<HTMLElement>(".mes_text");
      if (text && !history && !compose) {
        text.scrollTop = 0; sheld.querySelector("#chat")!.scrollTop = 0;
        animation.current?.cancel();
        if (motionAllowed()) animation.current = text.animate([{ opacity: .2, transform: "translateX(14px)" }, { opacity: 1, transform: "translateX(0)" }], { duration: 240, easing: "cubic-bezier(.22,.8,.3,1)" });
      }
    }
  }, [messages, current, page, compose, history, expanded, isHidden, textSize, dialogWidth, prefs.rpSpriteScale, prefs.readingFont]);
  useEffect(() => () => {
    animation.current?.cancel();
    originals.current.forEach((previous, node) => { node.inert = previous.inert; previous.aria === null ? node.removeAttribute("aria-hidden") : node.setAttribute("aria-hidden", previous.aria); node.classList.remove("wb-rp-current"); });
    partsSeen.current.forEach(part => part.classList.remove("wb-rp-part", "wb-rp-part-active"));
    document.getElementById("sheld")!.inert = false; document.getElementById("form_sheld")!.inert = false;
    document.body.classList.remove("wb-rp-compose", "wb-rp-expanded", "wb-rp-history");
    for (const name of ["text", "width", "sprite", "font"]) document.body.style.removeProperty("--wb-rp-" + name);
  }, []);
  useEffect(() => {
    const chat = document.getElementById("chat")!, text = current?.node.querySelector<HTMLElement>(".mes_text");
    const measure = () => {
      const next = { overflow:chat.scrollHeight > chat.clientHeight + 2, scrolled:chat.scrollTop > 2, end:chat.scrollTop + chat.clientHeight >= chat.scrollHeight - 2 };
      setScroll(old => old.overflow === next.overflow && old.scrolled === next.scrolled && old.end === next.end ? old : next);
    };
    measure(); chat.addEventListener("scroll", measure, { passive:true });
    const observer = new ResizeObserver(measure); observer.observe(chat); if (text) observer.observe(text);
    return () => { observer.disconnect(); chat.removeEventListener("scroll", measure); };
  }, [current?.node, page, compose, history]);
  const turn = (delta: number) => {
    if (current?.editing) return;
    if (compose) { setCursor({ id: current?.id ?? -1, page: -1, compose: false }); return; }
    if (!current) return;
    const chat = document.getElementById("chat")!;
    if ((delta > 0 && chat.scrollTop + chat.clientHeight < chat.scrollHeight - 2) || (delta < 0 && chat.scrollTop > 2)) {
      chat.scrollBy({ top:delta * Math.max(80, chat.clientHeight - 36), behavior:motionAllowed() ? "smooth" : "instant" });
      return;
    }
    live.current = false;
    const index = messages.indexOf(current), nextPage = page + delta;
    if (nextPage >= 0 && nextPage < current.pages.length) setCursor({ id: current.id, page: nextPage, compose: false });
    else if (delta < 0 && index > 0) setCursor({ id: messages[index - 1].id, page: -1, compose: false });
    else if (delta > 0 && index < messages.length - 1) setCursor({ id: messages[index + 1].id, page: 0, compose: false });
    else if (delta > 0) { live.current = true; setCursor({ id: current.id, page: -1, compose: true }); }
  };
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.isComposing || e.ctrlKey || e.altKey || e.metaKey || isHidden || history || document.querySelector("dialog[open],.wb-popover,[role=listbox]")) return;
      if ((e.target as Element)?.closest("input,textarea,select,button,[contenteditable=true]")) return;
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") { e.preventDefault(); turn(e.key === "ArrowLeft" ? -1 : 1); }
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  });
  const nativeAction = (selector: string) => run(() => {
    const button = current?.node.querySelector<HTMLElement>(selector);
    if (!button) throw new Error("当前消息没有此操作。");
    button.click();
  });
  const enterCompose = () => { if (current?.editing) return; live.current = true; setHistory(false); setCursor({ id: current?.id ?? -1, page: -1, compose: true }); };
  const visibleDots = current?.pages.map((_, i) => i).filter(i => Math.abs(i - page) <= 3) || [];
  const replies = [...new Map(host.quickReplies().map((qr: any) => [qr.key, qr])).values()].slice(0, 3) as any[];
  const scene = presentation.scene, sceneValue = (key: string) => typeof scene[key] === "string" || typeof scene[key] === "number" ? String(scene[key]) : "";
  return <>
    {createPortal(<div className="wb-rp-stage" aria-label="RP 舞台">
      <div className="wb-rp-atmosphere" />
      {(presentation.sprite || (prefs.rpShowPortraits !== false && presentation.portrait)) && <div className={`wb-rp-actor ${presentation.sprite ? "is-sprite" : "is-portrait"} ${current?.user || compose ? "is-listening" : "is-speaking"}`}><img src={presentation.sprite || presentation.portrait} alt={presentation.name} /><span>{presentation.name}</span></div>}
      {(presentation.userSprite || (prefs.rpShowPortraits !== false && presentation.userPortrait)) && <div className={`wb-rp-user ${presentation.userSprite ? "is-sprite" : "is-portrait"} ${current?.user || compose ? "is-speaking" : "is-listening"}`}><img src={presentation.userSprite || presentation.userPortrait} alt={presentation.userName} /><span>{presentation.userName}</span></div>}
    </div>, document.body)}
    <aside className={`wb-rp-situation ${isHidden || width < 1000 || (expanded && compose) || history ? "is-hidden" : ""}`} inert={isHidden || width < 1000 || history} aria-label="当前场景信息"><small>{sceneValue("day") ? "DAY " + sceneValue("day") : "当前对话"}</small><strong>{sceneValue("location") || snap.groupName || snap.character?.name || "等待故事开始"}</strong>{sceneValue("weather") && <span><MapPin size={13} />{sceneValue("weather")}</span>}<span><Clock3 size={13} />{sceneValue("time") || host.messageTime(snap.messages.find(m => m.id === current?.id)?.send_date) || "选择角色后开始"}</span></aside>
    <section className={`wb-rp-dialog-shell ${width < 800 ? "is-compact" : ""} ${isHidden || history ? "is-hidden" : ""}`} inert={isHidden || history} aria-label="RP 对白与输入">
      <div className="wb-rp-deck-header"><div className="wb-rp-speaker"><strong>{compose ? presentation.userName : current?.name || presentation.name}</strong><small>{compose ? "你的回应" : current?.user ? "你的输入" : "对白"}</small></div>
        <div className="wb-rp-deck-actions"><button aria-label="查看对话记录" title="对话记录" onClick={() => setHistory(true)}><History size={15} /><span>记录</span></button><IconButton title="切换阅读布局" onClick={readingLayout}><BookOpen size={16} /></IconButton><RPAppearance host={host} />
          {host.isGenerating() && <IconButton title="停止生成" onClick={() => run(() => host.click("#mes_stop"))}><Square size={16} /></IconButton>}
          {current?.editing ? <><IconButton title="保存对白编辑" onClick={() => nativeAction(".mes_edit_done")}><Check size={16} /></IconButton><IconButton title="取消对白编辑" onClick={() => nativeAction(".mes_edit_cancel")}><X size={16} /></IconButton></> : <><IconButton title="重生成当前回复" disabled={snap.busy || !current || current.user || current.id !== snap.messages.length - 1} onClick={() => run(() => host.click("#option_regenerate"))}><RotateCcw size={16} /></IconButton><IconButton title="编辑当前对白" disabled={snap.busy || !current || compose} onClick={() => nativeAction(".mes_edit")}><PencilLine size={16} /></IconButton>{addonEnabled(prefs,"image-gen")&&<IconButton title="为当前对白生图" disabled={snap.busy||!current||compose} onClick={()=>beginImage(host,current!.id)}><ImagePlus size={16}/></IconButton>}</>}
          <div className="wb-rp-page-control"><IconButton title="上一段对白" disabled={(!compose && current === messages[0] && page === 0 && !scroll.scrolled) || !current || current.editing} onClick={() => turn(-1)}><ChevronLeft size={17} /></IconButton><span aria-live="polite">{compose ? "输入" : `${page + 1} / ${current?.pages.length || 1}`}</span><IconButton title="下一段对白或输入" disabled={compose || !!current?.editing} onClick={() => turn(1)}><ChevronRight size={17} /></IconButton></div>
        </div>
      </div>
      <div className="wb-rp-caption"><span>{compose ? "写下接下来发生的事" : `#${(current?.id ?? 0) + 1} · ${scroll.overflow ? "长对白 · 可滚动阅读" : page + 1 === current?.pages.length ? "最后一段" : "对白"}`}</span><div className="wb-rp-page-dots">{visibleDots.map(index => <button key={index} aria-label={`对白第 ${index + 1} 段`} aria-current={!compose && index === page ? "true" : undefined} disabled={!!current?.editing} onClick={() => { live.current = false; setCursor({ id: current!.id, page: index, compose: false }); }} />)}<button className="wb-icon" aria-label="输入回应" aria-current={compose ? "true" : undefined} disabled={!!current?.editing} onClick={enterCompose}><PencilLine size={14} /></button>{compose && <button className="wb-icon" aria-label={expanded ? "还原 RP 输入区" : "展开 RP 输入区"} aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? <Minimize2 size={16} /> : <Maximize2 size={16} />}</button>}</div></div>
      {!compose && !current?.editing && <button className="wb-rp-next-hint" onClick={() => turn(1)}>{!scroll.end ? "继续阅读" : page + 1 === current?.pages.length && current === messages.at(-1) ? "继续，轮到你回应" : "继续下一段"}<ArrowRight size={14} /></button>}
      {compose && !expanded && !!replies.length && <div className="wb-rp-suggestions" aria-label="你的回应">{replies.map(qr => <button key={qr.key} title={qr.message} disabled={snap.busy} onClick={() => { host.setInput(qr.message || ""); }}><span>{qr.label || qr.message?.slice(0, 45)}</span><CornerDownLeft size={14} /></button>)}</div>}
    </section>
    {history && <><div className="wb-rp-history-bar"><strong>对话记录</strong><small>{snap.chatName}</small><span className="wb-grow" /><button aria-label="返回 RP 对白" onClick={() => setHistory(false)}>返回对白 <X size={17} /></button></div><ReadingPresentation host={host} /></>}
  </>;
}
