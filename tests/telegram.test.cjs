"use strict";
const test = require("node:test"),
  assert = require("node:assert/strict"),
  fs = require("node:fs"),
  os = require("node:os"),
  path = require("node:path");
const telegram = require("../platforms/telegram/adapter.cjs");
const {parseConfig, readConfig} = require("../platforms/telegram/config.cjs");
const {Journal} = require("../platforms/telegram/state.cjs");
const web = require("../platforms/telegram/selectors.cjs");
const {validateDetails} = require("../common/details.cjs");

const DAY = "2026-10-19";
const bot = (extra = {}) => ({id: "alpha", username: "AlphaBot", command: "/checkin",
  success: ["签到成功"], already: ["已签到"], failure: ["失败"], ...extra});

function workspace(config) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "benefits-telegram-test-"));
  const stateDir = path.join(root, "state");
  const profile = path.join(stateDir, "browser");
  fs.mkdirSync(profile, {recursive: true, mode: 0o700});
  fs.writeFileSync(path.join(profile, "prefs.js"), "");
  const configFile = path.join(root, "telegram.json");
  fs.writeFileSync(configFile, JSON.stringify(config), {mode: 0o600});
  return {root, stateDir, profile, configFile, cleanup: () => fs.rmSync(root, {recursive: true, force: true})};
}

// Scripted Telegram Web K: chats keyed by bot username, replies after polls.
function fakeTelegram({authenticated = true, chats = {}} = {}) {
  const state = {authenticated, chat: null, typed: "", sends: [], clicks: [], gotos: [], closed: 0, pending: []};
  let nextMid = 1000;
  const chat = () => chats[state.chat];
  const tick = () => {
    for (const job of state.pending.splice(0)) {
      if (--job.after > 0) state.pending.push(job);
      else job.run();
    }
  };
  const incoming = (text, buttons = []) => chat().messages.push({mid: String(nextMid++), out: false, text, buttons});
  const snapshot = () => {
    tick();
    const current = chat();
    return {
      auth: !state.authenticated, authenticated: state.authenticated, qr: !state.authenticated,
      passwordRequired: false,
      inputReady: Boolean(current && !current.notStarted),
      startRequired: Boolean(current && current.notStarted),
      messages: current ? current.messages.map((m) => ({...m, buttons: m.buttons || []})) : [],
      answers: current ? current.answers || [] : [],
    };
  };
  const locate = (selector) => {
    const handle = {
      locator: () => handle,
      first: () => handle,
      nth: (index) => ({click: async () => {
        const mid = /data-mid="([^"]+)"/.exec(selector)[1];
        state.clicks.push({chat: state.chat, mid, index});
        const message = chat().messages.find((m) => m.mid === mid);
        chat().onButton?.({message, index, incoming, state});
      }}),
      count: async () => (selector === web.SELECTORS.sendButton && state.typed ? 1 : 0),
      click: async () => {
        if (selector !== web.SELECTORS.sendButton) return;
        const text = state.typed;
        state.typed = "";
        state.sends.push({chat: state.chat, text});
        chat().messages.push({mid: String(nextMid++), out: true, text: text + "\n12:00", buttons: []});
        chat().onCommand?.({text, incoming, state, later: (after, run) => state.pending.push({after, run})});
      },
      fill: async (value) => { state.typed = value; },
      evaluate: async () => state.typed,
      press: async () => {},
      screenshot: async () => Buffer.from("qr"),
    };
    return handle;
  };
  const page = {
    goto: async (url) => {
      state.gotos.push(url);
      const match = /#@(\w+)$/.exec(url);
      state.chat = match ? match[1] : null;
    },
    waitForTimeout: async () => {},
    evaluate: async (fn) => {
      assert.equal(fn, web.readPage);
      return snapshot();
    },
    locator: locate,
  };
  return {
    state, incoming,
    firefox: {launchPersistentContext: async () => ({pages: () => [page], close: async () => { state.closed++; }})},
  };
}

function clock() {
  let now = 0;
  const spacingCalls = [];
  return {spacingCalls, now: () => now, sleep: async (page, ms) => { now += ms; },
    spacing: (range) => (spacingCalls.push(range), 7000)};
}

async function run(fake, ws, extra = {}) {
  return telegram.run(fake.firefox, {profile: ws.profile, stateDir: ws.stateDir, businessDate: DAY,
    account: "tg-ai", configFile: ws.configFile, clock: clock(), ...extra});
}

test("parseConfig validates one account and rejects unsafe bot entries", () => {
  const config = parseConfig({accounts: {"tg-ai": {bots: [bot()]}}}, "tg-ai");
  assert.equal(config.bots[0].replyTimeoutMs, 30000);
  assert.deepEqual(config.spacing, [5, 20]);
  assert.throws(() => parseConfig({accounts: {"tg-ai": {bots: [bot()]}}}, "tg-nsfw"), /account_not_configured/);
  for (const broken of [
    {username: "alice"}, {username: "Alice_Person"}, {command: "/checkin\n/again"},
    {success: []}, {id: "Bad Id"}, {reply_timeout_seconds: 1}, {button: {text: ""}}, {extra: 1},
  ])
    assert.throws(() => parseConfig({accounts: {"tg-ai": {bots: [bot(broken)]}}}, "tg-ai"),
      /configuration_invalid/, JSON.stringify(broken));
  assert.throws(() => parseConfig({accounts: {"tg-ai": {bots: [bot(), bot()]}}}, "tg-ai"), /configuration_invalid/);
  assert.throws(() => parseConfig({accounts: {"tg-ai": {bots: [bot()], spacing_seconds: [9, 1]}}}, "tg-ai"),
    /configuration_invalid/);
});

test("readConfig requires a private absolute file", () => {
  const ws = workspace({accounts: {"tg-ai": {bots: [bot()]}}});
  try {
    assert.equal(readConfig(ws.configFile, "tg-ai").bots.length, 1);
    assert.throws(() => readConfig(undefined, "tg-ai"), /configuration_missing/);
    assert.throws(() => readConfig("relative.json", "tg-ai"), /configuration_missing/);
    assert.throws(() => readConfig(path.join(ws.root, "missing.json"), "tg-ai"), /configuration_missing/);
    fs.chmodSync(ws.configFile, 0o644);
    assert.throws(() => readConfig(ws.configFile, "tg-ai"), /private_file_invalid/);
  } finally {
    ws.cleanup();
  }
});

test("journal moves idle to sent to confirmed and resets on a new day", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "benefits-telegram-journal-"));
  try {
    const journal = new Journal(dir, DAY);
    assert.equal(journal.get("alpha").phase, "idle");
    assert.throws(() => journal.markConfirmed("alpha", "checkin_confirmed"), /journal_transition_invalid/);
    journal.markSent("alpha", 41);
    assert.throws(() => journal.markSent("alpha", 41), /journal_transition_invalid/);
    journal.markConfirmed("alpha", "already_checked_in");
    const file = path.join(dir, "telegram-journal.json");
    assert.equal(fs.statSync(file).mode & 0o777, 0o600);
    assert.deepEqual(new Journal(dir, DAY).get("alpha"), {phase: "confirmed", baseline: 41,
      button: "none", button_mid: null, button_hash: null, reason: "already_checked_in"});
    assert.equal(new Journal(dir, "2026-10-20").get("alpha").phase, "idle");
    fs.writeFileSync(file, JSON.stringify({schema_version: 1, business_date: DAY, bots: {alpha: {phase: "sent"}}}));
    assert.throws(() => new Journal(dir, DAY), /journal_invalid/);
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});

test("missing profile reports not_logged_in without launching a browser", async () => {
  const ws = workspace({accounts: {"tg-ai": {bots: [bot()]}}});
  try {
    fs.rmSync(ws.profile, {recursive: true});
    let launched = false;
    const out = await telegram.run({launchPersistentContext: async () => { launched = true; }},
      {profile: ws.profile, stateDir: ws.stateDir, businessDate: DAY, account: "tg-ai",
        configFile: ws.configFile, statusOnly: true});
    assert.deepEqual(out, {execution: "failed", reason: "not_logged_in", checkin: "blocked"});
    assert.equal(launched, false);
  } finally {
    ws.cleanup();
  }
});

test("login page reports not_logged_in and sends nothing", async () => {
  const ws = workspace({accounts: {"tg-ai": {bots: [bot()]}}});
  try {
    const fake = fakeTelegram({authenticated: false, chats: {AlphaBot: {messages: []}}});
    assert.deepEqual(await run(fake, ws), {execution: "failed", reason: "not_logged_in", checkin: "blocked"});
    assert.deepEqual(fake.state.sends, []);
    assert.equal(fake.state.closed, 1);
  } finally {
    ws.cleanup();
  }
});

test("status reads the journal only and never opens a bot chat", async () => {
  const ws = workspace({accounts: {"tg-ai": {bots: [bot(), bot({id: "beta", username: "BetaBot"})]}}});
  try {
    const journal = new Journal(ws.stateDir, DAY);
    journal.markSent("alpha", null);
    journal.markConfirmed("alpha", "checkin_confirmed");
    const fake = fakeTelegram({chats: {}});
    const out = await run(fake, ws, {statusOnly: true});
    assert.equal(out.reason, "authenticated");
    assert.equal(out.checkin, "incomplete");
    assert.deepEqual(out.details.items.map((i) => [i.id, i.status, i.reason]),
      [["alpha", "complete", "checkin_confirmed"], ["beta", "incomplete", "not_attempted"]]);
    assert.ok(fake.state.gotos.every((url) => !url.includes("#@")));
    assert.deepEqual(fake.state.sends, []);
  } finally {
    ws.cleanup();
  }
});

test("sends once per bot, confirms from the reply and spaces bots", async () => {
  const ws = workspace({accounts: {"tg-ai": {bots: [bot(), bot({id: "beta", username: "BetaBot", command: "/sign"})]}}});
  try {
    const reply = (text) => ({messages: [{mid: "10", out: false, text: "签到成功 (old reply)"}],
      onCommand: ({incoming, later}) => later(2, () => incoming(text))});
    const fake = fakeTelegram({chats: {AlphaBot: reply("签到成功，+5"), BetaBot: reply("今天已签到")}});
    const c = clock();
    const out = await run(fake, ws, {clock: c});
    assert.equal(out.execution, "ok");
    assert.equal(out.checkin, "complete");
    assert.deepEqual(out.details.items.map((i) => [i.id, i.status, i.reason]),
      [["alpha", "complete", "checkin_confirmed"], ["beta", "complete", "already_checked_in"]]);
    assert.deepEqual(fake.state.sends, [{chat: "AlphaBot", text: "/checkin"}, {chat: "BetaBot", text: "/sign"}]);
    assert.deepEqual(c.spacingCalls, [[5, 20]]);
    assert.deepEqual(out.details.metrics.bots.current, 2);
    validateDetails(out.details);
    const saved = fs.readFileSync(path.join(ws.stateDir, "telegram-journal.json"), "utf8");
    assert.ok(!saved.includes("签到") && !saved.includes("checkin\""), "no message text stored");
    // Second run the same day: nothing is sent again.
    const again = fakeTelegram({chats: {AlphaBot: reply("x"), BetaBot: reply("x")}});
    const second = await run(again, ws);
    assert.equal(second.checkin, "complete");
    assert.deepEqual(again.state.sends, []);
    assert.ok(again.state.gotos.every((url) => !url.includes("#@")));
  } finally {
    ws.cleanup();
  }
});

test("a sent but unconfirmed bot is read back, never resent", async () => {
  const ws = workspace({accounts: {"tg-ai": {bots: [bot()]}}});
  try {
    new Journal(ws.stateDir, DAY).markSent("alpha", 20);
    const quiet = fakeTelegram({chats: {AlphaBot: {messages: [{mid: "15", out: true, text: "/checkin"}]}}});
    const first = await run(quiet, ws);
    assert.deepEqual(first.details.items.map((i) => [i.status, i.reason]), [["unknown", "previous_send_unconfirmed"]]);
    assert.deepEqual(quiet.state.sends, []);
    const answered = fakeTelegram({chats: {AlphaBot: {messages: [
      {mid: "21", out: true, text: "/checkin 08:45"}, {mid: "22", out: false, text: "签到成功"}]}}});
    const second = await run(answered, ws);
    assert.equal(second.checkin, "complete");
    assert.deepEqual(answered.state.sends, []);
  } finally {
    ws.cleanup();
  }
});

test("rejection, silence and unknown replies stay unconfirmed", async () => {
  for (const [script, expected] of [
    [({incoming}) => incoming("签到失败：请稍后"), ["incomplete", "bot_rejected"]],
    [() => {}, ["unknown", "reply_timeout"]],
    [({incoming}) => incoming("Unknown command"), ["unknown", "reply_unrecognized"]],
  ]) {
    const ws = workspace({accounts: {"tg-ai": {bots: [bot()]}}});
    try {
      const fake = fakeTelegram({chats: {AlphaBot: {messages: [], onCommand: script}}});
      const out = await run(fake, ws);
      assert.deepEqual(out.details.items.map((i) => [i.status, i.reason]), [expected]);
      assert.equal(out.reason, "bots_incomplete");
      assert.equal(fake.state.sends.length, 1);
      assert.equal(new Journal(ws.stateDir, DAY).get("alpha").phase, "sent");
    } finally {
      ws.cleanup();
    }
  }
});

test("button flow clicks once and ignores success words already in the menu", async () => {
  const ws = workspace({accounts: {"tg-ai": {bots: [bot({command: "/start", button: {text: "签到"}})]}}});
  try {
    const fake = fakeTelegram({chats: {AlphaBot: {
      messages: [],
      onCommand: ({incoming}) => incoming("菜单：签到成功可得积分", ["📅 签到", "帮助"]),
      onButton: ({message, index}) => { if (index === 0) message.text = "签到成功，获得 3 积分"; },
    }}});
    const out = await run(fake, ws);
    assert.equal(out.checkin, "complete");
    assert.equal(fake.state.clicks.length, 1);
    assert.equal(fake.state.clicks[0].index, 0);
    const entry = new Journal(ws.stateDir, DAY).get("alpha");
    assert.equal(entry.button, "clicked");
    assert.match(entry.button_hash, /^[a-f0-9]{16}$/);
  } finally {
    ws.cleanup();
  }
});

test("button that changes nothing is not clicked twice and stays unknown", async () => {
  const ws = workspace({accounts: {"tg-ai": {bots: [bot({command: "/start", button: {text: "签到"}})]}}});
  try {
    const chats = {AlphaBot: {messages: [], onCommand: ({incoming}) => incoming("菜单", ["签到"])}};
    const fake = fakeTelegram({chats});
    const out = await run(fake, ws);
    assert.deepEqual(out.details.items.map((i) => [i.status, i.reason]), [["unknown", "reply_unrecognized"]]);
    assert.equal(fake.state.clicks.length, 1);
    const again = fakeTelegram({chats: {AlphaBot: {messages: fake.state.sends.length ? [
      {mid: "1000", out: true, text: "/start"}, {mid: "1001", out: false, text: "菜单", buttons: ["签到"]}] : []}}});
    await run(again, ws);
    assert.deepEqual(again.state.clicks, []);
    assert.deepEqual(again.state.sends, []);
  } finally {
    ws.cleanup();
  }
});

test("bot that was never started is blocked without pressing START", async () => {
  const ws = workspace({accounts: {"tg-ai": {bots: [bot(), bot({id: "off", username: "OffBot", enabled: false})]}}});
  try {
    const fake = fakeTelegram({chats: {AlphaBot: {messages: [], notStarted: true}}});
    const out = await run(fake, ws);
    assert.deepEqual(out.details.items.map((i) => [i.id, i.status, i.reason]),
      [["alpha", "blocked", "bot_not_started"], ["off", "not_applicable", "bot_disabled"]]);
    assert.equal(out.checkin, "blocked");
    assert.deepEqual(fake.state.sends, []);
  } finally {
    ws.cleanup();
  }
});

test("each account keeps its own journal under its own state directory", async () => {
  const config = {accounts: {"tg-ai": {bots: [bot()]}, "tg-nsfw": {bots: [bot({id: "nsfw", username: "OtherBot"})]}}};
  const ai = workspace(config), nsfw = workspace(config);
  try {
    const reply = {messages: [], onCommand: ({incoming}) => incoming("签到成功")};
    await run(fakeTelegram({chats: {AlphaBot: {...reply}}}), ai);
    const out = await run(fakeTelegram({chats: {OtherBot: {...reply}}}), nsfw, {account: "tg-nsfw"});
    assert.deepEqual(out.details.items.map((i) => i.name), ["@OtherBot"]);
    assert.deepEqual(Object.keys(new Journal(ai.stateDir, DAY).value.bots), ["alpha"]);
    assert.deepEqual(Object.keys(new Journal(nsfw.stateDir, DAY).value.bots), ["nsfw"]);
  } finally {
    ai.cleanup();
    nsfw.cleanup();
  }
});

test("login captures the QR through the shared helper and verifies the session", async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "benefits-telegram-login-"));
  try {
    const fake = fakeTelegram({authenticated: false});
    let polls = 0;
    const page = (await fake.firefox.launchPersistentContext()).pages()[0];
    const original = page.evaluate;
    page.evaluate = async (fn) => {
      if (++polls > 3) fake.state.authenticated = true;
      return original(fn);
    };
    const terminal = {out: [], write(t) { this.out.push(t); }, question: async () => "",
      secret: async () => "", takeLine: () => false, close() {}};
    const profile = path.join(root, "browser");
    const out = await telegram.login(fake.firefox, {profile, captureFile: path.join(root, "qr.png"), terminal});
    assert.deepEqual(out, {execution: "ok", reason: "login_verified", checkin: "unknown"});
    assert.equal(fs.statSync(profile).mode & 0o777, 0o700);
    assert.equal(fs.existsSync(path.join(root, "qr.png")), false);
    assert.ok(terminal.out.some((line) => line.includes("qr.png")));
  } finally {
    fs.rmSync(root, {recursive: true, force: true});
  }
});

// Scripted Web K password card: `onSubmit(value)` returns "accept", "reject" or "ignore".
function fakePasswordPage(onSubmit, {fields = 1} = {}) {
  const state = {authenticated: false, password: true, busy: false, error: false, value: "",
    submits: 0, fills: 0, verdictAfter: 0};
  const page = {
    goto: async () => {},
    waitForTimeout: async () => {},
    evaluate: async (fn) => {
      assert.equal(fn, web.readPage);
      if (state.verdictAfter && --state.verdictAfter === 0) {
        state.busy = false;
        const verdict = onSubmit(state.value);
        if (verdict === "accept") { state.password = false; state.authenticated = true; }
        if (verdict === "reject") state.error = true;
      }
      return {auth: !state.authenticated, authenticated: state.authenticated, qr: false,
        passwordRequired: state.password, passwordBusy: state.password && state.busy,
        passwordRejected: state.password && !state.busy && state.error,
        inputReady: false, startRequired: false, messages: [], answers: []};
    },
    locator: (selector) => {
      assert.equal(selector, web.SELECTORS.passwordInput);
      const handle = {
        locator: () => handle,
        first: () => handle,
        count: async () => fields,
        fill: async (value) => { state.fills++; state.value = value; },
        evaluate: async (fn, length) => {
          const element = {value: state.value, classList: {remove: () => { state.error = false; }}};
          return fn(element, length);
        },
        press: async (key) => {
          assert.equal(key, "Enter");
          state.submits++;
          if (onSubmit(null) !== "ignore") { state.busy = true; state.verdictAfter = 2; }
        },
      };
      return handle;
    },
  };
  return {state, firefox: {launchPersistentContext: async () => ({pages: () => [page], close: async () => {}})}};
}

function passwordTerminal(answers) {
  return {out: [], prompts: 0, write(t) { this.out.push(t); }, question: async () => "",
    secret: async function() { return answers[this.prompts++] ?? ""; }, takeLine: () => false, close() {}};
}

async function passwordLogin(fake, terminal) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "benefits-telegram-password-"));
  try {
    return await telegram.login(fake.firefox, {profile: path.join(root, "browser"),
      captureFile: path.join(root, "qr.png"), terminal, clock: clock()});
  } finally {
    fs.rmSync(root, {recursive: true, force: true});
  }
}

test("login submits the two-step password once and verifies the session", async () => {
  const fake = fakePasswordPage((value) => (value === null || value === "right" ? "accept" : "reject"));
  const terminal = passwordTerminal(["right"]);
  const out = await passwordLogin(fake, terminal);
  assert.deepEqual(out, {execution: "ok", reason: "login_verified", checkin: "unknown"});
  assert.equal(terminal.prompts, 1);
  assert.equal(fake.state.submits, 1);
  assert.ok(!terminal.out.some((line) => line.includes("right")));
});

test("only explicit Telegram rejections count toward password_not_accepted", async () => {
  const fake = fakePasswordPage((value) => (value === null ? "submit" : "reject"));
  const terminal = passwordTerminal(["a", "b", "c", "d"]);
  const out = await passwordLogin(fake, terminal);
  assert.equal(out.reason, "password_not_accepted");
  assert.equal(terminal.prompts, 3);
  assert.equal(fake.state.submits, 3);
  assert.equal(terminal.out.filter((line) => line.includes("rejected")).length, 2);
});

test("a submit that never reaches Telegram is not reported as a wrong password", async () => {
  const fake = fakePasswordPage(() => "ignore");
  const terminal = passwordTerminal(["right", "right"]);
  const out = await passwordLogin(fake, terminal);
  assert.equal(out.reason, "password_submit_unconfirmed");
  assert.equal(terminal.prompts, 1, "no re-prompt when nothing was submitted");
});

test("password flow refuses ambiguous fields, short fills and empty input without submitting", async () => {
  let fake = fakePasswordPage(() => "accept", {fields: 3});
  assert.equal((await passwordLogin(fake, passwordTerminal(["right"]))).reason, "password_field_ambiguous");
  assert.equal(fake.state.submits, 0);

  fake = fakePasswordPage(() => "accept");
  assert.equal((await passwordLogin(fake, passwordTerminal([""]))).reason, "password_not_entered");
  assert.equal(fake.state.fills, 0);

  fake = fakePasswordPage(() => "accept");
  const page = (await fake.firefox.launchPersistentContext()).pages()[0];
  const locate = page.locator;
  page.locator = (selector) => {
    const handle = locate(selector);
    const fill = handle.fill;
    handle.fill = async (value) => fill(value.slice(0, 2)); // Field truncates the value.
    return handle;
  };
  assert.equal((await passwordLogin(fake, passwordTerminal(["right"]))).reason, "password_input_unconfirmed");
  assert.equal(fake.state.submits, 0);
});

test("password selector skips Web K's stealthy decoy inputs", () => {
  assert.match(web.SELECTORS.passwordInput, /:not\(\.stealthy\)/);
  assert.match(web.SELECTORS.passwordInput, /:not\(\[aria-hidden="true"\]\)/);
});

test("classify and summary follow the result contract", () => {
  const b = parseConfig({accounts: {a: {bots: [bot()]}}}, "a").bots[0];
  assert.equal(telegram.classify(["今天 已签到 了"], b), "already_checked_in");
  assert.equal(telegram.classify(["ＳＩＧＮ"], {...b, success: ["sign"]}), "checkin_confirmed");
  assert.equal(telegram.classify(["hello"], b), null);
  const out = telegram.summary([{id: "a", name: "@A", status: "complete", reason: "checkin_confirmed"},
    {id: "b", name: "@B", status: "unknown", reason: "reply_timeout"}]);
  assert.equal(out.checkin, "unknown");
  validateDetails(out.details);
});

// Reply shapes observed on 2026-10-20 (links and numbers trimmed): a notice and a
// "please wait" message precede the verdict, "您已经获得" must not read as already,
// and a join-channel gate is a rejection, not a silent timeout.
test("observed multi-message replies classify as success, already or gate", async () => {
  const already = ["已签到", "已经签到", "签到过", "already checked in"];
  const gate = ["签到失败", "人机验证", "请先加入以下频道"];
  for (const [replies, expected] of [
    [["\"广告\"是骗子 重 要 声 明", "正在签到,请稍后...", "签到成功\n您已经获得 1 积分。\n您现在的积分为：6分。"],
      ["complete", "checkin_confirmed"]],
    [["🎉签到成功！您获得了 5 积分！\n当前账户余额：20 分"], ["complete", "checkin_confirmed"]],
    [["今天已经签到了，明天再来！"], ["complete", "already_checked_in"]],
    [["人机验证\n请先加入以下频道/群组完成验证"], ["incomplete", "bot_rejected"]],
  ]) {
    const ws = workspace({accounts: {"tg-ai": {bots: [bot({command: "/sign", already, failure: gate})]}}});
    try {
      const fake = fakeTelegram({chats: {AlphaBot: {messages: [],
        onCommand: ({incoming, later}) => replies.forEach((text, i) => later(i + 1, () => incoming(text)))}}});
      const out = await run(fake, ws);
      assert.deepEqual(out.details.items.map((i) => [i.status, i.reason]), [expected], replies.join(" / "));
      assert.equal(fake.state.sends.length, 1);
    } finally {
      ws.cleanup();
    }
  }
});
