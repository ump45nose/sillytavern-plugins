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
// The NAS proxy to web.telegram.org drops for a minute or two at a time.
// Opening the app is read-only, so it is retried within this budget; sends
// are never retried (the journal guards them).
const APP_RETRY_MS = 180000;
const APP_RETRY_PAUSE_MS = 30000;

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

async function openAppRetrying(page, clock, url = web.BASE_URL) {
  const end = clock.now() + APP_RETRY_MS;
  for (;;) {
    try {
      return await openApp(page, clock, url);
    } catch (error) {
      if (error instanceof NotLoggedIn || (error && error.message === "selector_broken")) throw error;
      if (clock.now() + APP_RETRY_PAUSE_MS >= end) throw Error("telegram_app_unavailable");
      await clock.sleep(page, APP_RETRY_PAUSE_MS);
    }
  }
}

// First capture group of the bot's points pattern in the latest verdict text
// that has it. Only the number is kept; the reply text is not.
function readPoints(texts, bot) {
  if (!bot.points) return null;
  for (let i = texts.length - 1; i >= 0; i--) {
    const match = bot.points.regex.exec(web.normalize(texts[i]));
    if (match && match[1] !== undefined) {
      const value = Number(match[1].replace(/,/g, ""));
      if (Number.isFinite(value) && value >= 0) return value;
    }
  }
  return null;
}

async function openChat(page, bot, clock) {
  await openAppRetrying(page, clock, web.BASE_URL + "#@" + bot.username);
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
  const typed = await web.boundedRead(input.evaluate((element) => element.innerText || element.textContent || ""));
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

async function checkBot(page, bot, journal, clock, points = new Map()) {
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
      const texts = verdictTexts(snap, index, entry, bot);
      const verdict = classify(texts, bot);
      if (verdict === "bot_rejected") return item("incomplete", verdict);
      if (verdict) {
        const value = readPoints(texts, bot);
        if (value !== null) points.set(bot.id, value);
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

function pointMetrics(bots, points) {
  const metrics = {};
  for (const bot of bots)
    if (bot.points) metrics["points_" + bot.id.replace(/-/g, "_")] = metric(bot.points.unit, points.get(bot.id) ?? null);
  return metrics;
}

function summary(items, extraMetrics = {}) {
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
    details: {metrics: {bots: metric("count", confirmed, counted.length), ...extraMetrics}, items},
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
  statusOnly = false, clock = realClock, onProgress = () => {}} = {}) {
  if (!hasProfile(profile)) return failure("not_logged_in", "blocked");
  let config, journal;
  try {
    config = readConfig(configFile, account);
    journal = new Journal(stateDir, businessDate);
  } catch (error) {
    if (error instanceof ConfigError || error instanceof StateError) return failure(error.code);
    throw error;
  }
  let latest = summary(journalItems(config, journal));
  const checkpoint = (items = [], metrics = {}) => {
    const observed = new Map(items.map((item) => [item.id, item]));
    latest = summary(journalItems(config, journal).map((item) => observed.get(item.id) || item), metrics);
    if (!statusOnly) onProgress(latest);
  };
  checkpoint();
  try {
    return await withProfile(firefox, {profile, proxy, headless: true, contextOptions: CONTEXT},
      async (context, page) => {
        await openAppRetrying(page, clock);
        if (statusOnly) {
          const result = summary(journalItems(config, journal));
          return {...result, reason: "authenticated"};
        }
        const items = [];
        const points = new Map();
        let visited = false;
        for (const bot of config.bots) {
          const pending = bot.enabled && journal.get(bot.id).phase !== "confirmed";
          if (pending && visited) await clock.sleep(page, clock.spacing(config.spacing));
          items.push(await checkBot(page, bot, journal, clock, points));
          checkpoint(items, pointMetrics(config.bots, points));
          visited = visited || pending;
        }
        return summary(items, pointMetrics(config.bots, points));
      });
  } catch (error) {
    const reason = error instanceof NotLoggedIn ? "not_logged_in"
      : error instanceof StateError ? error.code
        : ["selector_broken", "telegram_app_unavailable", "telegram_snapshot_timeout"].includes(error?.message) ? error.message
          : "browser_or_network_error";
    console.error(JSON.stringify({event: "telegram_browser_failure", reason, type: error?.name,
      interaction: ["intercepts pointer events", "not stable", "outside of the viewport", "not visible", "Target closed"]
        .filter((marker) => String(error?.message || "").includes(marker))}));
    return {...latest, execution: "failed", reason,
      ...(error instanceof NotLoggedIn ? {checkin: "blocked"} : {})};
  }
}

// QR login in the persistent profile; the QR image refreshes in a 0600 file in
// the private run directory and is removed when login ends. A two-step
// password is read from the terminal without echo and never stored.
// Long enough for the QR to be relayed to another device and scanned.
const LOGIN_WAIT_MS = 600000;
const PASSWORD_ATTEMPTS = 3;
const PASSWORD_RESULT_MS = 30000;

// Fill the one real password field, confirm it holds the whole secret, submit,
// then wait for Telegram's verdict: the card leaves (accepted), the field gets
// .error (rejected), or neither (the submit never reached Telegram). Only an
// explicit rejection counts as a wrong password.
async function submitPassword(page, secret, clock) {
  const fields = page.locator(web.SELECTORS.passwordInput).locator("visible=true");
  if ((await fields.count()) !== 1) return "password_field_ambiguous";
  const input = fields.first();
  await input.fill(secret, {timeout: 10000});
  const filled = await web.boundedRead(input.evaluate((element, length) => {
    if (element.value.length !== length) return false;
    element.classList.remove("error"); // A previous verdict must not decide this attempt.
    return true;
  }, secret.length));
  if (!filled) {
    await input.fill("", {timeout: 10000}).catch(() => {});
    return "password_input_unconfirmed";
  }
  await input.press("Enter", {timeout: 10000});
  const end = clock.now() + PASSWORD_RESULT_MS;
  let busy = false;
  while (clock.now() < end) {
    await clock.sleep(page, 1000);
    const snap = await web.snapshot(page);
    if (snap.authenticated || !snap.passwordRequired) return "submitted";
    if (snap.passwordBusy) busy = true;
    else if (snap.passwordRejected) return "rejected";
  }
  return busy ? "password_check_timeout" : "password_submit_unconfirmed";
}

async function login(firefox, {profile, proxy, captureFile, terminal, clock = realClock}) {
  let rejected = 0;
  const outcome = await terminalLogin(firefox, {profile, proxy, headless: true, create: true,
    contextOptions: CONTEXT}, {
    url: web.BASE_URL,
    prompt: "Telegram > Settings > Devices > Link Desktop Device, then scan the QR image. " +
      "Press Enter to stop waiting.",
    captureFile,
    terminal,
    deadlineMs: LOGIN_WAIT_MS,
    capture: async (page) => {
      if (!(await web.snapshot(page)).qr) return null;
      return page.locator(web.SELECTORS.qrCanvas).locator("visible=true").first()
        .screenshot({timeout: 5000});
    },
    verify: async (page) => (await web.snapshot(page)).authenticated,
    poll: async (page, io) => {
      if (!(await web.snapshot(page)).passwordRequired) return null;
      const secret = await io.secret("Telegram two-step verification password (not shown):");
      if (!secret) return {reason: "password_not_entered"};
      const result = await submitPassword(page, secret, clock);
      if (result === "submitted") return null;
      if (result !== "rejected") return {reason: result};
      rejected++;
      if (rejected >= PASSWORD_ATTEMPTS) return {reason: "password_not_accepted"};
      io.write("Telegram rejected the password; try again.");
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
        statusOnly: args.includes("--status"),
        onProgress: (value) => publish("failed", "bots_in_progress", {checkin: value.checkin}, value.details)});
  } catch {
    r = failure("browser_cleanup_failed");
  }
  publish(r.execution, r.reason, {checkin: r.checkin},
    r.details || {metrics: {}, items: []});
}

if (require.main === module) main();
module.exports = {run, login, submitPassword, classify, summary, realClock};
