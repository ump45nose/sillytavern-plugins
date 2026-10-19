"use strict";

const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const {isPrivateFile} = require("../../common/private_file.cjs");

class OleError extends Error {
  constructor(code) {
    super(code);
    this.code = code;
  }
}

function text(value, limit = 8192) {
  return typeof value === "string" && value.length > 0 && value.length <= limit &&
    !/[\x00-\x1f\x7f]/.test(value);
}

function readPrivateJson(file) {
  let fd;
  try {
    fd = fs.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
    const stat = fs.fstatSync(fd);
    if (!isPrivateFile(stat) || stat.size > 16384)
      throw new OleError("private_file_invalid");
    const buffer = Buffer.alloc(16385);
    const size = fs.readSync(fd, buffer, 0, buffer.length, 0);
    if (size > 16384) throw new OleError("private_file_invalid");
    const value = JSON.parse(buffer.subarray(0, size).toString("utf8"));
    if (!value || typeof value !== "object" || Array.isArray(value))
      throw new OleError("private_file_invalid");
    return value;
  } catch (error) {
    if (error.code === "ENOENT" || error instanceof OleError) throw error;
    throw new OleError("private_file_invalid");
  } finally {
    if (fd !== undefined) fs.closeSync(fd);
  }
}

function atomicPrivateJson(file, value) {
  const encoded = JSON.stringify(value);
  if (Buffer.byteLength(encoded) > 16384) throw new OleError("state_save_failed");
  const directory = path.dirname(file);
  fs.mkdirSync(directory, {recursive: true, mode: 0o700});
  const temporary = file + ".tmp-" + crypto.randomUUID();
  let fd;
  try {
    fd = fs.openSync(temporary, "wx", 0o600);
    fs.writeFileSync(fd, encoded);
    fs.fsyncSync(fd);
    fs.closeSync(fd);
    fd = undefined;
    fs.renameSync(temporary, file);
    const parent = fs.openSync(directory, "r");
    try { fs.fsyncSync(parent); } finally { fs.closeSync(parent); }
  } catch {
    throw new OleError("state_save_failed");
  } finally {
    if (fd !== undefined) fs.closeSync(fd);
    if (fs.existsSync(temporary)) fs.unlinkSync(temporary);
  }
}

function configurationIdentity(wechat) {
  return crypto.createHash("sha256").update(wechat.url + "\0" + wechat.account).digest("hex");
}

function validSession(session) {
  return session && typeof session === "object" && !Array.isArray(session) &&
    text(session.session_id) && text(session.openid, 512) &&
    (session.shop_code === null || text(session.shop_code, 128));
}

class State {
  constructor(directory, account, date, identity) {
    if (!path.isAbsolute(directory)) throw new OleError("invalid_action_state");
    this.file = path.join(directory, "ole-state.json");
    this.date = date;
    this.value = {version: 1, account, identity, session: null, intent: null};
    let saved;
    try { saved = readPrivateJson(this.file); }
    catch (error) {
      if (error.code === "ENOENT") return;
      throw new OleError("invalid_action_state");
    }
    if (saved.version !== 1 || saved.account !== account ||
        (saved.session !== null && !validSession(saved.session)) ||
        (saved.intent !== null && (!saved.intent ||
          typeof saved.intent.date !== "string" ||
          !/^\d{4}-\d{2}-\d{2}$/.test(saved.intent.date) ||
          !["pending", "complete"].includes(saved.intent.status))))
      throw new OleError("invalid_action_state");
    if (saved.identity !== identity) throw new OleError("account_configuration_mismatch");
    this.value = saved;
  }
  get session() { return this.value.session ? {...this.value.session} : null; }
  get checkin() {
    return this.value.intent?.date === this.date ? this.value.intent.status : "unknown";
  }
  saveSession(session) {
    if (!validSession(session)) throw new OleError("merchant_login_response_invalid");
    this.value.session = {...session};
    atomicPrivateJson(this.file, this.value);
  }
  invalidateSession() {
    this.value.session = null;
    atomicPrivateJson(this.file, this.value);
  }
  record(status) {
    if (!["pending", "complete"].includes(status)) throw new OleError("invalid_action_state");
    if (this.checkin === status) return;
    this.value.intent = {date: this.date, status};
    atomicPrivateJson(this.file, this.value);
  }
}

module.exports = {OleError, State, text, readPrivateJson, atomicPrivateJson, configurationIdentity};
