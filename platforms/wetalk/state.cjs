"use strict";

const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");

function failure(reason) {
  return Object.assign(new Error(reason), { reason });
}

// One account/day receipt, not a copy of the captured request or API response.
function journal(directory, account, date, identity) {
  const file = directory ? path.join(directory, "checkin.json") : null;
  let value = { version: 1, account, date, identity, checkin: "unknown", reward: null };
  if (file) {
    try {
      const fd = fs.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
      let raw;
      try {
        if (!fs.fstatSync(fd).isFile()) throw failure("invalid_action_state");
        const bytes = Buffer.alloc(4097);
        const size = fs.readSync(fd, bytes, 0, bytes.length, 0);
        if (size > 4096) throw failure("invalid_action_state");
        raw = JSON.parse(bytes.subarray(0, size).toString("utf8"));
      } finally {
        fs.closeSync(fd);
      }
      if (!raw || Object.keys(raw).sort().join() !== "account,checkin,date,identity,reward,version" ||
          raw.version !== 1 || raw.account !== account ||
          typeof raw.date !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(raw.date) ||
          typeof raw.identity !== "string" || !/^[a-f0-9]{64}$/.test(raw.identity) ||
          !["unknown", "pending", "complete"].includes(raw.checkin) ||
          (raw.reward !== null && (typeof raw.reward !== "number" || !Number.isFinite(raw.reward) ||
                                  raw.reward < 0 || raw.reward > 1e12))) {
        throw failure("invalid_action_state");
      }
      if (raw.identity !== identity) throw failure("account_identity_mismatch");
      if (raw.date === date) value = raw;
    } catch (error) {
      if (error.code !== "ENOENT") {
        throw failure(error.reason === "account_identity_mismatch"
          ? "account_identity_mismatch" : "invalid_action_state");
      }
    }
  }

  function set(checkin, reward) {
    if (!["unknown", "pending", "complete"].includes(checkin) ||
        (reward !== undefined && reward !== null &&
         (typeof reward !== "number" || !Number.isFinite(reward) || reward < 0 || reward > 1e12))) {
      throw failure("invalid_action_state");
    }
    value = { ...value, checkin, reward: checkin === "unknown" ? null :
      (reward === undefined ? value.reward : reward) };
    if (!file) return;
    fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
    const temporary = file + ".tmp-" + crypto.randomUUID();
    let created = false;
    try {
      const fd = fs.openSync(temporary, "wx", 0o600);
      created = true;
      try {
        fs.writeFileSync(fd, JSON.stringify(value));
        fs.fsyncSync(fd);
      } finally {
        fs.closeSync(fd);
      }
      fs.renameSync(temporary, file);
      created = false;
      const dirfd = fs.openSync(directory, fs.constants.O_RDONLY | fs.constants.O_DIRECTORY);
      try {
        fs.fsyncSync(dirfd);
      } finally {
        fs.closeSync(dirfd);
      }
    } catch {
      throw failure("action_state_io_error");
    } finally {
      if (created) {
        try { fs.unlinkSync(temporary); }
        catch { throw failure("action_state_io_error"); }
      }
    }
  }
  return { get status() { return value.checkin; }, get reward() { return value.reward; }, set };
}

module.exports = { journal };
