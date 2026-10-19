"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const {isPrivateFile} = require("../common/private_file.cjs");
const {readPrivate} = require("../platforms/yingshijufeng/state.cjs");
const {readPrivateJson} = require("../platforms/ole/state.cjs");

test("merchant readers accept runtime group ACL modes and reject public files", (t) => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "benefits-private-"));
  t.after(() => fs.rmSync(directory, {recursive: true, force: true}));
  const file = path.join(directory, "session.json");
  fs.writeFileSync(file, '{"session":"synthetic"}', {mode: 0o600});
  for (const mode of [0o600, 0o660]) {
    fs.chmodSync(file, mode);
    for (const read of [readPrivate, readPrivateJson])
      assert.equal(read(file).session, "synthetic");
  }
  fs.chmodSync(file, 0o664);
  for (const read of [readPrivate, readPrivateJson]) assert.throws(() => read(file));
});

test("private file ownership and group must match the runtime identity", () => {
  const stat = {isFile: () => true, uid: process.getuid(), gid: process.getgid(), mode: 0o660};
  assert.equal(isPrivateFile(stat), true);
  for (const value of [
    {...stat, uid: stat.uid + 1}, {...stat, gid: stat.gid + 1},
    {...stat, mode: 0o670}, {...stat, mode: 0o760}, {...stat, isFile: () => false},
  ]) assert.equal(isPrivateFile(value), false);
});
