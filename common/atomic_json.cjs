"use strict";
const fs = require("node:fs");
const path = require("node:path");
const {randomUUID} = require("node:crypto");

function writeJson(file, value, limit = 65536) {
  const encoded = JSON.stringify(value);
  if (typeof encoded !== "string" || Buffer.byteLength(encoded) > limit)
    throw Error("state_too_large");
  const temporary = file + ".tmp-" + randomUUID();
  let descriptor;
  try {
    descriptor = fs.openSync(temporary, "wx", 0o600);
    fs.writeFileSync(descriptor, encoded);
    fs.fsyncSync(descriptor);
    fs.closeSync(descriptor);
    descriptor = undefined;
    fs.renameSync(temporary, file);
    const parent = fs.openSync(path.dirname(file), "r");
    try { fs.fsyncSync(parent); } finally { fs.closeSync(parent); }
  } finally {
    if (descriptor !== undefined) fs.closeSync(descriptor);
    fs.rmSync(temporary, {force: true});
  }
}

module.exports = {writeJson};
