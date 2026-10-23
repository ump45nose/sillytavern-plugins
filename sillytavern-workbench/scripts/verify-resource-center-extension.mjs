import assert from "node:assert/strict";
import { chromium } from "playwright";
import { readFileSync, writeFileSync, mkdtempSync, rmSync } from "node:fs";
const base = "http://192.168.31.201:18321";
const access = JSON.parse(
  readFileSync("/vol2/1000/Docker/ai-resource-center/access.json", "utf8"),
);
const login = await fetch(base + "/api/v1/session", {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({ password: access.adminPassword }),
});
const cookie = login.headers.get("set-cookie").split(";")[0];
const api = async (path) => {
  const r = await fetch(base + "/api/v1/" + path, { headers: { cookie } });
  return r.json();
};
const before = await api("state");
const extension =
  "/vol2/1000/Docker/ai-resource-center/all-api-hub-integration";
const profileDir = mkdtempSync(
  "/vol2/1000/Docker/ai-resource-center/extension-acceptance-",
);
const context = await chromium.launchPersistentContext(profileDir, {
  executablePath:
    "/home/yuwk/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome",
  headless: true,
  args: [
    "--no-sandbox",
    "--no-proxy-server",
    "--disable-dev-shm-usage",
    "--disable-extensions-except=" + extension,
    "--load-extension=" + extension,
  ],
});
try {
  const worker =
    context.serviceWorkers()[0] ||
    (await context.waitForEvent("serviceworker"));
  const id = new URL(worker.url()).host;
  const page = await context.newPage();
  page.on("response", (r) => {
    if (r.url().endsWith("/api/v1/ingest"))
      console.log("Ingest response", r.status());
  });
  await page.goto(
    `chrome-extension://${id}/options.html?tab=notifications&anchor=ai-resource-center#basic`,
  );
  await page.waitForSelector("#ai-resource-center", {
    state: "attached",
    timeout: 60000,
  });
  await page.evaluate(async () => {
    const now = Date.now();
    const a = {
      id: "arc-extension-fixture",
      site_name: "扩展隔离验收",
      site_url: "https://arc-extension-fixture.invalid",
      health: { status: "unknown" },
      site_type: "new-api",
      exchange_rate: 7,
      account_info: {
        id: "1",
        access_token: "fake-never-sent",
        username: "隔离验收",
        quota: 7,
        today_prompt_tokens: 0,
        today_completion_tokens: 0,
        today_quota_consumption: 0,
        today_requests_count: 0,
        today_income: 0,
      },
      last_sync_time: now,
      updated_at: now,
      user_updated_at: now,
      created_at: now,
      notes: "",
      tagIds: [],
      disabled: false,
      excludeFromTotalBalance: false,
      excludeFromTodayIncome: false,
      authType: "access_token",
      checkIn: {
        automaticExecutionEnabled: false,
        methodKnowledge: { methods: {} },
        selection: { mode: "automatic" },
      },
      configVersion: 7,
    };
    await chrome.storage.local.set({
      site_accounts: JSON.stringify({
        accounts: [a],
        bookmarks: [],
        pinnedAccountIds: [],
        orderedAccountIds: [a.id],
        deletedEntryRecords: [],
        last_updated: now,
      }),
    });
  });
  const section = page.locator("#ai-resource-center");
  await section.locator("button[role=switch]").click();
  await section.locator("#resource-center-url").fill(base);
  await section.locator("#resource-center-token").fill(access.allApiHubIngest);
  const buttons = section.locator("button");
  console.log("Extension settings buttons", await buttons.allTextContents());
  await section
    .locator("button")
    .filter({ hasText: /^保存$|^Save$/ })
    .click();
  await page.waitForFunction(async () => {
    const v = await chrome.storage.local.get("aiResourceCenterOutbox");
    const q =
      typeof v.aiResourceCenterOutbox === "string"
        ? JSON.parse(v.aiResourceCenterOutbox)
        : v.aiResourceCenterOutbox;
    return q?.events?.length === 1;
  });
  let block = true;
  await page.route("**/api/v1/ingest", (r) =>
    block ? r.abort() : r.continue(),
  );
  await section
    .locator("button")
    .filter({ hasText: /交付待交事件|Deliver/ })
    .click();
  await section.getByRole("alert").waitFor();
  const retained = await page.evaluate(async () => {
    const d = (await chrome.storage.local.get("aiResourceCenterOutbox"))
      .aiResourceCenterOutbox;
    return (typeof d === "string" ? JSON.parse(d) : d).events;
  });
  assert.equal(retained.length, 1);
  assert.ok(!JSON.stringify(retained).includes("fake-never-sent"));
  block = false;
  await section
    .locator("button")
    .filter({ hasText: /交付待交事件|Deliver/ })
    .click();
  await page.waitForFunction(async () => {
    const v = (await chrome.storage.local.get("aiResourceCenterOutbox"))
      .aiResourceCenterOutbox;
    const q = typeof v === "string" ? JSON.parse(v) : v;
    return q?.events?.length === 0 && q.lastAck;
  });
  const state = await api("state"),
    a = state.accounts.find((x) => x.sourceId === "arc-extension-fixture");
  assert.equal(a.balance, 7);
  writeFileSync(
    "/vol2/1000/Docker/ai-resource-center/extension-acceptance-cleanup.json",
    JSON.stringify({
      accountId: a.id,
      siteId: a.siteId,
      received: before.received.allApiHub,
    }),
    { mode: 0o600 },
  );
  const report = {
    passed: true,
    checks: [
      "compiled MV3 extension settings work",
      "account observation persists in the real Chrome outbox",
      "offline error keeps the event",
      "retry receives fn acknowledgement and removes only that event",
      "no login token appears in the event",
    ],
    accounts: 1,
  };
  writeFileSync(
    "artifacts/resource-center-extension.json",
    JSON.stringify(report, null, 2),
  );
  console.log(JSON.stringify(report));
} finally {
  await context.close();
  rmSync(profileDir, { recursive: true, force: true });
}
