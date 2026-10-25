import React, { useEffect, useLayoutEffect, useRef } from "react";
import {
  BookMarked,
  Activity,
  Check,
  ChevronDown,
  ChevronRight,
  Plug,
  ScanLine,
  SlidersHorizontal,
  UserRound,
  X,
} from "./icons";
import { createPortal } from "react-dom";
import type { HostSnapshot, Item, Panel, Resource } from "../host/types";
import { Empty, IconButton } from "./common";
import { resourceLabels } from "../host/labels";
import { usePresence } from "./Motion";
const pillIcons = { connection: Plug, preset: SlidersHorizontal, world: BookMarked, persona: UserRound };
/** The popover's way into the full panel, named after what the panel lets you do there. */
const manageLabels: Record<Resource, string> = {
  connection: "管理连接",
  preset: "打开预设",
  world: "打开世界书",
  persona: "打开用户设定",
};
/** What a choice in the popover changes, said once in its footer. */
const footHints: Partial<Record<Resource, string>> = {
  connection: "切换后立即用于下一次生成",
  world: "勾选即生效 · 全局",
};
/** The second line of a popover row: the profile's backend and model, the book's binding. */
function rowDetail(kind: Resource, item: Item, bound: string) {
  if (kind === "connection")
    return [item.data?.api, item.data?.model].filter(Boolean).join(" · ") || item.detail;
  if (kind === "world") return item.id === bound ? "角色绑定" : "";
  return item.detail;
}
export function Header({
  snap,
  panel,
  chooser,
  setChooser,
  goPanel,
  select,
  model,
  focus,
  focused,
  focusShortcut,
  actions,
}: {
  snap: HostSnapshot;
  panel: Panel;
  chooser: Resource | null;
  setChooser: (value: Resource | null) => void;
  goPanel: (panel: Panel, id?: string) => void;
  select: (kind: Resource, id: string, enabled: boolean) => void;
  model: string;
  focus: () => void;
  focused: boolean;
  focusShortcut: string;
  actions?: React.ReactNode;
}) {
  return (
    <header className="wb-top">
      <button
        className="wb-top-identity"
        aria-label={`打开角色面板：${snap.character?.name || "选择角色"}`}
        aria-pressed={panel === "character"}
        onClick={() => goPanel(panel === "character" ? null : "character")}
        title={snap.character?.name || "选择角色"}
      >
        <span className="wb-top-avatar">
          {snap.character?.image ? <img src={snap.character.image} alt="" /> : <span>N</span>}
        </span>
        <strong>{snap.groupName || snap.character?.name || "选择角色"}</strong>
      </button>
      <ResourcePills
        snap={snap}
        panel={panel}
        chooser={chooser}
        setChooser={setChooser}
        goPanel={goPanel}
        select={select}
        model={model}
      />
      <div className="wb-top-tools">
        <button
          className="wb-top-tool"
          title="Trace"
          aria-label="Trace"
          aria-pressed={panel === "trace"}
          onClick={() => goPanel(panel === "trace" ? null : "trace")}
        >
          <Activity size={18} />
        </button>
        {actions ?? (
          <button
            className="wb-top-tool wb-focus-toggle"
            title={`专注模式${focusShortcut ? " · " + focusShortcut : ""}`}
            aria-label="专注模式"
            aria-pressed={focused}
            onClick={focus}
          >
            <ScanLine size={18} />
          </button>
        )}
        {/* The layout switcher is mounted on its own (it also serves the native page) and sits here. */}
        <span className="wb-top-switcher-space" aria-hidden="true" />
      </div>
    </header>
  );
}

/** Desktop resource pills: one press opens a short list to switch; the footer leads to the panel. */
function ResourcePills({
  snap,
  panel,
  chooser,
  setChooser,
  goPanel,
  select,
  model,
}: Pick<
  Parameters<typeof Header>[0],
  "snap" | "panel" | "chooser" | "setChooser" | "goPanel" | "select" | "model"
>) {
  const presence = usePresence(chooser);
  const last = useRef<Resource | null>(null);
  // Keyboard users land on the current choice; closing returns them to the pill they came from.
  useEffect(() => {
    const previous = last.current;
    last.current = chooser;
    if (chooser) {
      requestAnimationFrame(() =>
        document
          .querySelector<HTMLInputElement>(
            `#wb-choices-${chooser} input:checked, #wb-choices-${chooser} input`,
          )
          ?.focus({ preventScroll: true }),
      );
    } else if (
      previous &&
      (!document.activeElement ||
        document.activeElement === document.body ||
        document.activeElement.closest(".wb-pill-pop"))
    )
      document.querySelector<HTMLButtonElement>(`.wb-pill[aria-controls="wb-choices-${previous}"]`)?.focus();
  }, [chooser]);
  useEffect(() => {
    if (!chooser) return;
    const outside = (event: PointerEvent) => {
      if (!(event.target as Element)?.closest?.(".wb-pill-slot")) setChooser(null);
    };
    document.addEventListener("pointerdown", outside, true);
    return () => document.removeEventListener("pointerdown", outside, true);
  }, [chooser]);
  return (
    <nav className="wb-top-pills" aria-label="当前资源">
      {(Object.keys(resourceLabels) as Resource[]).map((kind) => {
        const bound = String(snap.character?.data?.data?.extensions?.world ?? "");
        // The character's own book leads the list, as it does in the world panel.
        const items =
            kind === "world" && bound
              ? [...snap.resources.world].sort((a, b) => Number(b.id === bound) - Number(a.id === bound))
              : snap.resources[kind],
          selected = items.find((x) => x.id === snap.current[kind]);
        const Icon = pillIcons[kind];
        const value = selected?.name || (kind === "connection" ? model || "未连接" : "未选择");
        const active = items.filter((x) => x.active);
        const count = kind === "world" ? active.length : 0;
        const shown = kind === "world" ? active[0]?.name || "未启用" : value;
        const open = presence.value === kind;
        return (
          <div className="wb-pill-slot" key={kind}>
            <button
              className="wb-pill"
              aria-label={`${resourceLabels[kind]}：${shown}${count > 1 ? ` 等 ${count} 本` : ""}`}
              title={`${resourceLabels[kind]}：${shown}`}
              aria-expanded={chooser === kind}
              aria-controls={`wb-choices-${kind}`}
              aria-current={panel === kind ? "true" : undefined}
              onClick={() => setChooser(chooser === kind ? null : kind)}
            >
              <span className="wb-pill-icon">
                <Icon size={16} />
                {kind === "connection" && <i className={`wb-pill-dot ${snap.online ? "is-online" : ""}`} />}
              </span>
              <span className="wb-pill-value" key={shown + count}>
                {shown}
              </span>
              {count > 1 && <span className="wb-pill-extra">+{count - 1}</span>}
              <ChevronDown size={14} className="wb-pill-caret" />
            </button>
            {/* The icon is its own target: one press opens (or closes) this resource's tab in the right panel. */}
            <button
              className="wb-pill-go"
              aria-label={`${panel === kind ? "关闭" : "打开"}${resourceLabels[kind]}面板`}
              title={`${panel === kind ? "关闭" : "打开"}${resourceLabels[kind]}面板`}
              aria-pressed={panel === kind}
              onClick={() => {
                setChooser(null);
                goPanel(panel === kind ? null : kind);
              }}
            />
            {open && (
              <div
                className="wb-pill-pop"
                id={`wb-choices-${kind}`}
                role="dialog"
                aria-label={`${resourceLabels[kind]}选择`}
                inert={presence.exiting}
                data-wb-exiting={presence.exiting || undefined}
              >
                <div className="wb-pill-pop-head">
                  <strong>{kind === "connection" ? "连接配置" : resourceLabels[kind]}</strong>
                  <small>
                    {kind === "world" ? `已启用 ${count} · 共 ${items.length} 本` : `${items.length} 个`}
                  </small>
                </div>
                <ul className="wb-pill-pop-list">
                  {items.map((item) => {
                    const on = kind === "world" ? !!item.active : item.id === snap.current[kind];
                    const detail = rowDetail(kind, item, bound);
                    return (
                      <li key={item.id} className={on ? "is-on" : ""}>
                        <label>
                          <input
                            type={kind === "world" ? "checkbox" : "radio"}
                            name={`wb-pill-${kind}`}
                            aria-label={`${kind === "world" ? "启用" : "选择"} ${item.name}`}
                            checked={on}
                            disabled={snap.busy}
                            onChange={(e) => select(kind, item.id, e.target.checked)}
                          />
                          <span
                            className={`wb-pill-mark ${kind === "world" ? "is-check" : ""}`}
                            aria-hidden="true"
                          >
                            <Check size={12} strokeWidth={3} />
                          </span>
                          <span className="wb-pill-pop-copy">
                            <strong>{item.name}</strong>
                            {detail && <small>{detail}</small>}
                          </span>
                        </label>
                      </li>
                    );
                  })}
                </ul>
                {!items.length && <Empty>暂无配置</Empty>}
                <div className="wb-pill-pop-foot">
                  {footHints[kind] && <small>{footHints[kind]}</small>}
                  <button onClick={() => goPanel(kind)}>
                    {manageLabels[kind]}
                    <ChevronRight size={14} />
                  </button>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </nav>
  );
}

/** The PWA configuration row: one tile per resource, each opening its chooser sheet. */
export function ResourceControls({
  snap,
  panel,
  chooser,
  setChooser,
  goPanel,
  select,
  model,
}: Pick<
  Parameters<typeof Header>[0],
  "snap" | "panel" | "chooser" | "setChooser" | "goPanel" | "select" | "model"
>) {
  const presence = usePresence(chooser);
  // Phone tiles share the card's width equally; a name that does not fit leaves just the icon.
  const row = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const node = row.current;
    if (!node) return;
    const fit = () => {
      for (const tile of node.querySelectorAll<HTMLElement>(".wb-selector")) {
        const text = tile.querySelector<HTMLElement>(".wb-value-text"),
          icon = tile.querySelector<HTMLElement>(".wb-selector-icon");
        if (!text || !icon) continue;
        const room = tile.clientWidth - 20 - icon.offsetWidth - 6;
        tile.classList.toggle("is-iconic", text.scrollWidth > room);
      }
    };
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(node);
    return () => observer.disconnect();
  });
  return (
    <div className="wb-contexts" ref={row}>
      {(Object.keys(resourceLabels) as Resource[]).map((kind) => {
        const items = snap.resources[kind],
          selected = items.find((x) => x.id === snap.current[kind]);
        const value = selected?.name || (kind === "connection" ? model : "未选择");
        const count = kind === "world" ? items.filter((x) => x.active).length : 0;
        return (
          <div className={`wb-selector ${panel === kind || chooser === kind ? "is-active" : ""}`} key={kind}>
            {/* A phone tile is one tap target: icon and name open the chooser, whose rows lead on to details. */}
            <button
              className="wb-selector-value"
              title={`${resourceLabels[kind]}：${value}`}
              aria-label={`${resourceLabels[kind]}：${value}${count > 1 ? ` 等 ${count} 本` : ""}`}
              aria-expanded={chooser === kind}
              aria-controls={`wb-choices-${kind}`}
              onClick={() => setChooser(chooser === kind ? null : kind)}
            >
              <span className="wb-selector-icon" aria-hidden="true">
                {React.createElement(pillIcons[kind], { size: 17 })}
                {kind === "connection" && <i className={`wb-dot ${snap.online ? "online" : ""}`} />}
              </span>
              <span key={value + count} className="wb-value-text">
                {value}
                {count > 1 ? ` +${count - 1}` : ""}
              </span>
            </button>
            {presence.value === kind &&
              createPortal(
                <div className="wb-ui wb-mobile-resource-popup">
                  <button
                    className="wb-pop-dismiss"
                    aria-label="关闭选择框"
                    onClick={() => setChooser(null)}
                  />
                  <div
                    className="wb-popover"
                    role="dialog"
                    aria-label={`${resourceLabels[kind]}选择`}
                    inert={presence.exiting}
                    data-wb-exiting={presence.exiting || undefined}
                    id={`wb-choices-${kind}`}
                  >
                    <div className="wb-section-title">
                      {resourceLabels[kind]}
                      <small>选择 · 查看详情</small>
                      <button className="wb-icon" aria-label="关闭资源选择" onClick={() => setChooser(null)}>
                        <X size={18} />
                      </button>
                    </div>
                    {items.map((item) => (
                      <div
                        className={`wb-quick-row ${(kind === "world" ? item.active : item.id === snap.current[kind]) ? "is-active" : ""}`}
                        key={item.id}
                      >
                        <input
                          type="checkbox"
                          aria-label={`${kind === "world" ? "启用" : "选择"} ${item.name}`}
                          checked={kind === "world" ? !!item.active : item.id === snap.current[kind]}
                          disabled={snap.busy}
                          onChange={(e) => select(kind, item.id, e.target.checked)}
                        />
                        <button onClick={() => goPanel(kind, item.id)}>
                          <strong>{item.name}</strong>
                          {item.detail && <small>{item.detail}</small>}
                        </button>
                        <IconButton title={`查看 ${item.name} 详情`} onClick={() => goPanel(kind, item.id)}>
                          <ChevronRight size={15} />
                        </IconButton>
                      </div>
                    ))}
                    {!items.length && <Empty>暂无配置</Empty>}
                    <button className="wb-link" onClick={() => goPanel(kind)}>
                      查看全部与编辑 <ChevronRight size={14} />
                    </button>
                  </div>
                </div>,
                document.body,
              )}
          </div>
        );
      })}
    </div>
  );
}
