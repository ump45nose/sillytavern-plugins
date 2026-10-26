// Large world books on the validation instance: opening, scrolling, selecting and typing in the settings
// workspace's entry table and the side-panel entry list, plus what one settings save re-renders.
// Books come from WB_BENCH_BOOKS (a folder of exported world-book JSON, e.g. a read-only copy of
// production) or, without it, one synthetic book shaped like the largest production book (3189 entries,
// ~3 KB each). Writes artifacts/benchmark-world-scale.json; compare runs before and after a change.
import fs from "node:fs";
import path from "node:path";
import { launch, session, ready, urls, createCharacter, openSettings, save } from "./browser.mjs";

const SYNTHETIC = 3189,
  KEYS = 30;
const folder = process.env.WB_BENCH_BOOKS;
const books = folder
  ? fs
      .readdirSync(folder)
      .filter((f) => f.endsWith(".json"))
      .map((f) => ({ name: "Bench·" + path.parse(f).name, data: JSON.parse(fs.readFileSync(path.join(folder, f), "utf8")) }))
  : [];
const stats = (samples) => {
  if (!samples.length) return { n: 0 };
  const sorted = [...samples].sort((a, b) => a - b),
    at = (q) => sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))];
  return {
    n: samples.length,
    mean: +(samples.reduce((a, b) => a + b, 0) / samples.length).toFixed(1),
    median: +at(0.5).toFixed(1),
    p95: +at(0.95).toFixed(1),
    max: +sorted.at(-1).toFixed(1),
  };
};
const browser = await launch(),
  report = { checkedAt: new Date().toISOString(), source: folder ? "WB_BENCH_BOOKS" : "synthetic" };
try {
  const { page, errors } = await session(browser);
  page.on("dialog", (d) => d.accept());
  await ready(page, urls.validation, { probe: true });
  await createCharacter(page);
  // Long tasks and slow input events, read per phase.
  await page.evaluate(() => {
    window.__bench = { long: [], events: [] };
    new PerformanceObserver((l) => l.getEntries().forEach((e) => __bench.long.push(e.duration))).observe({ type: "longtask", buffered: false });
    new PerformanceObserver((l) =>
      l.getEntries().forEach((e) => ["keydown", "keypress", "input", "beforeinput", "keyup", "click", "pointerup"].includes(e.name) && __bench.events.push(e.duration)),
    ).observe({ type: "event", durationThreshold: 16, buffered: false });
  });
  const phase = async (fn) => {
    await page.evaluate(() => {
      __bench.long.length = 0;
      __bench.events.length = 0;
    });
    const result = await fn();
    const { long, events } = await page.evaluate(() => ({ long: [...__bench.long], events: [...__bench.events] }));
    return { ...result, longTasks: { count: long.length, totalMs: +long.reduce((a, b) => a + b, 0).toFixed(0), maxMs: +Math.max(0, ...long).toFixed(0) }, slowEvents: stats(events) };
  };

  // Install the books (the largest one is measured).
  const installed = await page.evaluate(
    async ({ books, synthetic }) => {
      const c = SillyTavern.getContext(),
        headers = c.getRequestHeaders();
      if (!books.length) {
        const entries = {};
        for (let i = 0; i < synthetic; i++)
          entries[i] = {
            uid: i,
            key: [`关键词${i}`, `别名${i}`],
            keysecondary: [],
            comment: `条目 ${i} · ${["人物", "地点", "势力", "物品"][i % 4]}`,
            content: `第 ${i} 条：潮声沿着旧码头传来，灯塔映在雨后的石板路上。`.repeat(36),
            constant: i % 7 === 0,
            selective: true,
            order: i,
            position: i % 5,
            disable: i % 11 === 0,
            depth: 4,
            probability: 100,
            useProbability: true,
          };
        books = [{ name: "Bench·Synthetic", data: { entries } }];
      }
      for (const b of books)
        await fetch("/api/worldinfo/edit", { method: "POST", headers, body: JSON.stringify({ name: b.name, data: b.data }) });
      await c.updateWorldInfoList();
      workbench.host.invalidate("resources");
      return books.map((b) => ({ name: b.name, entries: Object.keys(b.data.entries ?? {}).length, mb: +(JSON.stringify(b.data).length / 1048576).toFixed(1) }));
    },
    { books, synthetic: SYNTHETIC },
  );
  installed.sort((a, b) => b.entries - a.entries);
  const target = installed[0];
  report.books = installed;
  report.target = target;
  const tokenCalls = [];
  page.on("request", (r) => r.url().includes("/api/tokenizers/") && tokenCalls.push(r.url()));
  const frames = (n = 2) => page.evaluate((n) => new Promise((r) => { let i = 0; const f = () => (++i >= n ? r() : requestAnimationFrame(f)); requestAnimationFrame(f); }), n);

  // 1. Settings workspace: open the book in the entry table.
  await openSettings(page, "世界书");
  const ws = page.getByRole("dialog", { name: "独立设置工作区", exact: true });
  report.managerOpen = await phase(async () => {
    tokenCalls.length = 0;
    const start = Date.now();
    await ws.getByRole("button", { name: "编辑 " + target.name, exact: true }).click();
    await ws.locator(".wb-wt-row:not(.is-head)").nth(1).waitFor({ timeout: 120_000 });
    await frames();
    const ms = Date.now() - start;
    await page.waitForTimeout(3000);
    return {
      ms,
      rows: await ws.locator(".wb-wt-row:not(.is-head)").count(),
      nodes: await page.evaluate(() => document.querySelector(".wb-world.is-deep")?.querySelectorAll("*").length ?? 0),
      tokenRequests3s: tokenCalls.length,
    };
  });

  // 2. Scrolling the table from top to bottom, one step per frame.
  report.managerScroll = await phase(async () => {
    const deltas = await page.evaluate(async () => {
      const row = document.querySelector(".wb-wt-row:not(.is-head)");
      let box = row?.parentElement;
      while (box && !(box.scrollHeight > box.clientHeight + 4 && /auto|scroll/.test(getComputedStyle(box).overflowY))) box = box.parentElement;
      if (!box) return { error: "no scroll container" };
      box.scrollTop = 0;
      const out = [],
        step = Math.max(120, Math.ceil((box.scrollHeight - box.clientHeight) / 240));
      let last = performance.now();
      while (box.scrollTop + box.clientHeight < box.scrollHeight - 2) {
        box.scrollTop += step;
        await new Promise((r) => requestAnimationFrame(r));
        const now = performance.now();
        out.push(now - last);
        last = now;
      }
      return { frames: out, scrollHeight: box.scrollHeight };
    });
    return deltas.error ? deltas : { scrollHeight: deltas.scrollHeight, frameMs: stats(deltas.frames) };
  });

  // 3. Selecting an entry (scrolls back to the top first) and typing into its text.
  report.managerSelect = await phase(async () => {
    await page.evaluate(() => {
      const row = document.querySelector(".wb-wt-row:not(.is-head)");
      let box = row?.parentElement;
      while (box && !(box.scrollHeight > box.clientHeight + 4)) box = box.parentElement;
      if (box) box.scrollTop = 0;
    });
    await frames();
    const start = Date.now();
    await ws.locator(".wb-wt-row:not(.is-head)").nth(3).locator(".wb-wt-open").click();
    await ws.getByLabel("世界书正文").first().waitFor();
    await frames();
    return { ms: Date.now() - start };
  });
  report.managerTyping = await phase(async () => {
    const field = ws.getByLabel("世界书正文").first();
    await field.click();
    await page.keyboard.press("End");
    const start = Date.now();
    for (let i = 0; i < KEYS; i++) await page.keyboard.type("字", { delay: 0 });
    await frames();
    return { keys: KEYS, wallMs: Date.now() - start };
  });
  // 4. One settings save (SETTINGS_UPDATED) while the table is open.
  report.managerSettingsSave = await phase(async () => {
    const ms = await page.evaluate(async () => {
      const c = SillyTavern.getContext(),
        frame = () => new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0)));
      const versions = () => Object.values(workbench.host.sliceVersions).reduce((a, b) => a + b, 0);
      const samples = [],
        sync = [],
        before = versions();
      for (let i = 0; i < 5; i++) {
        const start = performance.now();
        const emitted = c.eventSource.emit(c.eventTypes.SETTINGS_UPDATED);
        sync.push(performance.now() - start);
        await emitted;
        await frame();
        samples.push(performance.now() - start);
      }
      return { samples, sync, notified: versions() - before };
    });
    return { emitToFrameMs: stats(ms.samples), syncMs: stats(ms.sync), sliceNotifications: ms.notified };
  });
  // Leave without saving the typed text.
  const revert = ws.getByRole("button", { name: "还原", exact: true });
  if (await revert.isVisible().catch(() => false)) await revert.click();
  await ws.getByRole("button", { name: "返回工作台", exact: true }).first().click();
  await ws.waitFor({ state: "hidden" });
  await page.waitForTimeout(500);

  // 5. Side panel: the same book in the entry list.
  await page.keyboard.press("Alt+Shift+Digit3");
  await page.waitForTimeout(500);
  report.panelOpen = await phase(async () => {
    tokenCalls.length = 0;
    const start = Date.now();
    await page.locator("#wb-resource-rail .wb-rail-open").filter({ hasText: new RegExp("^" + target.name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "$") }).click();
    await page.locator(".wb-entries .wb-entry").nth(1).waitFor({ timeout: 120_000 });
    await frames();
    const ms = Date.now() - start;
    await page.waitForTimeout(1500);
    return {
      ms,
      rows: await page.locator(".wb-entries .wb-entry").count(),
      nodes: await page.evaluate(() => document.querySelector(".wb-world-panel")?.querySelectorAll("*").length ?? 0),
    };
  });
  report.panelSettingsSave = await phase(async () => {
    const ms = await page.evaluate(async () => {
      const c = SillyTavern.getContext(),
        frame = () => new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0)));
      const versions = () => Object.values(workbench.host.sliceVersions).reduce((a, b) => a + b, 0);
      const samples = [],
        sync = [],
        before = versions();
      for (let i = 0; i < 5; i++) {
        const start = performance.now();
        const emitted = c.eventSource.emit(c.eventTypes.SETTINGS_UPDATED);
        sync.push(performance.now() - start);
        await emitted;
        await frame();
        samples.push(performance.now() - start);
      }
      return { samples, sync, notified: versions() - before };
    });
    return { emitToFrameMs: stats(ms.samples), syncMs: stats(ms.sync), sliceNotifications: ms.notified };
  });

  // Clean up the benchmark books.
  await page.evaluate(async (names) => {
    const c = SillyTavern.getContext();
    for (const name of names)
      await fetch("/api/worldinfo/delete", { method: "POST", headers: c.getRequestHeaders(), body: JSON.stringify({ name }) });
    await c.updateWorldInfoList();
  }, installed.map((b) => b.name));
  report.pageErrors = errors;
} catch (error) {
  report.error = String(error?.message ?? error).split("\n")[0];
  process.exitCode = 1;
} finally {
  save("benchmark-world-scale.json", report);
  console.log(JSON.stringify(report, null, 2));
  await browser.close();
}
