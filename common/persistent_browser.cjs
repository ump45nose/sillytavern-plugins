"use strict";
// Persistent browser profile helpers for one-shot Node adapters.
// common/ has no node_modules: callers pass their own pinned browser type.
// No browser pool, no background process; every context closes before return.
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");

const MAX_CAPTURE = 1048576;

// Resolve the dependency from the platform directory, like a plain require there.
function requirePinned(platformDirectory, name, version) {
  try {
    const paths = {paths: [platformDirectory]};
    const manifest = require(require.resolve(name + "/package.json", paths));
    if (manifest.version !== version) throw Error("version");
    return require(require.resolve(name, paths));
  } catch {
    throw Error("dependency_unavailable_or_incompatible");
  }
}

// True only for an existing, non-empty profile directory (no browser launch).
function hasProfile(profile) {
  try {
    const stat = fs.lstatSync(profile);
    return stat.isDirectory() && fs.readdirSync(profile).length > 0;
  } catch {
    return false;
  }
}

async function withProfile(browserType, options, work) {
  const {profile, proxy, headless = true, contextOptions = {}, create = false} =
    options || {};
  if (typeof profile !== "string" || !profile) throw Error("profile_invalid");
  if (create) fs.mkdirSync(profile, {recursive: true, mode: 0o700});
  let context;
  try {
    context = await browserType.launchPersistentContext(profile, {
      headless,
      ...(proxy ? {proxy: {server: proxy}} : {}),
      ...contextOptions,
    });
    const page = context.pages()[0] || (await context.newPage());
    return await work(context, page);
  } finally {
    if (context) await context.close();
  }
}

function writePrivate(file, bytes) {
  if (!Buffer.isBuffer(bytes) || bytes.length === 0 || bytes.length > MAX_CAPTURE)
    throw Error("capture_invalid");
  fs.mkdirSync(path.dirname(file), {recursive: true, mode: 0o700});
  const temporary = file + ".tmp-" + crypto.randomUUID();
  let fd;
  try {
    fd = fs.openSync(temporary, "wx", 0o600);
    fs.writeFileSync(fd, bytes);
    fs.fsyncSync(fd);
    fs.closeSync(fd);
    fd = undefined;
    fs.renameSync(temporary, file);
  } finally {
    if (fd !== undefined) fs.closeSync(fd);
    fs.rmSync(temporary, {force: true});
  }
}

// The runner pipes adapter stdout into the private run log; an interactive
// login inherits stdin, so prompts go to that terminal instead.
function openTerminal(input = process.stdin) {
  if (!input || !input.isTTY) return null;
  const lines = [];
  const waiters = [];
  let buffer = "";
  let secret = null;
  const write = (text) => {
    try {
      fs.writeSync(input.fd ?? 0, text);
    } catch {
      process.stdout.write(text);
    }
  };
  const onData = (chunk) => {
    const value = chunk.toString("utf8");
    if (secret) {
      for (const character of value) {
        if (character === "\r" || character === "\n") {
          const done = secret;
          secret = null;
          if (input.setRawMode) input.setRawMode(false);
          write("\n");
          done.resolve(done.value);
          return;
        }
        if (character === "\u0003") {
          const done = secret;
          secret = null;
          if (input.setRawMode) input.setRawMode(false);
          write("\n");
          done.reject(Error("login_cancelled"));
          return;
        }
        if (character === "\u007f" || character === "\b")
          secret.value = secret.value.slice(0, -1);
        else if (secret.value.length < 1024) secret.value += character;
      }
      return;
    }
    buffer += value;
    let index;
    while ((index = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, index).replace(/\r$/, "").slice(0, 1024);
      buffer = buffer.slice(index + 1);
      if (waiters.length) waiters.shift()(line);
      else lines.push(line);
    }
    if (buffer.length > 4096) buffer = "";
  };
  input.on("data", onData);
  if (input.resume) input.resume();
  return {
    write: (text) => write(String(text) + "\n"),
    question(prompt) {
      write(String(prompt) + " ");
      if (lines.length) return Promise.resolve(lines.shift());
      return new Promise((resolve) => waiters.push(resolve));
    },
    secret(prompt) {
      write(String(prompt) + " ");
      return new Promise((resolve, reject) => {
        secret = {value: "", resolve, reject};
        if (input.setRawMode) input.setRawMode(true);
      });
    },
    takeLine() {
      return lines.length ? (lines.shift(), true) : false;
    },
    close() {
      input.off("data", onData);
      if (secret && input.setRawMode) input.setRawMode(false);
      if (input.pause) input.pause();
    },
  };
}

const delay = (page, ms) =>
  page.waitForTimeout ? page.waitForTimeout(ms) : new Promise((r) => setTimeout(r, ms));

// One interactive login in the persistent profile. Without verify, the user
// confirms with Enter and the result stays unverified (caller checks later).
async function terminalLogin(browserType, options, flow) {
  const terminal = flow.terminal || openTerminal();
  if (!terminal)
    return {execution: "failed", reason: "interactive_terminal_required"};
  try {
    return await withProfile(browserType, options, async (context, page) => {
      await page.goto(flow.url, {
        waitUntil: flow.waitUntil || "domcontentloaded",
        timeout: flow.timeout ?? 45000,
      });
      if (typeof flow.verify !== "function") {
        await terminal.question(flow.prompt || "Complete login manually, then press Enter.");
        return {execution: "ok", reason: "manual_login_closed_unverified"};
      }
      terminal.write(flow.prompt || "Complete login; press Enter to stop waiting.");
      const end = Date.now() + (flow.deadlineMs ?? 300000);
      let announced = false;
      while (Date.now() < end) {
        if (await flow.verify(page)) return {execution: "ok", reason: "login_verified"};
        if (typeof flow.capture === "function" && flow.captureFile) {
          let image = null;
          try {
            image = await flow.capture(page);
          } catch {}
          if (image) {
            writePrivate(flow.captureFile, image);
            if (!announced) terminal.write("QR image (0600, refreshed): " + flow.captureFile);
            announced = true;
          }
        }
        if (typeof flow.poll === "function") {
          const outcome = await flow.poll(page, terminal);
          if (outcome && outcome.reason)
            return {execution: "failed", reason: outcome.reason};
        }
        if (terminal.takeLine())
          return (await flow.verify(page))
            ? {execution: "ok", reason: "login_verified"}
            : {execution: "failed", reason: "login_not_confirmed"};
        await delay(page, flow.intervalMs ?? 2000);
      }
      return {execution: "failed", reason: "login_timeout"};
    });
  } finally {
    if (flow.captureFile) fs.rmSync(flow.captureFile, {force: true});
    if (!flow.terminal) terminal.close();
  }
}

module.exports = {requirePinned, hasProfile, withProfile, terminalLogin, openTerminal, writePrivate};
