"use strict";
// The visible set identifies the platform day; host midnight does not.
const normalize = value => String(value).normalize("NFKC")
  .replace(/[\u200b-\u200d\ufeff]/g, "").replace(/\s+/g, " ").trim();
const matches = (row, card) => card.href === row.destinationUrl || normalize(card.title) === normalize(row.title);
function destination(value) {
  try {
    let target = new URL(value);
    if (target.username || target.password) return null;
    if (target.origin === "https://www.bing.com" && target.pathname === "/rewards/checkuser")
      target = new URL(target.searchParams.get("ru"), target.origin);
    return target.origin === "https://www.bing.com" && target.pathname === "/search" &&
      !target.username && !target.password ? target : null;
  } catch {
    return null;
  }
}
function excluded(row) {
  const target = destination(row.destinationUrl);
  return target ? /(?:^|\s)(?:BTROID|PollScenarioId):"/.test(target.searchParams.get("filters") || "") : false;
}
function summary(rows) {
  const {number} = require("../../common/details.cjs");
  const items = rows.map(row => {
    const skipped = excluded(row);
    return {id: row.offerId, name: row.title,
      status: skipped ? "not_applicable" : row.complete ? "complete" : "incomplete",
      reason: skipped ? "interactive_activity_excluded" : "fresh_readback"};
  });
  const active = items.filter(item => item.status !== "not_applicable");
  const pointRows = rows.filter(row => !excluded(row));
  const knownPoints = pointRows.every(row => number(row.pointProgress) !== null &&
    number(row.pointProgressMax) !== null && number(row.pointProgress) >= 0 &&
    number(row.pointProgressMax) >= 0 && number(row.pointProgress) <= number(row.pointProgressMax));
  return {current: active.filter(item => item.status === "complete").length,
    max: active.length, items,
    points: {current: knownPoints ? pointRows.reduce((total, row) => total + number(row.pointProgress), 0) : null,
      max: knownPoints ? pointRows.reduce((total, row) => total + number(row.pointProgressMax), 0) : null}};
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
module.exports = {inventory, item, matches, destination, excluded, summary};
