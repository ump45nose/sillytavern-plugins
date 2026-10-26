// Placeholder variables against the real quick-reply flow: /buttons menu → /setinput with prompted
// placeholders → the workbench dialog over the native popup → later reads, /inject, Enter, reload and
// the settings panel. WB_QR_SET=<file> runs a real quick-reply set export (it must have the super menu's
// 🎛️控制菜单 with ⚙️@角色指定 / 🤝男女主汇合 / 👨切换主角-男主); otherwise a synthetic set with the same
// structure is used. The set, the fixture's variables and the injection are removed afterwards.
import assert from "node:assert/strict";
import fs from "node:fs";
import { launch, session, ready, urls, artifacts, createCharacter, openSettings } from "./browser.mjs";

const MENU = "🎛️控制菜单";
const branches = `/setvar key=choice ||
/if left=choice rule=eq right="" {: /abort :} ||
/if left=choice rule=eq right="⚙️@角色指定" {: /setinput {{input}}<{@男主:男主:请输入接下来剧情男性的名称:-1}{@女主:女主:请输入接下来剧情女性的名称:-1}> ||/run ${MENU} :} ||
/if left=choice rule=eq right="🤝男女主汇合" {: /setinput {{input}}<{@男主:男主}和{@女主:女主}合理的碰面了> ||/run ${MENU} :} ||
/if left=choice rule=eq right="👨切换主角-男主" {: /inject id=色情主角 position=before depth=0 role=system <切换到{@男主:男主}的控制视角> ||/run ${MENU} :}`;
const synthetic = {
  name: "WB占位符验证",
  qrList: [
    {
      label: MENU,
      message: `/buttons labels=["⬅️返回","➕同时","▶️发送","--------","⚙️@角色指定","🤝男女主汇合","👨切换主角-男主"] 控制{@男主:男主} |\n${branches}`,
    },
  ],
};
const qrSet = process.env.WB_QR_SET ? JSON.parse(fs.readFileSync(process.env.WB_QR_SET, "utf8")) : synthetic;
const directory = artifacts + "/placeholders";
fs.mkdirSync(directory, { recursive: true });
const browser = await launch(),
  checks = [];
const pass = (name) => {
  checks.push(name);
  console.log("PASS", name);
};
let page, avatar;
try {
  ({ page } = await session(browser));
  await page.setViewportSize({ width: 1496, height: 817 });
  await ready(page, urls.validation);
  await page.waitForFunction(() => window.workbench?.mounted);
  ({ name: avatar } = await createCharacter(page));
  avatar = await page.evaluate(() => workbench.host.placeholders.scope().key);
  await page.evaluate(async (set) => {
    const api = globalThis.quickReplyApi;
    if (api.getSetByName(set.name)) await api.deleteSet(set.name);
    await api.createSet(set.name);
    for (const qr of set.qrList)
      api.createQuickReply(set.name, qr.label, { message: qr.message, isHidden: true });
    api.addGlobalSet(set.name, false);
    workbench.host.placeholders.setVars(workbench.host.placeholders.scope().key, {});
    document.getElementById("send_textarea").value = "";
    delete SillyTavern.getContext().chatMetadata.script_injects?.["色情主角"];
  }, qrSet);
  const input = () => page.evaluate(() => document.getElementById("send_textarea").value);
  const stored = () => page.evaluate(() => workbench.host.placeholders.vars());
  const popup = page.locator("dialog.popup[open]").last();
  const choose = async (label) => popup.getByText(label, { exact: true }).click();
  const prompt = page.getByRole("dialog", { name: "设置变量" });

  await page.evaluate(
    (menu) => void SillyTavern.getContext().executeSlashCommandsWithOptions(`/run ${menu}`),
    MENU,
  );
  await popup.waitFor();
  await page.waitForTimeout(400);
  await page.screenshot({ path: directory + "/buttons-toolbar.png" });
  const toolbar = await popup.evaluate((dialog) => ({
    box: !!dialog.querySelector(".scrollable-buttons-container.wb-buttons-toolbar"),
    tools: [...dialog.querySelectorAll(".wb-buttons-tool")].map((b) => b.textContent.trim()),
    sep: dialog.querySelector(".wb-buttons-sep")?.offsetHeight,
    send: dialog.querySelector(".popup-controls .wb-buttons-send")?.textContent.trim(),
    sticky: getComputedStyle(dialog.querySelector(".wb-buttons-tool")).position,
  }));
  assert.deepEqual(toolbar.tools.slice(0, 2), ["⬅️返回", "➕同时"]);
  assert.equal(toolbar.box, true);
  assert.equal(toolbar.sep, 1);
  assert.equal(toolbar.send, "▶️发送");
  assert.equal(toolbar.sticky, "sticky");
  pass(
    "a /buttons menu with a -------- label gets the sticky toolbar, a rule and 发送 beside the popup controls",
  );
  await choose("⚙️@角色指定");
  await prompt.waitFor({ timeout: 5000 });
  const fields = prompt.getByRole("textbox");
  assert.ok((await fields.count()) >= 2);
  assert.equal(await popup.isVisible(), true, "the native /buttons popup stays open under the dialog");
  await page.screenshot({ path: directory + "/prompt-over-buttons.png" });
  await fields.nth(0).fill("张三");
  await fields.nth(1).fill("李四");
  await prompt.getByRole("button", { name: "确认", exact: true }).click();
  await prompt.waitFor({ state: "hidden" });
  assert.equal(await input(), "<>");
  const vars = await stored();
  assert.equal(vars.男主, "张三");
  assert.equal(vars.女主, "李四");
  pass("the menu's -1 placeholders ask once over the /buttons popup, store the names and expand to nothing");

  await choose("🤝男女主汇合");
  await page.waitForFunction(
    () => document.getElementById("send_textarea").value.includes("张三和李四"),
    null,
    { timeout: 5000 },
  );
  assert.ok((await input()).startsWith("<><张三和李四"));
  pass("a later /setinput expands the stored names in the composer");

  await choose("👨切换主角-男主");
  await page.waitForFunction(() => SillyTavern.getContext().chatMetadata.script_injects?.["色情主角"], null, {
    timeout: 5000,
  });
  const injected = await page.evaluate(
    () => SillyTavern.getContext().chatMetadata.script_injects["色情主角"].value,
  );
  assert.ok(injected.includes("切换到张三的控制视角"), injected);
  pass("/inject expands placeholders before injecting");
  await page.keyboard.press("Escape");
  await popup.waitFor({ state: "hidden" });

  const before = await page.evaluate(() => SillyTavern.getContext().chat.length);
  await page.evaluate(() => {
    document.getElementById("send_textarea").value = "";
  });
  await page.locator(".wb-composer-md .cm-content").click();
  await page.keyboard.type("{@女主}好");
  await page.keyboard.press("Enter");
  await page.waitForFunction(() => document.getElementById("send_textarea").value === "李四好", null, {
    timeout: 3000,
  });
  assert.equal(
    await page.evaluate(() => SillyTavern.getContext().chat.length),
    before,
    "Enter expanded instead of sending",
  );
  await page.evaluate(() => {
    document.getElementById("send_textarea").value = "";
  });
  await page.keyboard.type("{@男主:无名}");
  await page.keyboard.press("Tab");
  await page.waitForFunction(() => document.getElementById("send_textarea").value === "张三", null, {
    timeout: 1000,
  });
  pass("Enter and Tab expand a typed placeholder at once; Enter does not send the raw text");
  await page.evaluate(() => {
    document.getElementById("send_textarea").value = "";
  });

  await page.evaluate(() => workbench.host.persistSettings());
  await ready(page, urls.validation);
  await page.waitForFunction(() => window.workbench?.mounted);
  await createCharacter(page);
  assert.equal((await stored()).女主, "李四");
  await page.evaluate(() => {
    const t = document.getElementById("send_textarea");
    t.value = "{@女主}在";
    t.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await page.waitForFunction(() => document.getElementById("send_textarea").value === "李四在", null, {
    timeout: 3000,
  });
  pass("variables survive a reload in the workbench settings and still expand");

  if ((await page.locator(".wb-edge-left").getAttribute("aria-expanded")) === "false")
    await page.locator(".wb-edge-left").click();
  await openSettings(page, "用户设置");
  await page
    .getByRole("navigation", { name: "设置分组" })
    .getByRole("button", { name: "占位符变量", exact: true })
    .click();
  const panel = page.getByRole("region", { name: "占位符变量" });
  await panel.waitFor();
  assert.equal(await panel.getByRole("textbox", { name: "变量 男主 的值" }).inputValue(), "张三");
  await panel.getByRole("textbox", { name: "变量 男主 的值" }).fill("王五");
  assert.equal((await stored()).男主, "王五");
  await panel.getByRole("button", { name: "删除 女主", exact: true }).click();
  assert.equal((await stored()).女主, undefined);
  await page.screenshot({ path: directory + "/settings-panel.png" });
  pass("the settings panel lists, edits and deletes the character's variables");
} finally {
  if (page)
    await page
      .evaluate(
        async ({ name, key }) => {
          const api = globalThis.quickReplyApi;
          api.removeGlobalSet(name);
          if (api.getSetByName(name)) await api.deleteSet(name);
          if (key) workbench.host.placeholders.setVars(key, {});
          const c = SillyTavern.getContext();
          if (c.chatMetadata.script_injects?.["色情主角"]) {
            delete c.chatMetadata.script_injects["色情主角"];
            await c.saveMetadata();
          }
          await workbench.host.persistSettings();
        },
        { name: qrSet.name, key: avatar },
      )
      .catch((error) => console.log("cleanup failed:", error.message));
  await browser.close();
}
console.log(`${checks.length} checks passed`);
