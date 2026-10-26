import React, { useEffect, useId, useLayoutEffect, useRef, useState, createContext, useContext } from "react";
import { createPortal } from "react-dom";
import { ChevronDown, ChevronRight, PanelLeftClose, PanelLeftOpen, Plus, RotateCcw, Search } from "./icons";
import type { Item } from "../host/types";
import { Empty, SearchBox } from "./common";
import { Select } from "./Select";
import { usePresence } from "./Motion";
import { groupItems, ungroupedLabel } from "../host/organize";

export const ResourceRailContext = createContext<{
  open: boolean;
  setOpen: (open: boolean) => void;
  target: HTMLElement | null;
} | null>(null);
/** Extras the side-panel rail shows around the list (boards "Panel*"). */
export interface RailExtras {
  /** Controls above the search box, e.g. the world-book scope switch. */
  top?: React.ReactNode;
  /** A quiet count under the search box. */
  caption?: string;
  /** Group rows by `item.group` under folding headers (connection profiles, world books). */
  grouped?: boolean;
  /** A group header's checkbox switches every unarchived book in it (multi-select lists only). */
  groupToggle?: (ids: string[], on: boolean) => void;
  /** Archived items fold under 已归档 at the foot of the list, each with this restore action. */
  restore?: (id: string) => void;
  /** Hide each row's detail line. */
  plain?: boolean;
  /** Show each item's image or initial (personas). */
  avatars?: boolean;
  create?: { label: string; run: () => void };
}
/** Sidebar lists occupy a separate rail; independent editors keep their title picker. */
export function ResourcePicker({
  label,
  items,
  id,
  active,
  choose,
  use,
  sortable = false,
  disabled = false,
  multiple,
  scopeLabel,
  extras,
}: {
  label: string;
  items: Item[];
  id: string;
  active: string;
  choose: (id: string) => void;
  use: (id: string) => void;
  sortable?: boolean;
  disabled?: boolean;
  multiple?: { selected: string[]; toggle: (id: string, on: boolean) => void };
  scopeLabel?: string;
  extras?: RailExtras;
}) {
  const rail = useContext(ResourceRailContext);
  const [popupOpen, setPopupOpen] = useState(false),
    [query, setQuery] = useState(""),
    [sort, setSort] = useState("name");
  const open = rail ? rail.open : popupOpen,
    setOpen = rail ? rail.setOpen : setPopupOpen;
  const presence = usePresence(open ? true : null);
  const button = useRef<HTMLButtonElement>(null),
    popup = useRef<HTMLDivElement>(null),
    popupId = useId();
  const [position, setPosition] = useState({ left: 0, top: 0, width: 300, maxHeight: 500 });
  const current = items.find((x) => x.id === id);
  useLayoutEffect(() => {
    if (!open || rail) return;
    const place = () => {
      const r = button.current!.getBoundingClientRect(),
        width = Math.min(340, innerWidth - 24);
      setPosition({
        left: Math.max(12, Math.min(r.left, innerWidth - width - 12)),
        top: r.bottom + 8,
        width,
        maxHeight: Math.min(500, innerHeight - r.bottom - 20),
      });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open, rail]);
  useEffect(() => {
    if (!open || rail) return;
    const outside = (e: PointerEvent) => {
      if (!button.current?.contains(e.target as Node) && !popup.current?.contains(e.target as Node))
        setOpen(false);
    };
    document.addEventListener("pointerdown", outside);
    popup.current?.querySelector("input")?.focus();
    return () => document.removeEventListener("pointerdown", outside);
  }, [open, rail]);
  const close = () => {
    setOpen(false);
    button.current?.focus();
  };
  const matches = items
    .filter((x) => `${x.name} ${x.detail} ${x.group ?? ""}`.toLowerCase().includes(query.toLowerCase()))
    .sort((a, b) => (sortable ? a.name.localeCompare(b.name, "zh") * (sort === "name" ? 1 : -1) : 0));
  // Archived items never show as choices; the rail lists them in a fold of their own.
  const list = matches.filter((x) => !x.archived),
    archived = matches.filter((x) => x.archived);
  const sections = extras?.grouped ? groupItems(list) : [{ name: "", items: list }];
  return (
    <div className="wb-resource-picker">
      {rail ? (
        <h2 className="wb-panel-title">
          <button
            ref={button}
            aria-label={`${open ? "收起" : "展开"}${label}资源列表`}
            title={open ? "收起资源列表" : "展开资源列表"}
            aria-expanded={open}
            aria-controls={open ? popupId : undefined}
            onClick={() => {
              setOpen(!open);
              setQuery("");
            }}
          >
            <span>{current?.name || label}</span>
            {open ? <PanelLeftClose size={15} /> : <PanelLeftOpen size={15} />}
          </button>
        </h2>
      ) : (
        <button
          ref={button}
          className="wb-resource-title"
          aria-label={`选择${label}`}
          aria-expanded={open}
          aria-controls={open ? popupId : undefined}
          disabled={disabled}
          onClick={() => {
            setOpen(!open);
            setQuery("");
          }}
        >
          <span>{current?.name || `选择${label}`}</span>
          <ChevronDown size={14} />
        </button>
      )}
      {rail?.target &&
        presence.value &&
        createPortal(
          <ResourceRail
            railId={popupId}
            label={label}
            items={list}
            archived={archived}
            id={id}
            active={active}
            choose={choose}
            disabled={disabled}
            multiple={multiple}
            extras={extras}
            query={query}
            setQuery={setQuery}
            exiting={presence.exiting}
          />,
          rail.target,
        )}
      {!rail &&
        presence.value &&
        createPortal(
          <div
            ref={popup}
            id={popupId}
            className="wb-ui wb-resource-menu"
            data-wb-exiting={presence.exiting || undefined}
            inert={presence.exiting}
            role="dialog"
            aria-label={`${label}选择`}
            style={position}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                e.preventDefault();
                e.stopPropagation();
                close();
              }
            }}
          >
            <SearchBox value={query} onChange={setQuery} placeholder={`搜索${label}`} />
            {sortable && (
              <Select aria-label={`${label}排序`} value={sort} onChange={(e) => setSort(e.target.value)}>
                <option value="name">名称 A–Z</option>
                <option value="reverse">名称 Z–A</option>
              </Select>
            )}
            {multiple && (
              <p className="wb-caption">{scopeLabel || "启用世界书"} · 可多选，点击名称浏览条目</p>
            )}
            <div className="wb-picker-list">
              {sections.map((section) => (
                <React.Fragment key={section.name || "all"}>
                  {extras?.grouped && (sections.length > 1 || section.name) && (
                    <p className="wb-caption wb-picker-group">
                      {multiple && extras.groupToggle && (
                        <GroupCheck
                          rows={section.items}
                          selected={multiple.selected}
                          disabled={disabled}
                          title={section.name || ungroupedLabel}
                          toggle={extras.groupToggle}
                        />
                      )}
                      {section.name || ungroupedLabel}
                    </p>
                  )}
                  {section.items.map((x) => (
                    <div key={x.id} className={`wb-resource-choice ${id === x.id ? "is-active" : ""}`}>
                      {x.image && <img src={x.image} alt="" />}
                      {multiple ? (
                        <input
                          type="checkbox"
                          aria-label={`启用世界书 ${x.name}`}
                          checked={multiple.selected.includes(x.id)}
                          disabled={disabled}
                          onChange={(e) => multiple.toggle(x.id, e.target.checked)}
                        />
                      ) : (
                        <button
                          className="wb-picker-apply"
                          title={`使用 ${x.name}`}
                          aria-label={`使用 ${x.name}`}
                          disabled={disabled}
                          onClick={() => {
                            use(x.id);
                            close();
                          }}
                        >
                          <span className={`wb-choice-state ${active === x.id ? "is-current" : ""}`} />
                        </button>
                      )}
                      <button
                        className="wb-picker-copy"
                        title={x.name}
                        onClick={() => {
                          choose(x.id);
                          close();
                        }}
                      >
                        <strong>{x.name}</strong>
                        {x.detail && <small>{x.detail}</small>}
                      </button>
                      <ChevronRight size={13} />
                    </div>
                  ))}
                </React.Fragment>
              ))}
              {!list.length && <Empty>没有符合条件的{label}</Empty>}
            </div>
          </div>,
          button.current?.closest("dialog[open]") ?? document.body,
        )}
    </div>
  );
}

/** The list column inside the right panel card: search, rows, and a quiet "new" action at the foot. */
function ResourceRail({
  railId,
  label,
  items,
  archived,
  id,
  active,
  choose,
  disabled,
  multiple,
  extras = {},
  query,
  setQuery,
  exiting,
}: {
  railId: string;
  label: string;
  items: Item[];
  archived: Item[];
  id: string;
  active: string;
  choose: (id: string) => void;
  disabled: boolean;
  multiple?: { selected: string[]; toggle: (id: string, on: boolean) => void };
  extras?: RailExtras;
  query: string;
  setQuery: (query: string) => void;
  exiting: boolean;
}) {
  const row = (x: Item) => {
    const viewing = id === x.id,
      on = multiple ? multiple.selected.includes(x.id) : active === x.id;
    return (
      <li key={x.id} className={`wb-rail-row ${viewing ? "is-viewing" : ""} ${on ? "is-on" : ""}`}>
        {multiple && (
          <input
            type="checkbox"
            aria-label={`启用世界书 ${x.name}`}
            checked={on}
            disabled={disabled}
            onChange={(e) => multiple.toggle(x.id, e.target.checked)}
          />
        )}
        <button
          className="wb-rail-open"
          aria-current={viewing || undefined}
          title={on && !multiple ? `${x.name} · 使用中` : x.name}
          onClick={() => choose(x.id)}
        >
          {extras.avatars ? (
            <span className="wb-rail-avatar" aria-hidden="true">
              {x.image ? <img src={x.image} alt="" /> : x.name.slice(0, 1)}
            </span>
          ) : (
            !multiple && <span className="wb-rail-dot" aria-hidden="true" />
          )}
          <span className="wb-rail-copy">
            <span className="wb-rail-name">{x.name}</span>
            {x.detail && !extras.grouped && !extras.plain && <small>{x.detail}</small>}
          </span>
        </button>
      </li>
    );
  };
  const [folded, setFolded] = useState<Set<string>>(() => new Set()),
    [showArchived, setShowArchived] = useState(false);
  const sections = extras.grouped ? groupItems(items) : [{ name: "", items }];
  // A search shows every match: folds and the archived fold open while a query is typed.
  const searching = !!query.trim(),
    archivedOpen = showArchived || (searching && !!archived.length);
  const fold = (name: string) =>
    setFolded((all) => {
      const next = new Set(all);
      next.has(name) ? next.delete(name) : next.add(name);
      return next;
    });
  const header = (name: string, rows: Item[]) => {
    const open = searching || !folded.has(name),
      title = name || ungroupedLabel;
    const on = multiple ? rows.filter((x) => multiple.selected.includes(x.id)).length : 0;
    return (
      <div className="wb-rail-group">
        {multiple && extras.groupToggle && (
          <GroupCheck
            rows={rows}
            selected={multiple.selected}
            disabled={disabled}
            title={title}
            toggle={extras.groupToggle}
          />
        )}
        <button
          className="wb-rail-group-fold"
          aria-expanded={open}
          aria-label={`${open ? "收起" : "展开"}分组 ${title}`}
          disabled={searching}
          onClick={() => fold(name)}
        >
          {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          <span>{title}</span>
          <small>{multiple ? `${on}/${rows.length}` : rows.length}</small>
        </button>
      </div>
    );
  };
  return (
    <nav
      id={railId}
      className="wb-ui wb-rail"
      aria-label={`${label}列表`}
      data-wb-exiting={exiting || undefined}
      inert={exiting}
    >
      {extras.top}
      <label className="wb-rail-search">
        <Search size={14} />
        <input
          aria-label={`搜索${label}`}
          placeholder="搜索"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </label>
      {extras.caption && <p className="wb-rail-caption">{extras.caption}</p>}
      <div className="wb-rail-scroll">
        {sections.map(({ name, items: rows }) => (
          <React.Fragment key={name || "all"}>
            {extras.grouped && (sections.length > 1 || name) && header(name, rows)}
            {(!extras.grouped || searching || !folded.has(name)) && (
              <ul className="wb-rail-list">{rows.map(row)}</ul>
            )}
          </React.Fragment>
        ))}
        {!items.length && <p className="wb-rail-empty">没有符合条件的{label}</p>}
        {extras.restore && !!archived.length && (
          <div className="wb-rail-archived">
            <button
              className="wb-rail-group-fold"
              aria-expanded={archivedOpen}
              disabled={searching}
              onClick={() => setShowArchived(!showArchived)}
            >
              {archivedOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
              <span>已归档</span>
              <small>{archived.length}</small>
            </button>
            {archivedOpen && (
              <ul className="wb-rail-list" aria-label={`已归档${label}`}>
                {archived.map((x) => (
                  <li key={x.id} className={`wb-rail-row is-archived ${id === x.id ? "is-viewing" : ""}`}>
                    <button className="wb-rail-open" title={x.name} onClick={() => choose(x.id)}>
                      <span className="wb-rail-copy">
                        <span className="wb-rail-name">{x.name}</span>
                      </span>
                    </button>
                    <button
                      className="wb-rail-restore"
                      aria-label={`恢复 ${x.name}`}
                      title="取消归档"
                      disabled={disabled}
                      onClick={() => extras.restore!(x.id)}
                    >
                      <RotateCcw size={13} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
      {extras.create && (
        <button className="wb-rail-new" disabled={disabled} onClick={extras.create.run}>
          <Plus size={15} />
          {extras.create.label}
        </button>
      )}
    </nav>
  );
}

/** A group's checkbox: checked when every row is enabled, mixed when some are; switches them all. */
export function GroupCheck({
  rows,
  selected,
  disabled,
  title,
  toggle,
}: {
  rows: Item[];
  selected: string[];
  disabled: boolean;
  title: string;
  toggle: (ids: string[], on: boolean) => void;
}) {
  const on = rows.filter((x) => selected.includes(x.id)).length,
    all = on === rows.length;
  return (
    <input
      type="checkbox"
      aria-label={`整组启用 ${title}`}
      title={all ? "整组停用" : "整组启用"}
      checked={all}
      ref={(node) => {
        if (node) node.indeterminate = on > 0 && !all;
      }}
      disabled={disabled}
      onChange={(e) =>
        toggle(
          rows.map((x) => x.id),
          e.target.checked,
        )
      }
    />
  );
}
