import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  ChevronDown,
  Ellipsis,
  FolderOpen,
  History,
  Keyboard,
  Layers,
  ListTree,
  MessageSquarePlus,
  PencilLine,
  Settings,
  UsersRound,
} from "./icons";
import type { HostAdapter } from "../host/adapter";
import type { Data, HostSnapshot, SettingsPage } from "../host/types";
import AddonWorkspace from "./AddonWorkspace";
import { useHostSlice } from "./common";
import { bus } from "../host/bus";
import { settingsLabels } from "../host/labels";
import { addonEnabled } from "../addons/catalog";
import type { ComposerPopup } from "./ComposerPopovers";
import { planSections, type NavSectionPlan } from "./navLayout";
type Section = "history" | "outline" | "floors";
type Measure = {
  available: number;
  gap: number;
  sizes: Partial<Record<Section, { head: number; body: number }>>;
};
/** Rows of the floor list kept rendered above and below the visible ones. */
const OVERSCAN = 8;

/**
 * The floor being read: RP's current line, else the turn at the upper third of #chat while it is
 * scrolled away from the end. null means the latest floor.
 */
function readFloor(chat: HTMLElement) {
  const line = chat.querySelector(".mes.wb-rp-current");
  if (document.body.classList.contains("wb-rp") && line) return Number(line.getAttribute("mesid"));
  if (chat.scrollTop + chat.clientHeight >= chat.scrollHeight - 4) return null;
  const mark = chat.getBoundingClientRect().top + chat.clientHeight / 3;
  let id: number | null = null;
  for (const node of chat.querySelectorAll(".mes[mesid]")) {
    if (node.getBoundingClientRect().top > mark) break;
    id = Number(node.getAttribute("mesid"));
  }
  return id;
}

/**
 * readFloor, re-read on scroll, on changes reported by the shared chat observer and when the RP stage
 * moves its line; #chat gets no observer of its own.
 */
function useReadingFloor(host: HostAdapter, active: boolean, count: number) {
  const [floor, setFloor] = useState<number | null>(null);
  useEffect(() => {
    const chat = document.getElementById("chat");
    if (!active || !chat) return;
    let frame = 0;
    const read = () => {
      frame = 0;
      setFloor(readFloor(chat));
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(read);
    };
    // Floors added, removed or renumbered; streamed text alone does not move the reading floor.
    const offChat = host.chatObserver.subscribe((change) => change.nodes && schedule()),
      offLine = bus.on("rp-line", schedule);
    chat.addEventListener("scroll", schedule, { passive: true });
    read();
    return () => {
      cancelAnimationFrame(frame);
      offChat();
      offLine();
      chat.removeEventListener("scroll", schedule);
    };
  }, [host, active, count]);
  return floor ?? count - 1;
}

/**
 * The left column of the desk: the open conversation on its own card, then three sections that
 * fold independently, and a short footer into settings. Everything else lives in the settings page.
 * On the desk the sections share the column's height (planSections): what does not fit scrolls inside
 * its section, and when even that overflows the focus — the section last opened, hovered or scrolled
 * — keeps the column while the others fold to their title rows. The phone drawer scrolls as a whole.
 */
export function Navigation({
  host,
  snap,
  visible,
  mobile,
  settings,
  open,
  help,
  run,
}: {
  host: HostAdapter;
  snap: HostSnapshot;
  visible: boolean;
  mobile: boolean;
  settings: (page: SettingsPage, group?: string) => void;
  open: (popup: ComposerPopup) => void;
  help: () => void;
  run: (fn: () => unknown) => unknown;
}) {
  const messages = useHostSlice(host, "chat");
  const outlineEnabled = addonEnabled(host.prefs(), "outline");
  const [expanded, setExpanded] = useState<Record<Section, boolean>>({
      history: false,
      // Closed at start so the outline add-on (and its stylesheet) loads only when asked for.
      outline: false,
      floors: true,
    }),
    [recent, setRecent] = useState<Data[] | null>(null),
    // Sections by focus, most recent first.
    [focus, setFocus] = useState<Section[]>(["floors"]),
    [measure, setMeasure] = useState<Measure>({ available: 0, gap: 0, sizes: {} });
  const sectionsRef = useRef<HTMLDivElement>(null);
  const order: Section[] = outlineEnabled ? ["history", "outline", "floors"] : ["history", "floors"];
  const plan: Partial<Record<Section, NavSectionPlan>> = mobile
    ? {}
    : planSections(
        order.map((id) => ({ id, open: expanded[id], head: 0, body: 0, ...measure.sizes[id] })),
        measure.available,
        focus,
        { gap: measure.gap },
      );
  const layout = (id: Section): NavSectionPlan =>
    plan[id] || { state: expanded[id] ? "open" : "closed", max: null };
  const promote = (id: Section) => setFocus((f) => (f[0] === id ? f : [id, ...f.filter((s) => s !== id)]));
  // A section folded for room opens by taking the focus; the user's own fold state stays as it was.
  const toggle = (id: Section) => {
    if (layout(id).state === "auto") return promote(id);
    if (!expanded[id]) promote(id);
    setExpanded((current) => ({ ...current, [id]: !current[id] }));
  };
  // Title rows, natural body heights and the column, re-read whenever any of them resizes.
  useLayoutEffect(() => {
    const root = sectionsRef.current;
    if (mobile || !root) return;
    const read = () => {
      const sizes: Measure["sizes"] = {};
      for (const el of root.querySelectorAll<HTMLElement>(":scope > .wb-nav-section")) {
        sizes[el.dataset.section as Section] = {
          head: el.querySelector<HTMLElement>(".wb-nav-toggle")!.offsetHeight,
          body: el.querySelector<HTMLElement>(".wb-nav-body")!.offsetHeight,
        };
      }
      const next = {
        available: root.clientHeight,
        gap: parseFloat(getComputedStyle(root).rowGap) || 0,
        sizes,
      };
      setMeasure((prev) => (JSON.stringify(prev) === JSON.stringify(next) ? prev : next));
    };
    const observer = new ResizeObserver(read);
    observer.observe(root);
    root.querySelectorAll(".wb-nav-body").forEach((el) => observer.observe(el));
    read();
    return () => observer.disconnect();
  }, [mobile, outlineEnabled]);
  const hasChat = !!snap.character || !!snap.groupId;
  useEffect(() => {
    if (!visible || !hasChat) return;
    let active = true;
    host
      .recentChats()
      .then((chats) => {
        if (active) setRecent(chats);
      })
      .catch((e) => {
        if (active) host.report(e);
      });
    return () => {
      active = false;
    };
  }, [host, visible, hasChat, snap.chatName, snap.character?.id, snap.groupId, host.chatsVersion]);
  const others = (recent || []).filter((c) => String(c.file_name).replace(/\.jsonl$/, "") !== snap.chatName);
  // On the desk the floor list waits for the first measure, so it scrolls inside its final height.
  const floorsActive = visible && layout("floors").state === "open" && (mobile || measure.available > 0);
  const reading = useReadingFloor(host, floorsActive, messages.length);
  return (
    <aside
      className={`wb-left wb-nav ${visible ? "is-open" : ""}`}
      aria-label="创作导航"
      inert={!visible}
      aria-hidden={!visible}
    >
      <section className="wb-nav-card" aria-label="当前对话">
        <div className="wb-nav-card-head">
          <span className="wb-nav-card-status">
            <i className={snap.chatName ? "is-live" : ""} />
            当前对话
          </span>
          <div className="wb-nav-card-tools">
            <button
              className="wb-nav-icon"
              disabled={snap.busy || !hasChat}
              aria-label="开始新对话"
              title="开始新对话"
              onClick={() => run(() => host.newChat())}
            >
              <MessageSquarePlus size={16} />
            </button>
            <button
              className="wb-nav-icon"
              aria-label="管理聊天文件"
              title="管理聊天文件"
              disabled={!hasChat}
              onClick={(e) => open({ kind: "files", anchor: e.currentTarget })}
            >
              <FolderOpen size={16} />
            </button>
            <button
              className="wb-nav-icon"
              aria-label="聊天管理操作"
              title="更多对话操作"
              aria-expanded="false"
              onClick={(e) => open({ kind: "chat", anchor: e.currentTarget })}
            >
              <Ellipsis size={16} />
            </button>
          </div>
        </div>
        <div className="wb-nav-card-title">
          <strong title={snap.chatName}>{snap.chatName || "还没有打开的对话"}</strong>
          {snap.chatName && (
            <button
              className="wb-nav-icon is-small"
              aria-label="重命名对话"
              title="重命名对话"
              disabled={snap.busy}
              onClick={(e) => open({ kind: "rename", anchor: e.currentTarget })}
            >
              <PencilLine size={13} />
            </button>
          )}
        </div>
        <small className="wb-nav-card-meta">
          {snap.groupName || snap.character?.name || "请选择角色"} · {messages.length} 层
        </small>
      </section>

      <div className="wb-nav-sections" ref={sectionsRef}>
        <NavSection
          id="history"
          icon={<History size={16} />}
          label="历史对话"
          count={recent ? String(others.length) : ""}
          layout={layout("history")}
          toggle={() => toggle("history")}
          focus={() => promote("history")}
        >
          <ul className="wb-nav-list" aria-label="历史对话">
            {others.map((c) => {
              const name = String(c.file_name).replace(/\.jsonl$/, "");
              return (
                <li key={c.file_name}>
                  <button
                    className="wb-nav-row"
                    title={name}
                    disabled={snap.busy}
                    onClick={() => run(() => host.openChat(c.file_name))}
                  >
                    <span className="wb-nav-row-text">{name}</span>
                  </button>
                </li>
              );
            })}
          </ul>
          {recent && !others.length && <p className="wb-nav-empty">暂无历史对话</p>}
        </NavSection>

        {outlineEnabled && (
          <NavSection
            id="outline"
            icon={<ListTree size={16} />}
            label="大纲"
            layout={layout("outline")}
            toggle={() => toggle("outline")}
            focus={() => promote("outline")}
          >
            <AddonWorkspace host={host} id="outline" active={expanded.outline && visible} view="sidebar" />
          </NavSection>
        )}

        <NavSection
          id="floors"
          icon={<Layers size={16} />}
          label="对话楼层"
          count={messages.length ? String(messages.length) : ""}
          layout={layout("floors")}
          toggle={() => toggle("floors")}
          focus={() => promote("floors")}
        >
          <FloorList
            key={snap.chatName}
            messages={messages}
            reading={reading}
            active={floorsActive}
            row={mobile ? 44 : 30}
            scroller={mobile ? ".wb-nav-sections" : ".wb-nav-scroll"}
            view={mobile ? null : layout("floors").max}
            jump={(id) => run(() => host.jump(id))}
          />
          {!messages.length && <p className="wb-nav-empty">开始聊天后，楼层会显示在这里。</p>}
        </NavSection>
      </div>

      <nav className="wb-nav-footer" aria-label="设置与管理">
        <button className="wb-nav-foot" onClick={() => settings("settings")}>
          <Settings size={16} />
          设置
        </button>
        <button className="wb-nav-foot" onClick={() => settings("character")}>
          <UsersRound size={16} />
          {settingsLabels.character}
        </button>
        <button className="wb-nav-icon wb-nav-keys" aria-label="快捷键" title="快捷键" onClick={help}>
          <Keyboard size={16} />
        </button>
      </nav>
    </aside>
  );
}

/**
 * Every floor, windowed: rows have a fixed height, so only the visible ones and OVERSCAN either side
 * are rendered, inside an <ol> as tall as the whole list. Becoming active (or a new chat, which
 * remounts it) puts the reading floor a few rows below the top of `scroller` — the section on the
 * desk, the drawer on a phone.
 */
function FloorList({
  messages,
  reading,
  active,
  row,
  scroller,
  view,
  jump,
}: {
  messages: { id: number; preview: string }[];
  reading: number;
  active: boolean;
  row: number;
  scroller: string;
  view: number | null;
  jump: (id: number) => void;
}) {
  const ref = useRef<HTMLOListElement>(null),
    [range, setRange] = useState<[number, number]>([
      Math.max(0, messages.length - OVERSCAN),
      messages.length,
    ]);
  const count = messages.length;
  useLayoutEffect(() => {
    const list = ref.current!,
      section = list.closest<HTMLElement>(".wb-nav-scroll")!,
      column = list.closest<HTMLElement>(".wb-nav-sections")!;
    let frame = 0;
    const update = () => {
      frame = 0;
      const top = list.getBoundingClientRect().top,
        a = section.getBoundingClientRect(),
        b = column.getBoundingClientRect();
      const first = Math.min(count, Math.max(0, Math.floor((Math.max(a.top, b.top) - top) / row) - OVERSCAN)),
        last = Math.min(
          count,
          Math.max(first, Math.ceil((Math.min(a.bottom, b.bottom) - top) / row) + OVERSCAN),
        );
      setRange((r) => (r[0] === first && r[1] === last ? r : [first, last]));
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    const observer = new ResizeObserver(schedule);
    observer.observe(section);
    observer.observe(column);
    column.addEventListener("scroll", schedule, { capture: true, passive: true });
    update();
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      column.removeEventListener("scroll", schedule, { capture: true });
    };
  }, [count, row]);
  // Where row `index` starts inside the scroll box's content. The box's own height lags behind while
  // its section unfolds, so the planned height (`view`) stands in for it when there is one.
  const offset = (box: HTMLElement, index: number) =>
    ref.current!.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop + index * row;
  const planned = useRef(view);
  planned.current = view;
  const height = (box: HTMLElement) => planned.current ?? box.clientHeight;
  // The list stays pinned to the reading floor — following new floors and the chat's scroll — until
  // the user scrolls that row out of view, and again once they scroll it back in. `placed` is the
  // last scrollTop set here, so those scrolls are not mistaken for the user's.
  const pinned = useRef(true),
    placed = useRef(-1),
    current = useRef(reading);
  current.current = reading;
  const place = (box: HTMLElement, top: number) => {
    box.scrollTop = top;
    placed.current = box.scrollTop;
  };
  useLayoutEffect(() => {
    const box = ref.current!.closest<HTMLElement>(scroller)!,
      chat = document.getElementById("chat");
    if (!active) return;
    // The hook's floor may predate this activation, so read the chat now.
    place(box, offset(box, Math.max(0, ((chat && readFloor(chat)) ?? count - 1) - 3)));
    pinned.current = true;
    const onScroll = () => {
      if (box.scrollTop === placed.current) return;
      const y = offset(box, current.current);
      pinned.current = y + row > box.scrollTop && y < box.scrollTop + height(box);
    };
    box.addEventListener("scroll", onScroll, { passive: true });
    return () => box.removeEventListener("scroll", onScroll);
  }, [active]);
  useLayoutEffect(() => {
    const box = ref.current!.closest<HTMLElement>(scroller)!,
      y = offset(box, reading);
    if (!active || !pinned.current) return;
    if (y < box.scrollTop) place(box, y);
    else if (y + row > box.scrollTop + height(box)) place(box, y + row - height(box));
  }, [reading, count, view]);
  const [first, last] = range;
  return (
    <ol
      ref={ref}
      className="wb-nav-list wb-floor-list"
      aria-label="对话楼层"
      style={{ height: count * row, paddingTop: first * row }}
    >
      {messages.slice(first, last).map((m) => (
        <li key={m.id}>
          <button
            className={`wb-nav-row ${m.id === reading ? "is-current" : ""}`}
            aria-current={m.id === reading ? "true" : undefined}
            onClick={() => jump(m.id)}
          >
            <span className="wb-floor-number">{m.id + 1}</span>
            <span className="wb-nav-row-text">{m.preview.replace(/[#*_]/g, "").slice(0, 80)}</span>
          </button>
        </li>
      ))}
    </ol>
  );
}

function NavSection({
  id,
  icon,
  label,
  count,
  layout,
  toggle,
  focus,
  children,
}: {
  id: Section;
  icon: React.ReactNode;
  label: string;
  count?: string;
  layout: NavSectionPlan;
  toggle: () => void;
  focus: () => void;
  children: React.ReactNode;
}) {
  const expanded = layout.state === "open",
    auto = layout.state === "auto";
  return (
    <section
      className={`wb-nav-section ${expanded ? "is-open" : ""} ${auto ? "is-auto-folded" : ""}`}
      id={`wb-nav-${id}`}
      data-section={id}
      // Scrolling a section starts with the pointer over it or focus inside it; the scroll events
      // themselves also fire when a folding section clamps its scrollTop, so they do not count.
      onPointerEnter={expanded ? focus : undefined}
      onFocus={expanded ? focus : undefined}
    >
      <button
        className="wb-nav-toggle"
        aria-label={label}
        aria-expanded={expanded}
        aria-controls={`wb-nav-${id}-body`}
        title={auto ? "栏内放不下，已暂时收起；点击展开" : undefined}
        onClick={toggle}
      >
        {icon}
        <span>{label}</span>
        {count && <small>{count}</small>}
        {auto && <i className="wb-nav-auto" aria-hidden="true" />}
        <ChevronDown size={14} className="wb-nav-caret" />
      </button>
      <div
        id={`wb-nav-${id}-body`}
        className={`wb-fold-body ${expanded ? "is-open" : ""}`}
        inert={!expanded}
        aria-hidden={!expanded}
      >
        <div
          className="wb-nav-scroll"
          style={
            layout.max === null ? undefined : ({ "--wb-nav-max": `${layout.max}px` } as React.CSSProperties)
          }
        >
          <div className="wb-nav-body">{children}</div>
        </div>
      </div>
    </section>
  );
}
