import crypto from "node:crypto";
import { SyncError } from "../../../src/sync";
import { Hub, type Reply } from "./hub";
import { NotFound, Refused } from "./space";
import { st, type Directories } from "./st";

/**
 * SillyTavern server plug-in: SillyTavern's data as readable files for an IDE. Routes live under
 * /api/plugins/workbench-sync/ and come after SillyTavern's login, Basic Auth and CSRF middleware,
 * so `req.user` is the signed-in user.
 */
export const info = {
  id: "workbench-sync",
  name: "Noval · Workbench Sync",
  description:
    "Reads and writes world books, characters, presets, connections, personas, outlines and database tables as readable files.",
};
const VERSION = "1";

interface Request {
  query: Record<string, unknown>;
  body: any;
  headers: Record<string, string | string[] | undefined>;
  user?: { profile: { handle: string }; directories: Directories };
  on(event: "close", fn: () => void): void;
}
interface Response {
  status(code: number): Response;
  json(body: unknown): void;
  writeHead(code: number, headers: Record<string, string>): void;
  flushHeaders?: () => void;
  write(chunk: string): boolean;
  flush?: () => void;
  end(): void;
}
interface Router {
  get(path: string, handler: (req: Request, res: Response) => unknown): void;
  put(path: string, handler: (req: Request, res: Response) => unknown): void;
  post(path: string, handler: (req: Request, res: Response) => unknown): void;
}

const hubs = new Map<string, Hub>();
function hubOf(req: Request) {
  if (!req.user) throw new Refused("需要先登录酒馆。", 401);
  const handle = req.user.profile.handle;
  let hub = hubs.get(handle);
  if (!hub) hubs.set(handle, (hub = new Hub(req.user.directories)));
  return hub;
}
const text = (value: unknown) => (typeof value === "string" ? value : "");
function pathOf(value: unknown) {
  const p = text(value).replace(/^\/+|\/+$/g, "");
  if (p.split("/").some((part) => part === "." || part === ".." || (p && !part)))
    throw new Refused("路径无效。");
  return p;
}

/** Optional extra secret for IDE routes: config.yaml `workbenchSync.token` (or SILLYTAVERN_WORKBENCHSYNC_TOKEN). */
async function checkToken(req: Request) {
  const { getConfigValue } = await st(),
    token = String(getConfigValue("workbenchSync.token", "") ?? "");
  if (!token) return;
  const given = Buffer.from(text(req.headers["x-workbench-sync-token"])),
    expected = Buffer.from(token);
  if (given.length !== expected.length || !crypto.timingSafeEqual(given, expected))
    throw new Refused("访问令牌不正确（X-Workbench-Sync-Token）。", 403);
}

function route(handler: (req: Request, res: Response) => Promise<unknown>, ide = true) {
  return async (req: Request, res: Response) => {
    try {
      if (ide) await checkToken(req);
      const result = await handler(req, res);
      if (result !== undefined) res.json(result);
    } catch (error) {
      const [status, body] =
        error instanceof SyncError
          ? [422, { error: error.message, line: error.line }]
          : error instanceof NotFound
            ? [404, { error: error.message }]
            : error instanceof Refused
              ? [error.status, { error: error.message }]
              : [500, { error: error instanceof Error ? error.message : String(error) }];
      if (status === 500) console.error("workbench-sync:", error);
      res.status(status).json(body);
    }
  };
}

export async function init(router: Router) {
  router.get(
    "/info",
    route(async (req) => {
      const hub = hubOf(req),
        { getConfigValue } = await st();
      return {
        id: info.id,
        version: VERSION,
        user: req.user!.profile.handle,
        token: !!getConfigValue("workbenchSync.token", ""),
        ...hub.status(),
      };
    }, false),
  );
  router.get(
    "/tree",
    route(async (req) => ({ entries: await hubOf(req).list(pathOf(req.query.path)) })),
  );
  router.get(
    "/stat",
    route(async (req) => hubOf(req).stat(pathOf(req.query.path))),
  );
  router.get(
    "/file",
    route(async (req) => hubOf(req).read(pathOf(req.query.path))),
  );
  router.put(
    "/file",
    route(async (req) => {
      if (typeof req.body?.text !== "string") throw new Refused("缺少 text。");
      return hubOf(req).write(pathOf(req.body.path), req.body.text, text(req.body.base));
    }),
  );
  router.post(
    "/delete",
    route(async (req) => hubOf(req).remove(pathOf(req.body?.path), text(req.body?.base))),
  );
  router.post(
    "/rename",
    route(async (req) => hubOf(req).rename(pathOf(req.body?.from), pathOf(req.body?.to))),
  );
  router.post(
    "/relay",
    route(async (req) => {
      const reply = req.body as Reply & { request?: string };
      if (!hubOf(req).reply(text(reply?.request), reply)) throw new NotFound("写入请求已超时。");
      return { ok: true };
    }, false),
  );
  router.post(
    "/page-state",
    route(async (req) => {
      const db = req.body?.database;
      const table = (t: any) =>
        typeof t?.key === "string" &&
        typeof t.name === "string" &&
        Array.isArray(t.columns) &&
        Array.isArray(t.rows);
      if (
        db !== null &&
        (typeof db?.chat !== "string" || !Array.isArray(db.tables) || !db.tables.every(table))
      )
        throw new Refused("database 应为 null 或 {chat, tables: [{key, name, columns, rows}]}。");
      hubOf(req).setDatabase(
        text(req.body?.page),
        db && {
          avatar: typeof db.avatar === "string" ? db.avatar : undefined,
          group: typeof db.group === "string" ? db.group : undefined,
          chat: db.chat,
          tables: db.tables,
        },
      );
      return { ok: true };
    }, false),
  );
  router.get("/events", async (req, res) => {
    const role = req.query.role === "page" ? "page" : "ide";
    let hub: Hub;
    try {
      if (role === "ide") await checkToken(req);
      hub = hubOf(req);
    } catch (error) {
      res.status(error instanceof Refused ? error.status : 500).json({ error: (error as Error).message });
      return;
    }
    res.writeHead(200, {
      "Content-Type": "text/event-stream; charset=utf-8",
      // no-transform keeps SillyTavern's compression middleware from buffering the stream.
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    });
    res.flushHeaders?.();
    const detach = hub.attach(role, res),
      heartbeat = setInterval(() => {
        res.write(": ping\n\n");
        res.flush?.();
      }, 20_000);
    req.on("close", () => {
      clearInterval(heartbeat);
      detach();
    });
  });
}

export async function exit() {
  hubs.forEach((hub) => hub.dispose());
  hubs.clear();
}
