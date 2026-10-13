import assert from "node:assert/strict";
import fs from "node:fs";
import { launch, session, ready, urls, createCharacter, connect, withReducedMotion } from "./browser.mjs";

const dir = "artifacts/rp-runtime"; fs.mkdirSync(dir, { recursive: true });
const checks = [], pass = (name, details = {}) => { checks.push({ name, details }); console.log("PASS", name); };
const browser = await launch();
let page, original;
try {
  ({ page } = await session(browser));
  const errors = [], expectedNativeErrors = []; let stopping = false;
  page.on("pageerror", error => {
    if (stopping && error.message === "Generation was aborted.") expectedNativeErrors.push(error.message);
    else errors.push(error.message);
  });
  await ready(page, urls.validation, { probe: true });
  original = await page.evaluate(() => structuredClone(SillyTavern.getContext().extensionSettings.workbench));
  await page.evaluate(async () => { workbench.unmount(); SillyTavern.getContext().extensionSettings.workbench.layout = "novel"; await workbench.mount(); });
  await createCharacter(page); await page.evaluate(() => workbench.host.newChat()); await connect(page);
  await page.setViewportSize({ width: 1496, height: 817 });
  await page.evaluate(() => { window.__rpNative = { chat: document.getElementById("chat"), input: document.getElementById("send_textarea"), form: document.getElementById("send_form"), background: document.getElementById("bg1") }; });
  const settle = () => page.waitForTimeout(350), css = (selector, key) => page.locator(selector).first().evaluate((n, key) => getComputedStyle(n)[key], key);
  const has = c => page.evaluate(c => document.body.classList.contains(c), c);
  const role = name => page.getByRole("button", { name, exact: true });
  await role("切换工作台").click(); await page.getByRole("menuitemradio", {name:/RP/}).click(); await settle();
  assert.equal(await has("wb-rp"), true); assert.equal(await has("wb-left-open"), false); assert.equal(await has("wb-right-open"), false);
  assert.equal(await page.evaluate(() => __rpNative.chat === document.getElementById("chat") && __rpNative.input === document.getElementById("send_textarea") && __rpNative.form === document.getElementById("send_form")), true);
  pass("RP opens with both panels closed and the original native chat, form and input");
  assert.equal(await page.evaluate(() => __rpNative.background === document.getElementById("bg1") && getComputedStyle(__rpNative.background).opacity === "1"), true);
  await page.waitForFunction(() => [...document.querySelectorAll(".wb-rp-stage img")].every(n => n.complete && n.naturalWidth > 0));
  const expression = page.locator("#expression-holder img.expression");
  const originalExpression = await expression.getAttribute("src");
  const portrait = await page.evaluate(() => workbench.host.rpPresentation().portrait);
  await expression.evaluate((n, src) => n.setAttribute("src", src), portrait);
  await page.waitForFunction(src => document.querySelector(".wb-rp-actor.is-sprite img")?.getAttribute("src") === src, portrait);
  await expression.evaluate((n, src) => src === null ? n.removeAttribute("src") : n.setAttribute("src", src), originalExpression);
  await page.waitForFunction(() => !document.querySelector(".wb-rp-actor.is-sprite"));
  pass("native background is retained and live expression image updates reach the stage");

  const eye = await role("隐藏界面").boundingBox(); await role("隐藏界面").click(); await settle();
  assert.deepEqual(await role("显示界面").boundingBox(), eye); assert.equal(await page.locator("#sheld").evaluate(n => n.inert), true);
  await role("显示界面").click(); await settle(); assert.equal(await page.locator("#sheld").evaluate(n => n.inert), false);
  pass("same eye control hides and restores the interface, including focus isolation");
  await role("展开左边栏").click(); await page.waitForTimeout(65); const mid = Number(await css(".wb-left", "opacity")); assert(mid > 0 && mid < 1); await settle();
  assert.equal(await page.locator(".wb-left-bottom button").count(), 9); await role("收纳左边栏").click(); await settle();
  pass("existing navigation and panel entry/exit animation remain available", { mid });

  await role("世界书详情").click(); await settle(); await page.locator(".wb-world").waitFor();
  assert.equal(await page.locator("#wb-resource-rail").evaluate(n => n.getBoundingClientRect().width), 180);
  await role("关闭右栏").click(); await settle();
  await role("预设详情").click(); await settle(); await page.locator(".wb-resource-v3").waitFor(); await role("关闭右栏").click(); await settle();
  pass("existing world and preset editors reused with the 180px resource rail");

  await role("固定顶栏").click(); await page.mouse.move(750, 400); await settle();
  assert.equal(await has("wb-rp-top-collapsed"), true); await page.mouse.move(740, 4); await settle(); assert.equal(await has("wb-rp-top-collapsed"), false);
  await page.mouse.move(740, 400); await settle(); assert.equal(await has("wb-rp-top-collapsed"), true);
  await role("显示顶栏").focus(); await role("显示顶栏").press("Enter"); await settle(); assert.equal(await has("wb-rp-top-collapsed"), false);
  await role("固定顶栏").click(); await page.mouse.move(700, 400); await settle();
  pass("top bar hover and keyboard reveal work while its auto-hide preference persists");

  await role("输入回应").click(); await settle(); const input = page.locator("#send_textarea"), draft = "WB_RP_DRAFT **MD**\n<story>{{char}}</story>";
  await input.fill(draft); const before = (await page.locator("#sheld").boundingBox()).height;
  await role("展开 RP 输入区").click(); await page.waitForTimeout(70); const halfway = (await page.locator("#sheld").boundingBox()).height;
  await settle(); const after = (await page.locator("#sheld").boundingBox()).height;
  assert(halfway > before && halfway < after, JSON.stringify({ before, halfway, after })); assert.equal(await input.inputValue(), draft);
  await role("还原 RP 输入区").click(); await settle(); await role("上一段对白").click(); await settle(); await role("输入回应").click(); await settle(); assert.equal(await input.inputValue(), draft);
  pass("input expansion interpolates and flipping back preserves the native raw draft", { before, halfway, after });
  await role("RP 外观").click(); await page.getByRole("slider", { name: "RP 对白宽度", exact: true }).press("End");
  assert.equal(await page.evaluate(() => workbench.host.prefs().rpDialogWidth), 94); await page.keyboard.press("Escape"); await settle();
  pass("RP appearance controls update real persisted layout preferences");

  await page.evaluate(async () => {
    await TavernHelper.createChatMessages([{ role: "assistant", message: "WB_RP_FIRST\n\n" + "第一段对白，保留原有 Markdown 和宏处理。".repeat(20) + "\n\n" + "第二段对白。".repeat(40) + "\n\nWB_RP_LAST" }]);
  });
  await page.waitForFunction(() => document.querySelector("#chat .wb-rp-current .mes_text")?.textContent.includes("WB_RP_LAST")); await settle();
  const id = await page.locator(".wb-rp-current").getAttribute("mesid");
  assert.equal(await role("对白第 1 段").getAttribute("aria-current"), "true");
  await page.locator("#chat .wb-rp-current").evaluate(n => { window.__rpMessage = n; window.__rpParent = n.parentElement; window.__rpText = n.querySelector(".mes_text"); window.__rpChildren = [...__rpText.childNodes]; });
  await role("对白第 2 段").click(); await settle();
  await role("对白第 1 段").click(); await page.waitForTimeout(65);
  assert(await page.locator("#chat .wb-rp-current .mes_text").evaluate(n => n.getAnimations().some(a => a.playState === "running"))); await settle();
  assert.equal(await page.evaluate(() => __rpMessage === document.querySelector(".wb-rp-current") && __rpParent === __rpMessage.parentElement && __rpText === __rpMessage.querySelector(".mes_text") && __rpChildren.every((n, i) => n === __rpText.childNodes[i])), true);
  assert.equal(await page.locator(".wb-rp-page-dots button:not(.wb-icon)").count() >= 3, true);
  pass("real formatted messages paginate with visible motion and no DOM reparenting", { id });
  await role("对白第 2 段").click(); await settle();
  assert(await page.locator("#chat").evaluate(n => n.scrollHeight > n.clientHeight));
  await role("下一段对白或输入").click(); await settle();
  assert(await page.locator("#chat").evaluate(n => n.scrollTop > 0));
  assert.equal(await page.locator(".wb-rp-current").getAttribute("mesid"), id);
  pass("continue reads an overflowing native paragraph before advancing to another page");
  await role("编辑当前对白").click(); const editor = page.locator(".wb-rp-current .edit_textarea"); await editor.waitFor();
  assert.match(await editor.inputValue(), /WB_RP_FIRST/); await editor.fill("WB_RP_EDIT **native Markdown**"); await role("保存对白编辑").click(); await editor.waitFor({ state: "detached" });
  assert.equal(await page.evaluate(() => SillyTavern.getContext().chat.at(-1).mes), "WB_RP_EDIT **native Markdown**");
  pass("edit and save use native message controls and preserve raw Markdown");

  await role("输入回应").click(); await settle();
  await page.evaluate(async () => { await TavernHelper.createChatMessages([{ role: "user", message: '```html\n<!doctype html><html><body><button id="rp-frame-button" onclick="document.body.dataset.count=String(Number(document.body.dataset.count||0)+1)">RP iframe</button></body></html>\n```' }]); });
  await page.waitForFunction(() => document.querySelector(".wb-rp-current iframe"));
  await page.evaluate(() => { window.__rpFrame = document.querySelector(".wb-rp-current iframe"); window.__rpFrameParent = __rpFrame.parentNode; });
  let frame;
  for (let i = 0; i < 40 && !frame; i++) { for (const f of page.frames()) if (await f.locator("#rp-frame-button").count()) frame = f; if (!frame) await page.waitForTimeout(100); }
  assert(frame); await frame.locator("#rp-frame-button").click();
  await role("输入回应").click(); await settle(); await role("上一段对白").click(); await settle();
  assert.equal(await page.evaluate(() => __rpFrame === document.querySelector(".wb-rp-current iframe") && __rpFrameParent === __rpFrame.parentNode), true);
  await frame.locator("#rp-frame-button").click(); assert.equal(await frame.locator("body").getAttribute("data-count"), "2");
  await role("查看对话记录").click(); await settle(); assert.equal(await has("wb-rp-history"), true); assert(await page.locator("#chat .mes").count() >= 3);
  await role("返回 RP 对白").click(); await settle(); assert.equal(await page.evaluate(() => __rpFrame.isConnected), true);
  pass("Tavern Helper iframe identity and interactive state survive input and history transitions");

  await role("输入回应").click(); await settle(); await input.fill("WB_RP_SEND 原生发送验证"); await page.locator("#send_but").click();
  await page.waitForFunction(() => SillyTavern.getContext().chat.at(-1)?.mes.includes("工作台验证回复") && !workbench.host.snapshot().busy); await settle();
  assert.equal(await page.evaluate(() => SillyTavern.getContext().chat.at(-2).mes), "WB_RP_SEND 原生发送验证");
  assert.equal(await input.inputValue(), ""); assert.equal(await has("wb-rp-compose"), false);
  pass("native send and streamed model reply return the stage to the live speaker");
  await role("输入回应").click(); await settle(); await input.fill("WB_SLOW WB_RP_STOP"); await page.locator("#send_but").click();
  await role("停止生成").waitFor(); stopping = true; await role("停止生成").click(); await page.waitForFunction(() => !workbench.host.snapshot().busy); await settle(); stopping = false;
  pass("generation can be stopped from the RP dialogue controls");

  for (const [width, height] of [[1366,768],[1440,900],[1496,817],[1920,1080],[2992,1634],[1100,800],[1024,768]]) {
    await page.setViewportSize({ width, height }); await settle();
    const metrics = await page.evaluate(() => { const rect = s => document.querySelector(s).getBoundingClientRect().toJSON(); return { width: innerWidth, overflow: document.documentElement.scrollWidth > innerWidth, dialog: rect("#sheld"), eye: rect(".wb-rp-visibility"), selectors: rect(".wb-contexts"), actions: rect(".wb-top-right") }; });
    assert.equal(metrics.overflow, false); assert(metrics.dialog.left >= 0 && metrics.dialog.right <= width + 1 && metrics.dialog.bottom <= height + 1, JSON.stringify(metrics));
    assert(metrics.selectors.right <= metrics.actions.left + 1, JSON.stringify(metrics));
    await role("世界书详情").click(); await settle(); if (width <= 1100) assert.equal(await page.locator("#sheld").evaluate(n => n.inert), true);
    await role("关闭右栏").click(); await settle(); pass(`viewport ${width}×${height}`, metrics);
  }
  await page.setViewportSize({ width:1496, height:817 }); await settle();
  await role("展开左边栏").click(); await settle(); await page.locator(".wb-floor-list > button").first().click(); await settle();
  assert.equal(await page.locator(".wb-rp-current").getAttribute("mesid"), await page.locator(".wb-floor-list > button").first().evaluate(n => Number(n.querySelector(".wb-floor-number").textContent) - 1).then(String));
  await role("收纳左边栏").click(); await settle(); pass("existing floor navigation selects the corresponding RP message");
  await role("展开左边栏").click(); await role("世界书详情").click(); await settle();
  const compact = await page.evaluate(() => {
    const header = document.querySelector(".wb-rp-deck-header").getBoundingClientRect(), speaker = document.querySelector(".wb-rp-speaker").getBoundingClientRect(), actions = document.querySelector(".wb-rp-deck-actions").getBoundingClientRect();
    return { header: header.toJSON(), speaker: speaker.toJSON(), actions: actions.toJSON() };
  });
  assert(compact.speaker.right < compact.actions.left && compact.actions.right <= compact.header.right + 1, JSON.stringify(compact));
  await role("关闭右栏").click(); await role("收纳左边栏").click(); await settle();
  pass("both panels can open together without dialogue controls overlapping the speaker", compact);
  await withReducedMotion(page, async () => assert.equal(await css("#sheld", "transitionDuration"), "0s")); pass("reduced motion is honored and the account preference restored");
  await role("切换阅读布局").click(); await settle(); assert.equal(await has("wb-rp"), false); assert.equal(await page.locator(".wb-reading-bar").count(), 1);
  assert.equal(await page.evaluate(() => __rpNative.chat === document.getElementById("chat") && __rpNative.input === document.getElementById("send_textarea") && !document.querySelector(".wb-rp-part")), true);
  for (const [width, height] of [[1024,768],[1366,768],[1496,817],[1920,1080]]) {
    await page.setViewportSize({ width, height }); await settle();
    const reading = await page.evaluate(() => {
      const rect = s => document.querySelector(s).getBoundingClientRect().toJSON();
      return { width:innerWidth, contexts:rect(".wb-contexts"), actions:rect(".wb-top-right"), form:rect("#send_form"), send:rect("#send_but"), tools:rect(".wb-composer-actions"), grip:rect(".wb-input-grip") };
    });
    assert(Math.abs(reading.contexts.x + reading.contexts.width / 2 - width / 2) < 1, JSON.stringify(reading));
    assert(reading.contexts.right <= reading.actions.left + 1 && reading.send.right <= reading.form.right && reading.tools.right <= reading.send.left && reading.grip.y - reading.form.y < 5, JSON.stringify(reading));
  }
  pass("reading mode keeps its centered header, native input grip and icon controls at four desktop sizes");
  await page.setViewportSize({ width:1496, height:817 });
  await role("切换工作台").click(); await page.getByRole("menuitemradio", {name:/RP/}).click(); await settle(); await page.evaluate(async () => { workbench.unmount(); await workbench.mount(); }); await settle();
  assert.equal(await has("wb-rp"), true); assert.equal(await has("wb-left-open"), false); assert.equal(await has("wb-right-open"), false);
  await page.evaluate(() => workbench.unmount()); assert.equal(await page.evaluate(() => !document.body.classList.contains("wb-rp") && !document.querySelector(".wb-rp-stage,.wb-rp-part") && !document.getElementById("sheld").inert && __rpNative.input.isConnected), true);
  pass("reading/RP switching, RP remount defaults and native fallback clean up all presentation state");
  await page.evaluate(async () => { await workbench.mount(); await workbench.host.persistSettings(); }); await page.reload();
  await page.waitForFunction(() => document.body.classList.contains("wb-rp")); await settle();
  assert.equal(await has("wb-left-open"), false); assert.equal(await has("wb-right-open"), false); assert.equal(await page.evaluate(() => workbench.host.prefs().rpDialogWidth), 94);
  pass("RP mode and appearance persist after a real reload while both panels start closed");
  assert.deepEqual(errors, []);
  fs.writeFileSync(`${dir}/verification.json`, JSON.stringify({ checkedAt:new Date().toISOString(), passed:true, url:urls.validation, checks, errors, expectedNativeErrors }, null, 2));
} finally {
  if (page && original) await page.evaluate(async original => { document.querySelector("#mes_stop")?.click(); workbench.unmount(); SillyTavern.getContext().extensionSettings.workbench = original; await (await import("/script.js")).saveSettings(); await workbench.mount(); }, original).catch(() => {});
  await browser.close();
}
