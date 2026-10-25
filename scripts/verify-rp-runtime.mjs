import assert from "node:assert/strict";
import fs from "node:fs";
import { launch, session, ready, urls, createCharacter, connect, withReducedMotion, openResource, chooseLayout, seedCast, selectPaper } from "./browser.mjs";

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
  await page.evaluate(async () => { workbench.unmount(); const settings = SillyTavern.getContext().extensionSettings.workbench; settings.layout = "novel"; settings.rpTopAuto = false; await workbench.mount(); });
  await createCharacter(page); await page.evaluate(() => workbench.host.newChat()); await connect(page);
  await page.setViewportSize({ width: 1496, height: 817 });
  await page.evaluate(() => { window.__rpNative = { chat: document.getElementById("chat"), input: document.getElementById("send_textarea"), form: document.getElementById("send_form"), background: document.getElementById("bg1") }; });
  const settle = () => page.waitForTimeout(350), css = (selector, key) => page.locator(selector).first().evaluate((n, key) => getComputedStyle(n)[key], key);
  const has = c => page.evaluate(c => document.body.classList.contains(c), c);
  const flag = c => page.evaluate(c => document.body.hasAttribute("data-" + c), c);
  const role = name => page.getByRole("button", { name, exact: true });
  await chooseLayout(page,'RP'); await settle();
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
  assert.equal(await page.locator(".wb-nav-footer button").count(), 3); await role("收纳左边栏").click(); await settle();
  pass("existing navigation and panel entry/exit animation remain available", { mid });

  await openResource(page,'世界书详情'); await settle(); await page.locator(".wb-world-panel").waitFor();
  assert.equal(await page.locator("#wb-resource-rail").evaluate(n => n.getBoundingClientRect().width), 180);
  await role("关闭右栏").click(); await settle();
  await openResource(page,'预设详情'); await settle(); await page.locator(".wb-resource-v3").waitFor(); await role("关闭右栏").click(); await settle();
  pass("existing world and preset editors reused with the 180px resource rail");

  await role("固定顶栏").click(); await page.mouse.move(750, 400); await settle();
  assert.equal(await has("wb-rp-top-collapsed"), true); await page.mouse.move(740, 4); await settle(); assert.equal(await has("wb-rp-top-collapsed"), false);
  await page.mouse.move(740, 400); await settle(); assert.equal(await has("wb-rp-top-collapsed"), true);
  await role("显示顶栏").focus(); await role("显示顶栏").press("Enter"); await settle(); assert.equal(await has("wb-rp-top-collapsed"), false);
  await role("固定顶栏").click(); await page.mouse.move(700, 400); await settle();
  pass("top bar hover and keyboard reveal work while its auto-hide preference persists");

  const input = page.locator("#send_textarea"), draft = "WB_RP_DRAFT **MD**\n<story>{{char}}</story>";
  assert.equal(await role("展开 RP 输入区").count(), 0); await role("快进到你的回应").click(); await settle(); assert.equal(await flag("wb-rp-compose"), true);
  // The input has focus: the native textarea, or the Markdown editor laid over it.
  assert.equal(await page.evaluate(() => document.activeElement === document.getElementById("send_textarea") || !!document.activeElement?.closest(".wb-composer-md")), true);
  await input.fill(draft); const before = (await page.locator("#sheld").boundingBox()).height;
  await role("展开 RP 输入区").click(); await page.waitForTimeout(70); const halfway = (await page.locator("#sheld").boundingBox()).height;
  await settle(); const after = (await page.locator("#sheld").boundingBox()).height;
  assert(halfway > before && halfway < after, JSON.stringify({ before, halfway, after })); assert.equal(await input.inputValue(), draft);
  await role("还原 RP 输入区").click(); await settle(); await role("返回对白").click(); await settle(); assert.equal(await flag("wb-rp-compose"), false); assert.equal(await input.inputValue(), draft);
  assert.equal(await page.locator("#form_sheld").evaluate(n => n.getBoundingClientRect().height === 0 || getComputedStyle(n).display === "none" || getComputedStyle(n).visibility === "hidden"), true);
  pass("reading hides the input; the reply key enters it focused, expansion interpolates and returning preserves the native raw draft", { before, halfway, after });
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
  assert(await page.locator("#chat .wb-rp-current .mes_block").evaluate(n => n.getAnimations().some(a => a.playState === "running"))); await settle();
  assert.equal(await page.evaluate(() => __rpMessage === document.querySelector(".wb-rp-current") && __rpParent === __rpMessage.parentElement && __rpText === __rpMessage.querySelector(".mes_text") && __rpChildren.every((n, i) => n === __rpText.childNodes[i])), true);
  assert.equal(await page.locator(".wb-rp-dots button").count() >= 3, true);
  pass("real formatted messages paginate with visible motion and no DOM reparenting", { id });
  const block = page.locator("#chat .wb-rp-current .mes_block"), pages = await page.locator(".wb-rp-dots button").count();
  const unscrolled = () => page.evaluate(() => { const chat = document.getElementById("chat"), b = document.querySelector(".wb-rp-current .mes_block"); return chat.scrollHeight <= chat.clientHeight + 1 && b.scrollHeight <= b.clientHeight + 1 && getComputedStyle(b).overflowY === "hidden"; });
  assert.equal(await unscrolled(), true); assert.equal(await block.evaluate(n => n.scrollLeft), 0);
  await role("下一段对白或输入").click(); await settle();
  const step = await block.evaluate(n => ({ left: n.scrollLeft, width: n.clientWidth }));
  assert.equal(step.left, step.width + 48, JSON.stringify(step)); assert.equal(await role("对白第 2 段").getAttribute("aria-current"), "true");
  assert.equal(await page.locator(".wb-rp-current").getAttribute("mesid"), id); assert.equal(await unscrolled(), true);
  await page.keyboard.press("ArrowLeft"); await settle(); assert.equal(await block.evaluate(n => n.scrollLeft), 0);
  const over = await page.locator("#chat .wb-rp-current .mes_text").boundingBox(); await page.mouse.move(over.x + 40, over.y + 20);
  await page.mouse.wheel(0, 120); await settle(); assert.equal(await role("对白第 2 段").getAttribute("aria-current"), "true");
  await page.mouse.wheel(0, -120); await settle(); assert.equal(await role("对白第 1 段").getAttribute("aria-current"), "true"); assert.equal(await page.evaluate(() => scrollY), 0);
  await page.locator("#chat .wb-rp-current .mes_text").click({ position: { x: 40, y: 20 } }); await settle(); assert.equal(await role("对白第 2 段").getAttribute("aria-current"), "true");
  await role(`对白第 ${pages} 段`).click(); await settle(); await role("下一段对白或输入").click(); await settle();
  assert.equal(await flag("wb-rp-compose"), true);
  // Composing, the wheel scrolls a long draft first; a fresh turn back at its top returns to the dialogue.
  // What scrolls is the Markdown editor over the input when it is on, else the textarea itself.
  const draftBox = page.locator("#send_textarea[data-wb-md] + .wb-composer-md .cm-scroller, #send_textarea:not([data-wb-md])");
  const kept = await input.inputValue(); await input.fill("WB_RP_WHEEL\n".repeat(120)); await draftBox.evaluate(n => { n.scrollTop = n.scrollHeight; });
  const field = await input.boundingBox(); await page.mouse.move(field.x + 60, field.y + 40);
  await page.mouse.wheel(0, -120); await settle(); assert.equal(await flag("wb-rp-compose"), true);
  assert(await draftBox.evaluate(n => n.scrollTop < n.scrollHeight - n.clientHeight - 1));
  await input.fill(kept); await draftBox.evaluate(n => { n.scrollTop = 0; }); await page.waitForTimeout(400);
  await page.mouse.wheel(0, -120); await settle(); assert.equal(await flag("wb-rp-compose"), false);
  assert.equal(await role(`对白第 ${pages} 段`).getAttribute("aria-current"), "true");
  pass("long messages page by lines without scrollbars; keys, the wheel, clicks and dots turn pages, the last page continues into input and the wheel turns back out of it", { pages, step });
  await role("编辑当前对白").click(); const editor = page.locator(".wb-rp-current .edit_textarea"); await editor.waitFor();
  assert.match(await editor.inputValue(), /WB_RP_FIRST/);
  // The wheel over the field scrolls the draft; it never turns the page out of editing.
  await editor.fill("WB_RP_EDIT_LONG\n\n".repeat(80)); await editor.hover(); await page.mouse.wheel(0, 300); await settle();
  assert((await editor.evaluate(n => n.scrollTop)) > 0); assert.equal(await editor.isVisible(), true);
  assert.equal(await page.evaluate(() => { const t = document.querySelector(".wb-rp-current .edit_textarea").getBoundingClientRect(), c = document.getElementById("chat").getBoundingClientRect(); return document.body.hasAttribute("data-wb-rp-editing") && t.left < c.left && t.right > c.right; }), true);
  await editor.fill("WB_RP_EDIT **native Markdown**"); await role("保存对白编辑").click(); await editor.waitFor({ state: "detached" });
  assert.equal(await page.evaluate(() => SillyTavern.getContext().chat.at(-1).mes), "WB_RP_EDIT **native Markdown**");
  pass("editing fills the column with one field the wheel scrolls; save uses native controls and preserves raw Markdown");

  await page.evaluate(async () => { await TavernHelper.createChatMessages([{ role: "user", message: '```html\n<!doctype html><html><body><button id="rp-frame-button" onclick="document.body.dataset.count=String(Number(document.body.dataset.count||0)+1)">RP iframe</button></body></html>\n```' }]); });
  await page.waitForFunction(() => document.querySelector(".wb-rp-current iframe"));
  await page.evaluate(() => { window.__rpFrame = document.querySelector(".wb-rp-current iframe"); window.__rpFrameParent = __rpFrame.parentNode; });
  let frame;
  for (let i = 0; i < 40 && !frame; i++) { for (const f of page.frames()) if (await f.locator("#rp-frame-button").count()) frame = f; if (!frame) await page.waitForTimeout(100); }
  assert(frame); await frame.locator("#rp-frame-button").click();
  await role("快进到你的回应").click(); await settle(); await role("展开 RP 输入区").click(); await settle(); await role("还原 RP 输入区").click(); await role("返回对白").click(); await settle();
  assert.equal(await page.evaluate(() => __rpFrame === document.querySelector(".wb-rp-current iframe") && __rpFrameParent === __rpFrame.parentNode), true);
  await frame.locator("#rp-frame-button").click(); assert.equal(await frame.locator("body").getAttribute("data-count"), "2");
  await role("查看对话记录").click(); await settle(); assert.equal(await flag("wb-rp-history"), true); assert(await page.locator("#chat .mes").count() >= 3);
  // The log scrolls natively: the paging wheel stands aside.
  assert.equal(await page.locator("#chat").evaluate(n => { const e = new WheelEvent("wheel", { deltaY: -120, bubbles: true, cancelable: true }); n.dispatchEvent(e); return e.defaultPrevented; }), false);
  await role("返回 RP 对白").click(); await settle(); assert.equal(await page.evaluate(() => __rpFrame.isConnected), true);
  pass("Tavern Helper iframe identity and interactive state survive input and history transitions");

  await role("快进到你的回应").click(); await settle(); await input.fill("WB_RP_SEND 原生发送验证"); await page.locator("#send_but").click();
  await page.waitForFunction(() => SillyTavern.getContext().chat.at(-1)?.mes.includes("工作台验证回复") && !workbench.host.snapshot().busy); await settle();
  assert.equal(await page.evaluate(() => SillyTavern.getContext().chat.at(-2).mes), "WB_RP_SEND 原生发送验证");
  assert.equal(await input.inputValue(), ""); assert.equal(await flag("wb-rp-compose"), false);
  pass("native send and streamed model reply return the stage to the live speaker");
  await role("快进到你的回应").click(); await settle(); await input.fill("WB_SLOW WB_RP_STOP"); await page.locator("#send_but").click();
  await role("停止生成").waitFor(); stopping = true; await role("停止生成").click(); await page.waitForFunction(() => !workbench.host.snapshot().busy); await settle(); stopping = false;
  pass("generation can be stopped from the RP dialogue controls");

  for (const [width, height] of [[1366,768],[1440,900],[1496,817],[1920,1080],[2992,1634],[1100,800],[1024,768]]) {
    await page.setViewportSize({ width, height }); await settle();
    const metrics = await page.evaluate(() => { const rect = s => document.querySelector(s).getBoundingClientRect().toJSON(); return { width: innerWidth, overflow: document.documentElement.scrollWidth > innerWidth, dialog: rect("#sheld"), eye: rect(".wb-rp-visibility"), selectors: rect(".wb-top-pills"), actions: rect(".wb-top-tools") }; });
    assert.equal(metrics.overflow, false); assert(metrics.dialog.left >= 0 && metrics.dialog.right <= width + 1 && metrics.dialog.bottom <= height + 1, JSON.stringify(metrics));
    assert(metrics.selectors.right <= metrics.actions.left + 1, JSON.stringify(metrics));
    await openResource(page,'世界书详情'); await settle(); if (width <= 1100) assert.equal(await page.locator("#sheld").evaluate(n => n.inert), true);
    await role("关闭右栏").click(); await settle(); pass(`viewport ${width}×${height}`, metrics);
  }
  await page.setViewportSize({ width:1496, height:817 }); await settle();
  await role("展开左边栏").click(); await settle(); await page.locator(".wb-floor-list .wb-nav-row").first().click(); await settle();
  assert.equal(await page.locator(".wb-rp-current").getAttribute("mesid"), await page.locator(".wb-floor-list .wb-nav-row").first().evaluate(n => Number(n.querySelector(".wb-floor-number").textContent) - 1).then(String));
  await role("收纳左边栏").click(); await settle(); pass("existing floor navigation selects the corresponding RP message");
  await role("展开左边栏").click(); await openResource(page,'世界书详情'); await settle();
  const compact = await page.evaluate(() => {
    const r = s => document.querySelector(s).getBoundingClientRect().toJSON();
    const left = r(".wb-left"), right = r(".wb-right"), hit = (box) => document.elementFromPoint(box.left + box.width / 2, box.bottom - 40);
    return { width: innerWidth, band: r("#sheld"), leftOnTop: !!hit(left)?.closest(".wb-left"), rightOnTop: !!hit(right)?.closest(".wb-right"), plate: r(".wb-rp-plate"), tools: r(".wb-rp-tools"), dots: r(".wb-rp-dots"), reply: r(".wb-rp-reply"), foot: r(".wb-rp-foot"), text: r("#chat") };
  });
  // The panels lie over the stage: the band keeps the whole window and both cards sit above it.
  assert(compact.band.left <= 1 && compact.band.right >= compact.width - 1 && compact.leftOnTop && compact.rightOnTop && compact.plate.bottom <= compact.text.top + 1 && compact.foot.top >= compact.text.bottom - 1 && compact.tools.top >= compact.foot.top - 1 && compact.tools.left >= compact.dots.right && compact.reply.left >= compact.tools.right, JSON.stringify(compact));
  await role("关闭右栏").click(); await role("收纳左边栏").click(); await settle();
  pass("both panels open together over a stage that keeps the whole window; dialogue controls stay in order", compact);
  // A world book's cast: entries with images in characters/<book>/<entry>/, tagged lines, two places on stage.
  await seedCast(page);
  const say = async mes => {
    await page.evaluate(mes => { const c = SillyTavern.getContext(), msg = { name:c.name2, is_user:false, is_system:false, send_date:Date.now(), mes, extra:{} }; c.chat.push(msg); c.addOneMessage(msg); }, mes);
    await settle(); if (await role("快进到最新对白").isEnabled()) await role("快进到最新对白").click();
    await settle(); await role("对白第 1 段").click(); await settle();
  };
  // Who stands where depends on who came first; each keeps its place, so only voice and face are compared.
  const figures = () => page.evaluate(() => {
    const all = [...document.querySelectorAll(".wb-rp-actor")];
    if (all.length === 2 && all[0].classList.contains("is-right") === all[1].classList.contains("is-right")) throw new Error("two figures share a place");
    return all.map(n => decodeURIComponent(n.querySelector("img").getAttribute("src")).split("?")[0].split("/").slice(-2).join("/") + (n.classList.contains("is-speaking") ? " speaking" : " listening")).sort();
  });
  const prose = Array.from({ length:7 }, () => "风从山谷里吹上来，带着松针和雨后泥土的气味，远处的钟声一下一下地敲着。").join("");
  await say(["张三|joy:「今天风大，我们上山看看吧。」", "李四|anger:「别去！山上要塌方了。」", prose, prose].join("\n")); await settle();
  assert.deepEqual(await figures(), ["张三/joy.webp speaking", "李四/anger.webp listening"]);
  assert.equal(await page.locator(".wb-rp-plate strong").textContent(), "张三"); assert.equal(await page.locator(".wb-rp-user").count(), 0, "two of the cast fill both places");
  const shown = await page.locator(".mes.wb-rp-current .mes_text").evaluate(n => ({ text:n.innerText, labels:[...n.querySelectorAll("[data-wb-speaker]")].map(t => t.getBoundingClientRect().width < 1 ? "hidden" : t.textContent) }));
  assert(!shown.text.includes("|joy") && !shown.text.includes("|anger"), shown.text); assert.deepEqual(shown.labels, ["hidden", "李四"], "the plate names the page's first voice; a later one carries its own label");
  // The tags are marked by SillyTavern's own formatter hook, after its tag encoding, so that setting changes nothing.
  assert.equal(await page.evaluate(() => {
    const c = SillyTavern.getContext(), id = c.chat.length - 1, encode = c.powerUserSettings.encode_tags;
    c.powerUserSettings.encode_tags = true; c.updateMessageBlock(id, c.chat[id]);
    const count = document.querySelectorAll(`.mes[mesid="${id}"] .mes_text [data-wb-speaker]`).length;
    c.powerUserSettings.encode_tags = encode; c.updateMessageBlock(id, c.chat[id]); return count;
  }), 2, "tags are marked with SillyTavern's tag encoding on");
  assert.match(await page.evaluate(() => SillyTavern.getContext().extensionPrompts.noval_cast.value), /张三（joy、neutral）；李四（anger）/);
  await role("下一段对白或输入").click(); await settle();
  assert.deepEqual(await figures(), ["张三/joy.webp listening", "李四/anger.webp speaking"], "an untagged page continues the last voice before it");
  await say("三哥笑道「好，听你的。」"); await settle();
  assert.deepEqual(await figures(), ["张三/neutral.webp speaking", "李四/anger.webp listening"], "an untagged reply goes by its names; with no classifier, the neutral face");
  pass("a world-book cast tags each line: speaker and face per page, two places, names kept, prompt injected");
  // Unmounted, the workbench marks nothing and what it marked still reads; mounted again, replies already
  // on screen are rendered once more with their tags marked.
  const unmounted = await page.evaluate(async () => {
    const c = SillyTavern.getContext(), before = c.chat.length - 2;
    workbench.unmount();
    const msg = { name:c.name2, is_user:false, is_system:false, send_date:Date.now(), mes:"李四|anger:「谁在那儿？」", extra:{} };
    c.chat.push(msg); c.addOneMessage(msg);
    const text = id => document.querySelector(`.mes[mesid="${id}"] .mes_text`).textContent;
    const result = { kept: text(before), raw: text(c.chat.length - 1) };
    await workbench.mount();
    result.marked = [...document.querySelectorAll(`.mes[mesid="${c.chat.length - 1}"] [data-wb-speaker]`)].map(n => n.dataset.wbSpeaker + "|" + n.dataset.wbExpr);
    await c.deleteLastMessage();
    return result;
  });
  await settle();
  assert(unmounted.kept.startsWith("张三「今天风大") && unmounted.kept.includes("李四「别去") && !unmounted.kept.includes("|joy"), JSON.stringify(unmounted));
  assert(unmounted.raw.includes("李四|anger"), JSON.stringify(unmounted)); assert.deepEqual(unmounted.marked, ["李四|anger"], JSON.stringify(unmounted));
  pass("cast tags come from SillyTavern's formatter hook: idle while unmounted, names still readable, on-screen replies marked on mount");
  await role("RP 外观").click(); await page.locator(".wb-cast-open").click(); await page.locator(".wb-cast-list").waitFor();
  assert.deepEqual(await page.locator(".wb-cast-entry input").evaluateAll(ns => ns.map(n => [n.checked, n.disabled])), [[true,false],[true,false],[false,true]]);
  assert.deepEqual(await page.locator(".wb-cast-count").allTextContents(), ["2 张", "1 张"]);
  pass("the cast page chooses entries and counts each one's images");
  // Portraits live with the entry: the cast page opens 李四 in the world panel, at its 立绘 tab.
  const grid = () => page.locator(".wb-portraits-grid .wb-portraits-label").allTextContents();
  const portraitsOf = name => page.evaluate(async name => (await workbench.host.cast.sprites("RP阵容测试", name)).map(s => s.label).sort(), name);
  const castPrompt = () => page.evaluate(() => SillyTavern.getContext().extensionPrompts.noval_cast.value);
  await role("管理 李四 的立绘").click();
  await page.locator(".wb-portraits-grid").waitFor(); await page.waitForFunction(() => document.querySelectorAll(".wb-portraits-grid .wb-portraits-label").length === 1);
  assert.equal(await page.locator('.wb-entry-tabs [aria-selected="true"]').textContent(), "立绘"); assert.match(await page.locator(".wb-entry-card").getAttribute("aria-label"), /李四/);
  const face = name => ({ name, mimeType:"image/webp", buffer:fs.readFileSync("docs/design/rp-desktop/assets/r-user-character.webp") });
  await page.getByLabel("添加立绘").setInputFiles([face("Neutral.webp"), face("smile2.webp")]);
  // Dropping onto the tab adds to the same list (a synthetic drop carries files, not folder entries).
  const dropped = await page.evaluateHandle(async b64 => {
    const data = new DataTransfer(); data.items.add(new File([Uint8Array.from(atob(b64), x => x.charCodeAt(0))], "anger.webp", { type:"image/webp" })); return data;
  }, fs.readFileSync("docs/design/rp-desktop/assets/r-user-character.webp").toString("base64"));
  await page.locator(".wb-portraits").dispatchEvent("dragover", { dataTransfer:dropped }); assert.equal(await page.locator(".wb-portraits-drop").count(), 1);
  await page.locator(".wb-portraits").dispatchEvent("drop", { dataTransfer:dropped }); await page.waitForFunction(() => document.querySelectorAll(".wb-portraits-staged li").length === 3);
  assert.deepEqual(await page.locator(".wb-portraits-staged li small").allTextContents(), ["", "自定义", "将替换"], "labels come from file names; a custom one and a replaced one are marked");
  await page.getByLabel("smile2.webp 的表情名").fill("neutral");
  assert.equal(await page.locator(".wb-portraits-staged footer .is-primary").isDisabled(), true, "a label twice in the batch blocks the upload");
  await page.getByLabel("smile2.webp 的表情名").fill("smile"); await role("移出 anger.webp").click();
  await role("上传 2 张").click(); await page.waitForFunction(() => !document.querySelector(".wb-portraits-staged") && document.querySelectorAll(".wb-portraits-grid .wb-portraits-label").length === 3);
  assert.deepEqual((await grid()).sort(), ["anger", "neutral", "smile"]); assert.match(await castPrompt(), /李四（anger、neutral、smile）/);
  await role("改 smile 的表情名").click(); await page.getByLabel("smile 的新表情名").fill("joy"); await page.keyboard.press("Enter");
  await page.waitForFunction(() => [...document.querySelectorAll(".wb-portraits-grid .wb-portraits-label")].some(n => n.textContent === "joy"));
  assert.deepEqual(await portraitsOf("李四"), ["anger", "joy", "neutral"]);
  await role("删除 joy").click(); await role("确认删除 joy").click();
  await page.waitForFunction(() => document.querySelectorAll(".wb-portraits-grid .wb-portraits-label").length === 2);
  assert.deepEqual(await portraitsOf("李四"), ["anger", "neutral"]);
  pass("the 立绘 tab adds a batch labeled by file name, checks it before upload, relabels and deletes in place");
  // A renamed entry takes its portraits to the new folder, and this chat's cast follows the title.
  await page.getByRole("tab", { name:"触发条件" }).click(); await page.locator(".wb-entry-trigger input").first().fill("李四郎");
  await page.getByRole("tab", { name:"立绘" }).click(); assert.match(await page.locator(".wb-portraits-note").first().textContent(), /保存后，立绘会随条目改名移到「李四郎」/);
  await role("保存").click(); await page.getByText("已保存 · 2 张立绘随改名移动").waitFor();
  assert.deepEqual(await portraitsOf("李四郎"), ["anger", "neutral"]); assert.deepEqual(await portraitsOf("李四"), []);
  assert.deepEqual(await page.evaluate(() => SillyTavern.getContext().chatMetadata.workbenchRP.cast.entries), ["张三", "李四郎"]); assert.match(await castPrompt(), /李四郎（anger、neutral）/);
  await (await page.locator(".wb-entries .wb-entry-open").filter({ hasText:"王五/村长" })).click(); await page.getByRole("tab", { name:"立绘" }).click();
  assert.match(await page.locator(".wb-portraits-note.is-warning").textContent(), /不能作为立绘文件夹名/);
  pass("renaming an entry moves its portraits and this chat's cast; a title the server would alter says so");
  await role("关闭右栏").click(); await settle();
  await role("RP 外观").click(); await page.getByRole("button", { name:"角色卡 · 单人" }).click();
  await page.waitForFunction(() => !document.querySelector(".wb-rp-actor.is-cast"));
  assert.equal(await page.evaluate(() => SillyTavern.getContext().extensionPrompts.noval_cast.value === "" && !SillyTavern.getContext().chatMetadata.workbenchRP?.cast), true);
  await page.keyboard.press("Escape"); await page.evaluate(async () => { const c = SillyTavern.getContext(); await c.deleteLastMessage(); await c.deleteLastMessage(); }); await settle();
  pass("the card returns the stage and clears the prompt");
  // Story options. From the model: an injected prompt asks for an <options> block that no reader sees and no later prompt carries.
  const optionsPanel = () => page.getByRole("dialog", { name:"剧情选项", exact:true }), choice = page.getByRole("dialog", { name:"选择剧情选项" });
  const choices = choice.locator(".wb-story-row"), titles = () => choices.locator("strong").allInnerTexts(), tag = page.locator(".wb-rp-options-tag");
  const closeOptions = async () => { await optionsPanel().getByRole("button", { name:"关闭弹出框" }).click(); await settle(); };
  const choiceAfter = (layout, label) => optionsPanel().getByRole("group", { name:`${layout} 点选后` }).getByRole("button", { name:label, exact:true });
  await role("剧情选项").click(); await optionsPanel().waitFor(); await optionsPanel().getByRole("button", { name:"模型输出", exact:true }).click();
  await page.waitForFunction(() => SillyTavern.getContext().extensionPrompts.noval_options?.value.includes("[剧情选项]") && SillyTavern.getContext().chatMetadata.workbenchOptions?.source === "model");
  assert.equal(await choiceAfter("Noval", "填入输入框").getAttribute("aria-pressed"), "true"); assert.equal(await choiceAfter("RP", "直接发送").getAttribute("aria-pressed"), "true", "Noval fills and RP sends by default");
  await closeOptions(); await fetch(urls.mock + "/requests", { method:"DELETE" });
  await page.evaluate(() => { window.__optionsSeen = false; const chat = document.getElementById("chat"); window.__optionsWatch = new MutationObserver(() => { if (/<\/?options|option title|踩着脚印/.test([...chat.querySelectorAll(".mes_text")].map(n => n.textContent).join(""))) __optionsSeen = true; }); __optionsWatch.observe(chat, { subtree:true, childList:true, characterData:true }); });
  await role("快进到你的回应").click(); await settle(); await input.fill("WB_RP_OPTIONS"); await page.locator("#send_but").click();
  await page.waitForFunction(() => SillyTavern.getContext().chat.at(-1)?.mes.includes("</options>") && !workbench.host.snapshot().busy); await settle();
  assert.equal(await page.evaluate(() => { __optionsWatch.disconnect(); return __optionsSeen; }), false, "the block never shows, not even while it streams");
  // On the latest reply's last page the stage dims and the choice stands in the middle of the scene, over the band.
  await choice.waitFor(); assert.deepEqual(await titles(), ["追上去", "回村", "原地生火等他"]);
  assert.match(await choices.first().innerText(), /踩着脚印追进林子/); assert.equal(await page.locator(".wb-rp-choice-veil").count(), 1); assert.equal(await tag.count(), 0);
  const geometry = await page.evaluate(() => { const r = document.querySelector(".wb-rp-choice-panel .wb-story-row").getBoundingClientRect(), deck = document.querySelector(".wb-rp-deck").getBoundingClientRect(); return { width:r.width, centre:r.left + r.width / 2, middle:innerWidth / 2, bottom:r.bottom, deck:deck.top }; });
  assert(geometry.width <= 560 && Math.abs(geometry.centre - geometry.middle) < 2 && geometry.bottom <= geometry.deck, JSON.stringify(geometry));
  await choices.nth(1).hover(); await settle();
  assert.notEqual(await choices.nth(1).evaluate(n => getComputedStyle(n).backgroundColor), await choices.nth(0).evaluate(n => getComputedStyle(n).backgroundColor), "the hovered choice takes the accent");
  await page.screenshot({ path:`${dir}/options-rp.png` });
  // Esc puts it away and the 选项 tag beside 回应 brings it back; × puts it away too.
  await page.keyboard.press("Escape"); await choice.waitFor({ state:"detached" }); assert.equal(await tag.getAttribute("aria-label"), "剧情选项 · 3");
  await tag.click(); await choice.waitFor(); await choice.getByRole("button", { name:"隐藏剧情选项" }).click(); await choice.waitFor({ state:"detached" }); await tag.click(); await choice.waitFor();
  // RP sends by default, through the native send.
  await choices.first().click();
  await page.waitForFunction(() => SillyTavern.getContext().chat.at(-2)?.mes.startsWith("踩着") && SillyTavern.getContext().chat.at(-1)?.mes.includes("</options>") && !workbench.host.snapshot().busy); await settle();
  assert.equal(await input.inputValue(), "", "the choice went out as a sent message");
  const sent = (await (await fetch(urls.mock + "/requests")).json()).at(-1).body.messages;
  assert.equal(sent.some(m => m.role === "assistant" && JSON.stringify(m.content).includes("<options")), false, "earlier replies reach the model without their options");
  assert.equal(sent.some(m => m.role === "assistant" && JSON.stringify(m.content).includes("工作台验证回复")), true);
  assert.equal(sent.some(m => m.role === "system" && String(m.content).includes("[剧情选项]") && String(m.content).includes("<options>") && !String(m.content).includes("{{user}}")), true, "the instruction keeps its example and its macros are filled");
  const exported = await page.evaluate(() => workbench.host.exportSnapshot().messages.map(m => m.text).join("\n"));
  assert.equal(exported.includes("<options"), false, "the record export reads as the reader sees it"); assert.equal(exported.includes("工作台验证回复"), true);
  // Set to fill, the next reply's choice (picked by its number key) fills the input and opens it.
  await role("剧情选项").click(); await optionsPanel().waitFor(); await choiceAfter("RP", "填入输入框").click();
  await page.waitForFunction(() => SillyTavern.getContext().chatMetadata.workbenchOptions?.rp === "fill"); await closeOptions();
  await choice.waitFor(); await page.keyboard.press("2"); await settle();
  assert.equal(await input.inputValue(), "先回村里报信。"); assert.equal(await flag("wb-rp-compose"), true, "a filled choice opens the input");
  assert.equal(await choice.count(), 0); await page.locator("#rightSendForm .wb-rp-options-tag").waitFor();
  await input.fill(""); await role("返回对白").click(); await settle();
  pass("model options: an injected prompt, a hidden block, a galgame choice that sends by default or fills when set; Esc, × and the tag; later prompts leave the blocks out");
  // From the database plug-in: a bound table, read again on every update.
  await page.evaluate(() => { window.__dbCallbacks = []; window.__dbTables = { sheet_1:{ name:"选项表", content:[[null, "选项一", "选项二"], [0, "推门进去", "转身离开"]] }, mate:{ type:"chatSheets" } }; window.AutoCardUpdaterAPI = { exportTableAsJson:() => structuredClone(__dbTables), registerTableUpdateCallback:fn => __dbCallbacks.push(fn) }; });
  await role("剧情选项").click(); await optionsPanel().waitFor(); await optionsPanel().getByRole("button", { name:"数据库表", exact:true }).click();
  await page.waitForFunction(() => SillyTavern.getContext().extensionPrompts.noval_options?.value === "" && SillyTavern.getContext().chatMetadata.workbenchOptions?.source === "db");
  assert.match(await optionsPanel().innerText(), /请选择一张表/); assert.equal(await choices.count(), 0); assert.equal(await tag.count(), 0, "no options, no way in");
  await selectPaper(page, "数据库选项表", "选项表"); await page.waitForFunction(() => SillyTavern.getContext().chatMetadata.workbenchOptions?.table === "选项表");
  await closeOptions(); await choice.waitFor(); assert.deepEqual(await titles(), ["推门进去", "转身离开"]);
  await page.evaluate(() => { __dbTables.sheet_1.content = [["row_id", "行动", "后果"], [0, "敲门", "有人应声"], [1, "翻墙", "惊动护院"]]; __dbCallbacks.forEach(fn => fn()); });
  await page.waitForFunction(() => [...document.querySelectorAll(".wb-rp-choice-panel .wb-story-row strong")].map(n => n.textContent).join() === "敲门,翻墙");
  assert.match(await choices.nth(1).innerText(), /后果：惊动护院/);
  await page.evaluate(() => { __dbTables = { mate:{} }; __dbCallbacks.forEach(fn => fn()); }); await choice.waitFor({ state:"detached" }); assert.equal(await tag.count(), 0);
  await role("剧情选项").click(); await optionsPanel().waitFor(); assert.match(await optionsPanel().innerText(), /没有名为「选项表」的表/); await closeOptions();
  await page.evaluate(() => { __dbTables.sheet_1 = { name:"选项表", content:[[null, "选项一", "选项二"], [0, "推门进去", "转身离开"]] }; __dbCallbacks.forEach(fn => fn()); }); await choice.waitFor();
  pass("database options: a bound table by name, one row column by column and rows one by one, read again on each update; a missing table is reported");
  // Noval folds the same options into a card over its composer.
  await role("切换阅读布局").click(); await settle();
  const card = page.getByRole("region", { name:"剧情选项" }), rows = card.locator(".wb-story-row");
  assert.deepEqual(await rows.locator("strong").allInnerTexts(), ["推门进去", "转身离开"]);
  const [slot, form] = await page.evaluate(() => [".wb-story-options", "#send_form"].map(s => document.querySelector(s).getBoundingClientRect().toJSON()));
  assert(slot.bottom <= form.top + 1 && Math.abs(slot.left - form.left) < 2 && Math.abs(slot.width - form.width) < 2, JSON.stringify({ slot, form }));
  await rows.first().hover(); await page.screenshot({ path:`${dir}/options-noval.png` });
  await rows.first().click(); assert.equal(await input.inputValue(), "推门进去", "Noval fills by default");
  await page.keyboard.press("Alt+Digit2"); assert.equal(await input.inputValue(), "推门进去", "Alt+number waits for an empty input");
  await input.fill(""); await input.focus(); await page.keyboard.press("Alt+Digit2"); assert.equal(await input.inputValue(), "转身离开"); await input.fill("");
  await card.getByRole("button", { name:/剧情选项/ }).first().click(); await settle();
  assert.equal(await rows.count(), 0); assert.equal(await page.evaluate(() => SillyTavern.getContext().extensionSettings.workbench.optionsCollapsed), true, "the fold is remembered");
  await card.getByRole("button", { name:/剧情选项/ }).first().click(); await settle(); assert.equal(await rows.count(), 2);
  await chooseLayout(page, "RP"); await settle();
  await role("剧情选项").click(); await optionsPanel().waitFor(); await choiceAfter("RP", "直接发送").click(); await optionsPanel().getByRole("button", { name:"关闭", exact:true }).click();
  await page.waitForFunction(() => !document.querySelector(".wb-rp-choice-panel") && SillyTavern.getContext().chatMetadata.workbenchOptions?.source === "off" && SillyTavern.getContext().chatMetadata.workbenchOptions.rp === "send"); await closeOptions();
  assert.equal(await tag.count(), 0, "with the source off there is no choice and no tag");
  await page.evaluate(async () => { delete window.AutoCardUpdaterAPI; const c = SillyTavern.getContext(); for (let i = 0; i < 4; i++) await c.deleteLastMessage(); }); await settle();
  pass("Noval folds the options into a remembered card over its composer that fills on click or Alt+number; switching the source off removes every way in");
  await withReducedMotion(page, async () => assert.equal(await css("#sheld", "transitionDuration"), "0s")); pass("reduced motion is honored and the account preference restored");
  await role("切换阅读布局").click(); await settle(); assert.equal(await has("wb-rp"), false); assert.equal(await page.locator(".wb-reading-bar").count(), 1);
  assert.equal(await page.evaluate(() => __rpNative.chat === document.getElementById("chat") && __rpNative.input === document.getElementById("send_textarea")), true);
  for (const [width, height] of [[1024,768],[1366,768],[1496,817],[1920,1080]]) {
    await page.setViewportSize({ width, height }); await settle();
    const reading = await page.evaluate(() => {
      const rect = s => document.querySelector(s).getBoundingClientRect().toJSON();
      return { width:innerWidth, contexts:rect(".wb-top-pills"), actions:rect(".wb-top-tools"), form:rect("#send_form"), send:rect("#send_but"), tools:rect(".wb-composer-actions"), grip:rect(".wb-input-grip") };
    });
    assert(Math.abs(reading.contexts.x + reading.contexts.width / 2 - width / 2) < 3, JSON.stringify(reading));
    assert(reading.contexts.right <= reading.actions.left + 1 && reading.send.right <= reading.form.right && reading.tools.right <= reading.send.left && reading.grip.y - reading.form.y < 5, JSON.stringify(reading));
  }
  pass("reading mode keeps its centered header, native input grip and icon controls at four desktop sizes");
  await page.setViewportSize({ width:1496, height:817 });
  await chooseLayout(page,'RP'); await settle(); await page.evaluate(async () => { workbench.unmount(); await workbench.mount(); }); await settle();
  assert.equal(await has("wb-rp"), true); assert.equal(await has("wb-left-open"), false); assert.equal(await has("wb-right-open"), false);
  await page.evaluate(() => workbench.unmount()); assert.equal(await page.evaluate(() => !document.body.classList.contains("wb-rp") && !document.querySelector(".wb-rp-stage") && !document.getElementById("sheld").inert && __rpNative.input.isConnected), true);
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
