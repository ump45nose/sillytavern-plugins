"use strict";
// One private TELEGRAM_CONFIG keyed by --account. Only bot usernames, commands
// and reply patterns; no session, phone number or api_id belongs here.
const fs = require("node:fs");
const {isPrivateFile} = require("../../common/private_file.cjs");

const MAX_CONFIG = 65536;
const MAX_BOTS = 20;

class ConfigError extends Error {
  constructor(code) {
    super(code);
    this.code = code;
  }
}

const invalid = () => { throw new ConfigError("configuration_invalid"); };
const plain = (value) => value && typeof value === "object" && !Array.isArray(value);
const line = (value, limit) =>
  typeof value === "string" && value.trim() === value && value.length > 0 &&
  value.length <= limit && !/[\x00-\x1f\x7f]/.test(value);

function onlyKeys(value, allowed) {
  if (!plain(value) || Object.keys(value).some((key) => !allowed.includes(key))) invalid();
}

function patterns(value, required) {
  if (value === undefined && !required) return [];
  if (!Array.isArray(value) || value.length === 0 || value.length > 20 ||
      value.some((item) => !line(item, 200))) invalid();
  return value.slice();
}

function spacing(value, fallback) {
  if (value === undefined) return fallback;
  if (!Array.isArray(value) || value.length !== 2 ||
      value.some((n) => !Number.isInteger(n) || n < 0 || n > 120) || value[0] > value[1])
    invalid();
  return value.slice();
}

function bot(value) {
  onlyKeys(value, ["id", "username", "command", "success", "already", "failure",
    "button", "reply_timeout_seconds", "enabled", "points"]);
  // Telegram requires bot usernames to end in "bot"; this keeps a typo from
  // sending a command to a person.
  if (!(typeof value.id === "string" && /^[a-z0-9][a-z0-9_-]{0,31}$/.test(value.id)) ||
      !(typeof value.username === "string" && /^[A-Za-z][A-Za-z0-9_]{2,30}bot$/i.test(value.username)) ||
      !line(value.command, 256)) invalid();
  let button = null;
  if (value.button !== undefined) {
    onlyKeys(value.button, ["text"]);
    if (!line(value.button.text, 64)) invalid();
    button = {text: value.button.text};
  }
  let points = null;
  if (value.points !== undefined) {
    onlyKeys(value.points, ["pattern", "unit"]);
    if (!line(value.points.pattern, 200) || !["points", "coins", "beans"].includes(value.points.unit ?? "points"))
      invalid();
    // Matched against the same NFKC, case-folded text as the other patterns,
    // so a full-width colon in a reply reads as ":".
    const source = value.points.pattern.normalize("NFKC");
    let regex;
    try { regex = new RegExp(source, "iu"); } catch { invalid(); }
    // Exactly one capturing group: the number.
    if (new RegExp("(?:" + source + ")|", "u").exec("").length !== 2) invalid();
    points = {regex, unit: value.points.unit ?? "points"};
  }
  const timeout = value.reply_timeout_seconds ?? 30;
  if (!Number.isInteger(timeout) || timeout < 5 || timeout > 120) invalid();
  if (value.enabled !== undefined && typeof value.enabled !== "boolean") invalid();
  return {
    id: value.id,
    username: value.username,
    command: value.command,
    success: patterns(value.success, true),
    already: patterns(value.already, false),
    failure: patterns(value.failure, false),
    button,
    points,
    replyTimeoutMs: timeout * 1000,
    enabled: value.enabled !== false,
  };
}

function readPrivateJson(file) {
  let fd;
  try {
    fd = fs.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
    const stat = fs.fstatSync(fd);
    if (!isPrivateFile(stat) || stat.size > MAX_CONFIG)
      throw new ConfigError("private_file_invalid");
    const buffer = Buffer.alloc(MAX_CONFIG + 1);
    const size = fs.readSync(fd, buffer, 0, buffer.length, 0);
    if (size > MAX_CONFIG) throw new ConfigError("private_file_invalid");
    return JSON.parse(buffer.subarray(0, size).toString("utf8"));
  } catch (error) {
    if (error instanceof ConfigError) throw error;
    if (error.code === "ENOENT") throw new ConfigError("configuration_missing");
    if (error instanceof SyntaxError) throw new ConfigError("configuration_invalid");
    throw new ConfigError("private_file_invalid");
  } finally {
    if (fd !== undefined) fs.closeSync(fd);
  }
}

function parseConfig(value, account) {
  onlyKeys(value, ["spacing_seconds", "accounts"]);
  const fallback = spacing(value.spacing_seconds, [5, 20]);
  if (!plain(value.accounts)) invalid();
  const entry = value.accounts[account];
  if (!Object.hasOwn(value.accounts, account) || entry === undefined)
    throw new ConfigError("account_not_configured");
  onlyKeys(entry, ["spacing_seconds", "bots"]);
  if (!Array.isArray(entry.bots) || entry.bots.length === 0 || entry.bots.length > MAX_BOTS)
    invalid();
  const bots = entry.bots.map(bot);
  if (new Set(bots.map((item) => item.id)).size !== bots.length ||
      new Set(bots.map((item) => item.username.toLowerCase())).size !== bots.length) invalid();
  return {spacing: spacing(entry.spacing_seconds, fallback), bots};
}

function readConfig(file, account) {
  if (typeof file !== "string" || !file.startsWith("/"))
    throw new ConfigError("configuration_missing");
  return parseConfig(readPrivateJson(file), account);
}

module.exports = {ConfigError, readConfig, parseConfig, MAX_BOTS};
