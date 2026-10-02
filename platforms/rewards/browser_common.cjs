"use strict";
const fs = require("node:fs"),
  path = require("node:path");
const DASHBOARD = "https://rewards.bing.com/dashboard";
const EARN = "https://rewards.bing.com/earn";
const FLYOUT =
  "https://www.bing.com/rewards/panelflyout/getuserinfo?channel=BingFlyout&partnerId=BingRewards";
const MAX_STATE = 1024 * 1024,
  MAX_HTML = 2 * 1024 * 1024;
const obstacles = require("./obstacles.cjs");
function restricted(raw) {
  const counters = raw?.flyoutResult?.userStatus?.counters;
  const attrs = raw?.userInfo?.profile?.attributes;
  const sum = (rows) => {
    if (!Array.isArray(rows)) return null;
    let value = 0;
    for (const row of rows) {
      const n = row?.pointProgressMax;
      if (
        n === null ||
        n === undefined ||
        typeof n === "boolean" ||
        (typeof n === "string" && !n.trim()) ||
        !Number.isFinite(Number(n)) ||
        Number(n) < 0
      )
        return null;
      value += Number(n);
    }
    return value;
  };
  const pc = sum(counters?.PCSearch ?? counters?.pcSearch);
  return (
    String(attrs?.rbs ?? "").trim() === "1" &&
    Boolean(attrs?.SerpBotScore_upd) &&
    Boolean(attrs?.AdsBotScore_upd) &&
    sum(counters?.ActivityAndQuiz ?? counters?.activityAndQuiz) === 0 &&
    pc !== null &&
    sum(counters?.DailyPoint ?? counters?.dailyPoint) === pc
  );
}
function assertAccountAvailable(raw, expectedRegion = null) {
  if (
    raw?.isError ||
    raw?.userInfo?.isRewardsUser !== true ||
    raw?.flyoutResult?.userStatus?.isRewardsUser !== true
  )
    throw Error("authenticated_inventory_unavailable");
  const warnings = [raw.userWarnings, raw.flyoutResult.userWarnings];
  if (
    restricted(raw) ||
    warnings.some(
      (rows) =>
        Array.isArray(rows) &&
        rows.some((row) => row?.name === "Fraud_UserWarning_BotScore_UX"),
    )
  )
    throw new obstacles.Obstacle({
      url: DASHBOARD,
      flags: { botWarning: true },
    });
  const country = raw.userInfo?.profile?.attributes?.country;
  if (
    expectedRegion &&
    (!country || String(country).toUpperCase() !== expectedRegion.toUpperCase())
  )
    throw new obstacles.Obstacle({
      url: DASHBOARD,
      flags: { regionMismatch: true },
    });
  return raw;
}
class HumanRequired extends obstacles.Obstacle {
  constructor() {
    super({
      url: DASHBOARD,
      flags: { login: true },
      safeEvidence: ["legacy-session-check"],
    });
  }
}
function boundedJson(file, max = MAX_STATE) {
  const fd = fs.openSync(file, "r");
  try {
    const bytes = Buffer.alloc(max + 1);
    const n = fs.readSync(fd, bytes, 0, bytes.length, 0);
    if (n > max) throw Error("input_too_large");
    return JSON.parse(bytes.subarray(0, n));
  } finally {
    fs.closeSync(fd);
  }
}
function readState(dir, device = "desktop") {
  const state = boundedJson(
    path.join(
      dir,
      device === "mobile" ? "storage-state.mobile.json" : "storage-state.json",
    ),
  );
  if (!state || !Array.isArray(state.cookies) || !Array.isArray(state.origins))
    throw Error("session_invalid");
  return state;
}
function dependency(root) {
  if (!root || !path.isAbsolute(root)) throw Error("dependency_not_configured");
  const packageFile = path.join(root, "node_modules/patchright/package.json");
  if (boundedJson(packageFile, 65536).version !== "1.61.1")
    throw Error("dependency_incompatible");
  return require(path.join(root, "node_modules/patchright")).chromium;
}
async function guard(page, { observeEvidence } = {}) {
  const rawUrl = page.url();
  let url;
  try {
    url = new URL(rawUrl);
  } catch {
    throw new HumanRequired();
  }
  const authHosts = [
    "login.live.com",
    "account.live.com",
    "login.microsoftonline.com",
  ];
  const expected = [
    "rewards.bing.com",
    "www.bing.com",
    "cn.bing.com",
    "bing.com",
    "www.youtube.com",
    "www.tiktok.com",
    ...authHosts,
  ];
  if (!expected.includes(url.hostname))
    throw new obstacles.Obstacle({
      url: rawUrl,
      flags: { unknownLayout: true },
    });
  const checks = [
    ["accountLocked", "#serviceAbuseLandingTitle"],
    ["captcha", 'iframe[src*="captcha"],iframe[src*="challenge"],#captcha'],
    ["terms", '[data-testid="terms-consent"],input[name="acceptTerms"]'],
    [
      "age",
      'input[name="birthYear"],input[name="birthDay"],select[name="BirthYear"]',
    ],
    ["permission", '[data-testid="permission-consent"]'],
    ["login", "input[type=password],#i0116,input#usernameEntry"],
  ];
  for (const [flag, selector] of checks) {
    if (await page.locator(selector).count())
      throw new obstacles.Obstacle({
        url: rawUrl,
        flags: { [flag]: true },
        safeEvidence: [
          selector,
          observeEvidence
            ? await observeEvidence(flag, page)
            : require("node:crypto").randomUUID(),
        ],
      });
  }
  // Only known non-binding cookie containers, never generic Accept/Next buttons.
  const cookie = page.locator("#bnp_overlay_wrapper");
  if (await cookie.count()) {
    const reject = page.locator("#bnp_btn_reject");
    if (await reject.count()) {
      try {
        await reject.click({ timeout: 3000 });
      } catch {}
      // A timeout may mean the click completed. Read back before considering another attempt.
      if ((await cookie.count()) && (await cookie.isVisible()))
        throw new obstacles.Obstacle({
          url: rawUrl,
          flags: { cookieBanner: true },
          safeEvidence: ["bing-cookie-reject"],
        });
    } else
      throw new obstacles.Obstacle({
        url: rawUrl,
        flags: { cookieBanner: true },
        safeEvidence: ["bing-cookie-control-missing"],
      });
  }
  if (
    authHosts.includes(url.hostname) ||
    /\/(?:auth|login|signin|challenge)(?:\/|\?|$)/i.test(url.pathname)
  )
    throw new obstacles.Obstacle({
      url: rawUrl,
      flags: { login: true },
      safeEvidence: ["authentication-route"],
    });
}
async function boundedHtml(page) {
  const html = await page.evaluate((max) => {
    const value = document.documentElement.outerHTML;
    return value.length > max ? null : value;
  }, MAX_HTML);
  if (typeof html !== "string") throw Error("page_too_large");
  return html;
}
function contextOptions(value = {}) {
  const allowed = new Set([
    "userAgent",
    "isMobile",
    "hasTouch",
    "viewport",
    "deviceScaleFactor",
    "locale",
    "timezoneId",
    "colorScheme",
  ]);
  if (
    !value ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    Object.keys(value).some((k) => !allowed.has(k))
  )
    throw Error("context_option_unsupported");
  for (const key of ["userAgent", "locale", "timezoneId"])
    if (
      value[key] !== undefined &&
      (typeof value[key] !== "string" ||
        value[key].length > 1024 ||
        /[\r\n]/.test(value[key]))
    )
      throw Error("invalid_context_option");
  for (const key of ["isMobile", "hasTouch"])
    if (value[key] !== undefined && typeof value[key] !== "boolean")
      throw Error("invalid_context_option");
  if (value.viewport) {
    for (const key of ["width", "height"])
      if (
        !Number.isInteger(value.viewport[key]) ||
        value.viewport[key] < 200 ||
        value.viewport[key] > 3840
      )
        throw Error("invalid_viewport");
  }
  if (
    value.deviceScaleFactor !== undefined &&
    (!Number.isFinite(value.deviceScaleFactor) ||
      value.deviceScaleFactor < 1 ||
      value.deviceScaleFactor > 4)
  )
    throw Error("invalid_scale");
  return { ...value };
}
async function withBrowser(chromium, state, options, work) {
  let browser, context;
  try {
    browser = await chromium.launch({
      headless: true,
      chromiumSandbox: true,
      ...(options.proxy
        ? { proxy: { server: options.proxy, bypass: "r.bing.com" } }
        : {}),
    });
    context = await browser.newContext({
      ...contextOptions(options.contextOptions),
      storageState: state,
      ignoreHTTPSErrors: false,
    });
    const output = await work(context, await context.newPage());
    if (
      output?.execution === "ok" &&
      typeof options.onVerifiedState === "function"
    ) {
      const next = await context.storageState();
      if (
        !next ||
        !Array.isArray(next.cookies) ||
        !Array.isArray(next.origins) ||
        Buffer.byteLength(JSON.stringify(next)) > MAX_STATE
      )
        throw Error("session_state_limit");
      // In-memory handoff only; failed stages do not overwrite a valid snapshot.
      await options.onVerifiedState(next);
    }
    return output;
  } finally {
    try {
      if (context) await context.close();
    } finally {
      if (browser) await browser.close();
    }
  }
}
async function readFlyout(context, existingPage = null) {
  // Stream and cap the body in the browser before transferring data to Node.
  const page = existingPage || (await context.newPage());
  try {
    if (!existingPage)
      await page.goto("https://www.bing.com/", {
        waitUntil: "domcontentloaded",
        timeout: 45000,
      });
    await guard(page);
    return await page.evaluate(
      async ({ url, max }) => {
        const c = new AbortController(),
          timer = setTimeout(() => c.abort(), 20000);
        try {
          const response = await fetch(url, {
            credentials: "include",
            signal: c.signal,
            redirect: "error",
          });
          if (!response.ok || !response.body) throw Error("flyout_unavailable");
          const reader = response.body.getReader(),
            decoder = new TextDecoder();
          let length = 0,
            text = "";
          while (true) {
            const part = await reader.read();
            if (part.done) break;
            length += part.value.byteLength;
            if (length > max) {
              await reader.cancel();
              throw Error("response_too_large");
            }
            text += decoder.decode(part.value, { stream: true });
          }
          text += decoder.decode();
          return JSON.parse(text);
        } finally {
          clearTimeout(timer);
        }
      },
      { url: FLYOUT, max: MAX_STATE },
    );
  } finally {
    if (!existingPage) await page.close();
  }
}
module.exports = {
  restricted,
  assertAccountAvailable,
  contextOptions,
  recordObstacle: obstacles.record,
  DASHBOARD,
  EARN,
  MAX_HTML,
  HumanRequired,
  boundedJson,
  readState,
  dependency,
  guard,
  boundedHtml,
  withBrowser,
  readFlyout,
};
