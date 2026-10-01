"use strict";
const crypto = require("node:crypto"),
  fs = require("node:fs"),
  path = require("node:path");
const TARGET = "https://laowang.vip/plugin.php";
const nonces = new WeakMap();
function safeTarget(page) {
  const value = typeof page?.url === "function" ? page.url() : page?.url;
  if (typeof value !== "string") throw Error("origin_unavailable");
  const url = new URL(value);
  if (
    url.protocol !== "https:" ||
    url.hostname !== "laowang.vip" ||
    url.username ||
    url.password ||
    url.port ||
    url.pathname !== "/plugin.php"
  )
    throw Error("unexpected_origin");
  return TARGET;
}
async function evidence(page) {
  safeTarget(page);
  // Observing a digest does not calculate a puzzle answer. Pixels stay in-browser.
  const digest = await page.evaluate(async () => {
    const t = window.tncode;
    if (!t?._img_loaded) return null;
    const w = t._img_w,
      h = t._img_h;
    if (
      !Number.isInteger(w) ||
      !Number.isInteger(h) ||
      w < 32 ||
      w > 640 ||
      h < 32 ||
      h > 320
    )
      throw Error("puzzle_dimensions_invalid");
    const c = document.createElement("canvas");
    c.width = w;
    c.height = h * 3;
    const ctx = c.getContext("2d");
    ctx.drawImage(t._img, 0, 0);
    const bytes = ctx.getImageData(0, 0, w, h * 3).data;
    return Array.from(
      new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
    )
      .map((x) => x.toString(16).padStart(2, "0"))
      .join("");
  });
  if (digest !== null && !/^[a-f0-9]{64}$/.test(digest))
    throw Error("invalid_challenge_evidence");
  if (!nonces.has(page)) nonces.set(page, crypto.randomUUID());
  return digest || nonces.get(page);
}
class PendingChallenge extends Error {
  constructor(observation) {
    super("human_required");
    this.observation = observation;
  }
}
async function observe(page, phase, readEvidence = evidence) {
  const target = safeTarget(page);
  const value = await readEvidence(page);
  return {
    kind: "captcha",
    capability: "tncode",
    phase,
    target,
    fingerprint: crypto
      .createHash("sha256")
      .update(JSON.stringify(["tncode-v1", phase, target, value]))
      .digest("hex"),
  };
}
function record(error) {
  if (!(error instanceof PendingChallenge) || !process.env.BENEFITS_RESULT_PATH)
    return;
  const signal = {
    schema_version: 1,
    run_id: process.env.BENEFITS_RUN_ID,
    platform: process.env.BENEFITS_PLATFORM,
    account: process.env.BENEFITS_ACCOUNT,
    ...error.observation,
    ttl_seconds: 300,
  };
  const file = path.join(
      path.dirname(process.env.BENEFITS_RESULT_PATH),
      "obstacle-signal.json",
    ),
    data = JSON.stringify(signal);
  if (Buffer.byteLength(data) > 8192) throw Error("signal_too_large");
  fs.writeFileSync(file + ".tmp", data, { mode: 0o600 });
  fs.renameSync(file + ".tmp", file);
}
async function solve(
  page,
  {
    authorize,
    readEvidence = evidence,
    loadSolver = () => require("./tncode.cjs"),
    maxAttempts = 2,
    beforeDrag = async () => {},
    onOutcome = async () => {},
  } = {},
) {
  if (!Number.isInteger(maxAttempts) || maxAttempts < 1 || maxAttempts > 2)
    throw Error("captcha_attempt_limit");
  async function allow(phase) {
    const current = await observe(page, phase, readEvidence);
    if (typeof authorize !== "function" || (await authorize(current)) !== null)
      throw new PendingChallenge(current);
    const fresh = await observe(page, phase, readEvidence);
    if (fresh.fingerprint !== current.fingerprint)
      throw new PendingChallenge(fresh);
    return fresh;
  }
  await allow("tncode_open"); // No solver load or CAPTCHA interaction without this.
  const solver = await loadSolver();
  await page.locator("#tncode").click({ timeout: 10000 });
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    try {
      await page.waitForFunction(
        () => window.tncode?._img_loaded === true,
        {},
        { timeout: 15000 },
      );
    } catch {
      if (attempt + 1 >= maxAttempts)
        return { status: "unknown", reason: "captcha_image_unavailable" };
      await allow("tncode_refresh");
      await page.locator(".tncode_refresh").click({ timeout: 10000 });
      continue;
    }
    const approved = await allow("tncode_drag");
    const match = await page.evaluate(solver.analyzePuzzle, null);
    const fresh = await observe(page, "tncode_drag", readEvidence);
    if (fresh.fingerprint !== approved.fingerprint)
      throw new PendingChallenge(fresh);
    await beforeDrag();
    const result = await solver.drag(page, match);
    await onOutcome(result.status);
    if (result.status === "accepted") return result;
    if (result.status !== "rejected" || attempt + 1 >= maxAttempts)
      return result;
    // Only explicit rejection can refresh/retry, and the new image is reauthorized.
    await allow("tncode_refresh");
    await page.locator(".tncode_refresh").click({ timeout: 10000 });
  }
  return { status: "unknown", reason: "captcha_attempt_limit" };
}
module.exports = {
  TARGET,
  safeTarget,
  evidence,
  observe,
  PendingChallenge,
  record,
  solve,
};
