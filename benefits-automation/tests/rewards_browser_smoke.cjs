"use strict";
// Explicit local-only smoke; excluded from test discovery. No saved state or site traffic.
const path = require("node:path"),
  assert = require("node:assert/strict");
const root = process.argv[2];
if (!root || !path.isAbsolute(root)) throw Error("Pass dependency root");
const { chromium } = require(path.join(root, "node_modules/patchright"));
(async () => {
  let browser;
  try {
    browser = await chromium.launch({
      headless: true,
      chromiumSandbox: true,
      timeout: 20000,
    });
    const context = await browser.newContext();
    await context.route("**/*", (route) => route.abort());
    const page = await context.newPage();
    await page.setContent(
      '<main><button>Local fixture</button><p id="result">ready</p></main>',
    );
    assert.equal(await page.locator("#result").innerText(), "ready");
    await context.close();
    console.log("Native Chromium local-only DOM smoke passed");
  } finally {
    await browser?.close();
  }
})().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
