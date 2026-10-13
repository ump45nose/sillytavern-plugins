"use strict";
// Explicit local-only browser integration. Empty state; all network is blocked.
const assert = require("node:assert/strict"), path = require("node:path");
const common = require("../platforms/rewards/browser_common.cjs"), trace = require("../platforms/rewards/telemetry.cjs");
const pacing = require("../platforms/rewards/interaction.cjs").create();
const {publish} = require("../common/result.cjs");
(async () => {
  await trace.withPhase("local_smoke", () => common.withBrowser(common.dependency(process.env.REWARDS_ROOT),
    {cookies: [], origins: []}, {}, async (context, page) => {
      await context.route("**/*", route => route.abort());
      await page.goto("about:blank", {waitUntil: "commit", timeout: 10000});
      await page.setContent(`<form><input id="sb_form_q"><button type="button" id="read">Read</button></form>
        <output id="events" data-keys="0" data-submits="0" data-clicks="0"></output>
        <main style="height:3000px">Local fixture</main><script>
        const stats = document.querySelector('#events').dataset;
        document.querySelector('input').addEventListener('keydown', () => stats.keys = Number(stats.keys) + 1);
        document.querySelector('form').addEventListener('submit', event => {event.preventDefault(); stats.submits = Number(stats.submits) + 1;});
        document.querySelector('#read').addEventListener('click', () => stats.clicks = Number(stats.clicks) + 1);
        </script>`);
      const box = page.locator("#sb_form_q"), text = "local fixture";
      await pacing.type(page, box, text);
      assert.equal(await box.inputValue(), text);
      const journal = require("../platforms/rewards/punchcards.cjs").journal(
        path.join(path.dirname(process.env.BENEFITS_RESULT_PATH), "smoke-journal.json"));
      await journal.mark("query_fixture", "attempted");
      trace.emit("journal.intent", {state: "attempted", offer_ref: trace.reference("query_fixture")});
      await trace.span("search.submit", {}, () => box.press("Enter"));
      await pacing.cooldown(page);
      await pacing.click(page, page.locator("#read"));
      await pacing.review(page);
      const events = await page.evaluate(() => Object.fromEntries(Object.entries(document.querySelector('#events').dataset)
        .map(([key,value]) => [key,Number(value)])));
      console.log("Local input events:", JSON.stringify(events));
      assert.equal(events.submits, 1); assert.equal(events.clicks, 1);
      assert.ok(events.keys >= [...text].length + 1);
      assert.equal(journal.has("query_fixture"), true);
    }));
  publish("ok", "local_interaction_smoke_complete", {local_smoke: "complete"});
  trace.close();
})().catch(error => {
  trace.failure("run", error, {capability: "local_smoke"});
  publish("failed", "local_interaction_smoke_failed", {local_smoke: "unknown"});
  trace.close();
});
