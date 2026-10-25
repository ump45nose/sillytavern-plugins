import fs from "node:fs";
import path from "node:path";
import {
  characterCodec,
  mirrorCard,
  outlineCodec,
  personaCodec,
  personaNames,
  presetCodec,
  profileCodec,
  profileNames,
  tableCodec,
  uniqueNames,
  worldCodec,
  SyncError,
  type Data,
  type SyncTable,
} from "../../../src/sync";
import { normalizeOutline } from "../../../src/addons/outline/model";
import { firstLine, st, writeAtomic, type Directories } from "./st";

const OPEN_CHAT = "打开该聊天后可同步：数据库只同步工作台页面里已打开的聊天。";

export class NotFound extends Error {
  constructor(message = "文件不存在。") {
    super(message);
  }
}
/** A request the plug-in will not carry out; `status` is the HTTP status to answer with. */
export class Refused extends Error {
  constructor(
    message: string,
    readonly status = 400,
  ) {
    super(message);
  }
}

export const AREAS = ["世界书", "角色", "预设", "连接", "用户设定", "大纲", "数据库"] as const;
export type Kind = "world" | "character" | "preset" | "connection" | "persona" | "outline" | "database";
/** Database tables live in the page that has their chat open; their units use this as `source`. */
export const PAGE_DATABASE = "page:database";
/** What a workbench page reports: the open chat and its database tables. */
export interface DatabaseView {
  avatar?: string;
  group?: string;
  chat: string;
  tables: SyncTable[];
  time: number;
}

/** One resource as the workbench page saves it, and where its readable files live. */
export interface Unit {
  kind: Kind;
  /** The id the page's save call takes: book or preset name, avatar file, profile id, persona id, chat. */
  id: string;
  /** Virtual path: a directory for multi-file resources, the file itself for single-file ones. */
  path: string;
  single: boolean;
  /** The file on disk the resource is read from. */
  source: string;
  stem?: string;
  explicit?: boolean;
}
export interface Loaded {
  data: Data;
  mtime: number;
  /** Rendered files by path inside the unit; "" is the file of a single-file unit. */
  files: Map<string, string>;
}
export type Entry = { name: string; type: "file" | "dir" };
export type Located = { type: "dir"; children: Entry[] } | { type: "unit"; unit: Unit; rel: string };

const dirs = (names: string[]): Located => ({
  type: "dir",
  children: names.map((name) => ({ name, type: "dir" })),
});
const files = (names: string[]): Located => ({
  type: "dir",
  children: names.map((name) => ({ name, type: "file" })),
});
const stems = async (dir: string, ext: string) =>
  (await fs.promises.readdir(dir).catch(() => [] as string[]))
    .filter((f) => f.endsWith(ext) && !f.startsWith("."))
    .map((f) => f.slice(0, -ext.length))
    .sort((a, b) => a.localeCompare(b));
const readJson = async (file: string) => JSON.parse(await fs.promises.readFile(file, "utf8"));
const mtimeOf = async (file: string) => (await fs.promises.stat(file)).mtimeMs;

/** Cards by file, re-read only when the file changes; shared by every user's space. */
const cards = new Map<string, { mtime: number; size: number; card: Data }>();
const settingsCache = new Map<string, { mtime: number; size: number; data: Data }>();

/** One user's data as a tree of readable files. Nothing is mirrored: every read renders from the source. */
export class Space {
  constructor(
    readonly dirs: Directories,
    private databases: () => DatabaseView[] = () => [],
  ) {}

  async characters() {
    const list: { avatar: string; name: string; card: Data; mtime: number }[] = [];
    for (const name of await fs.promises.readdir(this.dirs.characters).catch(() => [] as string[])) {
      if (!name.endsWith(".png") || name.startsWith(".")) continue;
      const file = path.join(this.dirs.characters, name);
      try {
        const card = await this.card(file);
        list.push({
          avatar: name,
          name: String(card.card.data?.name ?? card.card.name ?? ""),
          card: card.card,
          mtime: card.mtime,
        });
      } catch {
        // Not a character card; SillyTavern skips it as well.
      }
    }
    return list.sort((a, b) => a.avatar.localeCompare(b.avatar));
  }
  private async card(file: string) {
    const stat = await fs.promises.stat(file),
      cached = cards.get(file);
    if (cached && cached.mtime === stat.mtimeMs && cached.size === stat.size) return cached;
    const { readCard } = await st();
    const entry = {
      mtime: stat.mtimeMs,
      size: stat.size,
      card: JSON.parse(readCard(await fs.promises.readFile(file))),
    };
    cards.set(file, entry);
    return entry;
  }
  private get settingsFile() {
    return path.join(this.dirs.root, "settings.json");
  }
  async settings() {
    const file = this.settingsFile,
      stat = await fs.promises.stat(file),
      cached = settingsCache.get(file);
    if (cached && cached.mtime === stat.mtimeMs && cached.size === stat.size) return cached;
    const entry = { mtime: stat.mtimeMs, size: stat.size, data: await readJson(file) };
    settingsCache.set(file, entry);
    return entry;
  }
  private async profiles() {
    const settings = await this.settings(),
      list: Data[] = settings.data.extension_settings?.connectionManager?.profiles ?? [];
    return { list, names: profileNames(list) };
  }
  private async personas() {
    const p = (await this.settings()).data.power_user ?? {},
      list = Object.entries((p.personas ?? {}) as Record<string, string>).map(([id, name]) => ({ id, name }));
    return {
      list,
      names: personaNames(list),
      descriptions: (p.persona_descriptions ?? {}) as Record<string, Data>,
    };
  }
  private async groups() {
    const list: { id: string; name: string; chats: string[] }[] = [];
    for (const id of await stems(this.dirs.groups, ".json")) {
      try {
        const group = await readJson(path.join(this.dirs.groups, id + ".json"));
        list.push({
          id: String(group.id ?? id),
          name: String(group.name ?? id),
          chats: (group.chats ?? []).map(String),
        });
      } catch {
        // A broken group file is SillyTavern's to report.
      }
    }
    return list;
  }
  /** Directory names of chat owners: characters as in 角色/, groups marked 「（群组）」. */
  async owners() {
    const characters = await this.characters(),
      groups = await this.groups(),
      owners = [
        ...characters.map((c) => ({
          key: "c:" + c.avatar,
          title: c.name,
          avatar: c.avatar,
          group: undefined as string | undefined,
        })),
        ...groups.map((g) => ({
          key: "g:" + g.id,
          title: `${g.name}（群组）`,
          avatar: undefined,
          group: g.id,
        })),
      ],
      names = uniqueNames(
        owners,
        (o) => o.key,
        (o) => o.title,
        (o) => o.key.slice(2).replace(/\.png$/, ""),
      );
    return owners.map((o) => ({
      ...o,
      dir: names.get(o.key)!.stem,
      chats: o.group ? groups.find((g) => g.id === o.group)!.chats : [],
    }));
  }
  private async chatsOf(owner: { avatar?: string; group?: string; chats: string[] }) {
    if (owner.group) {
      const present = new Set(await stems(this.dirs.groupChats, ".jsonl"));
      return owner.chats.filter((c) => present.has(c));
    }
    return stems(path.join(this.dirs.chats, owner.avatar!.replace(/\.png$/, "")), ".jsonl");
  }

  async locate(segments: string[]): Promise<Located> {
    if (!segments.length) return dirs([...AREAS]);
    const [area, ...rest] = segments,
      unit = (u: Unit, rel: string[] = []): Located => ({ type: "unit", unit: u, rel: rel.join("/") });
    if (area === "世界书" || area === "预设") {
      const folder = area === "世界书" ? this.dirs.worlds : this.dirs.openAI_Settings,
        names = await stems(folder, ".json");
      if (!rest.length) return dirs(names);
      if (!names.includes(rest[0]))
        throw new NotFound(`没有名为「${rest[0]}」的${area}。新建${area}请在酒馆中操作。`);
      return unit(
        {
          kind: area === "世界书" ? "world" : "preset",
          id: rest[0],
          path: `${area}/${rest[0]}`,
          single: false,
          source: path.join(folder, rest[0] + ".json"),
        },
        rest.slice(1),
      );
    }
    if (area === "角色") {
      const list = await this.characters(),
        names = uniqueNames(
          list,
          (c) => c.avatar,
          (c) => c.name,
          (c) => c.avatar.replace(/\.png$/, ""),
        );
      if (!rest.length) return dirs(list.map((c) => names.get(c.avatar)!.stem));
      const found = list.find((c) => names.get(c.avatar)!.stem === rest[0]);
      if (!found) throw new NotFound(`没有名为「${rest[0]}」的角色。新建角色请在酒馆中操作。`);
      return unit(
        {
          kind: "character",
          id: found.avatar,
          path: `角色/${rest[0]}`,
          single: false,
          source: path.join(this.dirs.characters, found.avatar),
        },
        rest.slice(1),
      );
    }
    if (area === "连接" || area === "用户设定") {
      const { list, names } = area === "连接" ? await this.profiles() : await this.personas(),
        ext = area === "连接" ? ".yaml" : ".md",
        keyOf = (item: Data) => String(item.id);
      if (!rest.length) return files(list.map((item) => names.get(keyOf(item))!.stem + ext));
      const found = rest.length === 1 && list.find((item) => names.get(keyOf(item))!.stem + ext === rest[0]);
      if (!found)
        throw new NotFound(
          `没有「${rest.join("/")}」。新建${area === "连接" ? "连接配置" : "用户设定"}请在酒馆中操作。`,
        );
      const name = names.get(keyOf(found))!;
      return unit({
        kind: area === "连接" ? "connection" : "persona",
        id: keyOf(found),
        path: `${area}/${rest[0]}`,
        single: true,
        source: this.settingsFile,
        stem: name.stem,
        explicit: name.explicit,
      });
    }
    if (area === "大纲") {
      const owners = await this.owners();
      if (!rest.length) {
        const withChats: string[] = [];
        for (const owner of owners) if ((await this.chatsOf(owner)).length) withChats.push(owner.dir);
        return dirs(withChats);
      }
      const owner = owners.find((o) => o.dir === rest[0]);
      if (!owner) throw new NotFound();
      const chats = await this.chatsOf(owner);
      if (rest.length === 1) return files(chats.map((c) => c + ".md"));
      const chat = rest.length === 2 && chats.find((c) => c + ".md" === rest[1]);
      if (!chat) throw new NotFound("没有这个聊天；大纲随聊天创建。");
      return unit({
        kind: "outline",
        id: JSON.stringify({ avatar: owner.avatar, group: owner.group, chat }),
        path: `大纲/${owner.dir}/${rest[1]}`,
        single: true,
        source: owner.group
          ? path.join(this.dirs.groupChats, chat + ".jsonl")
          : path.join(this.dirs.chats, owner.avatar!.replace(/\.png$/, ""), chat + ".jsonl"),
      });
    }
    if (area === "数据库") {
      const owners = await this.owners(),
        placed = this.databases().flatMap((view) => {
          const owner = owners.find((o) => (view.group ? o.group === view.group : o.avatar === view.avatar));
          return owner ? [{ view, dir: owner.dir }] : [];
        }),
        here = placed.filter((p) => p.dir === rest[0]);
      if (!rest.length) return dirs([...new Set(placed.map((p) => p.dir))]);
      if (!here.length) throw new NotFound(OPEN_CHAT);
      if (rest.length === 1) return dirs([...new Set(here.map((p) => p.view.chat))]);
      const view = here.find((p) => p.view.chat === rest[1])?.view;
      if (!view) throw new NotFound(OPEN_CHAT);
      const names = uniqueNames(
          view.tables,
          (t) => t.key,
          (t) => t.name,
          (t) => t.key,
        ),
        file = (t: SyncTable) => names.get(t.key)!.stem + ".md";
      if (rest.length === 2) return files(view.tables.map(file));
      const table = rest.length === 3 && view.tables.find((t) => file(t) === rest[2]);
      if (!table) throw new NotFound("没有这张表；表由数据库插件的模板决定。");
      return unit({
        kind: "database",
        id: JSON.stringify({ avatar: view.avatar, group: view.group, chat: view.chat, table: table.key }),
        path: `数据库/${rest.join("/")}`,
        single: true,
        source: PAGE_DATABASE,
      });
    }
    throw new NotFound();
  }

  async load(unit: Unit): Promise<Loaded> {
    const one = (text: string) => new Map([["", text]]);
    switch (unit.kind) {
      case "world": {
        const data = await readJson(unit.source);
        return { data, mtime: await mtimeOf(unit.source), files: worldCodec.files(data) };
      }
      case "preset": {
        const data = await readJson(unit.source);
        return { data, mtime: await mtimeOf(unit.source), files: presetCodec.files(data) };
      }
      case "character": {
        const { card, mtime } = await this.card(unit.source),
          data = structuredClone(card.data ?? {});
        return { data, mtime, files: characterCodec.files(data) };
      }
      case "connection": {
        const settings = await this.settings(),
          profile = (settings.data.extension_settings?.connectionManager?.profiles ?? []).find(
            (p: Data) => p.id === unit.id,
          );
        if (!profile) throw new NotFound("连接配置已删除。");
        return {
          data: structuredClone(profile),
          mtime: settings.mtime,
          files: one(profileCodec.render(profile, !!unit.explicit)),
        };
      }
      case "persona": {
        const settings = await this.settings(),
          p = settings.data.power_user ?? {};
        if (!(unit.id in (p.personas ?? {}))) throw new NotFound("用户设定已删除。");
        const data = structuredClone({
          name: p.personas[unit.id],
          ...(p.persona_descriptions?.[unit.id] ?? {}),
        });
        return {
          data,
          mtime: settings.mtime,
          files: one(personaCodec.render(data, unit.id, !!unit.explicit)),
        };
      }
      case "database": {
        const { avatar, group, chat, table } = JSON.parse(unit.id),
          view = this.databases().find((v) => v.chat === chat && v.avatar === avatar && v.group === group),
          found = view?.tables.find((t) => t.key === table);
        if (!view || !found) throw new NotFound(OPEN_CHAT);
        return { data: structuredClone(found), mtime: view.time, files: one(tableCodec.render(found)) };
      }
      case "outline": {
        const header = JSON.parse((await firstLine(unit.source)) || "{}"),
          data = normalizeOutline(header.chat_metadata?.workbench_addons?.outline);
        return { data, mtime: await mtimeOf(unit.source), files: one(outlineCodec.render(data)) };
      }
    }
  }

  /** The resource after writing one file; SyncError for unreadable text, Refused for what cannot be written. */
  async apply(unit: Unit, loaded: Loaded, rel: string, text: string): Promise<Data> {
    const { data } = loaded;
    switch (unit.kind) {
      case "world":
        return worldCodec.write(data, rel, text);
      case "preset":
        return presetCodec.write(data, rel, text);
      case "character":
        return characterCodec.write(data, rel, text);
      case "connection": {
        const next = profileCodec.parse(data, unit.stem!, !!unit.explicit, text),
          { list } = await this.profiles();
        if (list.some((p) => p.id !== unit.id && p.name === next.name))
          throw new SyncError(`已有名为「${next.name}」的连接配置。`);
        return next;
      }
      case "persona":
        return personaCodec.parse(data, unit.id, unit.stem!, !!unit.explicit, text);
      case "outline":
        return outlineCodec.parse(data as any, text);
      case "database":
        return tableCodec.parse(data as SyncTable, text);
    }
  }
  remove(unit: Unit, loaded: Loaded, rel: string): Data {
    if (unit.kind === "world") return worldCodec.remove(loaded.data, rel);
    if (unit.kind === "preset") return presetCodec.remove(loaded.data, rel);
    if (unit.kind === "character") return characterCodec.remove(loaded.data, rel);
    throw new Refused("这类文件不能删除；删除资源请在酒馆中操作。", 405);
  }
  rename(unit: Unit, loaded: Loaded, from: string, to: string): Data {
    if (unit.kind === "world") return worldCodec.rename(loaded.data, from, to);
    if (unit.kind === "preset") return presetCodec.rename(loaded.data, from, to);
    if (unit.kind === "connection" || unit.kind === "persona") {
      const ext = unit.kind === "connection" ? ".yaml" : ".md";
      if (!to.endsWith(ext) || to.includes("/")) throw new Refused(`改名后仍应是同一目录下的 ${ext} 文件。`);
      return { ...loaded.data, name: to.slice(0, -ext.length) };
    }
    throw new Refused("这类文件不能改名。", 405);
  }

  /** Writes a resource straight into SillyTavern's files, for when no workbench page is open. */
  async saveDisk(unit: Unit, draft: Data) {
    switch (unit.kind) {
      case "database":
        // The tables are the database plug-in's, inside the page; only the page can write them.
        throw new Refused(OPEN_CHAT, 409);
      case "world":
      case "preset":
        return writeAtomic(unit.source, JSON.stringify(draft, null, 4));
      case "character": {
        const { readCard, writeCard } = await st(),
          image = await fs.promises.readFile(unit.source),
          card = JSON.parse(readCard(image));
        if (!String(draft.name ?? "").trim()) throw new SyncError("角色名称不能为空。");
        // The card cache keys on mtime, so SillyTavern reads the new card on its next request.
        return writeAtomic(unit.source, writeCard(image, JSON.stringify(mirrorCard(card, draft))));
      }
      case "connection":
      case "persona":
        return this.saveSettings((settings) => {
          if (unit.kind === "connection") {
            const profiles: Data[] = settings.extension_settings?.connectionManager?.profiles ?? [],
              index = profiles.findIndex((p) => p.id === unit.id);
            if (index < 0) throw new NotFound("连接配置已删除。");
            profiles[index] = draft;
            return;
          }
          const p = settings.power_user;
          if (!p?.personas || !(unit.id in p.personas)) throw new NotFound("用户设定已删除。");
          const { name, ...description } = draft;
          p.personas[unit.id] = name;
          p.persona_descriptions = { ...p.persona_descriptions, [unit.id]: description };
          // The current persona is also kept flat, as SillyTavern's setPersonaDescription leaves it.
          if (settings.user_avatar === unit.id) {
            settings.username = name;
            p.persona_description = description.description ?? "";
            p.persona_description_position = description.position ?? 0;
            p.persona_description_depth = description.depth ?? 2;
            p.persona_description_role = description.role ?? 0;
            p.persona_description_lorebook = description.lorebook ?? "";
          }
        });
      case "outline": {
        const text = await fs.promises.readFile(unit.source, "utf8"),
          end = text.indexOf("\n"),
          header = JSON.parse(end < 0 ? text : text.slice(0, end));
        header.chat_metadata = {
          ...header.chat_metadata,
          workbench_addons: { ...header.chat_metadata?.workbench_addons, outline: draft },
        };
        return writeAtomic(unit.source, JSON.stringify(header) + (end < 0 ? "" : text.slice(end)));
      }
    }
  }
  private async saveSettings(change: (settings: Data) => void) {
    const settings = await readJson(this.settingsFile);
    change(settings);
    await writeAtomic(this.settingsFile, JSON.stringify(settings, null, 4));
  }
}
