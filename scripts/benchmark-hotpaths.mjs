// Hot-path costs on the validation instance: world-book typing, bulk tagging, chat-index rebuilds and
// preset editor renders. Writes artifacts/benchmark-hotpaths.json; compare runs before and after a change.
import { launch, session, ready, urls, createCharacter, connect, openSettings, save } from "./browser.mjs";

const ENTRIES = 600,
  KEYS = 60,
  TAGGED = 8,
  MESSAGES = 400;
const stats = (samples) => {
  const sorted = [...samples].sort((a, b) => a - b),
    at = (q) => sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))];
  return {
    n: samples.length,
    mean: +(samples.reduce((a, b) => a + b, 0) / samples.length).toFixed(2),
    median: +at(0.5).toFixed(2),
    p95: +at(0.95).toFixed(2),
  };
};
const browser = await launch(),
  report = { checkedAt: new Date().toISOString(), entries: ENTRIES, keys: KEYS };
try {
  const { page, errors } = await session(browser);
  page.on("dialog", (d) => d.accept());
  await ready(page, urls.validation, { probe: true });
  await createCharacter(page);
  await connect(page);

  // 1. Typing into one entry of a large book. Each keystroke is a real input event; the time is the
  // synchronous React update it triggers (render, commit and effects of a discrete event).
  await page.evaluate(async (count) => {
    const c = SillyTavern.getContext(),
      wi = await import("/scripts/world-info.js"),
      data = { entries: {} };
    for (let i = 0; i < count; i++)
      Object.assign(wi.createWorldInfoEntry("BenchHotpathWorld", data), {
        key: [`bench_${i}`, `键${i}`],
        comment: `条目 ${i}`,
        content: `第 ${i} 条：潮声沿着旧码头传来，灯塔映在雨后的石板路上。`.repeat(8),
      });
    await c.saveWorldInfo("BenchHotpathWorld", data, true);
    await c.updateWorldInfoList();
    workbench.host.refresh();
  }, ENTRIES);
  await page.keyboard.press("Alt+Shift+Digit3");
  await page
    .locator("#wb-resource-rail .wb-rail-open")
    .filter({ hasText: /^BenchHotpathWorld$/ })
    .click();
  await page.getByRole("button", { name: "编辑条目 条目 0", exact: true }).click();
  await page.getByLabel("世界书正文").waitFor();
  const reads = [];
  page.on("request", (r) => r.url().includes("/api/worldinfo/get") && reads.push(r.url()));
  report.worldTyping = stats(
    await page.evaluate(async (keys) => {
      const node = document.querySelector('textarea[aria-label="世界书正文"]'),
        setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set,
        samples = [];
      for (let i = 0; i < keys; i++) {
        const start = performance.now();
        setter.call(node, node.value + "字");
        node.dispatchEvent(new Event("input", { bubbles: true }));
        samples.push(performance.now() - start);
        await new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0)));
      }
      return samples;
    }, KEYS),
  );
  reads.length = 0;
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await page.getByText("已保存", { exact: true }).waitFor();
  await page.waitForTimeout(500);
  report.worldSaveReads = reads.length;

  // 2. Tagging several characters at once: requests and wall time.
  const ids = await page.evaluate(async (n) => {
    const out = [];
    for (let i = 0; i < n; i++) out.push(await workbench.host.createCharacter(`BenchTag ${Date.now()} ${i}`));
    return out;
  }, TAGGED);
  const calls = [];
  const track = (r) => r.url().includes("/api/characters/") && calls.push(new URL(r.url()).pathname);
  page.on("request", track);
  const tagMs = await page.evaluate(async (ids) => {
    const start = performance.now();
    await workbench.host.tagCharacters(ids, "bench-tag");
    return performance.now() - start;
  }, ids);
  page.off("request", track);
  const tags = await page.evaluate(
    (ids) =>
      ids.every((id) =>
        SillyTavern.getContext()
          .characters.find((x) => x.avatar === id)
          ?.data?.tags?.includes("bench-tag"),
      ),
    ids,
  );
  report.tagCharacters = {
    characters: TAGGED,
    ms: +tagMs.toFixed(1),
    requests: calls.reduce((a, p) => ({ ...a, [p]: (a[p] ?? 0) + 1 }), {}),
    total: calls.length,
    tagged: tags,
  };

  // 3. Chat-index rebuilds caused by resource actions and settings saves on a long in-memory chat.
  await page.route("**/api/chats/save", (route) => route.fulfill({ json: {} }));
  report.chatRebuilds = await page.evaluate(async (count) => {
    const c = SillyTavern.getContext(),
      host = workbench.host;
    c.chat.splice(
      0,
      c.chat.length,
      ...Array.from({ length: count }, (_, i) => ({
        name: i % 2 ? "作者" : "WorkbenchFixture",
        is_user: !!(i % 2),
        is_system: false,
        send_date: "2026-10-07T00:00:00Z",
        mes: `## 第 ${i + 1} 段\n\n` + "<b>潮声</b>沿着旧码头传来，灯塔映在雨后的石板路上。".repeat(20),
        extra: {},
      })),
    );
    host.invalidate("chat");
    host.slice("chat");
    const frame = () => new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0)));
    await frame();
    let start = performance.now();
    for (let i = 0; i < 20; i++) {
      host.invalidate("chat");
      host.slice("chat");
    }
    const rebuildMs = (performance.now() - start) / 20;
    const before = host.sliceVersions.chat;
    start = performance.now();
    for (let i = 0; i < 3; i++) {
      await host.toggleBook("BenchHotpathWorld", true);
      await frame();
      await host.toggleBook("BenchHotpathWorld", false);
      await frame();
      await (await import("/script.js")).saveSettings();
      await frame();
    }
    return {
      messages: count,
      oneRebuildMs: +rebuildMs.toFixed(2),
      actions: 9,
      chatInvalidations: host.sliceVersions.chat - before,
      actionsMs: +(performance.now() - start).toFixed(1),
    };
  }, MESSAGES);
  await page.unroute("**/api/chats/save");

  // 4. Preset editor: how often one render reads the whole preset.
  await openSettings(page, "预设");
  const preset = await page.evaluate(() => SillyTavern.getContext().getPresetManager().getSelectedPresetName());
  const ws = page.getByRole("dialog", { name: "独立设置工作区", exact: true });
  await ws.getByRole("button", { name: "编辑 " + preset, exact: true }).click();
  await page.waitForTimeout(300);
  report.presetRender = await page.evaluate(async () => {
    const host = workbench.host,
      counts = { presetData: 0, livePreset: 0 },
      original = { presetData: host.presetData, livePreset: host.livePreset };
    host.presetData = function (...args) {
      counts.presetData++;
      return original.presetData.apply(this, args);
    };
    host.livePreset = function (...args) {
      counts.livePreset++;
      return original.livePreset.apply(this, args);
    };
    const frame = () => new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0)));
    const start = performance.now();
    for (let i = 0; i < 20; i++) {
      host.invalidate("session");
      await frame();
    }
    const ms = performance.now() - start;
    delete host.presetData;
    delete host.livePreset;
    return {
      renders: 20,
      presetDataPerRender: counts.presetData / 20,
      livePresetPerRender: counts.livePreset / 20,
      msPerRender: +(ms / 20).toFixed(2),
    };
  });
  report.pageErrors = errors;
  save("benchmark-hotpaths.json", report);
  console.log(JSON.stringify(report, null, 2));
} finally {
  await browser.close();
}
