"use strict";
// Opt-in external build check. Blocks Node network entry points before imports.
const assert = require("node:assert/strict"),
  net = require("node:net");
net.Socket.prototype.connect = function () {
  throw Error("offline_contract_network_forbidden");
};
for (const name of [
  "spawn",
  "spawnSync",
  "exec",
  "execSync",
  "execFile",
  "execFileSync",
  "fork",
])
  require("node:child_process")[name] = () => {
    throw Error("offline_contract_subprocess_forbidden");
  };
global.fetch = async () => {
  throw Error("offline_contract_network_forbidden");
};
const root = process.argv[2];
if (!root) throw Error("Pass an external build directory");
const {
  loadParser,
  loadExternalParser,
} = require("../platforms/rewards/parser_loader.cjs");
const parser = loadExternalParser(root);
const offer = {
  offerId: "fixture",
  title: "Fixture",
  points: 5,
  isCompleted: true,
  isLocked: false,
};
const payload = JSON.stringify(offer);
const html =
  "<script>self.__next_f.push([1," + JSON.stringify(payload) + "])</script>";
const parsed = parser.snapshotPage(html);
assert.deepEqual(loadParser().snapshotPage(html), parsed);
assert.equal(parsed.offers[0].offerId, "fixture");
assert.equal(parsed.offers[0].isCompleted, true);
const exportsOnly = require(require("node:path").join(root, "dist/index.js"));
assert.equal(typeof exportsOnly.MicrosoftRewardsBot, "function");
assert.equal(typeof exportsOnly.executionContext.run, "function");
console.log(
  "Pinned build imports without autonomous main; local React parser fixture passed",
);
