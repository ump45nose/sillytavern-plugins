import React, { useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { X } from "./icons";
export function Popover({
  anchor,
  title,
  onClose,
  children,
  tools,
  exiting,
  className = "",
}: {
  anchor: HTMLElement;
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  tools?: React.ReactNode;
  exiting?: boolean;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null),
    close = useRef(onClose),
    [place, setPlace] = useState({ left: 0, top: 0, visibility: "hidden" as "hidden" | "visible" });
  close.current = onClose;
  useLayoutEffect(() => {
    const el = ref.current!;
    const position = () => {
      const a = anchor.getBoundingClientRect(),
        p = el.getBoundingClientRect(),
        above = a.top - p.height - 8;
      setPlace({
        left: Math.max(10, Math.min(a.left, innerWidth - p.width - 10)),
        top: Math.max(10, Math.min(above >= 10 ? above : a.bottom + 8, innerHeight - p.height - 10)),
        visibility: "visible",
      });
    };
    position();
    const focusFrame = requestAnimationFrame(() => {
      const target = el.querySelector<HTMLElement>(
        "input:not([type=file]):not([type=hidden]),.wb-pop-row:not(:disabled),button:not(:disabled)",
      );
      target?.focus({ preventScroll: true });
    });
    const observer = new ResizeObserver(position);
    observer.observe(el);
    const outside = (e: PointerEvent) => {
      if (!el.inert && !el.contains(e.target as Node) && !anchor.contains(e.target as Node)) close.current();
    };
    const key = (e: KeyboardEvent) => {
      if (!el.inert && e.key === "Escape") {
        if (el.querySelector('.wb-select-trigger[aria-expanded="true"]')) return;
        e.preventDefault();
        e.stopImmediatePropagation();
        close.current();
        anchor.focus();
      }
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", key, true);
    window.addEventListener("resize", position);
    window.addEventListener("scroll", position, true);
    return () => {
      cancelAnimationFrame(focusFrame);
      if (el.contains(document.activeElement)) anchor.focus({ preventScroll: true });
      observer.disconnect();
      anchor.setAttribute("aria-expanded", "false");
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", key, true);
      window.removeEventListener("resize", position);
      window.removeEventListener("scroll", position, true);
    };
  }, [anchor]);
  useLayoutEffect(() => {
    anchor.setAttribute("aria-expanded", String(!exiting));
  }, [anchor, exiting]);
  return createPortal(
    <div
      ref={ref}
      className={`wb-ui wb-popover ${className}`}
      data-wb-exiting={exiting || undefined}
      inert={exiting}
      role="dialog"
      aria-modal="false"
      aria-label={title}
      style={place}
    >
      <header>
        <strong>{title}</strong>
        <span className="wb-grow" />
        {tools}
        <button className="wb-icon" aria-label="关闭弹出框" onClick={onClose}>
          <X size={16} />
        </button>
      </header>
      {children}
    </div>,
    anchor.closest("dialog[open]") || document.body,
  );
}
