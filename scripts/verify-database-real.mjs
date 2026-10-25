import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { launch, session, ready, urls, root, createCharacter, connect } from "./browser.mjs";

// Joint check against the real database plug-in (龙血玄黄·数据库) installed in the validation instance;
// verify:database covers the same flows against a stand-in. Writes only to the fixture chat and removes its rows.
const installed = path.join(root, "runtime/validation/data/default-user/extensions/shujuku/manifest.json");
if (!fs.existsSync(installed)) {
  console.log("SKIP database plug-in not installed in runtime/validation (extensions/shujuku)");
  process.exit(0);
}
const dir = "artifacts/database-real"; fs.mkdirSync(dir, { recursive: true });
const pass = name => console.log("PASS", name);
const browser = await launch();
try {
  const { page } = await session(browser, { helper: false, database: true });
  const errors = []; page.on("pageerror", error => errors.push(error.message));
  await ready(page, urls.validation, { probe: true });
  await createCharacter(page); await connect(page);
  // The plug-in loads the chat's tables shortly after the chat opens and reports them through its update callback.
  const loaded = await page.waitForFunction(() => workbench.host.database.state.tables.length, null, { timeout: 15_000 }).then(() => true, () => false);
  pass(loaded ? "the workbench picks up the tables the plug-in loads after the chat opens" : "the fixture chat has no tables yet; creating them from the template");
  await page.setViewportSize({ width: 1440, height: 900 });

  const read = await page.evaluate(async () => {
    const api = AutoCardUpdaterAPI, db = workbench.host.database;
    const sheets = () => Object.keys(api.exportTableAsJson() ?? {}).filter(k => k.startsWith("sheet_"));
    if (!sheets().length) await api.overrideWithTemplate();
    db.read();
    const exported = api.exportTableAsJson();
    return {
      error: db.state.error,
      tables: db.state.tables.map(t => ({ key: t.key, name: t.name, columns: t.columns })),
      headers: Object.fromEntries(sheets().map(k => [k, exported[k].content[0]])),
    };
  });
  assert.equal(read.error, "");
  assert.ok(read.tables.length > 0, "the template gives the chat tables");
  for (const t of read.tables) assert.deepEqual(t.columns, read.headers[t.key].slice(1), `${t.name}: row_id column left out`);
  pass(`the plug-in's ${read.tables.length} tables read with their columns, without row_id`);

  const r = await page.evaluate(async () => {
    const api = AutoCardUpdaterAPI, db = workbench.host.database, out = {};
    const t0 = db.state.tables.find(t => t.columns.length >= 2), table = () => db.table(t0.key);
    const [c0, c1] = t0.columns;
    const last = () => api.exportTableAsJson()[t0.key].content.at(-1);
    let updates = 0; const count = () => updates++; api.registerTableUpdateCallback(count);
    out.id = await db.insertRow(table(), { [c0]: "联调新行", [c1]: "原值" });
    out.inserted = last().slice(0, 3);
    await db.saveRow(table(), table().rows.at(-1), { [c0]: "改过" });
    out.saved = last().slice(0, 3);
    const refused = async (patch) => api.updateRow(t0.name, table().rows.at(-1).index, patch);
    db.toggleLock(table(), { row: table().rows.at(-1) });
    out.rowLock = [table().locks.rows.includes(table().rows.at(-1).index - 1), await refused({ [c0]: "x" })];
    db.toggleLock(table(), { row: table().rows.at(-1) });
    db.toggleLock(table(), { col: 0 });
    out.colLock = [await refused({ [c0]: "x" }), await refused({ [c1]: "列2可写" })];
    db.toggleLock(table(), { col: 0 });
    db.toggleLock(table(), { row: table().rows.at(-1), col: 1 });
    out.cellLock = [await refused({ [c1]: "x" }), await refused({ [c0]: "列1可写" })];
    db.toggleLock(table(), { row: table().rows.at(-1), col: 1 });
    out.unlocked = api.getTableLockState(t0.key);
    out.final = last().slice(0, 3);
    const before = api.exportTableAsJson()[t0.key].content.length;
    await db.deleteRow(table(), table().rows.at(-1));
    out.deleted = before - api.exportTableAsJson()[t0.key].content.length;
    out.updates = updates;
    api.unregisterTableUpdateCallback(count);
    return out;
  });
  assert.equal(r.inserted[0], r.id); assert.deepEqual(r.inserted.slice(1), ["联调新行", "原值"]);
  assert.deepEqual(r.saved.slice(1), ["改过", "原值"]);
  pass("insert returns the new row_id; save writes only the changed column");
  assert.deepEqual(r.rowLock, [true, false]);
  assert.deepEqual(r.colLock, [false, true]);
  assert.deepEqual(r.cellLock, [false, true]);
  assert.deepEqual(r.unlocked, { rows: [], cols: [], cells: [] });
  assert.deepEqual(r.final.slice(1), ["列1可写", "列2可写"]);
  pass("row, column and cell locks land on the intended targets (0-based) and the plug-in refuses those writes");
  assert.equal(r.deleted, 1); assert.ok(r.updates >= 4, `update callbacks: ${r.updates}`);
  pass("delete removes the row; the plug-in's update callback fires on each write");

  const options = await page.evaluate(async () => {
    const api = AutoCardUpdaterAPI, o = workbench.host.options;
    const sheet = Object.values(api.exportTableAsJson()).find(t => t?.name === "选项表");
    if (!sheet) return null;
    const name = sheet.name, cols = sheet.content[0].slice(1);
    const index = await api.insertRow(name, { [cols[0]]: "联调选项" });
    await o.save({ source: "db", table: name });
    const first = o.state.items.map(i => i.title);
    await api.updateRow(name, index, { [cols[0]]: "联调选项改" });
    const after = o.state.items.map(i => i.title);
    await o.save({ source: "off", table: "" });
    await api.deleteRow(name, index);
    return { first, after };
  });
  if (options) {
    assert.ok(options.first.includes("联调选项"), JSON.stringify(options.first));
    assert.ok(options.after.includes("联调选项改") && !options.after.includes("联调选项"), JSON.stringify(options.after));
    pass("story options follow the plug-in's 选项表 on every update");
  } else console.log("SKIP this template has no 选项表");

  const fill = await page.evaluate(async () => {
    const db = workbench.host.database, seen = [];
    const off = db.subscribe(() => seen.push(db.state.filling));
    await db.fill(); off();
    return { seen, filling: db.state.filling };
  });
  assert.equal(fill.seen[0], true); assert.equal(fill.filling, false);
  pass("立即填表 shows filling and clears it when the plug-in finishes");

  await page.locator('[data-wb-tool="builtin:database"]').click();
  const panel = page.locator(".wb-right .wb-db"); await panel.waitFor();
  assert.ok(await page.locator(".wb-right .wb-db-status").count());
  await page.screenshot({ path: dir + "/panel.png" });
  await page.getByRole("button", { name: "独立深度编辑" }).click();
  const workspace = page.getByRole("dialog", { name: "独立设置工作区" }); await workspace.waitFor();
  assert.equal(await workspace.locator(".wb-db-tables").getByRole("button").count() >= read.tables.length, true);
  await page.waitForTimeout(350);
  await page.screenshot({ path: dir + "/deep.png" });
  pass("right panel and deep page render the plug-in's tables");

  assert.deepEqual(errors, []);
  pass("no uncaught page errors");
} finally {
  await browser.close();
}
