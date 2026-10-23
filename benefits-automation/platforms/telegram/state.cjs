"use strict";
// Per-account, per-day, per-bot action journal: idle -> sent -> confirmed.
// "sent" is recorded before the send click; after that only readback is
// allowed for the rest of the day. No message or reply text is stored.
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const {isPrivateFile} = require("../../common/private_file.cjs");
const {writeJson} = require("../../common/atomic_json.cjs");

const MAX_STATE = 65536;
const CONFIRMED = new Set(["checkin_confirmed", "already_checked_in"]);

class StateError extends Error {
  constructor(code) {
    super(code);
    this.code = code;
  }
}

const bad = () => { throw new StateError("journal_invalid"); };
const id = (value) => typeof value === "string" && /^[a-z0-9][a-z0-9_-]{0,31}$/.test(value);
const mid = (value) => value === null || (typeof value === "number" && Number.isFinite(value) && value >= 0);

function validEntry(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) bad();
  const keys = ["phase", "baseline", "button", "button_mid", "button_hash", "reason"];
  if (Object.keys(value).some((key) => !keys.includes(key)) ||
      !["idle", "sent", "confirmed"].includes(value.phase) ||
      !mid(value.baseline) || !["none", "clicked"].includes(value.button) ||
      !mid(value.button_mid) ||
      !(value.button_hash === null || /^[a-f0-9]{16}$/.test(value.button_hash)) ||
      !(value.reason === null || CONFIRMED.has(value.reason)) ||
      (value.phase === "confirmed") !== (value.reason !== null) ||
      (value.phase === "idle" && value.button !== "none")) bad();
  return value;
}

function fresh() {
  return {phase: "idle", baseline: null, button: "none", button_mid: null, button_hash: null, reason: null};
}

function read(file) {
  let fd;
  try {
    fd = fs.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
  } catch (error) {
    if (error.code === "ENOENT") return null;
    throw new StateError("journal_invalid");
  }
  try {
    const stat = fs.fstatSync(fd);
    if (!isPrivateFile(stat) || stat.size > MAX_STATE) bad();
    const buffer = Buffer.alloc(MAX_STATE + 1);
    const size = fs.readSync(fd, buffer, 0, buffer.length, 0);
    if (size > MAX_STATE) bad();
    return JSON.parse(buffer.subarray(0, size).toString("utf8"));
  } catch (error) {
    if (error instanceof StateError) throw error;
    bad();
  } finally {
    fs.closeSync(fd);
  }
}

function write(file, value) {
  try {
    fs.mkdirSync(path.dirname(file), {recursive: true, mode: 0o700});
    writeJson(file, value, MAX_STATE);
  } catch {
    throw new StateError("state_save_failed");
  }
}

const textHash = (text) =>
  crypto.createHash("sha256").update(String(text).normalize("NFKC")).digest("hex").slice(0, 16);

class Journal {
  constructor(directory, businessDate) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(businessDate || "")) throw new StateError("journal_invalid");
    this.file = path.join(directory, "telegram-journal.json");
    this.value = {schema_version: 1, business_date: businessDate, bots: {}};
    const saved = read(this.file);
    if (saved === null) return;
    if (!saved || typeof saved !== "object" || Array.isArray(saved) ||
        Object.keys(saved).sort().join(",") !== "bots,business_date,schema_version" ||
        saved.schema_version !== 1 || typeof saved.business_date !== "string" ||
        !/^\d{4}-\d{2}-\d{2}$/.test(saved.business_date) ||
        !saved.bots || typeof saved.bots !== "object" || Array.isArray(saved.bots) ||
        Object.keys(saved.bots).length > 64) bad();
    for (const [key, entry] of Object.entries(saved.bots)) {
      if (!id(key)) bad();
      validEntry(entry);
    }
    // A new business day starts with every bot idle again.
    if (saved.business_date === businessDate) this.value = saved;
  }
  get(botId) {
    return {...(this.value.bots[botId] || fresh())};
  }
  #set(botId, next) {
    const previous = this.value.bots[botId];
    this.value.bots[botId] = validEntry(next);
    try {
      write(this.file, this.value);
    } catch (error) {
      if (previous) this.value.bots[botId] = previous;
      else delete this.value.bots[botId];
      throw error;
    }
  }
  markSent(botId, baseline) {
    const entry = this.get(botId);
    if (entry.phase !== "idle") throw new StateError("journal_transition_invalid");
    this.#set(botId, {...entry, phase: "sent", baseline});
  }
  markButton(botId, buttonMid, text) {
    const entry = this.get(botId);
    if (entry.phase !== "sent" || entry.button !== "none")
      throw new StateError("journal_transition_invalid");
    this.#set(botId, {...entry, button: "clicked", button_mid: buttonMid, button_hash: textHash(text)});
  }
  markConfirmed(botId, reason) {
    const entry = this.get(botId);
    if (entry.phase !== "sent" || !CONFIRMED.has(reason))
      throw new StateError("journal_transition_invalid");
    this.#set(botId, {...entry, phase: "confirmed", reason});
  }
}

module.exports = {Journal, StateError, textHash};
