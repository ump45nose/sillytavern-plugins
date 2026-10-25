import React, { useCallback, useEffect, useId, useRef, useState, useSyncExternalStore } from "react";
import { X, Search, LoaderCircle } from "./icons";
export { Select } from "./Select";
import type { HostAdapter } from "../host/adapter";
import type { HostSnapshot, Slice, Slices } from "../host/types";
import { guards, type Guard } from "../host/bus";
/**
 * While `dirty`, the browser asks before the page unloads and `guard` (if any) joins the workbench's
 * leave checks. The latest `guard` is used, so callers may pass an inline function.
 */
export function useLeaveGuard(dirty: boolean, guard?: Guard) {
  const latest = useRef(guard);
  latest.current = guard;
  useEffect(() => {
    if (!dirty) return;
    const offHold = guards.hold(() => true),
      offGuard = guards.add((options) => latest.current?.(options) ?? true);
    return () => {
      offHold();
      offGuard();
    };
  }, [dirty]);
}
export function useHost<S>(host: {
  subscribe: (listener: () => void) => () => void;
  revision: () => number;
  snapshot: () => S;
}) {
  useSyncExternalStore(host.subscribe, host.revision);
  return host.snapshot();
}
/** Every slice but the chat index: UI that does not list messages stays still while chat updates. */
export const withoutChat: readonly Slice[] = ["session", "characters", "resources", "prefs"];
/** The full snapshot, re-rendering only when one of `slices` changes. */
export function useHostSlices(host: HostAdapter, slices: readonly Slice[]): HostSnapshot {
  const key = slices.join();
  const subscribe = useCallback(
    (fn: () => void) => {
      const off = slices.map((name) => host.subscribeSlice(name, fn));
      return () => off.forEach((f) => f());
    },
    [host, key],
  );
  useSyncExternalStore(subscribe, () => slices.map((name) => host.sliceRevision(name)).join());
  return host.snapshot();
}
export function useHostSlice<K extends Slice>(host: HostAdapter, name: K): Slices[K] {
  const subscribe = useCallback((fn: () => void) => host.subscribeSlice(name, fn), [host, name]);
  return useSyncExternalStore(subscribe, () => host.slice(name));
}
export function IconButton({
  title,
  onClick,
  children,
  disabled = false,
}: {
  title: string;
  onClick: () => void;
  children: React.ReactNode;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      className="wb-icon"
      title={title}
      aria-label={title}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  );
}
/** An empty state. Plain text by default; with an icon, title or action it becomes the board's centred card. */
export function Empty({
  children,
  icon,
  title,
  action,
}: {
  children?: React.ReactNode;
  icon?: React.ReactNode;
  title?: string;
  action?: { label: string; onClick: () => void };
}) {
  if (!icon && !title && !action) return <div className="wb-empty">{children}</div>;
  return (
    <div className="wb-empty is-rich">
      {icon && <span className="wb-empty-icon">{icon}</span>}
      {title && <strong>{title}</strong>}
      {children && <p>{children}</p>}
      {action && (
        <button className="wb-empty-action" onClick={action.onClick}>
          {action.label}
        </button>
      )}
    </div>
  );
}
export function SearchBox({
  value,
  onChange,
  placeholder = "搜索…",
}: {
  value: string;
  onChange: (s: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="wb-search">
      <Search size={16} />
      <input
        aria-label={placeholder}
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}
export function useTask() {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const alive = useRef(true),
    running = useRef(false);
  useEffect(
    () => () => {
      alive.current = false;
    },
    [],
  );
  return {
    busy,
    error,
    setError,
    run: async (fn: () => unknown) => {
      if (running.current) return;
      running.current = true;
      setBusy(true);
      setError("");
      try {
        await fn();
      } catch (e) {
        if (alive.current) setError(e instanceof Error ? e.message : String(e));
      } finally {
        running.current = false;
        if (alive.current) setBusy(false);
      }
    },
  };
}
export function Notice({ error }: { error: string }) {
  return error ? (
    <p className="wb-error" role="alert">
      {error}
    </p>
  ) : null;
}
export function Dialog({
  title,
  children,
  onClose,
  wide = false,
  exiting = false,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
  wide?: boolean;
  exiting?: boolean;
}) {
  const titleId = useId();
  const ref = useRef<HTMLDialogElement>(null),
    close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement;
    ref.current?.showModal();
    return () => {
      ref.current?.close();
      previous?.focus();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      className={`wb-dialog ${wide ? "wb-wide" : ""}`}
      data-wb-exiting={exiting || undefined}
      inert={exiting}
      onCancel={(e) => {
        e.preventDefault();
        close.current();
      }}
    >
      <header>
        <div>
          <span className="wb-eyebrow">WORKBENCH / NOVAL</span>
          <h2 id={titleId}>{title}</h2>
        </div>
        <IconButton title="返回工作台" onClick={onClose}>
          <X size={20} />
        </IconButton>
      </header>
      {children}
    </dialog>
  );
}
export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="wb-field">
      <span>{label}</span>
      {React.isValidElement(children)
        ? React.cloneElement(children as React.ReactElement<any>, {
            "aria-label": label,
          })
        : children}
    </label>
  );
}
export function Loading() {
  return (
    <Empty>
      <LoaderCircle size={20} className="wb-spin" /> 正在载入…
    </Empty>
  );
}
