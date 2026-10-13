#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const net = require("node:net");

const stateDir = process.env.FIGMA_BROWSER_STATE_DIR || path.join(os.homedir(), ".local/share/figma-make/browser");
const socketPath = path.join(stateDir, "control.sock");

async function call(input) {
  return new Promise((resolve, reject) => {
    const connection = net.createConnection(socketPath);
    let response = "";
    connection.on("connect", () => connection.end(JSON.stringify(input)));
    connection.on("data", chunk => response += chunk);
    connection.on("end", () => resolve(JSON.parse(response)));
    connection.on("error", reject);
  });
}

async function serve() {
  process.umask(0o077);
  fs.mkdirSync(stateDir, { recursive: true });
  const { chromium } = require(process.env.FIGMA_PLAYWRIGHT_MODULE || "playwright");
  const context = await chromium.launchPersistentContext(path.join(stateDir, "profile"), {
    executablePath: process.env.FIGMA_CHROMIUM_PATH,
    headless: process.env.FIGMA_BROWSER_HEADLESS !== "false",
    viewport: { width: 1440, height: 1000 },
    locale: "en-US",
    userAgent: process.env.FIGMA_BROWSER_USER_AGENT,
    proxy: process.env.FIGMA_BROWSER_PROXY ? { server: process.env.FIGMA_BROWSER_PROXY } : undefined,
    acceptDownloads: true,
  });
  const page = await context.newPage();
  for (const previous of context.pages()) if (previous !== page) await previous.close();
  if (process.env.FIGMA_BROWSER_HEADLESS !== "false" && !process.env.FIGMA_BROWSER_USER_AGENT) {
    const agent = await page.evaluate(() => navigator.userAgent.replace("HeadlessChrome/", "Chrome/"));
    const session = await context.newCDPSession(page);
    await session.send("Emulation.setUserAgentOverride", { userAgent: agent });
  }
  const requests = [];
  function route(request) {
    const url = new URL(request.url());
    return { method: request.method(), origin: url.origin, path: url.pathname, type: request.resourceType() };
  }
  // Keep operation routes, never headers, payloads, query values, or tokens.
  page.on("request", request => requests.push(route(request)));
  page.on("response", response => requests.push({ ...route(response.request()), status: response.status() }));
  page.on("requestfailed", request => requests.push({ ...route(request), failure: request.failure().errorText }));
  const downloads = [];
  async function captureDownload(download) {
    const directory = path.join(stateDir, "downloads");
    fs.mkdirSync(directory, { recursive: true });
    const entry = { name: download.suggestedFilename(), state: "saving" };
    entry.path = path.join(directory, entry.name);
    downloads.push(entry);
    try {
      await download.saveAs(entry.path);
      entry.state = "saved";
      entry.bytes = fs.statSync(entry.path).size;
    } catch (error) {
      entry.state = "failed";
      entry.error = error.message;
    }
  }
  context.on("page", popup => popup.on("download", captureDownload));
  page.on("download", captureDownload);
  async function perform(input) {
    const target = input.frame === undefined ? page : page.frames()[input.frame];
    switch (input.op) {
      case "goto":
        await page.goto(input.url, { waitUntil: "domcontentloaded" });
        return { url: page.url() };
      case "snapshot":
        return { url: page.url(), text: await target.locator("body").ariaSnapshot() };
      case "click":
        await target.locator(input.selector).click({ noWaitAfter: true });
        return { clicked: true };
      case "hover":
        await target.locator(input.selector).hover();
        return { hovered: true };
      case "fill":
        await target.locator(input.selector).fill(input.text);
        return { filled: true };
      case "upload":
        await target.locator(input.selector).setInputFiles(input.paths);
        return { uploaded: input.paths.length };
      case "press":
        await target.locator(input.selector).press(input.key);
        return { pressed: true };
      case "evaluate":
        return await target.evaluate(input.expression);
      case "viewport":
        await page.setViewportSize({ width: input.width, height: input.height });
        return { width: input.width, height: input.height };
      case "frames":
        return page.frames().map((frame, index) => ({ index, name: frame.name(), url: frame.url() }));
      case "screenshot": {
        const output = path.join(stateDir, input.filename || "page.png");
        await page.screenshot({ path: output, fullPage: input.fullPage ?? true });
        return { path: output };
      }
      case "downloads":
        return downloads;
      case "network":
        return requests.slice(input.offset || 0);
      case "login":
        await page.locator(input.emailSelector).fill(input.email);
        await page.locator(input.passwordSelector).fill(input.password);
        await page.locator(input.submitSelector).click();
        return { submitted: true };
      case "close":
        await context.close();
        server.close();
        return { closed: true };
    }
  }
  const server = net.createServer({ allowHalfOpen: true }, connection => {
    let message = "";
    connection.on("data", chunk => message += chunk);
    connection.on("end", async () => {
      const input = JSON.parse(message);
      try {
        connection.end(JSON.stringify({ ok: true, result: await perform(input) }));
      } catch (error) {
        connection.end(JSON.stringify({ ok: false, error: input.op === "login" ? "Login failed; inspect the page without logging credentials." : error.message }));
      }
    });
  });
  server.listen(socketPath, () => console.log(JSON.stringify({ ready: true, socketPath })));
}

if (require.main === module) {
  const operation = process.argv[2];
  (operation === "serve" ? serve() : call(JSON.parse(fs.readFileSync(0, "utf8"))))
    .then(result => { if (result !== undefined) console.log(JSON.stringify(result)); })
    .catch(error => { console.error(error.message); process.exitCode = 1; });
}

module.exports = { call };
