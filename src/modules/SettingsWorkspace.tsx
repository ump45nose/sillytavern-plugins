import { Suspense, useEffect, useRef, useState } from "react";
import { lazyChunk } from "../ui/lazyChunk";
import {
  ArrowLeft,
  BookMarked,
  ChevronRight,
  Image,
  Plug,
  Puzzle,
  Settings,
  SlidersHorizontal,
  Table2,
  TextCursorInput,
  UserRound,
  UsersRound,
  X,
} from "../ui/icons";
import type { HostAdapter } from "../host/adapter";
import type { SettingsPage } from "../host/types";
import { Dialog, Loading, Notice, useTask, useHostSlices, withoutChat } from "../ui/common";
import { ReadingSettings } from "../ui/Reading";
import { nativePages } from "./NativeSettings";
import { bus, guards } from "../host/bus";
import { settingsLabels } from "../host/labels";
import { useDatabase } from "../ui/useDatabase";
const ComponentSettings = lazyChunk(() => import("./ComponentSettings")),
  WorldBindings = lazyChunk(() => import("./WorldBindings")),
  Groups = lazyChunk(() => import("./Groups")),
  PersonaManager = lazyChunk(() => import("./PersonaManager")),
  ResourceManager = lazyChunk(() => import("./ResourceManager")),
  Characters = lazyChunk(() => import("./Characters")),
  Database = lazyChunk(() => import("./Database"));
const AddonSettings = lazyChunk(() => import("./AddonSettings"));
const ToolSettings = lazyChunk(() => import("./ToolSettings")),
  StartupDiagnostics = lazyChunk(() => import("./StartupDiagnostics"));
export const settingsPages = (
  [
    ["generation", SlidersHorizontal],
    ["connection", Plug],
    ["formatting", TextCursorInput],
    ["world", BookMarked],
    ["settings", Settings],
    ["background", Image],
    ["extensions", Puzzle],
    ["persona", UserRound],
    ["character", UsersRound],
    ["database", Table2],
  ] as const
).map(([id, Icon]) => [id, settingsLabels[id], Icon] as const);
export default function SettingsWorkspace({
  host,
  page: initial,
  group: initialGroup,
  initial: resourceInitial,
  onClose,
  exiting,
  mobile = false,
}: {
  host: HostAdapter;
  page: SettingsPage;
  group?: string;
  initial?: string;
  onClose: () => void;
  exiting?: boolean;
  /** Phones navigate in two levels: every page's groups as one list, then a single group with back. */
  mobile?: boolean;
}) {
  // Subscribed for the re-render: host state such as pending resource actions is read directly.
  useHostSlices(host, withoutChat);
  const database = useDatabase(host),
    // 数据库 is the database plug-in's page, listed while the plug-in is installed.
    pages = settingsPages.filter(([id]) => id !== "database" || database.available),
    [closing, setClosing] = useState(false),
    [extensionId, setExtensionId] = useState("");
  const close = () => {
    if (host.resourceAction) return;
    if (host.dirtyDraftKeys().length) setClosing(true);
    else onClose();
  };
  const [positions, setPositions] = useState<Record<string, string>>(() =>
    resourceInitial ? { [initial === "generation" ? "preset" : initial]: resourceInitial } : {},
  );
  const [page, setPage] = useState(initial),
    [group, setGroup] = useState(initialGroup || ""),
    [listing, setListing] = useState(mobile && !initialGroup),
    [selected, setSelected] = useState<Record<string, string[]>>({}),
    task = useTask(),
    ref = useRef<HTMLDialogElement>(null);
  useEffect(
    () =>
      bus.on("settings-group", ({ group, extension }) => {
        setGroup(group);
        setExtensionId(extension || "");
        setListing(false);
      }),
    [],
  );
  const resource = page === "generation" ? "preset" : page === "connection" || page === "world" ? page : null;
  const groupsOf = (page: SettingsPage) =>
    page === "world"
      ? ["条目编辑", "绑定与全局设置"]
      : page === "generation"
        ? ["参数与预设", "提示词", "高级参数"]
        : page === "connection"
          ? ["API 与连接管理"]
          : page === "persona"
            ? ["身份编辑", "全局偏好"]
            : page === "character"
              ? ["全部角色", "群组"]
              : page === "database"
                ? ["表格数据"]
                : [
                    ...nativePages[page].sections.map((s) => s.label),
                    ...(page === "settings"
                      ? ["常用工具", "加载诊断"]
                      : page === "extensions"
                        ? ["工作台附加功能"]
                        : []),
                  ];
  const groups = groupsOf(page);
  const active = groups.includes(group) ? group : groups[0],
    def = settingsPages.find((p) => p[0] === page)!,
    PageIcon = def[2];
  const switchPage = (next: SettingsPage) => {
    if (guards.check({ preserveDrafts: true })) {
      setPage(next);
      setGroup("");
    }
  };
  const openGroup = (next: SettingsPage, name: string) => {
    if (!guards.check({ preserveDrafts: true })) return;
    setPage(next);
    setGroup(name);
    setListing(false);
  };
  const toList = () => {
    if (guards.check({ preserveDrafts: true })) setListing(true);
  };
  useEffect(() => {
    const dialog = ref.current!,
      previous = document.activeElement as HTMLElement;
    dialog.showModal();
    document.body.classList.add("wb-settings-open");
    return () => {
      dialog.close();
      document.body.classList.remove("wb-settings-open");
      previous?.focus();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className="wb-ui wb-settings-workspace"
      data-wb-exiting={exiting || undefined}
      inert={exiting}
      aria-label="独立设置工作区"
      onCancel={(e) => {
        e.preventDefault();
        if (mobile && !listing) toList();
        else close();
      }}
    >
      {mobile ? (
        <header className="wb-settings-header">
          {!listing && (
            <button aria-label="返回设置列表" disabled={host.resourceAction} onClick={toList}>
              <ArrowLeft size={20} />
            </button>
          )}
          <strong className="wb-settings-title">
            {listing ? (
              "设置"
            ) : (
              <>
                <small>{def[1]}</small>
                {active}
              </>
            )}
          </strong>
          <SaveState host={host} />
          {listing && (
            <button
              className="wb-icon"
              aria-label="返回工作台"
              disabled={host.resourceAction}
              onClick={close}
            >
              <X size={20} />
            </button>
          )}
        </header>
      ) : (
        <header className="wb-settings-header">
          <button disabled={host.resourceAction} onClick={close}>
            <ArrowLeft size={17} />
            返回
          </button>
          <strong>
            <PageIcon size={19} />
            {def[1]}
          </strong>
          <span className="wb-grow" />
          <SaveState host={host} />
          <button className="wb-icon" aria-label="返回工作台" disabled={host.resourceAction} onClick={close}>
            <X size={19} />
          </button>
        </header>
      )}
      {mobile && listing ? (
        <div className="wb-settings-index">
          {pages.map(([id, label, Icon]) => (
            <section key={id} aria-label={label}>
              <h3>
                <Icon size={16} />
                {label}
              </h3>
              <div className="wb-settings-index-rows">
                {groupsOf(id).map((name) => (
                  <button key={name} disabled={host.resourceAction} onClick={() => openGroup(id, name)}>
                    <span>{name}</span>
                    <ChevronRight size={16} />
                  </button>
                ))}
              </div>
            </section>
          ))}
          <footer>Noval 工作台 · SillyTavern 1.19.0</footer>
        </div>
      ) : (
        <div className="wb-settings-layout">
          <nav className="wb-settings-nav" aria-label="设置分类">
            {pages.map(([id, label, Icon]) => (
              <button
                key={id}
                aria-pressed={page === id}
                disabled={host.resourceAction}
                onClick={() => switchPage(id)}
              >
                <Icon size={17} />
                {label}
              </button>
            ))}
            <footer>
              Noval 工作台 · 独立设置工作区
              <br />
              SillyTavern 1.19.0
            </footer>
          </nav>
          <main>
            <nav className="wb-settings-subnav" aria-label="设置分组">
              {groups.map((g) => (
                <button
                  key={g}
                  aria-pressed={active === g}
                  disabled={host.resourceAction}
                  onClick={() => {
                    if (guards.check({ preserveDrafts: true })) setGroup(g);
                  }}
                >
                  {g}
                </button>
              ))}
              {page === "settings" && <ReadingSettings host={host} />}
            </nav>
            <Notice error={task.error} />
            <div className="wb-settings-body" key={page + ":" + active}>
              <Suspense fallback={<Loading />}>
                {page === "database" ? (
                  <Database
                    host={host}
                    // A phone keeps the records-and-form view: a grid would only scroll sideways.
                    deep={!mobile}
                    initial={positions.database}
                    onSelection={(key) => setPositions((p) => ({ ...p, database: key }))}
                    leave={() => {
                      // The plug-in's window opens under this modal, so the workspace closes first.
                      if (!guards.check({ preserveDrafts: true })) return false;
                      onClose();
                      return true;
                    }}
                  />
                ) : page === "extensions" && active === "工作台附加功能" ? (
                  <AddonSettings host={host} />
                ) : page === "settings" && active === "常用工具" ? (
                  <ToolSettings host={host} />
                ) : page === "settings" && active === "加载诊断" ? (
                  <StartupDiagnostics host={host} />
                ) : resource && active !== "绑定与全局设置" && active !== "高级参数" ? (
                  <ResourceManager
                    host={host}
                    kind={resource}
                    initial={positions[resource]}
                    onPosition={(id) => setPositions((p) => ({ ...p, [resource]: id }))}
                    selection={selected[resource] || []}
                    onSelection={(ids) => setSelected((s) => ({ ...s, [resource]: ids }))}
                    view={active === "提示词" ? "prompts" : undefined}
                  />
                ) : active === "绑定与全局设置" ? (
                  <WorldBindings host={host} />
                ) : page === "persona" ? (
                  <PersonaManager
                    host={host}
                    group={active}
                    initial={positions.persona}
                    onPosition={(id) => setPositions((p) => ({ ...p, persona: id }))}
                  />
                ) : page === "character" && active === "全部角色" ? (
                  <Characters host={host} management />
                ) : page === "character" ? (
                  <Groups host={host} />
                ) : (
                  <ComponentSettings host={host} page={page} group={active} extensionId={extensionId} />
                )}
              </Suspense>
            </div>
          </main>
        </div>
      )}
      {closing && (
        <Dialog
          title="离开设置工作区"
          onClose={() => {
            if (!task.busy) setClosing(false);
          }}
        >
          <div className="wb-confirm-body">
            <p>还有 {host.dirtyDraftKeys().length} 份资源草稿未保存。</p>
            <Notice error={task.error} />
            <div className="wb-flex">
              <button disabled={task.busy} onClick={() => setClosing(false)}>
                取消
              </button>
              <span className="wb-grow" />
              <button
                disabled={task.busy}
                onClick={() => {
                  host.drafts.clear();
                  onClose();
                }}
              >
                放弃修改
              </button>
              <button
                className="wb-primary"
                disabled={task.busy}
                onClick={() =>
                  task.run(async () => {
                    await host.saveDrafts();
                    onClose();
                  })
                }
              >
                保存并返回
              </button>
            </div>
          </div>
        </Dialog>
      )}
    </dialog>
  );
}

/** Instant settings are written by SillyTavern's debounced save; ST confirms a write with SETTINGS_UPDATED. */
const instantSettings = ".wb-designed-settings,.wb-native-settings-slot";
/**
 * Save state of the instant (native) settings in place of a save button: 已保存, 保存中, or
 * 保存失败 with a retry that writes the settings directly.
 */
function SaveState({ host }: { host: HostAdapter }) {
  const [state, setState] = useState<"saved" | "saving" | "failed">("saved"),
    ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const dialog = ref.current?.closest("dialog");
    let timer: ReturnType<typeof setTimeout> | undefined;
    const saved = () => {
      clearTimeout(timer);
      setState("saved");
    };
    const edit = (e: Event) => {
      const target = e.target as Element;
      // Resource editors (fieldsets) in the same workspace keep drafts and their own save bar.
      if (!target.closest?.(instantSettings) || target.closest("fieldset")) return;
      setState("saving");
      clearTimeout(timer);
      // SillyTavern debounces saves by a second; no confirmation after a few more means it failed.
      timer = setTimeout(() => setState("failed"), 6000);
    };
    const off = host.onSettingsSaved(saved);
    dialog?.addEventListener("input", edit, true);
    dialog?.addEventListener("change", edit, true);
    return () => {
      clearTimeout(timer);
      off();
      dialog?.removeEventListener("input", edit, true);
      dialog?.removeEventListener("change", edit, true);
    };
  }, [host]);
  return (
    <span ref={ref} className={`wb-save-state is-${state}`} role="status">
      {state === "failed" ? (
        <button
          onClick={() => {
            setState("saving");
            host.persistSettings().then(
              () => setState("saved"),
              () => setState("failed"),
            );
          }}
        >
          设置保存失败 · 重试
        </button>
      ) : state === "saving" ? (
        "设置保存中"
      ) : (
        "设置已保存"
      )}
    </span>
  );
}
