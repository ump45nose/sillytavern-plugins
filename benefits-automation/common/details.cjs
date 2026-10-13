"use strict";
// Same bounded metrics/items protocol as details.py. No raw response passthrough.
const UNITS = new Set(["points", "coins", "beans", "days", "count"]);
const STATES = new Set(["complete", "incomplete", "unknown", "not_applicable", "blocked"]);
function number(value) {
  if (value == null || typeof value === "boolean" ||
      !["number", "string"].includes(typeof value) ||
      (typeof value === "string" && !value.trim())) return null;
  const n = Number(value);
  return Number.isFinite(n) && Math.abs(n) <= 1e12 ? n : null;
}
function metric(unit, current = null, max = null, before = null, after = null, delta = null) {
  return {unit, current: number(current), max: number(max), before: number(before),
    after: number(after), delta: number(delta)};
}
function validateDetails(value) {
  if (!value || Object.keys(value).sort().join() !== "items,metrics" ||
      !value.metrics || Array.isArray(value.metrics) || typeof value.metrics !== "object" ||
      Object.keys(value.metrics).length > 32 || !Array.isArray(value.items) || value.items.length > 100)
    throw Error("invalid_details");
  for (const [key, row] of Object.entries(value.metrics)) {
    if (!/^[a-z][a-z0-9_]{0,63}$/.test(key) || !row ||
        Object.keys(row).sort().join() !== "after,before,current,delta,max,unit" || !UNITS.has(row.unit))
      throw Error("invalid_metric");
    for (const key of ["current", "max", "before", "after", "delta"])
      if (row[key] !== null && (typeof row[key] !== "number" || number(row[key]) === null ||
          (key !== "delta" && row[key] < 0))) throw Error("invalid_metric_number");
  }
  for (const row of value.items) {
    if (!row || Object.keys(row).some(k => !["id", "name", "url", "status", "reason"].includes(k)) ||
        !STATES.has(row.status)) throw Error("invalid_item");
    for (const [key, limit] of [["id",128],["name",200],["reason",100]])
      if (typeof row[key] !== "string" || row[key].length > limit || /[\x00-\x1f]/.test(row[key]))
        throw Error("invalid_item_text");
    if (!/^[a-z0-9_]{1,100}$/.test(row.reason)) throw Error("invalid_item_reason");
    if (row.url !== undefined) {
      const u = new URL(row.url);
      if (typeof row.url !== "string" || row.url.length > 512 || u.protocol !== "https:" ||
          u.username || u.password || u.search || u.hash || (u.port && u.port !== "443"))
        throw Error("invalid_item_url");
    }
  }
  return value;
}
module.exports = {number, metric, validateDetails};
