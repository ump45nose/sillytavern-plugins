"use strict";

const { execFileSync } = require("node:child_process");
const config = require("../config.json");

// Import in the browser host. Pass the result to its login form in memory.
function readLogin() {
  if (process.platform !== "darwin") {
    throw new Error("This login profile requires macOS Keychain.");
  }
  if (config.credential.backend !== "macos-keychain") {
    throw new Error("Unsupported credential backend.");
  }
  let password;
  try {
    password = execFileSync("/usr/bin/security", [
      "find-generic-password", "-a", config.account.email,
      "-s", config.credential.service, "-w"
    ], { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).replace(/\r?\n$/, "");
  } catch {
    throw new Error("Figma credential unavailable; check Keychain access.");
  }
  if (!password) throw new Error("Figma credential is empty.");
  return { email: config.account.email, password };
}

if (require.main === module) {
  process.stderr.write("Import readLogin() in the browser host; this script does not print credentials.\n");
  process.exitCode = 1;
}

module.exports = { readLogin };
