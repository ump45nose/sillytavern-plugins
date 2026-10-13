import React, { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { ScanLine, X, Activity, BookOpen, FileOutput, SlidersHorizontal, UserRound, UsersRound, Plug, ChevronDown, ChevronLeft, ChevronRight, Eye, EyeOff, Pin, PinOff, ListTree, ImagePlus } from "lucide-react";
import { resolveTool } from "./host/tools";
import { addonEnabled } from "./addons/catalog";
import { addonManager } from "./addons/runtime";
import { AddonTasks, MessageImageControls, ImageInputMode } from "./ui/AddonControls";
import AddonWorkspace from "./ui/AddonWorkspace";
import { ResourceRailContext } from "./ui/ResourcePicker";
import {ClickFeedback,usePresence} from "./ui/Motion";
import { Header } from "./ui/Header";
import { Composer } from "./ui/Composer";
import {useSidebarHover} from "./ui/useSidebarHover";
import { Navigation } from "./ui/Navigation";
import {ComposerPopovers, type ComposerPopup} from "./ui/ComposerPopovers";
import {ReadingPresentation,ReadingSettings} from "./ui/Reading";
import { Operations, shortcutAction, shortcutHint } from "./host/operations";
import {Shortcuts} from "./ui/Shortcuts";
import {RPStage} from "./ui/RPStage";
import {MobileShell} from "./ui/MobileShell";
import {useMobileViewport} from "./ui/useMobileViewport";
import type {LayoutMode} from "./ui/LayoutSwitcher";
import type { HostAdapter } from "./host/adapter";
import type { Panel, Resource, SettingsPage } from "./host/types";
import {
  useHost,
  useTask,
  IconButton,
  Empty,
  Dialog,
  Loading,
} from "./ui/common";
const World = lazy(() => import("./modules/World"));
const Characters = lazy(() => import("./modules/Characters"));
const Resources = lazy(() => import("./modules/Resources"));
const Trace = lazy(() => import("./modules/Trace"));
const SettingsWorkspace=lazy(()=>import("./modules/SettingsWorkspace"));
const labels = {
  connection: "连接",
  preset: "预设",
  world: "世界书",
  persona: "用户设定",
};
export function beforeClose() {
  return window.dispatchEvent(
    new Event("wb-before-close", { cancelable: true }),
  );
}
export default function App({
  host,
  trace,
  toolbar,
  onExit,
  onLayout,
}: {
  host: HostAdapter;
  trace: any;
  toolbar: HTMLElement;
  onExit: () => void;
  onLayout: (layout:LayoutMode) => void;
}) {
  const [operations] = useState(() => new Operations());
  const snap = useHost(host),
    task = useTask(),
    [left, setLeft] = useState(innerWidth<1024 || host.prefs().layout === "rp" ? false : host.prefs().left),
    [panel, setPanel] = useState<Panel>(null),
    [chooser, setChooser] = useState<Resource | null>(null),
    [focusId, setFocusId] = useState(""),
    [deep, setDeep] = useState<Panel | "library">(null),
    [focus, setFocus] = useState(false),
    [width, setWidth] = useState(window.innerWidth),
    [renderedPanel, setRenderedPanel] = useState<Panel>(null),
    [tabsOpen, setTabsOpen] = useState(false),
    [railOpen, setRailOpen] = useState(true),
    [railTarget, setRailTarget] = useState<HTMLElement|null>(null),
    [popup,setPopup]=useState<ComposerPopup|null>(null),
    [workspace,setWorkspace]=useState<{page:SettingsPage;group?:string;initial?:string}|null>(null),
    [help, setHelp] = useState(false),
    [externalError, setExternalError] = useState("");
  const mobile=width<1024;
  useMobileViewport(mobile);
  const rp=host.prefs().layout==='rp',leftWidth=width<=1400?240:260,rightWidth=width<=1400?440:460;
  const pinnedRail=!!panel&&!['trace','export','outline','image-gen'].includes(panel)&&railOpen&&!focus;
  const leftVisible=left&&!focus&&(mobile?!panel:(!panel||((!rp||width>1100)&&width-leftWidth-rightWidth-(pinnedRail?180:0)>=420)));
  const hover=useSidebarHover(!mobile&&!focus&&!workspace&&!deep&&!help&&!document.querySelector('dialog[open]'),leftVisible,!!panel,beforeClose);
  const lastPanel=useRef<Panel>('character');
  if(panel)lastPanel.current=panel;
  const rememberedPanel=lastPanel.current;
  const rememberedEnabled=rememberedPanel==='export'?addonEnabled(host.prefs(),'record-export'):rememberedPanel==='outline'||rememberedPanel==='image-gen'?addonEnabled(host.prefs(),rememberedPanel):true;
  const lastAvailablePanel=rememberedEnabled?rememberedPanel:'character';
  const shownPanel=panel||(hover.right?lastAvailablePanel:null);
  const manager=addonManager(host);
  useEffect(()=>()=>manager.dispose(),[manager]);
  useEffect(()=>{const handler=(event:Event)=>{const {id,view}=(event as CustomEvent).detail;if(!addonEnabled(host.prefs(),id))return;if(view==='editor'){if(beforeClose()){setDeep(id);setWorkspace(null);setPanel(null);if(mobile)setLeft(false);}}else goPanel(id);};window.addEventListener('wb-addon-open',handler);return()=>window.removeEventListener('wb-addon-open',handler);});
  const exportEnabled = addonEnabled(host.prefs(), "record-export");
  useEffect(() => { if (!exportEnabled && panel === "export") setPanel(null); }, [exportEnabled, panel]);
  useEffect(()=>{if((panel==='outline'||panel==='image-gen')&&!addonEnabled(host.prefs(),panel))setPanel(null);if((deep==='outline'||deep==='image-gen')&&!addonEnabled(host.prefs(),deep))setDeep(null);},[host.revision(),panel,deep]);
  const topAuto = !mobile && rp && !!host.prefs().rpTopAuto;
  const [topHot, setTopHot] = useState(false), [topFocus, setTopFocus] = useState(false), [layoutMenu, setLayoutMenu] = useState(false);
  const topCollapsed = topAuto && !topHot && !topFocus && !chooser && !layoutMenu;
  const topPointer = useRef(Infinity);
  const lastLayout = useRef(rp);
  useLayoutEffect(() => {
    if (lastLayout.current === rp) return;
    lastLayout.current = rp;
    setPanel(null); setChooser(null); setPopup(null); setWorkspace(null); setDeep(null); setFocus(false); setTopHot(false); setTopFocus(false);
    hover.dismiss('left');hover.dismiss('right');
    setLeft(mobile || rp ? false : host.prefs().left);
  }, [rp, host]);
  const previousMobile=useRef(mobile);
  useLayoutEffect(()=>{if(previousMobile.current===mobile)return;previousMobile.current=mobile;setLeft(mobile||rp?false:host.prefs().left);setPanel(null);setChooser(null);setPopup(null);setFocus(false);hover.dismiss('left');hover.dismiss('right');},[mobile]);
  useEffect(()=>{const compose=()=>{if(rp&&width<=1100){setPanel(null);setLeft(false);}};window.addEventListener('wb-image-input',compose);return()=>window.removeEventListener('wb-image-input',compose);},[rp,width]);
  const switchLayout = onLayout;
  useEffect(() => {
    const menu = (event:Event) => { const open = !!(event as CustomEvent).detail; setLayoutMenu(open); if (open) setChooser(null); };
    window.addEventListener("wb-layout-menu", menu);
    return () => window.removeEventListener("wb-layout-menu", menu);
  }, []);
  useEffect(() => {
    if (!rp) return;
    setTopHot(topAuto && topPointer.current <= (topCollapsed ? 14 : 74));
    let hide:ReturnType<typeof setTimeout> | undefined;
    const clear = () => { if (hide) clearTimeout(hide); hide = undefined; };
    const leave = () => { if (!hide) hide = setTimeout(() => {
      setTopHot(false);
      if (!document.querySelector('.wb-top :focus-visible,.wb-rp-top-trigger:focus-visible')) setTopFocus(false);
      hide = undefined;
    }, 140); };
    const move = (event:PointerEvent) => {
      if (event.pointerType === "touch") return;
      topPointer.current = event.clientY;
      if (!topAuto) return;
      // The reveal strip and header form one hover region, without relying on display:contents hit boxes.
      if (event.clientY <= (topCollapsed ? 14 : 74)) { clear(); setTopHot(true); }
      else leave();
    };
    document.addEventListener("pointermove", move); document.documentElement.addEventListener("pointerleave", leave);
    return () => { clear(); document.removeEventListener("pointermove", move); document.documentElement.removeEventListener("pointerleave", leave); };
  }, [rp, topAuto, topCollapsed]);
  const selectedIds = useRef<Partial<Record<NonNullable<Panel>, string>>>({});
  const popupPresence=usePresence(popup),workspacePresence=usePresence(workspace),helpPresence=usePresence(help?true:null);
  const openPopup=useCallback((next:ComposerPopup)=>setPopup(prev=>prev?.kind===next.kind&&prev.anchor===next.anchor?null:next),[]);
  const openSettings=(page:SettingsPage,group?:string,initial?:string)=>{if(!beforeClose())return;setPopup(null);setPanel(null);setChooser(null);setDeep(null);setWorkspace({page,group,initial});if(mobile)setLeft(false);};
  const goPanel = (next: Panel, id?: string) => {
    if (next === "export" && !exportEnabled) return;
    if((next==='outline'||next==='image-gen')&&!addonEnabled(host.prefs(),next))return;
    if (!beforeClose()) return;
    if (next && id !== undefined) selectedIds.current[next] = id;
    hover.dismiss("right");
    setPanel(next);
    if(mobile&&next)setLeft(false);
    if (rp && next && width <= 1100) setLeft(false);
    if(next)setRailOpen(true);
    if (next) setFocusId(id ?? selectedIds.current[next] ?? "");
    setChooser(null);
  };
  const goDeep = (next: Panel | "library", id = "") => {
    if(next==="world"||next==="connection"||next==="preset"||next==="persona"||next==="library"){openSettings(next==="preset"?"generation":next==="library"?"character":next,undefined,id);return;}
    if (!beforeClose()) return;
    setDeep(next);
    setFocusId(id);
    setPanel(null);
    setChooser(null);
  };
  const activateTool = (id: string, anchor: HTMLElement) => {
    setPopup(null);
    if (id === "wb:export") { goPanel("export"); return; }
    if (id === "builtin:quick") { setPopup({ kind: "quick", anchor }); return; }
    const selectors: Record<string, string> = { "builtin:continue": "#option_continue", "builtin:regenerate": "#option_regenerate", "builtin:impersonate": "#option_impersonate", "builtin:attachment": "#attachFile" };
    if (selectors[id]) { void task.run(() => host.click(selectors[id])); return; }
    const item = resolveTool(id);
    if (!item || item.disabled) { host.report("此工具当前不可用，请检查插件是否启用。"); return; }
    if (item.node.id === "option_toggle_AN" || item.node.id === "option_toggle_CFG") {
      setPopup({ kind: "tool", toolId: id, anchor });
    } else { void task.run(() => item.node.click()); }
  };
  const next = (kind: Resource) =>
    task.run(async () => {
      const items = snap.resources[kind];
      if (!items.length) {
        goPanel(kind);
        return;
      }
      const index = items.findIndex(
        (x) =>
          x.id ===
          (kind === "world"
            ? focusId || snap.current.world
            : snap.current[kind]),
      );
      const item = items[(index + 1) % items.length];
      if (kind === "world") goPanel(kind, item.id);
      else await host.select(kind, item.id);
    });
  for (const kind of [
    "connection",
    "preset",
    "world",
    "persona",
  ] as Resource[]) {
    operations.register(`open.${kind}`, () => goPanel(kind));
    operations.register(`next.${kind}`, () => next(kind));
  }
  operations.register("open.trace", () => goPanel("trace"));
  operations.register("outline.editor",()=>{if(addonEnabled(host.prefs(),"outline"))manager.api("outline").open("editor");});
  operations.register("open.outline",()=>goPanel("outline"));
  operations.register("outline.insert",()=>{if(addonEnabled(host.prefs(),'outline'))void manager.ensure('outline').then(r=>r.action('insert')).catch(e=>host.report(e));});
  operations.register("outline.pause",()=>{const r=manager.get('outline');if(r)void r.action(r.task().status==='running'?'pause':'resume').catch(e=>host.report(e));});
  operations.register("open.image-gen",()=>goPanel("image-gen"));
  operations.register("open.character", () => goPanel("character"));
  const railVisible=!mobile&&!!shownPanel&&shownPanel!=="trace"&&shownPanel!=="export"&&shownPanel!=="outline"&&shownPanel!=="image-gen"&&railOpen&&!focus;
  const navigationVisible=leftVisible||(hover.left&&!focus);
  const toggleLeft = () => { if(mobile){if(!beforeClose())return;setPanel(null);setChooser(null);setPopup(null);setLeft(v=>!v);return;} if(hover.left&&!leftVisible){hover.dismiss('left');if(panel)goPanel(null);setLeft(true);return;}hover.dismiss('left'); if (rp && width <= 1100 && !left) {goPanel(null);setLeft(true);} else if (left && !leftVisible && !focus) goPanel(null); else setLeft(v => !v); };
  const toggleRight=()=>{if(hover.right&&!panel)goPanel(shownPanel);else goPanel(panel?null:lastAvailablePanel);};
  const toggleFocus = () => { setChooser(null); setFocus(v => !v); };
  operations.register("toggle.left", toggleLeft);
  operations.register("toggle.focus", toggleFocus);
  useEffect(() => { const resize = () => setWidth(window.innerWidth); window.addEventListener("resize", resize); return () => window.removeEventListener("resize", resize); }, []);
  useEffect(() => {
    if (shownPanel) { setRenderedPanel(shownPanel); return; }
    const timer = setTimeout(() => setRenderedPanel(null), 220);
    return () => clearTimeout(timer);
  }, [shownPanel]);
  useEffect(() => { if (!rp&&!mobile) host.preference({ left }); }, [left, rp,mobile]);
  useLayoutEffect(() => {
    document.body.classList.toggle("wb-left-open", leftVisible);
    document.body.classList.toggle("wb-left-hover-open",hover.left&&!leftVisible);
    document.body.classList.toggle("wb-right-hover-open",hover.right&&!panel);
    document.body.classList.toggle("wb-right-open", !!panel && !focus);
    document.body.classList.toggle("wb-focus", focus);
    document.body.classList.toggle("wb-rail-open",railVisible&&!!panel);
    document.body.classList.toggle("wb-mobile",mobile);
    document.body.classList.toggle("wb-mobile-rp",mobile&&rp);
    document.body.classList.toggle("wb-rp",rp&&!mobile);
    document.body.classList.toggle("wb-rp-top-auto",topAuto);
    document.body.classList.toggle("wb-rp-top-collapsed",topCollapsed);
    document.body.classList.toggle("wb-rp-overlay-open",rp && width <= 1100 && !!(leftVisible || (panel && !focus)));
  }, [leftVisible, panel, focus, railVisible, rp, topAuto, topCollapsed, width,hover.left,hover.right,mobile]);
  useEffect(() => {
    const handler = (e: Event) => setExternalError((e as CustomEvent).detail);
    window.addEventListener("wb-error", handler);
    return () => window.removeEventListener("wb-error", handler);
  }, []);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.isComposing || workspace) return;
      if (e.key === "Escape") {
        if (chooser) {
          setChooser(null);
          return;
        }
        if (focus) {
          setFocus(false);
          return;
        }
        host.closeNative();
        return;
      }
    };
    const shortcut=(e:KeyboardEvent)=>{
      if(e.defaultPrevented||e.isComposing||e.repeat||e.getModifierState("AltGraph")||workspace||deep||help||document.querySelector("dialog[open]"))return;
      const prefs=host.prefs();if(prefs.shortcutsEnabled===false)return;
      const action=shortcutAction(e,prefs.shortcuts);
      if(action){e.preventDefault();e.stopPropagation();operations.run(action);}
    };
    document.addEventListener("keydown", key);
    document.addEventListener("keydown",shortcut,true);
    return () => {document.removeEventListener("keydown", key);document.removeEventListener("keydown",shortcut,true);};
  });
  const content = (kind: Panel, independent = false) =>
    kind === "world" ? (
      <World
        key={`world:${focusId}`}
        host={host}
        initial={focusId}
        deep={independent}
        onDeep={independent ? undefined : (name) => goDeep("world", name)}
      />
    ) : kind === "character" ? (
      <Characters host={host} onManage={group => group?openSettings("character",group):goDeep("library")} />
    ) : kind === "export" ? (
      <AddonWorkspace host={host} id="record-export" active={shownPanel === "export" && !workspace && !deep} />
    ) : kind === "outline" || kind === "image-gen" ? (
      <AddonWorkspace host={host} id={kind} active={independent || (shownPanel===kind&&!workspace&&!deep)} view={independent?"editor":"workspace"}/>
    ) : kind === "trace" ? (
      <Trace host={host} trace={trace} />
    ) : kind ? (
      <Resources
        key={`${kind}:${focusId}`}
        host={host}
        kind={kind}
        onSelection={id => { selectedIds.current[kind] = id; }}
        initial={focusId}
        deep={independent}
        onDeep={independent ? undefined : (id) => goDeep(kind, id)}
      />
    ) : null;
  return (
    <>
      <ClickFeedback/>
      <AddonTasks host={host}/>
      <MessageImageControls host={host}/>
      <ImageInputMode host={host}/>
      {mobile&&<MobileShell host={host} snap={snap} rp={rp} left={leftVisible} panel={shownPanel} chooser={chooser} setChooser={setChooser} goPanel={goPanel} toggleLeft={toggleLeft} closeDrawers={()=>{if(beforeClose()){setLeft(false);goPanel(null);}}} onLayout={switchLayout} settings={openSettings} open={openPopup} activate={activateTool} next={next} select={(kind,id,enabled)=>{void task.run(()=>kind==='world'?host.toggleBook(id,enabled):host.select(kind,id));}}/>}
      {!mobile&&<div className="wb-header-shell" inert={rp && (focus || topCollapsed)} onPointerLeave={e=>{if(e.pointerType!=="touch"&&!e.currentTarget.querySelector(':focus-visible'))setTopFocus(false);}} onFocusCapture={()=>setTopFocus(true)} onBlurCapture={e=>{if(!e.currentTarget.contains(e.relatedTarget as Node))setTopFocus(false);}}>
      <Header snap={snap} panel={shownPanel} chooser={chooser} setChooser={setChooser} goPanel={goPanel}
        next={kind => operations.run(`next.${kind}`)} model={host.model()} focus={toggleFocus} focused={focus}
        actions={rp ? <button className={`wb-top-action wb-top-pin ${!topAuto?"is-active":""}`} aria-label="固定顶栏" title={topAuto?"固定顶栏":"取消固定 · 鼠标悬浮显示"} aria-pressed={!topAuto} onClick={()=>{setTopHot(true);setTopFocus(!!document.querySelector('.wb-top-pin:focus-visible'));host.preference({rpTopAuto:!topAuto});}}>{topAuto?<PinOff size={20}/>:<Pin size={20}/>}</button> : undefined}
        focusShortcut={host.prefs().shortcutsEnabled===false?"":shortcutHint("toggle.focus",host.prefs().shortcuts)}
        select={(kind, id, enabled) => task.run(async () => {
          if (kind === "world") await host.toggleBook(id, enabled);
          else await host.select(kind, id);
        })} />
      </div>}
      {!mobile&&rp && <><button className="wb-rp-visibility wb-icon" aria-label={focus?"显示界面":"隐藏界面"} title={focus?"显示界面":"隐藏界面"} aria-pressed={focus} onClick={toggleFocus}>{focus?<Eye size={20}/>:<EyeOff size={20}/>}</button>
      {topAuto && !focus && <button className="wb-rp-top-trigger" aria-label="显示顶栏" tabIndex={topCollapsed?0:-1} onFocus={()=>setTopFocus(true)} onBlur={e=>{if(!(e.relatedTarget as Element)?.closest?.('.wb-top'))setTopFocus(false);}} onClick={()=>{setTopHot(true);setTopFocus(true);requestAnimationFrame(()=>document.querySelector<HTMLButtonElement>('.wb-selector-value')?.focus());}}><span/></button>}</>}
      {!mobile&&!rp &&
      <div className="wb-reading-bar">
        <span className="wb-chat-name" title={snap.chatName}>{snap.chatName || "开始一段新的故事"}</span>
        <span className="wb-grow" />
        <ReadingSettings host={host}/>
        {focus && <button className="wb-exit-focus wb-top-action is-active" title="退出专注" aria-label="退出专注" aria-pressed="true" onClick={toggleFocus}><ScanLine size={24} /></button>}
      </div>
      }
      {!mobile&&<nav className={`wb-edge-nav ${focus?"is-hidden":""}`} style={{"--wb-edge-left":`${navigationVisible?leftWidth:0}px`,"--wb-edge-right":`${shownPanel&&!focus?rightWidth+(railVisible?180:0):0}px`} as React.CSSProperties} inert={focus} aria-hidden={focus} aria-label="边栏操作">
        <button className="wb-edge-arrow wb-edge-left" aria-label={hover.left&&!leftVisible?"固定左边栏":leftVisible?"收纳左边栏":"展开左边栏"} title={`${hover.left&&!leftVisible?"固定左边栏":leftVisible?"收纳左边栏":"展开左边栏"}${host.prefs().shortcutsEnabled!==false&&shortcutHint("toggle.left",host.prefs().shortcuts)?" · "+shortcutHint("toggle.left",host.prefs().shortcuts):""}`} aria-expanded={navigationVisible} onClick={toggleLeft}>{navigationVisible?<ChevronLeft size={28}/>:<ChevronRight size={28}/>}</button>
        <button className="wb-edge-arrow wb-edge-right" aria-label={hover.right&&!panel?"固定右边栏":panel?"关闭右栏":"角色与资源侧栏"} title={hover.right&&!panel?"固定右边栏":panel?"关闭右栏":"角色与资源侧栏"} aria-expanded={!!shownPanel} onClick={toggleRight}>{shownPanel?<ChevronRight size={28}/>:<ChevronLeft size={28}/>}</button>
      </nav>}
      <Navigation host={host} snap={snap} visible={navigationVisible} settings={openSettings} open={openPopup}
        help={() => {if(mobile)setLeft(false);setHelp(true);}} exit={onExit} run={fn=>task.run(async()=>{await fn();if(mobile)setLeft(false);})} />
      <aside id="wb-resource-rail" ref={setRailTarget} className={`wb-resource-rail ${railVisible?"is-open":""}`} inert={!railVisible} aria-hidden={!railVisible} aria-label="资源列表与角色信息"/>
      <aside className={`wb-right ${shownPanel && !focus ? "is-open" : ""}`} inert={!shownPanel || focus} aria-hidden={!shownPanel || focus} aria-label="角色与资源">
        <div className="wb-panel-header-row"><button className="wb-panel-switch" aria-label="展开资源分类" aria-expanded={tabsOpen} onClick={()=>setTabsOpen(!tabsOpen)}><span>{shownPanel==="character"?"角色":shownPanel==="trace"?"Trace":shownPanel==="export"?"记录导出":shownPanel==="outline"?"大纲":shownPanel==="image-gen"?"生图":shownPanel?labels[shownPanel]:"角色与资源"}</span><ChevronDown size={14}/></button></div>
        <div className={`wb-panel-tabs-fold ${tabsOpen?"is-open":""}`} inert={!tabsOpen}>
        <div className="wb-panel-tabs">
          {([["character", "角色", UsersRound], ["world", "世界书", BookOpen], ["preset", "预设", SlidersHorizontal], ["connection", "连接", Plug], ["persona", "用户设定", UserRound], ["trace", "Trace", Activity], ["export", "记录导出", FileOutput], ["outline", "大纲", ListTree], ["image-gen", "生图", ImagePlus]] as const).filter(([kind]) => kind === "export"?exportEnabled:kind === "outline"||kind === "image-gen"?addonEnabled(host.prefs(),kind):true).map(([kind, label, Icon]) =>
            <button key={kind} className={shownPanel === kind ? "is-active" : ""} aria-pressed={shownPanel === kind} onClick={() => {goPanel(kind);setTabsOpen(false);}}><Icon size={15} />{label}</button>)}
        </div>
        </div>
        {!deep&&!workspace && <div className="wb-panel-content" key={renderedPanel}><ResourceRailContext.Provider value={mobile?null:{open:railOpen,setOpen:setRailOpen,target:railTarget}}><Suspense fallback={<Loading />}>{content(renderedPanel)}</Suspense></ResourceRailContext.Provider></div>}
      </aside>
      {(task.error || externalError) && (
        <div className="wb-toast" role="alert">
          <span>{task.error || externalError}</span>
          <IconButton
            title="关闭提示"
            onClick={() => {
              task.setError("");
              setExternalError("");
            }}
          >
            <X size={15} />
          </IconButton>
        </div>
      )}
      <button className="wb-native-return" onClick={() => host.closeNative()}>
        收起原生面板 <X size={16} />
      </button>
      {rp&&!mobile ? <RPStage host={host} hidden={focus} blocked={width<=1100&&!!(navigationVisible||shownPanel)} width={width-(width>1100?(leftVisible?leftWidth:0)+(panel&&!focus?rightWidth+(railVisible?180:0):0):0)} readingLayout={()=>switchLayout("novel")} run={task.run}/> : <ReadingPresentation host={host} chatStyle={mobile&&rp}/>}
      {popupPresence.value&&<ComposerPopovers key={popupPresence.value.kind+":"+(popupPresence.value.toolId||"")} host={host} popup={popupPresence.value} exiting={popupPresence.exiting} close={()=>setPopup(null)} settings={openSettings} activate={activateTool}/>}
      {workspacePresence.value&&<Suspense fallback={<Loading/>}><SettingsWorkspace host={host} page={workspacePresence.value.page} group={workspacePresence.value.group} initial={workspacePresence.value.initial} exiting={workspacePresence.exiting} onClose={()=>setWorkspace(null)}/></Suspense>}
      {(deep==='outline'||deep==='image-gen')&&<section className="wb-addon-editor" aria-label="附加功能完整编辑页"><header><strong>{deep==='outline'?'大纲 · 完整编辑':'生图 · 完整配置'}</strong><button onClick={()=>{if(beforeClose())setDeep(null);}}>返回工作台<X size={15}/></button></header><AddonWorkspace host={host} id={deep} active view="editor"/></section>}
      {deep && deep!=='outline' && deep!=='image-gen' && (
        <Dialog
          wide
          title={
            deep === "library"
              ? "角色管理"
              : `${deep in labels ? labels[deep as Resource] : "资源"} · 深度编辑`
          }
          onClose={() => {
            if (beforeClose()) setDeep(null);
          }}
        >
          <Suspense fallback={<Loading />}>
            {deep === "library" ? (
              <Characters host={host} management />
            ) : (
              content(deep, true)
            )}
          </Suspense>
        </Dialog>
      )}
      {helpPresence.value && (
        <Dialog title="快捷键" exiting={helpPresence.exiting} onClose={() => setHelp(false)}>
          <Shortcuts host={host}/>
        </Dialog>
      )}
      <Composer host={host} toolbar={toolbar} busy={snap.busy} open={openPopup} activate={activateTool} mobile={mobile}/>
    </>
  );
}
