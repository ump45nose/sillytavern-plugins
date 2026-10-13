import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import type { HostAdapter } from "../host/adapter";
import type { Data } from "../host/types";
import { clone } from "../host/model";
export function Fold({ title, children, initial = false, toolbar, icon }: { title: string; children: React.ReactNode; initial?: boolean; toolbar?: React.ReactNode; icon?: React.ReactNode }) {
  const [open, setOpen] = useState(initial);
  const toggle = <button className={`wb-fold-toggle ${icon ? "wb-icon" : ""}`} title={title} aria-label={title} aria-expanded={open} onClick={() => setOpen(!open)}>{icon || <>{title}<ChevronDown size={15} className={open ? "is-rotated" : ""}/></>}</button>;
  return <section className="wb-resource-fold">{toolbar ? <div className="wb-fold-toolbar">{toolbar}{toggle}</div> : toggle}<div className={`wb-fold-body ${open ? "is-open" : ""}`} aria-hidden={!open} inert={!open}><div>{children}</div></div></section>;
}
export function Check({ label, checked, onChange, disabled = false }: { label: string; checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return <label className="wb-check"><input type="checkbox" checked={checked} disabled={disabled} onChange={e => onChange(e.target.checked)} />{label}</label>;
}
export function NativeConnection({ host }: { host: HostAdapter }) {
  const ref = useRef<HTMLDivElement>(null), [error, setError] = useState("");
  useEffect(() => { try { return host.leaseConnection(ref.current!); } catch (e) { setError(String(e)); } }, [host]);
  return <><p className="wb-native-caption">当前运行连接 · 设置由酒馆即时保存</p>{error && <p role="alert">{error}</p>}<div ref={ref} className="wb-native-slot" /></>;
}
export function useDraft(read: () => Data, version: number, cache?:{host:HostAdapter;key:string}) {
  const previous=cache?.host.drafts.get(cache.key),retain=previous&&JSON.stringify(previous.base)!==JSON.stringify(previous.draft);
  const [base, setBase] = useState(()=>retain?clone(previous.base):read()), [draft, setDraft] = useState(() => retain?clone(previous.draft):clone(base)), [message, setMessage] = useState("");
  const dirty = JSON.stringify(base) !== JSON.stringify(draft);
  useLayoutEffect(()=>{if(cache)cache.host.drafts.set(cache.key,{base:clone(base),draft:clone(draft),extra:cache.host.drafts.get(cache.key)?.extra});},[base,draft,cache?.key]);
  useEffect(() => { if (!dirty) { const value = read(); setBase(value); setDraft(clone(value)); } }, [version]);
  useEffect(() => {
    const guard = (e: Event) => { if(cache)return;if (dirty && !confirm("有未保存修改，放弃这些修改？")) e.preventDefault(); };
    const unload = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("wb-before-close", guard); window.addEventListener("beforeunload", unload);
    return () => { window.removeEventListener("wb-before-close", guard); window.removeEventListener("beforeunload", unload); };
  }, [dirty]);
  return { base, draft, dirty, message, setDraft, change: (key: string, value: any) => { setDraft(d => ({ ...d, [key]: value })); setMessage(""); }, saved: (data: Data) => { setBase(clone(data)); setDraft(clone(data)); setMessage("已保存"); }, reset: () => { setDraft(clone(base)); setMessage(""); } };
}
