"use strict";
// Account-scoped check-in reconciliation. Local midnight never clears intent.
const fs = require("node:fs"), path = require("node:path");
const { boundedJson } = require("./browser_common.cjs");
const trace = require("./telemetry.cjs");
function validDate(value) {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
}
function journal(stateDir, businessDate) {
  if (!validDate(businessDate)) throw Error("business_date_invalid");
  const file = path.join(stateDir, "app-checkin-journal.json");
  let saved = { schema_version: 1, business_date: businessDate, generation: 0, status: null, previous: null };
  if (fs.existsSync(file)) {
    saved = boundedJson(file, 16384);
    if (saved?.schema_version !== 1 || !validDate(saved.business_date) ||
        !Number.isSafeInteger(saved.generation) || saved.generation < 0 ||
        ![null, "attempted", "confirmed"].includes(saved.status) ||
        (saved.previous !== null && (!validDate(saved.previous?.business_date) ||
          saved.previous.generation !== saved.generation - 1 || saved.previous.status !== "confirmed")))
      throw Error("journal_invalid");
    if (saved.business_date > businessDate) throw Error("business_date_regressed");
  } else {
    // Import the latest known check-in intent even across local midnight. Keep
    // both legacy files untouched; read-to-earn still owns the daily journal.
    const intents = [];
    for (const name of ["app-daily-journal.json", "app-journal.json"]) {
      const legacy = path.join(stateDir, name);
      if (!fs.existsSync(legacy)) continue;
      const value = boundedJson(legacy, 65536);
      const entries = name === "app-daily-journal.json" ? value?.entries : value;
      if (!entries || typeof entries !== "object" || Array.isArray(entries) ||
          Object.keys(entries).length > 100 ||
          Object.values(entries).some(v => !["attempted", "confirmed"].includes(v)))
        throw Error("journal_invalid");
      if (name === "app-daily-journal.json" && (value.schema_version !== 1 || !validDate(value.business_date)))
        throw Error("journal_invalid");
      for (const [key, status] of Object.entries(entries)) {
        if (!key.startsWith("daily_")) continue;
        const date = key.slice(6);
        if (!validDate(date)) throw Error("journal_invalid");
        if (date > businessDate) throw Error("business_date_regressed");
        intents.push({date, status});
      }
    }
    intents.sort((a, b) => b.date.localeCompare(a.date));
    if (intents.length) saved.status = intents[0].status;
  }
  function persist() {
    saved.business_date = businessDate;
    const temporary = file + ".tmp";
    fs.writeFileSync(temporary, JSON.stringify(saved), {mode: 0o600});
    fs.renameSync(temporary, file);
  }
  // Commit migrated intent before another capability can rotate its old day
  // journal. A read-only reconciliation must not forget an uncertain write.
  if (!fs.existsSync(file) || saved.business_date !== businessDate) persist();
  return {
    status: () => saved.status,
    confirm() { saved.status = "confirmed"; persist(); },
    reset() {
      if (saved.status !== "confirmed" || saved.generation >= Number.MAX_SAFE_INTEGER)
        throw Error("journal_invalid");
      saved.previous = {generation: saved.generation, status: "confirmed", business_date: saved.business_date};
      saved.generation++;
      saved.status = null;
      persist();
    },
    attempt() {
      if (saved.status !== null) throw Error("journal_invalid");
      saved.status = "attempted";
      persist();
    },
  };
}
function counter(snapshot) {
  if (snapshot?.execution !== "ok") return null;
  const value = snapshot.details?.metrics?.app_daily;
  if (value?.unit !== "count" || value.max !== 1 || ![0, 1].includes(value.current)) return null;
  if (snapshot.business?.app_daily !== (value.current === 1 ? "complete" : "incomplete")) return null;
  return value.current;
}
async function run(client, journal, {observeDaily, wait = () => new Promise(r => setTimeout(r, 3000)), beforeSubmit = async () => {}}) {
  const unknown = reason => ({business: {app_daily: "unknown"}, reason});
  const complete = () => ({business: {app_daily: "complete"}, reason: "app_checkin_confirmed_by_fresh_snapshot"});
  let snapshot = await observeDaily();
  if (snapshot.execution !== "ok") return {...snapshot, business: {app_daily: "unknown"}};
  let current = counter(snapshot);
  trace.emit("app.checkin", {current, max: 1, state: journal.status()});
  if (current === 1) { journal.confirm(); return complete(); }
  if (current !== 0) return unknown("app_checkin_progress_unavailable");
  if (journal.status() === "confirmed") {
    // A second independent read prevents a single stale/partial page from
    // opening a new cycle. Missing or changed counters never permit a write.
    await wait();
    snapshot = await observeDaily();
    if (snapshot.execution !== "ok") return {...snapshot, business: {app_daily: "unknown"}};
    current = counter(snapshot);
    if (current === 1) { journal.confirm(); return complete(); }
    if (current !== 0) return unknown("app_checkin_reset_unconfirmed");
    journal.reset();
  }
  if (journal.status() === "attempted")
    return unknown("previous_daily_submission_requires_reconciliation");
  client = typeof client === "function" ? await client() : client;
  await client.read();
  await beforeSubmit();
  journal.attempt();
  trace.emit("journal.intent", {capability: "app_daily", state: "attempted"});
  try { await client.submit("daily"); }
  catch (error) {
    trace.failure("app.checkin", error);
    if (error.name === "AppAuthenticationRequired" || error.message === "app_rate_limited") throw error;
  }
  snapshot = await observeDaily();
  if (snapshot.execution !== "ok") return {...snapshot, business: {app_daily: "unknown"}};
  if (counter(snapshot) === 1) { journal.confirm(); return complete(); }
  return unknown("daily_submitted_without_attributable_confirmation");
}
module.exports = {journal, counter, run};
