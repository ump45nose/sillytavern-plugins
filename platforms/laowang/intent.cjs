"use strict";
const fs = require("node:fs");
const TRANSITIONS = {
  idle: ["request_attempted", "challenge_pending"],
  request_attempted: ["challenge_pending"],
  challenge_pending: ["challenge_pending", "captcha_attempted"],
  captcha_attempted: ["captcha_rejected", "captcha_accepted", "challenge_pending"],
  captcha_rejected: ["challenge_pending", "captcha_attempted"],
  captcha_accepted: ["submit_attempted"],
  submit_attempted: [],
};
function createIntent(file, businessDate) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(businessDate))
    throw Error("business_date_invalid");
  let value = { business_date: businessDate, phase: "idle", attempts: 0 };
  if (file && fs.existsSync(file)) {
    const fd = fs.openSync(file, "r");
    let text;
    try {
      const buffer = Buffer.alloc(4097),
        n = fs.readSync(fd, buffer, 0, 4097, 0);
      if (n > 4096) throw Error("intent_too_large");
      text = buffer.subarray(0, n).toString();
    } finally {
      fs.closeSync(fd);
    }
    const saved = JSON.parse(text);
    if (
      !saved ||
      Object.keys(saved).sort().join(",") !== "attempts,business_date,phase" ||
      typeof saved.business_date !== "string" ||
      !/^\d{4}-\d{2}-\d{2}$/.test(saved.business_date) ||
      typeof saved.phase !== "string" ||
      !Object.hasOwn(TRANSITIONS, saved.phase) ||
      !Number.isInteger(saved.attempts) ||
      saved.attempts < 0 ||
      saved.attempts > 2
    )
      throw Error("intent_invalid");
    if (saved.business_date === businessDate) value = saved;
  }
  return {
    get phase() {
      return value.phase;
    },
    get attempts() {
      return value.attempts;
    },
    get requestAttempted() {
      return value.phase !== "idle";
    },
    get submitAttempted() {
      return value.phase === "submit_attempted";
    },
    mark(next) {
      if (!TRANSITIONS[value.phase].includes(next))
        throw Error("intent_transition_invalid");
      if (next === "captcha_attempted") {
        if (value.attempts >= 2) throw Error("captcha_attempt_limit");
        value.attempts++;
      }
      value.phase = next;
      if (file) {
        const temp = file + ".tmp",
          fd = fs.openSync(temp, "w", 0o600);
        try {
          fs.writeFileSync(fd, JSON.stringify(value));
          fs.fsyncSync(fd);
        } finally {
          fs.closeSync(fd);
        }
        fs.renameSync(temp, file);
      }
    },
  };
}
module.exports = { createIntent };
