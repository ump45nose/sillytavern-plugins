// W3 runtime check: world-book groups and archive, connection archive — side rail, top chooser, phone
// chooser, the settings manager, "next" and the in-use rule. Creates and removes its own WBG-* fixtures.
import assert from "node:assert/strict";
import path from "node:path";
import { launch, session, ready, urls, createCharacter, openSettings, artifacts, save } from "./browser.mjs";

const browser = await launch(),
  report = { checkedAt: new Date().toISOString(), checks: [] };
const check = (name, details = {}) => {
  report.checks.push({ name, passed: true, details });
  console.log("PASS", name);
};
const books = ["WBG-甲", "WBG-乙", "WBG-丙", "WBG-丁"],
  profiles = ["WBG-Conn-1", "WBG-Conn-2", "WBG-Conn-3"];
const shot = (page, name) => page.screenshot({ path: path.join(artifacts, `grouping-${name}.png`) });

async function seed(page) {
  return page.evaluate(
    async ({ books, profiles }) => {
      const h = workbench.host,
        c = SillyTavern.getContext(),
        cm = c.extensionSettings.connectionManager;
      for (const name of books)
        if (!h.snapshot().resources.world.some((r) => r.id === name)) await h.createResource("world", name);
      const ids = profiles.map((name) => {
        let p = cm.profiles.find((x) => x.name === name);
        if (!p) {
          p = { id: c.uuidv4(), name, mode: "cc", api: "openai", model: "wbg-model" };
          cm.profiles.push(p);
          document.getElementById("connection_profiles").add(new Option(name, p.id));
        }
        return p.id;
      });
      await h.persistSettings();
      await h.savePreference({ worldGroups: {}, archived: {} });
      await h.setResourceGroup("world", ["WBG-甲", "WBG-乙"], "组A");
      await h.toggleBooks(["WBG-丁"], true);
      // The in-use rule reads the selection; switching for real would load the stub profile into the API.
      cm.selectedProfile = ids[0];
      h.invalidate("resources", "session");
      return ids;
    },
    { books, profiles },
  );
}

async function cleanup(page) {
  await page.evaluate(
    async ({ books, profiles }) => {
      const h = workbench.host,
        c = SillyTavern.getContext(),
        cm = c.extensionSettings.connectionManager;
      if (!h) return;
      await h.toggleBooks(books, false).catch(() => {});
      if (c.chatMetadata?.world_info?.startsWith?.("WBG-")) await h.bindWorld("chat", "");
      if (String(h.snapshot().character?.data?.data?.extensions?.world ?? "").startsWith("WBG-"))
        await h.bindWorld("character", "");
      const wi = await import("/scripts/world-info.js");
      for (const name of books) if (h.snapshot().resources.world.some((r) => r.id === name)) await wi.deleteWorldInfo(name);
      if (profiles.some((n) => n === cm.profiles.find((p) => p.id === cm.selectedProfile)?.name)) cm.selectedProfile = null;
      for (const p of cm.profiles.filter((x) => profiles.includes(x.name)))
        [...document.querySelectorAll("#connection_profiles option")].find((o) => o.value === p.id)?.remove();
      cm.profiles = cm.profiles.filter((x) => !profiles.includes(x.name));
      await h.persistSettings();
      h.pruneOrganization();
    },
    { books, profiles },
  );
}

let page;
try {
  ({ page } = await session(browser));
  const answers = [];
  page.on("dialog", (d) => (d.type() === "prompt" ? d.accept(answers.shift() ?? "") : d.accept()));
  await ready(page, urls.validation, { probe: true });
  await createCharacter(page);
  const ids = await seed(page);

  // ── Manager: groups, batch grouping, rename, dissolve, archive, in-use refusal ──
  await openSettings(page, "世界书");
  const ws = page.getByRole("dialog", { name: "独立设置工作区", exact: true }),
    manager = ws.locator(".wb-resource-manager");
  await manager.locator(".wb-manager-group", { hasText: "组A" }).waitFor();
  const groupOf = (name) =>
    manager
      .locator(".wb-manager-section")
      .filter({ has: page.getByRole("button", { name: "编辑 " + name, exact: true }) })
      .locator(".wb-manager-group strong")
      .textContent();
  assert.equal(await groupOf("WBG-甲"), "组A");
  assert.equal(await groupOf("WBG-丙"), "未分组");
  const pick = (name, on = true) => manager.getByRole("checkbox", { name: "选择 " + name, exact: true }).setChecked(on);
  const action = (name) => manager.locator(".wb-batch-actions").getByRole("button", { name, exact: true });
  await pick("WBG-丙");
  await action("分组").click();
  const groupDialog = page.getByRole("dialog", { name: /移入分组/ });
  await groupDialog.getByLabel("分组名称").fill("组B");
  await groupDialog.getByRole("button", { name: "移入", exact: true }).click();
  await manager.locator(".wb-manager-group", { hasText: "组B" }).waitFor();
  answers.push("组C");
  await manager.getByRole("button", { name: "重命名分组 组B", exact: true }).click();
  await manager.locator(".wb-manager-group", { hasText: "组C" }).waitFor();
  assert.equal(await groupOf("WBG-丙"), "组C");
  await manager.getByRole("button", { name: "解散分组 组C", exact: true }).click();
  await page.waitForFunction(() => !workbench.host.prefs().worldGroups?.["WBG-丙"]);
  assert.equal(await groupOf("WBG-丙"), "未分组");
  check("manager groups books: batch move, rename and dissolve a group", { groups: await manager.locator(".wb-manager-group strong").allTextContents() });

  await pick("WBG-丙", false);
  await pick("WBG-丁");
  await page.evaluate(() => workbench.host.bindWorld("character", "WBG-乙"));
  await pick("WBG-乙");
  assert(await action("归档").isDisabled(), "in-use books must not be archivable");
  const hint = await manager.locator(".wb-batch-hint").textContent();
  assert.match(hint, /WBG-丁」全局启用/);
  assert.match(hint, /WBG-乙」角色卡「WorkbenchFixture」/);
  await pick("WBG-丁", false);
  await pick("WBG-乙", false);
  assert.equal(
    await page.evaluate(async () => (await workbench.host.archiveResources("world", ["WBG-丁"], true)).errors.length),
    1,
    "the host refuses too, not only the button",
  );
  check("books in use (global, character card) cannot be archived and say why", { hint });

  await pick("WBG-甲");
  await action("归档").click();
  await manager.locator(".wb-batch-status").filter({ hasText: "已归档 1" }).waitFor();
  assert.deepEqual(await page.evaluate(() => workbench.host.prefs().archived.world), ["WBG-甲"]);
  assert.equal(await manager.getByRole("button", { name: "编辑 WBG-甲", exact: true }).count(), 0);
  await manager.getByRole("button", { name: /^已归档 \d+$/ }).click();
  await manager.getByRole("button", { name: "编辑 WBG-甲", exact: true }).waitFor();
  await shot(page, "manager-archived");
  await manager.getByRole("button", { name: /^未归档 \d+$/ }).click();
  await shot(page, "manager");
  check("archiving moves a book to the archived shelf of the manager");

  await page.evaluate(() => workbench.host.bindWorld("character", ""));
  await page.keyboard.press("Escape");
  await ws.waitFor({ state: "hidden" }).catch(() => {});
  if (await ws.isVisible()) await ws.getByRole("button", { name: /关闭/ }).first().click();

  // ── Side rail ──
  await page.keyboard.press("Alt+Shift+Digit3");
  const rail = page.locator("#wb-resource-rail");
  await rail.getByRole("checkbox", { name: "整组启用 组A", exact: true }).waitFor();
  const visible = await rail.locator(".wb-rail-list:not([aria-label^='已归档']) .wb-rail-name").allTextContents();
  assert(!visible.includes("WBG-甲"), "archived book listed in the rail");
  assert(visible.includes("WBG-乙") && visible.includes("WBG-丙"));
  await rail.getByRole("checkbox", { name: "整组启用 组A", exact: true }).check();
  await page.waitForFunction(() => workbench.host.snapshot().resources.world.find((r) => r.id === "WBG-乙")?.active);
  assert.equal(await page.evaluate(() => workbench.host.snapshot().resources.world.find((r) => r.id === "WBG-甲").active), false, "a group toggle must not enable archived books");
  await shot(page, "rail");
  await rail.getByRole("checkbox", { name: "整组启用 组A", exact: true }).uncheck();
  await page.waitForFunction(() => !workbench.host.snapshot().resources.world.find((r) => r.id === "WBG-乙")?.active);
  check("the rail groups books, hides archived ones and switches a whole group", { visible: visible.filter((x) => x.startsWith("WBG-")) });

  await rail.getByRole("button", { name: /已归档/ }).click();
  await rail.getByRole("button", { name: "恢复 WBG-甲", exact: true }).waitFor();
  await rail.getByRole("button", { name: "恢复 WBG-甲", exact: true }).click();
  await page.waitForFunction(() => !workbench.host.prefs().archived.world.includes("WBG-甲"));
  await rail.locator(".wb-rail-list:not([aria-label^='已归档']) .wb-rail-name", { hasText: /^WBG-甲$/ }).waitFor();
  await page.evaluate(() => workbench.host.archiveResources("world", ["WBG-甲"], true));
  check("the rail's archived fold restores a book to its group");

  // ── Top chooser ──
  await page.locator('.wb-pill[aria-controls="wb-choices-world"]').click();
  const pop = page.locator("#wb-choices-world");
  await pop.locator(".wb-pill-pop-group", { hasText: "组A" }).waitFor();
  const popNames = await pop.locator(".wb-pill-pop-copy strong").allTextContents();
  assert(!popNames.includes("WBG-甲") && popNames.includes("WBG-乙"));
  await page.waitForTimeout(400);
  await shot(page, "chooser");
  await pop.getByRole("checkbox", { name: "整组启用 组A", exact: true }).check();
  await page.waitForFunction(() => workbench.host.snapshot().resources.world.find((r) => r.id === "WBG-乙")?.active);
  await pop.getByRole("checkbox", { name: "整组启用 组A", exact: true }).uncheck();
  await page.waitForFunction(() => !workbench.host.snapshot().resources.world.find((r) => r.id === "WBG-乙")?.active);
  await page.keyboard.press("Escape");
  await page.locator('.wb-pill[aria-controls="wb-choices-world"]').click();
  check("the top chooser lists groups without archived books and switches a group", { popNames: popNames.filter((x) => x.startsWith("WBG-")) });

  // ── Connections: archive, in-use refusal, "next" skips archived ──
  const refused = await page.evaluate(async (id) => (await workbench.host.archiveResources("connection", [id], true)).errors, ids[0]);
  assert.match(refused[0].message, /当前连接/);
  await page.evaluate((id) => workbench.host.archiveResources("connection", [id], true), ids[1]);
  await page.locator('.wb-pill[aria-controls="wb-choices-connection"]').click();
  const conns = await page.locator("#wb-choices-connection .wb-pill-pop-copy strong").allTextContents();
  assert(conns.includes("WBG-Conn-1") && conns.includes("WBG-Conn-3") && !conns.includes("WBG-Conn-2"));
  await page.locator('.wb-pill[aria-controls="wb-choices-connection"]').click();
  await page.evaluate(() => {
    window.__wbgSelected = [];
    workbench.host.select = async (kind, id) => void window.__wbgSelected.push([kind, id]);
  });
  await page.locator("body").click({ position: { x: 5, y: 450 } }).catch(() => {});
  await page.keyboard.press("Alt+Shift+KeyN");
  await page.waitForFunction(() => window.__wbgSelected.length);
  assert.deepEqual(await page.evaluate(() => window.__wbgSelected[0]), ["connection", ids[2]]);
  await page.evaluate(() => delete workbench.host.select);
  check("connections: the current one cannot be archived; archived ones leave the chooser and next skips them");

  // ── Persistence ──
  await page.reload();
  await ready(page, urls.validation, { probe: true });
  const after = await page.evaluate(() => {
    const p = workbench.host.prefs();
    return { world: p.archived?.world, connection: p.archived?.connection, groups: p.worldGroups };
  });
  assert.deepEqual(after.world, ["WBG-甲"]);
  assert.deepEqual(after.connection, [ids[1]]);
  assert.equal(after.groups["WBG-乙"], "组A");
  check("groups and archive marks survive a reload", after);

  // ── Phone: Noval's 快捷配置 key opens the grouped rail; RP's tools sheet holds the chooser tiles ──
  const phone = await session(browser, { mobile: true });
  const p = phone.page;
  await ready(p, urls.validation, { probe: true });
  await p.getByRole("group", { name: "快捷配置" }).getByRole("button").nth(2).click();
  // Phones have no rail: the panel title opens the picker popup, grouped with group toggles.
  await p.locator(".wb-right").getByRole("button", { name: "选择世界书", exact: true }).click();
  const menu = p.locator(".wb-resource-menu");
  await menu.getByRole("checkbox", { name: "整组启用 组A", exact: true }).waitFor();
  const menuNames = await menu.locator(".wb-picker-copy strong").allTextContents();
  assert(!menuNames.includes("WBG-甲") && menuNames.includes("WBG-乙"));
  await p.screenshot({ path: path.join(artifacts, "grouping-phone-picker.png") });
  await p.keyboard.press("Escape");
  await p.locator(".wb-panel-close").click();
  const layout = await p.evaluate(() => workbench.host.prefs().layout);
  await p.getByRole("button", { name: "打开会话管理", exact: true }).click();
  await p.getByRole("button", { name: "RP", exact: true }).click();
  await p.waitForFunction(() => document.body.classList.contains("wb-mobile-rp"));
  // RP reading has no input of its own; stepping into the reply shows it with its tools button.
  await p.waitForTimeout(400);
  const forward = p.getByRole("button", { name: "快进到你的回应", exact: true });
  if (await forward.isVisible()) await forward.click();
  await p.waitForTimeout(400);
  await p.getByRole("button", { name: "打开输入工具", exact: true }).click();
  await p.locator(".wb-mobile-tool-config").getByRole("button", { name: /^世界书：/ }).click();
  const sheet = p.locator(".wb-mobile-resource-popup");
  await sheet.locator(".wb-quick-group", { hasText: "组A" }).waitFor();
  const phoneNames = await sheet.locator(".wb-quick-row strong").allTextContents();
  assert(!phoneNames.includes("WBG-甲") && phoneNames.includes("WBG-乙"));
  await p.waitForTimeout(500);
  await p.screenshot({ path: path.join(artifacts, "grouping-phone-chooser.png") });
  await p.getByRole("button", { name: "关闭资源选择", exact: true }).click();
  // The layout is a saved preference; put back what the instance had.
  await p.evaluate((value) => workbench.host.savePreference({ layout: value }), layout);
  await p.context().close();
  check("phone: the panel picker and the RP chooser group books and hide archived ones");

  // ── Deleting a book drops its keys ──
  await page.evaluate(async () => {
    const wi = await import("/scripts/world-info.js");
    await wi.deleteWorldInfo("WBG-甲");
    workbench.host.pruneOrganization();
  });
  const pruned = await page.evaluate(() => workbench.host.prefs());
  assert(!pruned.archived.world.includes("WBG-甲") && !("WBG-甲" in pruned.worldGroups));
  check("a deleted book's group and archive mark are pruned");
  save("grouping-runtime.json", report);
} finally {
  if (page) await cleanup(page).catch((e) => console.error("cleanup", e));
  await browser.close();
}
