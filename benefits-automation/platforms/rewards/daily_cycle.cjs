"use strict";
// The visible set identifies the platform day; host midnight does not.
const normalize = value => String(value).normalize("NFKC")
  .replace(/[\u200b-\u200d\ufeff]/g, "").replace(/\s+/g, " ").trim();
const matches = (row, card) => card.href === row.destinationUrl || normalize(card.title) === normalize(row.title);
function excluded(row) {
  try {
    let target = new URL(row.destinationUrl);
    if (target.origin === "https://www.bing.com" && target.pathname === "/rewards/checkuser")
      target = new URL(target.searchParams.get("ru"), target.origin);
    if (target.origin !== "https://www.bing.com" || target.pathname !== "/search") return false;
    return /(?:^|\s)(?:BTROID|PollScenarioId):"/.test(target.searchParams.get("filters") || "");
  } catch {
    return false;
  }
}
function summary(rows) {
  const items = rows.map(row => {
    const skipped = excluded(row);
    return {id: row.offerId, name: row.title,
      status: skipped ? "not_applicable" : row.complete ? "complete" : "incomplete",
      reason: skipped ? "interactive_activity_excluded" : "fresh_readback"};
  });
  const active = items.filter(item => item.status !== "not_applicable");
  return {current: active.filter(item => item.status === "complete").length,
    max: active.length, items};
}
function inventory(raw, cards) {
  const sets = Object.entries(raw.flyoutResult.dailySetPromotions).filter(([, rows]) =>
    rows.length > 0 && rows.every(row => cards.some(card => matches(row, card))));
  if (sets.length !== 1) throw Error("daily_cycle_unavailable");
  const [date, rows] = sets[0], [month, day, year] = date.split("/");
  return {date: `${year}-${month.padStart(2, "0")}-${day.padStart(2, "0")}`, rows};
}
function item(date) {
  return {id: "rewards_cycle_" + date, name: "任务周期：" + date,
    status: "complete", reason: "platform_task_cycle"};
}
module.exports = {inventory, item, matches, excluded, summary};
