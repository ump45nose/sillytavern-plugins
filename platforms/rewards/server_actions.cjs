"use strict";
// Adapted protocol logic: TheNetsky/Microsoft-Rewards-Script v4.3.2, GPL-3.0-or-later.
// Full license and exact source commit are retained under vendor/rewards-parser.
// Version-bound Rewards Next server-action binding. See rewards v4.3.2 BrowserFunc.
// No upstream application import, parallel chunk fetch, or automatic POST retry.
const ORIGIN = "https://rewards.bing.com";
const trace = require("./telemetry.cjs");
function safePath(value) {
  if (
    typeof value !== "string" ||
    !/^\/(?:earn(?:\/quest\/[A-Za-z0-9_]{1,200})?|dashboard|_next\/static\/(?:chunks|immutable|media)\/[\w./()-]+\.js)$/.test(
      value,
    ) ||
    value.includes("..")
  )
    throw Error("invalid_rewards_path");
  return value;
}
async function request(
  page,
  route,
  { method = "GET", headers = {}, body } = {},
) {
  safePath(route);
  if (method === "POST" && !Object.keys(headers).some(key => key.toLowerCase() === "x-deployment-id")) {
    // React binds server actions to the current site deployment. Use the same
    // bounded page evidence as action discovery; never a saved deployment ID.
    const html = await require("./browser_common.cjs").boundedHtml(page);
    const deployment = require("./parser_loader.cjs").loadParser().buildId(html);
    if (typeof deployment !== "string" || !/^[A-Za-z0-9._-]{1,128}$/.test(deployment))
      throw Error("deployment_evidence_unavailable");
    headers = {...headers, "X-Deployment-Id": deployment};
  }
  return trace.span("server_action.request", {method, route: trace.route(ORIGIN + route)}, () => page.evaluate(
    async ({ url, method, headers, body }) => {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 20000);
      try {
        const response = await fetch(url, {
          method,
          headers,
          body,
          credentials: "same-origin",
          redirect: "error",
          signal: controller.signal,
        });
        const reader = response.body?.getReader();
        if (!reader) throw Error("empty_response");
        const decoder = new TextDecoder();
        let text = "",
          size = 0;
        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            size += value.byteLength;
            if (size > 2097152) throw Error("response_too_large");
            text += decoder.decode(value, { stream: true });
          }
          text += decoder.decode();
        } finally {
          await reader.cancel().catch(() => {});
        }
        return { status: response.status, text };
      } finally {
        clearTimeout(timer);
      }
    },
    { url: ORIGIN + route, method, headers, body },
  ));
}
function chunkPaths(text) {
  const found = new Set();
  for (const m of text.matchAll(
    /(?:\/_next\/)?(static\/(?:chunks|immutable|media)\/[\w\-./()]+?\.js)/g,
  ))
    found.add("/_next/" + m[1]);
  for (const m of text.matchAll(
    /static\/chunks\/"\s*\+\s*\w+\s*\+\s*"([-.])"\s*\+\s*\{([\s\S]*?)\}\s*\[/g,
  ))
    for (const e of m[2].matchAll(/(\d+)\s*:\s*"([a-f0-9]+)"/g))
      found.add(`/_next/static/chunks/${e[1]}${m[1]}${e[2]}.js`);
  for (const m of text.matchAll(/\b(\d{2,6}):"([a-f0-9]{12,})"/g)) {
    found.add(`/_next/static/chunks/${m[1]}-${m[2]}.js`);
    found.add(`/_next/static/chunks/${m[1]}.${m[2]}.js`);
  }
  return [...found].map(safePath);
}
async function discover(page, parser, html, read = request) {
  const queue = chunkPaths(html),
    seen = new Set(),
    ids = {};
  let bytes = 0;
  if (!queue.length) throw Error("action_chunks_missing");
  while (queue.length) {
    if (seen.size >= 60 || queue.length > 120)
      throw Error("action_discovery_limit");
    const path = queue.shift();
    if (seen.has(path)) continue;
    seen.add(path);
    const response = await read(page, path);
    if (response.status !== 200) continue;
    bytes += Buffer.byteLength(response.text);
    if (bytes > 12 * 1024 * 1024) throw Error("action_discovery_limit");
    // The source parser keeps only the last ID for a name. Parse individual
    // references too, so ambiguity inside one chunk cannot be hidden by it.
    const references =
      response.text.match(
        /(?:createServerReference\s*\)?\s*\(\s*"[a-f0-9]{40,64}"|registerServerReference\s*\)?\s*\([^,]+,\s*"[a-f0-9]{40,64}")[\s\S]{0,800}?\)/g,
      ) || [];
    const parsed = [
      parser.extractActionIds(response.text),
      ...references.map((reference) => parser.extractActionIds(reference)),
    ];
    for (const [name, id] of parsed.flatMap((value) =>
      Object.entries(value.byName),
    )) {
      if (!["reportActivity", "reportClaimAllPoints"].includes(name)) continue;
      if (!/^[a-f0-9]{40,64}$/i.test(id)) throw Error("invalid_action_id");
      if (ids[name] && ids[name] !== id) throw Error("ambiguous_action_id");
      ids[name] = id;
    }
    for (const path of chunkPaths(response.text))
      if (!seen.has(path) && !queue.includes(path)) queue.push(path);
  }
  return ids;
}
function validateSubmission(actionId, parent, child, timezoneOffset) {
  if (!/^[a-f0-9]{40,64}$/i.test(actionId)) throw Error("action_id_missing");
  safePath("/earn/quest/" + parent);
  if (
    typeof child?.hash !== "string" ||
    !child.hash ||
    child.hash.length > 8192 ||
    !/^[A-Za-z0-9_-]{1,200}$/.test(child.offerId) ||
    !Number.isInteger(timezoneOffset) ||
    Math.abs(timezoneOffset) > 840
  )
    throw Error("invalid_child_action");
}
async function submit(
  page,
  parser,
  actionId,
  parent,
  child,
  timezoneOffset,
  send = request,
) {
  validateSubmission(actionId, parent, child, timezoneOffset);
  return send(page, "/earn/quest/" + parent, {
    method: "POST",
    headers: {
      Accept: "text/x-component",
      "Content-Type": "text/plain;charset=UTF-8",
      "Next-Action": actionId,
      "Next-Router-State-Tree": parser.questRouterStateTree(parent),
    },
    body: JSON.stringify([
      child.hash,
      11,
      { offerid: child.offerId, isPromotional: "$undefined", timezoneOffset: String(timezoneOffset) },
    ]),
  });
}
module.exports = {
  safePath,
  request,
  chunkPaths,
  discover,
  validateSubmission,
  submit,
};
