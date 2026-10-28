import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronRight, Type } from "./icons";
import type { HostAdapter } from "../host/adapter";
import { useHostSlices } from "./common";
import { Popover } from "./Popover";
import { usePresence } from "./Motion";
import { MessageActions } from "./MessageActions";
import { useMessageEditing } from "./useMessageEditing";
import { messageActions } from "./message-actions";
/** `row` renders a labelled list row (the phone's session menu) instead of the toolbar icon. */
export function ReadingSettings({ host, row = false }: { host: HostAdapter; row?: boolean }) {
  // Subscribed for the re-render: the preferences below are read from the host on each render.
  useHostSlices(host, ["session", "chat", "prefs"]);
  const prefs = host.prefs(),
    [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const presence = usePresence(anchor);
  return (
    <>
      <button
        className={`${row ? "wb-reading-row" : "wb-icon"} ${anchor ? "is-active" : ""}`}
        title="阅读设置"
        aria-label="阅读设置"
        aria-expanded={!!anchor}
        onClick={(e) => setAnchor(anchor ? null : e.currentTarget)}
      >
        <Type size={row ? 19 : 17} />
        {row && "阅读设置"}
        {row && <ChevronRight size={15} />}
      </button>
      {presence.value && (
        <Popover
          anchor={presence.value}
          exiting={presence.exiting}
          title="阅读设置"
          onClose={() => setAnchor(null)}
        >
          <div className="wb-pop-form">
            <span className="wb-pop-label">字体</span>
            <div className="wb-font-choices">
              {[
                ["serif", "宋体 · 纸书"],
                ["sans", "黑体 · 清晰"],
              ].map(([value, label]) => (
                <button
                  key={value}
                  aria-pressed={(prefs.readingFont || "serif") === value}
                  onClick={() => host.preference({ readingFont: value as "serif" | "sans" })}
                >
                  {label}
                </button>
              ))}
            </div>
            <label className="wb-field">
              <span>
                字号<output>{prefs.readingSize ?? 17} px</output>
              </span>
              <input
                aria-label="阅读字号"
                type="range"
                min={14}
                max={24}
                step={1}
                value={prefs.readingSize ?? 17}
                onChange={(e) => host.preference({ readingSize: Number(e.target.value) })}
              />
            </label>
            <label className="wb-field">
              <span>
                行距<output>{prefs.readingLeading ?? 2}</output>
              </span>
              <input
                aria-label="阅读行距"
                type="range"
                min={1.5}
                max={2.4}
                step={0.1}
                value={prefs.readingLeading ?? 2}
                onChange={(e) => host.preference({ readingLeading: Number(e.target.value) })}
              />
            </label>
            <label className="wb-field">
              <span>
                左右留白<output>{prefs.readingInset ?? 64} px</output>
              </span>
              <input
                aria-label="正文左右留白"
                type="range"
                min={24}
                max={128}
                step={4}
                value={prefs.readingInset ?? 64}
                onChange={(e) => host.preference({ readingInset: Number(e.target.value) })}
              />
            </label>
            <label className="wb-check">
              <input
                type="checkbox"
                checked={prefs.userCollapsed !== false}
                onChange={(e) => host.preference({ userCollapsed: e.target.checked })}
              />
              默认折叠用户输入
            </label>
            <span className="wb-pop-label">时间与楼层</span>
            <div className="wb-meta-choices">
              {[
                ["hover", "悬浮显示"],
                ["always", "始终显示"],
                ["never", "隐藏"],
              ].map(([value, label]) => (
                <button
                  key={value}
                  aria-pressed={(prefs.messageMeta || "hover") === value}
                  onClick={() => host.preference({ messageMeta: value as any })}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        </Popover>
      )}
    </>
  );
}
/** Only add siblings and presentation classes; native text/media/iframe nodes remain owned by ST. */
/** Memoised: it follows its own host slices, so a parent re-render (a drawer opening) has nothing to add. */
export const ReadingPresentation = React.memo(function ReadingPresentation({
  host,
  chatStyle = false,
}: {
  host: HostAdapter;
  chatStyle?: boolean;
}) {
  useMessageEditing(host);
  const folds = useRef(new Map<HTMLElement, boolean>()),
    animations = useRef(new Map<HTMLElement, Animation>());
  const controls = useRef(
    new Map<HTMLElement, { role: string | null; tab: string | null; label: string | null }>(),
  );
  const snap = useHostSlices(host, ["session", "chat", "prefs"]),
    prefs = host.prefs(),
    [nodes, setNodes] = useState<HTMLElement[]>([]),
    [expanded, setExpanded] = useState<Map<HTMLElement, boolean>>(new Map());
  useEffect(() => {
    const chat = document.getElementById("chat")!;
    const scan = () => {
      for (const n of controls.current.keys()) if (!chat.contains(n)) controls.current.delete(n);
      const next = [...chat.querySelectorAll<HTMLElement>(".mes")];
      setNodes((old) => (old.length === next.length && old.every((n, i) => n === next[i]) ? [...old] : next));
    };
    scan();
    const off = host.chatObserver.subscribe((change) => {
      if (change.nodes || change.editing) scan();
    });
    const edit = (e: Event) => {
      const node = (e.target as Element)?.closest<HTMLElement>(".mes_edit")?.closest<HTMLElement>(".mes");
      if (node) setExpanded((prev) => new Map([...prev, [node, true]]));
    };
    const key = (e: KeyboardEvent) => {
      const control = (e.target as Element)?.closest<HTMLElement>(".wb-reading-icon");
      if (control && (e.key === "Enter" || e.key === " ")) {
        e.preventDefault();
        control.click();
      }
    };
    chat.addEventListener("click", edit, true);
    chat.addEventListener("keydown", key);
    return () => {
      animations.current.forEach((a) => a.cancel());
      animations.current.clear();
      folds.current.clear();
      off();
      chat.removeEventListener("click", edit, true);
      chat.removeEventListener("keydown", key);
      controls.current.forEach((attrs, n) => {
        for (const [key, value] of [
          ["role", attrs.role],
          ["tabindex", attrs.tab],
          ["aria-label", attrs.label],
        ])
          value === null ? n.removeAttribute(key!) : n.setAttribute(key!, value!);
      });
      controls.current.clear();
      chat.querySelectorAll(".wb-user-heading").forEach((n) => n.remove());
      chat.querySelectorAll(".wb-message-toolbar").forEach((n) => n.remove());
      chat.querySelectorAll(".wb-reading-icon").forEach((n) => n.classList.remove("wb-reading-icon"));
      chat.querySelectorAll(".wb-user-collapsed").forEach((n) => n.classList.remove("wb-user-collapsed"));
      chat
        .querySelectorAll<HTMLElement>(
          ".mes[is_user=true] .mes_text,.mes[is_user=true] .mes_img_container,.mes[is_user=true] .mes_file_container,.mes[is_user=true] .mes_reasoning_details",
        )
        .forEach((n) => (n.inert = false));
      document.body.removeAttribute("data-wb-meta");
      document.body.style.removeProperty("--wb-reading-font");
      document.body.style.removeProperty("--wb-reading-size");
      document.body.style.removeProperty("--wb-reading-leading");
      document.body.style.removeProperty("--wb-reading-inset");
    };
  }, [host]);
  useLayoutEffect(() => {
    for (const node of nodes) {
      if (node.getAttribute("is_user") !== "true") continue;
      const open =
        chatStyle ||
        (expanded.get(node) ?? prefs.userCollapsed === false) ||
        !!node.querySelector(".edit_textarea");
      const changed = folds.current.has(node),
        wasOpen = folds.current.get(node);
      const bodies = [
        ...node.querySelectorAll<HTMLElement>(
          ".mes_text,.mes_img_container,.mes_file_container,.mes_reasoning_details",
        ),
      ].filter(
        (n) =>
          !n.parentElement?.closest(
            ".mes_text,.mes_img_container,.mes_file_container,.mes_reasoning_details",
          ),
      );
      const heights = bodies.map((n) => n.getBoundingClientRect().height),
        styles = bodies.map((n) => getComputedStyle(n)),
        opacities = styles.map((n) => n.opacity),
        margins = styles.map((n) => n.marginTop);
      if (!changed || wasOpen !== open)
        bodies.forEach((n) => {
          animations.current.get(n)?.cancel();
          animations.current.delete(n);
        });
      node.classList.toggle("wb-user-collapsed", !open);
      const motion =
        !matchMedia("(prefers-reduced-motion: reduce)").matches &&
        !document.body.classList.contains("reduced-motion");
      bodies.forEach((body, i) => {
        body.inert = !open;
        if (changed && wasOpen !== open && motion) {
          const target = open ? body.scrollHeight : 0;
          const animation = body.animate(
            [
              {
                height: heights[i] + "px",
                marginTop: margins[i],
                opacity: opacities[i],
                visibility: "visible",
              },
              {
                height: target + "px",
                marginTop: getComputedStyle(body).marginTop,
                opacity: open ? 1 : 0,
                visibility: "visible",
              },
            ],
            { duration: 260, easing: "cubic-bezier(.22,.8,.3,1)" },
          );
          animations.current.set(body, animation);
          animation.onfinish = () => {
            if (animations.current.get(body) === animation) animations.current.delete(body);
          };
        }
      });
      folds.current.set(node, open);
    }
    for (const node of folds.current.keys()) if (!nodes.includes(node)) folds.current.delete(node);
  }, [nodes, expanded, prefs.userCollapsed, chatStyle]);
  useEffect(() => {
    setExpanded(new Map());
  }, [snap.chatName, prefs.userCollapsed]);
  useEffect(() => {
    document.body.dataset.wbMeta = prefs.messageMeta || "hover";
    document.body.style.setProperty(
      "--wb-reading-font",
      prefs.readingFont === "sans"
        ? "-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif"
        : "'Noto Serif CJK SC','Source Han Serif SC','Songti SC',SimSun,serif",
    );
    document.body.style.setProperty("--wb-reading-size", (prefs.readingSize ?? 17) + "px");
    document.body.style.setProperty("--wb-reading-leading", String(prefs.readingLeading ?? 2));
    const inset = Number(prefs.readingInset ?? 64);
    document.body.style.setProperty(
      "--wb-reading-inset",
      Math.max(24, Math.min(128, Number.isFinite(inset) ? inset : 64)) + "px",
    );
  }, [prefs.readingFont, prefs.readingSize, prefs.readingLeading, prefs.messageMeta, prefs.readingInset]);
  const output: React.ReactNode[] = [];
  for (const node of nodes) {
    const id = Number(node.getAttribute("mesid")),
      m = snap.messages[id],
      editing = !!node.querySelector(".edit_textarea"),
      user = node.getAttribute("is_user") === "true",
      block = node.querySelector<HTMLElement>(".mes_block");
    if (!block) continue;
    const open = chatStyle || (expanded.get(node) ?? prefs.userCollapsed === false) || editing;
    const header = node.querySelector<HTMLElement>(".ch_name");
    if (header) {
      let toolbar = header.querySelector<HTMLElement>(":scope>.wb-message-toolbar");
      if (!toolbar) {
        toolbar = document.createElement("div");
        toolbar.className = "wb-message-toolbar";
        header.append(toolbar);
      }
      output.push(
        createPortal(
          <MessageActions host={host} node={node} editing={editing} busy={snap.busy} />,
          toolbar,
          "actions-" + id,
        ),
      );
    }
    if (user) {
      let heading = block.querySelector<HTMLElement>(":scope>.wb-user-heading");
      if (!heading) {
        heading = document.createElement("div");
        heading.className = "wb-user-heading";
        block.prepend(heading);
      }
      const summary = m?.preview.slice(0, 110) ?? "";
      output.push(
        createPortal(
          <button
            aria-label={`展开用户输入 ${id + 1} 层`}
            aria-expanded={open}
            disabled={editing}
            onClick={() => {
              setExpanded((prev) => {
                const next = new Map(prev);
                next.set(node, !open);
                return next;
              });
            }}
          >
            {<ChevronRight size={14} className={open ? "is-open" : ""} />}
            <span>你的输入</span>
            {!open && <small>{summary}</small>}
          </button>,
          heading,
          "user-" + id,
        ),
      );
    }
    const timestamp = host.messageTime(m?.send_date) || node.querySelector(".timestamp")?.textContent,
      meta = node.querySelector<HTMLElement>(".ch_name>.flex1");
    if (meta)
      output.push(
        createPortal(
          <span className="wb-reading-meta">
            {!user && m?.name && <b>{m.name}</b>}
            <span>
              {!user && m?.name ? "· " : ""}第 {id + 1} 层
            </span>
            {timestamp && <span className="wb-reading-time">{timestamp}</span>}
          </span>,
          meta,
          "meta-" + id,
        ),
      );
    if (chatStyle && !document.body.classList.contains("wb-mobile"))
      for (const [name, [Icon, label]] of Object.entries(messageActions))
        for (const control of node.querySelectorAll<HTMLElement>("." + name)) {
          if (!controls.current.has(control)) {
            controls.current.set(control, {
              role: control.getAttribute("role"),
              tab: control.getAttribute("tabindex"),
              label: control.getAttribute("aria-label"),
            });
            control.setAttribute("role", "button");
            control.tabIndex = 0;
            control.setAttribute("aria-label", label);
          }
          // Render runs often; an unconditional add still writes the attribute and wakes SillyTavern's observer.
          if (!control.classList.contains("wb-reading-icon")) control.classList.add("wb-reading-icon");
          output.push(createPortal(<Icon size={17} aria-hidden="true" />, control, id + ":" + name));
        }
  }
  return <>{output}</>;
});
