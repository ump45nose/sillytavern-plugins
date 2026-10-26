import type { HostAdapter } from "./adapter";
import { ctx } from "./internals";
import {
  expandPlaceholders,
  placeholderComplete,
  type PlaceholderInput,
  type PlaceholderVars,
} from "./placeholders";

/** One scope's variables: a character card (by avatar file), a group chat, or no chat at all. */
export interface PlaceholderScope {
  name: string;
  vars: PlaceholderVars;
}
/** The dialog asking for prompted placeholders; the UI answers through `resolve`. */
export interface PlaceholderRequest {
  inputs: PlaceholderInput[];
  vars: PlaceholderVars;
  resolve: (values: string[] | null) => void;
}

const DEBOUNCE = 600,
  INPUT = "send_textarea",
  HOOKED = Symbol.for("workbench.placeholders.command");
const isInput = (node: EventTarget | null) =>
  node instanceof HTMLElement && (node.id === INPUT || !!node.closest(".wb-composer-md"));
const pending = (text: string) => text.includes("{@");

/**
 * Placeholder variables in the composer and in `/inject`. The draft expands where it is written:
 * typing, `/setinput` from quick replies and automation all land in #send_textarea, so every send
 * path sees the expanded text. Variables are stored per scope in the workbench settings.
 */
export class PlaceholderRuntime {
  /** The input dialog's on/off switch (`{@input:toggle}`); per page, as in the original script. */
  inputOn = true;
  request: PlaceholderRequest | null = null;
  private listeners = new Set<() => void>();
  private timer = 0;
  private busy = false;
  private last = "";
  private composing = false;
  private disposers: (() => void)[] = [];
  constructor(private host: HostAdapter) {
    const on = <K extends keyof DocumentEventMap>(type: K, fn: (e: DocumentEventMap[K]) => void) => {
      document.addEventListener(type, fn, true);
      this.disposers.push(() => document.removeEventListener(type, fn, true));
    };
    on("input", (e) => {
      if ((e.target as HTMLElement)?.id === INPUT) this.schedule();
    });
    on("compositionstart", (e) => {
      if (isInput(e.target)) this.composing = true;
    });
    on("compositionend", (e) => {
      if (!isInput(e.target)) return;
      this.composing = false;
      this.schedule();
    });
    on("keydown", (e) => {
      if (!isInput(e.target) || e.isComposing || this.composing || !pending(this.text())) return;
      // Tab expands at once; Enter would send the raw placeholders, so it expands instead and waits.
      const send = e.key === "Enter" && !e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey;
      if (e.key !== "Tab" && !send) return;
      if (send && !this.ready()) return;
      e.preventDefault();
      e.stopImmediatePropagation();
      void this.flush(true);
    });
    on("click", (e) => {
      if (!(e.target as Element)?.closest?.("#send_but") || !pending(this.text()) || !this.ready()) return;
      e.preventDefault();
      e.stopImmediatePropagation();
      void this.flush(true);
    });
    this.disposers.push(this.wrapInject(), this.wrapButtons(), () => clearTimeout(this.timer));
  }
  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    return () => {
      this.listeners.delete(fn);
    };
  };
  private notify() {
    this.listeners.forEach((fn) => fn());
  }
  dispose() {
    this.disposers.forEach((fn) => fn());
    this.request?.resolve(null);
  }

  /** Where variables go now: the open character's card, the open group, or "default". */
  scope() {
    const c = ctx(),
      character = this.host.snapshot().character;
    if (c.groupId) return { key: "group:" + c.groupId, name: this.host.snapshot().groupName || "群聊" };
    if (character) return { key: character.id, name: character.name };
    return { key: "default", name: "未选择角色" };
  }
  scopes(): Record<string, PlaceholderScope> {
    return ctx().extensionSettings.workbench?.placeholders ?? {};
  }
  vars(key = this.scope().key): PlaceholderVars {
    return this.scopes()[key]?.vars ?? {};
  }
  /** Replaces one scope's variables (an empty map removes the scope) and saves the settings. */
  setVars(key: string, vars: PlaceholderVars, name = this.scopes()[key]?.name ?? this.scope().name) {
    const settings = ctx().extensionSettings.workbench,
      next = { ...(settings.placeholders ?? {}) };
    if (Object.keys(vars).length) next[key] = { name, vars: { ...vars } };
    else delete next[key];
    settings.placeholders = next;
    ctx().saveSettingsDebounced();
    this.notify();
  }
  clearAll() {
    ctx().extensionSettings.workbench.placeholders = {};
    ctx().saveSettingsDebounced();
    this.notify();
  }
  setInputOn(on: boolean) {
    this.inputOn = on;
    this.notify();
  }

  /** Expands text in the current scope, storing what it set; one expansion (and dialog) at a time. */
  expand(text: string) {
    const run = this.queue.then(() => this.expandNow(text));
    this.queue = run.catch(() => {});
    return run;
  }
  private queue: Promise<unknown> = Promise.resolve();
  private async expandNow(text: string) {
    const { key, name } = this.scope();
    const result = await expandPlaceholders(text, {
      vars: this.vars(key),
      inputOn: this.inputOn,
      ask: (inputs, vars) =>
        new Promise((resolve) => {
          this.request = {
            inputs,
            vars,
            resolve: (values) => {
              this.request = null;
              this.notify();
              resolve(values);
            },
          };
          this.notify();
        }),
      toast: (message, kind = "info") => (window as any).toastr?.[kind](message, "占位符变量"),
      confirm: async (message) => confirm(message),
    });
    if (result.clear === "all") this.clearAll();
    else if (JSON.stringify(result.vars) !== JSON.stringify(this.vars(key)))
      this.setVars(key, result.vars, name);
    if (result.inputOn !== this.inputOn) this.setInputOn(result.inputOn);
    return result.text;
  }

  private input() {
    return document.getElementById(INPUT) as HTMLTextAreaElement | null;
  }
  private text() {
    return this.input()?.value ?? "";
  }
  private ready() {
    const input = this.input();
    return !!input && placeholderComplete(input.value, input.selectionStart ?? input.value.length);
  }
  private schedule() {
    clearTimeout(this.timer);
    if (this.composing || this.request || !pending(this.text())) return;
    this.timer = window.setTimeout(() => void this.flush(false), DEBOUNCE);
  }
  /** Expands the draft once it is complete; `now` skips the wait for an unchanged draft. */
  private async flush(now: boolean) {
    clearTimeout(this.timer);
    const input = this.input();
    if (!input || this.busy || this.request || this.composing) return;
    const text = input.value;
    if ((!now && text === this.last) || !pending(text) || !this.ready()) return;
    this.last = text;
    this.busy = true;
    try {
      const next = await this.expand(text);
      if (next === text) return;
      // Text typed or set while the dialog was open stays after the expanded draft.
      const current = input.value;
      if (current !== text && !current.startsWith(text)) return;
      input.value = next + current.slice(text.length);
      input.dispatchEvent(new Event("input", { bubbles: true }));
    } catch (error) {
      this.host.report(error);
    } finally {
      this.busy = false;
    }
  }
  /**
   * `/inject` expands its text first, as the script's interception did; `/buttons` gets the script's
   * toolbar. Each original callback comes back on dispose.
   */
  private wrapCommand(name: "inject" | "buttons", wrap: (original: Callback) => Callback) {
    const command = ctx().SlashCommandParser?.commands?.[name];
    if (!command || command[HOOKED]) return () => {};
    const original: Callback = command.callback,
      wrapped = wrap(original);
    command.callback = wrapped;
    command[HOOKED] = true;
    return () => {
      if (command.callback === wrapped) command.callback = original;
      delete command[HOOKED];
    };
  }
  private wrapInject() {
    const runtime = this;
    return this.wrapCommand(
      "inject",
      (original) =>
        async function (this: unknown, args, value) {
          const text = typeof value === "string" && pending(value) ? await runtime.expand(value) : value;
          return original.call(this, args, text);
        },
    );
  }
  /** SillyTavern builds and opens the /buttons popup before its callback first awaits. */
  private wrapButtons() {
    return this.wrapCommand(
      "buttons",
      (original) =>
        function (this: unknown, args, value) {
          const result = original.call(this, args, value);
          const box = [
            ...document.querySelectorAll<HTMLElement>("dialog[open] .scrollable-buttons-container"),
          ].at(-1);
          if (box) buttonsToolbar(box);
          return result;
        },
    );
  }
}

type Callback = (this: unknown, args: unknown, value: unknown) => unknown;
const SEPARATOR = "--------";
/**
 * The script's quick-reply toolbar: in a /buttons menu, the buttons before a `--------` label form a
 * row that stays at the top while the list scrolls, the separator becomes a rule, and a 发送 button
 * moves next to the popup's own controls.
 */
export function buttonsToolbar(box: HTMLElement) {
  const buttons = [...box.querySelectorAll<HTMLElement>(".menu_button")],
    at = buttons.findIndex((b) => b.textContent?.trim() === SEPARATOR),
    tools = buttons.slice(0, at);
  if (at < 0 || tools.length < 2) return;
  box.classList.add("wb-buttons-toolbar");
  buttons[at].classList.add("wb-buttons-sep");
  const send = tools.find((b) => b.textContent?.includes("发送")),
    controls = box.closest("dialog")?.querySelector(".popup-controls"),
    moved = send && controls ? send : null;
  if (moved) {
    moved.classList.add("wb-buttons-send");
    controls!.prepend(moved);
  }
  const row = tools.filter((b) => b !== moved);
  row.forEach((b) => {
    b.classList.add("wb-buttons-tool");
    b.style.setProperty("--wb-tool-width", `calc(${100 / row.length}% - 4px)`);
  });
}
