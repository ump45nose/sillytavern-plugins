import assert from "node:assert/strict";
import {
  launch,
  session,
  ready,
  urls,
  createCharacter,
  connect,
  selectPaper,
  save,
  artifacts,
} from "./browser.mjs";
const browser = await launch(),
  report = { checkedAt: new Date().toISOString(), checks: [] };
const check = (name, details = {}) => {
  report.checks.push({ name, passed: true, details });
  console.log("PASS", name);
};
try {
  const { page, errors } = await session(browser);
  page.on("dialog", (d) => d.accept());
  await ready(page, urls.validation, { probe: true });
  await createCharacter(page);
  await connect(page);
  await page.evaluate(async () => {
    const c = SillyTavern.getContext(),
      wi = await import("/scripts/world-info.js");
    const data = { entries: {}, vendor_book_field: { keep: true } };
    const e = wi.createWorldInfoEntry("WorkbenchFixtureWorld", data);
    Object.assign(e, {
      key: ["wb_lore"],
      comment: "灯塔",
      content: "WB_LORE_CONTENT：灯塔位于北岸。",
      disable: false,
      constant: false,
      vectorized: false,
      vendor_field: { keep: "unknown" },
    });
    const e2 = wi.createWorldInfoEntry("WorkbenchFixtureWorld", data);
    Object.assign(e2, {
      key: ["雨季"],
      comment: "雨季",
      content: "雨季持续到秋末。",
      disable: true,
    });
    await c.saveWorldInfo("WorkbenchFixtureWorld", data, true);
    await c.updateWorldInfoList();
    await workbench.host.toggleBook("WorkbenchFixtureWorld", true);
    workbench.host.refresh();
    if (!wi.selected_world_info.includes("WorkbenchFixtureWorld"))
      throw new Error("World enable did not reach native state");
  });
  await page.keyboard.press("Alt+Shift+Digit3");
  await page
    .locator(".wb-book-row button")
    .filter({ hasText: "WorkbenchFixtureWorld" })
    .click();
  await page.getByLabel("灯塔 激活方式").waitFor();
  await selectPaper(page, "灯塔 激活方式", "constant");
  assert.equal(await page.getByLabel("启用条目 灯塔").isChecked(), true);
  await page.getByLabel("世界书正文").fill("WB_LORE_CONTENT：新版灯塔。");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await page.getByText("已保存", { exact: true }).waitFor();
  const book = await page.evaluate(() =>
    workbench.host.readBook("WorkbenchFixtureWorld"),
  );
  assert.equal(book.entries[0].constant, true);
  assert.equal(book.entries[0].disable, false);
  assert.equal(book.entries[0].content, "WB_LORE_CONTENT：新版灯塔。");
  assert.deepEqual(book.entries[0].vendor_field, { keep: "unknown" });
  assert.deepEqual(book.vendor_book_field, { keep: true });
  check(
    "world sidebar edits activation separately from enabled state; unknown fields survive real save",
  );
  await page.getByRole("button", { name: "深度编辑", exact: true }).click();
  await page.getByRole("dialog").waitFor();
  await page.getByRole("dialog").getByRole("button", { name: "触发条件", exact: true }).click();
  const activationMenu = page.getByRole("dialog").getByRole("combobox", { name: "激活方式", exact: true });
  await activationMenu.click();
  await page.getByRole("listbox", { name: "激活方式", exact: true }).waitFor();
  await activationMenu.press("Escape");
  assert.equal(await page.getByRole("listbox", { name: "激活方式", exact: true }).count(), 0);
  assert(await page.getByRole("dialog").isVisible());
  await page.getByRole("dialog").getByRole("button", { name: "正文", exact: true }).click();
  assert.equal(
    await page.locator(".wb-world.is-deep .wb-book-column").count(),
    1,
  );
  await page.getByLabel("世界书正文").fill("这份失败草稿不能丢失");
  await page.route("**/api/worldinfo/edit", (r) =>
    r.fulfill({ status: 500, body: "fixture failure" }),
  );
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await page.getByRole("alert").filter({ hasText: "HTTP 500" }).waitFor();
  assert.equal(
    await page.getByLabel("世界书正文").inputValue(),
    "这份失败草稿不能丢失",
  );
  await page.unroute("**/api/worldinfo/edit");
  check("HTTP save failure keeps worldbook draft and reports an error");
  await page.getByLabel("世界书正文").fill("WB_LORE_CONTENT：灯塔保存恢复。");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await page.getByText("已保存", { exact: true }).waitFor();
  await page.screenshot({ path: artifacts + "/noval-world-editor.png" });
  await page.getByRole("button", { name: "返回工作台", exact: true }).click();
  await page
    .getByRole("button", { name: "角色与资源侧栏", exact: true })
    .click();
  await page.getByRole("button", { name: "当前角色", exact: true }).click();
  await page.getByLabel("角色描述", { exact: true }).waitFor();
  await page
    .getByLabel("角色描述", { exact: true })
    .fill("首版编辑验证：**Markdown** <xml>保留</xml> {{char}} " + Date.now());
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await page.getByText("已保存", { exact: true }).waitFor();
  const character = await page.evaluate(async () => {
    const id = workbench.host.snapshot().character.id;
    return workbench.host.characterData(id);
  });
  assert.match(character.data.description, /首版编辑验证/);
  check(
    "character editor saves through official merge endpoint without rewriting raw Markdown/XML",
  );
  await page.getByRole("button", { name: "全部角色", exact: true }).click();
  const star = page.getByRole("button", {
    name: "收藏 WorkbenchFixture",
    exact: true,
  });
  if (await star.count()) await star.click();
  await page
    .locator(".wb-favorites button")
    .filter({ hasText: "WorkbenchFixture" })
    .waitFor();
  await page.getByRole("button", { name: "独立管理", exact: true }).click();
  await page.locator(".wb-card-grid").waitFor();
  await page.getByLabel("搜索角色或标签").fill("WorkbenchFixture");
  assert.equal(
    await page.locator(".wb-card-grid .wb-character-card").count(),
    1,
  );
  await page.screenshot({ path: artifacts + "/noval-character-library.png" });
  await page.getByRole("button", { name: "返回工作台", exact: true }).click();
  check(
    "character favorites, search and independent management operate on host characters",
  );
  const resources = await page.evaluate(async () => {
    const h = workbench.host,
      c = SillyTavern.getContext(),
      manager = c.getPresetManager();
    const current = manager.getSelectedPresetName(),
      preset = h.presetData(current);
    preset.vendor_extension = { keep: "yes" };
    await manager.savePreset("WorkbenchFixturePreset", preset);
    h.refresh();
    const base = h.presetData("WorkbenchFixturePreset");
    await h.savePreset("WorkbenchFixturePreset", base, {
      ...base,
      temperature: 0.77,
    });
    assertLocal(
      h.presetData("WorkbenchFixturePreset").vendor_extension.keep === "yes",
      "preset lost extension",
    );
    const cm = c.extensionSettings.connectionManager;
    for (const [id, name] of [
      ["wb-test-1", "Workbench Test A"],
      ["wb-test-2", "Workbench Test B"],
    ]) {
      if (!cm.profiles.some((p) => p.id === id))
        cm.profiles.push({
          id,
          name,
          mode: "cc",
          api: "custom",
          model: "workbench-fixture",
          "api-url": "http://mock-model:4010/v1",
        });
      if (
        ![...document.querySelector("#connection_profiles").options].some(
          (x) => x.value === id,
        )
      )
        document
          .querySelector("#connection_profiles")
          .add(new Option(name, id));
    }
    h.preference({
      bindings: { "connection:wb-test-2": "WorkbenchFixturePreset" },
    });
    h.refresh();
    await h.select("connection", "wb-test-2");
    const bound = c.getPresetManager().getSelectedPresetName();
    const persona = h.snapshot().resources.persona[0];
    if (!persona) throw new Error("fixture persona absent");
    const personaBase = h.personaData(persona.id);
    await h.savePersona(persona.id, personaBase, {
      ...personaBase,
      description: "作者身份验证 {{user}}",
    });
    await h.select("persona", persona.id);
    return {
      bound,
      persona: h.personaData(persona.id).description,
      presetUnknown: h.presetData("WorkbenchFixturePreset").vendor_extension,
    };
    function assertLocal(v, message) {
      if (!v) throw new Error(message);
    }
  });
  assert.equal(resources.bound, "WorkbenchFixturePreset");
  assert.equal(resources.persona, "作者身份验证 {{user}}");
  assert.deepEqual(resources.presetUnknown, { keep: "yes" });
  check(
    "real preset save, profile application with binding and Persona editing",
    resources,
  );
  await page.getByRole("button", { name: "下一个连接", exact: true }).click();
  await page.waitForFunction(
    () => workbench.host.snapshot().current.connection === "wb-test-1",
  );
  check("next-connection button uses official connection manager");
  await page.keyboard.press("Alt+Shift+Digit2");
  await page.locator(".wb-resources").waitFor();
  await page.getByRole("button", { name: "独立深度编辑", exact: true }).click();
  await page.getByLabel("预设 JSON").waitFor();
  await page.getByRole("button", { name: "原生高级设置", exact: true }).click();
  await page.waitForFunction(() =>
    document.body.classList.contains("wb-native-panel"),
  );
  assert.equal(await page.getByRole("dialog").count(), 0);
  await page.getByRole("button", { name: "收起原生面板" }).click();
  await page.getByRole("dialog").waitFor();
  check(
    "independent editor suspends and resumes around native advanced settings",
  );
  await page.getByRole("button", { name: "返回工作台", exact: true }).click();
  await page
    .locator("#send_textarea")
    .fill("**编辑草稿**\n<xml>{{char}}</xml>");
  await page.getByRole("separator", { name: "调整输入框高度" }).press("End");
  assert.equal(
    await page.locator("#send_textarea").inputValue(),
    "**编辑草稿**\n<xml>{{char}}</xml>",
  );
  await page.getByRole("separator", { name: "调整输入框高度" }).press("Home");
  for (const [width, height] of [
    [1366, 768],
    [1440, 900],
    [1920, 1080],
  ]) {
    await page.setViewportSize({ width, height });
    await page.waitForTimeout(300);
    const geometry = await page.evaluate(() => {
      const r = (s) => {
        const e = document.querySelector(s),
          b = e.getBoundingClientRect();
        return {
          x: b.x,
          y: b.y,
          right: b.right,
          bottom: b.bottom,
          w: b.width,
          h: b.height,
        };
      };
      return {
        input: r("#send_textarea"),
        send: r("#send_but"),
        tools: r(".wb-composer-actions"),
        chat: r("#chat"),
        overflow: document.documentElement.scrollWidth > innerWidth,
      };
    });
    assert.equal(geometry.overflow, false);
    assert(geometry.input.x >= 0 && geometry.input.right <= width);
    assert(geometry.send.bottom <= height);
    assert(geometry.tools.y >= geometry.input.bottom - 2);
    assert(geometry.chat.bottom <= geometry.input.y);
    await page.screenshot({ path: `${artifacts}/noval-${width}.png` });
  }
  check(
    "three desktop resolutions keep reading, input and controls separate; resizing preserves draft",
  );
  await page.setViewportSize({ width: 1440, height: 900 });
  // Applying a fixture preset can restore its saved provider. Trace always uses
  // the isolated deterministic model, independent of that earlier preset test.
  await connect(page);
  await page.evaluate(() => workbench.clear());
  await page.locator("#send_textarea").fill("wb_lore 首版 Trace 验证");
  await page.locator("#send_but").click();
  await page.waitForFunction(
    () =>
      workbench.records.length &&
      workbench.records.at(-1).status === 200 &&
      !SillyTavern.getContext().streamingProcessor,
  );
  await page
    .getByRole("button", { name: "Trace", exact: true })
    .first()
    .click();
  await page.locator(".wb-trace").waitFor();
  await page.getByRole("button", { name: "查看完整 Prompt" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "世界书", exact: true }).click();
  await page
    .locator(".wb-trace-body")
    .getByText("WB_LORE_CONTENT：灯塔保存恢复。", { exact: true })
    .waitFor();
  await page.screenshot({ path: artifacts + "/noval-trace.png" });
  await page.getByRole("button", { name: "返回工作台", exact: true }).click();
  check("Trace displays real request and world-info activation");
  // A no-reparenting guarantee protects third-party message iframe identity.
  const identity = await page.evaluate(async () => {
    const chat = document.querySelector("#chat"),
      input = document.querySelector("#send_textarea"),
      parent = chat.parentNode;
    input.value = "**原文** <x>{{user}}</x>";
    input.setSelectionRange(2, 5);
    const count = () =>
      Object.values(SillyTavern.getContext().eventSource.events).reduce(
        (n, x) => n + x.length,
        0,
      );
    const before = count();
    for (let i = 0; i < 5; i++) {
      workbench.unmount();
      await workbench.mount();
      await new Promise((r) => setTimeout(r, 30));
    }
    return {
      chat: chat === document.querySelector("#chat"),
      parent: chat.parentNode === parent,
      input: input === document.querySelector("#send_textarea"),
      draft: input.value,
      range: [input.selectionStart, input.selectionEnd],
      before,
      after: count(),
    };
  });
  assert.equal(identity.chat && identity.parent && identity.input, true);
  assert.equal(identity.draft, "**原文** <x>{{user}}</x>");
  assert.deepEqual(identity.range, [2, 5]);
  assert.equal(identity.before, identity.after);
  check(
    "repeated mounting preserves nodes, parent, draft, selection and listener count",
    identity,
  );
  assert.deepEqual(errors, []);
  check("no uncaught page errors");
  report.passed = true;
} catch (error) {
  report.passed = false;
  report.failure = error.stack;
  console.error(error);
  process.exitCode = 1;
} finally {
  save("workbench-verification.json", report);
  await browser.close();
}
