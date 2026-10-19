"use strict";

const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const {isPrivateFile} = require("../../common/private_file.cjs");

function readPrivate(file, limit = 65536) {
  const fd = fs.openSync(file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0));
  try {
    const stat = fs.fstatSync(fd);
    if (!isPrivateFile(stat) || stat.size > limit)
      throw Error("private_file_invalid");
    const data = Buffer.alloc(limit + 1);
    const length = fs.readSync(fd, data, 0, data.length, 0);
    if (length > limit) throw Error("private_file_invalid");
    return JSON.parse(data.subarray(0, length).toString("utf8"));
  } finally {
    fs.closeSync(fd);
  }
}

function writePrivate(file, value) {
  const bytes = Buffer.from(JSON.stringify(value));
  if (bytes.length > 65536) throw Error("private_file_invalid");
  const directory = path.dirname(file);
  fs.mkdirSync(directory, {recursive: true, mode: 0o700});
  const temp = `${file}.tmp-${crypto.randomUUID()}`;
  try {
    const fd = fs.openSync(temp, "wx", 0o600);
    try {
      fs.writeFileSync(fd, bytes);
      fs.fsyncSync(fd);
    } finally {
      fs.closeSync(fd);
    }
    fs.renameSync(temp, file);
    const dirfd = fs.openSync(directory, "r");
    try { fs.fsyncSync(dirfd); } finally { fs.closeSync(dirfd); }
  } finally {
    if (fs.existsSync(temp)) fs.unlinkSync(temp);
  }
}

function binding(account, wechat) {
  return crypto.createHash("sha256")
    .update(JSON.stringify([account, wechat.url, wechat.account])).digest("hex");
}

function store(directory, owner, day) {
  const sessionFile = path.join(directory, "youzan-session.json");
  const actionFile = path.join(directory, "checkin-action.json");
  function read(file) {
    try { return readPrivate(file); }
    catch (error) { if (error.code === "ENOENT") return null; throw error; }
  }
  let saved = read(actionFile);
  if (saved && (saved.version !== 1 || typeof saved.owner !== "string" ||
      typeof saved.day !== "string" || typeof saved.activity !== "string" ||
      !["pending", "complete"].includes(saved.status))) throw Error("invalid_action_state");
  if (saved?.owner !== owner || saved?.day !== day) saved = null;
  return {
    action: () => saved,
    setAction(activity, status) {
      if (!/^[0-9]{1,20}$/.test(activity) || !["pending", "complete"].includes(status))
        throw Error("invalid_action_state");
      const next = {version: 1, owner, day, activity, status};
      writePrivate(actionFile, next);
      saved = next;
    },
    session() {
      const value = read(sessionFile);
      if (value && (value.version !== 1 || typeof value.owner !== "string" ||
          !value.session || typeof value.session !== "object" || Array.isArray(value.session)))
        throw Error("invalid_session_state");
      return value?.owner === owner ? value.session : null;
    },
    saveSession(session) { writePrivate(sessionFile, {version: 1, owner, session}); },
    clearSession() {
      try { fs.unlinkSync(sessionFile); }
      catch (error) { if (error.code !== "ENOENT") throw error; }
    },
  };
}

module.exports = {readPrivate, writePrivate, binding, store};
