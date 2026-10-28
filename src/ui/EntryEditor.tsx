import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ChevronDown, Expand, X } from "./icons";

export function useMobileLayout() {
  const [mobile, setMobile] = useState(() => matchMedia("(max-width: 1023px)").matches);
  useEffect(() => {
    const media = matchMedia("(max-width: 1023px)");
    const changed = () => setMobile(media.matches);
    media.addEventListener("change", changed);
    return () => media.removeEventListener("change", changed);
  }, []);
  return mobile;
}

/** One editor node through half/full height; a native modal keeps mobile background controls inert. */
export function EntryEditor({
  open,
  title,
  onClose,
  children,
  footer,
  busy = false,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
  busy?: boolean;
}) {
  const mobile = useMobileLayout(),
    dialog = useRef<HTMLDialogElement>(null),
    [full, setFull] = useState(false),
    origin = useRef<HTMLElement | null>(null),
    drag = useRef<{ pointer: number; y: number; height: number; max: number; time: number } | null>(null);
  useLayoutEffect(() => {
    const node = dialog.current!;
    if (!open) {
      if (node.open) node.close();
      setFull(false);
      return;
    }
    origin.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    if (mobile) node.showModal();
    else node.setAttribute("open", "");
    return () => {
      if (node.open) node.close();
      if (mobile && origin.current?.isConnected) origin.current.focus({ preventScroll: true });
    };
  }, [open, mobile]);
  useEffect(() => {
    if (!mobile || !open) return;
    const keyboard = () => {
      const viewport = window.visualViewport;
      if (viewport && innerHeight - viewport.height > 140) setFull(true);
    };
    window.visualViewport?.addEventListener("resize", keyboard);
    return () => window.visualViewport?.removeEventListener("resize", keyboard);
  }, [mobile, open]);
  const finishDrag = (event: React.PointerEvent, cancel = false) => {
    const current = drag.current;
    if (!current || current.pointer !== event.pointerId) return;
    drag.current = null;
    const node = dialog.current!;
    node.style.removeProperty("--wb-entry-height");
    delete node.dataset.dragging;
    if (cancel) return;
    const distance = current.y - event.clientY,
      speed = distance / Math.max(1, event.timeStamp - current.time);
    if (distance > 48 || speed > 0.4) setFull(true);
    else if (distance < -64 || speed < -0.5) {
      if (full) setFull(false);
      else onClose();
    }
  };
  return (
    <dialog
      ref={dialog}
      className={`wb-ui wb-entry-editor ${mobile ? "is-mobile" : "is-inline"} ${full ? "is-full" : ""}`}
      aria-label={title}
      onCancel={(event) => {
        event.preventDefault();
        event.stopPropagation();
        if (full) setFull(false);
        else onClose();
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") event.stopPropagation();
      }}
    >
      <header
        className="wb-entry-editor-head"
        onPointerDown={(event) => {
          if (!mobile || event.button !== 0 || (event.target as Element).closest("button")) return;
          const node = dialog.current!;
          drag.current = {
            pointer: event.pointerId,
            y: event.clientY,
            height: node.getBoundingClientRect().height,
            max: window.visualViewport?.height ?? innerHeight,
            time: event.timeStamp,
          };
          event.currentTarget.setPointerCapture(event.pointerId);
          node.dataset.dragging = "";
        }}
        onPointerMove={(event) => {
          const current = drag.current;
          if (!current || current.pointer !== event.pointerId) return;
          dialog.current!.style.setProperty(
            "--wb-entry-height",
            `${Math.max(160, Math.min(current.max, current.height + current.y - event.clientY))}px`,
          );
        }}
        onPointerUp={(event) => finishDrag(event)}
        onPointerCancel={(event) => finishDrag(event, true)}
        onLostPointerCapture={(event) => finishDrag(event, true)}
      >
        {mobile && <span className="wb-entry-editor-grip" aria-hidden="true" />}
        <strong>{title}</strong>
        {mobile && (
          <button
            type="button"
            className="wb-panel-icon"
            autoFocus
            aria-label={full ? "收起到半屏" : "全屏编辑"}
            onClick={() => setFull(!full)}
          >
            {full ? <ChevronDown size={18} /> : <Expand size={18} />}
          </button>
        )}
        <button type="button" className="wb-panel-icon" aria-label="返回条目列表" onClick={onClose}>
          <X size={18} />
        </button>
      </header>
      <fieldset disabled={busy} className="wb-entry-editor-body">
        {children}
      </fieldset>
      {footer && <div className="wb-entry-editor-footer">{footer}</div>}
    </dialog>
  );
}
