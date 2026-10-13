import {
  launch,
  session,
  ready,
  urls,
  createCharacter,
  save,
} from "./browser.mjs";
const browser = await launch(),
  report = {
    checkedAt: new Date().toISOString(),
    methodology:
      "Same deterministic 400-message in-memory chat; native chat_truncation is unchanged; no chat save or model request. Three fresh browser sessions per configuration. Scroll means 60 requestAnimationFrame steps, not guaranteed FPS.",
    profiles: [],
  };
try {
  for (const enabled of [false, true]) {
    const samples = [];
    for (let i = 0; i < 3; i++) {
      const { page, context, errors } = await session(browser, {
        probe: enabled,
      });
      // Prevent temporary native settings and synthetic messages from reaching disk.
      await page.route("**/api/settings/save", (route) =>
        route.fulfill({ json: {} }),
      );
      await page.route("**/api/chats/save", (route) =>
        route.fulfill({ json: {} }),
      );
      await ready(page, urls.validation, { probe: enabled });
      await createCharacter(page);
      samples.push(
        await page.evaluate(async () => {
          const c = SillyTavern.getContext(),
            messages = Array.from({ length: 400 }, (_, i) => ({
              name: i % 2 ? "作者" : "WorkbenchFixture",
              is_user: !!(i % 2),
              is_system: false,
              send_date: "2026-10-07T00:00:00Z",
              mes:
                `## 第 ${i + 1} 段\n\n` +
                "潮声沿着旧码头传来，灯塔映在雨后的石板路上。".repeat(20),
              extra: {},
            }));
          const old = c.chat.slice();
          const before = performance.memory?.usedJSHeapSize ?? null;
          const start = performance.now();
          c.chat.splice(0, c.chat.length, ...messages);
          document.querySelector("#chat").replaceChildren();
          await c.printMessages();
          await c.eventSource.emit(c.eventTypes.CHAT_CHANGED, c.chatId);
          await new Promise((r) =>
            requestAnimationFrame(() => requestAnimationFrame(r)),
          );
          const renderMs = performance.now() - start,
            rendered = document.querySelectorAll("#chat .mes").length;
          const frames = [],
            chat = document.querySelector("#chat");
          let prev = performance.now();
          for (let f = 0; f < 60; f++) {
            await new Promise((r) => requestAnimationFrame(r));
            const now = performance.now();
            frames.push(now - prev);
            prev = now;
            chat.scrollTop = (chat.scrollHeight - chat.clientHeight) * (f / 59);
          }
          const after = performance.memory?.usedJSHeapSize ?? null;
          c.chat.splice(0, c.chat.length, ...old);
          return {
            renderMs,
            rendered,
            nativeTruncation: c.powerUserSettings.chat_truncation,
            maxScrollFrameMs: Math.max(...frames),
            meanScrollFrameMs:
              frames.reduce((a, b) => a + b, 0) / frames.length,
            heapDeltaBytes:
              before === null || after === null ? null : after - before,
          };
        }),
      );
      if (errors.length) throw new Error(errors.join("\n"));
      await context.close();
    }
    report.profiles.push({ workbench: enabled, samples });
    console.log(enabled ? "workbench" : "native", JSON.stringify(samples));
  }
  report.passed = true;
} catch (e) {
  report.passed = false;
  report.failure = e.stack;
  process.exitCode = 1;
  console.error(e);
} finally {
  save("workbench-chat-benchmark.json", report);
  await browser.close();
}
