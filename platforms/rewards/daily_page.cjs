"use strict";
const LABEL = /^(Daily activit(?:y|ies)|Daily Set|每日活动|每日活動|每日設定)$/i;
const DASHBOARD = "https://rewards.bing.com/dashboard";
const DAILY_SELECTOR = '[role="progressbar"][aria-label="Daily Set" i],'+
  '[role="progressbar"][aria-label="Daily activities" i],'+
  '[role="progressbar"][aria-label="Daily activity" i],'+
  '[role="progressbar"][aria-label="每日活动"],'+
  '[role="progressbar"][aria-label="每日活動"],'+
  '[role="progressbar"][aria-label="每日設定"]';
function parseProgress(current, max) {
  if (
    typeof current !== "string" ||
    typeof max !== "string" ||
    !current.trim() ||
    !max.trim()
  )
    return null;
  const c = Number(current),
    m = Number(max);
  if (!Number.isFinite(c) || !Number.isFinite(m) || c < 0 || m <= 0)
    return null;
  return { current: c, max: m };
}
async function progress(page) {
  await page.waitForFunction(selector => document.querySelectorAll(selector).length === 1,
    DAILY_SELECTOR, {timeout: 20000});
  const bar = page.locator(DAILY_SELECTOR);
  return parseProgress(
    await bar.getAttribute("aria-valuenow"),
    await bar.getAttribute("aria-valuemax"),
  );
}
async function section(page) {
  const control = page.getByRole("button", { name: LABEL, exact: true });
  if ((await control.getAttribute("aria-expanded")) === "false")
    await control.click();
  await page.waitForTimeout(1000);
  return control.locator("xpath=ancestor::section[1]");
}
async function cards(page) {
  const panel = await section(page);
  return panel.locator("a").evaluateAll(xs => xs.slice(0, 100).map(x => ({
    title: x.innerText.split("\n")[0].trim().slice(0, 300),
    text: x.innerText.slice(0, 1000), href: x.href,
  })).filter(x => x.title));
}

module.exports = {DASHBOARD, parseProgress, progress, section, cards};
