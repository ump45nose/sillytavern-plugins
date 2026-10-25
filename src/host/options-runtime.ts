import type { HostAdapter } from "./adapter";
import { ctx } from "./internals";
import {
  DEFAULT_OPTIONS_PROMPT,
  optionText,
  parseOptions,
  readOptionsConfig,
  storedOptionsConfig,
  stripHistory,
  stripOptions,
  tableOptions,
  type OptionAction,
  type OptionsConfig,
  type StoryOption,
} from "./options";

export interface OptionsState {
  config: OptionsConfig;
  /** The options for the latest reply; empty while a reply is generating or the user spoke last. */
  items: StoryOption[];
  /** Changes with the reply the options belong to, so a view can drop what it had expanded. */
  key: string;
  /** The database's table names, for binding one. */
  tables: string[];
  error: string;
}

const PROMPT = "noval_options",
  IN_CHAT = 1,
  SYSTEM = 0,
  HOOKED = Symbol.for("workbench.options.formatter");

/**
 * A chat's story options: the model's `<options>` block (asked for by an injected prompt, hidden in
 * the text, left out of later prompts) or a bound table of the database plug-in.
 */
export class OptionsRuntime {
  state: OptionsState = { config: readOptionsConfig(undefined), items: [], key: "", tables: [], error: "" };
  private listeners = new Set<() => void>();
  private table: StoryOption[] = [];
  constructor(private host: HostAdapter) {
    // MessageFormatter keeps its hooks for the page's life, so the hook goes in once per page.
    const formatter = ctx().messageFormatter;
    if (formatter && !formatter[HOOKED]) {
      formatter[HOOKED] = true;
      formatter.addHook((mes: string, info: { isUser: boolean }) => (info.isUser ? mes : stripOptions(mes)), {
        stage: formatter.stage.BEFORE_REGEX,
      });
    }
    host.listen("CHAT_COMPLETION_PROMPT_READY", (data: { chat?: { role: string; content: unknown }[] }) => {
      for (const message of data.chat || [])
        if (message.role === "assistant") message.content = this.stripContent(message.content);
    });
    host.listen("GENERATE_AFTER_COMBINE_PROMPTS", (data: { prompt?: unknown }) => {
      if (typeof data.prompt === "string")
        data.prompt = stripHistory(data.prompt, this.state.config.source === "model");
    });
    host.listen("CHAT_CHANGED", () => this.load());
    host.cleanup.push(
      host.subscribe(() => this.update()),
      host.database.subscribe(() => {
        if (this.state.config.source === "db") this.readTable();
      }),
    );
    this.load();
  }
  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    return () => {
      this.listeners.delete(fn);
    };
  };
  private set(patch: Partial<OptionsState>) {
    this.state = { ...this.state, ...patch };
    this.listeners.forEach((fn) => fn());
  }
  private stripContent(content: unknown) {
    if (typeof content === "string") return stripOptions(content);
    if (Array.isArray(content))
      return content.map((part) =>
        part?.type === "text" && typeof part.text === "string"
          ? { ...part, text: stripOptions(part.text) }
          : part,
      );
    return content;
  }
  config(): OptionsConfig {
    return readOptionsConfig(ctx().chatMetadata?.workbenchOptions);
  }
  template() {
    return this.host.prefs().optionsPrompt || DEFAULT_OPTIONS_PROMPT;
  }
  /** Reads the chat's choice; called on every chat switch. */
  load() {
    const config = this.config();
    ctx().setExtensionPrompt(
      PROMPT,
      config.source === "model" ? this.template() : "",
      IN_CHAT,
      0,
      false,
      SYSTEM,
    );
    this.table = [];
    this.set({ config, error: "" });
    if (config.source === "db") {
      // A plug-in that loaded after the workbench is picked up here; its read notifies readTable too.
      this.host.database.read();
      this.readTable();
    } else this.set({ tables: [] });
    this.update(true);
  }
  /** Changes this chat's config; the fields left out keep their values. */
  async save(patch: Partial<OptionsConfig>) {
    const meta = ctx().chatMetadata,
      value = storedOptionsConfig({ ...this.config(), ...patch });
    if (value) meta.workbenchOptions = value;
    else delete meta.workbenchOptions;
    await ctx().saveMetadata();
    this.load();
  }
  /**
   * Chooses an option in a layout: its text goes into the native input and, when that layout sends,
   * through the native send, as if the user had typed it and pressed send.
   */
  choose(option: StoryOption, layout: "novel" | "rp"): OptionAction {
    const action = this.state.config[layout];
    this.host.setInput(optionText(option));
    if (action === "send") document.getElementById("send_but")!.click();
    return action;
  }
  /** The prompt is the user's own across chats; empty brings the default back. */
  async savePrompt(text: string) {
    this.host.preference({ optionsPrompt: text.trim() === DEFAULT_OPTIONS_PROMPT ? "" : text });
    await this.host.persistSettings();
    this.load();
  }
  /** Reads the bound table from the database runtime, which reads again on every plug-in update. */
  readTable() {
    const db = this.host.database.state,
      name = this.state.config.table,
      table = db.tables.find((t) => t.name === name);
    this.table = table ? tableOptions(table) : [];
    this.set({
      tables: db.tables.map((t) => t.name),
      error: !db.available
        ? "没有检测到数据库插件（AutoCardUpdaterAPI）。"
        : db.error || (!name ? "请选择一张表。" : table ? "" : `数据库里没有名为「${name}」的表。`),
    });
    this.update(true);
  }
  /** The options belong to the latest reply, and only once it has finished and the user has not answered. */
  private update(force = false) {
    const c = ctx(),
      last = c.chat?.at(-1),
      source = this.state.config.source;
    const reply = !!last && !last.is_user && !last.is_system && !this.host.isBusy();
    const key = reply ? `${c.chat.length - 1}:${last.swipe_id ?? 0}:${source}:${last.mes?.length ?? 0}` : "";
    if (!force && key === this.state.key) return;
    const items =
      !reply || source === "off"
        ? []
        : source === "model"
          ? parseOptions(String(last.mes ?? ""))
          : this.table;
    this.set({ items, key });
  }
  dispose() {
    ctx().setExtensionPrompt(PROMPT, "", IN_CHAT, 0, false, SYSTEM);
    this.listeners.clear();
  }
}
