import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { launch, session, urls } from "./browser.mjs";
const base = "http://192.168.31.201:18329",
  modelUrl = "http://arc-rp-model:4010/v1";
const password = readFileSync(
  "/vol2/1000/Docker/ai-resource-center/rp-call-acceptance/data/admin-password",
  "utf8",
).trim();
const login = await fetch(base + "/api/v1/session", {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({ password }),
});
const cookie = login.headers.get("set-cookie").split(";")[0];
const api = async (path, body) => {
  const r = await fetch(base + "/api/v1/" + path, {
    method: body ? "POST" : "GET",
    headers: { cookie, "content-type": "application/json" },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  const d = await r.json();
  if (!r.ok) throw Error(d.error);
  return d;
};
const channel = await api("channels", {
  site: { name: "RP calls fixture", url: modelUrl },
  name: "RP calls fixture",
  baseUrl: modelUrl,
  protocol: "OpenAI",
  models: ["fixture-normal", "fixture-rate", "fixture-slow"],
  category: "rp",
  enabled: true,
});
const token = (
  await api("access-tokens", { role: "rp", channelIds: [channel.id] })
).token;
await api("sources", {
  id: "sillytavern",
  name: "Isolated SillyTavern",
  kind: "sillytavern",
  url: urls.validation,
});
const browser = await launch();
let blocked = false,
  nativeRequests = 0;
try {
  const { page, context } = await session(browser, {
    helper: false,
    probe: false,
  });
  await page.route("**/api/settings/get", async (route) => {
    const r = await route.fetch(),
      d = await r.json(),
      s = JSON.parse(d.settings);
    s.firstRun = false;
    s.extension_settings.disabledExtensions = [
      ...(s.extension_settings.disabledExtensions || []),
      "third-party/JS-Slash-Runner",
      "third-party/workbench-probe",
      "third-party/ai-resource-center",
    ];
    delete s.extension_settings.aiResourceCenter;
    d.settings = JSON.stringify(s);
    await route.fulfill({ response: r, json: d });
  });
  await page.route("**/api/backends/**", (route) => {
    const req = route.request();
    if (new URL(req.url()).pathname.endsWith("/generate")) {
      const body = req.postDataJSON();
      assert.equal(body.custom_url, modelUrl);
      assert.match(body.model, /^fixture-/);
      nativeRequests++;
      return route.continue();
    }
    return route.fulfill({ json: {} });
  });
  await page.route("**/api/v1/rp/calls", (route) =>
    blocked ? route.abort() : route.continue(),
  );
  await page.route("**/arc-rp-capture.js", (route) =>
    route.fulfill({
      contentType: "application/javascript",
      body: readFileSync("extension-resource-center/index.js", "utf8"),
    }),
  );
  await page.goto(urls.validation, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(
    () => Number.isFinite(window.baselineMetrics?.appReadyMs),
    null,
    { timeout: 90000 },
  );
  await page.evaluate(
    ({ base, token, channelId, modelUrl }) => {
      const c = SillyTavern.getContext();
      c.extensionSettings.aiResourceCenter = {
        url: base,
        token,
        device: "fn:rp-call-test",
        bindings: { fixture: { channelId, version: 1, enabled: true } },
        outbox: [],
      };
      c.extensionSettings.connectionManager.selectedProfile = "fixture";
      Object.assign(c.chatCompletionSettings, {
        chat_completion_source: "custom",
        custom_url: modelUrl,
        custom_model: "fixture-normal",
        stream_openai: true,
        custom_include_body: "",
        custom_include_headers: "",
        custom_exclude_body: "",
      });
    },
    { base, token, channelId: channel.id, modelUrl },
  );
  await page.evaluate(() => import("/arc-rp-capture.js"));
  async function generate(model, stream, cancel = false) {
    return page.evaluate(
      async ({ model, stream, cancel }) => {
        const c = SillyTavern.getContext();
        c.chatCompletionSettings.custom_model = model;
        c.chatCompletionSettings.stream_openai = stream;
        const controller = new AbortController();
        let pieces = 0;
        try {
          const result = await (
            await import("/scripts/openai.js")
          ).sendOpenAIRequest(
            "normal",
            [{ role: "user", content: "ARC PRIVATE PROMPT" }],
            controller.signal,
          );
          if (typeof result === "function") {
            for await (const item of result()) {
              pieces++;
              if (cancel) controller.abort();
            }
          }
          return { ok: true, pieces };
        } catch (e) {
          return { ok: false, aborted: controller.signal.aborted };
        }
      },
      { model, stream, cancel },
    );
  }
  const normal = await generate("fixture-normal", true);
  assert.equal(normal.ok, true);
  assert.ok(normal.pieces > 0);
  const json = await generate("fixture-normal", false);
  assert.equal(json.ok, true);
  const rate = await generate("fixture-rate", false);
  assert.equal(rate.ok, false);
  const cancel = await generate("fixture-slow", true, true);
  assert.equal(cancel.aborted, true);
  await page.waitForFunction(
    () =>
      Object.keys(localStorage).filter((k) =>
        k.startsWith("arc-rp-calls:fn:rp-call-test:"),
      ).length === 0,
  );
  blocked = true;
  const offline = await generate("fixture-normal", true);
  assert.equal(offline.ok, true);
  await page.waitForFunction(() =>
    Object.keys(localStorage)
      .filter((k) => k.startsWith("arc-rp-calls:fn:rp-call-test:"))
      .some((k) => JSON.parse(localStorage[k]).event.result === "success"),
  );
  const retained = await page.evaluate(
    () =>
      Object.keys(localStorage).filter((k) =>
        k.startsWith("arc-rp-calls:fn:rp-call-test:"),
      ).length,
  );
  assert.equal(retained, 1);
  blocked = false;
  await page.locator("#extensions-settings-button .drawer-toggle").click();
  await page.locator("#ai-resource-center-rp .inline-drawer-toggle").click();
  await page.locator("#ai-resource-center-rp [data-action=calls]").click();
  await page.waitForFunction(
    () =>
      Object.keys(localStorage).filter((k) =>
        k.startsWith("arc-rp-calls:fn:rp-call-test:"),
      ).length === 0,
  );
  const calls = await api("calls?limit=100");
  assert.equal(calls.summary.total, 5);
  assert.equal(calls.summary.success, 3);
  assert.equal(calls.summary.failure, 1);
  assert.equal(calls.summary.cancelled, 1);
  assert.equal(calls.summary.pending, 0);
  assert.ok(calls.items.every((c) => c.channel_id === channel.id));
  assert.ok(!JSON.stringify(calls.items).includes("ARC PRIVATE PROMPT"));
  assert.equal(nativeRequests, 5);
  const report = {
    passed: true,
    scope: "isolated native SillyTavern and local model only",
    nativeRequests,
    records: calls.summary.total,
    results: {
      success: calls.summary.success,
      failure: calls.summary.failure,
      cancelled: calls.summary.cancelled,
      pending: calls.summary.pending,
    },
    usage: {
      input: calls.summary.inputTokens,
      output: calls.summary.outputTokens,
    },
    offlineRetained: retained,
    recovered: true,
    allAssociated: true,
    publicUpstreamRequests: 0,
  };
  writeFileSync(
    "artifacts/resource-center-calls.json",
    JSON.stringify(report, null, 2),
  );
  console.log(JSON.stringify(report));
} finally {
  await browser.close();
}
