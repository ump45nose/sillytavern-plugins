// Named UI states for the seeded visual instance, shared by capture and audit scripts.
import { session, ready, urls } from "../browser.mjs";

const desktop = { width: 1496, height: 817 };
const compact = { width: 1366, height: 768 };
const phone = { width: Number(process.env.WB_PHONE_WIDTH || 390), height: 844 };

const key = (combo) => async (page) => {
  await page.keyboard.press(combo);
};
const click = (selector) => async (page) => {
  await page.locator(selector).first().click();
};
const label = (name) => async (page) => {
  await page.getByLabel(name, { exact: true }).first().click();
};
const text = (name) => async (page) => {
  await page.getByRole("button", { name, exact: true }).first().click();
};
/** The left column leads to 设置; every page is then one entry in the workspace's own nav. */
const settings = (name) => async (page) => {
  await page.locator(".wb-nav-footer").getByRole("button", { name: "设置", exact: true }).click();
  await page.locator(".wb-settings-nav").getByRole("button", { name, exact: true }).click();
};
const layout = (mode) => async (page) => {
  await page.evaluate((mode) => workbench.host.preference({ layout: mode }), mode);
  // RP keeps its top bar out of view until the pointer reaches the top edge.
  await page.mouse.move(700, 420);
};

const dark = async (page) => {
  await page.evaluate(() => workbench.host.preference({ theme: "dark" }));
};

/** Clicks the last match: the newest message, which stays in view once the chat is pinned to the bottom. */
const tap = (selector) => async (page) => {
  await page.locator(selector).last().click();
};
/** A one-finger touch drag on the first match, as a phone gesture (touchstart → moves → touchend). */
const swipe = (selector, dx, dy) => async (page) => {
  await page.locator(selector).first().evaluate((node, [dx, dy]) => {
    const box = node.getBoundingClientRect(),
      x = box.left + box.width / 2,
      y = box.top + box.height / 2;
    const touch = (cx, cy) => new Touch({ identifier: 7, target: node, clientX: cx, clientY: cy });
    const send = (type, cx, cy) =>
      node.dispatchEvent(
        new TouchEvent(type, {
          bubbles: true,
          cancelable: true,
          touches: type === "touchend" ? [] : [touch(cx, cy)],
          changedTouches: [touch(cx, cy)],
        }),
      );
    send("touchstart", x, y);
    for (let i = 1; i <= 6; i++) send("touchmove", x + (dx * i) / 6, y + (dy * i) / 6);
    send("touchend", x + dx, y + dy);
  }, [dx, dy]);
  await page.waitForTimeout(450);
};
const hover = (selector) => async (page) => {
  await page.locator(selector).last().hover();
};
const fill = (selector, value) => async (page) => {
  await page.locator(selector).fill(value);
};

/** A captured request shaped like the trace collector's records, so the Trace panel has something to show. */
const traceRecord = async (page) => {
  await page.evaluate(() => {
    workbench.records.push({
      id: "visual-trace", atMs: 0, timestamp: Date.now() - 42_000, path: "/api/backends/chat-completions/generate",
      capturePoint: "browser-to-sillytavern", status: 200, elapsedMs: 3240, generation: { id: "g", type: "normal" },
      body: { model: "claude-opus", temperature: 0.9, max_tokens: 1200, stream: true, messages: [
        { role: "system", content: "你是一位克制的叙事者，用第三人称写作。" },
        { role: "system", content: "[雾港志 / 灯塔] 雾港北岬的灯塔已经熄灭七年，守塔人下落不明。" },
        { role: "user", content: "我把书拉过来，翻到夹信的那一页。" },
      ] },
      assemblyEvent: "CHAT_COMPLETION_SETTINGS_READY", assembled: null,
      worldInfo: [
        { world: "雾港志", comment: "灯塔", uid: 1, key: ["灯塔"], content: "雾港北岬的灯塔已经熄灭七年，守塔人下落不明。", position: 0 },
        { world: "雾港志", comment: "雾港 · 码头区", uid: 3, constant: true, key: [], content: "码头区终年有雾。", position: 4, depth: 2 },
      ],
      worldInfoEvidence: "WORLD_INFO_ACTIVATED",
      composition: { counts: { main: 1840, charDescription: 1312, worldInfoBefore: 2286, chatHistory: 32610, nsfw: 364 }, limit: 65536 },
    });
  });
};

// Each state starts from a fresh load; steps run in order.
export const states = [
  { name: "novel-home", viewport: desktop, steps: [] },
  { name: "novel-home-1366", viewport: compact, steps: [] },
  { name: "novel-hover", viewport: desktop, steps: [hover('#chat .mes[is_user="false"]:not(.last_mes)')] },
  { name: "novel-draft", viewport: desktop, steps: [fill("#send_textarea", "她把信封翻过来，背面写着一行小字。")] },
  { name: "novel-left-collapsed", viewport: desktop, steps: [label("收纳左边栏")] },
  { name: "panel-character", viewport: desktop, steps: [label("角色与资源侧栏")] },
  { name: "panel-world", viewport: desktop, steps: [key("Alt+Shift+Digit3")] },
  { name: "panel-world-entry", viewport: desktop, steps: [key("Alt+Shift+Digit3"), label("编辑条目 灯塔")] },
  { name: "panel-preset", viewport: desktop, steps: [key("Alt+Shift+Digit2")] },
  { name: "panel-connection", viewport: desktop, steps: [key("Alt+Shift+Digit1")] },
  { name: "panel-persona", viewport: desktop, steps: [key("Alt+Shift+Digit4")] },
  { name: "panel-trace", viewport: desktop, steps: [key("Alt+Shift+KeyT")] },
  { name: "panel-trace-record", viewport: desktop, steps: [traceRecord, key("Alt+Shift+KeyT")] },
  { name: "panel-export", viewport: desktop, steps: [key("Alt+Shift+KeyT"), click('.wb-panel-tabs [aria-label="记录导出"]')] },
  { name: "panel-image", viewport: desktop, steps: [key("Alt+Shift+KeyT"), click('.wb-panel-tabs [aria-label="生图"]')] },
  { name: "panel-outline", viewport: desktop, steps: [key("Alt+Shift+KeyT"), click('.wb-panel-tabs [aria-label="大纲"]')] },
  { name: "chooser-world", viewport: desktop, steps: [click('[aria-controls="wb-choices-world"]')] },
  {
    name: "chooser-connection",
    viewport: desktop,
    steps: [click('[aria-controls="wb-choices-connection"]')],
  },
  { name: "reading-settings", viewport: desktop, steps: [label("阅读设置")] },
  { name: "focus", viewport: desktop, steps: [key("Alt+Shift+KeyF")] },
  { name: "novel-dark", viewport: desktop, steps: [dark] },
  { name: "settings-character-empty", viewport: desktop, steps: [settings("角色管理"), fill(".wb-character-search-row input", "zzz")] },
  { name: "popover-chat-files", viewport: desktop, steps: [label("管理聊天文件")] },
  { name: "settings-user", viewport: desktop, steps: [settings("用户设置")] },
  { name: "settings-user-messages", viewport: desktop, steps: [settings("用户设置"), text("消息与输入")] },
  { name: "settings-formatting", viewport: desktop, steps: [settings("回复格式")] },
  { name: "settings-background", viewport: desktop, steps: [settings("背景")] },
  { name: "settings-connection", viewport: desktop, steps: [settings("连接")] },
  { name: "settings-persona", viewport: desktop, steps: [settings("用户设定")] },
  { name: "settings-extensions", viewport: desktop, steps: [settings("扩展")] },
  { name: "settings-addons", viewport: desktop, steps: [settings("扩展"), text("工作台附加功能")] },
  { name: "settings-preset", viewport: desktop, steps: [settings("预设")] },
  { name: "settings-preset-prompts", viewport: desktop, steps: [settings("预设"), text("提示词")] },
  { name: "settings-preset-advanced", viewport: desktop, steps: [settings("预设"), text("高级参数")] },
  { name: "settings-world", viewport: desktop, steps: [settings("世界书")] },
  {
    name: "settings-world-trigger",
    viewport: desktop,
    steps: [settings("世界书"), text("触发条件")],
  },
  { name: "settings-world-json", viewport: desktop, steps: [settings("世界书"), text("完整 JSON")] },
  { name: "settings-character", viewport: desktop, steps: [settings("角色管理")] },
  {
    name: "settings-character-select",
    viewport: desktop,
    steps: [settings("角色管理"), click(".wb-character-card:nth-child(1) > input"), click(".wb-character-card:nth-child(3) > input")],
  },
  { name: "settings-character-edit", viewport: desktop, steps: [settings("角色管理"), click(".wb-character-card:nth-child(1) .wb-character-main")] },
  {
    name: "panel-character-edit",
    viewport: desktop,
    steps: [key("Alt+Shift+KeyT"), click('.wb-panel-tabs [aria-label="角色"]'), click(".wb-character-edit")],
  },
  { name: "shortcuts", viewport: desktop, steps: [text("快捷键")] },
  { name: "rp-stage", viewport: desktop, steps: [layout("rp")] },
  { name: "rp-compose", viewport: desktop, steps: [layout("rp"), label("快进到你的回应")] },
  { name: "rp-expanded", viewport: desktop, steps: [layout("rp"), label("快进到你的回应"), label("展开 RP 输入区")] },
  { name: "rp-tools", viewport: desktop, steps: [layout("rp"), hover(".wb-rp-tools")] },
  { name: "rp-left-open", viewport: desktop, steps: [layout("rp"), label("展开左边栏")] },
  { name: "rp-pinned", viewport: desktop, steps: [layout("rp"), async (page) => { await page.mouse.move(748, 4); await page.waitForTimeout(250); }, label("固定顶栏")] },
  { name: "rp-history", viewport: desktop, steps: [layout("rp"), label("查看对话记录")] },
  { name: "rp-panel-world", viewport: desktop, steps: [layout("rp"), key("Alt+Shift+Digit3")] },
  { name: "rp-stage-dark", viewport: desktop, steps: [layout("rp"), dark] },
  { name: "rp-history-dark", viewport: desktop, steps: [layout("rp"), dark, label("查看对话记录")] },
  { name: "m-novel-home", viewport: phone, mobile: true, steps: [] },
  { name: "m-novel-left", viewport: phone, mobile: true, steps: [label("打开大纲与导航")] },
  { name: "m-novel-right", viewport: phone, mobile: true, steps: [label("打开角色与 Trace")] },
  { name: "m-panel-image-config", viewport: phone, mobile: true, steps: [label("打开角色与 Trace"), tap('.wb-right .wb-panel-tab[aria-label="生图"]'), label("生图完整配置")] },
  { name: "m-panel-image-scene", viewport: phone, mobile: true, steps: [label("打开角色与 Trace"), tap('.wb-right .wb-panel-tab[aria-label="生图"]'), text("场景来源 · 已排除思考块")] },
  ...["世界书", "预设", "连接", "用户设定", "Trace", "记录导出", "大纲", "生图"].map((tab, i) => ({
    name: `m-panel-${i + 1}`,
    viewport: phone,
    mobile: true,
    steps: [label("打开角色与 Trace"), tap(`.wb-right .wb-panel-tab[aria-label="${tab}"]`)],
  })),
  { name: "m-novel-menu", viewport: phone, mobile: true, steps: [label("打开会话管理")] },
  { name: "m-novel-editor", viewport: phone, mobile: true, steps: [label("打开输入工具"), text("全屏输入")] },
  { name: "m-settings", viewport: phone, mobile: true, steps: [label("打开会话管理"), text("用户设置")] },
  ...["外观与阅读", "参数与预设", "API 与连接管理", "全部角色", "身份编辑"].map((group, i) => ({
    name: `m-settings-${i + 1}`,
    viewport: phone,
    mobile: true,
    steps: [label("打开会话管理"), text("用户设置"), text(group)],
  })),
  { name: "m-novel-focus", viewport: phone, mobile: true, steps: [label("打开会话管理"), text("专注模式")] },
  { name: "m-novel-floor", viewport: phone, mobile: true, steps: [label("打开大纲与导航"), tap(".wb-floor-list button")] },
  { name: "m-rp-home", viewport: phone, mobile: true, steps: [layout("rp")] },
  { name: "m-rp-tools", viewport: phone, mobile: true, steps: [layout("rp"), label("快进到你的回应"), label("打开输入工具")] },
  { name: "m-rp-hidden", viewport: phone, mobile: true, steps: [layout("rp"), label("隐藏界面")] },
  { name: "m-rp-compose", viewport: phone, mobile: true, steps: [layout("rp"), label("快进到你的回应")] },
  { name: "m-rp-edit", viewport: phone, mobile: true, steps: [layout("rp"), label("编辑当前对白")] },
  { name: "m-rp-dark", viewport: phone, mobile: true, steps: [layout("rp"), dark] },
  { name: "m-rp-history", viewport: phone, mobile: true, steps: [layout("rp"), swipe("#sheld", 0, -160)] },
  { name: "m-novel-dark", viewport: phone, mobile: true, steps: [dark] },
  { name: "m-novel-tools", viewport: phone, mobile: true, steps: [label("打开输入工具")] },
  {
    name: "m-novel-config",
    viewport: phone,
    mobile: true,
    steps: [(page) => page.getByRole("group", { name: "快捷配置" }).getByRole("button").nth(1).click()],
  },
  { name: "m-novel-actions", viewport: phone, mobile: true, steps: [tap('#chat .mes[is_user="false"] .mes_text')] },
];
// The fixture keeps the last layout chosen; phone states other than RP start from Noval.
for (const state of states)
  if (state.mobile && !state.name.startsWith("m-rp")) state.steps.unshift(layout("novel"));

/** Opens a fresh session, drives it into `state`, then hands the page to `inspect`. */
export async function visit(browser, state, inspect) {
  const { context, page, errors } = await session(browser, { helper: false, mobile: !!state.mobile });
  try {
    await page.setViewportSize(state.viewport);
    await ready(page, urls.visual, { probe: true });
    await page.waitForFunction(() => workbench.mounted && SillyTavern.getContext().chat.length > 0);
    // A neutral pointer position outside hover zones and edge reveals.
    await page.mouse.move(state.viewport.width / 2, 8);
    await page.waitForTimeout(900);
    for (const step of state.steps) {
      await step(page);
      await page.waitForTimeout(500);
    }
    await page.mouse.move(state.viewport.width / 2, 8);
    await page.waitForTimeout(600);
    // Pin the reading scroll position; native auto-scroll timing otherwise varies by a few pixels.
    await page.evaluate(() => {
      const chat = document.getElementById("chat");
      chat?.scrollTo({ top: chat.scrollHeight, behavior: "instant" });
    });
    await page.waitForTimeout(400);
    return { result: await inspect(page), errors };
  } finally {
    await context.close();
  }
}
