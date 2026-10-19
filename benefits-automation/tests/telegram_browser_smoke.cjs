"use strict";
// Explicit local-only integration test. Never loads Telegram or credentials:
// all network is aborted and only synthetic fixtures are rendered.
const assert = require("node:assert/strict"),
  fs = require("node:fs/promises"),
  os = require("node:os"),
  path = require("node:path");
const {firefox} = require("../platforms/telegram/node_modules/playwright-firefox");
const web = require("../platforms/telegram/selectors.cjs");
const FIXTURES = path.join(__dirname, "fixtures", "telegram");

(async () => {
  const profile = await fs.mkdtemp(path.join(process.env.BENEFITS_SMOKE_TMP || os.tmpdir(),
    "benefits-telegram-fixture-"));
  let context;
  try {
    context = await firefox.launchPersistentContext(profile, {headless: true});
    await context.route("**/*", (route) => route.abort());
    const page = context.pages()[0] || (await context.newPage());
    const load = async (name) => page.setContent(await fs.readFile(path.join(FIXTURES, name), "utf8"));

    await load("login-qr.html");
    let snap = await web.snapshot(page);
    assert.equal(snap.auth, true);
    assert.equal(snap.authenticated, false);
    assert.equal(snap.qr, true);
    const qr = await page.locator(web.SELECTORS.qrCanvas).locator("visible=true").first().screenshot();
    assert.ok(qr.length > 100);

    await load("password.html");
    snap = await web.snapshot(page);
    assert.equal(snap.passwordRequired, true);
    assert.equal(await page.locator(web.SELECTORS.passwordInput).locator("visible=true").count(), 1);

    await load("bot-start.html");
    snap = await web.snapshot(page);
    assert.equal(snap.authenticated, true);
    assert.equal(snap.startRequired, true);
    assert.equal(snap.inputReady, false);

    await load("chat-reply.html");
    snap = await web.snapshot(page);
    assert.equal(snap.authenticated, true);
    assert.equal(snap.inputReady, true);
    assert.deepEqual(snap.messages.map((m) => [m.mid, m.out]), [["100", false], ["101", true], ["102", false]]);
    assert.match(snap.messages[1].text, /^\/checkin/);
    assert.deepEqual(snap.messages[2].buttons, ["📅 签到", "帮助"]);
    assert.deepEqual(snap.answers, ["今日已签到"]);
    const input = page.locator(web.SELECTORS.messageInput).locator("visible=true").first();
    await input.fill("/checkin");
    assert.equal((await input.evaluate((e) => e.innerText)).trim(), "/checkin");
    assert.equal(await page.locator(web.SELECTORS.sendButton).locator("visible=true").count(), 1);
    assert.equal(await page.locator(`${web.SELECTORS.bubble}[data-mid="102"] ${web.SELECTORS.inlineButton}`).count(), 2);
    console.log("Native Firefox Telegram fixture smoke passed (all network blocked)");
  } finally {
    if (context) await context.close();
    await fs.rm(profile, {recursive: true, force: true});
  }
})().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
