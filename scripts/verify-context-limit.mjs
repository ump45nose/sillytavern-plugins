// W4 context limit: the setting in 用户设置 › 外观与阅读 trims what a generation sends to the newest
// N chat messages (hidden floors not counted), marks the older floors in the list, and saves nothing else.
import assert from "node:assert/strict";
import { artifacts, connect, createCharacter, launch, openSettings, ready, session, urls } from "./browser.mjs";

const browser = await launch();
const { page } = await session(browser);
const check = (name) => console.log("PASS", name);
await ready(page, urls.validation, { probe: true });
const original = await page.evaluate(() => structuredClone(workbench.host.prefs().contextLimit));
try {
  await createCharacter(page);
  // Six floors, the third hidden: a generation sends at most five of them.
  // Run-unique markers (the floor preview drops "_", "*" and "#").
  const tag = "Fl" + Date.now().toString(36);
  await page.evaluate(async (tag) => {
    const c = SillyTavern.getContext();
    for (let i = 1; i <= 6; i++) {
      c.chat.push({ name: i % 2 ? c.name1 : c.name2, is_user: i % 2 === 1, is_system: i === 3, mes: `${tag}N${i}`, send_date: Date.now(), extra: {} });
      c.addOneMessage(c.chat.at(-1));
    }
    await c.saveChat();
    await c.reloadCurrentChat();
  }, tag);

  await openSettings(page, "用户设置");
  const group = page.getByRole("button", { name: "外观与阅读", exact: true });
  if (await group.count()) await group.first().click();
  await page.getByRole("switch", { name: "只发送最近的楼层", exact: true }).click();
  await page.getByLabel("发送条数", { exact: true }).fill("3");
  const setting = await page.evaluate(() => workbench.host.prefs().contextLimit);
  assert.deepEqual(setting, { enabled: true, limit: 3, quiet: false });
  check("the settings switch and count write the context limit");
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "返回工作台", exact: true }).click().catch(() => {});

  // Of the six new floors the third is hidden, so the last three sent are N4, N5, N6.
  const rows = await page.locator(".wb-floor-list .wb-nav-row").evaluateAll((nodes) =>
    nodes.map((n) => ({ text: n.textContent, unsent: n.classList.contains("is-unsent"), first: n.classList.contains("is-first-sent") })),
  );
  assert.equal(rows.find((r) => r.first)?.text.includes(tag + "N4"), true, JSON.stringify(rows));
  assert.ok(rows.filter((r) => !r.unsent).every((r) => new RegExp(tag + "N[456]").test(r.text)));
  check("the floor list dims the floors that are no longer sent");
  await page.screenshot({ path: artifacts + "/context-limit.png" });

  await connect(page);
  const request = page.waitForRequest((r) => r.url().includes("/api/backends/chat-completions/generate"));
  await page.evaluate(() => SillyTavern.getContext().generate("normal"));
  const messages = JSON.parse((await request).postData()).messages.map((m) => String(m.content)).join("\n");
  for (const i of [4, 5, 6]) assert.ok(messages.includes(tag + "N" + i), "sends N" + i);
  for (const i of [1, 2, 3]) assert.ok(!messages.includes(tag + "N" + i), "drops N" + i);
  await page.waitForFunction(() => !workbench.host.isGenerating());
  const after = await page.evaluate((tag) => SillyTavern.getContext().chat.filter((m) => m.mes?.startsWith(tag)).length, tag);
  assert.equal(after, 6, "the saved chat keeps every floor");
  check("a generation sends only the newest three floors and the chat keeps all of them");
} finally {
  await page.evaluate(async (value) => {
    workbench.host.preference({ contextLimit: value });
    await (await import("/script.js")).saveSettings();
  }, original ?? undefined);
  await browser.close();
}
