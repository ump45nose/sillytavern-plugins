import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from "react";
import type { MdHandle, MdOptions } from "./editor";

/** Whether Markdown fields preview as you type; the workbench sets it from the mdLive preference. */
let live = true;
const listeners = new Set<() => void>();
export const mdLive = {
  get: () => live,
  set(value: boolean) {
    if (value === live) return;
    live = value;
    listeners.forEach((fn) => fn());
  },
  subscribe(fn: () => void) {
    listeners.add(fn);
    return () => {
      listeners.delete(fn);
    };
  },
};
export const useMdLive = () => useSyncExternalStore(mdLive.subscribe, mdLive.get);

/** The editor chunk, fetched once on the first Markdown field. */
let loading: Promise<typeof import("./editor")> | null = null;
export const loadMdEditor = () => (loading ??= import("./editor"));

/** Mounts the live editor into a node; `options` is read through a ref so callbacks stay current.
 *  `failed` is set when the editor chunk could not be loaded. */
export function useMdEditor(
  node: HTMLElement | null,
  doc: string,
  options: () => Omit<MdOptions, "doc">,
): { handle: MdHandle | null; failed: boolean } {
  const [handle, setHandle] = useState<MdHandle | null>(null),
    [failed, setFailed] = useState(false),
    latest = useRef(options);
  latest.current = options;
  useEffect(() => {
    if (!node) return;
    let closed = false,
      mounted: MdHandle | null = null;
    loadMdEditor().then(
      ({ createMdEditor }) => {
        if (closed) return;
        const o = latest.current();
        mounted = createMdEditor(node, {
          ...o,
          doc,
          onChange: (text) => latest.current().onChange(text),
          onEnter: () => latest.current().onEnter?.() ?? false,
          onFocus: () => latest.current().onFocus?.(),
          onBlur: () => latest.current().onBlur?.(),
        });
        setHandle(mounted);
      },
      (error) => {
        console.error("[Workbench] Markdown editor failed to load", error);
        loading = null;
        if (!closed) setFailed(true);
      },
    );
    return () => {
      closed = true;
      mounted?.destroy();
      setHandle(null);
    };
    // The document is read once at mount; later values arrive through handle.set.
  }, [node]);
  return { handle, failed };
}

/**
 * A Markdown text field: the live-preview editor, or a plain textarea when live preview is off (or
 * its chunk failed to load). Height follows the content between `rows` and the field's max-height.
 */
export function MdField({
  value,
  onChange,
  label,
  placeholder,
  className = "",
  rows = 4,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  label: string;
  placeholder?: string;
  className?: string;
  rows?: number;
  disabled?: boolean;
}) {
  const [node, setNode] = useState<HTMLDivElement | null>(null);
  const live = useMdLive() && !disabled;
  const { handle, failed } = useMdEditor(live ? node : null, value, () => ({ label, placeholder, onChange }));
  useLayoutEffect(() => {
    handle?.set(value);
  }, [handle, value]);
  if (live && !failed)
    return (
      <div
        ref={setNode}
        className={`wb-md wb-native-embedded ${className}`}
        style={{ "--wb-md-rows": rows } as React.CSSProperties}
      />
    );
  return (
    <textarea
      className={className}
      aria-label={label}
      placeholder={placeholder}
      rows={rows}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}
