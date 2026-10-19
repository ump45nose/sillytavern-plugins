"use strict";
const test = require("node:test"),
  assert = require("node:assert/strict"),
  fs = require("node:fs"),
  os = require("node:os"),
  path = require("node:path"),
  {EventEmitter} = require("node:events");
const helper = require("../common/persistent_browser.cjs");
const laowang = require("../platforms/laowang/adapter.cjs");

function temp() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "benefits-profile-test-"));
}
function fakeBrowser({launchError, pageError, closeError, page = {}} = {}) {
  const state = {launches: [], closed: 0};
  return {
    state,
    browserType: {
      launchPersistentContext: async (profile, options) => {
        state.launches.push({profile, options});
        if (launchError) throw launchError;
        return {
          pages: () => [],
          newPage: async () => {
            if (pageError) throw pageError;
            return {goto: async () => {}, waitForTimeout: async () => {}, ...page};
          },
          close: async () => {
            state.closed++;
            if (closeError) throw closeError;
          },
        };
      },
    },
  };
}
function fakeTerminal(lines = []) {
  const out = [];
  return {
    out,
    write: (text) => out.push(String(text)),
    question: async (prompt) => (out.push(prompt), lines.shift() ?? ""),
    secret: async () => "",
    takeLine: () => (lines.length ? (lines.shift(), true) : false),
    close() {},
  };
}

test("requirePinned resolves from the platform directory and checks the version", () => {
  const root = temp();
  try {
    const pkg = path.join(root, "node_modules", "fake-browser-lib");
    fs.mkdirSync(pkg, {recursive: true});
    fs.writeFileSync(path.join(pkg, "package.json"), JSON.stringify({name: "fake-browser-lib", version: "1.2.3", main: "index.js"}));
    fs.writeFileSync(path.join(pkg, "index.js"), "module.exports = {firefox: 'pinned'};");
    assert.equal(helper.requirePinned(root, "fake-browser-lib", "1.2.3").firefox, "pinned");
    assert.throws(() => helper.requirePinned(root, "fake-browser-lib", "9.9.9"),
      /dependency_unavailable_or_incompatible/);
    assert.throws(() => helper.requirePinned(root, "missing-lib", "1.0.0"),
      /dependency_unavailable_or_incompatible/);
  } finally {
    fs.rmSync(root, {recursive: true, force: true});
  }
});

test("withProfile passes options unchanged and always closes the context", async () => {
  const b = fakeBrowser();
  const value = await helper.withProfile(b.browserType, {
    profile: "/fake", proxy: "http://127.0.0.1:1", contextOptions: {viewport: {width: 1, height: 2}},
  }, async (context, page) => (assert.ok(page.goto), "done"));
  assert.equal(value, "done");
  assert.deepEqual(b.state.launches[0], {profile: "/fake", options: {
    headless: true, proxy: {server: "http://127.0.0.1:1"}, viewport: {width: 1, height: 2}}});
  assert.equal(b.state.closed, 1);
  const failing = fakeBrowser();
  await assert.rejects(helper.withProfile(failing.browserType, {profile: "/fake"}, async () => {
    throw Error("work");
  }), /work/);
  assert.equal(failing.state.closed, 1);
  assert.deepEqual(failing.state.launches[0].options, {headless: true});
});

test("withProfile closes after page creation failure and surfaces close errors", async () => {
  const b = fakeBrowser({pageError: Error("page")});
  await assert.rejects(helper.withProfile(b.browserType, {profile: "/fake"}, async () => 1), /page/);
  assert.equal(b.state.closed, 1);
  const c = fakeBrowser({closeError: Error("close")});
  await assert.rejects(helper.withProfile(c.browserType, {profile: "/fake"}, async () => 1), /close/);
});

test("withProfile creates a private profile only when asked", async () => {
  const root = temp();
  try {
    const profile = path.join(root, "a", "browser");
    await helper.withProfile(fakeBrowser().browserType, {profile}, async () => 1);
    assert.equal(fs.existsSync(profile), false);
    assert.equal(helper.hasProfile(profile), false);
    await helper.withProfile(fakeBrowser().browserType, {profile, create: true}, async () => 1);
    assert.equal(fs.statSync(profile).mode & 0o777, 0o700);
    assert.equal(helper.hasProfile(profile), false);
    fs.writeFileSync(path.join(profile, "prefs.js"), "");
    assert.equal(helper.hasProfile(profile), true);
  } finally {
    fs.rmSync(root, {recursive: true, force: true});
  }
});

test("terminalLogin requires a terminal before launching", async () => {
  const b = fakeBrowser();
  const stdin = process.stdin;
  const original = Object.getOwnPropertyDescriptor(stdin, "isTTY");
  Object.defineProperty(stdin, "isTTY", {value: false, configurable: true});
  try {
    const out = await helper.terminalLogin(b.browserType, {profile: "/fake"}, {url: "https://example.invalid"});
    assert.deepEqual(out, {execution: "failed", reason: "interactive_terminal_required"});
    assert.equal(b.state.launches.length, 0);
  } finally {
    if (original) Object.defineProperty(stdin, "isTTY", original);
    else delete stdin.isTTY;
  }
});

test("terminalLogin without verify keeps the unverified manual result", async () => {
  const b = fakeBrowser();
  const terminal = fakeTerminal([""]);
  const out = await helper.terminalLogin(b.browserType, {profile: "/fake", headless: false},
    {url: "https://example.invalid", prompt: "Press Enter.", terminal});
  assert.deepEqual(out, {execution: "ok", reason: "manual_login_closed_unverified"});
  assert.deepEqual(terminal.out, ["Press Enter."]);
  assert.equal(b.state.launches[0].options.headless, false);
  assert.equal(b.state.closed, 1);
});

test("terminalLogin refreshes a private QR capture and removes it after verification", async () => {
  const root = temp();
  try {
    const file = path.join(root, "qr.png");
    let checks = 0;
    const seen = [];
    const out = await helper.terminalLogin(fakeBrowser().browserType, {profile: "/fake"}, {
      url: "https://example.invalid",
      terminal: fakeTerminal(),
      captureFile: file,
      capture: async () => Buffer.from("png" + checks),
      verify: async () => {
        if (fs.existsSync(file)) seen.push(fs.statSync(file).mode & 0o777);
        return ++checks > 2;
      },
      intervalMs: 1,
    });
    assert.deepEqual(out, {execution: "ok", reason: "login_verified"});
    assert.deepEqual(seen, [0o600, 0o600]);
    assert.equal(fs.existsSync(file), false);
  } finally {
    fs.rmSync(root, {recursive: true, force: true});
  }
});

test("terminalLogin reports poll failures, Enter without login and the deadline", async () => {
  const options = {profile: "/fake"};
  const flow = {url: "https://example.invalid", verify: async () => false, intervalMs: 1};
  assert.deepEqual(await helper.terminalLogin(fakeBrowser().browserType, options,
    {...flow, terminal: fakeTerminal(), poll: async () => ({reason: "password_rejected"})}),
  {execution: "failed", reason: "password_rejected"});
  assert.deepEqual(await helper.terminalLogin(fakeBrowser().browserType, options,
    {...flow, terminal: fakeTerminal([""])}),
  {execution: "failed", reason: "login_not_confirmed"});
  assert.deepEqual(await helper.terminalLogin(fakeBrowser().browserType, options,
    {...flow, terminal: fakeTerminal(), deadlineMs: 5}),
  {execution: "failed", reason: "login_timeout"});
});

test("openTerminal queues lines and reads a secret without keeping echo", async () => {
  const input = new EventEmitter();
  input.isTTY = true;
  input.fd = -1;
  const modes = [];
  input.setRawMode = (value) => modes.push(value);
  const writes = [];
  const original = process.stdout.write;
  process.stdout.write = (text) => (writes.push(String(text)), true);
  try {
    const terminal = helper.openTerminal(input);
    input.emit("data", Buffer.from("first\n"));
    assert.equal(terminal.takeLine(), true);
    assert.equal(terminal.takeLine(), false);
    const answer = terminal.question("Name?");
    input.emit("data", Buffer.from("value\n"));
    assert.equal(await answer, "value");
    const secret = terminal.secret("Password:");
    input.emit("data", Buffer.from("pa"));
    input.emit("data", Buffer.from("x\u007fss\r"));
    assert.equal(await secret, "pass");
    assert.deepEqual(modes, [true, false]);
    assert.ok(!writes.join("").includes("pass"));
    terminal.close();
  } finally {
    process.stdout.write = original;
  }
});

test("Laowang login keeps its manual unverified contract", async () => {
  const b = fakeBrowser();
  const out = await laowang.login(b.browserType, "/fake", undefined, fakeTerminal([""]));
  assert.deepEqual(out, {execution: "ok", reason: "manual_login_closed_unverified", checkin: "unknown"});
  assert.deepEqual(b.state.launches[0], {profile: "/fake", options: {headless: false}});
  assert.equal(b.state.closed, 1);
});

test("Laowang maps a launch failure and propagates a close failure", async () => {
  const launch = fakeBrowser({launchError: Error("offline")});
  assert.equal((await laowang.run(launch.browserType, "/fake")).reason, "browser_or_network_error");
  const close = fakeBrowser({closeError: Error("close"), page: {
    locator: () => ({count: async () => 1}), url: () => "https://laowang.vip/plugin.php"}});
  await assert.rejects(laowang.run(close.browserType, "/fake"), /close/);
});
