import assert from "node:assert/strict";
import fs from "node:fs";
import { launch, session, ready, urls, createCharacter, connect, seedDatabase } from "./browser.mjs";

const dir = "artifacts/database-runtime"; fs.mkdirSync(dir, { recursive: true });
const pass = name => console.log("PASS", name);
const browser = await launch();
try {
  const { page } = await session(browser, { helper: false });
  const errors = []; page.on("pageerror", error => errors.push(error.message));
  await ready(page, urls.validation, { probe: true });
  await createCharacter(page); await connect(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  const settle = () => page.waitForTimeout(350);
  const tab = page.locator(".wb-panel-tabs").getByRole("button", { name: "数据库", exact: true });
  const tool = page.locator('[data-wb-tool="builtin:database"]');
  const panel = page.locator(".wb-right .wb-db"), right = page.locator(".wb-right");
  const field = name => panel.getByRole("textbox", { name, exact: true });
  const calls = () => page.evaluate(() => __db.calls);
  const lastCall = async () => (await calls()).at(-1);

  assert.equal(await tool.count(), 0); assert.equal(await tab.count(), 0);
  pass("without the plug-in there is no database tool, tab or page");

  await seedDatabase(page); await settle();
  await tool.click(); await panel.waitFor(); await settle();
  assert.equal(await tab.getAttribute("aria-pressed"), "true");
  assert.equal(await field("天气").inputValue(), "细雨");
  assert.equal(await panel.locator(".wb-db-rows").count(), 0, "a one-row table opens as its form");
  assert.match(await right.locator(".wb-db-status").innerText(), /每 2 层自动填表/);
  await page.screenshot({ path: dir + "/panel-global.png" });
  pass("the composer tool opens the database panel; a one-row table is a form at once");

  await page.locator(".wb-rail").getByRole("button", { name: /重要人物/ }).click(); await settle();
  assert.equal(await panel.locator(".wb-db-rows > li").count(), 3);
  await panel.getByRole("button", { name: /编辑第 1 行/ }).click(); await settle();
  await field("身份").fill("灯塔看守人的女儿，二十四岁");
  page.once("dialog", dialog => dialog.dismiss());
  await panel.getByRole("button", { name: /编辑第 2 行/ }).click(); await settle();
  assert.equal(await field("身份").inputValue(), "灯塔看守人的女儿，二十四岁", "a dirty row asks before another opens");
  await panel.getByRole("button", { name: "保存", exact: true }).click(); await settle();
  assert.deepEqual(await lastCall(), ["updateRow", "重要人物", 1, { 身份: "灯塔看守人的女儿，二十四岁" }]);
  assert.equal(await page.evaluate(() => __db.tables.sheet_people.content[1][2]), "灯塔看守人的女儿，二十四岁");
  pass("a row saves only its changed columns through updateRow, and a dirty draft guards leaving it");

  await panel.getByRole("button", { name: "锁定此格：现状" }).click(); await settle();
  assert.deepEqual(await page.evaluate(() => __db.locks.sheet_people.cells), ["0:3"]);
  assert.equal(await field("现状").getAttribute("readonly"), "");
  assert.equal(await panel.getByRole("button", { name: "删除这一行" }).isDisabled(), true);
  await panel.getByRole("button", { name: "解锁此格：现状" }).click(); await settle();
  await panel.getByRole("button", { name: "锁定整行" }).click(); await settle();
  assert.deepEqual(await page.evaluate(() => __db.locks.sheet_people.rows), [0]);
  assert.equal(await field("姓名").getAttribute("readonly"), "");
  assert.match(await panel.locator(".wb-db-rows > li").first().innerHTML(), /含锁定内容/);
  await page.screenshot({ path: dir + "/panel-locked.png" });
  await panel.getByRole("button", { name: "整行已锁定" }).click(); await settle();
  assert.equal(await field("姓名").getAttribute("readonly"), null);
  pass("cell and row locks toggle through the plug-in, make their fields read-only and block deleting");

  await page.evaluate(() => { __db.locks.sheet_people.cols = [2]; });
  await field("与主角的关系").fill("挚友");
  await panel.getByRole("button", { name: "保存", exact: true }).click(); await settle();
  assert.match(await panel.locator(".wb-db-editor .wb-error").innerText(), /拒绝/);
  assert.equal(await field("与主角的关系").getAttribute("readonly"), "", "the refused write re-reads the locks");
  await page.evaluate(() => { __db.locks.sheet_people.cols = []; workbench.host.database.read(); }); await settle();
  await panel.getByRole("button", { name: "还原" }).click(); await settle();
  pass("a write the plug-in refuses is reported and the editor catches up with its locks");

  await panel.getByRole("button", { name: /编辑第 3 行/ }).click(); await settle();
  await page.evaluate(() => { __db.tables.sheet_people.content.splice(1, 1); workbench.host.database.updated(); }); await settle();
  await field("现状").fill("出海去了。");
  await panel.getByRole("button", { name: "保存", exact: true }).click(); await settle();
  assert.deepEqual(await lastCall(), ["updateRow", "重要人物", 2, { 现状: "出海去了。" }]);
  pass("a row moved by the plug-in is saved at its current position, found by row_id");

  await panel.getByRole("button", { name: /编辑第 1 行/ }).click(); await settle();
  await panel.getByRole("button", { name: "删除这一行" }).click();
  await panel.getByRole("group", { name: "确认删除" }).getByRole("button", { name: "删除", exact: true }).click(); await settle();
  assert.deepEqual(await lastCall(), ["deleteRow", "重要人物", 1]);
  assert.equal(await field("姓名").inputValue(), "老周", "the one row left is a form at once");
  await panel.getByRole("button", { name: "新增行" }).click(); await settle();
  await field("姓名").fill("阿遥"); await field("身份").fill("灯塔新来的学徒");
  await panel.getByRole("button", { name: "添加这一行" }).click(); await settle();
  assert.deepEqual(await lastCall(), ["insertRow", "重要人物", { 姓名: "阿遥", 身份: "灯塔新来的学徒" }]);
  assert.equal(await panel.locator(".wb-db-rows > li.is-selected strong").innerText(), "阿遥");
  pass("deleting asks in place; a new row is inserted only when saved and then stays open");

  await page.locator(".wb-rail").getByRole("button", { name: /全局数据/ }).click(); await settle();
  await right.getByRole("button", { name: "立即填表" }).click();
  await page.waitForFunction(() => document.querySelector(".wb-db-status.is-filling"));
  assert.equal(await tool.getAttribute("data-wb-busy"), "true");
  assert.match(await right.locator(".wb-db-status").innerText(), /填表中/);
  await page.screenshot({ path: dir + "/panel-filling.png" });
  await page.waitForFunction(() => !document.querySelector(".wb-db-status.is-filling")); await settle();
  assert.equal(await field("天气").inputValue(), "雨停了");
  assert.equal(await tool.getAttribute("data-wb-busy"), null);
  pass("立即填表 shows the fill on the status card and the tool, and the form follows the plug-in's update");

  await right.getByRole("button", { name: "数据库设置" }).click(); await settle();
  assert.deepEqual(await lastCall(), ["openSettings"]);
  pass("数据库设置 opens the plug-in's own window");

  await page.getByRole("button", { name: "独立深度编辑" }).click();
  const workspace = page.getByRole("dialog", { name: "独立设置工作区" }); await workspace.waitFor(); await settle();
  assert.equal(await workspace.locator(".wb-settings-nav").getByRole("button", { name: "数据库", exact: true }).getAttribute("aria-pressed"), "true");
  await workspace.locator(".wb-db-tables").getByRole("button", { name: /重要人物/ }).click(); await settle();
  assert.equal(await workspace.locator(".wb-db-grid-row:not(.is-head)").count(), 2);
  await workspace.getByRole("button", { name: "锁定整列：身份" }).click(); await settle();
  assert.deepEqual(await page.evaluate(() => __db.locks.sheet_people.cols), [1]);
  await workspace.getByRole("button", { name: /^第 1 行/ }).click(); await settle();
  assert.equal(await workspace.getByRole("textbox", { name: "身份", exact: true }).getAttribute("readonly"), "");
  const left = await workspace.locator(".wb-db-grid-editor").evaluate(n => n.getBoundingClientRect().width), grid = await workspace.locator(".wb-db-grid").evaluate(n => n.clientWidth);
  assert.ok(Math.abs(left - grid) < 2, "the open row spans the grid's visible width");
  await page.screenshot({ path: dir + "/deep.png" });
  await workspace.locator(".wb-db-grid-row.is-head").getByRole("button", { name: "解锁整列：身份" }).click(); await settle();
  await workspace.getByRole("button", { name: "返回工作台" }).click(); await settle();
  pass("the settings page shows the table as a grid with column locks and the row form unfolded in place");

  await page.setViewportSize({ width: 390, height: 844 }); await page.waitForTimeout(800);
  await page.getByRole("button", { name: "打开输入工具" }).click(); await settle();
  await page.locator(".wb-mobile-tool-grid").getByRole("button", { name: "数据库" }).click(); await settle();
  const chips = page.locator(".wb-right .wb-db-chips");
  await chips.getByRole("button", { name: "物品" }).click(); await settle();
  assert.equal(await page.locator(".wb-right .wb-db-rows > li").count(), 2);
  const box = await page.locator(".wb-right .wb-db").boundingBox();
  assert.ok(box.x >= 0 && box.x + box.width <= 390, "the phone panel stays on screen: " + JSON.stringify(box));
  await page.screenshot({ path: dir + "/phone.png" });
  await page.setViewportSize({ width: 1440, height: 900 }); await page.waitForTimeout(600);
  pass("on a phone the tool sheet opens the panel, with tables as chips");

  await page.evaluate(() => { delete window.AutoCardUpdaterAPI; workbench.host.database.read(); }); await settle();
  assert.equal(await tab.count(), 0); assert.equal(await tool.count(), 0);
  pass("removing the plug-in takes its entries away");

  assert.deepEqual(errors, []);
  pass("no uncaught page errors");
} finally {
  await browser.close();
}
