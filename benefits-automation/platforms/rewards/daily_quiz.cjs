"use strict";
const crypto = require("node:crypto");

function filters(href) {
  let url;
  try { url = new URL(href); } catch { return null; }
  if (url.origin !== "https://www.bing.com" || url.pathname !== "/search" ||
      url.username || url.password || url.searchParams.getAll("filters").length !== 1)
    return null;
  const text = url.searchParams.get("filters");
  if (text.length > 4096) return null;
  const fields = {};
  for (const match of text.matchAll(/(?:^|\s)([A-Za-z]+):"([^"\r\n]*)"/g)) {
    if (Object.hasOwn(fields, match[1])) return null;
    fields[match[1]] = match[2];
  }
  return fields;
}
function destination(href, offerId) {
  const fields = filters(href);
  return Boolean(fields && fields.BTROID === offerId &&
    /^REWARDSQUIZ_[A-Za-z0-9_]+$/.test(fields.BTEPOKey || ""));
}
function answer(href, offerId) {
  const fields = filters(href);
  if (!fields || fields.BTOID !== offerId ||
      !/^REWARDSQUIZ_[A-Za-z0-9_]+$/.test(fields.BTQID || "") ||
      fields.BTEPOKey !== fields.BTQID || !/^\d$/.test(fields.BTQI || "") ||
      !/^\d$/.test(fields.BTCI || "")) return null;
  return {quiz: fields.BTQID, question: Number(fields.BTQI), choice: Number(fields.BTCI),
    key: "quiz_" + crypto.createHash("sha256")
      .update([offerId, fields.BTQID, fields.BTQI, fields.BTCI].join("\0")).digest("hex")};
}

async function finish(page, row, {journal, guard, pacing, confirmed = async () => false}) {
  if (!journal) throw Error("daily_quiz_journal_unavailable");
  for (let step = 0; step < 30; step++) {
    await guard(page);
    const cards = page.locator(".btom_card");
    if (await cards.count() !== 1) return;
    // The answer page retains a disabled summary and hides the next question
    // until its own Next button is clicked. Only visible choices are actionable.
    const next = cards.locator(".btom_next_btn button:visible");
    if (await next.count() === 1) {
      await pacing.pause(page, "action");
      await next.click({timeout: 15000});
    }
    const links = cards.locator('.btom_opts a[href]:visible:not([href^="javascript:"])');
    const raw = await links.evaluateAll(xs => xs.map(x => ({href: x.href})));
    if (!raw.length || raw.length > 5) return;
    const choices = raw.map(x => answer(x.href, row.offerId));
    if (choices.some(x => !x) || choices.some(x => x.quiz !== choices[0].quiz ||
        x.question !== choices[0].question) || new Set(choices.map(x => x.choice)).size !== choices.length)
      throw Error("daily_quiz_evidence_unavailable");
    const index = choices.findIndex(x => !journal.has(x.key));
    if (index < 0) return;
    await pacing.pause(page, "action");
    await guard(page);
    // Each question/choice is a distinct UI action. An uncertain click is never replayed.
    await journal.mark(choices[index].key, "attempted");
    await links.nth(index).click({timeout: 15000});
    await page.waitForLoadState("domcontentloaded", {timeout: 30000}).catch(() => {});
    await pacing.review(page, 4000);
    if (await confirmed()) return;
  }
}

module.exports = {destination, answer, finish};
