"use strict";
// The visible set identifies the platform day; host midnight does not.
const normalize = value => String(value).normalize("NFKC")
  .replace(/[\u200b-\u200d\ufeff]/g, "").replace(/\s+/g, " ").trim();
const matches = (row, card) => card.href === row.destinationUrl || normalize(card.title) === normalize(row.title);
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
module.exports = {inventory, item, matches};
