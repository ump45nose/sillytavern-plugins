"use strict";
// Telegram Web K bot check-in through the account's own logged-in web session.
// Business logic only: profile, login, result and journal plumbing are shared.
const path = require("node:path");
const crypto = require("node:crypto");
const {publish} = require("../../common/result.cjs");
const {metric} = require("../../common/details.cjs");
const {requirePinned, hasProfile, withProfile, terminalLogin} =
  require("../../common/persistent_browser.cjs");
const {readConfig, ConfigError} = require("./config.cjs");
const {Journal, StateError, textHash} = require("./state.cjs");
const web = require("./selectors.cjs");

const CONTEXT = {viewport: {width: 1280, height: 900}};
const APP_TIMEOUT_MS = 60000;
const CHAT_TIMEOUT_MS = 30000;

class NotLoggedIn extends Error {}

const realClock = {
  now: () => Date.now(),
  sleep: (page, ms) => page.waitForTimeout(ms),
  spacing: ([min, max]) => crypto.randomInt(min * 1000, max * 1000 + 1),
};

function classify(texts, bot) {
  const values = texts.map(web.normalize);
  const has = (list) => list.some((pattern) => values.some((text) => text.includes(web.normalize(pattern))));
  if (has(bot.already)) return "already_checked_in";
  if (has(bot.failure)) return "bot_rejected";
  if (has(bot.success)) return "checkin_confirmed";
  return null;
}

// Wait until the web app shows either the signed-in layout or the login cards.
async function openApp(page, clock, url = web.BASE_URL) {
  await page.goto("about:blank");
  await page.goto(url, {waitUntil: "domcontentloaded", timeout: 45000});
  const end = clock.now() + APP_TIMEOUT_MS;
  let authSeen = 0;
  while (clock.now() < end) {
    const snap = await web.snapshot(page);
    if (snap.authenticated) return snap;
    authSeen = snap.auth ? authSeen + 1 : 0;
    if (authSeen >= 3) throw new NotLoggedIn();
    await clock.sleep(page, 1000);
  }
  throw Error("telegram_app_unavailable");
}

async function openChat(page, bot, clock) {
  await openApp(page, clock, web.BASE_URL + "#@" + bot.username);
  const end = clock.now() + CHAT_TIMEOUT_MS;
  while (clock.now() < end) {
    const snap = await web.snapshot(page);
    if (!snap.authenticated) throw new NotLoggedIn();
    if (snap.inputReady || snap.startRequired) return snap;
    await clock.sleep(page, 1000);
  }
  return null;
}

function commandIndex(messages, entry, command) {
  const wanted = web.normalize(command);
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i];
    const value = web.midValue(message);
    if (message.out && value !== null && (entry.baseline === null || value > entry.baseline) &&
        web.normalize(message.text).includes(wanted)) return i;
  }
  return -1;
}

// Replies that may carry the verdict. With a button flow, only content that
// appeared or changed after the recorded click counts, so a menu that merely
// mentions success cannot confirm the check-in.
function verdictTexts(snap, index, entry, bot) {
  const replies = snap.messages.slice(index + 1).filter((message) => !message.out);
  if (!bot.button) return [...replies.map((message) => message.text), ...snap.answers];
  if (entry.button !== "clicked") return [];
  const texts = [];
  for (const message of replies) {
    const value = web.midValue(message);
    if (value === null) continue;
    if (value > entry.button_mid) texts.push(message.text);
    else if (value === entry.button_mid && textHash(message.text) !== entry.button_hash)
      texts.push(message.text);
  }
  return [...texts, ...snap.answers];
}

function buttonTarget(snap, index, bot) {
  const wanted = web.normalize(bot.button.text);
  const replies = snap.messages.slice(index + 1).filter((message) => !message.out);
  for (let i = replies.length - 1; i >= 0; i--) {
    const message = replies[i];
    const position = message.buttons.findIndex((text) => web.normalize(text).includes(wanted));
    if (position >= 0 && web.midValue(message) !== null) return {message, position};
  }
  return null;
}

async function send(page, bot, journal, snap) {
  const input = page.locator(web.SELECTORS.messageInput).locator("visible=true").first();
  await input.click({timeout: 10000});
  await input.fill(bot.command, {timeout: 10000});
  const typed = await input.evaluate((element) => element.innerText || element.textContent || "");
  if (typed.trim() !== bot.command) {
    await input.fill("", {timeout: 10000}).catch(() => {});
    return "input_unconfirmed";
  }
  // The send button, not Enter: Enter may pick a command suggestion instead.
  const button = page.locator(web.SELECTORS.sendButton).locator("visible=true");
  if ((await button.count()) !== 1) {
    await input.fill("", {timeout: 10000}).catch(() => {});
    return "send_control_unavailable";
  }
  const values = snap.messages.map(web.midValue).filter((value) => value !== null);
  journal.markSent(bot.id, values.length ? Math.max(...values) : null);
  await button.first().click({timeout: 10000}).catch(() => {}); // May have reached Telegram.
  return null;
}

async function checkBot(page, bot, journal, clock) {
  const item = (status, reason) => ({
    id: bot.id, name: "@" + bot.username, url: "https://t.me/" + bot.username, status, reason,
  });
  if (!bot.enabled) return item("not_applicable", "bot_disabled");
  let entry = journal.get(bot.id);
  if (entry.phase === "confirmed") return item("complete", entry.reason);
  const opened = await openChat(page, bot, clock);
  if (!opened) return item("unknown", "chat_unavailable");
  if (opened.startRequired) return item("blocked", "bot_not_started");
  const resumed = entry.phase === "sent";
  if (!resumed) {
    const refused = await send(page, bot, journal, opened);
    if (refused) return item("unknown", refused);
    entry = journal.get(bot.id);
  }
  let seenCommand = false, sawReply = false;
  const end = clock.now() + bot.replyTimeoutMs;
  while (clock.now() < end) {
    const snap = await web.snapshot(page);
    if (!snap.authenticated) throw new NotLoggedIn();
    const index = commandIndex(snap.messages, entry, bot.command);
    if (index >= 0) {
      seenCommand = true;
      sawReply = sawReply || snap.messages.slice(index + 1).some((message) => !message.out);
      const verdict = classify(verdictTexts(snap, index, entry, bot), bot);
      if (verdict === "bot_rejected") return item("incomplete", verdict);
      if (verdict) {
        journal.markConfirmed(bot.id, verdict);
        return item("complete", verdict);
      }
      if (bot.button && entry.button === "none") {
        const target = buttonTarget(snap, index, bot);
        if (target) {
          journal.markButton(bot.id, web.midValue(target.message), target.message.text);
          entry = journal.get(bot.id);
          await page.locator(`${web.SELECTORS.bubble}[data-mid="${target.message.mid}"] ${web.SELECTORS.inlineButton}`)
            .nth(target.position).click({timeout: 10000}).catch(() => {});
        }
      }
    }
    await clock.sleep(page, 1000);
  }
  if (!seenCommand) return item("unknown", resumed ? "previous_send_unconfirmed" : "command_not_visible");
  if (bot.button && entry.button === "none") return item("unknown", sawReply ? "button_not_found" : "reply_timeout");
  return item("unknown", sawReply ? "reply_unrecognized" : "reply_timeout");
}

function summary(items) {
  const counted = items.filter((row) => row.status !== "not_applicable");
  const confirmed = counted.filter((row) => row.status === "complete").length;
  const states = new Set(counted.map((row) => row.status));
  const checkin = counted.length === 0 ? "not_applicable"
    : confirmed === counted.length ? "complete"
      : states.has("unknown") ? "unknown" : states.has("blocked") ? "blocked" : "incomplete";
  return {
    execution: "ok",
    reason: checkin === "complete" || checkin === "not_applicable" ? "all_bots_confirmed" : "bots_incomplete",
    checkin,
    details: {metrics: {bots: metric("count", confirmed, counted.length)}, items},
  };
}

function journalItems(config, journal) {
  return config.bots.map((bot) => {
    const entry = journal.get(bot.id);
    const base = {id: bot.id, name: "@" + bot.username, url: "https://t.me/" + bot.username};
    if (!bot.enabled) return {...base, status: "not_applicable", reason: "bot_disabled"};
    if (entry.phase === "confirmed") return {...base, status: "complete", reason: entry.reason};
    if (entry.phase === "sent") return {...base, status: "unknown", reason: "previous_send_unconfirmed"};
    return {...base, status: "incomplete", reason: "not_attempted"};
  });
}

const failure = (reason, checkin = "unknown") => ({execution: "failed", reason, checkin});

async function run(firefox, {profile, stateDir, businessDate, account, configFile, proxy,
  statusOnly = false, clock = realClock} = {}) {
  if (!hasProfile(profile)) return failure("not_logged_in", "blocked");
  let config, journal;
  try {
    config = readConfig(configFile, account);
    journal = new Journal(stateDir, businessDate);
  } catch (error) {
    if (error instanceof ConfigError || error instanceof StateError) return failure(error.code);
    throw error;
  }
  try {
    return await withProfile(firefox, {profile, proxy, headless: true, contextOptions: CONTEXT},
      async (context, page) => {
        await openApp(page, clock);
        if (statusOnly) {
          const result = summary(journalItems(config, journal));
          return {...result, reason: "authenticated"};
        }
        const items = [];
        let visited = false;
        for (const bot of config.bots) {
          const pending = bot.enabled && journal.get(bot.id).phase !== "confirmed";
          if (pending && visited) await clock.sleep(page, clock.spacing(config.spacing));
          items.push(await checkBot(page, bot, journal, clock));
          visited = visited || pending;
        }
        return summary(items);
      });
  } catch (error) {
    if (error instanceof NotLoggedIn) return failure("not_logged_in", "blocked");
    if (error instanceof StateError) return failure(error.code);
    if (error && error.message === "selector_broken") return failure("selector_broken");
    if (error && error.message === "telegram_app_unavailable") return failure("telegram_app_unavailable");
    return failure("browser_or_network_error");
  }
}

// QR login in the persistent profile; the QR image refreshes in a 0600 file in
// the private run directory and is removed when login ends. A two-step
// password is read from the terminal without echo and never stored.
async function login(firefox, {profile, proxy, captureFile, terminal}) {
  let attempts = 0;
  const outcome = await terminalLogin(firefox, {profile, proxy, headless: true, create: true,
    contextOptions: CONTEXT}, {
    url: web.BASE_URL,
    prompt: "Telegram > Settings > Devices > Link Desktop Device, then scan the QR image. " +
      "Press Enter to stop waiting.",
    captureFile,
    terminal,
    deadlineMs: 240000,
    capture: async (page) => {
      if (!(await web.snapshot(page)).qr) return null;
      return page.locator(web.SELECTORS.qrCanvas).locator("visible=true").first()
        .screenshot({timeout: 5000});
    },
    verify: async (page) => (await web.snapshot(page)).authenticated,
    poll: async (page, io) => {
      if (!(await web.snapshot(page)).passwordRequired) return null;
      if (attempts >= 3) return {reason: "password_not_accepted"};
      attempts++;
      const secret = await io.secret("Telegram two-step verification password (not shown):");
      const input = page.locator(web.SELECTORS.passwordInput).locator("visible=true").first();
      await input.fill(secret, {timeout: 10000});
      await input.press("Enter", {timeout: 10000});
      await page.waitForTimeout(3000);
      return null;
    },
  });
  return {...outcome, checkin: "unknown"};
}

async function main() {
  const args = process.argv.slice(2);
  const env = process.env;
  const profile = path.join(env.BENEFITS_STATE_DIR, "browser");
  // Without a logged-in profile nothing can be sent; no browser is loaded.
  if (!args.includes("--login") && !hasProfile(profile))
    return publish("failed", "not_logged_in", {checkin: "blocked"});
  let firefox;
  try {
    firefox = requirePinned(__dirname, "playwright-firefox", "1.63.0").firefox;
  } catch {
    return publish("failed", "dependency_unavailable_or_incompatible", {checkin: "unknown"});
  }
  let r;
  try {
    r = args.includes("--login")
      ? await login(firefox, {profile, proxy: env.TELEGRAM_PROXY,
        captureFile: path.join(path.dirname(env.BENEFITS_RESULT_PATH), "telegram-login-qr.png")})
      : await run(firefox, {profile, stateDir: env.BENEFITS_STATE_DIR,
        businessDate: env.BENEFITS_BUSINESS_DATE, account: env.BENEFITS_ACCOUNT,
        configFile: env.TELEGRAM_CONFIG, proxy: env.TELEGRAM_PROXY,
        statusOnly: args.includes("--status")});
  } catch {
    r = failure("browser_cleanup_failed");
  }
  publish(r.execution, r.reason, {checkin: r.checkin},
    r.details || {metrics: {}, items: []});
}

if (require.main === module) main();
module.exports = {run, login, classify, summary, realClock};
