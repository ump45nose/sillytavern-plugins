import type {
  Data,
  HostSnapshot,
  Item,
  MessageIndex,
  Preferences,
  Resource,
  SessionState,
  Slice,
  Slices,
} from "./types";
import { clone } from "./model";
import { ctx, internal } from "./internals";
import type { ChatObserver, MediaObserver } from "./chat-observer";
import type { CastRuntime } from "./cast-runtime";
import type { OptionsRuntime } from "./options-runtime";
import type { DatabaseRuntime } from "./database-runtime";
import { bus } from "./bus";

export const defaults: Preferences = { left: true, bindings: {}, groups: {} };

export const sliceNames: Slice[] = ["session", "characters", "resources", "chat", "prefs"];
/** Slices built from another slice go stale with it. */
const dependents: Partial<Record<Slice, Slice[]>> = {
  characters: ["session"],
  prefs: ["resources"],
};
/** Sources before the slices built from them. */
const buildOrder: Slice[] = ["characters", "prefs", "session", "resources", "chat"];
/**
 * What a slice shows, taken when it is built, so a rebuild can tell whether anything changed. Items carry
 * the host's own object as `data` (a character card, a connection profile): those count by identity,
 * everything else by value. The host edits those objects in place, so a character's favourite and bound
 * book, which lists show, are read into the signature; other in-place card edits arrive with
 * CHARACTER_EDITED, which invalidates.
 */
type Signature = { text: string; refs: unknown[] };
function signature(name: Slice, value: unknown): Signature {
  const refs: unknown[] = [];
  const text = JSON.stringify(value, function (key, v) {
    if (key !== "data" || !v || typeof v !== "object") return v;
    refs.push(v);
    return name === "characters" ? [v.data?.extensions?.fav ?? v.fav, v.data?.extensions?.world] : undefined;
  });
  return { text, refs };
}
const sameSignature = (a: Signature, b: Signature) =>
  a.text === b.text && a.refs.length === b.refs.length && a.refs.every((v, i) => v === b.refs[i]);

export const messagePreview = (text: unknown) =>
  String(text ?? "")
    .replace(/<[^>]*>/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 120);
const indexMessage = (m: Data, id: number): MessageIndex => ({
  id,
  name: m.name,
  is_user: m.is_user,
  send_date: m.send_date,
  // Hidden floors (/hide, system notes) are never sent to the model.
  ...(m.is_system ? { hidden: true } : {}),
  preview: messagePreview(m.mes),
});

/**
 * Shared host state and infrastructure. Domain behaviour lives in ./domains and is mixed into
 * HostAdapter; fields here are internal to the host package even where TypeScript cannot say so.
 */
export class HostCore {
  drafts = new Map<string, { base: Data; draft: Data; extra?: Data }>();
  listeners = new Set<() => void>();
  cleanup: (() => void)[] = [];
  resourceVersions = {
    world: 0,
    character: 0,
    preset: 0,
    persona: 0,
    connection: 0,
  };
  sliceListeners = new Map(sliceNames.map((name) => [name, new Set<() => void>()]));
  sliceVersions = Object.fromEntries(sliceNames.map((name) => [name, 0])) as Record<Slice, number>;
  sliceCache: Partial<Slices> = {};
  /** Signatures of the cached slices that rebuilds compare against (all but the chat index). */
  private signatures: Partial<Record<Slice, Signature>> = {};
  version = 0;
  cache: HostSnapshot | null = null;
  world: any;
  personas: any;
  openai: any;
  busy = false;
  resourceAction = false;
  chatsVersion = 0;
  bindingRun = false;
  generating = false;
  /** Created in init; the only observers on #chat and on the native sprite wrappers. */
  chatObserver!: ChatObserver;
  media!: MediaObserver;
  /** The chat's world-book cast on the RP stage. */
  cast!: CastRuntime;
  /** The database plug-in's tables for this chat; `available` is false without the plug-in. */
  database!: DatabaseRuntime;
  /** The chat's story options, from the model's replies or a database table. */
  options!: OptionsRuntime;
  listen(name: string, fn: (...args: any[]) => void) {
    const c = ctx(),
      event = c.eventTypes[name];
    if (event) {
      c.eventSource.on(event, fn);
      this.cleanup.push(() => c.eventSource.removeListener(event, fn));
    }
  }
  /** Notified on every change; prefer subscribeSlice for anything rendered often. */
  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    return () => {
      this.listeners.delete(fn);
    };
  };
  subscribeSlice = (name: Slice, fn: () => void) => {
    const set = this.sliceListeners.get(name)!;
    set.add(fn);
    return () => {
      set.delete(fn);
    };
  };
  revision = () => this.version;
  sliceRevision = (name: Slice) => this.sliceVersions[name];
  /** Everything may have changed. */
  refresh = () => this.invalidate(...sliceNames);
  /** Marks slices (and the slices built from them) stale; they rebuild on next read. */
  invalidate(...names: Slice[]) {
    const stale = new Set<Slice>();
    const add = (name: Slice) => {
      if (stale.has(name)) return;
      stale.add(name);
      dependents[name]?.forEach(add);
    };
    names.forEach(add);
    for (const name of stale) {
      delete this.sliceCache[name];
      this.sliceVersions[name]++;
    }
    this.notify(stale);
  }
  /**
   * Rebuilds cached slices and notifies only those that changed, for events that may or may not have
   * touched them (SillyTavern's settings save fires after every debounced write).
   */
  revalidate(...names: Slice[]) {
    const changed = this.rebuild(buildOrder.filter((name) => names.includes(name)));
    if (changed.size) this.notify(changed);
  }
  /** Rebuilds the cached ones among `names`, in build order; returns the ones that changed. */
  private rebuild(names: Slice[]) {
    const changed = new Set<Slice>(),
      cache = this.sliceCache as Slices;
    for (const name of names) {
      // A slice nobody has read since it went stale rebuilds on its next read anyway.
      const before = this.signatures[name];
      if (!(name in this.sliceCache) || !before) continue;
      const next = this.build(name),
        after = signature(name, next);
      if (sameSignature(before, after)) continue;
      (cache as Record<Slice, unknown>)[name] = next;
      this.signatures[name] = after;
      this.sliceVersions[name]++;
      changed.add(name);
    }
    return changed;
  }
  /** Re-indexes one floor after send, receive, edit or swipe without rebuilding the others. */
  updateMessage(id: number) {
    const chat = this.sliceCache.chat,
      source: Data[] = ctx().chat;
    if (!chat || !Number.isInteger(id) || id < 0 || id >= source.length || source.length < chat.length)
      return this.invalidate("chat");
    const next = chat.slice();
    for (let i = chat.length; i < source.length; i++) next[i] = indexMessage(source[i], i);
    next[id] = indexMessage(source[id], id);
    this.sliceCache.chat = next;
    this.sliceVersions.chat++;
    this.notify(new Set(["chat"]));
  }
  private notify(stale: Set<Slice>) {
    this.cache = null;
    this.version++;
    for (const name of stale) this.sliceListeners.get(name)!.forEach((fn) => fn());
    this.listeners.forEach((fn) => fn());
  }
  slice<K extends Slice>(name: K): Slices[K] {
    const cache = this.sliceCache as Slices;
    if (!(name in this.sliceCache)) {
      cache[name] = this.build(name);
      if (name !== "chat") this.signatures[name] = signature(name, cache[name]);
    }
    return cache[name];
  }
  private build<K extends Slice>(name: K): Slices[K] {
    const builders: { [S in Slice]: () => Slices[S] } = {
      session: () => this.buildSession(),
      characters: () => this.buildCharacters(),
      resources: () => this.buildResources(),
      chat: () => ctx().chat.map(indexMessage),
      prefs: () => this.prefs(),
    };
    return builders[name]();
  }
  isBusy() {
    return this.busy || this.resourceAction || this.generating;
  }
  report(error: unknown) {
    bus.emit("error", error instanceof Error ? error.message : String(error));
  }
  prefs(): Preferences {
    return { ...clone(defaults), ...ctx().extensionSettings.workbench };
  }
  preference(patch: Partial<Preferences>) {
    if (
      Object.entries(patch).every(
        ([k, v]) => JSON.stringify(this.prefs()[k as keyof Preferences]) === JSON.stringify(v),
      )
    )
      return;
    Object.assign(ctx().extensionSettings.workbench, patch);
    ctx().saveSettingsDebounced();
    this.invalidate("prefs");
  }
  /** Calls `fn` whenever SillyTavern confirms a settings write. */
  onSettingsSaved(fn: () => void) {
    const c = ctx(),
      event = c.eventTypes.SETTINGS_UPDATED;
    c.eventSource.on(event, fn);
    return () => c.eventSource.removeListener(event, fn);
  }
  async persistSettings() {
    const c = ctx(),
      event = c.eventTypes.SETTINGS_UPDATED;
    let saved = false;
    const done = () => {
      saved = true;
    };
    c.eventSource.on(event, done);
    try {
      const script = await internal("script");
      await script.saveSettings();
      if (!saved) throw new Error("酒馆设置未确认保存，草稿已保留，请重试。");
    } finally {
      c.eventSource.removeListener(event, done);
    }
  }
  /** POSTs a multipart form; the browser sets its Content-Type with the boundary, so the JSON one is dropped. */
  upload(path: string, form: FormData) {
    const headers = { ...ctx().getRequestHeaders() };
    delete headers["Content-Type"];
    return fetch(path, { method: "POST", headers, body: form });
  }
  async request(path: string, body: Data) {
    const response = await fetch(path, {
      method: "POST",
      headers: ctx().getRequestHeaders(),
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(`保存或读取失败（HTTP ${response.status}），草稿已保留。`);
    return response;
  }
  snapshot(): HostSnapshot {
    return (this.cache ??= {
      ...this.slice("session"),
      characters: this.slice("characters"),
      resources: this.slice("resources"),
      messages: this.slice("chat"),
    });
  }
  private buildCharacters(): Item[] {
    const c = ctx();
    return c.characters.map((x: Data, i: number) => ({
      id: x.avatar,
      name: x.name,
      detail: (x.data?.tags ?? []).join(" · "),
      image: c.getThumbnailUrl("avatar", x.avatar),
      active:
        c.characterId !== undefined &&
        c.characterId !== null &&
        c.characterId !== "" &&
        i === Number(c.characterId),
      data: x,
    }));
  }
  private buildResources(): Record<Resource, Item[]> {
    const c = ctx(),
      manager = c.getPresetManager(),
      profiles = c.extensionSettings.connectionManager?.profiles ?? [],
      prefs = this.slice("prefs"),
      groups = prefs.groups,
      worldGroups = prefs.worldGroups ?? {},
      presetGroups = prefs.presetGroups?.[manager?.apiId ?? c.mainApi] ?? {},
      archivedConnections = new Set(prefs.archived?.connection),
      archivedBooks = new Set(prefs.archived?.world),
      personas = c.powerUserSettings.personas ?? {};
    return {
      connection: profiles
        .map((p: Data) => ({
          id: p.id,
          name: p.name,
          detail: p.model || p.api || "",
          group: groups[p.id] || "",
          archived: archivedConnections.has(p.id),
          data: p,
        }))
        .sort(
          (a: Item, b: Item) =>
            (a.detail ?? "").localeCompare(b.detail ?? "") || a.name.localeCompare(b.name),
        ),
      preset: (manager?.getAllPresets() ?? []).map((name: string) => ({
        id: name,
        name,
        detail: c.mainApi,
        group: presetGroups[name] || "",
      })),
      world: c.getWorldInfoNames().map((name: string) => ({
        id: name,
        name,
        active: this.world?.selected_world_info.includes(name),
        group: worldGroups[name] || "",
        archived: archivedBooks.has(name),
      })),
      persona: Object.entries(personas).map(([id, name]) => ({
        id,
        name: String(name),
        image: c.getThumbnailUrl("persona", id),
        detail: c.powerUserSettings.persona_descriptions?.[id]?.title ?? "",
      })),
    };
  }
  private buildSession(): SessionState {
    const c = ctx(),
      manager = c.getPresetManager();
    return {
      chatName: String(c.chatId ?? "").replace(/\.jsonl$/, ""),
      groupId: c.groupId || undefined,
      groupName: c.groups?.find((g: Data) => g.id === c.groupId)?.name,
      character: this.slice("characters").find((x) => x.active) ?? null,
      current: {
        connection: c.extensionSettings.connectionManager?.selectedProfile ?? "",
        preset: manager?.getSelectedPresetName() ?? "",
        world: this.world?.selected_world_info[0] ?? "",
        persona: this.personas?.user_avatar ?? "",
      },
      online: c.onlineStatus !== "no_connection",
      busy: this.isBusy(),
    };
  }
  isGenerating() {
    return this.generating;
  }
  /**
   * Moves a native node into workbench UI with its handlers intact. `.wb-native-embedded` exempts it
   * from the style isolation rule; the returned function (and destroy) put it back exactly where it was.
   */
  lease(node: HTMLElement, container: HTMLElement, label: string) {
    const placeholder = document.createComment(label);
    node.before(placeholder);
    node.classList.add("wb-native-embedded");
    container.append(node);
    let restored = false;
    const restore = () => {
      if (restored) return;
      restored = true;
      node.classList.remove("wb-native-embedded");
      placeholder.replaceWith(node);
    };
    this.cleanup.push(restore);
    return () => {
      restore();
      this.cleanup = this.cleanup.filter((fn) => fn !== restore);
    };
  }
  download(blob: Blob, name: string) {
    const url = URL.createObjectURL(blob),
      a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}
