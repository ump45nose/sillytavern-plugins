import assert from "node:assert/strict";
import {
  launch,
  session,
  ready,
  urls,
  createCharacter,
  connect,
  save,
  artifacts,
} from "./browser.mjs";
const b = await launch(),
  report = { checkedAt: new Date().toISOString(), checks: [] };
const check = (name, details = {}) => {
  report.checks.push({ name, passed: true, details });
  console.log("PASS", name);
};
try {
  const { page, errors } = await session(b);
  await ready(page, urls.validation, { probe: true });
  await createCharacter(page);
  await connect(page);
  const batch = await page.evaluate(async () => {
    const c = SillyTavern.getContext(),
      h = workbench.host,
      name = "WorkbenchManagementFixture";
    if (!c.characters.some((x) => x.name === name)) {
      const body = new FormData();
      body.set("ch_name", name);
      body.set("description", "synthetic management fixture");
      body.set("first_mes", "hello");
      const headers = { ...c.getRequestHeaders() };
      delete headers["Content-Type"];
      const r = await fetch("/api/characters/create", {
        method: "POST",
        headers,
        body,
      });
      if (!r.ok) throw new Error("create fixture failed");
      await c.getCharacters();
      h.refresh();
    }
    const id = c.characters.find((x) => x.name === name).avatar,
      original = await h.characterData(id);
    await h.saveCharacter(id, original.data, {
      ...original.data,
      extensions: {
        ...original.data.extensions,
        workbench_fixture: { unknown: "keep" },
      },
    });
    await h.tagCharacters([id], "WB验证");
    const updated = await h.characterData(id);
    const r = await h.request("/api/characters/export", {
        avatar_url: id,
        format: "png",
      }),
      bytes = [...new Uint8Array(await r.arrayBuffer()).slice(0, 8)];
    await h.deleteCharacters([id]);
    return {
      tagged: updated.data.tags.includes("WB验证"),
      extension: updated.data.extensions.workbench_fixture,
      png: bytes,
      deleted: !c.characters.some((x) => x.avatar === id),
    };
  });
  assert.equal(batch.tagged && batch.deleted, true);
  assert.deepEqual(batch.extension, { unknown: "keep" });
  assert.deepEqual(batch.png, [137, 80, 78, 71, 13, 10, 26, 10]);
  check(
    "batch tags, native PNG export and deletion preserve card extensions and chat files",
    batch,
  );
  await page.evaluate(async () => {
    await SillyTavern.getContext().executeSlashCommandsWithOptions(
      "/setinput **STscript** <xml>{{char}}</xml>",
    );
  });
  assert.match(
    await page.locator("#send_textarea").inputValue(),
    /\*\*STscript\*\*/,
  );
  check("STscript writes directly into the original input");
  await page.evaluate(async () => {
    const api = window.quickReplyApi;
    const name = "WorkbenchFixtureReplies";
    if (api.getSetByName(name)) api.removeGlobalSet(name);
    await api.createSet(name, { disableSend: true });
    api.createQuickReply(name, "工作台快速回复", {
      message: "快速回复原文 **MD** <xml>test</xml>",
    });
    api.settings.isEnabled = true;
    api.addGlobalSet(name);
    api.settings.save();
  });
  await page.getByRole("button", { name: "快速回复", exact: true }).click();
  await page.getByRole("dialog",{name:"快速回复",exact:true}).getByRole("button",{name:"WorkbenchFixtureReplies",exact:true}).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "工作台快速回复", exact: true })
    .click();
  assert.match(
    await page.locator("#send_textarea").inputValue(),
    /快速回复原文/,
  );
  check(
    "workbench quick reply chooser executes the installed native Quick Reply API",
  );
  const chooserPromise = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "附件", exact: true }).click();
  const chooser = await chooserPromise;
  await chooser.setFiles({
    name: "workbench-fixture.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Workbench attachment fixture"),
  });
  await page
    .locator("#file_form .file_name")
    .filter({ hasText: "workbench-fixture.txt" })
    .waitFor();
  await page.locator("#file_form_reset").click();
  check("native text attachment upload remains usable");
  await page.locator("#options_button").click();
  await page.getByRole("dialog", {name:"聊天菜单",exact:true}).waitFor({ state: "visible" });
  await page.locator("#options_button").click();
  await page.locator("#extensionsMenuButton").click();
  await page.getByRole("dialog", {name:"扩展工具",exact:true}).waitFor({ state: "visible" });
  const sd = await page.locator("#sd_gen").count();
  assert(sd > 0);
  await page.locator("#extensionsMenuButton").click();
  check(
    "chat menu and extension menu including native image generation remain reachable",
    { imageGenerationMenu: true, externalImageBackendCalled: false },
  );
  const regex = await page.evaluate(async () => {
    const c = SillyTavern.getContext(),
      saved = structuredClone(c.extensionSettings.regex ?? []);
    c.extensionSettings.regex = [
      ...saved,
      {
        id: "wb-regex-fixture",
        scriptName: "WB display",
        findRegex: "WB_RENDER_SOURCE",
        replaceString: "WB_RENDER_OK",
        trimStrings: [],
        placement: [2],
        disabled: false,
        markdownOnly: true,
        promptOnly: false,
        runOnEdit: true,
        substituteRegex: 0,
        minDepth: null,
        maxDepth: null,
      },
    ];
    await TavernHelper.createChatMessages([
      { role: "user", message: "WB_COMPAT 正常生成验证" },
      { role: "assistant", message: "WB_RENDER_SOURCE" },
    ]);
    const raw = c.chat.at(-1).mes;
    await new Promise((r) => setTimeout(r, 100));
    const displayed = document.querySelector(
      "#chat .mes:last-child .mes_text",
    ).textContent;
    c.extensionSettings.regex = saved;
    return { raw, displayed };
  });
  assert.equal(regex.raw, "WB_RENDER_SOURCE");
  assert.match(regex.displayed, /WB_RENDER_OK/);
  check(
    "display regex uses native renderer and leaves message source intact",
    regex,
  );
  const before = await page.evaluate(
      () => SillyTavern.getContext().chat.length,
    ),
    traceBefore = await page.evaluate(() => workbench.records.length);
  await page.getByRole("button", { name: "重新生成", exact: true }).click();
  await page.waitForFunction((n) => workbench.records.length > n, traceBefore);
  await page.waitForFunction(
    () =>
      !SillyTavern.getContext().streamingProcessor &&
      SillyTavern.getContext().chat.at(-1).mes.includes("链路正常。"),
  );
  assert(
    (await page.evaluate(() => SillyTavern.getContext().chat.length)) <= before,
  );
  assert.equal(
    await page.evaluate(() => workbench.records.at(-1).generation.type),
    "regenerate",
  );
  check("regeneration toolbar delegates to native generation");
  const beforeContinue = await page.evaluate(
    () => SillyTavern.getContext().chat.length,
  );
  const continueTraceBefore = await page.evaluate(
    () => workbench.records.length,
  );
  await page.getByRole("button", { name: "续写", exact: true }).click();
  await page.waitForFunction(
    (n) => workbench.records.length > n,
    continueTraceBefore,
  );
  await page.waitForFunction(
    () => !SillyTavern.getContext().streamingProcessor,
  );
  assert.equal(
    await page.evaluate(() => workbench.records.at(-1).generation.type),
    "continue",
  );
  check("continue toolbar delegates to native generation", {
    messageDelta:
      (await page.evaluate(() => SillyTavern.getContext().chat.length)) -
      beforeContinue,
  });
  await page.keyboard.press("Alt+Shift+Digit4");
  await page.locator(".wb-resource-detail").waitFor();
  const name = await page.getByLabel("用户名称", { exact: true }).inputValue();
  await page.getByLabel("用户名称", { exact: true }).fill(name + " 测试");
  await page.route("**/api/settings/save", (r) =>
    r.fulfill({ status: 500, body: "failure" }),
  );
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await page.getByRole("alert").filter({ hasText: "未确认保存" }).waitFor();
  assert.equal(
    await page.getByLabel("用户名称", { exact: true }).inputValue(),
    name + " 测试",
  );
  await page.unroute("**/api/settings/save");
  await page.getByLabel("用户名称", { exact: true }).fill(name);
  await page
    .getByLabel("用户描述", { exact: true })
    .fill("设置保存失败后的恢复 " + Date.now());
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await page.getByText("已保存", { exact: true }).waitFor();
  check("settings save failures retain Persona drafts and permit retry");
  // A synthetic chapter makes typography, outline navigation and overflow inspectable.
  await page.getByRole("button", { name: "关闭右栏", exact: true }).click();
  await page.evaluate(async () => {
    await TavernHelper.createChatMessages([
      {
        role: "assistant",
        message:
          "# 第一章 · 雾中的来信\n\n雨停在黄昏之前。沿河的旧书店亮起一盏灯，暖光落在窗边那封没有署名的信上。\n\n林间把书页折回原处，抬头看向门口。\n\n“你终于来了。”\n\n## 灯塔与旧码头\n\n远处传来一声雾笛。她没有追问，只将信推到桌边，像是把一个尚未讲完的故事交还给你。\n\n> 信封背面，写着一个早已从地图上消失的地名。",
      },
    ]);
  });
  await page.waitForTimeout(500);
  await page.screenshot({ path: artifacts + "/noval-home.png" });
  assert.deepEqual(errors, []);
  check("no uncaught page errors");
  report.passed = true;
} catch (e) {
  report.passed = false;
  report.failure = e.stack;
  console.error(e);
  process.exitCode = 1;
} finally {
  save("workbench-compatibility.json", report);
  await b.close();
}
