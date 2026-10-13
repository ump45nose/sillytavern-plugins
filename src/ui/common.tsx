import React, {
  useEffect,
  useId,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import {
  X,
  Search,
  LoaderCircle,
  ArrowUpRight,
  ChevronRight,
} from "lucide-react";
export { Select } from "./Select";
import type { HostAdapter } from "../host/adapter";
export function useHost<S>(host: { subscribe: (listener: () => void) => () => void; revision: () => number; snapshot: () => S }) {
  useSyncExternalStore(host.subscribe, host.revision);
  return host.snapshot();
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
export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="wb-empty">{children}</div>;
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
  const alive = useRef(true),running=useRef(false);
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
      running.current=true;setBusy(true);
      setError("");
      try {
        await fn();
      } catch (e) {
        if (alive.current) setError(e instanceof Error ? e.message : String(e));
      } finally {
        running.current=false;
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
export function NativeLink({
  onClick,
  children = "原生高级设置",
}: {
  onClick: () => void;
  children?: React.ReactNode;
}) {
  return (
    <button className="wb-link" onClick={onClick}>
      {children}
      <ArrowUpRight size={14} />
    </button>
  );
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
  const titleId=useId();
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
export function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
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
export function Row({
  name,
  detail,
  active,
  onClick,
  children,
}: {
  name: string;
  detail?: string;
  active?: boolean;
  onClick: () => void;
  children?: React.ReactNode;
}) {
  return (
    <div className={`wb-row ${active ? "is-active" : ""}`}>
      <button className="wb-row-main" onClick={onClick}>
        <strong>{name}</strong>
        {detail && <small>{detail}</small>}
      </button>
      {children ?? <ChevronRight size={14} />}
    </div>
  );
}
