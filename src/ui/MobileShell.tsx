import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  Activity,
  BookMarked,
  BookOpen,
  ChevronDown,
  ChevronRight,
  Expand,
  Eye,
  EyeOff,
  Folder,
  Menu,
  MenuDrawer,
  MoreHorizontal,
  PanelsTopLeft,
  Plug,
  ScanLine,
  Plus,
  Settings,
  SlidersHorizontal,
  Theater,
  UserRound,
  Users,
  WandSparkles,
  X,
} from "./icons";
import type { HostAdapter } from "../host/adapter";
import type { HostSnapshot, Panel, Resource, SettingsPage } from "../host/types";
import type { LayoutMode } from "./LayoutSwitcher";
import type { ComposerPopup } from "./ComposerPopovers";
import { ResourceControls } from "./Header";
import { resourceLabels } from "../host/labels";
import { ReadingSettings } from "./Reading";
import { OptionsSheetList } from "./StoryOptions";
import { toolIcon } from "./ToolIcon";
import { useComposerTools } from "./useTools";
import { useDatabase } from "./useDatabase";
import { usePresence } from "./Motion";
import { bus } from "../host/bus";

import { useComposerPage } from "./mobile/useComposerPage";
import { useOverlayFocus } from "./mobile/useOverlayFocus";
import { useMessageGestures } from "./mobile/useMessageGestures";
import { useDrawerGestures } from "./mobile/useDrawerGestures";
import { useSheetGestures } from "./mobile/useSheetGestures";
import type { MobileSheet as Sheet } from "./mobile/types";
import { MessageActionButton } from "./MessageActionButton";
const resourceIcons = { connection: Plug, preset: SlidersHorizontal, world: BookMarked, persona: UserRound };
export function MobileShell({
  host,
  snap,
  rp,
  left,
  panel,
  chooser,
  setChooser,
  goPanel,
  toggleLeft,
  closeDrawers,
  onLayout,
  settings,
  open,
  activate,
  select,
  focus,
  toggleFocus,
}: {
  host: HostAdapter;
  snap: HostSnapshot;
  rp: boolean;
  left: boolean;
  panel: Panel;
  chooser: Resource | null;
  setChooser: (kind: Resource | null) => void;
  goPanel: (panel: Panel, id?: string) => void;
  toggleLeft: () => void;
  closeDrawers: () => void;
  onLayout: (mode: LayoutMode) => void;
  settings: (page: SettingsPage, group?: string) => void;
  open: (popup: ComposerPopup) => void;
  activate: (id: string, anchor: HTMLElement) => void;
  select: (kind: Resource, id: string | string[], on: boolean) => void;
  /** Focus mode: Noval keeps only the reading and the composer; RP hides every pane. */
  focus: boolean;
  toggleFocus: () => void;
}) {
  const [sheet, setSheet] = useState<Sheet>(null),
    [editor, setEditor] = useState(false),
    [length, setLength] = useState(0);
  const presence = usePresence(sheet),
    sheetRef = useRef<HTMLDivElement>(null),
    input = document.getElementById("send_textarea") as HTMLTextAreaElement,
    form = document.getElementById("send_form")!,
    items = document.getElementById("nonQRFormItems")!;
  const latest = useRef({ left, panel, editor, sheet });
  latest.current = { left, panel, editor, sheet };
  const close = () => {
      setSheet(null);
      setChooser(null);
    },
    setEditing = (value: boolean) => {
      setSheet(null);
      setChooser(null);
      setEditor(value);
    };
  const headerRef = useRef<HTMLElement>(null);
  const { edit, letGo, grip } = useComposerPage(rp, editor, latest, headerRef, setEditing);
  const presentation = host.rpPresentation();
  // Novel names the story; RP names the scene, falling back to the story when the card has none.
  const scene = (key: string) => {
      const value = presentation.scene?.[key];
      return typeof value === "string" || typeof value === "number" ? String(value) : "";
    },
    who = snap.character?.name || snap.groupName || "选择角色",
    title = (rp && scene("location")) || snap.chatName || who,
    subtitle =
      rp && scene("location")
        ? [scene("time"), scene("weather")].filter(Boolean).join(" · ") || who
        : snap.chatName
          ? `${who} · ${snap.messages.length} 层`
          : "开始一段新的故事";
  const worlds = snap.resources.world.filter((x) => x.active),
    summary = [
      snap.resources.preset.find((x) => x.id === snap.current.preset)?.name,
      worlds.length ? worlds[0].name + (worlds.length > 1 ? ` +${worlds.length - 1}` : "") : "",
    ]
      .filter(Boolean)
      .join(" · ");
  // Every class written on <body> makes SillyTavern's keyboard.js rescan the whole page, so these
  // change only when their value does and are removed only on unmount.
  useLayoutEffect(() => {
    document.body.classList.toggle("wb-mobile-busy", snap.busy);
    document.body.classList.toggle("wb-mobile-offline", !snap.online);
  }, [snap.busy, snap.online]);
  useLayoutEffect(() => () => document.body.classList.remove("wb-mobile-busy", "wb-mobile-offline"), []);
  useEffect(() => {
    setSheet(null);
    setEditor(false);
    letGo();
  }, [rp, snap.chatName, snap.character?.id]);
  useEffect(() => {
    // A draft taller than the pill scrolls under the finger; a short one lets the pill be pulled up.
    const changed = () => {
      setLength(input.value.length);
      input.toggleAttribute("data-wb-overflow", input.scrollHeight > input.clientHeight + 1);
    };
    changed();
    input.addEventListener("input", changed);
    const image = () => {
      setSheet(null);
      setEditor(false);
      closeDrawers();
    };
    const off = [
      bus.on("image-compose", image),
      // The story options open over whatever is reading, never over a drawer or the editor.
      bus.on("story-options", () => {
        const now = latest.current;
        if (host.options.state.items.length && !now.left && !now.panel && !now.editor && !now.sheet)
          setSheet("options");
      }),
      // A floor picked in the outline is also selected, so its tools are one tap away.
      bus.on("floor-jump", (id) => {
        const chat = document.getElementById("chat")!;
        chat.querySelectorAll(".wb-mobile-actions").forEach((n) => n.classList.remove("wb-mobile-actions"));
        chat.querySelector(`.mes[mesid="${id}"]`)?.classList.add("wb-mobile-actions");
      }),
    ];
    return () => {
      input.removeEventListener("input", changed);
      input.removeAttribute("data-wb-overflow");
      off.forEach((f) => f());
    };
  }, []);
  const database = useDatabase(host);
  const { tools, disabled: toolDisabled } = useComposerTools(host, snap.busy);
  useOverlayFocus(left, panel, !!sheet, sheetRef, close, closeDrawers);
  useMessageGestures(rp, setSheet);
  useDrawerGestures(rp, latest, toggleLeft, goPanel, closeDrawers);
  useSheetGestures(sheetRef, headerRef, presence, latest, close, setSheet);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape" && editor) {
        e.preventDefault();
        edit(false);
      }
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [editor]);
  const resources = (
    <ResourceControls
      snap={snap}
      panel={panel}
      chooser={chooser}
      setChooser={setChooser}
      goPanel={(next, id) => {
        close();
        goPanel(next, id);
      }}
      select={select}
      model={host.model()}
    />
  );
  const goSettings = (page: SettingsPage) => {
    close();
    settings(page);
  };
  return (
    <>
      <header
        ref={headerRef}
        className="wb-mobile-header wb-ui"
        inert={left || !!panel || !!sheet || editor || (focus && !rp)}
      >
        <button
          className="wb-mobile-nav"
          aria-label="打开大纲与导航"
          aria-expanded={left}
          onClick={toggleLeft}
        >
          <MenuDrawer size={21} />
        </button>
        {/* RP: the scene's name is the way to the session menu (as is pulling the header down). */}
        {rp ? (
          <button
            className="wb-mobile-title"
            aria-label="打开会话管理"
            aria-expanded={sheet === "management"}
            onClick={() => setSheet("management")}
          >
            <strong>{title}</strong>
            <small>{subtitle}</small>
          </button>
        ) : (
          <>
            <button
              className="wb-mobile-management"
              aria-label="打开会话管理"
              aria-expanded={sheet === "management"}
              onClick={() => setSheet("management")}
            >
              <MoreHorizontal size={21} strokeWidth={2.4} />
            </button>
            <div className="wb-mobile-title">
              <strong>{title}</strong>
              <small>{subtitle}</small>
            </div>
          </>
        )}
        <button
          className="wb-mobile-person"
          aria-label={rp ? (focus ? "显示界面" : "隐藏界面") : "打开角色与 Trace"}
          aria-pressed={rp ? focus : undefined}
          aria-expanded={rp ? undefined : !!panel}
          onClick={() => (rp ? toggleFocus() : goPanel("character"))}
        >
          {rp ? (
            focus ? (
              <Eye size={20} />
            ) : (
              <EyeOff size={20} />
            )
          ) : snap.character?.image ? (
            <span className="wb-mobile-face">
              <img src={snap.character.image} alt="" />
            </span>
          ) : (
            <span className="wb-avatar-fallback">N</span>
          )}
        </button>
      </header>
      <button
        className={`wb-mobile-shade ${left || panel ? "is-open" : ""}`}
        aria-label="收起边栏"
        aria-hidden={!(left || panel)}
        tabIndex={left || panel ? 0 : -1}
        onClick={closeDrawers}
      />
      {/* The panel closes from the end of its own tab row. */}
      {left && (
        <>
          <span className="wb-mobile-drawer-title wb-ui">大纲与导航</span>
          <button
            className="wb-mobile-drawer-close is-left wb-ui"
            aria-label="关闭边栏"
            onClick={closeDrawers}
          >
            <X size={20} />
          </button>
        </>
      )}
      {/* Noval's quick configuration: what is connected, then one key per resource into its
          right-panel page (switching happens there). */}
      {!rp && (
        <div className="wb-mobile-config wb-ui" inert={left || !!panel || !!sheet || editor || focus}>
          <span className="wb-mobile-status">
            <i className={`wb-dot ${snap.online ? "online" : ""}`} />
            <strong>
              {snap.resources.connection.find((x) => x.id === snap.current.connection)?.name ||
                host.model() ||
                "未连接"}
            </strong>
            {!!summary && <small>{summary}</small>}
          </span>
          <div className="wb-mobile-keys" role="group" aria-label="快捷配置">
            {(Object.keys(resourceLabels) as Resource[]).map((kind) => {
              const Icon = resourceIcons[kind],
                value =
                  snap.resources[kind].find((x) => x.id === snap.current[kind])?.name ||
                  (kind === "connection" ? host.model() : "未选择"),
                count = kind === "world" ? worlds.length : 0;
              return (
                <button
                  key={kind}
                  aria-label={`${resourceLabels[kind]}：${kind === "world" ? `${count} 本已启用` : value}`}
                  aria-pressed={panel === kind}
                  onClick={() => {
                    close();
                    goPanel(kind);
                  }}
                >
                  <Icon size={19} />
                  {count > 0 && <b>{count}</b>}
                </button>
              );
            })}
          </div>
        </div>
      )}
      {!rp && focus && !editor && (
        <button
          type="button"
          className="wb-mobile-focus-exit wb-ui"
          aria-label="退出专注"
          onClick={toggleFocus}
        >
          <ScanLine size={15} />
          退出专注
        </button>
      )}
      {createPortal(
        <button
          type="button"
          className="wb-mobile-plus wb-ui"
          aria-label="打开输入工具"
          aria-expanded={sheet === "tools"}
          onClick={() => setSheet(sheet === "tools" ? null : "tools")}
        >
          <Plus size={23} />
        </button>,
        items,
      )}
      {createPortal(
        <>
          <div className="wb-mobile-editor-heading wb-ui" {...grip}>
            <button aria-label="返回聊天，保留草稿" onClick={() => edit(false)}>
              <ChevronDown size={22} />
            </button>
            <strong>
              {document.body.classList.contains("wb-image-input-mode") ? "生图提示词" : "编辑草稿"}
            </strong>
            <small>{length} 字</small>
          </div>
        </>,
        form,
      )}
      {presence.value && (
        <>
          <button
            className="wb-mobile-sheet-shade"
            aria-label="关闭工具面板"
            data-wb-exiting={presence.exiting || undefined}
            inert={presence.exiting}
            onClick={close}
          />
          <div
            ref={sheetRef}
            className={`wb-mobile-sheet wb-ui ${presence.value === "management" ? "is-management" : ""}`}
            role="dialog"
            aria-modal="true"
            aria-label={
              sheet === "management"
                ? "会话管理"
                : sheet === "tools"
                  ? "输入工具"
                  : sheet === "options"
                    ? "选择剧情选项"
                    : "最新回复操作"
            }
            inert={presence.exiting}
            data-wb-exiting={presence.exiting || undefined}
          >
            <span className="wb-mobile-sheet-grip" aria-hidden="true" />
            <header>
              <strong>
                {presence.value === "management"
                  ? "会话管理"
                  : presence.value === "tools"
                    ? "输入工具"
                    : presence.value === "options"
                      ? "剧情选项"
                      : "最新回复"}
              </strong>
              <button aria-label="关闭工具面板" onClick={close}>
                <X size={21} />
              </button>
            </header>
            {presence.value === "management" ? (
              <>
                <span className="wb-mobile-sheet-caption" aria-hidden="true">
                  布局模式
                </span>
                <div className="wb-mobile-mode-row" role="group" aria-label="工作台模式">
                  {(
                    [
                      ["novel", "Noval", BookOpen],
                      ["rp", "RP", Theater],
                      ["native", "原生", PanelsTopLeft],
                    ] as const
                  ).map(([mode, name, Icon]) => (
                    <button
                      key={mode}
                      aria-pressed={mode === (rp ? "rp" : "novel")}
                      onClick={() => {
                        close();
                        onLayout(mode);
                      }}
                    >
                      <Icon size={17} />
                      {name}
                    </button>
                  ))}
                </div>
                <div className="wb-mobile-sheet-list">
                  {!rp && (
                    <button
                      aria-pressed={focus}
                      onClick={() => {
                        close();
                        toggleFocus();
                      }}
                    >
                      <ScanLine size={19} />
                      专注模式
                      <ChevronRight size={15} />
                    </button>
                  )}
                  <button
                    onClick={() => {
                      close();
                      goPanel("character");
                    }}
                  >
                    <Users size={19} />
                    角色与资源
                    <ChevronRight size={15} />
                  </button>
                  <button
                    onClick={() => {
                      close();
                      goPanel("trace");
                    }}
                  >
                    <Activity size={19} />
                    Trace
                    <ChevronRight size={15} />
                  </button>
                  <button
                    onClick={(e) => {
                      close();
                      open({ kind: "files", anchor: e.currentTarget });
                    }}
                  >
                    <Folder size={19} />
                    聊天文件
                    <ChevronRight size={15} />
                  </button>
                  <button onClick={() => goSettings("settings")}>
                    <Settings size={19} />
                    用户设置
                    <ChevronRight size={15} />
                  </button>
                  <ReadingSettings host={host} row />
                </div>
              </>
            ) : presence.value === "options" ? (
              <OptionsSheetList
                host={host}
                rp={rp}
                onDone={close}
                onConfig={(anchor) => {
                  close();
                  activate("builtin:options", anchor);
                }}
              />
            ) : presence.value === "tools" ? (
              <>
                {rp && <div className="wb-mobile-tool-config">{resources}</div>}
                <div className="wb-mobile-tool-grid">
                  {tools.map((tool) => {
                    const Icon = toolIcon(tool.id, tool.label);
                    return (
                      <button
                        key={tool.id}
                        data-wb-busy={(tool.id === "builtin:database" && database.filling) || undefined}
                        disabled={toolDisabled(tool.id)}
                        onClick={(e) => {
                          close();
                          activate(tool.id, e.currentTarget);
                        }}
                      >
                        <Icon size={21} />
                        <span>{tool.label}</span>
                      </button>
                    );
                  })}
                  <button
                    onClick={(e) => {
                      close();
                      open({ kind: "menu", anchor: e.currentTarget });
                    }}
                  >
                    <Menu size={21} />
                    聊天菜单
                  </button>
                  <button
                    onClick={(e) => {
                      close();
                      open({ kind: "tools", anchor: e.currentTarget });
                    }}
                  >
                    <WandSparkles size={21} />
                    扩展工具
                  </button>
                  <button onClick={() => edit(true)}>
                    <Expand size={21} />
                    全屏输入
                  </button>
                </div>
              </>
            ) : (
              <div className="wb-mobile-sheet-list">
                <MessageActionButton
                  node={presence.value as HTMLElement}
                  action="mes_edit"
                  busy={snap.busy}
                  onInvoke={close}
                  size={19}
                />
                <MessageActionButton
                  node={presence.value as HTMLElement}
                  action="mes_copy"
                  onInvoke={close}
                  size={19}
                />
                <div className="wb-mobile-candidates">
                  <MessageActionButton
                    node={presence.value as HTMLElement}
                    action="swipe_left"
                    busy={snap.busy}
                    onInvoke={close}
                    size={20}
                  />
                  <MessageActionButton
                    node={presence.value as HTMLElement}
                    action="swipe_right"
                    busy={snap.busy}
                    onInvoke={close}
                    size={20}
                  />
                </div>
                {(presence.value as HTMLElement).querySelector(".wb-image-message-button") && (
                  <MessageActionButton
                    node={presence.value as HTMLElement}
                    action="wb-image-message-button"
                    busy={snap.busy}
                    onInvoke={close}
                    size={19}
                  />
                )}
                {(presence.value as HTMLElement).querySelector(".wb-image-insert-button") && (
                  <MessageActionButton
                    node={presence.value as HTMLElement}
                    action="wb-image-insert-button"
                    busy={snap.busy}
                    onInvoke={close}
                    size={19}
                  />
                )}
                <button
                  onClick={() => {
                    close();
                    goPanel("trace");
                  }}
                >
                  <Activity size={19} />
                  Trace
                </button>
              </div>
            )}
          </div>
        </>
      )}
    </>
  );
}
