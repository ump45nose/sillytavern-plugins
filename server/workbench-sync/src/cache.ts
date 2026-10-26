import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";
import crypto from "node:crypto";
import { promisify } from "node:util";

/**
 * Response cache for the two boot requests that dominate a page refresh: /api/settings/get and
 * /api/characters/all. A response is reused only while every file it was built from is unchanged,
 * judged by a fingerprint of name, inode, size and mtime (SillyTavern writes through
 * write-file-atomic, so each write is a new inode). Writes through SillyTavern's settings and
 * character routes, and through this plug-in, drop the user's entries outright as well.
 */

/** The user directories (SillyTavern's USER_DIRECTORY_TEMPLATE) the cached responses are built from. */
export interface CacheDirectories {
  root: string;
  characters: string;
  chats: string;
  worlds: string;
  novelAI_Settings: string;
  openAI_Settings: string;
  textGen_Settings: string;
  koboldAI_Settings: string;
  themes: string;
  movingUI: string;
  quickreplies: string;
  instruct: string;
  context: string;
  sysprompt: string;
  reasoning: string;
}
export type Kind = "settings" | "characters";
type Encoding = "br" | "gzip";

/** settings/get reads settings.json and these directories (src/endpoints/settings.js, 1.19.0). */
const settingsDirectories = [
  "novelAI_Settings",
  "openAI_Settings",
  "textGen_Settings",
  "koboldAI_Settings",
  "worlds",
  "themes",
  "movingUI",
  "quickreplies",
  "instruct",
  "context",
  "sysprompt",
  "reasoning",
] as const;

async function statLine(file: string, name: string) {
  try {
    const s = await fs.promises.stat(file);
    return `${name}\t${s.ino}\t${s.size}\t${s.mtimeMs}`;
  } catch {
    return `${name}\t-`;
  }
}
/** One line per entry; `depth` levels of subdirectories are listed too (chats/<character>/). */
async function directoryLines(dir: string, depth: number): Promise<string[]> {
  let names: fs.Dirent[];
  try {
    names = await fs.promises.readdir(dir, { withFileTypes: true });
  } catch {
    return [`${dir}\t-`];
  }
  names.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
  const lines = await Promise.all(
    names.map(async (entry) => {
      const file = path.join(dir, entry.name);
      if (depth > 0 && entry.isDirectory()) return [file, ...(await directoryLines(file, depth - 1))];
      return [await statLine(file, file)];
    }),
  );
  return [dir, ...lines.flat()];
}

/** A digest of every file the response of `kind` is built from. */
export async function fingerprint(kind: Kind, dirs: CacheDirectories) {
  const parts =
    kind === "settings"
      ? [
          [await statLine(path.join(dirs.root, "settings.json"), "settings.json")],
          ...(await Promise.all(settingsDirectories.map((key) => directoryLines(dirs[key], 0)))),
        ]
      : await Promise.all([directoryLines(dirs.characters, 0), directoryLines(dirs.chats, 1)]);
  return crypto.createHash("sha1").update(parts.flat().join("\n")).digest("hex");
}

const brotli = promisify(zlib.brotliCompress),
  gzip = promisify(zlib.gzip);

/** Same preference as SillyTavern's compression middleware (1.8): br, then gzip; q=0 refuses. */
export function pickEncoding(header: unknown): Encoding | null {
  const accepted = new Set(
    String(header ?? "")
      .split(",")
      .map((part) => part.trim().split(";"))
      .filter(([, ...params]) => !params.some((p) => /^\s*q\s*=\s*0(\.0*)?\s*$/.test(p)))
      .map(([token]) => token.trim().toLowerCase()),
  );
  return accepted.has("br") ? "br" : accepted.has("gzip") || accepted.has("*") ? "gzip" : null;
}

interface Entry {
  fingerprint: string;
  type: string;
  body: Buffer;
  encoded: Partial<Record<Encoding, Promise<Buffer>>>;
}

export class ResponseCache {
  private entries = new Map<string, Entry>();
  private generations = new Map<string, number>();
  counts = { hits: 0, misses: 0, bytes: 0 };

  generation(handle: string) {
    return this.generations.get(handle) ?? 0;
  }
  /** Drops the user's responses; a fill that started before this is discarded. */
  invalidate(handle: string) {
    this.generations.set(handle, this.generation(handle) + 1);
    for (const kind of ["settings", "characters"] as const) this.entries.delete(`${handle}:${kind}`);
  }
  get(handle: string, kind: Kind, print: string) {
    const entry = this.entries.get(`${handle}:${kind}`);
    return entry?.fingerprint === print ? entry : undefined;
  }
  /** Stores a response only when nothing invalidated the user since `generation` was read. */
  set(handle: string, kind: Kind, print: string, generation: number, type: string, body: Buffer) {
    if (this.generation(handle) !== generation) return false;
    this.entries.set(`${handle}:${kind}`, { fingerprint: print, type, body, encoded: {} });
    return true;
  }
  /** The body as sent for `encoding`; each encoding is compressed once per entry. */
  encode(entry: Entry, encoding: Encoding | null) {
    if (!encoding) return Promise.resolve(entry.body);
    return (entry.encoded[encoding] ??=
      encoding === "br"
        ? brotli(entry.body, { params: { [zlib.constants.BROTLI_PARAM_QUALITY]: 4 } })
        : gzip(entry.body));
  }
  clear() {
    this.entries.clear();
  }
}

/* ---------------------------- Express wiring ---------------------------- */

interface Layer {
  route?: { path?: string };
}
export interface ExpressRouter {
  stack: Layer[];
  post(path: string, handler: Handler): unknown;
  use(handler: Handler): unknown;
}
interface Req {
  path: string;
  headers: Record<string, string | string[] | undefined>;
  user?: { profile: { handle: string }; directories: CacheDirectories };
}
interface Res {
  statusCode: number;
  send(body: unknown): Res;
  getHeader(name: string): unknown;
  setHeader(name: string, value: string | number): void;
  end(body?: Buffer): void;
  on(event: "finish" | "close", fn: () => void): void;
}
type Handler = (req: Req, res: Res, next: (error?: unknown) => void) => unknown;

const size = (bytes: number) =>
  bytes >= 1048576 ? `${(bytes / 1048576).toFixed(2)} MB` : `${Math.round(bytes / 1024)} KB`;

/** Prepends `handler` to an Express 4 router, ahead of SillyTavern's own routes. */
function prepend(router: ExpressRouter, add: () => void) {
  const before = router.stack.length;
  add();
  const added = router.stack.splice(before);
  router.stack.unshift(...added);
  return () => {
    for (const layer of added) {
      const at = router.stack.indexOf(layer);
      if (at >= 0) router.stack.splice(at, 1);
    }
  };
}

/** Serves `kind` from the cache while its fingerprint holds; otherwise records SillyTavern's reply. */
function reader(cache: ResponseCache, kind: Kind): Handler {
  return async (req, res, next) => {
    const user = req.user;
    if (!user) return next();
    const handle = user.profile.handle,
      generation = cache.generation(handle),
      started = Date.now();
    let print: string;
    try {
      print = await fingerprint(kind, user.directories);
    } catch (error) {
      console.warn("workbench-sync: cache fingerprint failed, serving from source:", error);
      return next();
    }
    const hit = cache.get(handle, kind, print);
    if (hit) {
      try {
        const encoding = pickEncoding(req.headers["accept-encoding"]),
          body = await cache.encode(hit, encoding);
        res.setHeader("Content-Type", hit.type);
        res.setHeader("Vary", "Accept-Encoding");
        // An encoded response passes through SillyTavern's compression middleware untouched.
        if (encoding) res.setHeader("Content-Encoding", encoding);
        res.setHeader("Content-Length", body.length);
        res.end(body);
        cache.counts.hits++;
        cache.counts.bytes += body.length;
        console.log(
          `workbench-sync: cache hit ${kind} [${handle}] ${size(hit.body.length)}` +
            `${encoding ? ` → ${encoding} ${size(body.length)}` : ""} in ${Date.now() - started} ms` +
            ` · hits ${cache.counts.hits} / misses ${cache.counts.misses}`,
        );
      } catch (error) {
        console.warn("workbench-sync: cache hit could not be sent, serving from source:", error);
        cache.invalidate(handle);
        next();
      }
      return;
    }
    cache.counts.misses++;
    // Express turns an object into a JSON string and calls send again; the string is the body.
    const send = res.send;
    res.send = function (this: Res, body: unknown) {
      if (this.statusCode === 200 && (typeof body === "string" || Buffer.isBuffer(body))) {
        res.send = send;
        const buffer = Buffer.from(body as string),
          stored = cache.set(
            handle,
            kind,
            print,
            generation,
            String(this.getHeader("Content-Type") || "application/json; charset=utf-8"),
            buffer,
          );
        console.log(
          `workbench-sync: cache miss ${kind} [${handle}] ${size(buffer.length)} in ${Date.now() - started} ms` +
            `${stored ? "" : " (not stored: changed meanwhile)"} · hits ${cache.counts.hits} / misses ${cache.counts.misses}`,
        );
      }
      return send.call(this, body);
    };
    next();
  };
}

/** Invalidates the user before and after any request on the router other than the read-only paths. */
function writer(cache: ResponseCache, reads: string[]): Handler {
  return (req, res, next) => {
    const handle = req.user?.profile.handle;
    if (handle && !reads.includes(req.path)) {
      cache.invalidate(handle);
      let done = false;
      const after = () => {
        if (!done) cache.invalidate(handle);
        done = true;
      };
      res.on("finish", after);
      res.on("close", after);
    }
    next();
  };
}

/**
 * Wraps SillyTavern's own settings and characters routers (the module instances server-startup
 * mounted, imported by the same file URL). Returns the undo, or null when a router does not look
 * like 1.19.0's, in which case nothing is installed.
 */
export function install(
  cache: ResponseCache,
  routers: { settings: ExpressRouter; characters: ExpressRouter },
) {
  const has = (router: ExpressRouter, route: string) =>
    Array.isArray(router?.stack) && router.stack.some((layer) => layer.route?.path === route);
  if (!has(routers.settings, "/get") || !has(routers.characters, "/all")) return null;
  const undo = [
    prepend(routers.settings, () => routers.settings.use(writer(cache, ["/get", "/get-snapshots"]))),
    prepend(routers.settings, () => routers.settings.post("/get", reader(cache, "settings"))),
    prepend(routers.characters, () =>
      routers.characters.use(writer(cache, ["/all", "/get", "/chats", "/export"])),
    ),
    prepend(routers.characters, () => routers.characters.post("/all", reader(cache, "characters"))),
  ];
  return () => {
    undo.forEach((fn) => fn());
    cache.clear();
  };
}
