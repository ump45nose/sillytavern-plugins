import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { BookOpen, ChevronLeft, ChevronRight, PanelsTopLeft, Theater } from "lucide-react";
import { usePresence } from "./Motion";

export type LayoutMode = "novel" | "rp" | "native";
const modes = [
  { id:"novel", name:"Noval", detail:"阅读工作台", Icon:BookOpen },
  { id:"rp", name:"RP", detail:"角色聊天与立绘", Icon:Theater },
  { id:"native", name:"原生", detail:"酒馆原版", Icon:PanelsTopLeft },
] as const;

/** Stays mounted independently of the workbench so native mode has the same entry. */
export function LayoutSwitcher({ mode, onChange }: { mode:LayoutMode; onChange:(mode:LayoutMode)=>Promise<boolean> }) {
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const root = useRef<HTMLDivElement>(null), trigger = useRef<HTMLButtonElement>(null), presence = usePresence(open ? true : null);
  const selected = modes.find(item => item.id === mode)!;
  const index = modes.indexOf(selected), previous = modes[(index + modes.length - 1) % modes.length], next = modes[(index + 1) % modes.length];
  useEffect(() => {
    window.dispatchEvent(new CustomEvent("wb-layout-menu", { detail:open }));
    return () => { window.dispatchEvent(new CustomEvent("wb-layout-menu", { detail:false })); };
  }, [open]);
  useLayoutEffect(() => {
    if (!open) return;
    const frame = requestAnimationFrame(() => (root.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]:not(:disabled)') || root.current?.querySelector<HTMLButtonElement>('button[role="menuitemradio"]:not(:disabled)'))?.focus({ preventScroll:true }));
    const outside = (event:PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", outside);
    return () => { cancelAnimationFrame(frame); document.removeEventListener("pointerdown", outside); };
  }, [open]);
  const choose = async (next:LayoutMode) => {
    if (busy) return;
    if (next === mode) { setOpen(false); trigger.current?.focus(); return; }
    setBusy(true); setError("");
    try { if (await onChange(next)) { setOpen(false); trigger.current?.focus({ preventScroll:true }); } }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); setOpen(true); }
    finally { setBusy(false); }
  };
  return <div ref={root} className={`wb-layout-switcher wb-ui ${mode === "rp" ? "is-rp" : ""}`} onKeyDown={event => {
    if (event.key === "Escape" && open) { event.preventDefault(); event.stopPropagation(); setOpen(false); trigger.current?.focus(); }
  }}>
    <div className="wb-layout-controls" role="group" aria-label="工作台切换">
    <button className="wb-layout-step" aria-label={`上一个工作台 · ${previous.name}`} title={`上一个工作台 · ${previous.name}`} disabled={busy} onClick={() => void choose(previous.id)}><ChevronLeft size={16}/></button>
    <button ref={trigger} className="wb-layout-trigger" aria-label="切换工作台" title={`选择工作台 · 当前 ${selected.name}`} aria-haspopup="menu" aria-expanded={open} aria-controls="wb-layout-menu" disabled={busy} onClick={() => { setError(""); setOpen(!open); }} onKeyDown={event => {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") { event.preventDefault(); setOpen(true); }
    }}><selected.Icon size={20}/></button>
    <button className="wb-layout-step" aria-label={`下一个工作台 · ${next.name}`} title={`下一个工作台 · ${next.name}`} disabled={busy} onClick={() => void choose(next.id)}><ChevronRight size={16}/></button>
    </div>
    {presence.value && <div id="wb-layout-menu" className="wb-layout-menu" role="menu" aria-label="工作台模式" data-wb-exiting={presence.exiting || undefined} inert={presence.exiting} onKeyDown={event => {
      if (event.key === "Tab") { setOpen(false); return; }
      const items = [...event.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')], index = items.indexOf(document.activeElement as HTMLButtonElement);
      const next = event.key === "ArrowDown" ? (index + 1) % items.length : event.key === "ArrowUp" ? (index - 1 + items.length) % items.length : event.key === "Home" ? 0 : event.key === "End" ? items.length - 1 : -1;
      if (next >= 0) { event.preventDefault(); items[next]?.focus(); }
    }}>
      {modes.map(({ id, name, detail, Icon }) => <button key={id} role="menuitemradio" aria-checked={mode === id} disabled={busy} onClick={() => void choose(id)}><Icon size={19}/><span><strong>{name}</strong><small>{detail}</small></span><i className="wb-layout-dot" aria-hidden="true"/></button>)}
      {error && <p className="wb-layout-error" role="alert">{error}</p>}
    </div>}
  </div>;
}
