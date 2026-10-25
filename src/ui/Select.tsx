import React, { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronDown } from "./icons";
import { usePresence } from "./Motion";

type Props = React.SelectHTMLAttributes<HTMLSelectElement>;
type Option = { value: string; label: React.ReactNode; text: string; disabled: boolean };
function optionsFrom(children: React.ReactNode, disabled = false): Option[] {
  return React.Children.toArray(children).flatMap((child) => {
    if (!React.isValidElement<Props & { label?: string }>(child)) return [];
    const props = child.props;
    if (child.type !== "option") return optionsFrom(props.children, disabled || !!props.disabled);
    const text = React.Children.toArray(props.children).join("");
    return [
      {
        value: String(props.value ?? text),
        label: props.children,
        text,
        disabled: disabled || !!props.disabled,
      },
    ];
  });
}

/** Paper listbox over a real select: callers still receive its native change event. */
export function Select({ children, className = "", value, onChange, disabled, ...props }: Props) {
  const options = optionsFrom(children),
    native = useRef<HTMLSelectElement>(null),
    trigger = useRef<HTMLButtonElement>(null),
    menu = useRef<HTMLDivElement>(null);
  const id = useId(),
    [open, setOpen] = useState(false),
    [active, setActive] = useState(0),
    [place, setPlace] = useState({ left: 0, top: 0, width: 0, maxHeight: 260 });
  const presence = usePresence(open ? true : null);
  const current = options.findIndex(
    (o) => o.value === String(value ?? props.defaultValue ?? options[0]?.value),
  );
  const blocked = () => !!disabled || !!trigger.current?.closest("fieldset:disabled");
  const show = () => {
    if (!blocked()) {
      setActive(Math.max(0, current));
      setOpen(true);
    }
  };
  const choose = (index: number) => {
    const option = options[index];
    if (!option || option.disabled || blocked()) return;
    const node = native.current!;
    if (node.value !== option.value) {
      node.value = option.value;
      node.dispatchEvent(new Event("change", { bubbles: true }));
    }
    setOpen(false);
    trigger.current?.focus();
  };
  useLayoutEffect(() => {
    if (!open) return;
    const position = () => {
      const rect = trigger.current!.getBoundingClientRect(),
        width = Math.min(Math.max(rect.width, 180), innerWidth - 16);
      const below = innerHeight - rect.bottom - 14,
        above = rect.top - 14;
      const downward = below >= 150 || below >= above;
      const height = Math.min(260, Math.max(80, downward ? below : above));
      if (menu.current) menu.current.style.width = `${width}px`;
      const renderedHeight = Math.min(height, (menu.current?.scrollHeight ?? height) + 2);
      setPlace({
        left: Math.max(8, Math.min(rect.left, innerWidth - width - 8)),
        top: downward ? rect.bottom + 6 : rect.top - renderedHeight - 6,
        width,
        maxHeight: height,
      });
    };
    position();
    window.addEventListener("resize", position);
    window.addEventListener("scroll", position, true);
    return () => {
      window.removeEventListener("resize", position);
      window.removeEventListener("scroll", position, true);
    };
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const outside = (e: PointerEvent) => {
      if (!trigger.current?.contains(e.target as Node) && !menu.current?.contains(e.target as Node))
        setOpen(false);
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open]);
  useEffect(() => {
    if (open)
      menu.current?.querySelector(`[id="${id}-option-${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active, open]);
  const portal = trigger.current?.closest(".wb-resource-menu,.wb-popover,dialog[open]") ?? document.body;
  return (
    <span className={`wb-select ${className}`}>
      <select
        {...props}
        className="wb-select-native"
        ref={native}
        value={value}
        onChange={onChange}
        disabled={disabled}
        aria-label={undefined}
        aria-hidden="true"
        tabIndex={-1}
      >
        {children}
      </select>
      <button
        type="button"
        ref={trigger}
        className="wb-select-trigger"
        role="combobox"
        aria-label={props["aria-label"]}
        title={props.title}
        aria-expanded={open}
        aria-controls={open ? `${id}-list` : undefined}
        aria-haspopup="listbox"
        aria-activedescendant={open ? `${id}-option-${active}` : undefined}
        disabled={disabled}
        onClick={() => (open ? setOpen(false) : show())}
        onBlur={(e) => {
          if (!menu.current?.contains(e.relatedTarget as Node)) setOpen(false);
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape" && open) {
            e.preventDefault();
            setOpen(false);
            e.stopPropagation();
            return;
          }
          if (e.key === "Tab") {
            setOpen(false);
            return;
          }
          if (["Enter", " "].includes(e.key)) {
            e.preventDefault();
            if (open) choose(active);
            else show();
            return;
          }
          if (["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) {
            e.preventDefault();
            if (!open) {
              show();
              return;
            }
            const step = e.key === "ArrowUp" || e.key === "End" ? -1 : 1;
            let next = e.key === "Home" ? 0 : e.key === "End" ? options.length - 1 : active + step;
            while (next >= 0 && next < options.length && options[next].disabled) next += step;
            if (next >= 0 && next < options.length) setActive(next);
          } else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey) {
            const next = options.findIndex(
              (o, i) => i > active && !o.disabled && o.text.toLowerCase().startsWith(e.key.toLowerCase()),
            );
            if (next >= 0) {
              if (!open) show();
              setActive(next);
            }
          }
        }}
      >
        <span key={String(value)}>{options[current]?.label ?? "请选择"}</span>
        <ChevronDown size={14} />
      </button>
      {presence.value &&
        createPortal(
          <div
            ref={menu}
            className="wb-ui wb-select-menu"
            data-wb-exiting={presence.exiting || undefined}
            inert={presence.exiting}
            id={`${id}-list`}
            role="listbox"
            aria-label={props["aria-label"]}
            style={place}
          >
            {options.map((option, i) => (
              <button
                key={`${option.value}-${i}`}
                type="button"
                role="option"
                id={`${id}-option-${i}`}
                aria-selected={i === current}
                disabled={option.disabled}
                tabIndex={-1}
                className={`${i === current ? "is-selected" : ""} ${i === active ? "is-highlighted" : ""}`}
                onMouseMove={() => setActive(i)}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => choose(i)}
              >
                <span className="wb-option-state" />
                <span>{option.label}</span>
              </button>
            ))}
          </div>,
          portal,
        )}
    </span>
  );
}
