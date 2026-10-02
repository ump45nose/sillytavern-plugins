"use strict";
// MIT: native adaptation of upstream/laowang-checkin/sign.cjs.
// Loaded only after the trusted host authorizes the current tncode challenge.
async function analyzePuzzle(input) {
  let data, width, height, markWidth;
  if (input) ({ data, width, height, markWidth } = input);
  else {
    const t = window.tncode;
    if (!t?._img_loaded) throw Error("puzzle_not_loaded");
    width = t._img_w;
    height = t._img_h;
    markWidth = t._mark_w;
    if (
      !Number.isInteger(width) ||
      width < 32 ||
      width > 640 ||
      !Number.isInteger(height) ||
      height < 32 ||
      height > 320 ||
      !Number.isInteger(markWidth) ||
      markWidth < 20 ||
      markWidth > 128 ||
      markWidth >= width
    )
      throw Error("puzzle_dimensions_invalid");
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height * 3;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(t._img, 0, 0);
    data = ctx.getImageData(0, 0, width, height * 3).data;
  }
  if (
    !Number.isInteger(width) ||
    width < 32 ||
    width > 640 ||
    !Number.isInteger(height) ||
    height < 32 ||
    height > 320 ||
    !Number.isInteger(markWidth) ||
    markWidth < 20 ||
    markWidth > 128 ||
    markWidth >= width ||
    data?.length !== width * height * 3 * 4
  )
    throw Error("puzzle_dimensions_invalid");
  const samples = [];
  for (let y = 8; y < height - 20; y += 2)
    for (let x = 8; x < markWidth - 8; x += 2) {
      const i = ((y + height) * width + x) * 4;
      if (data[i] + data[i + 1] + data[i + 2] > 220)
        samples.push({ x, y, r: data[i], g: data[i + 1], b: data[i + 2] });
    }
  if (samples.length < 50) throw Error("puzzle_samples_insufficient");
  const scores = [];
  for (let offset = 1; offset <= width - markWidth; offset++) {
    let error = 0;
    for (const q of samples) {
      const i = ((q.y + height * 2) * width + q.x + offset) * 4;
      error +=
        (data[i] - q.r) ** 2 +
        (data[i + 1] - q.g) ** 2 +
        (data[i + 2] - q.b) ** 2;
    }
    scores.push({ x: offset, error: error / samples.length });
  }
  scores.sort((a, b) => a.error - b.error);
  const best = scores[0],
    second = scores.find((q) => Math.abs(q.x - best.x) > 5);
  if (!second) throw Error("puzzle_difference_ambiguous");
  const ratio = second.error / Math.max(best.error, 1);
  if (!Number.isFinite(ratio) || ratio < 1.08)
    throw Error("puzzle_confidence_low");
  return { x: best.x, width, markWidth, samples: samples.length, ratio };
}
function accepted(text) {
  return typeof text === "string" && text.trim() === "_ok";
}
function checkURL(value) {
  try {
    const url = new URL(value);
    return (
      url.protocol === "https:" &&
      url.hostname === "laowang.vip" &&
      !url.username &&
      !url.password &&
      !url.port &&
      url.pathname === "/captcha/check.php"
    );
  } catch {
    return false;
  }
}
async function drag(page, match) {
  if (
    !Number.isInteger(match?.x) ||
    match.x < 1 ||
    match.x > match.width - match.markWidth
  )
    throw Error("puzzle_offset_invalid");
  const locator = page.locator(".slide_block");
  if ((await locator.count()) !== 1) throw Error("slider_ambiguous");
  const box = await locator.boundingBox();
  if (
    !box ||
    ![box.x, box.y, box.width, box.height].every(Number.isFinite) ||
    box.width <= 0 ||
    box.height <= 0
  )
    throw Error("slider_not_visible");
  const x = box.x + box.width / 2,
    y = box.y + box.height / 2;
  let down = false,
    response;
  try {
    await page.mouse.move(x, y);
    await page.mouse.down();
    down = true;
    for (let i = 1; i <= 28; i++) {
      const f = i / 28,
        pace = f < 0.5 ? 2 * f * f : 1 - Math.pow(-2 * f + 2, 2) / 2;
      await page.mouse.move(
        x + (match.x + 3) * pace,
        y + Math.sin(f * Math.PI) * 2 + (i % 5 === 0 ? 1 : 0),
      );
      await page.waitForTimeout(15);
    }
    for (let i = 1; i <= 4; i++) {
      await page.mouse.move(x + match.x + 3 - i * 0.75, y + (i % 2));
      await page.waitForTimeout(22);
    }
    // Install listener first; a missing response is uncertain, never retry drag.
    response = page
      .waitForResponse((r) => checkURL(r.url()), { timeout: 15000 })
      .catch(() => null);
    await page.mouse.up();
    down = false;
    const reply = await response;
    if (!reply)
      return { status: "unknown", reason: "captcha_response_uncertain" };
    const status = reply.status?.();
    if (!Number.isInteger(status) || status < 200 || status >= 300)
      return { status: "unknown", reason: "captcha_response_http_error" };
    // Bounded text: refuse an oversized declared body before fetching it.
    const declared = reply.headers?.()["content-length"];
    const length =
      typeof declared === "string" && /^\d{1,4}$/.test(declared)
        ? Number(declared)
        : null;
    if (length === null || length > 4096)
      return { status: "unknown", reason: "captcha_response_oversized" };
    const text = await reply.text();
    if (Buffer.byteLength(text) > 4096)
      return { status: "unknown", reason: "captcha_response_oversized" };
    return accepted(text)
      ? { status: "accepted" }
      : // The pinned source establishes only the success token. A negative token
        // has not been verified; HTML, errors and unknown bodies are not proof of
        // rejection and therefore must not authorize another drag.
        { status: "unknown", reason: "captcha_response_unrecognized" };
  } finally {
    if (down) await page.mouse.up().catch(() => {});
    if (response) await response;
  }
}
module.exports = { analyzePuzzle, accepted, checkURL, drag };
