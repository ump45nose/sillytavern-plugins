import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import type { HostAdapter } from "../host/adapter";
import { bus } from "../host/bus";
import {
  DEFAULT_OPTIONS_PROMPT,
  type OptionAction,
  type OptionSource,
  type StoryOption,
} from "../host/options";
import { useHostSlices } from "./common";
import { ChevronDown, Lightbulb, SlidersHorizontal, X } from "./icons";
import { Popover } from "./Popover";
import { Select } from "./Select";

export function useOptionsState(host: HostAdapter) {
  return useSyncExternalStore(host.options.subscribe, () => host.options.state);
}

const actionHint = (action: OptionAction) => (action === "send" ? "点选即发送" : "点选填入输入框");

/** One option: its number, its title, and its detail on one line (or in full). */
function OptionRow({
  option,
  index,
  full,
  shortcut,
  onChoose,
  onPeek,
}: {
  option: StoryOption;
  index: number;
  full?: boolean;
  shortcut?: string;
  onChoose: () => void;
  onPeek?: (node: HTMLElement | null) => void;
}) {
  return (
    <button
      className="wb-story-row"
      style={{ "--wb-i": index } as React.CSSProperties}
      aria-keyshortcuts={shortcut?.replace(" ", "+")}
      onClick={onChoose}
      onPointerEnter={(e) => onPeek?.(e.currentTarget)}
      onPointerLeave={() => onPeek?.(null)}
      onFocus={(e) => e.currentTarget.matches(":focus-visible") && onPeek?.(e.currentTarget)}
      onBlur={() => onPeek?.(null)}
    >
      <span className="wb-story-num" aria-hidden="true">
        {index + 1}
      </span>
      <span className="wb-story-text">
        <strong>{option.title}</strong>
        {option.detail && <span className={full ? "is-full" : ""}>{option.detail}</span>}
      </span>
      {shortcut && (
        <kbd className="wb-story-key" aria-hidden="true">
          {shortcut}
        </kbd>
      )}
    </button>
  );
}

/**
 * Noval: a folding card over the composer, in the native form's flow so the reading column makes
 * room. A row shows its detail on one line and the rest on hover; Alt+1…9 picks one while the input
 * is empty. On the phone the card is a tag that opens the options sheet.
 */
export function ComposerOptions({ host, mobile }: { host: HostAdapter; mobile: boolean }) {
  useHostSlices(host, ["prefs"]);
  const state = useOptionsState(host),
    collapsed = !!host.prefs().optionsCollapsed,
    [slot, setSlot] = useState<HTMLElement | null>(null),
    [peek, setPeek] = useState(-1),
    [config, setConfig] = useState<HTMLElement | null>(null);
  const { items } = state,
    choose = (option: StoryOption) => {
      setPeek(-1);
      if (host.options.choose(option, "novel") === "fill")
        requestAnimationFrame(() => document.getElementById("send_textarea")?.focus());
    };
  useLayoutEffect(() => {
    const form = document.getElementById("send_form"),
      node = document.createElement("div");
    node.className = "wb-story-options wb-ui";
    form?.before(node);
    setSlot(node);
    return () => node.remove();
  }, []);
  useEffect(() => setPeek(-1), [state.key, collapsed]);
  // Alt+1…9 while the input is empty; another field keeps its own keys.
  const latest = useRef({ items, choose });
  latest.current = { items, choose };
  useEffect(() => {
    if (mobile) return;
    const key = (e: KeyboardEvent) => {
      const digit = /^Digit([1-9])$/.exec(e.code);
      if (!digit || !e.altKey || e.ctrlKey || e.metaKey || e.shiftKey || e.repeat) return;
      const input = document.getElementById("send_textarea") as HTMLTextAreaElement | null,
        target = e.target as Element | null,
        option = latest.current.items[Number(digit[1]) - 1];
      if (!option || !input || input.value.trim()) return;
      // The composer's Markdown editor is the input too.
      if (
        target !== input &&
        !target?.closest(".wb-composer-md") &&
        target?.closest("input,textarea,select,[contenteditable=true]")
      )
        return;
      if (document.querySelector("dialog[open],.wb-popover,[role=listbox]")) return;
      e.preventDefault();
      latest.current.choose(option);
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [mobile]);
  if (!slot || !items.length) return null;
  if (mobile)
    return createPortal(
      <button className="wb-story-tag" aria-haspopup="dialog" onClick={() => bus.emit("story-options")}>
        <Lightbulb size={14} aria-hidden="true" />
        剧情选项
        <span>{items.length}</span>
      </button>,
      slot,
    );
  // The full detail shows over the card when the row's line cuts it short.
  const peekAt = (index: number, node: HTMLElement | null) => {
    const line = node?.querySelector<HTMLElement>(".wb-story-text > span");
    setPeek(line && line.scrollWidth > line.clientWidth + 1 ? index : -1);
  };
  const peeked = items[peek];
  return createPortal(
    <section className={`wb-story-card ${collapsed ? "is-collapsed" : ""}`} aria-label="剧情选项">
      <header>
        <button
          className="wb-story-toggle"
          aria-expanded={!collapsed}
          onClick={() => host.preference({ optionsCollapsed: !collapsed })}
        >
          <Lightbulb size={14} aria-hidden="true" />
          <span>
            剧情选项 <em>· {items.length}</em>
          </span>
          {!collapsed && <small>{actionHint(state.config.novel)}</small>}
          <ChevronDown size={15} aria-hidden="true" className="wb-story-chevron" />
        </button>
        <button
          className="wb-story-config"
          aria-label="剧情选项设置"
          title="剧情选项设置"
          aria-expanded={!!config}
          onClick={(e) => setConfig(config ? null : e.currentTarget)}
        >
          <SlidersHorizontal size={14} />
        </button>
      </header>
      {!collapsed && (
        <div className="wb-story-list" role="group" aria-label="选择一个选项">
          {items.map((option, index) => (
            <OptionRow
              key={index}
              option={option}
              index={index}
              shortcut={index < 9 ? `Alt ${index + 1}` : undefined}
              onChoose={() => choose(option)}
              onPeek={(node) => peekAt(index, node)}
            />
          ))}
        </div>
      )}
      {peeked && (
        <div className="wb-story-peek" role="tooltip">
          <strong>{peeked.title}</strong>
          <span>{peeked.detail}</span>
        </div>
      )}
      {config && <OptionsPopover host={host} anchor={config} onClose={() => setConfig(null)} />}
    </section>,
    slot,
  );
}

/**
 * RP: a galgame choice. On the latest reply's last page the stage dims and the options stand as glass
 * buttons in the middle of the scene; Esc or × puts them away and the 选项 tag by the input brings
 * them back. The phone opens the options sheet instead, once per reply, and the tag reopens it.
 */
export function useRPChoices(
  host: HostAdapter,
  {
    ending,
    blocked,
    mobile,
    onFill,
  }: {
    /** Reading the latest reply's last page. */
    ending: boolean;
    /** Something else holds the stage (history, editing, focus). */
    blocked: boolean;
    mobile: boolean;
    /** The option went into the input: the band turns into it. */
    onFill: () => void;
  },
) {
  const state = useOptionsState(host),
    { items, key } = state,
    [closed, setClosed] = useState(""),
    [summoned, setSummoned] = useState(""),
    sheetFor = useRef(""),
    panel = useRef<HTMLDivElement>(null);
  const open = !mobile && !blocked && !!items.length && ((ending && closed !== key) || summoned === key);
  const hide = () => {
      setClosed(key);
      setSummoned("");
    },
    choose = (option: StoryOption) => {
      hide();
      if (host.options.choose(option, "rp") === "fill") onFill();
    };
  useEffect(() => {
    if (mobile && ending && !blocked && items.length && sheetFor.current !== key) {
      sheetFor.current = key;
      bus.emit("story-options");
    }
  }, [mobile, ending, blocked, items.length, key]);
  const latest = useRef({ items, choose, hide });
  latest.current = { items, choose, hide };
  useEffect(() => {
    if (!open) return;
    const keydown = (e: KeyboardEvent) => {
      if (
        e.ctrlKey ||
        e.metaKey ||
        e.altKey ||
        document.querySelector("dialog[open],.wb-popover,[role=listbox]")
      )
        return;
      const target = e.target as Element | null;
      if (target?.closest("input,textarea,select,[contenteditable=true]") && e.key !== "Escape") return;
      const buttons = [...(panel.current?.querySelectorAll<HTMLElement>(".wb-story-row") ?? [])],
        at = buttons.indexOf(document.activeElement as HTMLElement),
        digit = /^[1-9]$/.test(e.key) ? latest.current.items[Number(e.key) - 1] : undefined;
      if (e.key === "Escape") latest.current.hide();
      else if (digit) latest.current.choose(digit);
      else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        const step = e.key === "ArrowDown" ? 1 : -1;
        buttons[
          at < 0 ? (step > 0 ? 0 : buttons.length - 1) : (at + step + buttons.length) % buttons.length
        ]?.focus();
      } else return;
      e.preventDefault();
      e.stopPropagation();
    };
    document.addEventListener("keydown", keydown);
    return () => document.removeEventListener("keydown", keydown);
  }, [open]);
  const overlay = open && (
    <div className="wb-rp-choices wb-ui">
      <div className="wb-rp-choice-veil" aria-hidden="true" />
      <div ref={panel} className="wb-rp-choice-panel" role="dialog" aria-label="选择剧情选项">
        <header>
          <span>{actionHint(state.config.rp)}</span>
          <button aria-label="隐藏剧情选项" title="隐藏（Esc）" onClick={hide}>
            <X size={16} />
          </button>
        </header>
        {items.map((option, index) => (
          <OptionRow key={index} option={option} index={index} onChoose={() => choose(option)} />
        ))}
      </div>
    </div>
  );
  const tag = !!items.length && !open && !blocked && (
    <button
      className="wb-rp-tool is-labelled wb-rp-options-tag"
      aria-label={`剧情选项 · ${items.length}`}
      title="显示剧情选项"
      aria-haspopup="dialog"
      onClick={() => (mobile ? bus.emit("story-options") : (setSummoned(key), setClosed("")))}
    >
      <Lightbulb size={15} />
      选项
      <span>{items.length}</span>
    </button>
  );
  return { overlay, tag };
}

/** The phone's options sheet: every option with its detail in full. */
export function OptionsSheetList({
  host,
  rp,
  onDone,
  onConfig,
}: {
  host: HostAdapter;
  rp: boolean;
  onDone: () => void;
  onConfig: (anchor: HTMLElement) => void;
}) {
  const state = useOptionsState(host),
    layout = rp ? "rp" : "novel";
  useEffect(() => {
    if (!state.items.length) onDone();
  }, [state.items.length]);
  return (
    <>
      <div className="wb-story-sheet" role="group" aria-label="选择一个选项">
        {state.items.map((option, index) => (
          <OptionRow
            key={index}
            option={option}
            index={index}
            full
            onChoose={() => {
              onDone();
              if (host.options.choose(option, layout) === "fill" && rp) bus.emit("rp-reply");
            }}
          />
        ))}
      </div>
      <footer className="wb-story-sheet-foot">
        <span>{actionHint(state.config[layout])}</span>
        <button onClick={(e) => onConfig(e.currentTarget)}>
          <SlidersHorizontal size={15} />
          设置
        </button>
      </footer>
    </>
  );
}

const sources: [OptionSource, string][] = [
  ["off", "关闭"],
  ["model", "模型输出"],
  ["db", "数据库表"],
];
const actions: [OptionAction, string][] = [
  ["fill", "填入输入框"],
  ["send", "直接发送"],
];

/** Where this chat's options come from, what choosing one does, and the prompt that asks for them. */
export function OptionsPopover({
  host,
  anchor,
  onClose,
}: {
  host: HostAdapter;
  anchor: HTMLElement;
  onClose: () => void;
}) {
  const state = useOptionsState(host),
    config = state.config,
    [prompt, setPrompt] = useState(host.options.template()),
    run = (pending: Promise<unknown>) => pending.catch((error) => host.report(error));
  return (
    <Popover anchor={anchor} title="剧情选项" onClose={onClose} className="wb-options-pop">
      <div className="wb-pop-form">
        <span className="wb-pop-label">选项来源 · 本聊天</span>
        <div className="wb-font-choices">
          {sources.map(([source, label]) => (
            <button
              key={source}
              aria-pressed={config.source === source}
              onClick={() => config.source !== source && run(host.options.save({ source }))}
            >
              {label}
            </button>
          ))}
        </div>
        {config.source !== "off" && (
          <>
            <span className="wb-pop-label">点选后 · 本聊天</span>
            <div className="wb-options-after">
              {(
                [
                  ["novel", "Noval"],
                  ["rp", "RP"],
                ] as const
              ).map(([layout, name]) => (
                <div key={layout} role="group" aria-label={`${name} 点选后`}>
                  <span>{name}</span>
                  <div className="wb-font-choices">
                    {actions.map(([action, label]) => (
                      <button
                        key={action}
                        aria-pressed={config[layout] === action}
                        onClick={() =>
                          config[layout] !== action && run(host.options.save({ [layout]: action }))
                        }
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
        {config.source === "db" && (
          <>
            <span className="wb-pop-label">选项表</span>
            <Select
              aria-label="数据库选项表"
              value={config.table}
              onChange={(e) => run(host.options.save({ table: e.target.value }))}
            >
              <option value="">选择一张表</option>
              {[...new Set([...state.tables, ...(config.table ? [config.table] : [])])].map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </Select>
            <p className="wb-options-note">
              只有一行时每列是一个选项；多行时每行是一个选项，第一列作标题，其余作详情。
            </p>
          </>
        )}
        {config.source === "model" && (
          <>
            <span className="wb-pop-label">提示词 · 所有聊天共用</span>
            <textarea
              className="wb-options-prompt"
              aria-label="剧情选项提示词"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
            />
            <div className="wb-options-actions">
              <button
                className="wb-primary"
                disabled={prompt === host.options.template()}
                onClick={() => run(host.options.savePrompt(prompt))}
              >
                保存提示词
              </button>
              <button
                disabled={prompt === DEFAULT_OPTIONS_PROMPT}
                onClick={() => {
                  setPrompt(DEFAULT_OPTIONS_PROMPT);
                  run(host.options.savePrompt(DEFAULT_OPTIONS_PROMPT));
                }}
              >
                恢复默认
              </button>
            </div>
            <p className="wb-options-note">
              模型在回复末尾附带 <code>{"<options>"}</code> 块：阅读时隐藏，下次请求时从历史中去掉。
            </p>
          </>
        )}
        {state.error && config.source !== "off" && <p className="wb-options-note is-error">{state.error}</p>}
      </div>
    </Popover>
  );
}
