import test from "node:test";
import assert from "node:assert/strict";
import { build } from "esbuild";
import fs from "node:fs";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import zlib from "node:zlib";

const directory = await mkdtemp(tmpdir() + "/wb-cache-tests-");
const result = await build({
  entryPoints: ["server/workbench-sync/src/cache.ts"],
  bundle: true,
  format: "esm",
  platform: "node",
  write: false,
});
await writeFile(directory + "/cache.mjs", result.outputFiles[0].text);
const { ResponseCache, fingerprint, pickEncoding, install } = await import(directory + "/cache.mjs");

const keys = [
  "characters",
  "chats",
  "worlds",
  "novelAI_Settings",
  "openAI_Settings",
  "textGen_Settings",
  "koboldAI_Settings",
  "themes",
  "movingUI",
  "quickreplies",
  "instruct",
  "context",
  "sysprompt",
  "reasoning",
  "backups",
];
let users = 0;
function userDirs() {
  const root = fs.mkdtempSync(path.join(directory, `user${users++}-`));
  const dirs = { root };
  for (const key of keys) fs.mkdirSync((dirs[key] = path.join(root, key)));
  fs.writeFileSync(path.join(root, "settings.json"), JSON.stringify({ a: 1 }));
  return dirs;
}
/** Writes like write-file-atomic: a temporary file renamed over the target (a new inode). */
function atomic(file, text) {
  fs.writeFileSync(file + ".tmp", text);
  fs.renameSync(file + ".tmp", file);
}

/** Express 4's dispatch order for the parts the cache uses: layers in stack order, route layers match method and path. */
function router() {
  const stack = [];
  return {
    stack,
    post(p, handle) {
      stack.push({ route: { path: p }, method: "POST", handle });
    },
    use(handle) {
      stack.push({ handle });
    },
    async dispatch(req, res) {
      let i = 0;
      const next = async () => {
        while (i < stack.length) {
          const layer = stack[i++];
          if (layer.route && layer.route.path !== req.path) continue;
          return layer.handle(req, res, next);
        }
      };
      await next();
      await res.done;
    },
  };
}
function response() {
  const headers = {},
    listeners = { finish: [], close: [] };
  let resolve;
  const res = {
    statusCode: 200,
    headers,
    done: new Promise((r) => (resolve = r)),
    setHeader: (k, v) => (headers[k.toLowerCase()] = v),
    getHeader: (k) => headers[k.toLowerCase()],
    status(code) {
      this.statusCode = code;
      return this;
    },
    send(body) {
      if (typeof body !== "string" && !Buffer.isBuffer(body)) {
        this.setHeader("Content-Type", "application/json; charset=utf-8");
        return this.send(JSON.stringify(body));
      }
      this.body = Buffer.from(body);
      this.finish();
      return this;
    },
    end(body) {
      this.body = body;
      this.finish();
    },
    finish() {
      listeners.finish.forEach((fn) => fn());
      resolve();
    },
    on: (event, fn) => listeners[event].push(fn),
  };
  return res;
}
/** SillyTavern's two handlers reduced to the files they read; `calls` counts source reads. */
function server() {
  const settings = router(),
    characters = router(),
    calls = { settings: 0, characters: 0, saves: 0 };
  settings.post("/save", (req, res) => {
    calls.saves++;
    atomic(path.join(req.user.directories.root, "settings.json"), JSON.stringify(req.body));
    res.send({ result: "ok" });
  });
  settings.post("/get", (req, res) => {
    calls.settings++;
    const d = req.user.directories;
    if (req.fail) return res.status(500).send({ error: true });
    res.send({
      settings: fs.readFileSync(path.join(d.root, "settings.json"), "utf8"),
      world_names: fs.readdirSync(d.worlds).sort(),
      openai: fs.readdirSync(d.openAI_Settings).map((f) => fs.readFileSync(path.join(d.openAI_Settings, f), "utf8")),
    });
  });
  characters.post("/all", (req, res) => {
    calls.characters++;
    const d = req.user.directories;
    res.send(
      fs.readdirSync(d.characters).map((f) => ({
        avatar: f,
        chat_size: fs.existsSync(path.join(d.chats, f))
          ? fs.readdirSync(path.join(d.chats, f)).reduce((n, c) => n + fs.statSync(path.join(d.chats, f, c)).size, 0)
          : 0,
      })),
    );
  });
  characters.post("/edit", (req, res) => {
    atomic(path.join(req.user.directories.characters, req.body.avatar), req.body.data);
    res.send("ok");
  });
  return { settings, characters, calls };
}
const user = (handle, dirs) => ({ profile: { handle }, directories: dirs });
async function call(r, p, u, extra = {}) {
  const res = response();
  await r.dispatch({ path: p, headers: { "accept-encoding": "gzip, deflate, br" }, user: u, ...extra }, res);
  return res;
}
const decode = (res) =>
  JSON.parse(
    (res.headers["content-encoding"] === "br"
      ? zlib.brotliDecompressSync(res.body)
      : res.headers["content-encoding"] === "gzip"
        ? zlib.gunzipSync(res.body)
        : res.body
    ).toString("utf8"),
  );

test("fingerprint follows every file settings/get reads and ignores the rest", async () => {
  const d = userDirs(),
    print = () => fingerprint("settings", d);
  let last = await print();
  const changed = async (label) => {
    const next = await print();
    assert.notEqual(next, last, label);
    last = next;
  };
  atomic(path.join(d.root, "settings.json"), JSON.stringify({ a: 2 })); // same size, new inode
  await changed("settings.json rewritten at the same size");
  fs.writeFileSync(path.join(d.worlds, "灯塔.json"), "{}");
  await changed("world book created");
  atomic(path.join(d.openAI_Settings, "p.json"), "{}");
  await changed("preset saved");
  atomic(path.join(d.quickreplies, "q.json"), "{}");
  await changed("quick reply set saved");
  fs.rmSync(path.join(d.worlds, "灯塔.json"));
  await changed("world book deleted");
  fs.writeFileSync(path.join(d.backups, "b.json"), "{}");
  fs.writeFileSync(path.join(d.characters, "c.png"), "x");
  assert.equal(await print(), last, "backups and characters do not feed settings/get");
});

test("characters fingerprint covers cards and the chat files under chats/<character>/", async () => {
  const d = userDirs();
  fs.writeFileSync(path.join(d.characters, "A.png"), "card");
  fs.mkdirSync(path.join(d.chats, "A"));
  fs.writeFileSync(path.join(d.chats, "A", "1.jsonl"), "{}\n");
  const first = await fingerprint("characters", d);
  fs.appendFileSync(path.join(d.chats, "A", "1.jsonl"), "{}\n");
  const second = await fingerprint("characters", d);
  assert.notEqual(second, first, "chat append changes chat_size");
  atomic(path.join(d.characters, "A.png"), "card");
  assert.notEqual(await fingerprint("characters", d), second, "card rewrite");
});

test("pickEncoding prefers br, then gzip, and honours q=0", () => {
  assert.equal(pickEncoding("gzip, deflate, br, zstd"), "br");
  assert.equal(pickEncoding("gzip;q=1.0, br;q=0"), "gzip");
  assert.equal(pickEncoding("deflate"), null);
  assert.equal(pickEncoding(undefined), null);
  assert.equal(pickEncoding("*"), "gzip");
});

test("settings/get: miss records, hit serves the same body compressed, a file change refetches", async () => {
  const st = server(),
    cache = new ResponseCache(),
    d = userDirs(),
    u = user("alice", d);
  assert.ok(install(cache, st));
  const first = await call(st.settings, "/get", u);
  assert.equal(st.calls.settings, 1);
  const hit = await call(st.settings, "/get", u);
  assert.equal(st.calls.settings, 1, "served from cache");
  assert.equal(hit.headers["content-encoding"], "br");
  assert.equal(hit.headers["vary"], "Accept-Encoding");
  assert.deepEqual(decode(hit), JSON.parse(first.body.toString()));
  const gz = await call(st.settings, "/get", u, { headers: { "accept-encoding": "gzip" } });
  assert.deepEqual(decode(gz), decode(hit));
  const plain = await call(st.settings, "/get", u, { headers: {} });
  assert.equal(plain.headers["content-encoding"], undefined);
  assert.deepEqual(decode(plain), decode(hit));
  fs.writeFileSync(path.join(d.worlds, "新书.json"), "{}"); // e.g. /api/worldinfo/edit, not a hooked route
  const after = await call(st.settings, "/get", u);
  assert.equal(st.calls.settings, 2);
  assert.deepEqual(JSON.parse(after.body.toString()).world_names, ["新书.json"]);
  assert.deepEqual(cache.counts.hits >= 3, true);
});

test("settings/save invalidates at once and the next get returns the saved value", async () => {
  const st = server(),
    cache = new ResponseCache(),
    u = user("alice", userDirs());
  install(cache, st);
  await call(st.settings, "/get", u);
  await call(st.settings, "/save", u, { body: { a: 99 } });
  assert.equal(st.calls.saves, 1);
  const next = await call(st.settings, "/get", u);
  assert.equal(st.calls.settings, 2);
  assert.equal(JSON.parse(JSON.parse(next.body.toString()).settings).a, 99);
});

test("an invalidation during a miss discards that fill; errors are never stored", async () => {
  const st = server(),
    cache = new ResponseCache(),
    u = user("alice", userDirs());
  install(cache, st);
  // A write lands while SillyTavern builds the response: the fill must not be kept.
  const slow = st.settings.stack.find((l) => l.route?.path === "/get" && l !== st.settings.stack[0]);
  const original = slow.handle;
  slow.handle = (req, res, next) => {
    cache.invalidate("alice");
    return original(req, res, next);
  };
  await call(st.settings, "/get", u);
  slow.handle = original;
  await call(st.settings, "/get", u);
  assert.equal(st.calls.settings, 2, "the racing fill was not stored");
  await call(st.settings, "/get", user("bob", userDirs()), { fail: true });
  await call(st.settings, "/get", user("bob", userDirs()), { fail: true });
  assert.equal(st.calls.settings, 4, "500 responses pass through uncached");
});

test("users are cached apart; plug-in and character writes invalidate only their user", async () => {
  const st = server(),
    cache = new ResponseCache(),
    a = user("alice", userDirs()),
    b = user("bob", userDirs());
  install(cache, st);
  fs.writeFileSync(path.join(a.directories.characters, "A.png"), "card");
  await call(st.characters, "/all", a);
  await call(st.characters, "/all", b);
  await call(st.characters, "/all", a);
  await call(st.characters, "/all", b);
  assert.equal(st.calls.characters, 2);
  assert.equal(decode(await call(st.characters, "/all", b)).length, 0, "bob never sees alice's list");
  cache.invalidate("alice"); // what the plug-in's own file writes do
  await call(st.characters, "/all", a);
  await call(st.characters, "/all", b);
  assert.equal(st.calls.characters, 3, "only alice refetched");
  await call(st.characters, "/edit", a, { body: { avatar: "A.png", data: "card2" } });
  await call(st.characters, "/all", a);
  assert.equal(st.calls.characters, 4);
});

test("install refuses routers that do not look like SillyTavern's and undoes cleanly", () => {
  const cache = new ResponseCache();
  assert.equal(install(cache, { settings: router(), characters: router() }), null);
  const st = server(),
    before = [st.settings.stack.length, st.characters.stack.length],
    undo = install(cache, st);
  assert.equal(st.settings.stack.length, before[0] + 2);
  undo();
  assert.deepEqual([st.settings.stack.length, st.characters.stack.length], before);
});
