import React, {
  Suspense,
  startTransition,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from "react";
import { lazyChunk } from "./ui/lazyChunk";
import {
  BookMarked,
  ScanLine,
  X,
  Activity,
  FileOutput,
  SlidersHorizontal,
  UserRound,
  UsersRound,
  Plug,
  ChevronLeft,
  ChevronRight,
  Eye,
  EyeOff,
  Pin,
  PinOff,
  ListTree,
  ImagePlus,
  Maximize2,
  Table2,
} from "./ui/icons";
import { resolveTool } from "./host/tools";
import { addonEnabled } from "./addons/catalog";
import { addonManager } from "./addons/runtime";
import { AddonTasks, MessageImageControls, ImageInputMode } from "./ui/AddonControls";
import AddonWorkspace from "./ui/AddonWorkspace";
import { ResourceRailContext } from "./ui/ResourcePicker";
import { ClickFeedback, usePresence } from "./ui/Motion";
import { Header } from "./ui/Header";
import { Composer } from "./ui/Composer";
import { ComposerOptions, OptionsPopover } from "./ui/StoryOptions";
import { useSidebarHover } from "./ui/useSidebarHover";
import { useScrollbars } from "./ui/useScrollbars";
import { Navigation } from "./ui/Navigation";
import { ComposerPopovers, type ComposerPopup } from "./ui/ComposerPopovers";
import { ReadingPresentation, ReadingSettings } from "./ui/Reading";
import { Operations, shortcutAction, shortcutHint } from "./host/operations";
import { Shortcuts } from "./ui/Shortcuts";
import { RPStage } from "./ui/RPStage";
import { MobileShell } from "./ui/MobileShell";
import { useMobileViewport } from "./ui/useMobileViewport";
import { useDatabase } from "./ui/useDatabase";
import type { LayoutMode } from "./ui/LayoutSwitcher";
import type { HostAdapter } from "./host/adapter";
import type { Panel, Resource, SettingsPage } from "./host/types";
import { useTask, IconButton, Dialog, Loading, useHostSlices, withoutChat } from "./ui/common";
import { bus, guards } from "./host/bus";
import { mdLive } from "./ui/md/MdField";
import { panelLabels } from "./host/labels";
import {
  available,
  bodyClasses,
  initial,
  lastAvailablePanel,
  leaves,
  leftVisible,
  navigationVisible,
  railVisible,
  reduce,
  sameEnv,
  shownPanel,
  type Action,
  type Env,
  type Sizes,
} from "./ui/layout/model";
const World = lazyChunk(() => import("./modules/World"));
const Characters = lazyChunk(() => import("./modules/Characters"));
const Resources = lazyChunk(() => import("./modules/Resources"));
const Trace = lazyChunk(() => import("./modules/Trace"));
const Database = lazyChunk(() => import("./modules/Database"));
const SettingsWorkspace = lazyChunk(() => import("./modules/SettingsWorkspace"));
export function beforeClose() {
  return guards.check();
}
/** Sidebar widths come from the --wb-*-size tokens, so CSS breakpoints stay the only source. */
type DeepTarget = Exclude<NonNullable<Panel>, "character" | "trace" | "export"> | "library";
/** Where the panel header's "独立深度编辑" leads for each panel; Trace and export have no larger view. */
function deepTarget(kind: NonNullable<Panel>): DeepTarget | null {
  if (kind === "character") return "library";
  return kind === "trace" || kind === "export" ? null : kind;
}
function readSizes(): Sizes {
  const style = getComputedStyle(document.documentElement);
  const px = (name: string, fallback: number) => parseFloat(style.getPropertyValue(name)) || fallback;
  return {
    left: px("--wb-left-size", 260),
    right: px("--wb-right-size", 460),
    rail: px("--wb-rail-size", 180),
  };
}
export default function App({
  host,
  trace,
  toolbar,
  onLayout,
}: {
  host: HostAdapter;
  trace: any;
  toolbar: HTMLElement;
  onLayout: (layout: LayoutMode) => void;
}) {
  const snap = useHostSlices(host, withoutChat),
    task = useTask(),
    [width, setWidth] = useState(window.innerWidth),
    [renderedPanel, setRenderedPanel] = useState<Panel>(null),
    [railTarget, setRailTarget] = useState<HTMLElement | null>(null),
    [externalError, setExternalError] = useState(""),
    // The entry the world panel opens on, at its portraits; n tells one request from the next.
    [worldEntry, setWorldEntry] = useState<{ title: string; n: number }>(),
    [optionsAnchor, setOptionsAnchor] = useState<HTMLElement | null>(null);
  const database = useDatabase(host);
  const prefs = host.prefs(),
    mobile = width < 1024,
    rp = prefs.layout === "rp";
  useMobileViewport(mobile);
  const env: Env = {
    mode: rp ? "rp" : "novel",
    mobile,
    width,
    addons: {
      export: addonEnabled(prefs, "record-export"),
      outline: addonEnabled(prefs, "outline"),
      "image-gen": addonEnabled(prefs, "image-gen"),
    },
    database: database.available,
  };
  const [layout, dispatch] = useReducer(reduce, null, () => initial(env, prefs.left));
  // Mode, device, width and add-on switches arrive as props of the render, so the model catches up
  // during render (React re-runs it before committing) instead of one stale frame later.
  const envAction: Action = { type: "env", env, prefLeft: prefs.left };
  const envChanged = !sameEnv(layout.env, env),
    modeChanged = envChanged && layout.env.mode !== env.mode,
    deviceChanged = envChanged && layout.env.mobile !== env.mobile;
  if (envChanged) dispatch(envAction);
  const s = envChanged ? reduce(layout, envAction) : layout;
  const { panel, chooser, focusId, deep, focus, popup, workspace, help, railOpen } = s;
  const sizes = useMemo(readSizes, [width]);
  const leftShown = leftVisible(s, sizes);
  const edgeHover = !mobile && prefs.edgeHover !== false;
  useLayoutEffect(() => mdLive.set(prefs.mdLive !== false), [prefs.mdLive]);
  useScrollbars();
  const hover = useSidebarHover(
    edgeHover && !focus && !workspace && !deep && !help && !document.querySelector("dialog[open]"),
    leftShown,
    !!panel,
    beforeClose,
  );
  const hovered = { left: hover.left, right: hover.right };
  const shown = shownPanel(s, hovered),
    lastAvailable = lastAvailablePanel(s),
    railShown = railVisible(s, hovered),
    navigationShown = navigationVisible(s, hovered, sizes);
  const manager = addonManager(host);
  useEffect(() => () => manager.dispose(), [manager]);
  // Board "RpDesktop": the top bar stays out of the scene until hovered, unless the user pins it.
  const topAuto = !mobile && rp && prefs.rpTopAuto !== false;
  const [topHot, setTopHot] = useState(false),
    [topFocus, setTopFocus] = useState(false),
    [layoutMenu, setLayoutMenu] = useState(false);
  if (modeChanged || deviceChanged) {
    hover.dismiss("left");
    hover.dismiss("right");
  }
  if (modeChanged) {
    setTopHot(false);
    setTopFocus(false);
  }
  const topCollapsed = topAuto && !topHot && !topFocus && !chooser && !layoutMenu;
  const topPointer = useRef(Infinity);
  useEffect(() => {
    if (!rp) return;
    setTopHot(topAuto && topPointer.current <= (topCollapsed ? 14 : 74));
    let hide: ReturnType<typeof setTimeout> | undefined;
    const clear = () => {
      if (hide) clearTimeout(hide);
      hide = undefined;
    };
    const leave = () => {
      if (!hide)
        hide = setTimeout(() => {
          setTopHot(false);
          if (!document.querySelector(".wb-top :focus-visible,.wb-rp-top-trigger:focus-visible"))
            setTopFocus(false);
          hide = undefined;
        }, 140);
    };
    const move = (event: PointerEvent) => {
      if (event.pointerType === "touch") return;
      topPointer.current = event.clientY;
      if (!topAuto) return;
      // The reveal strip and header form one hover region, without relying on display:contents hit boxes.
      if (event.clientY <= (topCollapsed ? 14 : 74)) {
        clear();
        setTopHot(true);
      } else leave();
    };
    document.addEventListener("pointermove", move);
    document.documentElement.addEventListener("pointerleave", leave);
    return () => {
      clear();
      document.removeEventListener("pointermove", move);
      document.documentElement.removeEventListener("pointerleave", leave);
    };
  }, [rp, topAuto, topCollapsed]);
  const selectedIds = useRef<Partial<Record<NonNullable<Panel>, string>>>({});
  const popupPresence = usePresence(popup),
    workspacePresence = usePresence(workspace),
    helpPresence = usePresence(help ? true : null);
  /** Applies a layout change once the leave guards agree, when it takes the user off the current view. */
  const act = (action: Action) => {
    const next = reduce(s, action);
    if (next === s || (leaves(s, next, shown) && !beforeClose())) return false;
    dispatch(action);
    return true;
  };
  const openPopup = useCallback((popup: ComposerPopup) => dispatch({ type: "toggle-popup", popup }), []);
  const closePopup = () => dispatch({ type: "popup", popup: null });
  const setChooser = (chooser: Resource | null) => dispatch({ type: "chooser", chooser });
  const openSettings = (page: SettingsPage, group?: string, initial?: string) =>
    act({ type: "settings", workspace: { page, group, initial } });
  const goPanel = (next: Panel, id?: string) => {
    const focusId = next ? (id ?? selectedIds.current[next] ?? "") : undefined;
    if (!act({ type: "panel", panel: next, id: focusId })) return;
    if (next && id !== undefined) selectedIds.current[next] = id;
    hover.dismiss("right");
  };
  /** The add-ons open their own full editor; every other larger view is a settings workspace page. */
  const goDeep = (next: DeepTarget, id = "") => {
    if (next === "outline" || next === "image-gen") act({ type: "deep", deep: next, id });
    else
      openSettings(next === "preset" ? "generation" : next === "library" ? "character" : next, undefined, id);
  };
  const closeDeep = () => act({ type: "deep", deep: null });
  const activateTool = (id: string, anchor: HTMLElement) => {
    closePopup();
    if (id === "wb:export") {
      goPanel("export");
      return;
    }
    if (id === "builtin:quick") {
      dispatch({ type: "popup", popup: { kind: "quick", anchor } });
      return;
    }
    if (id === "builtin:database") {
      goPanel(shown === "database" ? null : "database");
      return;
    }
    if (id === "builtin:options") {
      // A phone's tool sheet closes as this opens, so the settings sit over the composer instead.
      setOptionsAnchor(mobile ? document.getElementById("send_form")! : anchor);
      return;
    }
    const selectors: Record<string, string> = {
      "builtin:continue": "#option_continue",
      "builtin:regenerate": "#option_regenerate",
      "builtin:impersonate": "#option_impersonate",
      "builtin:attachment": "#attachFile",
    };
    if (selectors[id]) {
      void task.run(() => host.click(selectors[id]));
      return;
    }
    const item = resolveTool(id);
    if (!item || item.disabled) {
      host.report("此工具当前不可用，请检查插件是否启用。");
      return;
    }
    if (item.node.id === "option_toggle_AN" || item.node.id === "option_toggle_CFG") {
      dispatch({ type: "popup", popup: { kind: "tool", toolId: id, anchor } });
    } else {
      void task.run(() => item.node.click());
    }
  };
  const next = (kind: Resource) =>
    task.run(async () => {
      const items = snap.resources[kind];
      if (!items.length) {
        goPanel(kind);
        return;
      }
      const index = items.findIndex(
        (x) => x.id === (kind === "world" ? focusId || snap.current.world : snap.current[kind]),
      );
      const item = items[(index + 1) % items.length];
      if (kind === "world") goPanel(kind, item.id);
      else await host.select(kind, item.id);
    });
  const toggleLeft = () => {
    if (!mobile) hover.dismiss("left");
    act({ type: "toggle-left", hover: hovered, sizes });
  };
  const toggleRight = () => {
    if (hover.right && !panel) goPanel(shown);
    else goPanel(panel ? null : lastAvailable);
  };
  const toggleFocus = () => dispatch({ type: "focus" });
  // The edge arrows sit in the lane beside #chat's scrollbar. Releasing a scrollbar drag over an
  // arrow makes the browser fire a click on it, so they act only on presses that began on them.
  const pressedArrow = useRef<EventTarget | null>(null);
  const ownClick = (action: () => void) => ({
    onPointerDown: (e: React.PointerEvent) => {
      pressedArrow.current = e.currentTarget;
    },
    onClick: (e: React.MouseEvent) => {
      const own = e.detail === 0 || pressedArrow.current === e.currentTarget;
      pressedArrow.current = null;
      if (own) action();
    },
  });
  // Long-lived subscribers (operations, keyboard, bus) read the current render through this ref,
  // so they are registered once.
  const live = useRef({ s, act, goPanel, next, toggleLeft, toggleFocus });
  live.current = { s, act, goPanel, next, toggleLeft, toggleFocus };
  const [operations] = useState(() => {
    const ops = new Operations();
    for (const kind of ["connection", "preset", "world", "persona"] as Resource[]) {
      ops.register(`open.${kind}`, () => live.current.goPanel(kind));
      ops.register(`next.${kind}`, () => live.current.next(kind));
    }
    for (const kind of ["trace", "outline", "database", "image-gen", "character"] as const)
      ops.register(`open.${kind}`, () => live.current.goPanel(kind));
    ops.register("outline.editor", () => {
      if (addonEnabled(host.prefs(), "outline")) manager.api("outline").open("editor");
    });
    ops.register("outline.insert", () => {
      if (addonEnabled(host.prefs(), "outline"))
        void manager
          .ensure("outline")
          .then((r) => r.action("insert"))
          .catch((e) => host.report(e));
    });
    ops.register("outline.pause", () => {
      const r = manager.get("outline");
      if (r) void r.action(r.task().status === "running" ? "pause" : "resume").catch((e) => host.report(e));
    });
    ops.register("toggle.left", () => live.current.toggleLeft());
    ops.register("toggle.focus", () => live.current.toggleFocus());
    return ops;
  });
  useEffect(
    () =>
      bus.on("addon-open", ({ id, view }) => {
        // The record-export add-on's panel is "export", and it has no full editor.
        if (id === "record-export") live.current.goPanel("export");
        else if (view === "editor") live.current.act({ type: "deep", deep: id });
        else live.current.goPanel(id);
      }),
    [],
  );
  useEffect(() => bus.on("image-input", () => dispatch({ type: "image-input" })), []);
  useEffect(
    () =>
      bus.on("layout-menu", (open) => {
        setLayoutMenu(open);
        dispatch({ type: "layout-menu", open });
      }),
    [],
  );
  useEffect(() => bus.on("error", setExternalError), []);
  useEffect(() => {
    const resize = () => setWidth(window.innerWidth);
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);
  useEffect(() => {
    if (shown) {
      // The tab (or the sliding drawer) answers at once; the panel mounts without blocking that paint.
      // The desk's first open stays synchronous so the column never appears empty.
      if (renderedPanel || mobile) startTransition(() => setRenderedPanel(shown));
      else setRenderedPanel(shown);
      return;
    }
    const timer = setTimeout(() => setRenderedPanel(null), 220);
    return () => clearTimeout(timer);
  }, [shown]);
  useEffect(() => {
    if (!rp && !mobile) host.preference({ left: s.left });
  }, [s.left, rp, mobile]);
  const classes = {
    ...bodyClasses(s, hovered, sizes),
    // Focus mode hides the arrows and the reveal, so the lane would only cost reading width.
    "wb-edge-hover": edgeHover && !focus,
    "wb-rp-top-auto": topAuto,
    "wb-rp-top-collapsed": topCollapsed,
  };
  useLayoutEffect(() => {
    for (const [name, on] of Object.entries(classes)) document.body.classList.toggle(name, on);
  }, [Object.values(classes).join()]);
  useLayoutEffect(() => {
    const root = document.documentElement,
      query = matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      const dark = prefs.theme === "dark" || (prefs.theme === "system" && query.matches);
      if (dark) root.dataset.wbTheme = "dark";
      else delete root.dataset.wbTheme;
    };
    apply();
    if (prefs.theme !== "system") return () => delete root.dataset.wbTheme;
    query.addEventListener("change", apply);
    return () => {
      query.removeEventListener("change", apply);
      delete root.dataset.wbTheme;
    };
  }, [prefs.theme]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const { s } = live.current;
      if (e.isComposing || s.workspace) return;
      if (e.key === "Escape") {
        if (s.chooser) {
          dispatch({ type: "chooser", chooser: null });
          return;
        }
        if (s.focus) dispatch({ type: "focus", on: false });
        return;
      }
    };
    const shortcut = (e: KeyboardEvent) => {
      const { s } = live.current;
      if (
        e.defaultPrevented ||
        e.isComposing ||
        e.repeat ||
        e.getModifierState("AltGraph") ||
        s.workspace ||
        s.deep ||
        s.help ||
        document.querySelector("dialog[open]")
      )
        return;
      const prefs = host.prefs();
      if (prefs.shortcutsEnabled === false) return;
      const action = shortcutAction(e, prefs.shortcuts);
      if (action) {
        e.preventDefault();
        e.stopPropagation();
        operations.run(action);
      }
    };
    document.addEventListener("keydown", key);
    document.addEventListener("keydown", shortcut, true);
    return () => {
      document.removeEventListener("keydown", key);
      document.removeEventListener("keydown", shortcut, true);
    };
  }, [host, operations]);
  const content = (kind: Panel) =>
    kind === "world" ? (
      <World
        key={`world:${focusId}:${worldEntry?.n ?? 0}`}
        host={host}
        initial={focusId}
        entryTitle={worldEntry?.title}
        onSelection={(name) => {
          selectedIds.current.world = name;
        }}
      />
    ) : kind === "character" ? (
      <Characters
        host={host}
        onManage={(group) => (group ? openSettings("character", group) : goDeep("library"))}
      />
    ) : kind === "export" ? (
      <AddonWorkspace host={host} id="record-export" active={shown === "export" && !workspace && !deep} />
    ) : kind === "outline" || kind === "image-gen" ? (
      <AddonWorkspace host={host} id={kind} active={shown === kind && !workspace && !deep} />
    ) : kind === "trace" ? (
      <Trace host={host} trace={trace} />
    ) : kind === "database" ? (
      <Database
        host={host}
        initial={focusId}
        onSelection={(key) => {
          selectedIds.current.database = key;
        }}
      />
    ) : kind ? (
      <Resources
        key={`${kind}:${focusId}`}
        host={host}
        kind={kind}
        onSelection={(id) => {
          selectedIds.current[kind] = id;
        }}
        initial={focusId}
      />
    ) : null;
  return (
    <>
      <ClickFeedback />
      <AddonTasks host={host} />
      <MessageImageControls host={host} />
      <ImageInputMode host={host} />
      {mobile && (
        <MobileShell
          host={host}
          snap={snap}
          rp={rp}
          left={leftShown}
          panel={shown}
          chooser={chooser}
          setChooser={setChooser}
          goPanel={goPanel}
          toggleLeft={toggleLeft}
          closeDrawers={() => act({ type: "close-drawers" })}
          onLayout={onLayout}
          settings={openSettings}
          open={openPopup}
          activate={activateTool}
          select={(kind, id, enabled) => {
            void task.run(() => (kind === "world" ? host.toggleBook(id, enabled) : host.select(kind, id)));
          }}
          focus={focus}
          toggleFocus={toggleFocus}
        />
      )}
      {!mobile && (
        <div
          className="wb-header-shell"
          inert={rp && (focus || topCollapsed)}
          onPointerLeave={(e) => {
            if (e.pointerType !== "touch" && !e.currentTarget.querySelector(":focus-visible"))
              setTopFocus(false);
          }}
          onFocusCapture={() => setTopFocus(true)}
          onBlurCapture={(e) => {
            if (!e.currentTarget.contains(e.relatedTarget as Node)) setTopFocus(false);
          }}
        >
          <Header
            snap={snap}
            panel={shown}
            chooser={chooser}
            setChooser={setChooser}
            goPanel={goPanel}
            model={host.model()}
            focus={toggleFocus}
            focused={focus}
            actions={
              rp ? (
                <button
                  className={`wb-top-action wb-top-pin ${!topAuto ? "is-active" : ""}`}
                  aria-label="固定顶栏"
                  title={topAuto ? "固定顶栏" : "取消固定 · 鼠标悬浮显示"}
                  aria-pressed={!topAuto}
                  onClick={() => {
                    setTopHot(true);
                    setTopFocus(!!document.querySelector(".wb-top-pin:focus-visible"));
                    host.preference({ rpTopAuto: !topAuto });
                  }}
                >
                  {topAuto ? <PinOff size={20} /> : <Pin size={20} />}
                </button>
              ) : undefined
            }
            focusShortcut={
              host.prefs().shortcutsEnabled === false
                ? ""
                : shortcutHint("toggle.focus", host.prefs().shortcuts)
            }
            select={(kind, id, enabled) =>
              task.run(async () => {
                if (kind === "world") await host.toggleBook(id, enabled);
                else await host.select(kind, id);
              })
            }
          />
        </div>
      )}
      {!mobile && rp && (
        <>
          <button
            className="wb-rp-visibility wb-icon"
            aria-label={focus ? "显示界面" : "隐藏界面"}
            title={focus ? "显示界面" : "隐藏界面"}
            aria-pressed={focus}
            onClick={toggleFocus}
          >
            {focus ? <Eye size={20} /> : <EyeOff size={20} />}
          </button>
          {topAuto && !focus && (
            <button
              className="wb-rp-top-trigger"
              aria-label="显示顶栏"
              tabIndex={topCollapsed ? 0 : -1}
              onFocus={() => setTopFocus(true)}
              onBlur={(e) => {
                if (!(e.relatedTarget as Element)?.closest?.(".wb-top")) setTopFocus(false);
              }}
              onClick={() => {
                setTopHot(true);
                setTopFocus(true);
                requestAnimationFrame(() => document.querySelector<HTMLButtonElement>(".wb-pill")?.focus());
              }}
            >
              <span />
            </button>
          )}
        </>
      )}
      {!mobile && !rp && (
        <div className="wb-reading-bar">
          <nav className="wb-reading-crumbs" aria-label="当前位置">
            <span>{snap.groupName || snap.character?.name || "Noval"}</span>
            <ChevronRight size={12} aria-hidden="true" />
            <span className="wb-chat-name" title={snap.chatName}>
              {snap.chatName || "开始一段新的故事"}
            </span>
          </nav>
          <span className="wb-grow" />
          {focus && (
            <button
              className="wb-exit-focus"
              title="退出专注"
              aria-label="退出专注"
              aria-pressed="true"
              onClick={toggleFocus}
            >
              <ScanLine size={14} />
              退出专注
            </button>
          )}
          <ReadingSettings host={host} />
        </div>
      )}
      {!mobile && (
        <nav
          className={`wb-edge-nav ${focus ? "is-hidden" : ""}`}
          style={
            {
              // Beside an open column, plus the gap a floating card keeps from the window edge.
              "--wb-edge-left": navigationShown
                ? `calc(${sizes.left}px + var(--wb-edge-gap-left, 0px))`
                : "0px",
              "--wb-edge-right":
                shown && !focus
                  ? `calc(${sizes.right + (railShown ? sizes.rail : 0)}px + var(--wb-edge-gap-right, 0px))`
                  : "0px",
            } as React.CSSProperties
          }
          inert={focus}
          aria-hidden={focus}
          aria-label="边栏操作"
        >
          <button
            className="wb-edge-arrow wb-edge-left"
            aria-label={hover.left && !leftShown ? "固定左边栏" : leftShown ? "收纳左边栏" : "展开左边栏"}
            title={`${hover.left && !leftShown ? "固定左边栏" : leftShown ? "收纳左边栏" : "展开左边栏"}${host.prefs().shortcutsEnabled !== false && shortcutHint("toggle.left", host.prefs().shortcuts) ? " · " + shortcutHint("toggle.left", host.prefs().shortcuts) : ""}`}
            aria-expanded={navigationShown}
            {...ownClick(toggleLeft)}
          >
            {navigationShown ? <ChevronLeft size={28} /> : <ChevronRight size={28} />}
          </button>
          {/* The one key for both directions: it stays beside a pinned panel to fold it again. */}
          <button
            className="wb-edge-arrow wb-edge-right"
            aria-label={hover.right && !panel ? "固定右边栏" : panel ? "收纳右边栏" : "角色与资源侧栏"}
            title={hover.right && !panel ? "固定右边栏" : panel ? "收纳右边栏" : "角色与资源侧栏"}
            aria-expanded={!!shown}
            {...ownClick(toggleRight)}
          >
            {shown ? <ChevronRight size={28} /> : <ChevronLeft size={28} />}
          </button>
        </nav>
      )}
      <Navigation
        host={host}
        snap={snap}
        visible={navigationShown}
        mobile={mobile}
        settings={openSettings}
        open={openPopup}
        help={() => dispatch({ type: "help", open: true })}
        run={(fn) =>
          task.run(async () => {
            await fn();
            if (mobile) dispatch({ type: "left", open: false });
          })
        }
      />
      <aside
        className={`wb-right ${shown && (mobile || !focus) ? "is-open" : ""}`}
        inert={!shown || (focus && !mobile)}
        aria-hidden={!shown || (focus && !mobile)}
        aria-label="角色与资源"
        style={{ "--wb-panel-rail": `${railShown ? sizes.rail : 0}px` } as React.CSSProperties}
      >
        <header className="wb-panel-head">
          <div className="wb-panel-tabs" role="toolbar" aria-label="右栏面板">
            {(
              [
                ["character", UsersRound],
                ["world", BookMarked],
                ["preset", SlidersHorizontal],
                ["connection", Plug],
                ["persona", UserRound],
                ["trace", Activity],
                ["export", FileOutput],
                ["outline", ListTree],
                ["database", Table2],
                ["image-gen", ImagePlus],
              ] as const
            )
              .filter(([kind]) => available(env, kind))
              .map(([kind, Icon]) => (
                <React.Fragment key={kind}>
                  {kind === "trace" && <span className="wb-panel-tab-gap" aria-hidden="true" />}
                  <button
                    className={`wb-panel-tab ${shown === kind ? "is-active" : ""}`}
                    aria-pressed={shown === kind}
                    aria-label={panelLabels[kind]}
                    title={panelLabels[kind]}
                    onClick={() => goPanel(kind)}
                  >
                    <Icon size={16} />
                    {shown === kind && <span className="wb-panel-tab-label">{panelLabels[kind]}</span>}
                  </button>
                </React.Fragment>
              ))}
          </div>
          {shown && deepTarget(shown) && (
            <button
              className="wb-panel-tool wb-panel-expand"
              aria-label="独立深度编辑"
              title="独立深度编辑"
              onClick={() => {
                const target = deepTarget(shown)!;
                goDeep(target, target === "library" ? "" : (selectedIds.current[shown] ?? ""));
              }}
            >
              <Maximize2 size={15} />
            </button>
          )}
          <button
            className="wb-panel-close"
            aria-label="关闭右栏"
            title="关闭右栏"
            onClick={() => (panel ? goPanel(null) : hover.dismiss("right"))}
          >
            <X size={16} />
          </button>
        </header>
        <div className="wb-panel-body">
          <aside
            id="wb-resource-rail"
            ref={setRailTarget}
            className={`wb-resource-rail ${railShown ? "is-open" : ""}`}
            inert={!railShown}
            aria-hidden={!railShown}
            aria-label="资源列表与角色信息"
          />
          {!deep && !workspace && (
            <div className="wb-panel-content" key={renderedPanel}>
              <ResourceRailContext.Provider
                value={
                  mobile
                    ? null
                    : {
                        open: railOpen,
                        setOpen: (open) => dispatch({ type: "rail", open }),
                        target: railTarget,
                      }
                }
              >
                <Suspense fallback={<Loading />}>{content(renderedPanel)}</Suspense>
              </ResourceRailContext.Provider>
            </div>
          )}
        </div>
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
      {rp ? (
        <RPStage
          host={host}
          hidden={focus}
          blocked={!mobile && width <= 1100 && !!(navigationShown || shown)}
          width={width}
          readingLayout={() => onLayout("novel")}
          openPortraits={(book, title) => {
            setWorldEntry({ title, n: Date.now() });
            goPanel("world", book);
          }}
          run={task.run}
          mobile={mobile}
        />
      ) : (
        <ReadingPresentation host={host} />
      )}
      {popupPresence.value && (
        <ComposerPopovers
          key={popupPresence.value.kind + ":" + (popupPresence.value.toolId || "")}
          host={host}
          popup={popupPresence.value}
          exiting={popupPresence.exiting}
          close={closePopup}
          settings={openSettings}
          activate={activateTool}
        />
      )}
      {workspacePresence.value && (
        <Suspense fallback={<Loading />}>
          <SettingsWorkspace
            host={host}
            page={workspacePresence.value.page}
            group={workspacePresence.value.group}
            initial={workspacePresence.value.initial}
            exiting={workspacePresence.exiting}
            onClose={() => dispatch({ type: "close-settings" })}
            mobile={mobile}
          />
        </Suspense>
      )}
      {deep && (
        <section className="wb-addon-editor" aria-label="附加功能完整编辑页">
          <header>
            <strong>{deep === "outline" ? "大纲 · 完整编辑" : "生图 · 完整配置"}</strong>
            <button onClick={closeDeep}>
              返回工作台
              <X size={15} />
            </button>
          </header>
          <AddonWorkspace host={host} id={deep} active view="editor" />
        </section>
      )}
      {helpPresence.value && (
        <Dialog
          title="快捷键"
          exiting={helpPresence.exiting}
          onClose={() => dispatch({ type: "help", open: false })}
        >
          <Shortcuts host={host} />
        </Dialog>
      )}
      {!rp && <ComposerOptions host={host} mobile={mobile} />}
      {optionsAnchor && (
        <OptionsPopover host={host} anchor={optionsAnchor} onClose={() => setOptionsAnchor(null)} />
      )}
      <Composer
        host={host}
        toolbar={toolbar}
        busy={snap.busy}
        open={openPopup}
        activate={activateTool}
        mobile={mobile}
      />
    </>
  );
}
