import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { sameData, type Data } from "../../../src/sync";
import {
  NotFound,
  PAGE_DATABASE,
  Refused,
  Space,
  type DatabaseView,
  type Entry,
  type Loaded,
  type Unit,
} from "./space";
import type { Directories } from "./st";

/** The parts of an Express response the event streams use. */
export interface Stream {
  write(chunk: string): boolean;
  flush?: () => void;
  end(): void;
}
interface Version {
  hash: string;
  mtime: number;
  size: number;
  /** The unit the file belongs to and the disk file it renders from, for change detection. */
  unit: string;
  source: string;
}
interface Page {
  id: string;
  stream: Stream;
  /** The chat this page has open and its database tables, as last reported. */
  database?: DatabaseView;
}
export interface Reply {
  status: "done" | "skip" | "error";
  message?: string;
  /** Fields the page kept its own values for (a running preset with unsaved changes). */
  conflicts?: string[];
}
export interface Recent {
  time: number;
  path: string;
  route: "page" | "disk" | "none";
  ok: boolean;
  message?: string;
}
export type Route = Recent["route"];

const RELAY_TIMEOUT = 10_000,
  DEBOUNCE = 150;
const hashOf = (text: string) => crypto.createHash("sha1").update(text).digest("hex").slice(0, 16);
export const tag = (v: { mtime: number; hash: string }) => `${v.mtime}:${v.hash}`;
const parentOf = (p: string) => p.split("/").slice(0, -1).join("/");
const split = (p: string) => p.split("/").filter(Boolean);
const under = (p: string, dir: string) => !dir || p === dir || p.startsWith(dir + "/");

/**
 * One user's sync state: connected pages and IDEs, the version of every file an IDE has seen, the
 * relay of writes to the page, and file watchers while an IDE listens.
 */
export class Hub {
  readonly space: Space;
  private pages: Page[] = [];
  private ides = new Set<Stream>();
  private versions = new Map<string, Version>();
  /** Directory listings an IDE has read, to tell it when one changes. */
  private listings = new Map<string, string>();
  private watchers: fs.FSWatcher[] = [];
  private timers = new Map<string, NodeJS.Timeout>();
  private pending = new Map<string, { resolve: (reply: Reply) => void; timer: NodeJS.Timeout }>();
  private queue: Promise<unknown> = Promise.resolve();
  readonly recent: Recent[] = [];

  constructor(dirs: Directories) {
    this.space = new Space(dirs, () => this.pages.flatMap((p) => (p.database ? [p.database] : [])));
  }

  // ── Connections ──────────────────────────────────────────────
  attach(role: "page" | "ide", stream: Stream) {
    if (role === "page") {
      const page: Page = { id: crypto.randomUUID(), stream };
      this.pages.push(page);
      this.send(stream, "hello", { page: page.id, ...this.status() });
      this.broadcastStatus();
      return () => {
        this.pages = this.pages.filter((p) => p !== page);
        this.broadcastStatus();
        if (page.database) this.later(PAGE_DATABASE);
      };
    }
    this.ides.add(stream);
    if (this.ides.size === 1) this.watch();
    this.send(stream, "hello", this.status());
    this.broadcastStatus();
    return () => {
      this.ides.delete(stream);
      if (!this.ides.size) this.unwatch();
      this.broadcastStatus();
    };
  }
  status() {
    return { pages: this.pages.length, clients: this.ides.size, recent: this.recent };
  }
  private send(stream: Stream, event: string, data: unknown) {
    stream.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
    // compression buffers otherwise; it adds flush() to the response.
    stream.flush?.();
  }
  private broadcastStatus() {
    const status = this.status();
    for (const stream of [...this.ides, ...this.pages.map((p) => p.stream)])
      this.send(stream, "status", status);
  }
  /** The page writes go to: the one connected last; for a database table, the page with its chat open. */
  private page(unit: Unit) {
    if (unit.kind !== "database") return this.pages.at(-1);
    const { avatar, group, chat } = JSON.parse(unit.id);
    return [...this.pages]
      .reverse()
      .find(({ database: d }) => d && d.chat === chat && d.avatar === avatar && d.group === group);
  }
  /** A page reports the chat it has open and that chat's database tables (null: none). */
  setDatabase(pageId: string, view: Omit<DatabaseView, "time"> | null) {
    const page = this.pages.find((p) => p.id === pageId);
    if (!page) throw new NotFound("页面连接已断开。");
    page.database = view ? { ...view, time: Date.now() } : undefined;
    this.later(PAGE_DATABASE);
  }
  reply(request: string, reply: Reply) {
    const waiting = this.pending.get(request);
    if (!waiting) return false;
    clearTimeout(waiting.timer);
    this.pending.delete(request);
    waiting.resolve(reply);
    return true;
  }
  private relay(page: Page, unit: Unit, base: Data, draft: Data) {
    const request = crypto.randomUUID();
    return new Promise<Reply>((resolve) => {
      const timer = setTimeout(() => {
        this.pending.delete(request);
        resolve({
          status: "error",
          message: "工作台页面没有在 10 秒内完成写入；页面可能正忙，稍后重新载入文件确认结果。",
        });
      }, RELAY_TIMEOUT);
      this.pending.set(request, { resolve, timer });
      this.send(page.stream, "write", {
        request,
        kind: unit.kind,
        id: unit.id,
        path: unit.path,
        base,
        draft,
      });
    });
  }

  // ── Versions ─────────────────────────────────────────────────
  /**
   * A file's version: the hash of its text and an mtime of its own, which only moves when its text
   * does. Sibling files rendered from the same source keep theirs, so VS Code sees no false change.
   */
  private version(file: string, text: string, unit: Unit, sourceMtime: number) {
    const hash = hashOf(text),
      previous = this.versions.get(file);
    if (previous?.hash === hash) return previous;
    const version = {
      hash,
      mtime: previous ? Math.max(Date.now(), previous.mtime + 1) : Math.floor(sourceMtime) || Date.now(),
      size: Buffer.byteLength(text),
      unit: unit.path,
      source: unit.source,
    };
    this.versions.set(file, version);
    return version;
  }
  /** Records a unit's rendered files; returns what changed against what IDEs had seen. */
  private track(unit: Unit, loaded: Loaded) {
    const changed: string[] = [],
      created: string[] = [],
      seen = new Set([...this.versions].filter(([, v]) => v.unit === unit.path).map(([p]) => p));
    for (const [rel, text] of loaded.files) {
      const file = rel ? `${unit.path}/${rel}` : unit.path,
        previous = this.versions.get(file),
        version = this.version(file, text, unit, loaded.mtime);
      seen.delete(file);
      if (!previous) created.push(file);
      else if (previous.hash !== version.hash) changed.push(file);
    }
    for (const file of seen) this.versions.delete(file);
    return { changed, created, deleted: [...seen] };
  }
  private push(change: { changed: string[]; created: string[]; deleted: string[]; dirs?: string[] }) {
    const dirs = new Set(change.dirs ?? []);
    for (const file of [...change.created, ...change.deleted]) dirs.add(parentOf(file));
    if (!change.changed.length && !change.created.length && !change.deleted.length && !dirs.size) return;
    for (const stream of this.ides) this.send(stream, "changed", { ...change, dirs: [...dirs] });
  }

  // ── Reads ────────────────────────────────────────────────────
  private async open(file: string) {
    const located = await this.space.locate(split(file));
    if (located.type === "dir") return { located, unit: null, loaded: null } as const;
    const loaded = await this.space.load(located.unit);
    // Reads also refresh what IDEs know, so a later write compares against this text.
    this.push(this.track(located.unit, loaded));
    return { located, unit: located.unit, loaded, rel: located.rel } as const;
  }
  private childrenOf(unit: Unit, loaded: Loaded, rel: string, extraDirs: string[]): Entry[] {
    const prefix = rel ? rel + "/" : "",
      entries = new Map<string, Entry["type"]>();
    for (const file of loaded.files.keys()) {
      if (!file.startsWith(prefix)) continue;
      const [head, ...rest] = file.slice(prefix.length).split("/");
      entries.set(head, rest.length ? "dir" : "file");
    }
    if (!rel) for (const dir of extraDirs) entries.set(dir, "dir");
    return [...entries].map(([name, type]) => ({ name, type }));
  }
  private static extraDirs(unit: Unit) {
    return unit.kind === "character" ? ["备选开场白"] : unit.kind === "preset" ? ["提示词"] : [];
  }
  async list(dir: string): Promise<Entry[]> {
    const opened = await this.open(dir);
    let entries: Entry[];
    if (!opened.unit) entries = opened.located.type === "dir" ? opened.located.children : [];
    else {
      if (opened.unit.single && !opened.rel) throw new Refused("这是文件，不是目录。");
      entries = this.childrenOf(opened.unit, opened.loaded, opened.rel, Hub.extraDirs(opened.unit));
      if (opened.rel && !entries.length && !Hub.extraDirs(opened.unit).includes(opened.rel))
        throw new NotFound();
    }
    this.listings.set(dir, JSON.stringify(entries));
    return entries;
  }
  async stat(file: string) {
    const opened = await this.open(file);
    if (!opened.unit) return { type: "dir" as const, mtime: 0, size: 0 };
    const text = opened.loaded.files.get(opened.rel);
    if (text === undefined) {
      const children = this.childrenOf(opened.unit, opened.loaded, opened.rel, Hub.extraDirs(opened.unit));
      if (!opened.rel || children.length || Hub.extraDirs(opened.unit).includes(opened.rel))
        return { type: "dir" as const, mtime: 0, size: 0 };
      throw new NotFound();
    }
    const version = this.versions.get(file)!;
    return { type: "file" as const, mtime: version.mtime, size: version.size, version: tag(version) };
  }
  async read(file: string) {
    const opened = await this.open(file);
    const text = opened.unit ? opened.loaded.files.get(opened.rel) : undefined;
    if (text === undefined) throw opened.unit ? new NotFound() : new Refused("这是目录，不是文件。");
    const version = this.versions.get(file)!;
    return { text, version: tag(version), mtime: version.mtime, size: version.size };
  }

  // ── Writes ───────────────────────────────────────────────────
  private serial<T>(fn: () => Promise<T>): Promise<T> {
    const run = this.queue.then(fn);
    this.queue = run.catch(() => {});
    return run;
  }
  /** Writes a file whose text an IDE last saw at `base` ("" for a file it creates). */
  write(file: string, text: string, base: string) {
    return this.serial(async () => {
      const opened = await this.open(file);
      if (!opened.unit) throw new Refused("不能在这里新建文件：新建资源请在酒馆中操作。", 405);
      const current = opened.loaded.files.get(opened.rel);
      this.checkBase(file, current, base);
      const draft = await this.space.apply(opened.unit, opened.loaded, opened.rel, text);
      const route = await this.commit(file, opened.unit, opened.loaded, draft);
      const after = this.versions.get(file);
      return {
        route,
        ...(after ? { version: tag(after), mtime: after.mtime, size: after.size } : {}),
        // The stored text differs from what was sent (defaults filled in, quoting): the IDE reloads.
        normalized: after?.hash !== hashOf(text),
      };
    });
  }
  remove(file: string, base: string) {
    return this.serial(async () => {
      const opened = await this.open(file);
      if (!opened.unit) throw new Refused("目录不能删除；删除资源请在酒馆中操作。", 405);
      this.checkBase(file, opened.loaded.files.get(opened.rel), base);
      const draft = this.space.remove(opened.unit, opened.loaded, opened.rel);
      return { route: await this.commit(file, opened.unit, opened.loaded, draft) };
    });
  }
  rename(from: string, to: string) {
    return this.serial(async () => {
      const opened = await this.open(from);
      if (!opened.unit || opened.loaded.files.get(opened.rel) === undefined) throw new NotFound();
      const unit = opened.unit,
        rel = unit.single ? path.posix.relative(parentOf(unit.path), to) : path.posix.relative(unit.path, to);
      if (rel.startsWith("..") || !rel) throw new Refused("只能在同一目录里改名。");
      const draft = this.space.rename(
        unit,
        opened.loaded,
        unit.single ? path.posix.basename(from) : opened.rel,
        rel,
      );
      const route = await this.commit(from, unit, opened.loaded, draft, [parentOf(from)]);
      // The IDE carries on with the file under its new name, at this version.
      await this.open(to);
      const after = this.versions.get(to);
      return { route, ...(after ? { version: tag(after) } : {}) };
    });
  }
  private checkBase(file: string, current: string | undefined, base: string) {
    if (current === undefined) {
      if (base) throw new Refused("文件已在酒馆中删除。", 409);
      return;
    }
    const hash = base.split(":")[1];
    if (!hash || hash !== this.versions.get(file)?.hash)
      throw new Refused("文件已在酒馆中修改：请先重新载入，或比较后再保存。", 409);
  }
  /** Stores a draft through the page when one is connected, else on disk; then pushes what changed. */
  private async commit(
    file: string,
    unit: Unit,
    loaded: Loaded,
    draft: Data,
    dirs: string[] = [],
  ): Promise<Route> {
    const entry: Recent = { time: Date.now(), path: file, route: "none", ok: false };
    try {
      if (sameData(draft, loaded.data)) {
        entry.ok = true;
        return entry.route;
      }
      const page = this.page(unit);
      if (page) {
        const reply = await this.relay(page, unit, loaded.data, draft);
        if (reply.status === "done") entry.route = "page";
        else if (reply.status === "skip" && unit.kind === "outline") {
          await this.space.saveDisk(unit, draft);
          entry.route = "disk";
        } else
          throw new Refused(reply.message || "页面没有接受这次写入。", reply.status === "skip" ? 409 : 502);
        if (reply.conflicts?.length) entry.message = `页面保留了未保存的修改：${reply.conflicts.join("、")}`;
      } else {
        await this.space.saveDisk(unit, draft);
        entry.route = "disk";
      }
      entry.ok = true;
      await this.refresh(unit.source, dirs);
      return entry.route;
    } catch (error) {
      entry.message = error instanceof Error ? error.message : String(error);
      throw error;
    } finally {
      this.recent.unshift(entry);
      this.recent.splice(20);
      this.broadcastStatus();
    }
  }

  // ── Changes from SillyTavern ─────────────────────────────────
  /**
   * Re-renders every tracked file rendered from `source` and re-reads the listings IDEs have open,
   * then tells IDEs what changed.
   */
  async refresh(source: string, dirs: string[] = []) {
    const change = {
      changed: [] as string[],
      created: [] as string[],
      deleted: [] as string[],
      dirs: [...dirs],
    };
    const units = new Set([...this.versions.values()].filter((v) => v.source === source).map((v) => v.unit));
    for (const unitPath of units) {
      try {
        const located = await this.space.locate(split(unitPath));
        if (located.type !== "unit") throw new NotFound();
        const result = this.track(located.unit, await this.space.load(located.unit));
        change.changed.push(...result.changed);
        change.created.push(...result.created);
        change.deleted.push(...result.deleted);
      } catch {
        // The resource is gone or renamed: its files are deleted for the IDE.
        for (const [file, version] of this.versions)
          if (version.unit === unitPath) {
            this.versions.delete(file);
            change.deleted.push(file);
          }
      }
    }
    const areas = this.areasOf(source);
    for (const [dir, before] of this.listings) {
      if (!areas.some((area) => under(dir, area))) continue;
      let now = "";
      try {
        const opened = await this.space.locate(split(dir));
        if (opened.type === "dir") now = JSON.stringify(opened.children);
        else if (!units.has(opened.unit.path)) continue;
        else {
          const loaded = await this.space.load(opened.unit);
          now = JSON.stringify(this.childrenOf(opened.unit, loaded, opened.rel, Hub.extraDirs(opened.unit)));
        }
      } catch {
        this.listings.delete(dir);
        change.dirs.push(parentOf(dir));
        continue;
      }
      if (now !== before) {
        this.listings.set(dir, now);
        change.dirs.push(dir);
      }
    }
    this.push(change);
  }
  /** The top-level folders whose listings a change to `source` can alter. */
  private areasOf(source: string) {
    const d = this.space.dirs,
      inside = (dir: string) => source.startsWith(dir + path.sep);
    if (source === path.join(d.root, "settings.json")) return ["连接", "用户设定"];
    if (inside(d.worlds)) return ["世界书"];
    if (inside(d.openAI_Settings)) return ["预设"];
    if (source === PAGE_DATABASE) return ["数据库"];
    if (inside(d.characters)) return ["角色", "大纲", "数据库"];
    if (inside(d.groups)) return ["大纲", "数据库"];
    if (inside(d.chats) || inside(d.groupChats)) return ["大纲"];
    return [];
  }
  private later(source: string) {
    clearTimeout(this.timers.get(source));
    this.timers.set(
      source,
      setTimeout(() => {
        this.timers.delete(source);
        void this.serial(() => this.refresh(source)).catch(() => {});
      }, DEBOUNCE),
    );
  }
  private watch() {
    const d = this.space.dirs,
      on = (dir: string, recursive: boolean, accept: (name: string) => boolean) => {
        try {
          const watcher = fs.watch(dir, { recursive }, (_type, name) => {
            const file = name?.toString();
            if (file && accept(file) && !path.basename(file).startsWith("."))
              this.later(path.join(dir, file));
          });
          watcher.on("error", () => {});
          this.watchers.push(watcher);
        } catch {
          // A missing directory has nothing to watch; SillyTavern creates them on start.
        }
      };
    on(d.worlds, false, (f) => f.endsWith(".json"));
    on(d.openAI_Settings, false, (f) => f.endsWith(".json"));
    on(d.characters, false, (f) => f.endsWith(".png"));
    on(d.root, false, (f) => f === "settings.json");
    on(d.chats, true, (f) => f.endsWith(".jsonl"));
    on(d.groupChats, false, (f) => f.endsWith(".jsonl"));
    on(d.groups, false, (f) => f.endsWith(".json"));
  }
  private unwatch() {
    this.watchers.forEach((w) => w.close());
    this.watchers = [];
    this.timers.forEach((t) => clearTimeout(t));
    this.timers.clear();
    this.listings.clear();
  }
  dispose() {
    this.unwatch();
    for (const [request] of this.pending) this.reply(request, { status: "error", message: "插件已停止。" });
    for (const stream of [...this.ides, ...this.pages.map((p) => p.stream)]) stream.end();
  }
}
