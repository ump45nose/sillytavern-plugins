"use strict";
const fs = require("node:fs"),
  path = require("node:path"),
  crypto = require("node:crypto");
const { boundedJson } = require("./browser_common.cjs");
const COMMIT = "f61f4e982bbb435f37133bed0dc5b4c582ed1e73";
function instantiate(root, files) {
  const name = "dist/browser/ReactFunc.js",
    file = path.join(root, name);
  if (fs.statSync(file).size > 256 * 1024) throw Error("parser_too_large");
  const bytes = fs.readFileSync(file);
  if (crypto.createHash("sha256").update(bytes).digest("hex") !== files?.[name])
    throw Error("upstream_build_modified");
  const React = require(file).default;
  if (typeof React?.prototype?.snapshotPage !== "function")
    throw Error("parser_contract_incompatible");
  return new React({
    isMobile: false,
    currentAccountEmail: null,
    logger: { info() {}, warn() {}, debug() {}, error() {} },
  });
}
function loadParser() {
  const root = path.join(__dirname, "vendor/rewards-parser");
  const manifest = boundedJson(path.join(root, "PROVENANCE.json"), 65536);
  if (manifest.commit !== COMMIT || manifest.license !== "GPL-3.0-or-later")
    throw Error("parser_provenance_incompatible");
  return instantiate(root, manifest.files);
}
// Development verification only. Production always uses the exact bundled parser.
function loadExternalParser(root) {
  if (!root || !path.isAbsolute(root))
    throw Error("upstream_build_not_configured");
  const manifest = boundedJson(
    path.join(root, "benefits-build.json"),
    512 * 1024,
  );
  if (manifest.protocol !== 1 || manifest.source_commit !== COMMIT)
    throw Error("upstream_build_incompatible");
  return instantiate(root, manifest.files);
}
module.exports = { loadParser, loadExternalParser };
