#!/usr/bin/env node
"use strict";

const fs = require("node:fs");

const operations = {
  tabs: ["GET", "/api/tabs", false],
  navigate: ["POST", "/api/navigate", true],
  snapshot: ["GET", "/api/snapshot", true],
  wait: ["POST", "/api/wait", true],
  click: ["POST", "/api/click", true],
  type: ["POST", "/api/type", true],
  key: ["POST", "/api/key", true],
  scroll: ["POST", "/api/scroll", true],
  eval: ["POST", "/api/eval", true],
  screenshot: ["GET", "/api/screenshot", true],
  network: ["GET", "/api/network", true],
  download: ["POST", "/api/download", true],
  downloads: ["GET", "/api/downloads", false],
};

async function callRelay(operation, input = {}, options = {}) {
  const spec = operations[operation];
  if (!spec) throw new Error(`Unknown operation: ${operation}`);
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    throw new Error("Input must be a JSON object.");
  }
  const [method, path, needsTab] = spec;
  if (needsTab && (input.tabId === undefined || input.tabId === null || input.tabId === "")) {
    throw new Error("Provide an explicit tabId from /api/tabs.");
  }
  const base = new URL(options.baseUrl || process.env.FIGMA_BROWSER_RELAY_URL || "http://127.0.0.1:18795");
  if (base.protocol !== "http:" || !["127.0.0.1", "localhost", "[::1]"].includes(base.hostname) || base.username || base.password || base.pathname !== "/" || base.search || base.hash) {
    throw new Error("Relay URL must be an HTTP loopback origin without credentials.");
  }
  const url = new URL(path, base);
  if (method === "GET") {
    for (const [key, value] of Object.entries(input)) {
      if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
    }
  }
  const request = {
    method,
    redirect: "error",
    signal: AbortSignal.timeout(operation === "wait" ? 25000 : 10000),
  };
  if (method === "POST") {
    request.headers = { "Content-Type": "application/json" };
    request.body = JSON.stringify(input);
  }
  // Never retry mutations: after an uncertain response, inspect the page first.
  const response = await (options.fetch || fetch)(url, request);
  if (!response.ok) throw new Error(`Relay HTTP ${response.status} for ${operation}.`);
  const result = await response.json();
  if (result.ok === false) throw new Error(`Relay rejected ${operation}; inspect the relay locally.`);
  return result;
}

if (require.main === module) {
  (async () => {
    if (process.argv.length !== 3) throw new Error("Usage: node browser-relay.cjs <operation> < input.json");
    const operation = process.argv[2];
    const input = ["tabs", "downloads"].includes(operation) ? {} : JSON.parse(fs.readFileSync(0, "utf8"));
    process.stdout.write(JSON.stringify(await callRelay(operation, input), null, 2) + "\n");
  })().catch(error => {
    process.stderr.write(error.message + "\n");
    process.exitCode = 1;
  });
}

module.exports = { callRelay };
