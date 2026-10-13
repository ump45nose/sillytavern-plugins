"use strict";
// Explicit local-only integration test. Never loads a platform URL or credentials.
const assert = require("node:assert/strict"),
  fs = require("node:fs/promises"),
  os = require("node:os"),
  path = require("node:path");
const {
  firefox,
} = require("../platforms/laowang/node_modules/playwright-firefox");
(async () => {
  const profile = await fs.mkdtemp(
    path.join(
      process.env.BENEFITS_SMOKE_TMP || os.tmpdir(),
      "benefits-firefox-fixture-",
    ),
  );
  let context;
  try {
    context = await firefox.launchPersistentContext(profile, {
      headless: true,
    });
    await context.route("**/*", (route) => route.abort());
    const page = context.pages()[0] || (await context.newPage());
    await page.setContent(
      '<html><body><div class="qdleft"><span class="btnvisted">Signed fixture</span></div></body></html>',
    );
    assert.equal(await page.locator(".qdleft .btnvisted").count(), 1);
    console.log(
      "Native Firefox local HTML/profile smoke passed (all network blocked)",
    );
  } finally {
    if (context) await context.close();
    await fs.rm(profile, { recursive: true, force: true });
  }
})().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
