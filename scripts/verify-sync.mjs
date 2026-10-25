import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { launch, session, ready, urls, root, credentials, seedDatabase } from "./browser.mjs";

// IDE sync against the validation instance with the workbench-sync plug-in loaded (npm run build links
// it; local-runtime turns plug-ins on). An HTTP client stands in for VS Code. Without a page, writes
// go straight to disk; with this checkout's workbench open, they go through the page. Fixtures are
// its own world book, preset, character and chat, removed at the end; the shared connection profile
// and persona it edits are written back.
const base = urls.validation;
const user = path.join(root, "runtime/validation/data/default-user");
const WORLD = "WorkbenchSyncWorld",
  PRESET = "WorkbenchSyncPreset",
  CHAR = "WorkbenchSyncFixture",
  PROFILE = "连接/Workbench Test A.yaml",
  PERSONA = "用户设定/[Unnamed Persona].md";
const pass = (name) => console.log("PASS", name);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function until(fn, what, ms = 8000) {
  const end = Date.now() + ms;
  for (;;) {
    const value = await fn();
    if (value) return value;
    if (Date.now() > end) throw new Error(`timed out: ${what}`);
    await sleep(100);
  }
}
const json = (file) => JSON.parse(fs.readFileSync(file, "utf8"));
const settings = () => json(path.join(user, "settings.json"));

// ── The IDE: Basic Auth, a session cookie and its CSRF token, as the VS Code extension sends them ──
const auth = "Basic " + Buffer.from(`${credentials.username}:${credentials.password}`).toString("base64");
const csrf = await fetch(base + "/csrf-token", { headers: { authorization: auth } });
assert.equal(csrf.status, 200, "Basic Auth and /csrf-token");
const headers = {
  authorization: auth,
  cookie: csrf.headers
    .getSetCookie()
    .map((c) => c.split(";")[0])
    .join("; "),
  "x-csrf-token": (await csrf.json()).token,
  "content-type": "application/json",
};
async function call(method, url, body) {
  const response = await fetch(base + url, { method, headers, body: body && JSON.stringify(body) });
  const text = await response.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    data = text;
  }
  return { status: response.status, data };
}
const tavern = async (route, body) => {
  const r = await call("POST", route, body);
  assert.ok(r.status < 300, `${route}: ${r.status} ${JSON.stringify(r.data)}`);
  return r.data;
};
const sync = (method, route, body) => call(method, "/api/plugins/workbench-sync/" + route, body);
const tree = async (p) => {
  const r = await sync("GET", "tree?path=" + encodeURIComponent(p));
  assert.equal(r.status, 200, `tree ${p}: ${JSON.stringify(r.data)}`);
  return r.data.entries.map((e) => e.name);
};
const read = async (p) => {
  const r = await sync("GET", "file?path=" + encodeURIComponent(p));
  assert.equal(r.status, 200, `read ${p}: ${JSON.stringify(r.data)}`);
  return r.data;
};
const put = (p, text, version) => sync("PUT", "file", { path: p, text, base: version });
/** Reads, changes and saves a file as an editor would; returns the stale version and the reply. */
async function edit(p, change, route) {
  const file = await read(p),
    text = change(file.text);
  assert.notEqual(text, file.text, `${p}: the edit changes the text`);
  const r = await put(p, text, file.version);
  assert.equal(r.status, 200, `write ${p}: ${JSON.stringify(r.data)}`);
  assert.equal(r.data.route, route, `${p} written via ${route}`);
  return { stale: file.version, text, reply: r.data };
}
const setLine = (key, value) => (text) =>
  new RegExp(`^${key}: .*$`, "m").test(text)
    ? text.replace(new RegExp(`^${key}: .*$`, "m"), `${key}: ${value}`)
    : text.replace(/\n?$/, `\n${key}: ${value}\n`);

// ── The IDE's event stream ──
const events = [];
const stream = new AbortController();
(async () => {
  const response = await fetch(base + "/api/plugins/workbench-sync/events?role=ide", {
    headers,
    signal: stream.signal,
  });
  const decoder = new TextDecoder();
  let buffer = "";
  for await (const chunk of response.body) {
    buffer += decoder.decode(chunk, { stream: true });
    for (let end; (end = buffer.indexOf("\n\n")) >= 0; ) {
      const block = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      const event = block.match(/^event: (.*)$/m)?.[1],
        data = block.match(/^data: (.*)$/m)?.[1];
      if (event && data) events.push({ event, data: JSON.parse(data) });
    }
  }
})().catch(() => {});
const pushed = (file, from) =>
  until(
    () =>
      events
        .slice(from)
        .some((e) => e.event === "changed" && [...e.data.changed, ...e.data.created].includes(file)),
    `changed event for ${file}`,
  );

const info = await sync("GET", "info");
if (info.status !== 200) {
  console.error("FAIL workbench-sync is not loaded on the validation instance: run npm run build, then");
  console.error(
    "     node scripts/local-runtime.mjs stop validation visual && node scripts/local-runtime.mjs start validation visual",
  );
  process.exit(1);
}
assert.equal(
  info.data.pages,
  0,
  "no other workbench page with IDE sync is connected to the validation instance",
);
await until(async () => (await sync("GET", "info")).data.clients >= 1, "the IDE stream is attached");

const restore = {};
let avatar = "",
  chat = "",
  browser;
try {
  // ── Fixtures ──
  await tavern("/api/worldinfo/edit", {
    name: WORLD,
    data: json(path.join(user, "worlds/WorkbenchFixtureWorld.json")),
  });
  await tavern("/api/presets/save", {
    apiId: "openai",
    name: PRESET,
    preset: json(path.join(user, "OpenAI Settings/WorkbenchFixturePreset.json")),
  });
  const form = new FormData();
  form.set("ch_name", CHAR);
  form.set("description", "IDE 同步验证用角色。");
  form.set("first_mes", "同步验证开始。");
  form.set("scenario", "旧场景");
  const { "content-type": _, ...formHeaders } = headers;
  const created = await fetch(base + "/api/characters/create", {
    method: "POST",
    headers: formHeaders,
    body: form,
  });
  assert.equal(created.status, 200, "fixture character created");
  avatar = (await created.text()).trim();
  chat = (await tavern("/api/characters/get", { avatar_url: avatar })).chat;
  await tavern("/api/chats/save", {
    ch_name: CHAR,
    file_name: chat,
    avatar_url: avatar,
    chat: [
      { user_name: "User", character_name: CHAR, create_date: "2026-10-20@00h00m00s", chat_metadata: {} },
      { name: CHAR, is_user: false, mes: "同步验证开始。", send_date: "2026-10-20@00h00m00s" },
    ],
  });
  restore.profile = (await read(PROFILE)).text;
  restore.persona = (await read(PERSONA)).text;
  restore.active = settings().active_character;

  assert.deepEqual(await tree(""), ["世界书", "角色", "预设", "连接", "用户设定", "大纲", "数据库"]);
  const entry = `世界书/${WORLD}/${(await tree("世界书/" + WORLD))[0]}`;
  const prompt = `预设/${PRESET}/提示词/${(await tree(`预设/${PRESET}/提示词`))[0]}`;
  const outline = `大纲/${CHAR}/${chat}.md`;
  assert.ok((await tree(`角色/${CHAR}`)).includes("场景.md"));
  pass("the IDE lists every area and the fixtures as readable files");

  // ── No page: straight to SillyTavern's files ──
  const worldFile = path.join(user, "worlds", WORLD + ".json"),
    presetFile = path.join(user, "OpenAI Settings", PRESET + ".json"),
    chatFile = path.join(user, "chats", CHAR, chat + ".jsonl");
  const world = await edit(entry, (t) => t.replace(/\n[^\n]*$/, "\n直写磁盘的条目内容。"), "disk");
  assert.match(Object.values(json(worldFile).entries)[0].content, /直写磁盘的条目内容。$/);
  await edit(`角色/${CHAR}/场景.md`, () => "直写磁盘的场景", "disk");
  assert.equal((await tavern("/api/characters/get", { avatar_url: avatar })).data.scenario, "直写磁盘的场景");
  await edit(`预设/${PRESET}/参数.yaml`, setLine("温度", 0.31), "disk");
  assert.equal(json(presetFile).temperature, 0.31);
  await edit(prompt, (t) => t + "\n直写磁盘的提示词。", "disk");
  assert.ok(json(presetFile).prompts.some((p) => p.content?.endsWith("直写磁盘的提示词。")));
  await edit(PROFILE, setLine("模型", "sync-disk-model"), "disk");
  assert.equal(
    settings().extension_settings.connectionManager.profiles.find((p) => p.id === "wb-test-1").model,
    "sync-disk-model",
  );
  await edit(PERSONA, (t) => t + "\n直写磁盘的用户设定。", "disk");
  assert.match(
    settings().power_user.persona_descriptions["user-default.png"].description,
    /直写磁盘的用户设定。$/,
  );
  await edit(outline, () => "# 第一章\n直写磁盘的大纲。\n", "disk");
  const header = () => JSON.parse(fs.readFileSync(chatFile, "utf8").split("\n")[0]);
  assert.deepEqual(
    header().chat_metadata.workbench_addons.outline.nodes.map((n) => [n.title, n.content]),
    [["第一章", "直写磁盘的大纲。"]],
  );
  assert.equal(header().character_name, CHAR, "the rest of the chat header is kept");
  pass(
    "without a page: world book, character, preset parameters and prompt, connection, persona and outline written to disk",
  );

  let r = await put(entry, world.text + "过期", world.stale);
  assert.equal(r.status, 409, "a save over a newer version is refused");
  r = await put(`预设/${PRESET}/参数.yaml`, "温度: 很高\n", (await read(`预设/${PRESET}/参数.yaml`)).version);
  assert.equal(r.status, 422);
  assert.equal(r.data.line, 1, JSON.stringify(r.data));
  assert.ok(!(await tree("数据库")).includes(CHAR));
  r = await put(`数据库/${CHAR}/${chat}/重要人物.md`, "", "");
  assert.equal(r.status, 404);
  assert.match(r.data.error, /打开该聊天后可同步/);
  pass("409 on a stale base, 422 with the line, database refused while its chat is not open in a page");

  let mark = events.length;
  const onDisk = json(worldFile);
  Object.values(onDisk.entries)[0].content = "外部修改的条目内容。";
  fs.writeFileSync(worldFile, JSON.stringify(onDisk, null, 4));
  await pushed(entry, mark);
  assert.match((await read(entry)).text, /外部修改的条目内容。$/);
  pass("a change in SillyTavern's files reaches the IDE as a changed event");

  // ── With this checkout's workbench open: through the page ──
  browser = await launch();
  const { context, page, errors } = await session(browser);
  // The instances load the main checkout's extension; this run serves the one built here.
  const extension = path.join(root, "extension");
  const types = {
    ".js": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".woff2": "font/woff2",
  };
  await context.route("**/scripts/extensions/third-party/workbench-probe/**", (route) => {
    const rel = decodeURIComponent(new URL(route.request().url()).pathname.split("/workbench-probe/")[1]);
    const file = path.join(extension, rel);
    if (!file.startsWith(extension + path.sep) || !fs.existsSync(file)) return route.fulfill({ status: 404 });
    return route.fulfill({
      body: fs.readFileSync(file),
      contentType: types[path.extname(file)] ?? "application/octet-stream",
    });
  });
  await ready(page, base, { probe: true });
  await page.waitForFunction(() => workbench.host.sync.state.status === "online", null, { timeout: 15_000 });
  await page.evaluate(async (name) => {
    const c = SillyTavern.getContext();
    await c.getCharacters();
    await c.selectCharacterById(c.characters.findIndex((x) => x.name === name));
  }, CHAR);
  await page.waitForFunction((id) => SillyTavern.getContext().getCurrentChatId() === id, chat, {
    timeout: 15_000,
  });
  assert.equal((await sync("GET", "info")).data.pages, 1);
  pass("the page connects to the plug-in and opens the fixture chat");

  await edit(entry, (t) => t.replace(/\n[^\n]*$/, "\n经页面写入的条目内容。"), "page");
  const memoryWorld = await page.evaluate(
    (name) => Object.values(workbench.host.world.worldInfoCache.get(name).entries)[0].content,
    WORLD,
  );
  assert.equal(memoryWorld, Object.values(json(worldFile).entries)[0].content);
  assert.match(memoryWorld, /经页面写入的条目内容。$/);

  await edit(`角色/${CHAR}/场景.md`, () => "经页面写入的场景", "page");
  const memoryCharacter = await page.evaluate(
    async (id) => (await workbench.host.characterData(id)).data.scenario,
    avatar,
  );
  assert.equal(memoryCharacter, "经页面写入的场景");
  assert.equal(
    await page.evaluate(
      (id) => SillyTavern.getContext().characters.find((c) => c.avatar === id).scenario,
      avatar,
    ),
    "经页面写入的场景",
    "the page's character list holds the new scenario",
  );

  await edit(`预设/${PRESET}/参数.yaml`, setLine("温度", 0.42), "page");
  const memoryPreset = await page.evaluate((name) => {
    const { presets, preset_names } = SillyTavern.getContext().getPresetManager("openai").getPresetList();
    return presets[Array.isArray(preset_names) ? preset_names.indexOf(name) : preset_names[name]].temperature;
  }, PRESET);
  assert.equal(memoryPreset, 0.42);
  assert.equal(json(presetFile).temperature, 0.42);

  await edit(PROFILE, setLine("模型", "sync-page-model"), "page");
  const memoryProfile = await page.evaluate(
    () =>
      SillyTavern.getContext().extensionSettings.connectionManager.profiles.find((p) => p.id === "wb-test-1")
        .model,
  );
  assert.equal(memoryProfile, "sync-page-model");
  await until(
    () =>
      settings().extension_settings.connectionManager.profiles.find((p) => p.id === "wb-test-1").model ===
      "sync-page-model",
    "the page saves settings",
  );

  await edit(PERSONA, (t) => t + "\n经页面写入的用户设定。", "page");
  const memoryPersona = await page.evaluate(
    () => SillyTavern.getContext().powerUserSettings.persona_descriptions["user-default.png"].description,
  );
  assert.match(memoryPersona, /经页面写入的用户设定。$/);
  await until(
    () => settings().power_user.persona_descriptions["user-default.png"].description === memoryPersona,
    "the page saves the persona",
  );

  await edit(outline, (t) => t.replace("直写磁盘的大纲。", "经页面写入的大纲。"), "page");
  const memoryOutline = await page.evaluate(() =>
    SillyTavern.getContext().chatMetadata.workbench_addons.outline.nodes.map((n) => n.content),
  );
  assert.deepEqual(memoryOutline, ["经页面写入的大纲。"]);
  await until(
    () => header().chat_metadata.workbench_addons?.outline?.nodes?.[0]?.content === "经页面写入的大纲。",
    "the open chat's outline is saved",
  );
  pass(
    "with a page: world book, character, preset, connection, persona and the open chat's outline go through the page; page memory equals disk",
  );

  r = await put(entry, "过期", world.stale);
  assert.equal(r.status, 409, "409 through the page path as well");

  // Database tables of the open chat, through the stand-in plug-in.
  await seedDatabase(page);
  await page.evaluate(() => workbench.host.database.read());
  const tableFile = `数据库/${CHAR}/${chat}/重要人物.md`;
  await until(
    async () =>
      (await sync("GET", "tree?path=" + encodeURIComponent(`数据库/${CHAR}/${chat}`))).data.entries?.length,
    "the page reports its tables",
  );
  assert.deepEqual(await tree(`数据库/${CHAR}/${chat}`), [
    "全局数据.md",
    "重要人物.md",
    "物品.md",
    "选项表.md",
  ]);
  const table = await read(tableFile);
  assert.match(table.text, /^\| row_id \| 姓名 \| 身份 \| 与主角的关系 \| 现状 \|$/m);
  const tableEdit = await edit(
    tableFile,
    (t) =>
      t
        .replace("今天迟到了。", "今天准时到了。")
        .replace(/^\| 3 \|.*\n/m, "")
        .concat("|  | 阿青 | 船匠 | 新认识 | 在码头修船。 |\n"),
    "page",
  );
  const db = await page.evaluate(() => ({
    rows: __db.tables.sheet_people.content.slice(1),
    calls: __db.calls.map((c) => c[0]),
  }));
  assert.deepEqual(
    db.rows.map((row) => row[1]),
    ["林晚", "沈舟", "阿青"],
  );
  assert.equal(db.rows[1][4], "每天黄昏送信到灯塔，今天准时到了。");
  const newId = db.rows[2][0];
  assert.deepEqual(db.rows[2].slice(1), ["阿青", "船匠", "新认识", "在码头修船。"]);
  assert.ok(newId && !["1", "2"].includes(newId), `new row_id ${newId}`);
  assert.deepEqual(db.calls, ["updateRow", "deleteRow", "insertRow"]);
  assert.equal(tableEdit.reply.normalized, true, "the new row's id comes back to the IDE");
  assert.ok((await read(tableFile)).text.includes(`\n| ${newId} | 阿青 |`));
  pass("database: a changed cell, a removed row and a new row go through the plug-in's API in the open chat");

  mark = events.length;
  await page.evaluate(() => AutoCardUpdaterAPI.updateRow("重要人物", 1, { 现状: "插件填表改写。" }));
  await pushed(tableFile, mark);
  r = await put(tableFile, tableEdit.text, tableEdit.reply.version);
  assert.equal(r.status, 409, "a table the plug-in changed meanwhile is not overwritten");
  mark = events.length;
  await page.evaluate(async (name) => {
    const book = structuredClone(workbench.host.world.worldInfoCache.get(name));
    const draft = structuredClone(book);
    Object.values(draft.entries)[0].content = "工作台页面里改的条目内容。";
    await workbench.host.saveBook(name, book, draft);
  }, WORLD);
  await pushed(entry, mark);
  assert.match((await read(entry)).text, /工作台页面里改的条目内容。$/);
  pass("changes made in the page (a table fill, a world book save) reach the IDE; 409 on the table");

  assert.deepEqual(errors, []);
  pass("no uncaught page errors");
  await browser.close();
  browser = null;
  await until(async () => (await sync("GET", "info")).data.pages === 0, "the page disconnects");
} finally {
  await browser?.close();
  // Shared fixtures are written back as they were; the run's own fixtures are removed.
  for (const [file, text] of [
    [PROFILE, restore.profile],
    [PERSONA, restore.persona],
  ])
    if (text !== undefined) {
      const current = await read(file);
      if (current.text !== text)
        assert.equal((await put(file, text, current.version)).status, 200, `restore ${file}`);
    }
  await call("POST", "/api/worldinfo/delete", { name: WORLD });
  await call("POST", "/api/presets/delete", { apiId: "openai", name: PRESET });
  if (avatar) await call("POST", "/api/characters/delete", { avatar_url: avatar, delete_chats: true });
  if (restore.active !== undefined && settings().active_character === avatar) {
    const s = settings();
    s.active_character = restore.active;
    fs.writeFileSync(path.join(user, "settings.json"), JSON.stringify(s, null, 4));
  }
  stream.abort();
}
assert.ok(!fs.existsSync(path.join(user, "worlds", WORLD + ".json")));
assert.ok(!fs.existsSync(path.join(user, "OpenAI Settings", PRESET + ".json")));
assert.ok(!fs.existsSync(path.join(user, "characters", avatar)));
pass("fixtures removed; the shared connection profile and persona restored");
