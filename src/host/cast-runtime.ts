import type { HostAdapter } from "./adapter";
import { ctx, loadExtensionModule, nativeNodes } from "./internals";
import { castPrompt, isPathSafe, markCastTags, parseCastTag, type CastName, type Sprite } from "./cast";

let hookAdded = false,
  marking = false;

/** Chat metadata `workbenchRP.cast`: a world book and the titles of the entries that play. */
export interface CastConfig {
  book: string;
  entries: string[];
}
export interface CastEntry extends CastName {
  /** The title is a name the server keeps as it is for a folder. */
  safe: boolean;
}
export interface CastMember extends CastEntry {
  sprites: Sprite[];
}
export interface CastState {
  /** Absent: the chat plays its character card, as before. */
  config?: CastConfig;
  /** Every titled entry of the book, for choosing the cast. */
  entries: CastEntry[];
  members: CastMember[];
  /** Chosen titles the book no longer has. */
  missing: string[];
  loading: boolean;
  error: string;
}

const PROMPT = "noval_cast",
  EXPRESSIONS = "/scripts/extensions/expressions/index.js",
  IN_CHAT = 1,
  SYSTEM = 0;
const idle: CastState = { entries: [], members: [], missing: [], loading: false, error: "" };
const enc = encodeURIComponent;
/** A sprite's file name without its extension: what the server matches to replace or delete it. */
const stem = (sprite: Sprite) =>
  decodeURIComponent(sprite.path.split("?")[0].split("/").pop()!).replace(/\.[^.]+$/, "");
const extension = (fileName: string) => fileName.match(/\.[^.]+$/)?.[0].toLowerCase() ?? ".png";

function entriesOf(book: any): CastEntry[] {
  const seen = new Set<string>(),
    entries: CastEntry[] = [];
  for (const entry of Object.values<any>(book?.entries || {})) {
    const name = String(entry?.comment ?? "").trim();
    if (!name || seen.has(name)) continue;
    seen.add(name);
    entries.push({
      name,
      aliases: (Array.isArray(entry.key) ? entry.key : [])
        .map((key: unknown) => String(key).trim())
        .filter((key: string) => key && key !== name),
      safe: isPathSafe(name),
    });
  }
  return entries;
}

/**
 * A chat's world-book cast: which entries play, their images in `characters/<book>/<entry>/`, the
 * prompt asking the model to tag who speaks, and the tags taken out of the rendered text.
 */
export class CastRuntime {
  state: CastState = idle;
  private listeners = new Set<() => void>();
  private run = 0;
  private labels = new Map<string, Promise<string>>();
  constructor(private host: HostAdapter) {}
  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    return () => {
      this.listeners.delete(fn);
    };
  };
  private set(state: CastState) {
    this.state = state;
    this.listeners.forEach((fn) => fn());
  }
  config(): CastConfig | undefined {
    const value = ctx().chatMetadata?.workbenchRP?.cast;
    if (!value || typeof value.book !== "string" || !value.book || !Array.isArray(value.entries)) return;
    return { book: value.book, entries: value.entries.filter((x: unknown) => typeof x === "string") };
  }
  /** Reads the chat's choice, the book and the chosen entries' images; called on every chat switch. */
  async load() {
    const run = ++this.run,
      config = this.config();
    this.labels.clear();
    if (!config) {
      this.prompt([]);
      return this.set(idle);
    }
    this.set({ ...this.state, config, loading: true, error: "" });
    try {
      const entries = entriesOf(await this.host.readBook(config.book));
      const chosen = config.entries
        .map((name) => entries.find((entry) => entry.name === name))
        .filter((entry): entry is CastEntry => !!entry?.safe);
      const members = await Promise.all(
        chosen.map(async (entry) => ({ ...entry, sprites: await this.sprites(config.book, entry.name) })),
      );
      if (run !== this.run) return;
      this.prompt(members);
      this.set({
        config,
        entries,
        members,
        missing: config.entries.filter((name) => !entries.some((entry) => entry.name === name)),
        loading: false,
        error: "",
      });
    } catch (error) {
      if (run !== this.run) return;
      this.prompt([]);
      this.set({ ...idle, config, error: error instanceof Error ? error.message : String(error) });
    }
  }
  /** Writes the chat's choice (none: back to the character card) and loads it. */
  async save(config: CastConfig | undefined) {
    const meta = ctx().chatMetadata,
      rp = { ...(meta.workbenchRP || {}) };
    if (config) rp.cast = { book: config.book, entries: [...new Set(config.entries)] };
    else delete rp.cast;
    meta.workbenchRP = rp;
    await ctx().saveMetadata();
    await this.load();
  }
  /** The images in `characters/<book>/<entry>/`, with URLs escaped part by part. */
  async sprites(book: string, name: string): Promise<Sprite[]> {
    const response = await fetch(`/api/sprites/get?name=${enc(`${book}/${name}`)}`, {
      headers: ctx().getRequestHeaders(),
    });
    if (!response.ok) throw new Error(`读取「${name}」的立绘失败（HTTP ${response.status}）。`);
    const prefix = `/characters/${book}/${name}/`;
    return ((await response.json()) as Sprite[]).map((sprite) => {
      // The server answers with the folder names unescaped; a name with # or % would break the URL.
      const [file, query] = (
        sprite.path.startsWith(prefix) ? sprite.path.slice(prefix.length) : sprite.path.split("/").pop()!
      ).split("?");
      return {
        label: sprite.label,
        path: `/characters/${enc(book)}/${enc(name)}/${enc(file)}${query ? "?" + query : ""}`,
      };
    });
  }
  /**
   * Each image goes in as `<label>.<ext>` (or under the file name it replaces, `joy-2`), replacing
   * what was there; the file it came from only gives the extension. The server reads the label
   * back from the file name.
   */
  async upload(
    book: string,
    name: string,
    items: { file: Blob; fileName: string; label: string; stem?: string }[],
  ) {
    for (const item of items) {
      if (!/^[a-z_]+$/.test(item.label))
        throw new Error(`表情名「${item.label}」只能用小写英文字母和下划线。`);
      await this.put(
        book,
        name,
        item.label,
        new File([item.file], (item.stem ?? item.label) + extension(item.fileName)),
      );
    }
    await this.touched(book);
  }
  async remove(book: string, name: string, sprite: Sprite) {
    await this.drop(book, name, sprite);
    await this.touched(book);
  }
  /** The image under another label: written there first, then taken off the old one. */
  async relabel(book: string, name: string, sprite: Sprite, label: string) {
    if (!/^[a-z_]+$/.test(label)) throw new Error(`表情名「${label}」只能用小写英文字母和下划线。`);
    const file = await this.fetchSprite(sprite);
    await this.put(book, name, label, new File([file], label + extension(file.name)));
    await this.drop(book, name, sprite);
    await this.touched(book);
  }
  /**
   * An entry's images follow it to a new title. The server cannot move them, so each is copied to
   * the new folder and only then taken off the old one; a failure stops there and leaves the old
   * images in place. This chat's cast follows the new title too.
   */
  async move(book: string, from: string, to: string, progress?: (done: number, total: number) => void) {
    const sprites = await this.sprites(book, from);
    for (const [i, sprite] of sprites.entries()) {
      progress?.(i, sprites.length);
      const file = await this.fetchSprite(sprite);
      await this.put(book, to, sprite.label, file);
      await this.drop(book, from, sprite);
    }
    const config = this.config();
    if (config?.book === book && config.entries.includes(from))
      await this.save({ book, entries: config.entries.map((x) => (x === from ? to : x)) });
    else await this.touched(book);
    return sprites.length;
  }
  private async fetchSprite(sprite: Sprite) {
    const response = await fetch(sprite.path, { headers: ctx().getRequestHeaders(), cache: "no-store" });
    if (!response.ok) throw new Error(`读取立绘「${stem(sprite)}」失败（HTTP ${response.status}）。`);
    return new File([await response.blob()], decodeURIComponent(sprite.path.split("?")[0].split("/").pop()!));
  }
  private async put(book: string, name: string, label: string, file: File) {
    const form = new FormData();
    form.append("avatar", file);
    form.append("name", `${book}/${name}`);
    form.append("label", label);
    form.append("spriteName", file.name.replace(/\.[^.]+$/, ""));
    const response = await this.host.upload("/api/sprites/upload", form);
    if (!response.ok) throw new Error(`上传「${file.name}」失败（HTTP ${response.status}）。`);
  }
  private async drop(book: string, name: string, sprite: Sprite) {
    await this.host.request("/api/sprites/delete", {
      name: `${book}/${name}`,
      label: sprite.label,
      spriteName: stem(sprite),
    });
  }
  /** The stage and the prompt list the cast's images again when its book's images change. */
  private async touched(book: string) {
    if (this.state.config?.book === book) await this.load();
  }
  /** A member by its title or one of its keywords. */
  member(name: string | null | undefined) {
    if (!name) return;
    return (
      this.state.members.find((member) => member.name === name) ??
      this.state.members.find((member) => member.aliases.includes(name))
    );
  }
  private prompt(members: CastMember[]) {
    ctx().setExtensionPrompt(
      PROMPT,
      castPrompt(members.map((m) => ({ name: m.name, labels: [...new Set(m.sprites.map((s) => s.label))] }))),
      IN_CHAT,
      1,
      false,
      SYSTEM,
    );
  }
  /** The expression the host's classifier reads in an untagged passage; "" when none is set up. */
  expression(key: string, text: string) {
    let pending = this.labels.get(key);
    if (!pending) {
      pending = this.classify(text);
      this.labels.set(key, pending);
    }
    return pending;
  }
  private async classify(text: string) {
    const settings = ctx().extensionSettings.expressions;
    // 99 is the classifier switched off.
    if (!settings || settings.api === 99 || !text.trim()) return "";
    try {
      const module = await loadExtensionModule(EXPRESSIONS);
      return typeof module.getExpressionLabel === "function"
        ? String((await module.getExpressionLabel(text)) || "")
        : "";
    } catch {
      return "";
    }
  }
  fallbackExpression(): string | undefined {
    return ctx().extensionSettings.expressions?.fallback_expression;
  }
  /**
   * Marks the line-opening `名字|表情:` tags of replies as SillyTavern renders them; the raw message
   * keeps them, so editing and the model still see them. SillyTavern's formatter has no way to
   * remove a hook, so it is added once per page and stands idle while the workbench is unmounted.
   * Replies already on screen were rendered without it and are rendered again once.
   */
  showTags() {
    if (!hookAdded) {
      ctx().messageFormatter.addHook((mes: string, at: { isUser: boolean; isReasoning: boolean }) =>
        marking && !at.isUser && !at.isReasoning ? markCastTags(mes) : mes,
      );
      hookAdded = true;
    }
    marking = true;
    const { chat, updateMessageBlock } = ctx();
    for (const node of nativeNodes.chat!.querySelectorAll<HTMLElement>('.mes:not([is_user="true"])')) {
      const id = Number(node.getAttribute("mesid"));
      const message = chat[id];
      if (
        message &&
        !message.is_user &&
        (message.extra?.display_text ?? message.mes ?? "").split("\n").some(parseCastTag)
      )
        updateMessageBlock(id, message);
    }
    return () => {
      marking = false;
    };
  }
}
