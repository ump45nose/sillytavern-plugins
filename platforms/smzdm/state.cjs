"use strict";
const fs = require("node:fs"),
  path = require("node:path");
const STATES = new Set(["unknown", "pending", "complete", "not_applicable"]);
// One account/day, three facts. Never store cookies, request bodies, or API data.
function journal(directory, account, date, confirmedPath) {
  const file = directory ? path.join(directory, "http-actions.json") : null;
  let value = {
    version: 1,
    account,
    date,
    checkin: "unknown",
    reward: "unknown",
    extra: "unknown",
  };
  if (file) {
    try {
      const fd = fs.openSync(file, "r");
      let raw;
      try {
        const buf = Buffer.alloc(4097);
        const n = fs.readSync(fd, buf, 0, buf.length, 0);
        if (n > 4096) throw Error("invalid_action_state");
        raw = buf.subarray(0, n).toString();
      } finally {
        fs.closeSync(fd);
      }
      const saved = JSON.parse(raw);
      if (
        Object.keys(saved).sort().join() !==
          "account,checkin,date,extra,reward,version" ||
        saved.version !== 1 ||
        saved.account !== account ||
        typeof saved.date !== "string" ||
        ![saved.checkin, saved.reward, saved.extra].every((x) => STATES.has(x))
      )
        throw Error("invalid_action_state");
      if (saved.date === date) value = saved;
      else if (saved.extra === "pending") value.extra = "pending";
    } catch (e) {
      if (e.code !== "ENOENT") throw Error("invalid_action_state");
    }
  }
  // Merge independent confirmed write receipts; checkin never implies extra.
  // An existing checkin journal must not hide a legacy extra-reward receipt.
  if (
    confirmedPath &&
    (value.checkin !== "complete" || value.extra !== "complete")
  ) {
    try {
      const fd = fs.openSync(confirmedPath, "r");
      let raw;
      try {
        const buf = Buffer.alloc(65537);
        const n = fs.readSync(fd, buf, 0, buf.length, 0);
        if (n > 65536) throw Error("invalid_previous_result");
        raw = buf.subarray(0, n).toString();
      } finally {
        fs.closeSync(fd);
      }
      const old = JSON.parse(raw);
      const statuses = new Set([
        "complete",
        "incomplete",
        "unknown",
        "not_applicable",
        "blocked",
      ]);
      if (
        !old ||
        Object.keys(old).sort().join() !==
          "account,business,business_date,execution_status,platform,reason,run_id,schema_version" ||
        old.schema_version !== 1 ||
        old.platform !== "smzdm" ||
        old.account !== account ||
        typeof old.business_date !== "string" ||
        typeof old.run_id !== "string" ||
        !["ok", "failed", "timeout", "busy"].includes(old.execution_status) ||
        typeof old.reason !== "string" ||
        old.reason.length > 256 ||
        !old.business ||
        typeof old.business !== "object" ||
        Array.isArray(old.business) ||
        Object.keys(old.business).length === 0 ||
        Object.keys(old.business).length > 32 ||
        !Object.entries(old.business).every(
          ([k, v]) => k.length <= 64 && statuses.has(v),
        )
      )
        throw Error("invalid_previous_result");
      if (old.business_date === date) {
        let migrated = false;
        for (const [source, target] of [
          ["checkin", "checkin"],
          ["extra_reward", "extra"],
        ]) {
          if (
            old.business[source] === "complete" &&
            value[target] !== "complete"
          ) {
            value[target] = "complete";
            migrated = true;
          }
        }
        // Save receipts even if all subsequent read-only queries fail.
        if (migrated) save();
      }
    } catch (e) {
      if (e.code !== "ENOENT") throw Error("invalid_previous_result");
    }
  }
  function set(key, state) {
    if (!["checkin", "reward", "extra"].includes(key) || !STATES.has(state))
      throw Error("invalid_action_state");
    value[key] = state;
    save();
  }
  function save() {
    if (!file) return;
    fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
    const tmp = file + ".tmp-" + process.pid;
    const fd = fs.openSync(tmp, "wx", 0o600);
    try {
      fs.writeFileSync(fd, JSON.stringify(value));
      fs.fsyncSync(fd);
    } finally {
      fs.closeSync(fd);
    }
    try {
      fs.renameSync(tmp, file);
      const dirfd = fs.openSync(directory, "r");
      try {
        fs.fsyncSync(dirfd);
      } finally {
        fs.closeSync(dirfd);
      }
    } finally {
      if (fs.existsSync(tmp)) fs.unlinkSync(tmp);
    }
  }
  return { get: (key) => value[key], set };
}
module.exports = { journal };
